"""📨 Завдання арбітрам і зворотний імпорт: файли замість API.

Зводить голоси рушія не чужий сервіс, а сесія агента користувача та її
підагенти: завдання лягає файлом, арбітр ДИВИТЬСЯ на аркуш і кропи, пише
відповідь поруч, `import` забирає її в `drafts/merge/` і одразу проганяє
ворота. Зовнішній LLM-API у цьому каналі не викликається: платить той, чий
агент читає, і він бачить, за що.

Формат завдання (усе, що міняє читання, — ПЕРЕД рядками):

    <!-- ЗАВДАННЯ 1 з 3 · набір demo · рядків 212 · сторінки 0001, 0012 -->
    …шапка: куди писати відповідь і що запустити далі…
    Джерело: <domain>
    Правила: …
    ★ АРКУШІ З РАМКАМИ · ★ ЗГОРТКА ОДНОСТАЙНИХ · ★ СЛОВНИК СПРАВИ
    Поверни ЛИШЕ JSON …
    Рядки:
    0001:0
      A: …
      B: …
    0001:1
      = …

Відповідь — `<стем>.answer.json`: `{"0001:0": {"m": "текст", "c": "high|med|low"}}`.
Частковий файл законний: арбітр пише порціями, `import` бере, що є.

🔴 Завдання ріжеться ПО МЕЖАХ СТОРІНОК, і прапорця «по N рядків» немає.
Розірваний між двома арбітрами аркуш коштує двічі й дає два написання одного
прізвища — причт розколюється рівно по межі агента.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import gate as G
from nyshporka.train import sets as S
from nyshporka.utils.atomic import read_json, write_json

TASKS_DIR = "_tasks"
SHEETS_DIR = "_sheets"
VOICES = "ABCDEF"
DEFAULT_DOMAIN = "архівний рукопис XIX — початку XX ст., дореформена орфографія"

HEAD = """<!-- ЗАВДАННЯ {n} з {total} · набір {set} · рядків {rows} · сторінки {pages} -->
Відповідь — файл {stem}.answer.json поруч із цим. Пиши його порціями (кожні 25 рядків),
щоразу цілком тим, що вже зведено. Далі: {next_cmd}
─────────────────────────────────────────────────────────────────────────────
"""

#: Як зводиться рядок. `arbiter` — голоси сильні, арбітр обирає між ними й
#: дивиться кроп на власних назвах. `crop-read` — голоси слабкі (рука, якої
#: модель не знає): сліпий арбітр на скорописі XVII ст. дав CER 32% проти
#: палеографа, а читання кожного рядка по кропу з людським виданням поруч —
#: 693 рядки med (пак 6 Регента, 12.10.2026). Формат відповіді той самий.
PROCEDURES = ("arbiter", "crop-read")

RULES = """Ти зводиш {k} машинних транскрипцій ОДНОГО рукописного рядка в один найкращий варіант.

Джерело: {domain}

