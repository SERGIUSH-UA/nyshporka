"""🏛 ARCHIUM — каталог і скани обласного архіву (перша реалізація: ДАХмО).

Сайт на Laravel. API віддає не JSON-дані, а HTML-фрагменти в конверті
`{"Status":1,"View":"<html>"}`; GET без авторизації. Ієрархія:
група фондів → фонд → опис → справа → кадри.

🔴 головне, І це не дрібниця: вбудований пошук сайту індексує лише назви фондів
і описів — не заголовки справ. Запит «Борсуківці», який є реальним заголовком
справи, дає там нуль. Тому `search` тут працює не по сайту, а по каталогу,
зібраному обходом; і доти, доки обходу не було, нуль означає «ми не дивились»,
а не «немає».

Ця різниця варта окремого коду, бо ціна помилки асиметрична: «немає» закриває
напрям пошуку назавжди, а коштує це рівно одного слова у відповіді. Тому
`search` без каталогу не повертає порожній список — він кидає `SourceError` із
готовою командою обходу.

Адресація (`ref`), непрозора для решти застосунку:

    group:<id>   група фондів
    fond:<id>    фонд         → описи
    inv:<id>     опис         → справи
    file:<id>    справа       → кадри (manifest / fetch)
"""
from __future__ import annotations

import contextlib
import csv
import datetime as _dt
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Iterator

from nyshporka.archives.pack import Site
from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    ProgressFn,
    SourceError,
)
from nyshporka.sources.http import Fetcher, HttpError
from nyshporka.utils.atomic import atomic_write_bytes

BASE = "https://archium.dahmo.gov.ua"

#: Сервер не обмежує; більшість описів влазить в один запит.
PAGE_LIMIT = 2000

_ARK_RE = re.compile(r"(\d+)\s*арк")
_PAGE_RE = re.compile(r"[?&]Page=(\d+)")
_FILE_ID_RE = re.compile(r"/files/(\d+)/")
_INV_ID_RE = re.compile(r"/inventories/(\d+)/")
_FOND_ID_RE = re.compile(r"/fonds/(\d+)/")
_COUNT_RE = re.compile(r"([\d ]+)\s*справ")
_DATES_RE = re.compile(r"(\d{4}\s*[-–]\s*\d{4}|\d{4})")
#: (id кадру, номер сторінки). Порядок сторінок дає `alt`, а не числовий id —
#: id у переглядачі перемішані.
_VIEWER_PAGE_RE = re.compile(
    r'data-observe-src="/static/files/\d{3}/(\d+)\.jpg"[^>]*?alt="(\d+)"')
_VIEWER_FILE_RE = re.compile(r"#file-(\d+)")


def _parser(html: str) -> Any:
    try:
        from selectolax.parser import HTMLParser
    except ImportError as exc:  # pragma: no cover — extras `archives`
        raise SourceError(
            "для роботи з ARCHIUM потрібен розбирач HTML: "
            "pip install 'nyshporka[archives]'") from exc
    return HTMLParser(html)


@dataclass(frozen=True)
class CaseRow:
    """Рядок опису так, як його віддає сайт."""

    file_id: str
    number: str
    date: str
    description: str
    sheets: int | None


def parse_cases(view_html: str) -> list[CaseRow]:
    out: list[CaseRow] = []
    for row in _parser(view_html).css("div.row"):
        left = row.css_first("div.left")
        if not left:
            continue
        link = left.css_first("a")
        m = _FILE_ID_RE.search(link.attributes.get("href", "") if link else "")
        if not m:
            continue
        date_node = left.css_first("span.date")
        right = row.css_first("div.right")
        desc = right.text(strip=True) if right else ""
        ark = _ARK_RE.search(desc)
        out.append(CaseRow(
            file_id=m.group(1),
            number=link.text(strip=True) if link else "",
            date=date_node.text(strip=True) if date_node else "",
            description=desc,
            sheets=int(ark.group(1)) if ark else None))
    return out


@dataclass(frozen=True)
class SearchRow:
    """Знахідка живого пошуку сайту: шифра й viewer-id одним рядком.

    🔥 Цінність саме в тому, що обидва тут разом. Формула «viewer-id = опора +
    (номер справи − опора)» має дрейф — літерні справи (2а, 704А) займають id,
    але не займають номера, — тож далеко від опорної точки вона бреше на
    десяток. Пошук сайту віддає адресу без арифметики й без обходу.
    """

    fond: str
    opys: str
    spr: str
    title: str
    date: str
    sheets: int | None
    file_id: str

    @property
    def shifra(self) -> str:
        return f"ф.{self.fond} оп.{self.opys} спр.{self.spr}"


