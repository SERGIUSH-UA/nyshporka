"""📰 Номери друкованого видання з дерева тек: роки, номери, сторінки, пропуски.

Людина, що зняла підшивку газети, кладе її так:

    <Назва>/<РІК>/<N (НАСКРІЗНИЙ) РРРР-ММ-ДД>/<кадри>
    Колективізоване село/1936/3 (770) 1936-01-06/0001.jpg
    Колективізоване село/1936/12-13 (779-780) 1936-01-22/…   ← здвоєний номер
    За ударну працю/1934/2 1934-02-26/…                      ← без наскрізного
    Громадянин/1 (1918-10-24)/…                              ← без теки року
    Колективізоване село/1935/Додаток … 1935-08-12/…         ← додаток

і кілька видань одного міста поруч (`НБУВ/Пирятин/<Назва>/…`).

Номер у році, наскрізний номер за всі роки й дата вже є в імені теки. Звідси
`issues.json` пакета видання (`share/print_pack`) складається без жодного
питання до людини, а наскрізна нумерація дає ще й ЗНАМЕННИК зібрання: яких
номерів у підшивці немає. «Немає» без цього переліку звучало б як «газета
про це не писала», хоча номер просто не знятий.

🔴 Номер газети — не архівна справа. Розбір шляху бібліотеки читав дату з
імені теки як фонд-опис-справу (`… 1934-02-12` → `CASES/1934/2/12`), і різні
газети одного дня (у партнера — сім пар) та номер із додатком того самого дня
діставали одну шифру. Тотожність номера — видання + дата + номер або ознака
додатка (`Issue.ident`), і рахують її тут для всіх: `cloud go --print`,
збирання років і бібліотеки, яка такі теки справами не вважає.

🔴 Модуль без залежностей від `share` і `pagestore` (як і `vydannia`): його
кличуть і `cloud go --print`, і збирання років після забору, і бібліотека.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Кадри, які читає рушій (той самий набір, що в `htr/runner.py::FRAME_EXT`).
FRAME_EXT = frozenset({".jpg", ".jpeg", ".png"})

_NUM = r"\d+(?:\s*[-–]\s*\d+)?"
_DATE_RE = re.compile(r"(?<!\d)(?P<date>(?P<year>\d{4})-(?P<m>\d{2})-(?P<d>\d{2}))(?!\d)")
#: Номер без дати: «3 (770)» · «12-13 (779-780)» · «4(771)» · «№ 5» · «5».
#: Наскрізний номер у дужках необов'язковий: не кожна газета його друкує.
_NO_RE = re.compile(
    rf"^\s*(?:№\s*)?(?P<no>{_NUM})?\s*(?:\(\s*(?P<total>{_NUM})\s*\))?\s*$")
#: Додаток: «Додаток», «додаток до № 111», «Дод.» — ознака будь-де в імені.
_SUPPLEMENT_RE = re.compile(r"(?<!\w)(?:додат\w*|дод\.)", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\s*(?P<year>\d{4})\s*$")
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,23}$")


def _num(value: str | None) -> str:
    """«12 – 13» → «12-13»: один запис номера, хоч як його набрали."""
    return re.sub(r"\s*[-–]\s*", "-", (value or "").strip())


def _span(value: str) -> tuple[int, int] | None:
    """«779-780» → (779, 780); «770» → (770, 770); негодяще → None."""
    parts = [p for p in value.split("-") if p]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    lo, hi = int(parts[0]), int(parts[-1])
    return (lo, hi) if lo <= hi else None


@dataclass(frozen=True)
class IssueName:
    """Розібране ім'я теки номера."""

    no: str              # «3» або «12-13»; порожньо — номера в імені немає
    no_total: str        # «770» або «779-780»; порожньо — наскрізного немає
    date: str            # ISO
    year: int
    supplement: bool = False

    @property
    def ident(self) -> str:
        """Тотожність номера в межах видання: `1936-01-06_3`, `1935-08-12_dod`.

        Дата сама номер не визначає: того самого дня виходять номер і додаток
        до нього, а здвоєний номер має свій запис («12-13»).
        """
        tail = ("dod" + (f"-{self.no}" if self.no else "")) if self.supplement else self.no
        return f"{self.date}_{tail}" if tail else self.date