Правила:
1. Вихід має бути якнайближчим до того, що РЕАЛЬНО написано на аркуші. {voices} — незалежні зашумлені спостереження одного тексту.
2. Зберігай орфографію джерела як є, за письмом справи (кирилиця XIX ст.: ѣ, ъ у кінці слів, і, ѳ; латинка: ł, ń, ś, ż, ó). Не модернізуй і не перекладай на інше письмо.
3. НЕ вигадуй слів, яких не підказує жоден варіант. Якщо всі нерозбірливі — віддай правдоподібніший і постав низьку впевненість. Власна назва (прізвище, ім'я, топонім) береться лише з голосів і словника; підписант кожного запису — не формула.
4. Знання формуляра застосовуй, але не підставляй формулу там, де варіанти їй явно суперечать.
5. 🔴 МАРКЕРІВ РОЗБІЖНОСТІ НЕ СТАВ. Жодних ‹A|B›, дужок, слешів, знаків питання, приміток «або». Де голоси розходяться — обери найправдоподібніший варіант і постав "c":"low". Такі маркери одного разу протекли в тренувальний корпус і осіли в алфавіті моделі.
6. 🔴 РЯДОК — ЦЕ СМУЖКА, А НЕ РЕЧЕННЯ. Він може починатися і закінчуватися на півслові. НЕ добудовуй обірване слово до повної форми — лишай рівно стільки, скільки прочитали голоси.
7. 🔴🔴 НІЧОГО НЕ ВИКИДАЙ. Довжина відповіді ≈ як у найдовшого голосу. Якщо початок або середина нерозбірливі — все одно дай найкращий здогад і постав "c":"low". Пропуск гірший за помилку: спотворене слово знайдеться нечітким пошуком, відсутнє — ніколи.
8. Смужка без тексту (лінійка графи, згин, просвічування) → "m": "" — порожня мітка, а не найкоротший здогад.
9. Впевненість: "high" — практично певен, "med" — основа зрозуміла або власна назва не звірена на збільшенні, "low" — здогад. Збіг більшості голосів — доказ, але не механічне правило: моделі споріднені й помиляються схоже.
"""

CROP_RULES = """Ти читаєш КОЖЕН рядок сам, на його кропі. Голоси {voices} — машинні прочитання цього рядка ({k} шт.), рушій цієї руки знає погано. Рядки з позначкою джерела (див. ★ ДЖЕРЕЛА) — людський текст. Усе це підказки; мітка — те, що написано на кропі.

Джерело: {domain}

Правила:
1. Мітка — рівно те, що видно на смужці, в орфографії рукопису. Умовності правопису (як писати виносні, ъ/ь, скорочення) — з розділу контексту справи й з опису джерела; без них — як у рукописі.
2. Людське джерело дає ПРОЧИТАННЯ СЛІВ, але не межі й не написання: видання розкриває скорочення, нормалізує, ставить свою пунктуацію, а межа рядка в ньому підібрана автоматично і буває зсунута на слово-два (позначка ⚠ — дивись першими). Що з джерела не видно на кропі — у мітку НЕ вписуй; що видно на кропі, а в джерелі немає — вписуй.
3. Джерело розходиться з кропом (інший варіант акту, пропуск видавця, інше ім'я) — вирішує кроп. Імена й числа звіряй на збільшенні (`zoom`): ширина слова в пікселях на літеру проти сусідніх слів — об'єктивний арбітр.
4. Ініціал чи розчерк великої літери, що стоїть на полі ПОЗА кропом, у мітку не входить: мітка — те, що всередині смужки.
5. 🔴 РЯДОК — ЦЕ СМУЖКА, А НЕ РЕЧЕННЯ. Обірване слово лишай обірваним, навіть якщо джерело дає його повністю.
6. 🔴 МАРКЕРІВ РОЗБІЖНОСТІ НЕ СТАВ. Жодних ‹A|B›, дужок, слешів, знаків питання. Не впевнений — обери найправдоподібніше і постав "c":"low".
7. Рядок іншим письмом (латинка в кириличній книзі) чи нечитабельний без людського тексту — найкращий здогад і "c":"low". Смужка без тексту → "m": "".
8. Впевненість: "high" — кожне слово звірене на кропі й збігається з людським джерелом або очевидне; "med" — текст певний, окремі літери чи виносні не звірені на збільшенні; "low" — здогад.
"""

SOURCES_NOTE = """
★ ДЖЕРЕЛА — людський текст поруч із голосами. Позначка в рядку — ліворуч:
{items}
   🔴 Джерело — не голос рушія і не готова мітка: скільки б разів воно не
   збіглося з голосом, мітку вирішує смужка.
"""

PAGE_SOURCE_NOTE = """
★ ТЕКСТ ДЖЕРЕЛА ДО СТОРІНКИ {page} — {tag} («{title}»), ширше за рядки сторінки.
   Для контексту: звідки почався акт, хто сторони, де зсунулась межа рядка.
   «{text}»
"""

FOLD_NOTE = """
★ ЗГОРТКА ОДНОСТАЙНИХ. Рядок, позначений «=», — це місце, де ВСІ голоси дали
   однаковий текст. Переписуй його як є. 🔴 Але одностайність НЕ доводить
   правильність: моделі споріднені й помиляються схоже. Якщо в такому рядку
   стоїть ВЛАСНА НАЗВА — прізвище, ім'я, топонім, число, дата — він проходить
   очну звірку нарівні з рештою. Згортка економить твій вхід, а не твою увагу.
"""

SHEETS_NOTE = """
★ АРКУШІ З РАМКАМИ — `{path}`, сторінки: {pages}. Там зображення, де КОЖЕН
   рядок обведено рамкою з його номером (тим самим, що в id); великий аркуш
   порізаний сіткою на тайли `<скан>_t1.png`, `_t2.png`… із перекриттям. Дивись
   СПЕРШУ туди: аркуш дає формуляр, графи, підписантів і межі колонок одразу.
   Окремий кроп (`{crops}/<скан>/line_<NNN>.png`) бери лише на ВЛАСНИХ
   НАЗВАХ — сторінковий масштаб їх систематично псує.{gap}
"""

GAP_NOTE = """
   ⚠ Для сторінок {gap_pages} аркуша НЕМА — там працюй із кропами."""

GLOSSARY_NOTE = """
★ СЛОВНИК СПРАВИ — власні назви, звірені оком на аркуші:
   {items}
   Коли голоси розходяться на слові, схожому на словникове, бери форму зі
   словника. 🔴 Але словник НЕ перебиває голоси: якщо всі читають щось інше
   (інший корінь, інша кількість складів) — це ІНША назва, і словникову
   підставляти ЗАБОРОНЕНО, навіть якщо вона в цій справі найчастіша.
"""

HINTS_NOTE = """
★ СТОРОННЄ ПРОЧИТАННЯ СТОРІНКИ — що про цю сторінку прочитали люди поза рушієм
   (форум, власник документа, опис). Це КОНТЕКСТ, а не мітка:
{items}
   Користуйся ним, щоб упізнати власну назву, яку голоси калічать, і щоб знати,
   де на аркуші шукати. 🔴 Але: «переклад» і «нормалізовано» — НЕ текст рядка,
   орфографію й скорочення бери з голосів і аркуша; читання бувають хибні й
   суперечливі; слово, якого не видно на смужці, у рядок НЕ вписуй.
"""

HINT_KINDS = {"literal": "дослівно", "normalized": "нормалізовано",
              "translation": "переклад", "interpretation": "тлумачення"}
HINT_TRUST = {"published": "друковане наукове видання",
              "confirmed": "підтверджено власником документа",
              "agreed": "кілька людей згодні", "single": "одна відповідь",
              "disputed": "є суперечка"}


def source_items(spec: S.SetSpec) -> list[str]:
    """Опис кожного людського джерела — щоб агент знав, ЩО це і як ним брати."""
    out = []
    for h in spec.hint_sources:
        tags = [HINT_KINDS.get(h.kind, h.kind), HINT_TRUST.get(h.trust, h.trust),
                "по рядках" if h.level == "line" else "до сторінки"]
        head = f"   {h.tag} — «{h.title or h.id}»" + (f", {h.by}" if h.by else "")
        out.append(head + f" [{', '.join(t for t in tags if t)}]")
        if h.how:
            out.append(f"      як брати: {h.how}")
        out += [f"      ⚠ {c}" for c in h.caveats]
    return out


def page_source_blocks(reg: S.Registry, spec: S.SetSpec, pages: list[str]) -> list[str]:
    out = []
    for src in spec.hint_sources:
        if src.level != "page":
            continue
        data = reg.hint_data(spec, src)
        for pg in pages:
            v = data.get(pg)
            if v:
                out.append(PAGE_SOURCE_NOTE.format(page=pg, tag=src.tag,
                                                   title=src.title or src.id, text=v["text"]))
    return out


def hint_lines(spec: S.SetSpec, pages: list[str]) -> list[str]:
    out = []
    for pg in pages:
        for h in spec.page_hints.get(pg, []):
            tags = [HINT_KINDS.get(h.get("kind", ""), h.get("kind", "")),
                    HINT_TRUST.get(h.get("trust", ""), h.get("trust", ""))]
            part = f" ({h['part']})" if h.get("part") else ""
            tag = ", ".join(t for t in tags if t)
            out.append(f"   {pg}{part}: «{h.get('text', '')}»" + (f" [{tag}]" if tag else ""))
    return out


TAIL = """
Поверни ЛИШЕ JSON-об'єкт {{"<id>": {{"m": "<злитий рядок>", "c": "high|med|low"}}}} — рівно {n} ключів, ті самі id, у тому ж порядку.

Рядки:
{rows}"""

_PAIR_RE = re.compile(
    r'"([^"]+?)"\s*:\s*\{\s*"m"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"c"\s*:\s*"(\w+)"')
_ID_RE = re.compile(r"^([^:\s]+):(\d+)$")


class TaskError(ValueError):
    """Немає голосів, сторінок або відповідей."""


# ── рядки завдання ───────────────────────────────────────────────────────────
def page_rows(reg: S.Registry, spec: S.SetSpec, page: str,
              voices: list[S.Draft]) -> list[dict[str, Any]]:
    """Рядки сторінки як N паралельних прочитань; порожні смужки пропущено."""
    cols = [reg.draft_lines(spec, d, page) or [] for d in voices]
    hints = reg.line_hints(spec, page) if spec.hint_sources else {}
    rows: list[dict[str, Any]] = []
    for i in range(max((len(c) for c in cols), default=0)):
        vals = [(c[i].strip() if i < len(c) else "") for c in cols]
        h = [(src.tag, v["text"], v.get("doubt", "")) for src, v in hints.get(i, [])]
        # Рядок, якого рушії не прочитали, а людина прочитала, — не порожній.
        if all(len(v) < 3 for v in vals) and not h:
            continue
        rows.append({"id": f"{page}:{i}", "page": page, "idx": i, "v": vals, "h": h})
    return rows


def row_block(r: dict[str, Any], fold: bool) -> str:
    vs = r["v"]
    tail = [f"  {tag}: {text}" + (f"  ⚠ {doubt}" if doubt else "")
            for tag, text, doubt in r.get("h", [])]
    if fold and all(vs) and len(set(vs)) == 1:
        return "\n".join([f'{r["id"]}\n  = {vs[0]}', *tail])
    return "\n".join([r["id"]] + [f"  {VOICES[k]}: {v}" for k, v in enumerate(vs)] + tail)


def chunk_by_pages(rows: list[dict[str, Any]], pages_per_file: int) -> list[list[dict[str, Any]]]:
    by_page: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_page.setdefault(r["page"], []).append(r)
    pages = list(by_page)
    n = max(1, pages_per_file)
    return [[r for pg in pages[i:i + n] for r in by_page[pg]]
            for i in range(0, len(pages), n)]


def glossary_items(spec: S.SetSpec) -> list[str]:
    return [str(k) for k in spec.glossary if str(k).strip()]


# ── експорт ──────────────────────────────────────────────────────────────────
@dataclass
class ExportReport:
    set: str
    out: Path
    files: list[Path] = field(default_factory=list)
    rows: int = 0
    pages: list[str] = field(default_factory=list)
    dropped_blank: list[str] = field(default_factory=list)
    sheets: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def export_tasks(name: str, *, pages: list[str] | None = None, pages_per_file: int = 3,
                 only_missing: bool = False, drafts: list[str] | None = None,
                 out: Path | None = None, sheets: bool = True, fold: bool = True,
                 skip_blank: bool = True, hints: bool = True, ws: Workspace | None = None,
                 image_of: Any = None, procedure: str = "arbiter",
                 next_cmd: str = "") -> ExportReport:
    if procedure not in PROCEDURES:
        raise TaskError(f"процедура «{procedure}» невідома: {' | '.join(PROCEDURES)}")
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    voices = spec.voices()
    if drafts:
        want = [d.strip() for d in drafts if d.strip()]
        by_id = {d.id: d for d in voices}
        missing = [d for d in want if d not in by_id]
        if missing:
            raise TaskError(f"голосів немає в наборі: {', '.join(missing)}; "
                            f"є: {', '.join(by_id) or '—'}")
        voices = [by_id[d] for d in want]
    if len(voices) < 2:
        raise TaskError(f"набору «{name}» потрібні щонайменше ДВА голоси, є "
                        f"{len(voices)} — `nysh train voices`")
    have = reg.crop_pages(spec)
    all_pages = sorted(have)
    if pages:
        unknown = [p for p in pages if p not in have]
        if unknown:
            raise TaskError(f"у наборі немає сторінок: {', '.join(unknown)}")
        all_pages = [p for p in all_pages if p in set(pages)]
    rows = [r for pg in all_pages for r in page_rows(reg, spec, pg, voices)]
    rep = ExportReport(set=name, out=out or reg.set_dir(name) / TASKS_DIR)

    if only_missing:
        # 🔴 «Зведено» — це наявність conf у меті, а не непорожній текст: арбітр
        # має право лишити смужку порожньою (`"m": ""`), і такий рядок не має
        # тягтися в кожен наступний захід як «ще не зроблений».
        conf = reg.merge_conf(spec)
        rows = [r for r in rows if str(r["idx"]) not in conf.get(r["page"], {})]
    if skip_blank:
        keep = []
        for r in rows:
            png = reg.crop_path(spec, r["page"], r["idx"])
            if png is not None and G.ink_fraction(png) < G.INK_MIN:
                rep.dropped_blank.append(r["id"])
            else:
                keep.append(r)
        rows = keep
    if not rows:
        rep.warnings.append("нічого експортувати: усі рядки вже зведені або порожні")
        return rep

    rep.out.mkdir(parents=True, exist_ok=True)
    chunks = chunk_by_pages(rows, pages_per_file)
    rep.rows = len(rows)
    rep.pages = sorted({r["page"] for r in rows})
    sheet_dir: Path | None = None
    if sheets:
        from nyshporka.train import sheets as SH

        sheet_dir = reg.set_dir(name) / SHEETS_DIR
        try:
            got = SH.make_sheets(name, rep.pages, sheet_dir, ws=w, image_of=image_of)
            rep.sheets = {pg: [p.name for p in files] for pg, files in got.pages.items()}
            rep.warnings += got.warnings
        except SH.SheetError as exc:
            rep.warnings.append(f"аркуші не зроблено: {exc}")
    domain = spec.domain or DEFAULT_DOMAIN
    k = len(voices)
    rules = CROP_RULES if procedure == "crop-read" else RULES
    sources = source_items(spec) if hints else []
    for n, ch in enumerate(chunks, 1):
        stem = f"{name}_part{n:02d}"
        ch_pages = sorted({r["page"] for r in ch})
        txt = HEAD.format(n=n, total=len(chunks), set=name, rows=len(ch), stem=stem,
                          pages=", ".join(ch_pages),
                          next_cmd=next_cmd or f"nysh train import --set {name}")
        txt += rules.format(k=k, domain=domain, voices=", ".join(VOICES[:k]))
        if sources:
            txt += SOURCES_NOTE.format(items="\n".join(sources))
            txt += "".join(page_source_blocks(reg, spec, ch_pages))
        if rep.sheets:
            have_sh = [p for p in ch_pages if rep.sheets.get(p)]
            gap = [p for p in ch_pages if not rep.sheets.get(p)]
            if have_sh:
                txt += SHEETS_NOTE.format(
                    path=sheet_dir, pages=", ".join(have_sh), crops=reg.crops_of(spec),
                    gap=GAP_NOTE.format(gap_pages=", ".join(gap)) if gap else "")
        if fold:
            txt += FOLD_NOTE
        items = glossary_items(spec)
        if items:
            txt += GLOSSARY_NOTE.format(items="; ".join(items))
        page_hints = hint_lines(spec, ch_pages) if hints else []
        if page_hints:
            txt += HINTS_NOTE.format(items="\n".join(page_hints))
        txt += TAIL.format(n=len(ch), rows="\n".join(row_block(r, fold) for r in ch))
        f = rep.out / f"{stem}.txt"
        f.write_text(txt, encoding="utf-8")
        rep.files.append(f)
    return rep


# ── відповіді ────────────────────────────────────────────────────────────────
def parse_answer(raw: str) -> dict[str, dict[str, str]]:
    """JSON відповіді — з фолбеком на регекс для обірваного файлу.

    Строгого `json.loads` замало: обірвана на ліміті відповідь не закриває
    об'єкт, і суворий парсер дає НУЛЬ там, де зведено 59 рядків із 60.
    """
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*|\s*```$", "", s, flags=re.S)
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            got = json.loads(s[i:j + 1])
            if isinstance(got, dict):
                return {str(k): v for k, v in got.items() if isinstance(v, dict)}
        except json.JSONDecodeError:
            pass
    out: dict[str, dict[str, str]] = {}
    for k, m, c in _PAIR_RE.findall(s):
        try:
            out[k] = {"m": json.loads(f'"{m}"'), "c": c}
        except json.JSONDecodeError:
            out[k] = {"m": m, "c": c}
    return out


@dataclass
class ImportReport:
    set: str
    files: int = 0
    rows: int = 0
    pages: list[str] = field(default_factory=list)
    conf: dict[str, int] = field(default_factory=lambda: {"high": 0, "med": 0, "low": 0})
    rejected: list[str] = field(default_factory=list)
    gates: list[G.PageGate] = field(default_factory=list)
    splits: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def import_answers(name: str, *, tasks_dir: Path | None = None, keep_old: bool = False,
                   ws: Workspace | None = None) -> ImportReport:
    """Забрати `*.answer.json` у `drafts/merge/` і прогнати ворота."""
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    src = tasks_dir or reg.set_dir(name) / TASKS_DIR
    answers = sorted(src.glob("*.answer.json"))
    if not answers:
        raise TaskError(f"немає файлів *.answer.json у {src}")
    have = reg.crop_pages(spec)
    rep = ImportReport(set=name, files=len(answers))

    by_file: dict[str, dict[str, str]] = {}
    merged: dict[str, dict[str, str]] = {}
    for f in answers:
        got = parse_answer(f.read_text(encoding="utf-8", errors="replace"))
        ok_rows: dict[str, str] = {}
        for key, v in got.items():
            m = _ID_RE.match(key)
            if not m or m.group(1) not in have or "m" not in v:
                rep.rejected.append(f"{f.name}: {key}")
                continue
            merged[key] = v
            ok_rows[key] = str(v.get("m") or "")
        by_file[f.name] = ok_rows
        if len(got) and not ok_rows:
            rep.warnings.append(f"{f.name}: жоден ключ не належить набору")

    out = reg.merge_dir(spec)
    if keep_old and out.is_dir():
        old = out.parent / f"{S.MERGE_ID}_old"
        if old.exists():
            import shutil

            shutil.rmtree(old)
        out.rename(old)
    out.mkdir(parents=True, exist_ok=True)

    by_page: dict[str, dict[int, str]] = {}
    by_conf: dict[str, dict[int, str]] = {}
    for key, v in merged.items():
        pg, idx = key.rsplit(":", 1)
        i = int(idx)
        by_page.setdefault(pg, {})[i] = str(v["m"]).replace("\n", " ").strip()
        c = str(v.get("c", "")).strip().lower()
        by_conf.setdefault(pg, {})[i] = c if c in S.CONFS else "low"

    meta = read_json(out / S.META_FILE, default=None)
    if not isinstance(meta, dict):
        meta = {"version": 1, "model": "arbiters", "pages": {}}
    meta.setdefault("pages", {})
    meta["set"] = name
    voices = spec.voices()
    for pg, lines in by_page.items():
        f = out / f"{pg}.txt"
        # 🔴 Дописуємо В НАЯВНЕ, а не перезаписуємо: другий захід доливає те,
        # чого бракувало, і затирання коштувало б усього першого.
        cur = f.read_text(encoding="utf-8").splitlines() if f.is_file() else []
        n = max([*lines, len(cur) - 1]) + 1
        cur += [""] * (n - len(cur))
        for i, t in lines.items():
            cur[i] = t
            rep.rows += 1
        page_meta = meta["pages"].setdefault(pg, {})
        conf_all = {int(k): str(v) for k, v in (page_meta.get("conf") or {}).items()}
        conf_all.update(by_conf.get(pg, {}))
        vlines = [reg.draft_lines(spec, d, pg) or [] for d in voices]

        def _ink(i: int, _pg: str = pg) -> float | None:
            p = reg.crop_path(spec, _pg, i)
            return G.ink_fraction(p) if p is not None else None

        gate = G.gate_page(pg, cur, vlines, conf_all, ink_of=_ink,
                           crop_of=lambda i, _pg=pg: reg.crop_path(spec, _pg, i),
                           support=literal_support(reg, spec, pg))
        rep.gates.append(gate)
        f.write_text("\n".join(cur) + "\n", encoding="utf-8")
        page_meta["conf"] = {str(k): v for k, v in sorted(conf_all.items())}
        if gate.shift_blocks:
            page_meta["shift_blocks"] = [list(b) for b in gate.shift_blocks]
        rep.pages.append(pg)
        for i in by_conf.get(pg, {}):
            rep.conf[conf_all.get(i, "low")] = rep.conf.get(conf_all.get(i, "low"), 0) + 1
    meta["gate"] = {"demoted": sum(len(g.demoted) for g in rep.gates),
                    "marks_stripped": sum(len(g.marks_stripped) for g in rep.gates),
                    "shift_pages": [g.page for g in rep.gates if g.shift_blocks]}
    write_json(out / S.META_FILE, meta)
    if spec.merge() is None:
        spec.drafts.append(S.Draft(id=S.MERGE_ID, dir=f"{S.DRAFTS_DIR}/{S.MERGE_ID}"))
        reg.save(spec)
    rep.splits = G.spelling_splits(glossary_items(spec), by_file)
    for g in rep.gates:
        if g.marks_stripped:
            rep.warnings.append(f"{g.page}: маркери розбіжності зняті, рядки → low: "
                                f"{', '.join(map(str, g.marks_stripped[:10]))}")
        dense = {i for i, _ in g.dense}
        babble = [i for i in g.demoted if i not in dense]
        if babble:
            rep.warnings.append(f"{g.page}: понижено до low як белькіт/порожнє: "
                                f"{', '.join(map(str, babble[:10]))}"
                                f"{' …' if len(babble) > 10 else ''}")
        if g.dense:
            rep.warnings.append(f"{g.page}: понижено до low — мітка задовга для кропа: "
                                + ", ".join(f"{i} (×{r:.0f})" for i, r in g.dense[:10]))
        for a, b, off in g.shift_blocks:
            rep.warnings.append(f"{g.page}: рядки {a}–{b} зсунуті на {off:+d} відносно "
                                f"голосів — блок понижено до low, перевірити аркуш")
    for sp in rep.splits:
        rep.warnings.append(f"словникове «{sp['term']}» має різні написання в різних "
                            f"файлах: {', '.join(sp['forms'])}")
    if rep.rejected:
        rep.warnings.append(f"відкинуто {len(rep.rejected)} ключів не з набору "
                            f"(перші: {', '.join(rep.rejected[:4])})")
    return rep


def literal_support(reg: S.Registry, spec: S.SetSpec, page: str) -> dict[int, list[str]]:
    """Дослівний людський текст рядків сторінки — опора для воріт.

    Лише `kind=literal`: переклад чи нормалізоване прочитання з міткою не
    збігаються за побудовою, і «опора» на них нічого б не доводила.
    """
    return {i: [v["text"] for src, v in got if src.kind == "literal"]
            for i, got in reg.line_hints(spec, page).items()
            if any(src.kind == "literal" for src, _ in got)}


def suspects_of(name: str, ws: Workspace | None = None) -> list[dict[str, Any]]:
    """Рядки злиття на очі людині: розбіжність голосів або неопертість."""
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    m = spec.merge()
    if m is None:
        return []
    voices = spec.voices()
    out: list[dict[str, Any]] = []
    for pg in sorted(reg.crop_pages(spec)):
        merged = reg.draft_lines(spec, m, pg)
        if not merged:
            continue
        vlines = [reg.draft_lines(spec, d, pg) or [] for d in voices]
        conf = reg.merge_conf(spec).get(pg, {})
        dens = {}
        for i, text in enumerate(merged):
            png = reg.crop_path(spec, pg, i) if text.strip() else None
            d = G.label_density(text, png) if png is not None else None
            if d is not None:
                dens[i] = d
        ratios = G.density_ratios(dens)
        support = literal_support(reg, spec, pg)
        for i, text in enumerate(merged):
            if not text.strip() or conf.get(str(i)) == "low":
                continue
            vs = [v[i] if i < len(v) else "" for v in vlines]
            sig = G.signals(text, vs, None)
            why = ""
            if ratios.get(i, 0) >= G.DENSITY_SUSPECT:
                why = G.dense_why(ratios[i])
            elif support.get(i) and G.grounded(text, support[i]) >= G.GROUNDED_MIN:
                continue
            elif G.suspect(sig, text):
                why = "голоси розходяться"
            elif G.grounded(text, vs) < G.GROUNDED_MIN and len(text) >= 6:
                why = "не спирається на жоден голос"
            if why:
                out.append({"page": pg, "idx": i, "text": text, "voices": vs, "why": why})
    return out
