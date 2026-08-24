"""🏛 ARCHIUM — каталог і скани обласного архіву (перша реалізація: ДАХмО).

Сайт на Laravel. API віддає не JSON-дані, а HTML-фрагменти в конверті
`{"Status":1,"View":"<html>"}`; GET без авторизації. Ієрархія:
група фондів → фонд → опис → справа → кадри.

🔴 ГОЛОВНЕ, І ЦЕ НЕ ДРІБНИЦЯ: вбудований пошук сайту індексує ЛИШЕ назви фондів
і описів — не заголовки справ. Запит «Борсуківці», який є реальним заголовком
справи, дає там нуль. Тому `search` тут працює НЕ по сайту, а по каталогу,
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
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
#: (id кадру, номер сторінки). Порядок сторінок дає `alt`, а НЕ числовий id —
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
    """[(id зображення, номер сторінки)] у ПРАВИЛЬНОМУ порядку.

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
    ВЛАСНИМИ номерами, які з архівною шифрою не пов'язані ніяк, а знайти їх
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
    оцифровано» від «справа є». Код відповіді для цього НЕ ГОДИТЬСЯ: заміряно
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


class ArchiumSource:
    """Джерело ARCHIUM. Каталог для пошуку читається з робочого простору."""

    id = "archium"
    label = "ARCHIUM (ДАХмО)"
    caps = frozenset({"search", "browse", "manifest", "fetch"})

    #: Куди обхід складає каталог. Відносно кореня простору.
    #: ⚠ Лишається константою класу: на неї спираються тести, і для ДАХмО вона
    #: дорівнює тому, що рахує `catalog_rel` за кодом архіву.
    CATALOG_REL = Path("data") / "raw" / "dahmo_archium" / "_crawl" / "cases.tsv"

    def __init__(self, workspace: Path | None = None, *,
                 site: Site | None = None, repo: str = "DAHMO",
                 fetcher: Fetcher | None = None) -> None:
        """`site` порожній — майданчик ДАХмО, як було до мультихостовості.

        🔴 `id` і `label` стають атрибутами ЕКЗЕМПЛЯРА: один рушій обслуговує
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

        🔴 Саме він робить застосунок корисним ДО першого завантаження. Аудиторія
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
        пакеті лишається запасним і НІКОЛИ не перекриває власний обхід.
        """
        import json

        path = self.catalog_path
        if path is not None and path.is_file():
            return "workspace", {"path": str(path)}
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

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Пошук по каталогу справ: зібраному на місці або вкладеному в пакет.

        🔴 Порожній результат тут не є негативним результатом двічі. По-перше,
        сайт не індексує заголовки справ, тож без каталогу шукати просто нема
        де. По-друге, вкладений зріз СТАРІЄ: архів додає описи, і «не
        знайшлось» у ньому означає «не було на дату зрізу». Обидві межі
        називаються у примітці кожної знахідки й у відмові.
        """
        kind, info = self.catalog_source()
        if kind == "none":
            raise SourceError(
                "каталог справ недоступний: ні зібраного обходом, ні вкладеного "
                "в пакет. Нуль тут нічого не означав би — вбудований пошук сайту "
                "індексує лише назви фондів і описів, а не заголовки справ. "
                "Зібрати: `nysh crawl archium`.")
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
                frames=int(row["sheets"]) if (row.get("sheets") or "").isdigit() else None,
                acquirable=True,
                note=((row.get("fond_title") or "")[:110] + note_tail).strip()))
            if len(out) >= limit:
                break
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
            # у цього майданчика просто немає ЗАПИТУ на дерево груп (він віддає
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

    def _group_fonds(self, group_id: str) -> list[Node]:
        def url(page: int) -> str:
            return (f"/api/v1/fond-groups/{group_id}/?Limit={PAGE_LIMIT}&Page={page}"
                    f"&SortField=FondNumber&SortOrder=asc")

        with self.http.client() as c:
            view = self.http.get(url(1), client=c).json().get("View", "") or ""
            out = parse_fonds(view)
            for page in range(2, last_page(view) + 1):
                nxt = self.http.get(url(page), client=c).json().get("View", "") or ""
                out.extend(parse_fonds(nxt))
        return out

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
            for group in (groups or self.DEFAULT_GROUPS):
                fonds = self._group_fonds(group)
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
                                "group_id": group, "fond_id": fond_id,
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
            # на неоцифровану справу сайт віддає ГОЛОВНУ, і той, хто дивиться
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
                        meta={"image_ids": [i for i, _ in pages],
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