def parse_issue_name(name: str) -> IssueName | None:
    """Ім'я теки номера → `IssueName` або None.

    Форми: «3 (770) 1936-01-06», «2 1934-02-26», «1 (1918-10-24)» (дата в
    дужках), «Додаток … 1935-08-12». Дата — рівно одна й справжня (місяць і
    день у межах). У звичайному номері, крім номера й наскрізного, нічого
    стороннього бути не може: інакше це не номер, а тека, про яку питають
    людину. Додаток розбирається поблажливіше — у ньому трапляються «до № 111»
    і назва, а тотожність дає дата й сама ознака.
    """
    name = (name or "").strip()
    dates = list(_DATE_RE.finditer(name))
    if len(dates) != 1:
        return None
    m = dates[0]
    month, day = int(m.group("m")), int(m.group("d"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    rest = (name[:m.start()] + " " + name[m.end():]).strip()
    # «1 (1918-10-24)» — від дати лишаються порожні дужки
    rest = re.sub(r"\(\s*\)", " ", rest).strip()
    date, year = m.group("date"), int(m.group("year"))
    if _SUPPLEMENT_RE.search(rest):
        rest = _SUPPLEMENT_RE.sub(" ", rest)
        total_m = re.search(rf"\(\s*({_NUM})\s*\)", rest)
        bare = re.sub(rf"\(\s*{_NUM}\s*\)", " ", rest)
        no_m = re.search(rf"(?<!\d)({_NUM})(?!\d)", bare)
        return IssueName(no=_num(no_m.group(1) if no_m else ""),
                         no_total=_num(total_m.group(1) if total_m else ""),
                         date=date, year=year, supplement=True)
    got = _NO_RE.match(rest)
    if got is None:
        return None
    return IssueName(no=_num(got.group("no")), no_total=_num(got.group("total")),
                     date=date, year=year)


_RUN_TAIL_RE = re.compile(
    r"^(?P<date>(?P<year>\d{4})-(?P<m>\d{2})-(?P<d>\d{2}))(?:_(?P<tail>[^_]+))?$")


def parse_run_name(code: str, run: str) -> IssueName | None:
    """Ім'я прогону номера → `IssueName`; обернене до `<код>_<IssueName.ident>`.

    `kolselo_pyr_1938-03-15_60`, `kolselo_pyr_1935-08-12_dod-111`,
    `kolselo_pyr_1936-01-06`. Наскрізного номера в імені прогону немає — він
    губиться ще при складанні плану, тож `no_total` порожній.
    """
    prefix = f"{code.lower()}_"
    if not run.lower().startswith(prefix):
        return None
    m = _RUN_TAIL_RE.match(run[len(prefix):])
    if m is None:
        return None
    if not (1 <= int(m.group("m")) <= 12 and 1 <= int(m.group("d")) <= 31):
        return None
    date, year, tail = m.group("date"), int(m.group("year")), m.group("tail") or ""
    if tail == "dod" or tail.startswith("dod-"):
        return IssueName(no=tail[4:], no_total="", date=date, year=year, supplement=True)
    return IssueName(no=tail, no_total="", date=date, year=year)


def is_issue_dir_name(name: str) -> bool:
    """Чи ім'я теки — номер друкованого видання (для бібліотеки й розгортання)."""
    return parse_issue_name(name) is not None


@dataclass
class Issue:
    """Один номер: як записаний у теці і які кадри його сторінки."""

    no: str              # «3» або «12-13»
    no_total: str        # «770» або «779-780»; порожньо — наскрізного немає
    date: str            # ISO, з імені теки
    year: int
    path: Path
    pages: list[Path] = field(default_factory=list)
    supplement: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ident(self) -> str:
        return IssueName(self.no, self.no_total, self.date, self.year, self.supplement).ident

    def row(self, first_page: int) -> dict[str, Any]:
        """Рядок `issues.json` (поля, які приймає `share/print_pack._issues`)."""
        out: dict[str, Any] = {"no": self.no, "date": self.date,
                               "first_page": first_page, "pages": len(self.pages)}
        if self.no_total:
            out["no_total"] = self.no_total
        if self.supplement:
            out["note"] = "додаток"
        return out


def issue_order(i: Issue) -> tuple[str, int, int]:
    """Порядок у підшивці: дата, потім номер; додаток — після номера свого дня."""
    sp = _span(i.no)
    return (i.date, 1 if i.supplement else 0, sp[0] if sp else 0)


@dataclass
class Edition:
    """Розібране дерево видання."""

    root: Path
    title: str
    issues: list[Issue] = field(default_factory=list)
    #: Теки, ім'я яких не розібралось як номер, — людині, а не мовчки геть.
    unparsed: list[Path] = field(default_factory=list)
    #: Теки номерів без жодного кадру.
    empty: list[Path] = field(default_factory=list)
    #: Дві теки одного номера (та сама дата й номер): котра з них номер,
    #: вирішує людина, а не порядок обходу.
    dupes: list[tuple[Path, Path]] = field(default_factory=list)

    @property
    def years(self) -> list[int]:
        return sorted({i.year for i in self.issues})

    def of_year(self, year: int) -> list[Issue]:
        return [i for i in self.issues if i.year == year]

    def pages_total(self) -> int:
        return sum(len(i.pages) for i in self.issues)

    def missing(self, year: int | None = None) -> list[str]:
        """Наскрізні номери, яких бракує між першим і останнім у зібранні.

        Рахується по всіх роках разом: наскрізна нумерація через межу року не
        переривається, і номер, що мав би вийти 31 грудня, інакше пропав би з
        обох років. `year` — лише ті пропуски, що лежать між номерами цього року.
        Додаток свого наскрізного номера не має, тож у знаменник не йде.
        """
        def spans(issues: list[Issue]) -> list[int]:
            return [n for i in issues if not i.supplement and (sp := _span(i.no_total))
                    for n in range(sp[0], sp[1] + 1)]

        have = set(spans(self.issues))
        if not have:
            return []
        mine = spans(self.of_year(year)) if year is not None else sorted(have)
        if not mine:
            return []
        return [str(n) for n in range(min(mine), max(mine) + 1) if n not in have]

    def issues_json(self, year: int) -> list[dict[str, Any]]:
        """`issues.json` одного року: `first_page` — у нумерації сторінок року."""
        rows, page = [], 1
        for i in self.of_year(year):
            rows.append(i.row(page))
            page += len(i.pages)
        return rows


def frames_of(folder: Path) -> list[Path]:
    """Кадри теки в тому порядку, у якому їх читає рушій (за іменем)."""
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in FRAME_EXT)


def _issue(folder: Path) -> Issue | None:
    got = parse_issue_name(folder.name)
    if got is None:
        return None
    return Issue(no=got.no, no_total=got.no_total, date=got.date, year=got.year,
                 path=folder, pages=frames_of(folder), supplement=got.supplement)


def _subdirs(d: Path) -> list[Path]:
    try:
        return sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith("_"))
    except OSError:
        return []