def parse_search(view_html: str) -> list[SearchRow]:
    """Розбір видачі `/api/v1/search/act/`.

    Шифра лежить окремими підписами («Фонд 127», «Опис 2», «Справа 53»), а не
    рядком, тож збирається з них, а не вигризається регексом із заголовка.
    """
    out: list[SearchRow] = []
    for row in _parser(view_html).css("div.row"):
        left = row.css_first("div.left")
        right = row.css_first("div.right")
        if not left or not right:
            continue
        link = right.css_first("a")
        m = _FILE_ID_RE.search(link.attributes.get("href", "") if link else "")
        if not m:
            continue
        parts: dict[str, str] = {}
        for span in left.css("span"):
            text = span.text(strip=True)
            key, _, value = text.partition(" ")
            if value:
                parts[key.lower()] = value.strip()
        title_node = right.css_first("p.doc-title")
        date_node = right.css_first("p.date")
        date = date_node.text(strip=True) if date_node else ""
        ark = _ARK_RE.search(date)
        out.append(SearchRow(
            fond=parts.get("фонд", ""), opys=parts.get("опис", ""),
            spr=parts.get("справа", ""),
            title=title_node.text(strip=True) if title_node else "",
            # У підписі дата й обсяг стоять разом («1806, 16 аркушів»); обсяг
            # виноситься в поле, бо ним звіряють повноту завантаження.
            date=date.split(",")[0].strip(),
            sheets=int(ark.group(1)) if ark else None,
            file_id=m.group(1)))
    return out


def parse_inventories(fond_html: str) -> tuple[str, list[Node]]:
    """(назва фонду, описи). `/api/v1/fonds` не існує — описи рендеряться інлайн."""
    tree = _parser(fond_html)
    head = tree.css_first("h1.head-title")
    title = head.text(strip=True) if head else ""
    out: list[Node] = []
    seen: set[str] = set()
    for row in tree.css("div.thin-row"):
        link = row.css_first("div.left a")
        if not link:
            continue
        m = _INV_ID_RE.search(link.attributes.get("href", "") or "")
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        right = row.css_first("div.right")
        rtext = right.text(strip=True) if right else ""
        dm = _DATES_RE.search(rtext)
        cm = _COUNT_RE.search(rtext)
        label = link.text(strip=True)
        if dm:
            label += f" · {dm.group(1).replace(' ', '')}"
        out.append(Node(ref=f"inv:{m.group(1)}", label=label, kind="folder",
                        frames=int(cm.group(1).replace(" ", "")) if cm else None))
    # Розмітка сторінки міняється частіше за адреси. Якщо структурний розбір дав
    # нуль — беремо будь-які посилання на описи: гірший підпис кращий за
    # порожній фонд, бо порожній читається як «нічого немає».
    if not out:
        for a in tree.css("a"):
            m = _INV_ID_RE.search(a.attributes.get("href", "") or "")
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(Node(ref=f"inv:{m.group(1)}", label=a.text(strip=True)))
    return title, out


def parse_fonds(view_html: str) -> list[Node]:
    out: list[Node] = []
    for tr in _parser(view_html).css("table.fond-groups tbody tr"):
        tds = tr.css("td")
        if len(tds) < 4:
            continue
        link = tds[1].css_first("a")
        m = _FOND_ID_RE.search(link.attributes.get("href", "") if link else "")
        if not m:
            continue
        no = tds[0].text(strip=True)
        title = link.text(strip=True) if link else ""
        dates = tds[2].text(strip=True)
        out.append(Node(ref=f"fond:{m.group(1)}",
                        label=f"ф.{no} {title}" + (f" · {dates}" if dates else "")))
    return out


def last_page(view_html: str) -> int:
    pages = [int(m) for m in _PAGE_RE.findall(view_html)]
    return max(pages) if pages else 1


def viewer_pages(html: str) -> list[tuple[int, int]]:
    """[(id зображення, номер сторінки)] у правильному порядку.

    🔴 Id зображень у переглядачі перемішані, а порядок аркушів несе `alt`.
    Взяти їх у порядку появи в документі означає отримати справу, зшиту
    навмання, — і виявиться це аж на читанні, коли записи не сходяться з датами.
    """
    pairs = [(int(i), int(p)) for i, p in _VIEWER_PAGE_RE.findall(html)]
    if pairs:
        return pairs
    seen: set[int] = set()
    out: list[tuple[int, int]] = []
    for m in _VIEWER_FILE_RE.finditer(html):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append((n, len(out) + 1))
    return out


@dataclass(frozen=True)
class CaseMeta:
    """Шифра справи, прочитана зі сторінки переглядача.

    Внутрішні `fond_id` та `inv_id` цінні окремо: сайт адресує фонд і опис
    власними номерами, які з архівною шифрою не пов'язані ніяк, а знайти їх
    більше нізвідки.
    """

    fond: str = ""
    opys: str = ""
    spr: str = ""
    fond_id: str = ""
    inv_id: str = ""

    def __bool__(self) -> bool:
        return bool(self.fond and self.spr)


