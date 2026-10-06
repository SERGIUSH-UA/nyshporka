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
    if not boxed:
        return out
    spec = _spec(reg, name, title=f"Нотатник: {ref.shifra or ref.key}", case=ref.key,
                 script=script, origin="notebook")
    reg.save(spec)
    have = reg.marks(name)
    for n in boxed:
        assert n.line is not None and n.line.bbox is not None
        page = Path(n.page).stem
        idx = n.line.line_no - 1
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
    return out


# ── поширене іншими (лише власник проєкту) ───────────────────────────────────
def from_pool(rows: list[dict[str, Any]], fetch: Any, *,
              ws: Workspace | None = None) -> dict[str, Any]:
    """Набори `pool-<книга>` із записів пулу з кропами.

    `rows` — записи адмінського переліку пулу (id, uid, book, shifra, key,
    page, line, text, by); `fetch(uid) -> bytes` — JPEG кропа. Курсор (найбільший
    id) лягає в `set.json` кожного набору, тож повтор бере лише нове.
    """
    import io

    from PIL import Image

    reg = S.registry(ws)
    out: dict[str, Any] = {"rows": len(rows), "cut": 0, "marked": 0, "sets": {},
                           "failed": []}
    by_book: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_book.setdefault(str(r.get("book") or "unknown"), []).append(r)
    for book, items in sorted(by_book.items()):
        name = _safe(f"pool-{book}")
        sample = " ".join(str(r.get("text") or "") for r in items)
        spec = _spec(reg, name, title=f"Пул: {items[0].get('shifra') or book}",
                     case=str(items[0].get("key") or ""), script=script_of(sample),
                     origin="pool")
        have = reg.marks(name) if reg.exists(name) else {}
        n_new = 0
        for r in items:
            raw_line = r.get("line")
            line: dict[str, Any] = raw_line if isinstance(raw_line, dict) else {}
            try:
                idx = int(line.get("line_no") or 0) - 1
            except (TypeError, ValueError):
                idx = -1
            page = Path(str(r.get("page") or "")).stem
            if idx < 0 or not page or not S.safe_page(page):
                out["failed"].append({"uid": r.get("uid"), "why": "без сторінки чи рядка"})
                continue
            try:
                raw = fetch(str(r["uid"]))
                with Image.open(io.BytesIO(raw)) as im:
                    piece = im.convert("L")
            except Exception as exc:
                out["failed"].append({"uid": r.get("uid"), "why": str(exc)[:200]})
                continue
            d = reg.crops_of(spec) / page
            d.mkdir(parents=True, exist_ok=True)
            # Два дослідники звірили той самий рядок — лишається пізніший
            # (мітки append-only, останній запис на ключ виграє).
            piece.save(d / f"line_{idx:03d}.png")
            out["cut"] += 1
            if _mark(reg, name, page, idx, str(r.get("text") or ""),
                     f"pool:{r.get('by') or '?'}", have):
                out["marked"] += 1
                n_new += 1
            spec.cursor = max(spec.cursor, int(r.get("id") or 0))
        reg.save(spec)
        out["sets"][name] = {"rows": len(items), "new": n_new, "cursor": spec.cursor}
    return out


def pool_cursor(ws: Workspace | None = None) -> int:
    """Найбільший id пулу, уже взятий у будь-який набір `pool`."""
    reg = S.registry(ws)
    best = 0
    for name in reg.names(hidden=True):
        try:
            spec = reg.load(name)
        except S.SetError:
            continue
        if spec.origin == "pool":
            best = max(best, spec.cursor)
    return best