def _is_year(d: Path) -> bool:
    return bool(_YEAR_RE.match(d.name))


def _is_year_of_issues(d: Path) -> bool:
    return _is_year(d) and any(is_issue_dir_name(c.name) for c in _subdirs(d))


def is_edition_root(d: Path) -> bool:
    """Тека видання: номери просто в ній або в її теках років."""
    return any(is_issue_dir_name(c.name) or _is_year_of_issues(c) for c in _subdirs(d))


def find_editions(root: Path, *, max_depth: int = 4) -> list[Path]:
    """Теки видань під `root` (і сама `root`), без заходу всередину видання.

    `НБУВ/Пирятин` з трьома газетами дає три теки. Тека року з номерами — теж
    видання (один його рік), як і в `scan`.
    """
    root = Path(root)
    if is_edition_root(root) or _is_year_of_issues(root):
        return [root]
    out: list[Path] = []
    level = [root]
    for _ in range(max_depth):
        nxt: list[Path] = []
        for d in level:
            for c in _subdirs(d):
                if is_issue_dir_name(c.name) or _is_year(c):
                    continue
                (out if is_edition_root(c) else nxt).append(c)
        level = nxt
    return sorted(out)


def scan(root: Path) -> Edition:
    """Розібрати теку одного видання або одного його року.

    Номери лежать у теках років (`<Назва>/<РІК>/<номер>`), просто в теці
    видання (`<Назва>/<номер>`), або і так, і так. Тека, що не є ні роком, ні
    номером, іде в `unparsed` — людині.

    Номери впорядковуються за датою, у межах дати — за номером, додаток — після
    номера свого дня: так вони й ідуть у підшивці, і так нумеруються сторінки
    року.
    """
    root = Path(root)
    subs = _subdirs(root)
    if _is_year(root) and not any(_is_year(c) for c in subs):
        title, candidates = root.parent.name, subs
    else:
        title, candidates = root.name, []
        for c in subs:
            candidates += _subdirs(c) if _is_year(c) else [c]
    ed = Edition(root=root, title=title)
    seen: dict[str, Path] = {}
    for d in candidates:
        got = _issue(d)
        if got is None:
            ed.unparsed.append(d)
        elif not got.pages:
            ed.empty.append(d)
        elif got.ident in seen:
            ed.dupes.append((seen[got.ident], d))
        else:
            # Рік номера — з дати в імені, а не з теки року: номер, покладений
            # не в ту теку, все одно належить своєму року.
            seen[got.ident] = d
            ed.issues.append(got)
    ed.issues.sort(key=issue_order)
    return ed