def case_meta(html: str) -> CaseMeta:
    """Шифра зі сторінки переглядача; порожня — сторінки справи тут немає.

    🔴 Єдина ознака, за якою можна відрізнити «справи в цьому архіві не
    оцифровано» від «справа є». Код відповіді для цього не годиться: заміряно
    на живому сайті — на неоцифровану справу ARCHIUM віддає HTTP 200 і головну
    сторінку (9.9 КБ, жодного кадру), а не 404. Той, хто перевіряє статус,
    дістає «все гаразд» і порожній результат, і читає це як «кадри скінчились».
    """
    block = re.search(r'<div class="description".*?</ul>', html, re.S)
    if not block:
        return CaseMeta()
    b = block.group(0)
    spr = re.search(r'/files/\d+/"[^>]*>\s*Справа(?:&nbsp;|\s)*([^<\s]+)', b)
    fond = re.search(r'Фонд\s*<a href="/fonds/(\d+)/"[^>]*>\s*([^<\s]+)', b)
    opys = re.search(r'Опис\s*<a href="/inventories/(\d+)/"[^>]*>\s*([^<\s]+)', b)
    return CaseMeta(
        fond=fond.group(2) if fond else "",
        opys=opys.group(2) if opys else "",
        spr=spr.group(1) if spr else "",
        fond_id=fond.group(1) if fond else "",
        inv_id=opys.group(1) if opys else "")


def image_url(image_id: int, base: str = BASE) -> str:
    """Адреса кадру. `base` із дефолтом: рушій спільний, хости різні."""
    s = f"{image_id:06d}"
    return f"{base}/static/files/{s[:3]}/{s}.jpg"


def _flat(s: str) -> str:
    """Один рядок без табуляцій — інакше TSV розпадеться посеред каталогу."""
    return " ".join((s or "").split())


def _norm(s: str) -> str:
    """Порівняння заголовків: апостроф і `і`/`и` в українських назвах пливуть."""
    s = s.casefold().replace("’", "'").replace("`", "'").replace("ʼ", "'")
    return re.sub(r"[^\w']+", " ", s).strip()


def _num(s: object) -> str | None:
    """Перше число з поля каталогу, без провідних нулів.

    Каталог пише «Опис 1» і «Справа 0114» там, де людина набирає «1» і «114»:
    звірка сирих рядків не збіглася б жодного разу.
    """
    m = re.search(r"\d+", str(s or ""))
    return str(int(m.group())) if m else None



@lru_cache(maxsize=8)
def _tsv_rows(path: Path, mtime_ns: int, size: int) -> int | None:
    """Скільки рядків у зібраному каталозі. Кешується штампом файлу.

    ⚠ Ключ кешу несе `mtime`/`size` навмисно: після нового обходу число мусить
    змінитись, а кеш за самим шляхом віддавав би старе — тобто знаменник
    відставав би від даних мовчки.
    """
    _ = (mtime_ns, size)
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return max(0, sum(1 for _line in fh) - 1)
    except OSError:
        return None

