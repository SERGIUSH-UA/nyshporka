r"""Бібліотека архівних справ — єдиний каталог «що яка справа за що відповідає».

Об'єднує два джерела в один перелік `CaseEntry`:
  1. **Канон** — усі `data/canonical/sources/S_*.md` (найкращі людські назви: `title`
     + `coverage`); канон лінкує на теку сканів через `raw_path`, тож справи роду
     приєднуються автоматично.
  2. **Диск** — усі теки сканів у `data/raw/**` (+ junction на T:); ті, що не мають
     канонічного джерела, отримують назву через fallback-ланцюг за кодом справи:
       `_source.json` → `_crawl/cases.tsv` (archium) → `wikisource_meta.json`
       → `f315_opys_merged.tsv` → код.

⚠ Теки `data/raw/dahmo_archium/**` (junction на `D:\архів\dahmo_archium`)
іменуються **id файлу на сайті** archium, а не шифрою: `f794_spr_16732` = ф.794 оп.1
спр.**2**. Резолвити ЛИШЕ через `_crawl/cases.tsv` (`_archium_parse`).

Опис (назва/роки/тип) — СТАТИЧНИЙ, перебудовується на вимогу у `data/derived/case_library.json`.
Статус скану (скановано/готово/не скачано) — рахується НАЖИВО у консолі
(`nyshporka.console.helpers._case_status`), тут НЕ зберігається.

Ключ справи для дедупу/join — трійка `(repo, fond, spr)` (опис часто відсутній в імені
теки, тож у ключ не входить; зберігається окремо як метадані).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import workspace
from nyshporka.models import Source
from nyshporka.storage.files import read_source

_WS = workspace()
ROOT = _WS.root
SOURCES_DIR = _WS.canonical / "sources"
RAW_DIR = _WS.raw
LIBRARY_PATH = _WS.derived / "case_library.json"
SCAN_TARGETS_PATH = _WS.spotter / "scan_targets.json"

# fallback-джерела назв для фонду 315 (опис 1)
_WIKISOURCE_META = RAW_DIR / "dahmo_315" / "wikisource_meta.json"
_OPYS_MERGED = RAW_DIR / "dahmo_315" / "f315_opys_merged.tsv"
_MASTER_INDEX = RAW_DIR / "dahmo_315" / "f315_MASTER_INDEX.tsv"
_KLIROVI_INDEX = RAW_DIR / "dahmo_315" / "klirovi_index.tsv"
_DAVO_F904_CATALOG = RAW_DIR / "davo" / "CATALOG_F904_OP24_OLHOPIL.md"
_DAHMO_226_CATALOG = RAW_DIR / "dahmo_226" / "CATALOG.md"
# каталог усього оцифрованого ДАХмО (9022 справи) — краулер archium.dahmo.gov.ua
_ARCHIUM_CASES = RAW_DIR / "dahmo_archium" / "_crawl" / "cases.tsv"
_ARCHIUM_SLUG = "dahmo_archium"

_IMG_EXT = {".jpg", ".jpeg", ".png"}

# Скільки PDF у теці ще варто розкривати заради лічильника сторінок. Справа-PDF це
# один-два файли; десятки PDF в одній теці — вже не справа, а збірка чи корпус, і
# точне число сторінок там нічого не вирішує.
_PDF_PROBE_LIMIT = 50

# Теки data/raw/<slug>, що НЕ містять архівних справ (описи фондів, OCR-корпуси,
# періодика за роками) — навіть якщо їх імена схожі на шифри.
_SKIP_SLUGS = {"davo_opysy", "dahmo_319_f65_opisy", "bev_pdh", "kev_pdh",
               "khev_pdh", "eev_pdh", "_console_pages"}

# repo-slug (тека data/raw/<slug>) / архів-код → людська абревіатура
_REPO_LABEL = {
    "DAHMO": "ДАХмО", "CDIAK": "ЦДІАК", "DAVO": "ДАВО", "DAVIO": "ДАВіО",
    "ANRM": "ANRM", "BNRM": "BNRM", "DACHVO": "ДАЧвО",
    # ДАОО додано 2026-08-12 разом із першими справами: метрики Фараонівки
    # (Аккерманський пов., Кишинівська єпархія) — ф.897/900/904/1009.
    "DAOO": "ДАОО",
}
# опис за замовчуванням для фондів, де скановані справи майже завжди одного опису
# (ім'я теки spr-XXXX опис не несе). Довідково — canonical парсить опис з repository_ref.
_DEFAULT_OPYS = {("DAHMO", "315"): "1", ("CDIAK", "224"): "1", ("CDIAK", "127"): "1076"}
# фонди, де опис ОБОВ'ЯЗКОВО входить у ключ справи (див. `_mk_key`): нумерація справ
# починається з одиниці в кожному описі, тож без опису різні книги злипаються.
# ANRM ф.211 (Кишинівська духовна консисторія): оп.1/3 — метрики, оп.5 — метрики
# сільських церков, оп.11 — сповідні розписи; усі мають справи з малими номерами.
_OPYS_IN_KEY: set[tuple[str, str]] = {("ANRM", "211")}
# тип запису (normalized) → людський підпис для UI
_RTYPE_LABEL = {
    "birth": "народження", "marriage": "шлюби", "death": "смерті",
    "confession": "сповідні", "revision": "ревізькі", "gazette": "єпарх. відомості",
    "clergy_list": "клірові", "finding_aid": "опис фонду", "other": "інше",
}


@dataclass
class CaseEntry:
    """Один запис бібліотеки справ."""

    key: str                       # "DAHMO/315/8433" — дедуп-ключ (repo/fond/spr)
    repo: str | None = None        # "DAHMO"
    repo_label: str | None = None  # "ДАХмО"
    fond: str | None = None        # "315"
    opys: str | None = None        # "1" (може бути None якщо невідомо)
    spr: str | None = None         # "8433"
    shifra: str = ""               # "ДАХмО 315-1-8433"
    title: str = ""                # людська назва
    year_from: int | None = None
    year_to: int | None = None
    doc_type: str = ""             # людський тип ("метричні", "Н+Ш+С", …)
    record_types: list[str] = field(default_factory=list)  # normalized (birth/…)
    rtypes_inferred: bool = False  # типи вгадані з тексту назви, не з канону
    rtypes_final: bool = False     # типи вирішені остаточно (не довгадувати з тексту)
    place: str = ""                # село/парафія/повіт для показу
    parish: str | None = None
    path: str | None = None        # rel-шлях входу для прогону (тека або .pdf)
    # Інші теки диска з тим самим ключем (справа розірвана між двома плівками,
    # `_reshoot`, вирізка по другому селу). Раніше друга тека мовчки зникала —
    # запис лишався один, і «на диску немає» було неправдою.
    extra_paths: list[str] = field(default_factory=list)
    raw_path: str | None = None    # канонічний raw_path як є
    source_id: str | None = None   # S_… якщо є канонічне джерело
    on_disk: bool = False
    frames: int | None = None      # к-сть кадрів/PDF на диску (build-time hint)
    desc_source: str = "code"      # canonical|source_json|wikisource|opys_tsv|code
    # письмо справи: latin|cyrillic|mixed — від якого залежить РУШІЙ HTR (Скриба
    # чи Писар). Порожнє = не зафіксовано, консоль вгадає з жанру/років
    # (`routers.htr._guess_script`) і чесно позначить це як здогад.
    script: str = ""
    langs: list[str] = field(default_factory=list)  # ["ru","pl","la"] — як у джерелі
    curated: bool = False          # присутня в scan_targets.json (§9)
    group: str | None = None       # черга (з scan_targets)
    why: str | None = None         # навіщо (з scan_targets)
    tag: str = ""                  # ключ для матчингу review-тек


# ── парсинг кодів справ у ключ ────────────────────────────────────────────────

_ID_RE = re.compile(r"^S_([A-Z]+)_F(\d+)(?:_OP(\d+))?_D([0-9A-Za-z]+)$")
_SHIFRA_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)")  # 315-1-8433
_SLUG_FOND_RE = re.compile(r"^([a-z]+)_(\d+)$")                  # dahmo_315
_SPR_DIR_RE = re.compile(r"spr[-_]?0*(\w+?)$", re.IGNORECASE)    # spr-8433 / spr-199a
# опис у назві теки: `op2-spr-148` = опис 2 (інакше візьметься дефолт і збреше)
_OP_PREFIX_RE = re.compile(r"(?:^|[-_])op(\d+)", re.IGNORECASE)
# davo-стиль тек: 010904-24-00114  → fond 904, опис 24, справа 114
# ⚠️ Літерний суфікс обов'язковий у групі справи: ДАВіО має пари 84 і 84а (ф.474 —
# дві РІЗНІ книги за 1833). Без нього обидві дають ключ DAVO/474/84 і одна зникає з каталогу.
_DAVO_DIR_RE = re.compile(r"^0*1?0*(\d{3,4})[-_](\d+)[-_]0*(\d+[а-яa-z]?)", re.IGNORECASE)
_FSUB_RE = re.compile(r"f(\d+)(?:[_-]op(\d+))?", re.IGNORECASE)  # f904_op24
# archium-теки: `f794_spr_16732` / `spr_16732` — число це **file_id сайту**, а НЕ номер
# справи (16732 = «Справа 2» ф.794). Справжню шифру дає лише cases.tsv.
_ARCHIUM_DIR_RE = re.compile(r"^(?:f\d+[_-])?spr[_-](\d+)$", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d+)")


def _norm_spr(s: str | None) -> str | None:
    """Номер справи/фонду/опису без провідних нулів: `00114`→`114`, `080`→`80`.

    Приймає і число: сайдкари пишуть `"inv": 1` так само часто, як `"inv": "1"`,
    а `.strip()` на int валив збірку ВСІЄЇ бібліотеки через один такий файл.
    """
    if s is None or s == "":
        return None
    return str(s).strip().lower().lstrip("0") or "0"


def _mk_key(repo: str | None, fond: str | None, spr: str | None,
            opys: str | None = None) -> str | None:
    """Дедуп-ключ справи. Опис входить у ключ ЛИШЕ для фондів з `_OPYS_IN_KEY`.

    Трійка repo/fond/spr унікальна не всюди: у ANRM ф.211 описи 1/3/5/11 нумерують
    справи кожен з одиниці, тож «211-1-140» (с. Парково) і «211-3-140» (Кишинівський
    собор) — РІЗНІ книги, які без опису злипаються в один ключ і один файл
    `data/pages/ANRM/211-140.json`. Розширювати правило на всі фонди не можна:
    там опис часто невідомий, і ключ поплив би між збірками.
    Збірки (`spr` на `@`) опису не мають ніколи — інакше відв'яжуться оверрайди.
    """
    if not (repo and fond and spr):
        return None
    if opys and not str(spr).startswith("@") and (repo, str(fond)) in _OPYS_IN_KEY:
        return f"{repo}/{fond}-{opys}/{spr}"
    return f"{repo}/{fond}/{spr}"


def split_fond_opys(fond_part: str) -> tuple[str, str | None]:
    """`211-3` → («211», «3»); `315` → («315», None). Зворотне до `_mk_key`."""
    if "-" in fond_part:
        f, _, o = fond_part.partition("-")
        return f, (o or None)
    return fond_part, None


def candidate_keys(parsed: tuple[str, str, str | None, str] | None) -> list[str]:
    """Ключі-кандидати для пошуку в бібліотеці: з описом і без.

    Опис у розібраному коді буває невідомий (ім'я теки його не несе), а запис
    бібліотеки для `_OPYS_IN_KEY`-фонду вже з описом — і навпаки. Шукати треба
    обома формами, інакше та сама справа двоїться на диску й у каталозі.
    """
    if not parsed:
        return []
    repo, fond, opys, spr = parsed
    out = [_mk_key(repo, fond, spr, opys), _mk_key(repo, fond, spr)]
    return [k for i, k in enumerate(out) if k and k not in out[:i]]


@lru_cache(maxsize=1)
def _archium_cases() -> dict[str, dict[str, Any]]:
    """file_id → рядок `_crawl/cases.tsv` (fond_no, inv_label, case_no, date, …).

    Ім'я теки скану (`f794_spr_16732`) несе **id файлу на сайті**, а не архівну шифру,
    тож без цього індексу бібліотека показувала б «ДАХмО 794-16732» замість «794-1-2».
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        with _ARCHIUM_CASES.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                fid = (row.get("file_id") or "").strip()
                if fid:
                    out[fid] = row
    except Exception:
        pass
    return out


def _archium_parse(leaf: str) -> tuple[str, str, str | None, str] | None:
    """Тека скану archium → (DAHMO, fond, opys, spr) через cases.tsv. None якщо не в ньому."""
    m = _ARCHIUM_DIR_RE.match(leaf.strip())
    if not m:
        return None
    row = _archium_cases().get(m.group(1))
    if not row:
        return None
    fond = _norm_spr(row.get("fond_no"))
    spr_m = _NUM_RE.search(row.get("case_no") or "")      # «Справа 2» → 2
    opys_m = _NUM_RE.search(row.get("inv_label") or "")   # «Опис 1»   → 1
    if not (fond and spr_m):
        return None
    return "DAHMO", fond, (opys_m.group(1) if opys_m else None), str(_norm_spr(spr_m.group(1)))


def parse_source_id(source_id: str) -> tuple[str, str, str | None, str] | None:
    """`S_<АРХІВ>_F<фонд>_D<справа>` → (repo, fond, opys|None, spr). None якщо не справа."""
    m = _ID_RE.match(source_id.strip())
    if not m:
        return None
    repo, fond, opys, spr = m.groups()
    return repo, fond, opys, str(_norm_spr(spr))


def parse_case_path(rel: str) -> tuple[str, str, str | None, str] | None:
    """Rel-шлях теки/файлу справи → (repo, fond, opys|None, spr) або None.

    Розбирає конвенцію імен: `data/raw/<slug>/…/spr-XXXX`, davo-стиль
    `.../010904-24-00114`, або `f904_op24/<num>`. slug `dahmo_315` → repo/fond.
    """
    parts = [p for p in re.split(r"[\\/]+", rel.strip()) if p]
    if "raw" in parts:
        parts = parts[parts.index("raw") + 1:]
    if not parts:
        return None
    slug = parts[0]
    if slug in _SKIP_SLUGS:
        return None
    if slug == _ARCHIUM_SLUG:
        return _archium_parse(parts[-1])
    repo = fond = opys = None
    m = _SLUG_FOND_RE.match(slug)
    if m:
        repo, fond = m.group(1).upper(), _norm_spr(m.group(2))
    elif slug.split("_")[0].isalpha():
        repo = slug.split("_")[0].upper()
    last = parts[-1]
    stem = re.sub(r"\.(pdf|jpe?g|png)$", "", last, flags=re.IGNORECASE)
    # davo-стиль повного шифру у назві теки
    md = _DAVO_DIR_RE.match(stem)
    if md and (repo in (None, "DAVO") or slug == "davo"):
        fond2, opys2, spr2 = md.groups()
        return (repo or "DAVO", str(fond or _norm_spr(fond2)),
                _norm_spr(opys2), str(_norm_spr(spr2)))
    # опис із проміжної теки f904_op24
    for seg in parts[1:-1]:
        fm = _FSUB_RE.fullmatch(seg)
        if fm:
            fond = fond or _norm_spr(fm.group(1))
            opys = opys or _norm_spr(fm.group(2))
    # опис у самій назві теки (`op2-spr-148`) — має пріоритет над дефолтом фонду
    mop = _OP_PREFIX_RE.search(stem)
    if mop:
        opys = opys or _norm_spr(mop.group(1))
    # номер справи
    spr = None
    ms = _SPR_DIR_RE.search(stem)
    if ms:
        spr = _norm_spr(ms.group(1))
    elif stem.isdigit():
        spr = _norm_spr(stem)
    else:
        msh = _SHIFRA_RE.search(stem)
        if msh:
            fond = fond or _norm_spr(msh.group(1))
            opys = opys or _norm_spr(msh.group(2))
            spr = _norm_spr(msh.group(3))
    if not (repo and fond and spr):
        # Ім'я теки коду справи не несе (`harvest` fsfiles зве теки за плівкою й
        # кадрами: `2102930_0309-0313`). Шифра лежить у сайдкарі, писаному руками.
        return _sidecar_case(rel)
    return repo, fond, opys, spr


@lru_cache(maxsize=4096)
def _sidecar_village(rel: str | None) -> str:
    """Село з `_source.json` теки-вирізки (`harvest` по покажчику плівки)."""
    if not rel:
        return ""
    f = ROOT / rel / "_source.json"
    if not f.is_file():
        return ""
    try:
        return (json.loads(f.read_text(encoding="utf-8")).get("village") or "").strip()
    except Exception:
        return ""


@lru_cache(maxsize=4096)
def _sidecar_case(rel: str) -> tuple[str, str, str | None, str] | None:
    """(repo, fond, opys, spr) з `_source.json`/`meta.json` теки — коли ім'я мовчить."""
    d = ROOT / rel
    if not d.is_dir():
        return None
    for name in ("_source.json", "meta.json"):
        f = d / name
        if not f.exists():
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        shifra = (m.get("shifra") or "").strip()
        msh = _SHIFRA_RE.search(shifra)
        if not msh:
            # `fsfiles_download.py harvest` пише шифру не як «211-3-140», а словами
            # з покажчика дзеркала: `"delo": "Ф. 211 Оп. 3 Д. 140"`. Без цієї гілки
            # усі плівки ANRM лишались «без шифри» — сховище сторінок їх не брало.
            got = _parse_delo(m.get("delo"))
            if got is None:
                got = _case_from_sheet_index(m, d)
            if got is None:
                continue
            fond, opys, spr = got
            repo = _repo_from_rel(rel)
            if repo and fond and spr:
                return repo, fond, opys, spr
            continue
        repo = (re.split(r"[\s\d]", shifra, maxsplit=1)[0] or "").upper()
        if not repo.isalpha():
            repo = _repo_from_rel(rel)
        fond, opys, spr = (_norm_spr(g) or "" for g in msh.groups())
        opys = _norm_spr(m.get("inv") or m.get("opys") or "") or opys
        if repo and fond and spr:
            return repo, str(fond), str(opys) if opys else None, str(spr)
    return None


# «Ф. 211 Оп. 3 Д. 140» / «ф.211 оп.3 спр.140» / «F. 211 Inv. 3 D. 140»
_DELO_RE = re.compile(
    r"[ФFФ]\.?\s*(\d+)\s*[.,;]?\s*(?:Оп|Inv|О)\w*\.?\s*(\d+)\s*[.,;]?\s*"
    r"(?:Д|Спр|D|Dosar)\w*\.?\s*(\d+[а-яa-z]?)", re.IGNORECASE)


def _parse_delo(value: Any) -> tuple[str, str | None, str] | None:
    """«Ф. 211 Оп. 3 Д. 140» → («211», «3», «140»). None якщо не розпізнано.

    Кілька шифр в одному полі (плівка накриває суміжні справи) — беремо ПЕРШУ:
    решта потрапить у свої теки, бо `harvest` ріже плівку по діапазонах кадрів.
    """
    if not value or not isinstance(value, str):
        return None
    m = _DELO_RE.search(value)
    if not m:
        return None
    fond, opys, spr = (_norm_spr(g) for g in m.groups())
    if not (fond and spr):
        return None
    return str(fond), (str(opys) if opys else None), str(spr)


# «Л. 156-741 - Кишинёв» / «Л. 742-… - Кишинёв» / «Л. 6-155»
_LISTY_RE = re.compile(r"Л\.\s*(\d+)\s*[-–]\s*(\d+|…|\.\.\.)?", re.IGNORECASE)
# частка кадрів теки, яку має накрити справа, щоб теку можна було назвати ЇЇ шифрою
_SHEET_DOMINANCE = 0.80


def _case_from_sheet_index(m: dict[str, Any], d: Path) -> tuple[str, str | None, str] | None:
    """Справа теки за ПЕРЕТИНОМ кадрів на диску з діапазонами «Л.» покажчика.

    Плівка сама по собі справою не є: `2086507_1864` несе спр.242-249, а
    `2256454_full` — спр.273/274/275. Брати першу-ліпшу з `sheet_index` означає
    назвати теку чужою шифрою — рівно та тиха підміна, від якої лікує
    `_OPYS_IN_KEY`. Тому справа приймається, лише якщо накриває ≥80% кадрів
    (вирізка `harvest` під одну справу), інакше тека лишається плівкою без шифри.

    «Л.» у покажчику дзеркала = номер КАДРУ плівки, не фоліація аркуша — саме
    тому діапазон можна зіставляти з іменами файлів.
    """
    items = [x for x in (m.get("sheet_index") or []) if isinstance(x, dict)]
    # Окреме ім'я для відфільтрованого: перезапис `cases` собою ж ховає, що
    # після фільтра шифра вже точно є — і читач, і перевіряч бачать старий тип.
    parsed = [(_parse_delo(x.get("delo")), x.get("listy") or "") for x in items]
    cases = [(c, ly) for c, ly in parsed if c is not None]
    if not cases:
        return None
    uniq = {c for c, _ in cases}
    if len(uniq) == 1:
        return next(iter(uniq))

    frames = sorted(int(p.stem) for p in d.glob("*.jpg") if p.stem.isdigit())
    if not frames:
        return None
    # межі справ: заповнюємо відкриті хвости («Л. 742-…») початком наступної
    spans: list[tuple[tuple[Any, ...], int, int]] = []
    for i, (case, listy) in enumerate(cases):
        ml = _LISTY_RE.search(listy)
        if not ml:
            continue
        lo = int(ml.group(1))
        hi_raw = ml.group(2)
        if hi_raw and hi_raw.isdigit():
            hi = int(hi_raw)
        else:
            nxt = next((_LISTY_RE.search(ly) for _, ly in cases[i+1:] if _LISTY_RE.search(ly)),
                       None)
            hi = int(nxt.group(1)) - 1 if nxt else frames[-1]
        spans.append((case, lo, hi))
    if not spans:
        return None
    best, best_n = None, 0
    for case, lo, hi in spans:
        n = sum(1 for f in frames if lo <= f <= hi)
        if n > best_n:
            best, best_n = case, n
    if best and best_n >= _SHEET_DOMINANCE * len(frames):
        return best
    return None


def _repo_from_rel(rel: str) -> str:
    """`data/raw/anrm/villages/…` → «ANRM» (slug теки одразу під data/raw)."""
    parts = [p for p in re.split(r"[\\/]+", rel.strip()) if p]
    if "raw" in parts:
        parts = parts[parts.index("raw") + 1:]
    if not parts:
        return ""
    return (parts[0].split("_")[0] or "").upper()


def parse_case_code(value: str) -> tuple[str, str, str | None, str] | None:
    """Універсальний резолвер: source-id / rel-шлях / шифра → (repo, fond, opys, spr)."""
    v = value.strip()
    if v.startswith("S_"):
        return parse_source_id(v)
    return parse_case_path(v)


# ── диск ──────────────────────────────────────────────────────────────────────

def _external_files(d: Path) -> int:
    """Скільки файлів справи лежить ПОЗА репо — з `meta.json` (`files[].external_path`).

    Великі PDF архівних справ живуть на архівному томі (`D:\\архів\\**`), а не в
    `data/raw`: копія коштувала б гігабайти, symlink на Windows потребує адміна, а
    junction тут не працює — файли лежать одним списком, не по теках-справах.
    Тому тека справи може містити САМ ОПИС (`meta.json`), а матеріал бути зовнішнім.

    🔴 Рахується лише файл, який РЕАЛЬНО існує на диску: інакше запис у meta.json сам
    себе оголошував би справою, і зниклий том читався б як повна бібліотека
    (пор. приймач «диск, а не rc»). Відсутній зовнішній файл видно як `frames: 0`.
    """
    f = d / "meta.json"
    if not f.exists():
        return 0
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for item in (m.get("files") or []):
        ext = (item or {}).get("external_path") if isinstance(item, dict) else None
        if ext and Path(str(ext)).exists():
            n += 1
    return n


@lru_cache(maxsize=8192)
def _pdf_pages_cached(path: str, size: int, mtime: int) -> int:
    """Сторінок у PDF. 0 = порахувати не вийшло (кличний код лишає файловий лік).

    Ключ кешу несе розмір і mtime, тож дописаний чи перекачаний файл перечитується
    сам. `pypdfium2` — оголошена залежність пакета (легша й з дозвільною ліцензією),
    `fitz` лишається запасним, бо стоїть у споживачів.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        try:
            import fitz
        except ImportError:
            return 0
        try:
            with fitz.open(path) as doc:
                return int(doc.page_count)
        except Exception:
            return 0
    try:
        doc = pdfium.PdfDocument(path)
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return 0


def _pdf_pages(paths: list[Path]) -> int:
    """Сумарно сторінок; 0 — якщо не вийшло. Стеля файлів боронить від періодики."""
    if not paths or len(paths) > _PDF_PROBE_LIMIT:
        return 0
    total = 0
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            return 0
        n = _pdf_pages_cached(str(p), st.st_size, int(st.st_mtime))
        if not n:
            return 0
        total += n
    return total


def _count_case(d: Path) -> tuple[int, int]:
    """(images, СТОРІНКИ) прямо у теці; PDF на архівному томі — через `external_path`.

    🔴 Друге число — СТОРІНКИ PDF, а не кількість файлів (виправлено 2026-08-15).
    Справа, завантажена одним PDF (вікі-дзеркало ДАВіО: `904-24-17/904-24-17.pdf`,
    275 стор.), давала `frames=1` і ставала в бібліотеці невідрізненною від голої
    картки опису — справи, якої на диску немає ВЗАГАЛІ. **Ціна помилки виміряна:**
    по реєстру виходило, що метрик Гарячківки 1861-1870 у нас немає, і їх замовили
    в архіві вдруге, хоча обидва томи (спр.17 і 19, 275 і 313 стор.) лежали на диску.

    Замір 2026-08-15: 95 PDF-тек у `data/raw` (періодика й описи вже відсічені
    `_SKIP_SLUGS`), ~4.5 мс на файл проти 16.3 с самого обходу диска.
    ⚠ Не вийшло порахувати (немає бібліотеки, битий файл, тека понад стелю) —
    лишається файловий лік: занижене число краще за нуль, бо нуль читається як
    «на диску нічого немає».
    """
    imgs = pdfs = 0
    pdf_paths: list[Path] = []
    try:
        for p in d.iterdir():
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in _IMG_EXT:
                imgs += 1
            elif ext == ".pdf":
                pdfs += 1
                pdf_paths.append(p)
    except OSError:
        pass
    if not (imgs or pdfs):
        pdfs = _external_files(d)
    elif pdf_paths and not imgs:
        pdfs = _pdf_pages(pdf_paths) or pdfs
    return imgs, pdfs


def _scan_disk_cases(limit: int = 4000) -> list[tuple[str, int, int]]:
    """Теки data/raw/** (1-4 рівні) з зображеннями/PDF → [(rel, images, pdfs)].

    4-й рівень з'явився з `fsfiles_download.py harvest`: `anrm/villages/<село>/<тека>`
    — одна тека на справу, ім'я за плівкою й кадрами, шифра в `_source.json`.
    """
    out: list[tuple[str, int, int]] = []
    if not RAW_DIR.exists():
        return out
    seen: set[Path] = set()
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*"):
        for d in sorted(RAW_DIR.glob(depth)):
            if not d.is_dir() or d in seen or d.name.startswith("_"):
                continue
            # періодика/описи/корпуси — тисячі PDF за роками, не справи (і не обходити T:)
            if d.relative_to(RAW_DIR).parts[0] in _SKIP_SLUGS:
                continue
            imgs, pdfs = _count_case(d)
            if imgs or pdfs:
                seen.add(d)
                rel = str(d.relative_to(ROOT)).replace("\\", "/")
                out.append((rel, imgs, pdfs))
            if len(out) >= limit:
                return out
    return out


# ── fallback-резолвери назв ───────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _wikisource_meta() -> dict[str, Any]:
    try:
        return dict(json.loads(_WIKISOURCE_META.read_text(encoding="utf-8")))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _opys_merged() -> dict[tuple[str, str], dict[str, Any]]:
    """(opys, spr_norm) → row(dict). Опис фонду 315 з Вікіджерел/ukrfamily."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        with _OPYS_MERGED.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                op = (row.get("opys") or "").strip()
                sp = _norm_spr(row.get("spr"))
                if op and sp:
                    out[(op, sp)] = row
    except Exception:
        pass
    return out


@lru_cache(maxsize=1)
def _master_index() -> dict[tuple[str, str], dict[str, Any]]:
    """(opys, spr) → рядок f315_MASTER_INDEX.tsv (12.8k справ фонду 315).

    ⚠ Колонку `title` ІГНОРУЄМО — вона генерична («Церковні записи, Подільська
    духовна консисторія (ф. 315), 1795-1920») однакова для всіх 12813 рядків, тобто
    виглядає як опис, але не каже про справу нічого. Цінні: `read_*` (людська звірка
    титулки, 177 справ) і — як останній шанс — FS-метадані (place/record_type), які
    НЕнадійні (див. memory dahmo-f315-opys-full-scrape: FS масово хибно тегає
    адмін-справи «Religious Records»).
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        with _MASTER_INDEX.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                op = (row.get("opys") or "").strip()
                sp = _norm_spr(row.get("spr"))
                if op and sp:
                    out[(op, sp)] = row
    except Exception:
        pass
    return out


@lru_cache(maxsize=1)
def _klirovi_index() -> dict[str, Any]:
    """spr → рядок klirovi_index.tsv (курований індекс клірових відомостей ф.315)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        with _KLIROVI_INDEX.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                sp = _norm_spr(row.get("spr"))
                if sp:
                    out[sp] = row
    except Exception:
        pass
    return out


_F904_ROW_RE = re.compile(
    r"^\|\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|\s*\*{0,2}(\d{4})\s*[–-]\s*(\d{4})\*{0,2}\s*\|"
    r"\s*\*{0,2}спр\.(\d+)\*{0,2}")
_F904_PART = {"Н": "народження", "Ш": "шлюби", "С": "смерті"}


@lru_cache(maxsize=1)
def _davo_f904_catalog() -> dict[str, Any]:
    """spr → {part, year_from, year_to} з людського каталогу ДАВО ф.904 оп.24
    (М'ястківська Свято-Благовіщенська ц.). Рядки виду `| Н | 1876-1885 | спр.53 |`."""
    out: dict[str, dict[str, Any]] = {}
    try:
        for line in _DAVO_F904_CATALOG.read_text(encoding="utf-8").splitlines():
            m = _F904_ROW_RE.match(line.strip())
            if not m:
                continue
            part, yf, yt, spr = m.groups()
            sp = _norm_spr(spr)
            if sp and sp not in out:
                out[sp] = {"part": part.strip(), "year_from": int(yf), "year_to": int(yt)}
    except Exception:
        pass
    return out


# `| 80 | 1043 | 1854 | ревізькі казки (IX рев.), однодворці | Ольгопільський | 1067 | …`
_D226_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|\s*\*{0,2}([^|*]*?)\*{0,2}\s*\|"
    r"\s*\*{0,2}([^|]+?)\*{0,2}\s*\|\s*\*{0,2}([^|*]*?)\*{0,2}\s*\|")


@lru_cache(maxsize=1)
def _dahmo_226_catalog() -> dict[str, Any]:
    """spr → {opys, year, type, uezd} з курованого CATALOG.md ф.226
    (Подільська казенна палата — ревізькі казки; таблиця ведеться вручну).

    Ключ — лише справа: ім'я теки `spr-1043` опису не несе, а каталог знає що це
    оп.80 → звідти ж і уточнюємо шифру (інакше показували б «226-1043»).

    ⚠️ Парсимо ЛИШЕ секцію «Наявне в нас»: у файлі три таблиці з РІЗНИМИ колонками
    (`inv|spr|рік|тип|повіт|…`, `inv|spr|рік|вміст|стан`, `inv|spr|в описі|реальний
    вміст|вердикт`) — без цієї межі рядки пізніших таблиць лізуть у поле «тип».
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        in_section = False
        for line in _DAHMO_226_CATALOG.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("##"):
                in_section = s.startswith("## Наявне в нас")
                continue
            if not in_section:
                continue
            m = _D226_ROW_RE.match(s)
            if not m:
                continue
            inv, spr, year, typ, uezd = (g.strip() for g in m.groups())
            sp, op = _norm_spr(spr), _norm_spr(inv)
            if sp and op and typ and typ != "тип":
                out[sp] = {"opys": op, "year": _to_int(year), "type": typ, "uezd": uezd}
    except Exception:
        pass
    return out


# хвіст опису archium дублює вже наявні поля: «…, 27.10.1881-18.12.1882, 244 арк.»
_ARCHIUM_TAIL_RE = re.compile(r"\s*,\s*\d{2}\.\d{2}\.\d{4}\s*[–-]?\s*(?:\d{2}\.\d{2}\.\d{4})?"
                              r"(?:\s*,\s*\d+\s*арк\.?)?\s*$")
_ARCHIUM_SHEETS_RE = re.compile(r"\s*,\s*\d+\s*арк\.?\s*$")
# «Церква, с. Зеленці, Проскурівського повіту» → населений пункт із опису
_SETTLEMENT_RE = re.compile(r"(?:^|,\s*)((?:с|м|смт|сщ|м-ко)\.?\s+[^,]{2,80})", re.IGNORECASE)
# «м. Ольгопіль Ольгопільського повіту Подільської губернії» → без губернії (шум у списку)
_GUB_TAIL_RE = re.compile(r"\s+\S+ої\s+губернії.*$", re.IGNORECASE)


# Жанр-маркери справи книгою записів. Без них типи НЕ вгадуємо: описи прокурорських
# фондів рясніють «смерті», «ревізії», «віросповідання» у слідчому, а не метричному
# сенсі — і 10 карних справ падало у фільтр «смерті» поруч із метричними книгами.
_ARCHIUM_GENRE = ("метрич", "метрик", "сповідальн", "сповідн", "исповед",
                  "ревізьк", "ревизск", "казк", "кліров", "клирови", "посімейн")


def _archium_desc(row: dict[str, Any]) -> dict[str, Any]:
    """Рядок cases.tsv → поля опису для CaseEntry (title/роки/місце)."""
    desc = (row.get("description") or "").strip()
    for rx in (_ARCHIUM_TAIL_RE, _ARCHIUM_SHEETS_RE):
        desc = rx.sub("", desc).strip()
    fond_title = (row.get("fond_title") or "").strip()
    title = desc or f"{fond_title} — {(row.get('case_no') or '').strip()}".strip(" —")
    years = re.findall(r"\b(1[6-9]\d{2}|20\d{2})\b", row.get("date") or "")
    ms = _SETTLEMENT_RE.search(desc) or _SETTLEMENT_RE.search(fond_title)
    return {"title": title, "doc_type": "",
            "year_from": int(years[0]) if years else None,
            "year_to": int(years[-1]) if years else None,
            "place": _GUB_TAIL_RE.sub("", ms.group(1)).strip() if ms else "",
            "desc_source": "archium_catalog",
            "rtypes_final": None if any(g in desc.lower() for g in _ARCHIUM_GENRE) else []}


def _strip_links(text: str) -> str:
    """Прибрати `[[PL-місце]]`-лінки з поля сайдкара («Назва села … — [[PL-місце]]»)."""
    t = re.sub(r"\[\[[^\]]*\]\]", "", text or "")
    return re.sub(r"\s+", " ", t).strip().rstrip("—-–").strip()


def _genitive(uezd: str) -> str:
    """Назва повіту в родовий: «Ольгопільський» → «Ольгопільського».

    Усі повіти в індексах — прикметники на -ський/-цький (klirovi_index.tsv тримає
    їх у називному), тож правило -ий → -ого покриває всі.
    """
    return uezd[:-2] + "ого" if uezd.endswith("ий") else uezd


def _clean_wiki(text: str) -> str:
    """Прибрати вікі-розмітку [[File:…]]/[[Категорія:…]]/[[…]] і зайві пробіли."""
    text = re.sub(r"\[\[[^\]]*\]\]", " ", text or "")
    text = re.sub(r"[{}|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HARVEST_YEAR_RE = re.compile(r"\b(1[6-9]\d\d)\b")


def _harvest_desc(m: dict[str, Any], single_case: bool = False) -> dict[str, Any] | None:
    """Опис теки `fsfiles harvest` з полів покажчика дзеркала. None якщо їх нема."""
    sod = (m.get("soderzhanie") or "").strip()
    village = (m.get("village") or "").strip()
    listy = (m.get("listy") or "").strip()
    if not (sod or village):
        return None
    years = sorted({int(y) for y in _HARVEST_YEAR_RE.findall(sod)})
    frames = (m.get("frame_range_on_disk") or m.get("frames_taken") or "").strip()
    bits = [b for b in (village, sod) if b]
    title = " — ".join(bits)
    if frames:
        title += f" (кадри {frames})"
    # Плівка на кілька справ ключа не дістає (`_case_from_sheet_index`), тож єдине
    # місце, де видно її склад — назва. Без цього матеріал спр.306-309 виглядав би
    # у каталозі як безіменна тека, і «справи на диску немає» було б неправдою.
    cases = []
    for it in (m.get("sheet_index") or []):
        got = _parse_delo(it.get("delo")) if isinstance(it, dict) else None
        if got and got not in cases:
            cases.append(got)
    if len(cases) > 1 and not single_case:
        fond = cases[0][0]
        same_fond = all(c[0] == fond for c in cases)
        listed = ", ".join(f"{c[1] or '?'}-{c[2]}" if same_fond else f"{c[0]}-{c[1] or '?'}-{c[2]}"
                           for c in cases[:8])
        more = f" +{len(cases) - 8}" if len(cases) > 8 else ""
        title = (f"плівка на {len(cases)} справ: "
                 + (f"ф.{fond} оп." if same_fond else "") + listed + more
                 + (f" — {title}" if title else ""))
    return {"title": title[:300], "place": village,
            "year_from": years[0] if years else None,
            "year_to": years[-1] if years else None,
            "listy": listy}


def _fallback_name(rel_path: str, key_parts: tuple[Any, ...] | None) -> dict[str, Any]:
    """Назва теки без канону: _source.json → wikisource → opys_tsv → код."""
    d = ROOT / rel_path
    # 1) сайдкар у теці — писаний руками, найточніший опис поза каноном.
    #    ДВІ конвенції: `_source.json` (shifra/record_type/frames) і `meta.json`
    #    (archive/fond/inv/doc_type/place/folios — 18 тек). Читаємо обидві.
    for name in ("_source.json", "meta.json"):
        src = d / name if d.is_dir() else None
        if not (src and src.exists()):
            continue
        try:
            m = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = (m.get("title") or "").strip()
        harvest = None
        if not title:
            # сайдкар `harvest` (fsfiles) `title` не має — опис лежить у полях
            # покажчика дзеркала: `soderzhanie` (англійська анотація FS з роком),
            # `village`, `listy` (діапазон кадрів). Без цієї гілки справа лишалась
            # безіменною в каталозі, хоч шифра з `delo` вже читалась.
            # `key_parts` != None означає, що тека все-таки звелась до ОДНІЄЇ справи
            # (вирізка `harvest` під неї) — тоді перелік справ плівки в назві зайвий
            harvest = _harvest_desc(m, single_case=key_parts is not None)
            if harvest is None:
                continue
            title = harvest["title"]
        # формат гуляє: одні сайдкари пишуть year_from/year_to, інші — `year`;
        # місце буває у `place` або `covers` (spr-6739 vs spr-8676)
        yf = _to_int(m.get("year_from")) or _to_int(m.get("year"))
        yt = _to_int(m.get("year_to")) or yf
        if not yf:
            yf, yt = _years_span(m.get("years"))
        if harvest:
            yf, yt = yf or harvest["year_from"], yt or harvest["year_to"]
        delo = _parse_delo(m.get("delo")) if not (m.get("shifra") or "").strip() else None
        return {"title": title,
                "doc_type": (m.get("record_type") or m.get("doc_type") or "").strip(),
                "year_from": yf, "year_to": yt,
                "place": _strip_links(m.get("place") or m.get("covers")
                                      or (harvest or {}).get("place") or ""),
                "shifra_hint": (m.get("shifra") or "").strip(),
                "opys_hint": _norm_spr(m.get("inv") or m.get("opys") or "")
                             or (delo[1] if delo else None),
                "desc_source": "source_json" if name == "_source.json" else "meta_json"}
    # ДАХмО archium — офіційний опис справи з краулу каталогу (найточніше поза каноном)
    if _ARCHIUM_SLUG in re.split(r"[\\/]+", rel_path):
        m = _ARCHIUM_DIR_RE.match(Path(rel_path).name)
        row = _archium_cases().get(m.group(1)) if m else None
        if row:
            return _archium_desc(row)

    # ДАХмО ф.226 — курований CATALOG.md (ревізькі казки однодворців)
    if key_parts and key_parts[0] == "DAHMO" and key_parts[1] == "226":
        c = _dahmo_226_catalog().get(key_parts[3])
        if c:
            uezd = c["uezd"].strip()
            place = f"{uezd} повіт" if uezd and uezd != "—" else ""
            title = c["type"][0].upper() + c["type"][1:]
            if place:
                title += f" — {_genitive(uezd)} повіту"
            return {"title": title, "doc_type": c["type"], "year_from": c["year"],
                    "year_to": c["year"], "place": place, "opys_hint": c["opys"],
                    "desc_source": "catalog_md"}

    # ДАВО ф.904 оп.24 — людський каталог М'ястківської Свято-Благовіщенської ц.
    if key_parts and key_parts[0] == "DAVO" and key_parts[1] == "904" \
            and (key_parts[2] or "") == "24":
        c = _davo_f904_catalog().get(key_parts[3])
        if c:
            part = _F904_PART.get(c["part"].split()[0], c["part"])
            okr = " (окружний том)" if "окр" in c["part"] else ""
            return {"title": f"Метрична книга Свято-Благовіщенської церкви м-ка "
                             f"М'ястківка — {part}{okr}",
                    "doc_type": part, "year_from": c["year_from"], "year_to": c["year_to"],
                    "place": "М'ястківка, Ольгопільський пов.", "desc_source": "davo_catalog"}

    # фонд 315: клірові-індекс → людська звірка титулки → wikisource → опис-TSV → FS-мета
    if key_parts and key_parts[0] == "DAHMO" and key_parts[1] == "315":
        opys, spr = key_parts[2] or "1", key_parts[3]
        kl = _klirovi_index().get(spr)
        if kl and (kl.get("uezd") or "").strip():
            uezd = kl["uezd"].strip()
            leaves = (kl.get("leaves") or "").strip()
            return {"title": f"Клірові відомості церков {_genitive(uezd)} повіту"
                             + (f" ({leaves} арк.)" if leaves else ""),
                    "doc_type": "клірові", "year_from": _to_int(kl.get("year")),
                    "year_to": _to_int(kl.get("year")),
                    "place": f"{uezd} повіт", "desc_source": "klirovi_index"}
        mi = _master_index().get((opys, spr))
        if mi:
            # людська звірка титулки — найнадійніше поза каноном
            note = (mi.get("read_note") or "").strip().lstrip("—").strip()
            village = (mi.get("read_village") or "").strip().strip("—").strip()
            rtypes = (mi.get("read_types") or "").strip()
            if note or village:
                title = note or f"{village} — {rtypes}".strip(" —")
                return {"title": title, "doc_type": rtypes,
                        "year_from": _to_int(mi.get("read_span")) or _to_int(mi.get("year_from")),
                        "year_to": _to_int(mi.get("year_to")),
                        "place": village or (mi.get("place") or "").strip(),
                        "desc_source": "fs_titleread"}
        wk = _wikisource_meta().get(f"{opys}-{spr}")
        if wk:
            title = _clean_wiki(wk.get("title") or "")
            dt = (wk.get("doc_type") or "").strip()
            if title or dt:
                return {"title": title or f"{dt} ({wk.get('year','')})".strip(),
                        "doc_type": dt, "year_from": _to_int(wk.get("year")),
                        "year_to": None, "place": "", "desc_source": "wikisource"}
        row = _opys_merged().get((opys, spr))
        if row and (row.get("title") or "").strip():
            return {"title": row["title"].strip(), "doc_type": "",
                    "year_from": _to_int(row.get("year_from")),
                    "year_to": _to_int(row.get("year_to")), "place": "",
                    "desc_source": "opys_tsv"}
        # останній шанс — FS-метадані. Позначаємо «FS-індекс», бо тип/місце НЕ звірені
        # з титулкою і FS часто бреше (адмін-справи тегає «Religious Records»).
        if mi and ((mi.get("place") or "").strip() or (mi.get("record_type") or "").strip()):
            place = (mi.get("place") or "").strip()
            rt = (mi.get("record_type") or "").strip()
            return {"title": f"FS-індекс (не звірено з титулкою): {rt or '?'}"
                             + (f" — {place}" if place else ""),
                    "doc_type": "", "year_from": _to_int(mi.get("year_from")),
                    "year_to": _to_int(mi.get("year_to")), "place": place,
                    "desc_source": "fs_master"}
    return {"title": "", "doc_type": "", "year_from": None, "year_to": None,
            "place": "", "desc_source": "code"}


def _years_span(v: Any) -> tuple[int | None, int | None]:
    """«1861-1870» або «1857-1866, 1869-1873» → (1861, 1870) / (1857, 1873).

    Третя конвенція сайдкара, крім `year_from/year_to` і `year`: суцільний РЯДОК
    років. Так пише `_source.json` справ, знятих із Wikimedia Commons, де роки
    стоять просто в назві файла. Без розбору такі справи лежали в реєстрі без
    років узагалі, тобто фільтр `--year` їх не бачив ЖОДНОГО разу — а це саме ті
    справи, які качаються безкоштовно й у яких шукають прогалину десятиліття.

    ⚠ Повертається ОБВІДНА, а не покриття: «1857-1866, 1869-1873» дасть
    (1857, 1873), хоча 1867-68 у книзі немає. Для фільтра «може містити рік X»
    це правильна семантика (краще показати зайве, ніж сховати потрібне), але
    вважати обвідну доказом покриття не можна — точні роки в назві справи.
    """
    years = sorted({int(y) for y in _HARVEST_YEAR_RE.findall(str(v or ""))})
    return (years[0], years[-1]) if years else (None, None)


def _to_int(v: Any) -> int | None:
    try:
        return int(str(v).strip()[:4])
    except (TypeError, ValueError):
        return None


#: Мова в сайдкарі → письмо. Кириличні й латинописні мови діловодства
#: Правобережжя: до 1830-х польська/латина, далі російська.
_LANG_SCRIPT = {"ru": "cyrillic", "uk": "cyrillic", "cs": "cyrillic",
                "pl": "latin", "la": "latin", "lat": "latin", "de": "latin"}
_SCRIPT_ALIASES = {
    "cyrillic": "cyrillic", "cyr": "cyrillic", "кирилиця": "cyrillic",
    "кириллица": "cyrillic", "ru": "cyrillic", "рос": "cyrillic",
    "latin": "latin", "lat": "latin", "латинка": "latin", "латиниця": "latin",
    "pl": "latin", "пол": "latin",
    "mixed": "mixed", "мішане": "mixed", "змішане": "mixed", "both": "mixed",
}


def _sidecar_script(rel_path: str | None) -> tuple[str, list[str]]:
    """Письмо й мови справи з сайдкара — ЗАФІКСОВАНІ людиною, не вгадані.

    Чому не самої евристики: `routers.htr._guess_script` судить із жанру й років,
    і на тримовних фондах це принципово ненадійно — ДАВіО ф.474 має російську
    рамку, латинські обляти актів XVIII ст. і польські контракти в одній книзі
    (спр.115 узагалі польськомовна, чого опис не згадує). Такі справи вимагають
    ДВОХ прогонів різними рушіями, і сказати це може лише той, хто бачив аркуші.

    Приймаємо і `script`, і `langs`/`lang`: якщо вказані лише мови, письмо
    виводимо з них (кілька різних → `mixed`).
    """
    if not rel_path:
        return "", []
    d = ROOT / rel_path
    if not d.is_dir():
        return "", []
    for name in ("_source.json", "meta.json"):
        p = d / name
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        raw_langs = m.get("langs") or m.get("lang") or m.get("languages") or []
        if isinstance(raw_langs, str):
            raw_langs = [x.strip() for x in re.split(r"[,;/]+", raw_langs) if x.strip()]
        langs = [str(x).strip().lower() for x in raw_langs if str(x).strip()]
        script = _SCRIPT_ALIASES.get(str(m.get("script") or "").strip().lower(), "")
        if not script and langs:
            got = {_LANG_SCRIPT.get(x) for x in langs} - {None}
            script = (got.pop() or "") if len(got) == 1 else ("mixed" if got else "")
        if script or langs:
            return script, langs
    return "", []


# ── визначення типу запису з тексту (лише для справ БЕЗ канонічних record_types) ──
# Канон дає нормалізовані типи напряму; решта описів (wikisource/_source.json/опис-TSV)
# — вільний текст, тож без цього фільтр «шлюби» не бачив би пів курованої черги.
_RTYPE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("birth", ("народж", "рождени", "родившихся")),
    ("marriage", ("шлюб", "брак", "бракосочет", "вінчан", "обиск")),
    ("death", ("смерт", "умерших", "померл")),
    ("confession", ("сповід", "исповед", "сповідальн")),
    ("revision", ("ревіз", "ревизск", "ревизьк", "посімейн", "посемейн", "сказк")),
    ("clergy_list", ("кліров", "клирови")),
    ("gazette", ("єпарх", "епарх")),
]


def _infer_record_types(*texts: str) -> list[str]:
    """Евристика типів із назви/типу документа. Порожньо — якщо нічого не впізнали."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return []
    out = [code for code, keys in _RTYPE_HINTS if any(k in blob for k in keys)]
    # «Н+Ш+С» / «Н, Ш, С» — стисла нотація зведеної метрики
    if re.search(r"\bн\s*[+,/]\s*ш\s*[+,/]\s*с\b", blob):
        out = list(dict.fromkeys([*out, "birth", "marriage", "death"]))
    # «метрична книга» без уточнення частини = усі три частини
    if not out and ("метрич" in blob or "метрик" in blob):
        out = ["birth", "marriage", "death"]
    return out


# ── канон ─────────────────────────────────────────────────────────────────────

_REF_OPYS_RE = re.compile(r"(?:Опис|оп\.?)\s*(\d+)", re.IGNORECASE)


def _opys_from_ref(ref: str | None) -> str | None:
    """Опис із `repository_ref` («…, Опис 1, Справа 8433») — авторитетніше за id."""
    m = _REF_OPYS_RE.search(ref or "")
    return m.group(1) if m else None


def _source_to_entry(src: Source) -> CaseEntry | None:
    """Канонічне джерело → CaseEntry (тільки якщо id парситься як справа)."""
    parsed = parse_source_id(src.id)
    if not parsed:
        return None
    repo, fond, opys, spr = parsed
    opys = opys or _opys_from_ref(src.repository_ref) or _DEFAULT_OPYS.get((repo, fond))
    key = _mk_key(repo, fond, spr, opys)
    if not key:
        return None
    years = [c.year_from for c in src.coverage if c.year_from]
    years_to = [c.year_to or c.year_from for c in src.coverage if (c.year_to or c.year_from)]
    rtypes: list[str] = []
    place = parish = None
    for c in src.coverage:
        for rt in c.record_types:
            if rt not in rtypes:
                rtypes.append(rt)
        if not place:
            place = (c.settlements[0] if c.settlements else None) or c.parish or c.region
        if not parish:
            parish = c.parish
    raw = (src.raw_path or "").strip() or None
    rel = raw.replace("\\", "/").rstrip("/") if raw else None
    return CaseEntry(
        key=key, repo=repo, repo_label=_REPO_LABEL.get(repo, repo),
        fond=fond, opys=opys, spr=spr,
        shifra=_shifra(repo, fond, opys, spr),
        title=src.title.strip(), year_from=min(years) if years else None,
        year_to=max(years_to) if years_to else None,
        doc_type=_rtypes_label(rtypes), record_types=rtypes,
        place=place or "", parish=parish,
        raw_path=rel, source_id=src.id, desc_source="canonical",
        tag=_tag_from_path(rel) if rel else f"{fond}-{opys or '1'}-{spr}",
    )


def _shifra(repo: str | None, fond: str | None, opys: str | None,
            spr: str | None) -> str:
    lbl = _REPO_LABEL.get(repo or "", repo or "")
    mid = f"{fond}-{opys}-{spr}" if opys else f"{fond}-{spr}"
    return f"{lbl} {mid}".strip()


def _rtypes_label(rtypes: list[str]) -> str:
    """Стислий людський тип: народж./шлюб/смерть → «Н+Ш+С», решта — підписи."""
    if not rtypes:
        return ""
    metric = [r for r in rtypes if r in ("birth", "marriage", "death")]
    other = [r for r in rtypes if r not in ("birth", "marriage", "death")]
    parts = []
    if metric:
        parts.append("+".join({"birth": "Н", "marriage": "Ш", "death": "С"}[r]
                              for r in ("birth", "marriage", "death") if r in metric))
    parts.extend(_RTYPE_LABEL.get(r, r) for r in other)
    return ", ".join(parts)


def _tag_from_path(rel: str) -> str:
    return Path(rel).name if rel else ""


# ── scan_targets (курована черга §9) ──────────────────────────────────────────

def _load_curated() -> dict[str, dict[str, Any]]:
    """rel-path → {group, why, tag, expected} з scan_targets.json (для позначки 🎖)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        data = json.loads(SCAN_TARGETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return out
    for t in data.get("targets", []):
        rel = str(t.get("path", "")).replace("\\", "/").rstrip("/")
        if rel:
            out[rel] = t
    return out


# ── build ─────────────────────────────────────────────────────────────────────

def build_library() -> list[CaseEntry]:
    """Зібрати бібліотеку: канон ∪ диск, злиття за ключем (repo/fond/spr)."""
    by_key: dict[str, CaseEntry] = {}
    by_raw: dict[str, CaseEntry] = {}
    orphans: list[CaseEntry] = []  # канон без парсабельного ключа не буває, але про запас

    # 1) канонічні джерела
    for md in sorted(SOURCES_DIR.glob("S_*.md")):
        try:
            src = read_source(md)
        except Exception:
            continue
        entry = _source_to_entry(src)
        if not entry:
            continue
        # кілька канонічних джерел на ту саму справу — виграє те, що з назвою
        prev = by_key.get(entry.key)
        if prev is None or (not prev.title and entry.title):
            by_key[entry.key] = entry
        if entry.raw_path:
            by_raw[entry.raw_path] = by_key[entry.key]

    # 2) КАНОНІЧНИЙ raw_path під data/raw — головний: пінимо ДО скану диска, інакше
    #    сусідня тека з тим самим ключем перебиває оголошене джерело (інцидент: ф.357
    #    спр.23 — канон вказує на `…_reshoot`, а скан диска підставляв
    #    `010357-01-00023`, тож «є прогін» рахувалось по одній теці, а «→ скан»
    #    запускав іншу). raw_path на `data/source/archives/**` НЕ пінимо — то стор
    #    першоджерел, а прогін іде по теці в data/raw (її знайде крок 3).
    for e in list(by_key.values()):
        # Локальна змінна, а не `e.raw_path` двічі: перевіряч не доводить
        # звуження крізь `(x or "")`, а читач через це не бачить, що далі
        # шлях уже точно є.
        raw = e.raw_path or ""
        if not raw.startswith("data/raw/"):
            continue
        p = ROOT / raw
        if not p.exists():
            continue
        e.path = raw
        e.tag = _tag_from_path(raw)
        i, d = _count_case(p) if p.is_dir() else (0, _pdf_pages([p]) or 1)
        e.frames = i or d
        e.on_disk = bool(e.frames)

    # 3) теки сканів на диску
    for rel, imgs, pdfs in _scan_disk_cases():
        frames = imgs or pdfs
        entry = by_raw.get(rel)
        parsed = parse_case_path(rel)
        if entry is None and parsed:
            entry = next((by_key[k] for k in candidate_keys(parsed) if k in by_key), None)
        if entry is not None:
            entry.on_disk = True
            if not entry.path:
                entry.path = rel
                entry.frames = frames
                # тег МАЄ описувати вхід прогону. Раніше лишався від raw_path канону
                # («315-1-6664.pdf», «159 справа Григорій») і не матчив review-теки ніколи.
                entry.tag = _tag_from_path(rel)
                continue
            if rel == entry.path:
                continue
            # Дві теки на один ключ — не завжди одне й те саме. Заводимо окремий запис,
            # коли це РІЗНИЙ матеріал:
            #  · різний опис — 211-**5**-75 і 211-**13**-75 просто ділять ключ без опису;
            #  · різне село — том метрик повіту нарізаний по селах, і вирізка Царевки
            #    не є «іншим ракурсом» вирізки Фузовки, а окремим входом прогону.
            # Решта (справа на двох плівках, `_reshoot`, сторінкові рендери) — extra_paths.
            other_opys = bool(parsed and parsed[2] and entry.opys and parsed[2] != entry.opys)
            v_new, v_old = _sidecar_village(rel), _sidecar_village(entry.path)
            if other_opys or (v_new and v_old and v_new != v_old):
                pass  # → нижче створиться свій запис
            else:
                entry.extra_paths.append(rel)
                continue
        # Тека не є архівною справою (річні теки єпарх. відомостей, OCR-корпуси,
        # описи фондів) — код справи з неї не парситься → у бібліотеку не йде.
        if not parsed:
            continue
        # нова справа поза каноном → fallback-назва
        repo, fond, opys, spr = parsed
        fb = _fallback_name(rel, parsed)
        # опис із каталогу авторитетніший за дефолт фонду (ім'я теки його не несе)
        opys = opys or fb.get("opys_hint") or _DEFAULT_OPYS.get((repo, fond))
        # ⚠️ ключ рахується ПІСЛЯ доповнення опису: для `_OPYS_IN_KEY`-фондів опис
        # у ключі, і порахований до цього рядка ключ був би без опису (два різні
        # описи злиплися б в один запис бібліотеки).
        key = _mk_key(repo, fond, spr, opys)
        if not key:
            continue          # без ключа запис ніде не знайдеться
        shifra = fb.get("shifra_hint") or _shifra(repo, fond, opys, spr)
        # `rtypes_final=[]` від резолвера = «жанр не книга записів, не вгадувати»
        final = fb.get("rtypes_final")
        rtypes = _infer_record_types(fb["title"], fb["doc_type"]) if final is None else final
        new = CaseEntry(
            key=key, repo=repo, repo_label=_REPO_LABEL.get(repo or "", repo),
            fond=fond, opys=opys, spr=spr, shifra=shifra,
            title=fb["title"], doc_type=fb["doc_type"] or _rtypes_label(rtypes),
            record_types=rtypes, rtypes_inferred=bool(rtypes) and final is None,
            rtypes_final="rtypes_final" in fb,
            year_from=fb["year_from"], year_to=fb["year_to"], place=fb["place"],
            path=rel, raw_path=rel, on_disk=True, frames=frames,
            desc_source=fb["desc_source"], tag=_tag_from_path(rel),
        )
        if key in by_key:
            orphans.append(new)
        else:
            by_key[key] = new

    entries = list(by_key.values()) + orphans

    # 3b) теки в data/raw не знайшлось → вхід = raw_path канону як є (першоджерело-PDF
    #     у data/source/archives тощо). Краще, ніж лишити справу зовсім без входу.
    for e in entries:
        if e.path is None and e.raw_path:
            p = ROOT / e.raw_path
            if p.exists():
                e.path = e.raw_path
                e.tag = _tag_from_path(e.raw_path)
                i, d = _count_case(p) if p.is_dir() else (0, _pdf_pages([p]) or 1)
                e.frames = i or d
                e.on_disk = bool(e.frames)

    # 4) позначка курованих (🎖) з scan_targets.json
    curated = _load_curated()
    for e in entries:
        label = ""
        for cand in (e.path, e.raw_path):
            t = curated.get((cand or "").rstrip("/"))
            if t:
                e.curated = True
                e.group = t.get("group")
                e.why = t.get("why")
                e.tag = t.get("tag") or e.tag
                label = t.get("label") or ""
                break
        # типи, яких канон не дав — вгадуємо з тексту (мітка черги «шлюби Проскурів
        # 1866» / назва / тип), інакше фільтр за типом мовчки ховав би пів каталогу
        if not e.record_types and not e.rtypes_final:
            e.record_types = _infer_record_types(e.title, e.doc_type, label, e.why or "")
            e.rtypes_inferred = bool(e.record_types)
            if e.record_types and not e.doc_type:
                e.doc_type = _rtypes_label(e.record_types)

    # 4b) письмо/мови з сайдкара — вирішує, ЯКИМ рушієм читати справу
    for e in entries:
        for cand in (e.path, e.raw_path):
            script, langs = _sidecar_script(cand)
            if script or langs:
                e.script, e.langs = script, langs
                break

    entries.sort(key=lambda e: (not e.curated, e.repo_label or "", e.fond or "",
                                _to_int(e.spr) or 0))
    return entries


def write_library(entries: list[CaseEntry]) -> Path:
    """Записати бібліотеку у data/derived/case_library.json."""
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": ("Бібліотека архівних справ (канон ∪ диск). Опис статичний — "
                     "перебудова: `nysh library build` або кнопка 🔄 у консолі. "
                     "Статус скану рахується наживо (не тут)."),
        "count": len(entries),
        "cases": [asdict(e) for e in entries],
    }
    tmp = LIBRARY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(LIBRARY_PATH)
    return LIBRARY_PATH


# ── читання / резолвер для пікера ─────────────────────────────────────────────

# ── ручні вердикти по справах (USER-рішення оком) ────────────────────────────
VERDICTS_PATH = ROOT / "data" / "spotter" / "case_verdicts.json"

# `no_clan` — головний: USER сам переглянув справу (мала/швидка) і роду там немає.
# Це рішення ЛЮДИНИ і воно НЕ застаріває від зміни моделі — на відміну від скану.
VERDICT_KINDS = {
    "no_clan": {"emoji": "🚫", "label": "роду немає (вручну)"},
    "clan_found": {"emoji": "🎯", "label": "рід знайдено"},
    "recheck": {"emoji": "🔁", "label": "перевірити ще раз"},
}


def load_verdicts() -> dict[str, Any]:
    """key справи → {verdict, note, pages, date}. Порожньо якщо файла ще нема."""
    try:
        return dict(json.loads(
            VERDICTS_PATH.read_text(encoding="utf-8")).get("verdicts", {}))
    except Exception:
        return {}


def set_verdict(key: str, verdict: str | None, note: str = "",
                pages: int | None = None, date: str = "") -> dict[str, Any]:
    """Виставити/зняти ручний вердикт справи (verdict=None або "" знімає)."""
    if verdict and verdict not in VERDICT_KINDS:
        raise ValueError(f"невідомий вердикт: {verdict}")
    data = load_verdicts()
    if verdict:
        data[key] = {"verdict": verdict, "note": note or "",
                     "pages": pages, "date": date or ""}
    else:
        data.pop(key, None)
    VERDICTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_comment": ("Ручні вердикти по справах (перегляд оком). Не застарівають "
                            "від зміни YOLO-моделі — на відміну від скану. Ключ = key "
                            "справи з case_library.json."),
               "verdicts": data}
    tmp = VERDICTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(VERDICTS_PATH)
    return dict(data.get(key, {}))


def load_library() -> list[dict[str, Any]]:
    """Прочитати case_library.json (порожньо якщо ще не збудовано)."""
    try:
        return list(json.loads(
            LIBRARY_PATH.read_text(encoding="utf-8")).get("cases", []))
    except Exception:
        return []


@lru_cache(maxsize=1)
def _describe_index() -> tuple[float, dict[str, Any], dict[str, Any]]:
    """(mtime, path→entry, key→entry) з case_library.json — для describe_case."""
    try:
        mtime = LIBRARY_PATH.stat().st_mtime
    except OSError:
        return (0.0, {}, {})
    by_path: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for e in load_library():
        for p in (e.get("path"), e.get("raw_path")):
            if p:
                by_path[str(p).replace("\\", "/").rstrip("/")] = e
        if e.get("key"):
            by_key[e["key"]] = e
    return (mtime, by_path, by_key)


@lru_cache(maxsize=1)
def _junctions() -> list[tuple[str, str]]:
    """[(фізична ціль, rel-шлях у репо)] для junction-тек `data/raw` — 1-2 рівні.

    🐞 Файл-браузер консолі робить `Path.resolve()`, а той РОЗКРИВАЄ junction:
    тека `data/raw/dahmo_archium/olhopilska_f794` повертається клієнту як
    `D:\\архів\\dahmo_archium\\olhopilska_f794`. Такий шлях не має в собі
    сегмента `raw`, тож `parse_case_path` здавався, і всі 287 справ трьох
    прокурорських фондів ДАХмО показувались у пікері як «справи нема в
    бібліотеці» — при тому, що в бібліотеці вони є (і з описом, і з письмом).
    Два рівні: junction буває і на слузі (`data/raw/bev_pdh`), і на підтеці
    всередині нього (`data/raw/dahmo_archium/olhopilska_f794`).
    """
    out: list[tuple[str, str]] = []
    if not RAW_DIR.exists():
        return out
    for depth in ("*", "*/*"):
        for d in RAW_DIR.glob(depth):
            if not d.is_dir():
                continue
            try:
                real = d.resolve()
                real.relative_to(ROOT)
            except ValueError:  # фізично поза репо → junction/symlink
                rel = str(d.relative_to(ROOT)).replace("\\", "/")
                out.append((str(real).replace("\\", "/").rstrip("/").lower(), rel))
            except OSError:
                continue
    # довші цілі першими: junction на підтеці має вигравати над junction на слузі
    out.sort(key=lambda t: -len(t[0]))
    return out


def dejunction(path: str) -> str | None:
    """Фізичний шлях крізь junction → rel-шлях у репо (None якщо не з наших тек)."""
    p = str(path).replace("\\", "/").rstrip("/")
    low = p.lower()
    for target, rel in _junctions():
        if low == target:
            return rel
        if low.startswith(target + "/"):
            return rel + p[len(target):]
    return None


def describe_case(path: str) -> dict[str, Any] | None:
    """Знайти опис справи за шляхом входу (для збагачення пікера консолі).

    Кеш скидається коли case_library.json перезаписано (звірка mtime).
    """
    if not path:
        return None
    try:
        cur_mtime = LIBRARY_PATH.stat().st_mtime
    except OSError:
        return None
    mtime, by_path, by_key = _describe_index()
    if mtime != cur_mtime:
        _describe_index.cache_clear()
        mtime, by_path, by_key = _describe_index()
    rel = str(path).replace("\\", "/").rstrip("/")
    # абсолютний шлях → rel від кореня, якщо можливо
    if rel not in by_path:
        try:
            rel_root = str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/").rstrip("/")
            if rel_root in by_path:
                rel = rel_root
        except (ValueError, OSError):
            pass
    # шлях крізь junction (D:\архів\…) → назад у data/raw/…
    if rel not in by_path:
        rel = dejunction(path) or rel
    if rel in by_path:
        return dict(by_path[rel])
    parsed = parse_case_code(rel) or parse_case_code(path)
    if parsed:
        return next((by_key[k] for k in candidate_keys(parsed) if k in by_key), None)
    return None


# Псевдо-неймспейси ідентифікаторів банку: це НЕ теки на диску, а походження запису.
_BANK_NS = ("_addtp/", "_direct/", "_synthetic/", "_svshch/")


def describe_bank_case(case_id: str) -> dict[str, Any] | None:
    """Опис справи за ідентифікатором запису БАНКУ (`data/spotter/canonical/pages.jsonl`).

    Ідентифікатор там — не шлях: `davo_904_24/010904-24-00053` (тека/підтека),
    `_addtp/dahmo_315-spr-159` (псевдо-неймспейс + «тека-підтека» через дефіс),
    `_direct/v1`, `_synthetic/b1` (походження, справи не мають взагалі).
    Пробуємо кілька нормалізацій і беремо першу, що резолвиться в бібліотеці.
    Свідомо НЕ вгадуємо шифру з тексту — краще None, ніж вигаданий номер справи.
    """
    if not case_id:
        return None
    cands = [case_id]
    rest = case_id
    for ns in _BANK_NS:
        if case_id.startswith(ns):
            rest = case_id[len(ns):]
            cands.append(rest)
            break
    # «dahmo_315-spr-159» → «dahmo_315/spr-159»: перший дефіс розділяє теку й підтеку
    if "-" in rest and "/" not in rest:
        a, b = rest.split("-", 1)
        cands += [f"{a}/{b}", f"data/raw/{a}/{b}"]
    cands.append(f"data/raw/{rest}")
    for c in cands:
        if (info := describe_case(c)):
            return info
    return None
