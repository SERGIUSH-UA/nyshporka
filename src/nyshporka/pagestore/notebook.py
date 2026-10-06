"""📓 Нотатник справи: секція `notes` у файлі сховища сторінок.

Що вже бачили на аркуші, лежить у `pages` того самого файла. Нотатник додає
три речі, для яких там місця не було:

* **рядок** — звірене оком читання з прив'язкою до рядка прогону й рамки
  (`reading`), а не абзац у `comment` сторінки;
* **справу загалом** — опис (`about`), помилку опису архіву (`catalog-error`),
  копію деінде (`copy`);
* **віддачу** — записи, позначені `share`, їдуть у пул окремо від тексту
  (`note push`), разом зі зведенням переглянутих сторінок без коментарів.

🔴 Це НЕ голос прогону. Око читає вибрані рядки, а не сторінку, і поставлене
поряд із Писарем і Дяком воно зіпсувало б знаменник: «прочитано 3 з 1189», а
нуль у ньому читався б як «людини немає». Тому `text index` нотатника не
бачить, а пошук показує його окремим блоком, який нуля не дає.

🔴 Особисте (`note`) — «тут жив мій дід», «це прабаба Миколи» — не їде ніколи;
решта їде лише з явною позначкою. Ворота (`share.gates.check_note`) ще раз
перевіряють текст на обох кінцях.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.pagestore.models import SHAREABLE_KINDS, CaseNote, NoteLine, NoteWas

if TYPE_CHECKING:
    from nyshporka.pagestore.models import CaseFile

#: Версія формату того, що їде в пул. Піднімається, коли змінюється СМИСЛ
#: поля, а не коли додається нове.
WIRE_VERSION = 1

#: Поля запису, що їдуть у пул. 🔴 Білий список: `author` (у нас там пишуть
#: «сесія, пошук Пухтицький»), `share` і `origin` — домашні.
WIRE_FIELDS = ("uid", "kind", "created", "reader", "model", "supersedes", "retracts",
               "text", "page", "line", "was", "confidence", "uncertain",
               "field", "archive_says", "actually", "other", "relation")

#: Поля сторінки, що їдуть у пул. `comment` і `agent` — ніколи: там нотатки
#: дослідження й ім'я сесії з тим, кого шукали.
PAGE_FIELDS = ("scan", "page_type", "status", "method", "years", "sheet", "noted")


def live(notes: list[CaseNote], *, own: bool | None = None) -> list[CaseNote]:
    """Чинні записи: без замінених і відкликаних, без самих відкликань.

    `own=True` — лише свої, `False` — лише чужі з пулу, `None` — усі.
    """
    dead = {n.supersedes for n in notes if n.supersedes} \
        | {n.retracts for n in notes if n.retracts}
    out = [n for n in notes if n.uid not in dead and not n.retracts]
    if own is not None:
        out = [n for n in out if (n.origin is None) == own]
    return out


def chain_root(notes: list[CaseNote], uid: str) -> str:
    """Перший запис ланцюжка замін — ним запис знає пул."""
    by = {n.uid: n for n in notes}
    seen: set[str] = set()
    cur = by.get(uid)
    while cur is not None and cur.supersedes and cur.supersedes not in seen:
        seen.add(cur.uid)
        nxt = by.get(cur.supersedes)
        if nxt is None:
            break
        cur = nxt
    return cur.uid if cur else uid


def readings_for(notes: list[CaseNote], page: str) -> list[CaseNote]:
    """Чинні звірені читання на сторінці — за стемом, бо імена різняться."""
    stem = Path(page).stem.casefold()
    return [n for n in live(notes) if n.kind == "reading"
            and Path(n.page).stem.casefold() == stem]


def wire_note(n: CaseNote) -> dict[str, Any]:
    """Запис у вигляді для пулу: білий список полів, без порожніх."""
    raw = n.model_dump(mode="json")
    out: dict[str, Any] = {}
    for k in WIRE_FIELDS:
        v = raw.get(k)
        if v in (None, "", [], {}):
            continue
        out[k] = v
    return out


def pages_digest(cf: CaseFile) -> list[dict[str, Any]]:
    """Переглянуті сторінки для пулу: що бачили, без коментарів.

    🔴 Прізвища й місця — лише з `status=full`, тобто з повним переліком, як
    і в описі справи (`share.opys.from_pagestore`): неповний перелік, виданий
    назовні, читався б як «на цьому аркуші більше нікого немає».
    """
    out: list[dict[str, Any]] = []
    for scan, p in sorted(cf.pages.items()):
        raw = p.model_dump(mode="json")
        row = {k: raw[k] for k in PAGE_FIELDS if raw.get(k) not in (None, "", [])}
        row["scan"] = scan
        if p.status == "full":
            if p.surnames:
                row["surnames"] = list(p.surnames)
            if p.places:
                row["places"] = list(p.places)
        out.append(row)
    return out


def outgoing(cf: CaseFile) -> list[dict[str, Any]]:
    """Що поїде в пул: свої чинні записи з `share` і відкликання відданого.

    🔴 Заміна посилається лише на те, що пул міг бачити. Ланцюжок «віддане →
    домашнє → знову віддане» в пулі виглядає як одна заміна: новий запис
    замінює найближчого ВІДДАНОГО предка, а домашня ланка між ними назовні не
    з'являється навіть ідентифікатором.

    Відкликання потрібне, коли віддане згодом замінили домашнім
    (`note unshare`) або відкликали: пул мусить прибрати свою копію, а змісту
    нового запису не дізнатись. Тому замість запису їде лише
    `{"retracts": <uid>}`. Пул, який такого запису не бачив, його пропускає.
    """
    own = [n for n in cf.notes if n.origin is None]
    by = {n.uid: n for n in own}

    def ancestors(n: CaseNote) -> list[CaseNote]:
        chain: list[CaseNote] = []
        cur = by.get(n.supersedes)
        while cur is not None and cur not in chain:
            chain.append(cur)
            cur = by.get(cur.supersedes)
        return chain

    out: list[dict[str, Any]] = []
    covered: set[str] = set()
    for n in live(own, own=True):
        if not (n.share and n.kind in SHAREABLE_KINDS):
            continue
        w = wire_note(n)
        w.pop("supersedes", None)
        chain = ancestors(n)
        covered |= {a.uid for a in chain}
        if anc := next((a.uid for a in chain if a.share), ""):
            w["supersedes"] = anc
        out.append(w)
    sent = {w["uid"] for w in out}
    for n in own:
        if n.share and n.uid not in sent and n.uid not in covered:
            out.append({"retracts": n.uid, "kind": n.kind})
    return out


# ── прив'язка рядка ──────────────────────────────────────────────────────────
def line_anchor(scope: str, page: str, line: int) -> dict[str, Any]:
    """Прогін, сторінка, текст рушія й рамка рядка — для `note read`.

    Ті самі сховище й правило, що в `text ctx`/`text crop`: перший прогін
    області, у якому є сторінка. Рамки немає (прогін без геометрії) — запис
    лишається текстовим, і це сказано в результаті, а не вгадано.
    """
    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    sc = T.scope_runs(scope)
    if not sc["rows"]:
        return {"error": f"у області «{scope}» немає жодного прогону"}
    try:
        conn = ST.connect(readonly=True)
    except RuntimeError as exc:
        return {"error": str(exc)}
    try:
        for r in sc["rows"]:
            run = str(r["name"])
            pg = T.find_page(conn, run, page)
            if pg is None:
                continue
            text = ST.page_text(run, pg, conn) or []
            if not 1 <= line <= len(text):
                return {"error": f"рядка {line} немає: у {run} · {pg} {len(text)} рядків"}
            pid = ST._page_id(conn, run, pg)
            box = None
            if pid is not None:
                got = {ln.no: ln for ln in ST._page_lines(conn, pid)}.get(line)
                if got is not None and got.box is not None:
                    box = [int(v) for v in got.box]
            return {"run": run, "page": pg, "line": line, "text": text[line - 1],
                    "bbox": box, "case_key": str(sc.get("key") or "")}
    finally:
        conn.close()
    return {"error": f"сторінки «{page}» немає в жодному прогоні області «{scope}»"}


# ── імпорт вільних тек ока ───────────────────────────────────────────────────
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_BASE_RE = re.compile(r"^#\s*коригує\s*:\s*(?:\S+\s+)?(\S+)\s*$", re.I)
_LINE_RE = re.compile(r"^\[\s*(?:рядок|ряд\.?|line)\s*(\d+)\s*\]\s*(.*)$", re.I)
_FIELD_RE = re.compile(r"^\s+(\w[\w\s]*?)\s*:\s*(.*)$")
_UNSURE_RE = re.compile(r"(\S+?)\(\?\)")


def _eye_uid(*parts: object) -> str:
    """Той самий блок тієї самої теки — той самий запис: повторний імпорт не дублює."""
    from hashlib import blake2b

    return blake2b("|".join(map(str, parts)).encode("utf-8"), digest_size=16).hexdigest()


def parse_eye_file(text: str, page: str, *, reader: str, model: str,
                   base_run: str = "") -> tuple[list[CaseNote], list[str]]:
    """Вільний файл теки `-claude_eye` → записи нотатника.

    Формат, який розпізнається (issue #24): шапка `# claude_eye — p0531 —
    звірено оком 2026-09-23`, рядок `# коригує: Писар <прогін>` і блоки
    `[рядок N] <текст>` з полями з відступом. Поле `примітка`/`note` стає
    окремим ОСОБИСТИМ записом (`note`): там висновки дослідження, і
    віддавати їх чи ні — рішення людини після перегляду.

    Повертає записи й перелік рядків, яких не розпізнано, — щоб людина
    бачила, що лишилось поза нотатником, а не вірила, що перенесено все.
    """
    date = ""
    run = base_run
    notes: list[CaseNote] = []
    skipped: list[str] = []
    cur: dict[str, Any] | None = None

    def flush() -> None:
        if cur is None:
            return
        line = NoteLine(run=run, line_no=cur["no"]) if run else None
        kw: dict[str, Any] = {"reader": reader, "model": model}
        if date:
            kw["created"] = f"{date}T00:00:00+00:00"
        notes.append(CaseNote(uid=_eye_uid("eye", run, page, cur["no"], cur["text"]),
                              kind="reading", page=page, line=line, text=cur["text"],
                              uncertain=_UNSURE_RE.findall(cur["text"]),
                              was=NoteWas(run=run, text=cur["was"]) if cur.get("was") else None,
                              **kw))
        extra = "\n".join(cur["extra"]).strip()
        if extra:
            notes.append(CaseNote(uid=_eye_uid("eye-note", run, page, cur["no"], extra),
                                  kind="note", page=page,
                                  text=f"[рядок {cur['no']}] {extra}", **kw))

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("#"):
            if m := _DATE_RE.search(line):
                date = date or m.group(1)
            if m := _BASE_RE.match(line):
                run = run or m.group(1)
            continue
        if m := _LINE_RE.match(line):
            flush()
            cur = {"no": int(m.group(1)), "text": m.group(2).strip(), "extra": []}
            continue
        if cur is not None and (m := _FIELD_RE.match(raw)):
            key = m.group(1).strip().casefold()
            if key in ("було", "was", "писар", "рушій"):
                cur["was"] = m.group(2).strip()
            else:
                cur["extra"].append(f"{m.group(1).strip()}: {m.group(2).strip()}")
            continue
        if cur is not None and raw[:1].isspace():
            cur["extra"].append(line.strip())
            continue
        skipped.append(line)
    flush()
    return notes, skipped


def import_eye_dir(folder: Path, *, reader: str, model: str = "",
                   base_run: str = "") -> dict[str, Any]:
    """Усі `*.txt` теки ока → записи; ім'я файла — сторінка базового прогону."""
    if not base_run:
        name = folder.name
        for suffix in ("-claude_eye", "-codex_eye", "-human_eye", "-eye"):
            if name.endswith(suffix):
                base_run = name[: -len(suffix)]
                break
    notes: list[CaseNote] = []
    skipped: dict[str, list[str]] = {}
    files = sorted(folder.glob("*.txt"))
    for f in files:
        got, left = parse_eye_file(f.read_text(encoding="utf-8", errors="replace"),
                                   f.stem, reader=reader, model=model, base_run=base_run)
        notes += got
        if left:
            skipped[f.name] = left
    return {"notes": notes, "skipped": skipped, "files": len(files), "base_run": base_run}
