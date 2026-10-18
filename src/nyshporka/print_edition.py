"""📰 Друковане видання в хмарі: від теки підшивки до років `VYD/<код>/<рік>`.

Людина показує теку видання (`<Назва>/<РІК>/<N (НАСКРІЗНИЙ) РРРР-ММ-ДД>/`).
`nysh cloud go --print` розгортає її в номери (`vydannia_issues`), везе їх
наглядачеві як звичайні справи й записує тут ВИДАННЯ: код, назву, місто й
те, куди ляже прочитане кожного номера. Після забору `nysh print assemble`
збирає з номерів роки — `reports/htr/vyd_<код>_<рік>` — і кладе їх у
текстовий стор: пошук прізвища по газеті працює одразу. `nysh print pack`
пакує повні роки для Супряги, а віддає їх людина (`nysh print publish`).

🔴 Розпізнавання друку тут немає й не буде: рушій живе лише на орендованій
машині (пакет оренди). Цей модуль — облік і складання тексту.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka import vydannia
from nyshporka import vydannia_issues as VI

#: Чим прочитано — так і пишеться в пакет (`ocr_by`): ворота пулу вимагають
#: назвати джерело тексту.
OCR_BY = "PaddleOCR-VL 1.6 (Нишпорка, хмарний прогін)"


def editions_dir() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / "print" / "editions"


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


# ── розгортання теки видання ─────────────────────────────────────────────────
@dataclass
class Expanded:
    """Що `cloud go --print` отримав замість тек, які назвала людина."""

    cases: list[str] = field(default_factory=list)
    editions: list[VI.Edition] = field(default_factory=list)
    #: Номери в порядку `cases`: тотожність кожного (дата, номер, додаток, рік).
    issues: list[VI.Issue] = field(default_factory=list)
    #: Теки, які номерами не розібрались (людині, а не мовчки геть).
    unparsed: list[str] = field(default_factory=list)
    #: Дві теки одного номера — людині.
    dupes: list[tuple[str, str]] = field(default_factory=list)
    #: Теки, у яких знайшлось КІЛЬКА видань (`НБУВ/Пирятин`): код у кожного свій,
    #: тож женуться вони окремо.
    many: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def titles(self) -> list[str]:
        """Назви видань, до яких належать номери (тека над теками років)."""
        return sorted({edition_root(i.path).name for i in self.issues})


def expand(args: list[str] | tuple[str, ...]) -> Expanded:
    """Теку видання чи року → теки номерів; тека номера лишається як є.

    Тека, під якою лежить кілька видань, не розгортається: вона йде в `many`
    разом із теками видань, щоб людина пустила кожне зі своїм кодом.
    """
    out = Expanded()
    for arg in args:
        path = Path(arg).expanduser()
        if not path.is_dir():
            out.cases.append(arg)
            continue
        one = VI._issue(path)
        if one is not None:
            out.cases.append(str(path))
            out.issues.append(one)
            continue
        roots = VI.find_editions(path)
        if len(roots) > 1:
            out.many.append((str(path), [str(r) for r in roots]))
            continue
        ed = VI.scan(roots[0] if roots else path)
        if not ed.issues:
            out.cases.append(arg)          # звичайна справа, не видання
            continue
        out.editions.append(ed)
        out.cases += [str(i.path) for i in ed.issues]
        out.issues += ed.issues
        out.unparsed += [str(p) for p in ed.unparsed]
        out.dupes += [(str(a), str(b)) for a, b in ed.dupes]
    return out


def edition_root(issue_dir: Path) -> Path:
    """Тека видання над текою номера: `<Назва>/<РІК>/<номер>` → `<Назва>`."""
    year = issue_dir.parent
    return year.parent if year.name.strip().isdigit() else year


def issue_run_name(code: str, issue: VI.Issue) -> str:
    """Ім'я прогону номера: `kolselo_pyr_1934-02-12_16`, `…_1935-08-12_dod`.

    🔴 Не ім'я теки номера: «1 1934-02-12» є і в «За ударну працю», і в будь-якій
    іншій газеті того дня, а ім'я прогону — це тека результату, стиснута копія
    кадрів і адреса в сховищі.
    """
    return f"{code.lower()}_{issue.ident}"


@dataclass(frozen=True)
class IssueRun:
    """Як номер їде наглядачеві: ім'я, ключ і що лишилось від давнішого заходу."""

    name: str                 # `issue_run_name`
    key: str                  # `VYD/<код>/<рік>`
    stage: Path | None = None  # стиснута копія цього номера з давнішого заходу
    reuse_key: str = ""       # адреса його архіву кадрів у сховищі звідти ж