class ArchiumSource:
    """Джерело ARCHIUM. Каталог для пошуку читається з робочого простору."""

    id = "archium"
    label = "ARCHIUM (ДАХмО)"
    caps = frozenset({"search", "browse", "manifest", "fetch", "address"})

    #: Куди обхід складає каталог. Відносно кореня простору.
    #: ⚠ Лишається константою класу: на неї спираються тести, і для ДАХмО вона
    #: дорівнює тому, що рахує `catalog_rel` за кодом архіву.
    CATALOG_REL = Path("data") / "raw" / "dahmo_archium" / "_crawl" / "cases.tsv"

    def __init__(self, workspace: Path | None = None, *,
                 site: Site | None = None, repo: str = "DAHMO",
                 fetcher: Fetcher | None = None) -> None:
        """`site` порожній — майданчик ДАХмО, як було до мультихостовості.

        🔴 `id` і `label` стають атрибутами екземпляра: один рушій обслуговує
        кілька архівів, а `id` їде у «де шукали» кожної відповіді. Спільне ім'я
        на два різні архіви зробило б знаменник пошуку неправдивим — «шукали в
        archium» не сказало б, у якому саме.
        """
        self.workspace = Path(workspace) if workspace else None
        self.repo = (repo or "DAHMO").upper()
        self.site = site or self._default_site()
        self.base = self.site.url or BASE
        self.id = self.site.source_id or f"archium-{self.repo.lower()}"
        self.label = f"ARCHIUM ({self._repo_label()})"
        self.http = fetcher or Fetcher(base=self.base)

    def _default_site(self) -> Site:
        """Майданчик із паку, а якщо його там немає — зашитий ДАХмО.

        Фолбек не декоративний: пак перекривається файлом користувача, і
        накладка, що не знає про майданчики, інакше лишила б джерело без адреси.
        """
        from nyshporka.archives import active

        found = active().site(self.repo, "archium")
        return found or Site(engine="archium", url=BASE, source_id="archium")

    def _repo_label(self) -> str:
        from nyshporka.archives import active

        return active().repo_label(self.repo)

    @property
    def slug(self) -> str:
        """Тека архіву в просторі: `dahmo_archium`, `cdiak_archium`."""
        return f"{self.repo.lower()}_archium"

    @property
    def catalog_rel(self) -> Path:
        """Те саме, що `CATALOG_REL`, але за кодом архіву (для ДАХмО збігається)."""
        return Path("data") / "raw" / self.slug / "_crawl" / "cases.tsv"

    @property
    def state_rel(self) -> Path:
        return Path("data") / "raw" / self.slug / "_crawl" / "state.json"

    # ── каталог ──────────────────────────────────────────────────────────────

    @property
    def catalog_path(self) -> Path | None:
        return (self.workspace / self.catalog_rel) if self.workspace else None

    @staticmethod
    def bundled_catalog() -> tuple[Path, Path] | None:
        """(стиснений TSV, сайдкар) зрізу, що їде разом із пакетом.

        🔴 Саме він робить застосунок корисним до першого завантаження. Аудиторія
        «не знаю, де шукати» не має ні сканів, ні відеокарти — і без готового
        зрізу мусила б спершу години обходити чужий сайт, щоб дізнатись, чи
        існує потрібна справа взагалі.
        """
        d = Path(__file__).resolve().parent.parent / "archives" / "data"
        blob = d / "dahmo_archium_cases.tsv.gz"
        meta = d / "dahmo_archium_cases.json"
        return (blob, meta) if blob.is_file() else None

    def _bundled_for_site(self) -> tuple[Path, Path] | None:
        """Зріз каталогу цього майданчика.

        ⚠ Для ДАХмО навмисно йде через `self.bundled_catalog()`: та лишається
        статичною й без аргументів, бо наявні тести і кличуть її на класі, і
        підміняють. Виклик через екземпляр зберігає обидві можливості.
        """
        if self.repo == "DAHMO":
            return self.bundled_catalog()
        name = self.site.bundled
        if not name:
            return None
        d = Path(__file__).resolve().parent.parent / "archives" / "data"
        blob = d / name
        meta = blob.with_suffix("").with_suffix(".json")
        return (blob, meta) if blob.is_file() else None

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Звідки братимемо рядки: `workspace` (свіжіший) чи `bundled`.

        Пріоритет у зібраного на місці — він новіший за побудовою. Зріз у
        пакеті лишається запасним і ніколи не перекриває власний обхід.
        """
        import json

        path = self.catalog_path
        if path is not None and path.is_file():
            st = path.stat()
            return "workspace", {
                "path": str(path),
                # 🔴 Знаменник власного обходу теж мусить бути числом. Без
                # нього перелік джерел казав «зібрано на місці» — і не казав,
                # скільки там справ, тобто нуль пошуку лишався без ваги.
                "rows": _tsv_rows(path, st.st_mtime_ns, st.st_size),
                "taken": _dt.date.fromtimestamp(st.st_mtime).isoformat()}
        got = self._bundled_for_site()
        if got is None:
            return "none", {}
        blob, meta_path = got
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        return "bundled", {"path": str(blob), "taken": meta.get("taken", ""),
                           "rows": meta.get("rows"), "source": meta.get("source", "")}

    def _catalog_rows(self) -> Iterator[dict[str, str]]:
        kind, info = self.catalog_source()
        if kind == "workspace":
            with Path(info["path"]).open(encoding="utf-8", newline="") as fh:
                yield from csv.DictReader(fh, delimiter="\t")
        elif kind == "bundled":
            import gzip

            with gzip.open(info["path"], "rt", encoding="utf-8", newline="") as fh:
                yield from csv.DictReader(fh, delimiter="\t")

    #: Скільки сторінок живого пошуку гортати щонайбільше. Стеля навмисна:
    #: канал точковий («Шупики метрична»), і сотня сторінок на запит з одного
    #: поширеного слова — це вже не пошук справи, а обхід чужим коштом.
    LIVE_PAGES = 5

    def live_search(self, q: str, *, limit: int = 30, fond: str = "") -> list[SearchRow]:
        """Пошук САЙТУ, без каталогу на диску: слово в заголовку → шифра + viewer-id.

        🔴 Канал існує, і його довго не було в застосунку через хибний висновок,
        що сайт заголовків справ не індексує. Індексує: `/api/v1/search/act/`
        віддає рівно те, чого бракує, — фонд, опис, номер справи й `/files/<id>/`,
        тобто адресу для завантажувача. Саме так знайшлась спр.144, тоді як
        арифметика по опорній точці давала сусідній id.

        🪤 `FondNumber` сервер приймає й ІГНОРУЄ: запит «1662» з фондом 127
        віддає справи фонду 57. Тому фонд відсівається тут, на розібраних
        рядках, — інакше звуження було б удаваним, а видача чужого фонду
        читалась би як «ваша справа знайшлась».

        ⚠ Шукає лише по оцифрованих і лише за текстом заголовка: номер справи в
        заголовку не стоїть, тож спитати цей канал ШИФРОЮ не можна.
        """
        needle = (q or "").strip()
        if not needle:
            return []
        want = _num(fond) if fond else None
        out: list[SearchRow] = []
        with self.http.client() as c:
            for page in range(1, self.LIVE_PAGES + 1):
                url = (f"/api/v1/search/act/?Limit={min(limit, 100)}&Page={page}"
                       f"&Search={quote(needle)}&Type=digitized")
                view = self.http.get(url, client=c).json().get("View", "") or ""
                rows = parse_search(view)
                out += [r for r in rows if want is None or _num(r.fond) == want]
                # Пагінації в розмітці немає, тож кінець видно лише по неповній
                # сторінці — і по ній же зупиняємось, не питаючи наступну.
                if len(rows) < min(limit, 100) or len(out) >= limit:
                    break
        return out[:limit]

    def _live_hits(self, q: str, *, limit: int, note: str) -> list[Hit]:
        return [Hit(
            source=self.id,
            ref=f"file:{r.file_id}",
            title=r.title[:200],
            years=r.date,
            shifra=r.shifra,
            repo=self.repo,
            archive=self.repo,
            fond=r.fond,
            frames=r.sheets,
            acquirable=True,
            note=note) for r in self.live_search(q, limit=limit)]

    #: Що саме відповіло, коли відповів сайт. Примітка не косметична: у живого
    #: каналу інша межа, ніж у каталогу, і за нею читається його нуль.
    LIVE_NOTE = "живий пошук сайту · лише оцифровані · за словами заголовка"

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Пошук по каталогу справ: зібраному на місці, вкладеному — або живому.

        🔴 Порожній результат тут не є негативним результатом двічі. По-перше,
        вкладений зріз старіє: архів додає описи, і «не знайшлось» у ньому
        означає «не було на дату зрізу». По-друге, каталогу може не бути зовсім.
        Обидві межі називаються у примітці кожної знахідки й у відмові.

        🔥 Тому там, де каталог мовчить, питається сам сайт. Доти відповіддю
        була відмова з порадою зібрати каталог обходом — тобто години роботи
        там, де на питання відповідає один запит. Для ЦДІАК каталогу немає
        взагалі, і застосунок не вмів знайти жодної справи цього архіву.
        """
        kind, info = self.catalog_source()
        if kind == "none":
            return self._live_hits(q, limit=limit, note=self.LIVE_NOTE)
        needle = _norm(q)
        if not needle:
            return []
        note_tail = ""
        if kind == "bundled" and info.get("taken"):
            note_tail = f" · зріз каталогу від {info['taken']}"
        out: list[Hit] = []
        for row in self._catalog_rows():
            hay = _norm(f"{row.get('description', '')} {row.get('case_no', '')}")
            if needle not in hay:
                continue
            out.append(Hit(
                source=self.id,
                ref=f"file:{row.get('file_id', '')}",
                title=(row.get("description") or "")[:200],
                years=row.get("date") or "",
                shifra=f"ф.{row.get('fond_no', '')} {row.get('inv_label', '')} "
                       f"{row.get('case_no', '')}".strip(),
                # Фонд розібраним полем, а не лише всередині шифри: з нього
                # починається оцінка «чи варто збирати реєстр цього фонду».
                repo=self.repo,
                archive=self.repo,
                fond=str(row.get("fond_no") or ""),
                frames=int(row["sheets"]) if (row.get("sheets") or "").isdigit() else None,
                acquirable=True,
                note=((row.get("fond_title") or "")[:110] + note_tail).strip()))
            if len(out) >= limit:
                break
        if not out:
            # 🔴 Нуль каталогу — це нуль ЗРІЗУ, а не архіву: обхід міг спинитись
            # на половині, а вкладений пак узагалі знятий колись. Питати після
            # цього сам сайт коштує один запит, і саме він відповідає про те,
            # що додали після зрізу.
            return self._live_hits(q, limit=limit,
                                   note=f"{self.LIVE_NOTE} · каталог мовчав")
        return out

    def find_case(self, fond: str, opys: str, spr: str, *,
                  repo: str = "") -> list[Hit]:
        """Справа за ШИФРОЮ, а не за словом із заголовка.

        🔴 Каталог носив фонд, опис і номер справи окремими полями з першого
        дня, а пошук звіряв лише опис і номер справи як ТЕКСТ. Тому «127-1078-1662»
        не знаходило нічого: три числа поспіль не трапляються в жодному
        заголовку. Прохід той самий по тому самому TSV, тож дорожче не стало.

        ⚠ Номери звіряються нормалізованими з обох боків: каталог пише «Опис 1»
        і «Справа 0114» там, де людина набрала «1» і «114».
        """
        kind, _ = self.catalog_source()
        if kind == "none":
            # ⚠ Живий пошук сайту тут НЕ рятує, і сказати про це треба одразу:
            # він шукає за текстом заголовка, а номер справи в заголовку не
            # стоїть. Тож замість самої лише поради «зберіть каталог» (години)
            # називається канал, який працює зараз, — слово з назви справи.
            raise SourceError(
                "каталог справ недоступний: ні зібраного обходом, ні вкладеного "
                "в пакет — а за шифрою сайт не шукає, лише за словами заголовка. "
                "Зараз: `nysh find <слово з назви>` (живий пошук сайту). "
                "Назавжди: `nysh crawl archium`.")
        if repo and repo != self.repo:
            return []
        want = (_num(fond), _num(opys), _num(spr))
        out: list[Hit] = []
        for row in self._catalog_rows():
            got = (_num(row.get("fond_no")), _num(row.get("inv_label")),
                   _num(row.get("case_no")))
            if got != want or None in got:
                continue
            out.append(Hit(
                source=self.id,
                ref=f"file:{row.get('file_id', '')}",
                title=(row.get("description") or "")[:200],
                years=row.get("date") or "",
                shifra=f"ф.{row.get('fond_no', '')} {row.get('inv_label', '')} "
                       f"{row.get('case_no', '')}".strip(),
                repo=self.repo,
                archive=self.repo,
                fond=str(row.get("fond_no") or ""),
                frames=int(row["sheets"]) if (row.get("sheets") or "").isdigit() else None,
                acquirable=True,
                note=(row.get("fond_title") or "")[:110].strip()))
        return out

    # ── дерево ───────────────────────────────────────────────────────────────

    def browse(self, ref: str | None = None) -> list[Node]:
        if not ref:
            # Групи фондів жорстко задані сайтом і окремого списку в API не мають,
            # тож приходять паком — разом з адресою майданчика.
            if self.site.groups:
                return [Node(ref=f"group:{gid}", label=label)
                        for gid, label in self.site.groups]
            if self.site.fond_groups:
                return [Node(ref="group:1", label="Фонди давніх актів (1739-1921)"),
                        Node(ref="group:2", label="Фонди радянського періоду"),
                        Node(ref="group:3", label="Фонди особового походження"),
                        Node(ref="group:4", label="Колекції")]
            # 🔴 Порожній список тут читався б як «архів порожній», а це неправда:
            # у цього майданчика просто немає запиту на дерево груп (він віддає
            # 500). Фонд тут знаходять за номером або за назвою.
            raise SourceError(
                f"{self.label}: переліку груп фондів у цього архіву немає — "
                f"його API на такий запит відповідає помилкою. Фонд шукайте за "
                f"номером: `nysh browse {self.id} fond:<id>`.")
        kind, _, ident = ref.partition(":")
        if kind == "group":
            return self._group_fonds(ident)
        if kind == "fond":
            return parse_inventories(self.http.get(f"/fonds/{ident}/").text)[1]
        if kind == "inv":
            return self._inventory_cases(ident)
        raise SourceError(f"незрозуміла адреса: {ref!r}")

    def _fonds(self, group_id: str | None) -> list[Node]:
        """Перелік фондів: у майданчика з групами — по групі, без груп — суцільно.

        🔴 `group_id=None` — не косметика. У майданчика без груп
        `/api/v1/fond-groups/1/` віддає HTTP 500, тож обхід, який завжди питає
        групу, для такого архіву неможливий у принципі. Гірше за саме падіння
        те, як воно виглядає: помилка звинувачує відсічку за темпом або
        лежачий хост, тобто постійну структурну невідповідність подає як
        тимчасову мережеву — і той, хто це побачив, чекає й пробує ще раз.
        Розмітка обох перекликів однакова (`table.fond-groups`), тож розбирає
        їх той самий `parse_fonds`.
        """
        node = f"/api/v1/fond-groups/{group_id}/" if group_id else "/api/v1/fonds/"

        def url(page: int) -> str:
            return (f"{node}?Limit={PAGE_LIMIT}&Page={page}"
                    f"&SortField=FondNumber&SortOrder=asc")

        with self.http.client() as c:
            view = self.http.get(url(1), client=c).json().get("View", "") or ""
            out = parse_fonds(view)
            for page in range(2, last_page(view) + 1):
                nxt = self.http.get(url(page), client=c).json().get("View", "") or ""
                out.extend(parse_fonds(nxt))
        return out

    def _group_fonds(self, group_id: str) -> list[Node]:
        return self._fonds(group_id)

    def _inventory_rows(self, inv_id: str) -> list[CaseRow]:
        def url(page: int) -> str:
            return f"/api/v1/inventories/{inv_id}?Limit={PAGE_LIMIT}&Page={page}"

        rows: list[CaseRow] = []
        with self.http.client() as c:
            view = self.http.get(url(1), client=c).json().get("View", "") or ""
            rows += parse_cases(view)
            for page in range(2, last_page(view) + 1):
                nxt = self.http.get(url(page), client=c).json().get("View", "") or ""
                rows += parse_cases(nxt)
        return rows

    def _inventory_cases(self, inv_id: str) -> list[Node]:
        rows = self._inventory_rows(inv_id)
        return [Node(ref=f"file:{r.file_id}",
                     label=f"{r.number} · {r.description[:140]}",
                     kind="case", frames=r.sheets) for r in rows]

    # ── обхід каталогу ───────────────────────────────────────────────────────

    #: Стан обходу — щоб перерваний краул продовжувався, а не починався заново.
    STATE_REL = Path("data") / "raw" / "dahmo_archium" / "_crawl" / "state.json"

    #: Групи фондів. Дефолт — давні акти: там метрики, сповідки й ревізії.
    DEFAULT_GROUPS = ("1",)

    CATALOG_FIELDS = ("group_id", "fond_id", "fond_no", "fond_title", "inv_id",
                      "inv_label", "file_id", "case_no", "date", "sheets",
                      "description")

    def _walk_groups(self, groups: tuple[str, ...] | None) -> tuple[str | None, ...]:
        """Що саме обходити: групи фондів або суцільний перелік.

        🔴 Мовчки зігнорувати переданий `--groups` там, де груп немає,
        не можна: людина просила частину архіву, а дістала б увесь — і дізналась
        би про це аж за часом обходу.
        """
        if not self.site.fond_groups:
            if groups:
                raise SourceError(
                    f"{self.label}: груп фондів у цього майданчика немає — "
                    f"обхід іде суцільним переліком, і `--groups` тут нічого не "
                    f"обмежує. Заберіть аргумент, щоб обійти архів повністю.")
            return (None,)
        return tuple(groups or self.DEFAULT_GROUPS)

    def crawl(self, groups: tuple[str, ...] | None = None, *,
              on_progress: ProgressFn | None = None,
              resume: bool = True) -> dict[str, int]:
        """Зібрати каталог справ обходом. Без нього `search` тут неможливий.

        🔴 Це не «зручність», а єдиний спосіб шукати в цьому архіві по
        заголовках справ: вбудований пошук сайту їх не індексує. Обхід
        неквапливий за побудовою (пауза між запитами) і резюмується — фонд,
        який уже пройдено, не перечитується.
        """
        if self.workspace is None:
            raise SourceError("для обходу потрібен робочий простір — каталог "
                              "лягає в нього")
        cat = self.workspace / self.catalog_rel
        state_path = self.workspace / self.state_rel
        cat.parent.mkdir(parents=True, exist_ok=True)
        done: set[str] = set()
        if resume and state_path.is_file():
            with contextlib.suppress(ValueError, OSError):
                done = set(json.loads(state_path.read_text(encoding="utf-8"))
                           .get("fonds_done") or [])
        # Дописуємо, а не переписуємо: перерваний обхід уже коштував запитів,
        # і викидати зібране заради охайності означало б платити двічі.
        new_file = not cat.exists() or not resume
        stats = {"fonds": 0, "inventories": 0, "cases": 0, "skipped": len(done)}
        with cat.open("w" if new_file else "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=self.CATALOG_FIELDS, delimiter="\t",
                               extrasaction="ignore")
            if new_file:
                w.writeheader()
            for group in self._walk_groups(groups):
                fonds = self._fonds(group)
                for i, fond in enumerate(fonds, 1):
                    fond_id = fond.ref.partition(":")[2]
                    if fond_id in done:
                        continue
                    title, invs = parse_inventories(
                        self.http.get(f"/fonds/{fond_id}/").text)
                    fond_no = fond.label.partition(" ")[0].removeprefix("ф.")
                    stats["fonds"] += 1
                    for inv in invs:
                        inv_id = inv.ref.partition(":")[2]
                        stats["inventories"] += 1
                        for row in self._inventory_rows(inv_id):
                            w.writerow({
                                "group_id": group or "", "fond_id": fond_id,
                                "fond_no": fond_no, "fond_title": title,
                                "inv_id": inv_id, "inv_label": inv.label,
                                "file_id": row.file_id, "case_no": row.number,
                                "date": row.date, "sheets": row.sheets or "",
                                # 🔴 Табуляція й переводи рядків із заголовка
                                # справи розірвали б TSV: наступний рядок став
                                # би «справою» з полями зі зсувом, і каталог
                                # тихо зіпсувався б із середини.
                                "description": _flat(row.description)})
                            stats["cases"] += 1
                    fh.flush()
                    done.add(fond_id)
                    state_path.write_text(
                        json.dumps({"fonds_done": sorted(done)}), encoding="utf-8")
                    if on_progress:
                        on_progress(done=i, total=len(fonds), unit="фонд",
                                    note=f"справ зібрано {stats['cases']}")
        return stats

    # ── справа ───────────────────────────────────────────────────────────────

    def _title(self, file_id: str) -> str:
        for row in self._catalog_rows():
            if row.get("file_id") == file_id:
                    return " · ".join(x for x in (
                        f"ф.{row.get('fond_no', '')} {row.get('inv_label', '')} "
                        f"{row.get('case_no', '')}".strip(),
                        row.get("description") or "") if x)
        return ""

    def manifest(self, ref: str) -> Manifest:
        kind, _, ident = ref.partition(":")
        if kind != "file":
            raise SourceError(f"завантажувати можна лише справу, а не {ref!r}")
        html = self.http.get(f"/file-viewer/{ident}").text
        pages = viewer_pages(html)
        if not pages:
            # 🔴 Два різні стани, які легко сплутати, бо код відповіді в обох
            # однаковий — 200. Розрізняє їх лише наявність шифри на сторінці:
            # на неоцифровану справу сайт віддає головну, і той, хто дивиться
            # на статус, читає це як «справа є, кадри скінчились».
            meta = case_meta(html)
            if not meta:
                raise SourceError(
                    f"{self.label}: справи {ident} у переглядачі немає — сайт "
                    f"відповів головною сторінкою (і кодом 200, не 404). "
                    f"Або номер чужий, або справу не оцифровано; шукати її "
                    f"треба іншим каналом.")
            raise SourceError(
                f"справа {ident} у каталозі є, але оцифрованих кадрів у ній немає")
        # Заголовок беремо з каталогу, якщо він зібраний. Переглядач його не
        # несе, а підтвердження перед завантаженням на кілька гігабайтів без
        # відповіді «що це» нічого не підтверджує.
        meta = case_meta(html)
        return Manifest(source=self.id, ref=ref, title=self._title(ident),
                        frames=len(pages),
                        # ⚠ Адреса переглядача — у маніфесті, а не збирається
                        # тим, хто його читає: інакше знання про будову адрес
                        # цього сайту жило б у двох місцях і розійшлося б.
                        meta={"image_ids": [i for i, _ in pages],
                              "url": f"{self.base}/file-viewer/{ident}/",
                              "shifra": {"fond": meta.fond, "opys": meta.opys,
                                         "spr": meta.spr} if meta else {}})

    def fetch(self, ref: str, dest: Path, *,
              frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        kind, _, ident = ref.partition(":")
        if kind != "file":
            raise SourceError(f"завантажувати можна лише справу, а не {ref!r}")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        pages = viewer_pages(self.http.get(f"/file-viewer/{ident}").text)
        if frames:
            lo, hi = frames
            pages = [(i, p) for i, p in pages if lo <= p <= hi]
        res = FetchResult(dest=dest)
        total = len(pages)
        with self.http.client() as c:
            for done, (image_id, page) in enumerate(pages, 1):
                # Ім'я несе І номер сторінки, І id кадру: за сторінкою читають
                # по порядку, за id знаходять той самий кадр на сайті, коли
                # прочитане треба звірити з оригіналом.
                dst = dest / f"{page:04d}_f{image_id}.jpg"
                if dst.exists() and dst.stat().st_size > 0:
                    res.skipped += 1
                else:
                    try:
                        blob = self.http.get(image_url(image_id, self.base),
                                             client=c).content
                        # `.part` — див. коментар у `fsfilm.fetch`: кадр
                        # ненульового розміру більше ніколи не докачується.
                        atomic_write_bytes(dst, blob)
                        res.frames += 1
                        res.bytes += len(blob)
                    except (HttpError, OSError) as exc:
                        res.errors.append(f"кадр {page} (f{image_id}): {exc}")
                if on_progress:
                    on_progress(done=done, total=total, unit="кадр")
        return res
