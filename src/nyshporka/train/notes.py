"""📓→🧪 Навчальні пари з нотатника справи: кроп рядка ↔ звірене оком.

Записи `reading` нотатника — рядки, які рушій прочитав криво, а око звірило
зі сканом. Це найцінніший матеріал для дотрену: саме там модель і помиляється.
Тут вони стають набором (`data/train/sets/<набір>`) у тому самому форматі, що
й нарізка прогону: кроп `crops/<набір>/<сторінка>/line_NNN.png` + мітка в
`lines.jsonl`.

Два входи:

* `from_notes` — свої записи справи; кроп ріжеться з власного кадру за рамкою
  рушія (`search.textops.line_image`);
* `from_pool` — записи, поширені іншими в Супрягу, разом із кропом, який
  автор прислав сам. Лише для власника проєкту: поширити звірений рядок =
  погодитись, що власник візьме його в трен; іншим пул цих кропів не віддає.

🔴 Набори мають `origin` `notebook` / `pool`, і корпус бере їх окремим
джерелом `notes`, а не в `gt`: рядки відібрані там, де модель помилилась, тож
змішані з рівномірною розміткою вони спотворили б і вагу, і val.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace
from nyshporka.train import sets as S
from nyshporka.utils.atomic import read_json, write_json

_LATIN = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]")
_CYR = re.compile(r"[Ѐ-ӿ]")


class NotesError(RuntimeError):
    """Набір із нотатника не складається — з причиною для людини."""


def script_of(text: str) -> str:
    """Письмо рядка за літерами: латинка чи кирилиця (кирилиця при рівності)."""
    return "latin" if len(_LATIN.findall(text)) > len(_CYR.findall(text)) else "cyrillic"


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "-", name).strip("-.") or "x"


def _spec(reg: S.Registry, name: str, *, title: str, case: str, script: str,
          origin: str) -> S.SetSpec:
    if reg.exists(name):
        spec = reg.load(name)
        if spec.origin != origin:
            raise NotesError(f"набір «{name}» уже є, але походження в нього "
                             f"«{spec.origin}», а не «{origin}» — інше ім'я")
        return spec
    return S.SetSpec(name=name, title=title, case=case, script=script, role="train",
                     origin=origin)


def _meta_page(reg: S.Registry, spec: S.SetSpec, page: str, info: dict[str, Any]) -> None:
    path = reg.crops_of(spec) / S.CUT_META_FILE
    meta = read_json(path, default={})
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("version", 3)
    meta.setdefault("source_run", "")
    pages = meta.setdefault("pages", {})
    pages[page] = {**(pages.get(page) or {}), **info}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, meta)


def _mark(reg: S.Registry, name: str, page: str, idx: int, text: str, by: str,
          have: dict[tuple[str, int], dict[str, Any]]) -> bool:
    """Мітка лише нова або змінена: повторний прохід журналу не роздуває."""
    old = have.get((page, idx))
    if old is not None and str(old.get("text") or "") == text and old.get("status") == "ok":
        return False
    reg.append_mark(name, page, idx, text, "ok", by=by)
    return True


# ── свої записи ──────────────────────────────────────────────────────────────
def from_notes(case: str, *, ws: Workspace | None = None) -> dict[str, Any]:
    """Набір `notes-<справа>` зі своїх чинних звірених рядків справи.

    Знаменник у відповіді: скільки читань у нотатнику, скільки з рамкою,
    скільки вирізано, у скількох кадру на цій машині немає — щоб «набір на 3
    рядки» не читався як «у нотатнику 3 рядки».
    """
    from nyshporka import htr_store as HS
    from nyshporka.core import casekey
    from nyshporka.pagestore import notebook as NB
    from nyshporka.pagestore import store as PS
    from nyshporka.search import textops as T

    ref = PS.resolve_case(case)
    cf = PS.load_case(ref)
    reads = [n for n in NB.live(cf.notes, own=True) if n.kind == "reading"] if cf else []
    boxed = [n for n in reads if n.line is not None and n.line.bbox]
    ck = casekey.parse(ref.key)
    name = _safe(f"notes-{casekey.stem(ck) if ck else ref.key}")
    reg = S.registry(ws)
    scripts = [str((HS.load_meta(n.line.run) or {}).get("script") or "")
               for n in boxed if n.line is not None]
    script = max(set(scripts), key=scripts.count) if any(scripts) else (
        script_of(" ".join(n.text for n in boxed)) if boxed else "cyrillic")
    if script not in ("latin", "cyrillic"):
        script = script_of(" ".join(n.text for n in boxed))
    out: dict[str, Any] = {"case": ref.key, "shifra": ref.shifra, "set": name,
                           "readings": len(reads), "with_box": len(boxed), "cut": 0,
                           "marked": 0, "no_box": [n.uid for n in reads if n not in boxed],
                           "no_frame": []}
    if not boxed and not reg.exists(name):
        return out
    spec = _spec(reg, name, title=f"Нотатник: {ref.shifra or ref.key}", case=ref.key,
                 script=script, origin="notebook")
    reg.save(spec)
    have = reg.marks(name)
    live_keys: set[tuple[str, int]] = set()
    for n in boxed:
        assert n.line is not None and n.line.bbox is not None
        page = Path(n.page).stem
        idx = n.line.line_no - 1
        live_keys.add((page, idx))
        try:
            piece = T.line_image(n.line.run, n.page, n.line.bbox)
        except T.FrameError as exc:
            out["no_frame"].append({"uid": n.uid, "page": n.page, "why": str(exc)})
            continue
        d = reg.crops_of(spec) / page
        d.mkdir(parents=True, exist_ok=True)
        piece.save(d / f"line_{idx:03d}.png")
        out["cut"] += 1
        _meta_page(reg, spec, page, {"crop_source": "notebook", "run": n.line.run})
        if _mark(reg, name, page, idx, n.text, "notebook", have):
            out["marked"] += 1
    # 🔴 Відкликане чи перенесене читання мусить вийти з набору: інакше хибна
    # мітка, яку людина вже відкликала, лишалась у корпусі (перевірка 0.26.0).
    # Мітки лише дописуються, тож вихід — це `skip`, а не видалення.
    out["withdrawn"] = _withdraw(reg, name, have, live_keys, by="notebook")
    return out


def _withdraw(reg: S.Registry, name: str, have: dict[tuple[str, int], dict[str, Any]],
              live: set[tuple[str, int]], *, by: str) -> int:
    n = 0
    for (page, idx), rec in have.items():
        if (page, idx) in live or rec.get("status") == "skip":
            continue
        if not str(rec.get("by") or "").startswith(by):
            continue                         # чужу (ручну) розмітку набору не чіпаємо
        reg.append_mark(name, page, idx, str(rec.get("text") or ""), "skip", by=by)
        n += 1
    return n


# ── поширене іншими (лише власник проєкту) ───────────────────────────────────
#: Курсор пулу — один на простір: найбільший номер КРОПА, до якого все взято.
POOL_CURSOR_FILE = "pool_cursor.json"
#: Яка мітка набору прийшла з якого запису пулу — щоб відкликане в пулі вийшло.
POOL_UIDS_FILE = "pool_uids.json"


def _cursor_path(ws: Workspace | None) -> Path:
    from nyshporka.train import layout as L

    return L.train_root(ws) / POOL_CURSOR_FILE


def pool_cursor(ws: Workspace | None = None) -> int:
    """До якого номера кропа пулу все вже взято (0 — з початку)."""
    got = read_json(_cursor_path(ws), default={})
    return int(got.get("after") or 0) if isinstance(got, dict) else 0


def from_pool(rows: list[dict[str, Any]], fetch: Any, *, dead: list[str] | None = None,
              ws: Workspace | None = None) -> dict[str, Any]:
    """Набори `pool-<книга>` із записів пулу з кропами.

    `rows` — записи адмінського переліку пулу (cid — номер кропа, uid, book,
    shifra, key, page, line, text, by); `fetch(uid) -> bytes` — JPEG кропа;
    `dead` — uid записів, що в пулі вже не чинні (відкликані, сховані,
    замінені): їхні мітки виходять із наборів як `skip`.

    🔴 Курсор — номер КРОПА, а не запису, і не йде далі першого рядка, що не
    вдався. Доти курсор був найбільшим id запису по всіх наборах: збій на
    одному рядку чи кроп, що доїхав пізніше за запис, губились назавжди
    (перевірка 0.26.0).
    """
    import io

    from PIL import Image

    reg = S.registry(ws)
    out: dict[str, Any] = {"rows": len(rows), "cut": 0, "marked": 0, "sets": {},
                           "failed": [], "withdrawn": 0}
    by_book: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_book.setdefault(str(r.get("book") or "unknown"), []).append(r)
    done: list[int] = []
    failed_at: list[int] = []
    for book, items in sorted(by_book.items()):
        name = _safe(f"pool-{book}")
        sample = " ".join(str(r.get("text") or "") for r in items)
        spec = _spec(reg, name, title=f"Пул: {items[0].get('shifra') or book}",
                     case=str(items[0].get("key") or ""), script=script_of(sample),
                     origin="pool")
        reg.save(spec)
        have = reg.marks(name)
        uids = _uids(reg, name)
        n_new = 0
        for r in items:
            cid = int(r.get("cid") or r.get("id") or 0)
            raw_line = r.get("line")
            line: dict[str, Any] = raw_line if isinstance(raw_line, dict) else {}
            try:
                idx = int(line.get("line_no") or 0) - 1
            except (TypeError, ValueError):
                idx = -1
            page = Path(str(r.get("page") or "")).stem
            if idx < 0 or not page or not S.safe_page(page):
                out["failed"].append({"uid": r.get("uid"), "why": "без сторінки чи рядка"})
                done.append(cid)            # такий рядок і повтор не виправить
                continue
            try:
                raw = fetch(str(r["uid"]))
                with Image.open(io.BytesIO(raw)) as im:
                    piece = im.convert("L")
            except Exception as exc:
                out["failed"].append({"uid": r.get("uid"), "why": str(exc)[:200]})
                failed_at.append(cid)
                continue
            d = reg.crops_of(spec) / page
            d.mkdir(parents=True, exist_ok=True)
            # Два дослідники звірили той самий рядок — лишається пізніший
            # (мітки append-only, останній запис на ключ виграє).
            piece.save(d / f"line_{idx:03d}.png")
            out["cut"] += 1
            uids[str(r["uid"])] = [page, idx]
            if _mark(reg, name, page, idx, str(r.get("text") or ""),
                     f"pool:{r.get('by') or '?'}", have):
                out["marked"] += 1
                n_new += 1
            done.append(cid)
        _save_uids(reg, name, uids)
        out["sets"][name] = {"rows": len(items), "new": n_new}
    out["withdrawn"] = _withdraw_dead(reg, dead or [])
    before = pool_cursor(ws)
    after = (min(failed_at) - 1) if failed_at else max(done, default=before)
    after = max(before, after)              # назад курсор не йде ніколи
    path = _cursor_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"after": after})
    out["cursor"] = after
    return out


def _uids(reg: S.Registry, name: str) -> dict[str, list[Any]]:
    got = read_json(reg.set_dir(name) / POOL_UIDS_FILE, default={})
    return dict(got) if isinstance(got, dict) else {}


def _save_uids(reg: S.Registry, name: str, uids: dict[str, list[Any]]) -> None:
    write_json(reg.set_dir(name) / POOL_UIDS_FILE, uids)


def _withdraw_dead(reg: S.Registry, dead: list[str]) -> int:
    """Мітки записів, що в пулі вже не чинні, — `skip` у їхніх наборах."""
    if not dead:
        return 0
    gone = set(dead)
    n = 0
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError:
            continue
        if spec.origin != "pool":
            continue
        uids = _uids(reg, name)
        hit = [u for u in uids if u in gone]
        if not hit:
            continue
        marks = reg.marks(name)
        for u in hit:
            page, idx = str(uids[u][0]), int(uids[u][1])
            rec = marks.get((page, idx)) or {}
            if rec.get("status") != "skip":
                reg.append_mark(name, page, idx, str(rec.get("text") or ""), "skip",
                                by="pool")
                n += 1
            uids.pop(u)
        _save_uids(reg, name, uids)
    return n