def issue_runs(code: str, issues: list[VI.Issue]) -> dict[str, IssueRun]:
    """Тека номера (нормалізована) → `IssueRun` для кожного номера."""
    out: dict[str, IssueRun] = {}
    for iss in issues:
        stage, reuse = legacy_frames(iss.path)
        out[_norm(iss.path.resolve())] = IssueRun(
            name=issue_run_name(code, iss), key=vydannia.key(code, iss.year),
            stage=stage, reuse_key=reuse)
    return out


def run_for(runs: dict[str, IssueRun], issue_dir: str | Path) -> IssueRun | None:
    return runs.get(_norm(Path(issue_dir).expanduser().resolve()))


def _label(iss: VI.Issue) -> str:
    """Номер для людини: «3 (1936-01-06)», «додаток 111 (1935-08-12)»."""
    if iss.book:
        return f"книга ({iss.year})"
    head = (f"додаток {iss.no}".strip() if iss.supplement else iss.no) or "без номера"
    return f"{head} ({iss.date})"


# ── давніша адреса кадрів ─────────────────────────────────────────────────────
def _key_of_url(url: str) -> str:
    """Ключ об'єкта з presigned-посилання R2: `…/<бакет>/<ключ>?…` → `<ключ>`."""
    from urllib.parse import unquote, urlparse

    u = urlparse(url or "")
    path = unquote(u.path or "").lstrip("/")
    if not path:
        return ""
    # Шлях `https://<акаунт>.r2.cloudflarestorage.com/<бакет>/<ключ>`; у
    # віртуальному стилі (`<бакет>.<акаунт>.r2…`) бакет у хості, а не в шляху.
    labels = (u.hostname or "").split(".")
    if len(labels) > 4 and (u.hostname or "").endswith("r2.cloudflarestorage.com"):
        return path
    return path.split("/", 1)[1] if "/" in path else ""


def _plan_keys(runs: Path) -> dict[str, str]:
    """Тека оригіналу справи → ключ її архіву кадрів з планів наглядача.

    Пізніший план перекриває ранній: адреса могла змінитись між заходами.
    Справа частинами (`pages_parts`) сюди не йде — друк частинами не читається.
    """
    out: dict[str, str] = {}
    plans = sorted(runs.glob("*/plan.json"), key=lambda p: p.stat().st_mtime)
    for p in plans:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for case in data.get("cases") or [] if isinstance(data, dict) else []:
            if not isinstance(case, dict) or case.get("pages_parts"):
                continue
            key = _key_of_url(str(case.get("pages_url") or ""))
            if key and case.get("case_dir"):
                out[_norm(case["case_dir"])] = key
    return out


_PLAN_KEYS: dict[str, dict[str, str]] = {}