#: Українська транслітерація (постанова КМУ 2010, без позиційних правил): код
#: видання українською назвою має читатись так, як її пише українець, — «Pyr»,
#: а не «Pir». Решту письма (російське, польське) бере загальна нормалізація.
_UK_LAT = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
           "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
           "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
           "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
           "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "’": ""}


def _latin(word: str) -> str:
    """Слово латинкою: українські літери — таблицею, решта — загальною нормалізацією."""
    from nyshporka.utils.translit import normalize_for_matching

    # Нормалізація для зіставлення зводить і латинське «y» до «i», тож вона
    # бере лише те, чого таблиця не знає (ы, ё, ł, ó…), а не готову латинку.
    out = "".join(_UK_LAT[ch] if ch in _UK_LAT
                  else (ch if ch.isascii() else normalize_for_matching(ch))
                  for ch in (word or "").casefold())
    return re.sub(r"[^a-z0-9]", "", out)


def suggest_code(title: str, city: str = "") -> str:
    """Код видання з назви й міста: «Колективізоване село» + «Пирятин» → KOLSELO_PYR.

    Лише пропозиція: код іде в ключ `VYD/<код>/<рік>` назавжди, тож його
    підтверджує людина (`--vydannia`). Місто в коді обов'язкове там, де воно
    відоме: районні газети з однаковою назвою виходили в десятках міст.
    """
    words = [_latin(w) for w in re.split(r"[\s\-–«»\"'’.,]+", title or "") if w]
    words = [w for w in words if w]
    if not words:
        head = "VYD"
    elif len(words) == 1:
        head = words[0][:8]
    else:
        head = words[0][:3] + "".join(w[:4] for w in words[1:3])
    tail = _latin(city or "")[:3]
    code = (head + (f"_{tail}" if tail else "")).upper()
    if not code[0].isalpha():
        code = "V" + code
    code = code[:24]
    return code if _CODE_RE.match(code) else "VYD"