def legacy_frames(issue_dir: Path) -> tuple[Path | None, str]:
    """Що лишилось від заходу, у якому номер ішов безіменною справою.

    Партнер залив 1 789 номерів, коли друку ще не було: кадри стиснуто в
    `cloud/frames/<ім'я теки номера>` і залито під адресою з цього імені. Друк
    дає номеру нове ім'я, тож без цього кадри стискались би й заливались удруге.
    Повертає (стиснута копія ЦЬОГО номера або None, ключ архіву або "").

    🔴 Копія береться лише за підписом (`_from.txt` = тека цього номера): ім'я
    «1 1934-02-12» мають номери різних газет. А ключ наглядач бере лише тоді,
    коли там лежить рівно цей архів (розмір до байта, не старший за кадри).
    """
    from nyshporka.cloud import frames as F
    from nyshporka.core.workspace import workspace

    issue_dir = Path(issue_dir)
    stage = F.shrink_dir_for(issue_dir, name=issue_dir.name)
    try:
        claim = (stage / F.CLAIM_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        claim = ""
    mine = claim and _norm(claim) == _norm(issue_dir.resolve())
    runs = workspace().derived / "cloud" / "supervised" / "runs"
    keys = _PLAN_KEYS.get(str(runs))
    if keys is None:
        keys = _PLAN_KEYS[str(runs)] = _plan_keys(runs) if runs.is_dir() else {}
    return (stage if mine else None), keys.get(_norm(issue_dir.resolve()), "")


# ── запис видання ────────────────────────────────────────────────────────────
def record_path(code: str) -> Path:
    return editions_dir() / f"{code.upper()}.json"


def load_record(code: str) -> dict[str, Any]:
    try:
        data = json.loads(record_path(code).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def records() -> list[dict[str, Any]]:
    d = editions_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("code"):
            out.append(data)
    return out


def record(code: str, *, title: str, city: str,
           issues: list[tuple[str, Path, Path]], book: int = 0) -> Path:
    """Дописати видання: `issues` — (ім'я прогону, тека номера, куди ляже текст).

    Запис дописується, а не перезаписується: видання часто женуть частинами
    (рік за роком), і попередні номери мусять лишитись у ньому.

    `book` — рік видання разової книги: тоді `issues` — сама тека книги, а
    дерева підшивки (`<Назва>/<РІК>/<номер>`) немає й шукати його нема де.
    """
    code = code.upper()
    if not vydannia.is_code(code):
        raise ValueError(f"код видання «{code}» — лише латинка й цифри, від двох знаків")
    data = load_record(code) or {"code": code, "issues": {}, "roots": []}
    # 🔴 Книга й підшивка під одним кодом не змішуються: збирач видання читає
    # або дерево номерів, або теки книги, і друге мовчки випало б із видання.
    was_book = data.get("kind") == "book"
    if data.get("issues") and was_book != bool(book):
        raise ValueError(
            f"код «{code}» уже має {'книгу' if was_book else 'номери періодичного видання'}"
            f" — {'книга' if book else 'номери газети'} під ним не ляже; дайте інший код")
    data["title"] = title or data.get("title") or ""
    data["city"] = city or data.get("city") or ""
    if book:
        data["kind"] = "book"
    roots = set(data.get("roots") or [])
    for run, case_dir, out_dir in issues:
        data["issues"][run] = {"case_dir": str(case_dir), "out_dir": str(out_dir),
                               **({"year": int(book)} if book else {})}
        if not book:
            roots.add(str(edition_root(Path(case_dir))))
    data["roots"] = sorted(roots)
    return _write_record(data)


def _write_record(data: dict[str, Any]) -> Path:
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = record_path(str(data["code"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


# ── картка видання ──────────────────────────────────────────────────────────
#: Без цих полів рік видання в пулі виглядає «Без назви / місце не назване /
#: жанру нема», і генеалог не знає, звідки підшивка. Пакування їх вимагає.
CARD_REQUIRED = ("title", "city", "doc_type", "holder")
#: Решта полів картки: що ще бачить людина на картці в пулі.
CARD_FIELDS = (*CARD_REQUIRED, "places", "organ", "frequency", "scans_url",
               "scans_label", "source_terms", "note")
_CARD_HINT = {
    "title": "назва з шапки номера, без року: --title \"Колективізоване село\"",
    "city": "місто видання: --city \"Пирятин\"",
    "doc_type": "жанр: --doc-type newspaper (газета) | gazette (єпарх. відомості) | "
                "directory (довідник) | book (разова книга)",
    "holder": "де лежить підшивка, з якої скани: --holder \"НБУВ, фонд газет\" або "
              "\"приватна колекція (ім'я)\"",
}


def set_card(code: str, **fields: Any) -> dict[str, Any]:
    """Дописати картку видання; `None` — поле не чіпати, порожнє — стерти."""
    code = code.upper()
    if not vydannia.is_code(code):
        raise ValueError(f"код видання «{code}» — лише латинка й цифри, від двох знаків")
    data = load_record(code) or {"code": code, "issues": {}, "roots": []}
    for key, value in fields.items():
        if key not in CARD_FIELDS:
            raise ValueError(f"невідоме поле картки: {key}")
        if value is None:
            continue
        if key in ("places", "organ"):
            clean = [" ".join(str(v).split()) for v in (value or [])]
            data[key] = [v for v in clean if v]
        else:
            data[key] = " ".join(str(value).split())
    if data.get("doc_type"):
        from nyshporka.share.card import genres

        known = genres()
        if known and data["doc_type"] not in known:
            raise ValueError(f"жанр «{data['doc_type']}» невідомий; є: "
                             + ", ".join(f"{k} ({v})" for k, v in known.items()))
    _write_record(data)
    return data


def card_gaps(rec: dict[str, Any]) -> list[str]:
    """Чого бракує картці для пакування — з підказкою, як заповнити."""
    return [f"{k}: {_CARD_HINT[k]}" for k in CARD_REQUIRED if not str(rec.get(k) or "").strip()]


def _by_year(lines: list[str], year: int) -> tuple[list[str], list[str]]:
    """Рядки картки для року: (з роками, що покривають рік; без років)."""
    import re

    dated: list[str] = []
    plain: list[str] = []
    for line in lines or []:
        m = re.match(r"^\s*(\d{4})(?:\s*[-–]\s*(\d{4}))?\s*:\s*(.+)$", line)
        if m is None:
            plain.append(line.strip())
        elif int(m.group(1)) <= year <= int(m.group(2) or m.group(1)):
            dated.append(m.group(3).strip())
    return dated, plain


def organ_for(rec: dict[str, Any], year: int) -> str:
    """Чий орган газета цього року. Рядок картки `organ` — «1932–1937: текст»,
    «1938: текст» або просто текст (на всі роки)."""
    dated, plain = _by_year(list(rec.get("organ") or []), year)
    return (dated or plain or [""])[0]


def places_for(rec: dict[str, Any], year: int) -> list[str]:
    """Місця картки для року: «1932–1937: Харківська область» — лише в ті роки,
    рядок без років — у всі (адміністративний поділ мінявся)."""
    dated, plain = _by_year(list(rec.get("places") or []), year)
    return plain + dated


def _ua_date(iso: str) -> str:
    y, m, d = [*iso.split("-"), "", ""][:3]
    return f"{d}.{m}.{y}" if d and m else iso


def _n(count: int, one: str, few: str, many: str) -> str:
    """Числівник з іменником: 1 номер, 4 номери, 208 номерів."""
    tail = count % 100
    if 11 <= tail <= 14:
        word = many
    elif count % 10 == 1:
        word = one
    elif 2 <= count % 10 <= 4:
        word = few
    else:
        word = many
    return f"{count} {word}"


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def year_note(rec: dict[str, Any], year: int, rows: list[dict[str, Any]],
              pages: int) -> str:
    """Опис року для картки в пулі: сайт показує нотатку текстом, а перелік
    номерів (`extra.publication.issues`) не показує ніде."""
    if rec.get("kind") == "book":
        return _book_note(rec, year, pages)
    out: list[str] = []
    organ = organ_for(rec, year)
    if organ:
        out.append(_sentence(organ))
    place = []
    if rec.get("city"):
        place.append(f"Місце видання — {rec['city']}")
    if rec.get("frequency"):
        place.append(f"виходила {rec['frequency']}")
    if place:
        out.append(_sentence("; ".join(place)))
    regular = [r for r in rows if r.get("note") != "додаток"]
    extra = len(rows) - len(regular)
    span = ""
    if regular:
        a, b = regular[0], regular[-1]
        span = (f"; перший — № {a.get('no') or '?'} від {_ua_date(str(a.get('date') or ''))}, "
                f"останній — № {b.get('no') or '?'} від {_ua_date(str(b.get('date') or ''))}")
    out.append(f"За {year} рік у пулі {_n(len(regular), 'номер', 'номери', 'номерів')}"
               + (f" і {_n(extra, 'додаток', 'додатки', 'додатків')}" if extra else "")
               + f", {_n(pages, 'сторінка', 'сторінки', 'сторінок')}{span}.")
    if rec.get("holder"):
        out.append(f"Підшивка: {rec['holder']}.")
    out.append("Текст — PaddleOCR-VL 1.6, хмарний прогін Нишпорки; номери й дати взято "
               "з назв тек сканів, а не з розпізнаного тексту.")
    if rec.get("note"):
        out.append(_sentence(str(rec["note"])))
    return " ".join(out)


def _book_note(rec: dict[str, Any], year: int, pages: int) -> str:
    """Опис книги: без «номерів» і дат випуску — у книги їх немає."""
    out = [f"Друкована книга, {year} р."]
    if rec.get("city"):
        out.append(_sentence(f"Місце видання — {rec['city']}"))
    out.append(f"У пулі {_n(pages, 'сторінка', 'сторінки', 'сторінок')}.")
    if rec.get("holder"):
        out.append(f"Примірник: {rec['holder']}.")
    out.append("Текст — PaddleOCR-VL 1.6, хмарний прогін Нишпорки.")
    if rec.get("note"):
        out.append(_sentence(str(rec["note"])))
    return " ".join(out)


@dataclass
class Adopted:
    """Що `adopt` записав у видання з тек тексту."""

    path: Path
    issues: int
    years: list[int]
    skipped: list[str] = field(default_factory=list)


def adopt(code: str, *, title: str = "", city: str = "",
          issues_root: Path | None = None) -> Adopted:
    """Записати видання з УЖЕ ПРОЧИТАНИХ номерів — без локальних кадрів.

    Кадри газети лежать у чужому сховищі (партнер дав читати свій бакет), а
    тексти номерів — у `derived/print/issues/<код>_<дата>_<номер>/`. Запис
    видання робив лише `cloud go --print` із теки кадрів, тож без неї роки не
    збирались зовсім (16.10.2026, 1 606 номерів «Колективізованого села»).
    Номер ідентифікується за ім'ям прогону й `case_key` його мети
    (`VYD/<КОД>/<рік>`); наскрізного номера в імені прогону немає.
    """
    code = code.upper()
    if not vydannia.is_code(code):
        raise ValueError(f"код видання «{code}» — лише латинка й цифри, від двох знаків")
    root = issues_root or _issues_root()
    data = load_record(code) or {"code": code, "issues": {}, "roots": []}
    data["title"] = title or data.get("title") or ""
    data["city"] = city or data.get("city") or ""
    years: set[int] = set()
    skipped: list[str] = []
    added = 0
    prefix = f"{code.lower()}_"
    for d in sorted(root.glob(f"{prefix}*")) if root.is_dir() else []:
        if not d.is_dir():
            continue
        name = VI.parse_run_name(code, d.name)
        meta = _read_json(d / "_htr_meta.json")
        key = str(meta.get("case_key") or "")
        if name is None or not key.upper().startswith(f"VYD/{code}/"):
            skipped.append(d.name)
            continue
        row = data["issues"].get(d.name) or {}
        if row.get("case_dir") and Path(str(row["case_dir"])).is_dir():
            continue                       # номер із локальними кадрами — не чіпаємо
        data["issues"][d.name] = {"case_dir": "", "out_dir": str(d), "no": name.no,
                                  "no_total": name.no_total, "date": name.date,
                                  "supplement": name.supplement}
        years.add(name.year)
        added += 1
    return Adopted(path=_write_record(data), issues=added, years=sorted(years),
                   skipped=skipped)


def _issues_root() -> Path:
    from nyshporka.cloud import printed

    return printed.out_root()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _issue_from_text(row: dict[str, Any]) -> VI.Issue | None:
    """Номер без локальних кадрів — із теки його тексту.

    Сторінки — ключі `pages` мети в тому порядку, у якому їх читав рушій (за
    іменем кадру); лише їхні імена потрібні збиранню року (`stem` → txt). Якщо
    `htr_case_summary.json` знає більше сторінок, ніж мета, нестача лишається
    видимою: рік із нею не буде повним.
    """
    out = Path(str(row.get("out_dir") or ""))
    date = str(row.get("date") or "")
    if not out.is_dir() or len(date) < 4 or not date[:4].isdigit():
        return None
    meta = _read_json(out / "_htr_meta.json")
    names = sorted(str(k) for k in (meta.get("pages") or {}))
    if not names:
        names = sorted(f"{p.stem}.jpg" for p in out.glob("*.txt"))
    expected = int(_read_json(out / "htr_case_summary.json").get("n_pages_expected") or 0)
    names += [f"__unread_{k:04d}.jpg" for k in range(len(names) + 1, expected + 1)]
    return VI.Issue(no=str(row.get("no") or ""), no_total=str(row.get("no_total") or ""),
                    date=date, year=int(date[:4]), path=out,
                    pages=[out / n for n in names], supplement=bool(row.get("supplement")))


def repoint(out_dirs: dict[str, str]) -> int:
    """Теки, куди наглядач СПРАВДІ покладе текст номерів: ім'я прогону → тека.

    🔴 Наглядач кладе вихід у теку за своїм slug-ім'ям справи
    (`13 (177) 1932-02-01` → `13-177-1932-02-01`), а не за тим, що бачить
    Нишпорка. Ім'я справи міняти не можна — від нього рахуються ключі архівів
    у сховищі. Тому після складання плану записане видання переводиться на
    теки з плану (`cloud.supervised._patch_plan`). Повертає, скільки записів
    змінено.
    """
    changed = 0
    for rec in records():
        touched = False
        for run, out in out_dirs.items():
            row = (rec.get("issues") or {}).get(run)
            if row is not None and row.get("out_dir") != out:
                row["out_dir"] = out
                touched = True
                changed += 1
        if touched:
            path = record_path(str(rec["code"]))
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
    return changed


# ── роки ─────────────────────────────────────────────────────────────────────
@dataclass
class Year:
    """Рік видання, зібраний із номерів."""

    code: str
    year: int
    run_dir: Path
    issues: int
    pages: int
    read: int
    missing_pages: list[str] = field(default_factory=list)
    missing_numbers: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.pages > 0 and self.read == self.pages

    @property
    def key(self) -> str:
        return vydannia.key(self.code, self.year)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "year": self.year, "run": self.run_dir.name,
                "issues": self.issues, "pages": self.pages, "read": self.read,
                "complete": self.complete, "missing_pages": self.missing_pages[:20],
                "missing_numbers": self.missing_numbers}


def _edition_of(rec: dict[str, Any]) -> tuple[VI.Edition | None, dict[str, Path]]:
    """Дерево видання з диска й тека тексту кожного номера (за текою кадрів)."""
    rows = list((rec.get("issues") or {}).values())
    by_dir = {_norm(v.get("case_dir") or ""): Path(str(v.get("out_dir") or ""))
              for v in rows if v.get("case_dir")}
    if rec.get("kind") == "book":
        books = [VI.book_issue(Path(str(v["case_dir"])), int(v["year"])) for v in rows
                 if v.get("case_dir") and v.get("year") and Path(str(v["case_dir"])).is_dir()]
        if not books:
            return None, by_dir
        return VI.Edition(root=books[0].path.parent,
                          title=str(rec.get("title") or rec.get("code") or ""),
                          issues=sorted(books, key=lambda i: i.year)), by_dir
    eds = [VI.scan(Path(r)) for r in rec.get("roots") or [] if Path(r).is_dir()]
    ed: VI.Edition | None = eds[0] if eds else None
    for other in eds[1:]:
        assert ed is not None
        ed.issues += other.issues
        ed.unparsed += other.unparsed
        ed.empty += other.empty
    # Номери без локальних кадрів (`nysh print adopt`): текст є, кадри деінде.
    # Локальна тека номера, якщо вона є, важить більше за запис із тексту.
    have = {i.ident for i in ed.issues} if ed else set()
    remote: list[VI.Issue] = []
    for v in rows:
        if v.get("case_dir") and Path(str(v["case_dir"])).is_dir():
            continue
        iss = _issue_from_text(v) if v.get("date") else None
        if iss is None or iss.ident in have:
            continue
        have.add(iss.ident)
        remote.append(iss)
        by_dir[_norm(iss.path)] = iss.path
    if remote:
        if ed is None:
            ed = VI.Edition(root=editions_dir() / str(rec.get("code") or ""),
                            title=str(rec.get("title") or rec.get("code") or ""))
        ed.issues += remote
    if ed is None:
        return None, by_dir
    ed.issues.sort(key=VI.issue_order)
    return ed, by_dir


def run_dir_for(code: str, year: int) -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().htr_reports / f"vyd_{code.lower()}_{year}"


def assemble(code: str = "") -> list[Year]:
    """Зібрати роки видань із прочитаних номерів. Повторний виклик — те саме.

    Рік складається з номерів у порядку дат, сторінки нумеруються в межах року
    (`0001.txt`…), а `issues.json` поруч каже, з якої сторінки починається
    кожен номер. Сторінка без тексту лишається пропуском у меті (`missing`),
    і такий рік не пакується: пакувальник нумерує сторінки підряд, тож пропуск
    зсунув би всі номери після нього.
    """
    out: list[Year] = []
    for rec in records():
        if code and rec.get("code") != code.upper():
            continue
        ed, by_dir = _edition_of(rec)
        if ed is None:
            continue
        for year in ed.years:
            out.append(_assemble_year(rec, ed, by_dir, year))
    return out


def _assemble_year(rec: dict[str, Any], ed: VI.Edition, by_dir: dict[str, Path],
                   year: int) -> Year:
    code = str(rec["code"])
    run = run_dir_for(code, year)
    tmp = run.with_name(run.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    pages_meta: dict[str, Any] = {}
    source: list[dict[str, Any]] = []
    missing: list[str] = []
    k = 0
    issues = ed.of_year(year)
    for iss in issues:
        text_dir = by_dir.get(_norm(iss.path))
        for frame in iss.pages:
            k += 1
            name = f"{k:04d}"
            src = (text_dir / f"{frame.stem}.txt") if text_dir else None
            row = {"page": name, "no": iss.no, "date": iss.date, "frame": str(frame)}
            if src is not None and src.is_file():
                text = src.read_text(encoding="utf-8")
                (tmp / f"{name}.txt").write_text(text, encoding="utf-8")
                pages_meta[f"{name}.jpg"] = {"lines": sum(1 for ln in text.splitlines()
                                                          if ln.strip()),
                                             "chars": len(text)}
                blocks = src.with_name(f"{frame.stem}.blocks.json")
                if blocks.is_file():
                    shutil.copy2(blocks, tmp / f"{name}.blocks.json")
            else:
                missing.append(f"{_label(iss)} {frame.name}")
            source.append(row)
    meta = {"version": 1, "case_dir": str(ed.root / str(year)),
            "case_key": vydannia.key(code, year), "frames_total": k,
            "model": "PaddleOCR-VL-1.6-0.9B", "engine": "print", "script": "print",
            "device": "vllm", "done": not missing, "failed": [], "missing": missing,
            "pages": pages_meta, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (tmp / "_htr_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    (tmp / "issues.json").write_text(json.dumps(ed.issues_json(year), ensure_ascii=False,
                                                indent=1), encoding="utf-8")
    (tmp / "_print_source.json").write_text(
        json.dumps({"code": code, "title": rec.get("title") or "", "city": rec.get("city") or "",
                    "pages": source}, ensure_ascii=False, indent=1), encoding="utf-8")
    # Підміна цілим каталогом: напівзібраний рік у сторі гірший за старий.
    old = run.with_name(run.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if run.exists():
        os.replace(run, old)
    os.replace(tmp, run)
    shutil.rmtree(old, ignore_errors=True)
    return Year(code=code, year=year, run_dir=run, issues=len(issues), pages=k,
                read=len(pages_meta), missing_pages=missing,
                missing_numbers=ed.missing(year))


def status(code: str = "") -> list[dict[str, Any]]:
    """Видання, роки й прочитане — без жодного запису на диск."""
    out = []
    for rec in records():
        if code and rec.get("code") != code.upper():
            continue
        ed, by_dir = _edition_of(rec)
        years = []
        for y in (ed.years if ed else []):
            pages = read = 0
            for iss in ed.of_year(y) if ed else []:
                text_dir = by_dir.get(_norm(iss.path))
                for frame in iss.pages:
                    pages += 1
                    if text_dir and (text_dir / f"{frame.stem}.txt").is_file():
                        read += 1
            years.append({"year": y, "key": vydannia.key(rec["code"], y),
                          "issues": len(ed.of_year(y)) if ed else 0, "pages": pages,
                          "read": read, "missing_numbers": ed.missing(y) if ed else [],
                          "assembled": run_dir_for(rec["code"], y).is_dir()})
        out.append({"code": rec["code"], "title": rec.get("title") or "",
                    "city": rec.get("city") or "", "roots": rec.get("roots") or [],
                    "years": years,
                    "unparsed": [str(p) for p in (ed.unparsed if ed else [])],
                    "empty": [str(p) for p in (ed.empty if ed else [])]})
    return out
