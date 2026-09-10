"""🕯 Онлайн-архів «Бабин Яр» (BYHMC) — 21 архів України однією адресою.

Меморіальний центр оцифрував і виклав те, що самі архіви онлайн не показують:
21 архів, 667 фондів, ~63 тисячі справ, ~7,8 млн кадрів (заміряно обходом
09.09.2026). Найбільша частка — книги державної реєстрації актів цивільного
стану 1921-1946 (понад 1,3 млн кадрів): їх зазвичай не виставляє ніхто через
75-річне обмеження.

🔴 Пошуку в цього сайту НЕМАЄ ВЗАГАЛІ — ні по заголовках справ, ні по тексту,
ні через API. Тобто нуль тут не буває відповіддю сайту: питати нема чим. Тому
`search` працює по каталогу, зібраному обходом (`nysh crawl babynyar`), а без
каталогу відмовляється відповідати замість того, щоб віддати порожній список.
Обхід дешевий: увесь каталог — це перелік фондів через API плюс одна сторінка
на кожен опис, тобто ~900 запитів на ВЕСЬ сайт.

🛡 Сайт стоїть за Cloudflare, який відсікає по TLS-відбитку: `httpx` дістає 403
на кожну адресу, включно з відкритим API. Ходимо через `cfclient` — див. його
модуль. ⚠ Медіа-хост під захист НЕ підпадає, тож самі кадри качає звичайний
`Fetcher`, з його повторами й ввічливістю.

🔴 Стеля роздільності — 2000 px по довшій стороні, і підняти її не можна:
`size:` входить у підпис imgproxy, а `/insecure/` дає 403. Для рукописного
скоропису це мало, і маніфест каже про це вголос: рішення «чи годиться це на
читання» ухвалює людина ДО завантаження, а не після прогону рушія.

Адресація (`ref`), непрозора для решти застосунку:

    arch:<id>    архів   → фонди
    fond:<id>    фонд    → описи
    desc:<id>    опис    → справи
    case:<id>    справа  → кадри (manifest / fetch)
"""
from __future__ import annotations

import base64
import binascii
import csv
import datetime as _dt
import html as _html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    SourceError,
)
from nyshporka.sources.cfclient import CfClient, ShieldError
from nyshporka.sources.http import DEFAULT_DELAY, Fetcher, HttpError
from nyshporka.utils.atomic import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nyshporka.sources.base import ProgressFn

BASE = "https://babynyar.org"

#: Скільки фондів просимо однією відповіддю API. Сервер стелі не має.
PAGE_SIZE = 100

#: Роздільність, яку віддає майданчик. Не параметр: число входить у підпис.
MAX_SIDE_PX = 2000


# ── розбір розмітки ──────────────────────────────────────────────────────────

_TR = re.compile(r"(?s)<tr[^>]*>(.*?)</tr>")
_TD = re.compile(r"(?s)<td[^>]*>(.*?)</td>")
_TAG = re.compile(r"<[^>]+>")
_FULL = re.compile(r'data-full="([^"]+)"')
_HREF_ID = {
    "fond": re.compile(r"/archive/fund/(\d+)"),
    "desc": re.compile(r"/archive/desc/(\d+)"),
    "case": re.compile(r"/archive/case/(\d+)"),
}


def _flat(s: str) -> str:
    """Один рядок без табуляцій — інакше TSV розпадеться посеред каталогу."""
    return " ".join((s or "").split())


def _cell(raw: str) -> str:
    return _flat(_html.unescape(_TAG.sub(" ", raw)))


def _norm(s: str) -> str:
    """Порівняння заголовків: апостроф і лапки в українських назвах пливуть."""
    s = s.casefold().replace("’", "'").replace("`", "'").replace("ʼ", "'")
    return re.sub(r"[^\w']+", " ", s).strip()


def _num(s: object) -> str | None:
    """Перше число з поля, без провідних нулів («Справа 0114» → «114»)."""
    m = re.search(r"\d+", str(s or ""))
    return str(int(m.group())) if m else None


def _count(s: object) -> int | None:
    """Число з комірки-лічильника: «1 234» → 1234. Порожньо — `None`.

    🔴 Не `_num`. Той бере ПЕРШЕ число — правильно для шифри («Справа 0114»),
    але лічильник кадрів майданчик може писати з роздільником тисяч, зокрема
    нерозривним пробілом, і «1 234» ставало одиницею: справа на тисячу кадрів
    лягала в каталог як одноаркушна.
    """
    digits = re.sub(r"[\s\u00a0\u2009\u202f]", "", str(s or ""))
    m = re.match(r"\d+", digits)
    return int(m.group()) if m else None


def fond_key(number: object) -> str:
    """Номер фонду до порівнюваного вигляду — РЯДКОМ, не числом.

    «Р-6453» і «6453» — два різні фонди того самого архіву. Знімаються пробіли й
    регістр, дефіси різних видів зводяться в один, а латинська `R` — у
    кирилічну `Р`: майданчик пише `R-6453` там, де архів пише `Р-6453`.
    Одне правило на джерело й на збирач реєстру (`norm_fond`).
    """
    s = str(number or "").strip().casefold()
    s = s.replace("–", "-").replace("—", "-").replace(" ", "")
    return s.replace("r", "р")


def table_rows(html: str, kind: str) -> list[tuple[str, list[str]]]:
    """Рядки таблиці сайту: `(id посилання, комірки)`.

    Усі три переліки — фондів, описів і справ — це одна й та сама таблиця з
    чотирьох колонок, тож розбір один.

    🔴 Повнота переліку тут НЕ гарантована. Сторінка «фонди архіву» гортається
    (ДАМО: 75 із 97 на першому аркуші), тому фонди й описи беруться з API, а
    звідси — лише справи опису. Що сторінка опису повна, доводить не розбір, а
    звірка з `cases_count` того самого опису (див. збирач реєстру).
    """
    pat = _HREF_ID[kind]
    out: list[tuple[str, list[str]]] = []
    for tr in _TR.findall(html):
        m = pat.search(tr)
        if not m:
            continue
        cells = [_cell(td) for td in _TD.findall(tr)]
        if cells:
            out.append((m.group(1), cells))
    return out


def frame_urls(html: str) -> list[str]:
    """Адреси кадрів справи, в порядку сторінок.

    🔴 Береться `data-full`, а не `src` мініатюри. Обидві адреси підписані
    окремо, тож «підняти» мініатюру до повного розміру, поправивши `size:` у
    посиланні, не вийде — підпис перестане сходитись, і сервер віддасть 403.
    """
    return _FULL.findall(html)


def s3_name(url: str) -> str:
    """Ім'я кадру в сховищі архіву з підписаної адреси imgproxy.

    Адреса має вигляд `/<підпис>/size:.../<base64 шляху s3>.jpg`, і base64
    розкриває походження: `s3://archive-files/DAKhmO/funds/R-6453/1/3/
    image00001_oeO4F2Z.jpg`. ⚠ Це не прикраса: без нього завантажений кадр
    неможливо звірити з оригіналом на сайті, а цитата в каноні мусить вести до
    конкретного аркуша, а не до «сторінки 17 якоїсь справи».
    """
    tail = url.rstrip("/").rpartition("/")[2]
    blob = tail.rpartition(".")[0] or tail
    try:
        raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
    except (binascii.Error, ValueError):
        return ""
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if "://" not in path:
        return ""
    return path.rstrip("/").rpartition("/")[2]


@lru_cache(maxsize=8)
def _tsv_rows(path: Path, mtime_ns: int, size: int) -> int | None:
    """Скільки рядків у зібраному каталозі. Ключ кешу — штамп файлу, щоб
    знаменник не відставав від даних після нового обходу."""
    _ = (mtime_ns, size)
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return max(0, sum(1 for _line in fh) - 1)
    except OSError:
        return None


# ── джерело ──────────────────────────────────────────────────────────────────

class BabynYarSource:
    """Каталог і скани онлайн-архіву «Бабин Яр»."""

    id = "babynyar"
    label = "Бабин Яр (BYHMC)"
    caps = frozenset({"search", "browse", "manifest", "fetch", "address"})

    CATALOG_REL = Path("data") / "raw" / "babynyar" / "_crawl" / "cases.tsv"
    STATE_REL = Path("data") / "raw" / "babynyar" / "_crawl" / "state.json"

    CATALOG_FIELDS = ("arch_id", "arch", "repo", "fond_id", "fond_no", "fond_title",
                      "desc_id", "opys", "case_id", "spr", "date", "scans", "title")

    def __init__(self, workspace: Path | None = None, *,
                 client: Any = None, media: Fetcher | None = None) -> None:
        """`client` і `media` — два РІЗНІ транспорти, і це не дублювання.

        Сторінки каталогу лежать за Cloudflare, який відсікає httpx по
        TLS-відбитку; медіа-хост — ні. Один клієнт на обидва означав би або
        403 на каталозі, або втрату повторів і ввічливості на завантаженні.
        """
        self.workspace = Path(workspace) if workspace else None
        self._client = client
        self._pages_http: Fetcher | None = None
        #: (коли взято, перелік) — див. `_all_funds`.
        self._funds_cache: tuple[float, list[dict[str, Any]]] | None = None
        self.media = media or Fetcher(base="https://media.babynyar.org")

    # ── транспорт ────────────────────────────────────────────────────────────

    def _cf(self) -> Fetcher:
        """Транспорт сторінок каталогу: клієнт крізь Cloudflare під `Fetcher`.

        🔴 Саме під `Fetcher`, а не напряму. Доти сторінки йшли просто в
        `CfClient.get`: ні паузи між запитами, ні відступу на 429 і 5xx, ні
        повтору на обірваному з'єднанні. Обхід сайту — ~900 сторінок підряд, і
        без паузи це вже не ввічливий клієнт, а навантаження на чужий сервер;
        а перший же тимчасовий 502 валив увесь обхід. Політика темпу в пакеті
        одна — в `Fetcher`, і друга її копія тут розійшлась би з першою.

        ⚠ Створюється ліниво: реєстр джерел будує це джерело на КОЖЕН виклик
        `nysh`, а `CfClient` без `curl_cffi` і без `curl` відмовляє одразу —
        тож рання ініціалізація зламала б `nysh sources` на такій машині.

        Підставлений `client` — вхід для тестів (як і в самого `Fetcher`), і
        пауза для нього нульова: двійник не сервер, і чекати на нього нема
        кого.
        """
        if self._pages_http is None:
            injected = self._client is not None
            if not injected:
                from nyshporka.sources.http import proxy_url

                self._client = CfClient(proxy=proxy_url())
            self._pages_http = Fetcher(base=BASE, client=self._client,
                                       delay=0.0 if injected else DEFAULT_DELAY)
        return self._pages_http

    def page(self, path: str) -> str:
        """HTML сторінки майданчика. Публічний навмисно: збирач реєстру читає
        ті самі переліки, і другий транспорт поруч розійшовся б із цим."""
        url = path if path.startswith("http") else f"{BASE}{path}"
        try:
            r = self._cf().get(url)
        except (ShieldError, HttpError) as exc:
            raise SourceError(str(exc)) from exc
        return str(r.text)

    def _api(self, path: str) -> dict[str, Any]:
        try:
            data = json.loads(self.page(path))
        except ValueError as exc:
            raise SourceError(f"{path}: відповідь не є JSON — {exc}") from exc
        return data if isinstance(data, dict) else {}

    # ── дерево ───────────────────────────────────────────────────────────────

    def archives(self) -> list[dict[str, Any]]:
        """Перелік архівів майданчика.

        ⚠ Скорочення тут неоднозначні за побудовою: «ДАЧО» на цьому сайті
        носять ТРИ різні архіви (Черкаської, Чернігівської й Чернівецької
        областей), «ДАКО» — два, «ДАХО» — два. Розрізняє їх лише числовий `id`,
        і саме він, а не скорочення, зшивається з нашим кодом архіву.
        """
        data = self._api("/api/archive/archives/?page_size=100")
        rows = data.get("results")
        return list(rows) if isinstance(rows, list) else []

    def funds(self, archive_id: str = "") -> list[dict[str, Any]]:
        """Усі фонди майданчика разом з описами — сторінками по 100.

        🔴 Саме API, а не сторінка «фонди архіву». Та сторінка ГОРТАЄТЬСЯ, і
        перший аркуш віддає лише частину: для ДАМО — 75 фондів із 97, і серед
        відрізаних була ф.484, тобто найбільша колекція метричних книг на
        майданчику. Збирач, який читав ту сторінку, чесно казав «такого фонду
        тут немає» — відповідь, що закриває напрям пошуку назавжди.

        ⚠ `archive_id` відсіюється ТУТ, на розібраних рядках: параметр
        `?archive=` сервер приймає й ігнорує (`total` не змінюється), тож
        звуження запитом було б удаваним.
        """
        want = str(archive_id or "").strip()
        return [r for r in self._all_funds()
                if not want or str((r.get("archive") or {}).get("id")) == want]

    #: Скільки живе перелік фондів на екземплярі. Не нуль і не вічність.
    FUNDS_TTL_SEC = 600.0

    def _all_funds(self) -> list[dict[str, Any]]:
        """Увесь перелік фондів — один раз на екземпляр, а не на кожен запит.

        🔴 Кеш тут не про швидкість, а про доступ. Перелік — 7 сторінок API, і
        перегляд архіву плюс збирання фонду брали їх двічі поспіль; заміряно
        09.09.2026: Cloudflare показав сторінку-виклик саме на другому проході,
        посеред збирача. Кожен зайвий запит тут наближає відсічку.

        ⚠ Із терміном, а не назавжди: у живому демоні екземпляр джерела живе
        годинами, і вічний кеш ховав би фонди, які майданчик виклав після
        старту, — той самий клас, що вже лікували на паку архівів.
        """
        import time

        now = time.monotonic()
        if self._funds_cache is not None and now - self._funds_cache[0] < self.FUNDS_TTL_SEC:
            return self._funds_cache[1]
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._api(f"/api/archive/funds/?page={page}&page_size={PAGE_SIZE}")
            rows = data.get("results") or []
            out += [r for r in rows if isinstance(r, dict)]
            if not data.get("page_next") or not rows:
                break
            page += 1
        self._funds_cache = (now, out)
        return out

    def cases_count(self, desc_id: str) -> int | None:
        """Скільки справ в описі за словами САМОГО майданчика.

        🔴 Знаменник для звірки розбору. Сторінка опису віддає таблицю без
        пагінації, але довести це можна лише числом із іншого каналу — інакше
        обрізаний перелік виглядав би як повний фонд.
        """
        got = self._api(f"/api/archive/descriptions/{desc_id}/").get("cases_count")
        return int(got) if isinstance(got, int) else None

    def repo_for(self, arch_id: object) -> str:
        """Наш код архіву за числовим id майданчика. Порожньо — не знаємо.

        🔴 Здогад тут заборонений. Підставлений «схожий» код завів би справи
        чужого архіву в облік під нашим шифром, і звірка «чи є цей фонд у нас»
        порівнювала б різні архіви як один.
        """
        from nyshporka.archives import active

        return active().repo_for_code("babynyar", str(arch_id or ""))

    def browse(self, ref: str | None = None) -> list[Node]:
        if not ref:
            return [Node(ref=f"arch:{a.get('id')}",
                         label=f"{a.get('short_name', '')} · {a.get('name', '')}")
                    for a in self.archives()]
        kind, _, ident = ref.partition(":")
        if kind == "arch":
            return [Node(ref=f"fond:{f.get('id')}",
                         label=f"ф.{f.get('number', '')} · {f.get('name', '')}"[:160])
                    for f in self.funds(ident)]
        if kind == "fond":
            out: list[Node] = []
            for f in self.funds():
                if str(f.get("id")) != str(ident):
                    continue
                out += [Node(ref=f"desc:{d.get('id')}",
                             label=f"оп.{d.get('number', '')} · "
                                   f"{d.get('annotation', '')}"[:160])
                        for d in (f.get("descriptions") or [])]
                break
            return out
        if kind == "desc":
            cases: list[Node] = []
            for cid, c in table_rows(self.page(f"/archive/desc/{ident}"), "case"):
                cases.append(Node(ref=f"case:{cid}", kind="case",
                                  label=" · ".join(c[:2])[:160],
                                  frames=_count(c[3]) if len(c) > 3 else None))
            return cases
        raise SourceError(f"незрозуміла адреса: {ref!r}")

    # ── каталог ──────────────────────────────────────────────────────────────

    @property
    def catalog_path(self) -> Path | None:
        return (self.workspace / self.CATALOG_REL) if self.workspace else None

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Звідки беруться рядки пошуку — і чи є вони взагалі."""
        path = self.catalog_path
        if path is None or not path.is_file():
            return "none", {}
        st = path.stat()
        return "workspace", {
            "path": str(path),
            "rows": _tsv_rows(path, st.st_mtime_ns, st.st_size),
            "taken": _dt.date.fromtimestamp(st.st_mtime).isoformat(),
            # Скільки описів у каталозі неповні: без цього числа нуль пошуку
            # по такому опису читався б як «справи немає».
            "short": len(self._read_state().get("descs_short") or {})}

    def _catalog_rows(self) -> Iterator[dict[str, str]]:
        kind, info = self.catalog_source()
        if kind != "workspace":
            return
        with Path(info["path"]).open(encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh, delimiter="\t")

    NO_CATALOG = (
        "у «Бабиного Яру» немає власного пошуку — ані по заголовках справ, ані "
        "по тексту, ані в API. Тобто нуль звідси не був би відповіддю архіву: "
        "питати нема чим. Каталог збирається обходом і потім лежить на диску: "
        "`nysh crawl babynyar` (увесь сайт — близько 900 запитів).")

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Пошук по зібраному каталогу — по заголовку справи й по назві фонду.

        🔴 Назва фонду шукається нарівні із заголовком навмисно. Тут переважають
        фонди установ, де заголовок справи — це «Опис №1» або «Книга реєстрації
        актів про народження за 1932 р.», і жодного топоніма не містить: село й
        район стоять у назві ФОНДУ. Пошук лише по заголовках віддавав би нуль на
        запит, відповідь на який лежить рядком вище.
        """
        kind, info = self.catalog_source()
        if kind == "none":
            raise SourceError(self.NO_CATALOG)
        needle = _norm(q)
        if not needle:
            return []
        taken = info.get("taken") or ""
        short = int(info.get("short") or 0)
        out: list[Hit] = []
        for row in self._catalog_rows():
            hay = _norm(f"{row.get('title', '')} {row.get('fond_title', '')}")
            if needle not in hay:
                continue
            out.append(self._hit(row, taken, short=short))
            if len(out) >= limit:
                break
        return out

    def find_case(self, fond: str, opys: str, spr: str, *,
                  repo: str = "") -> list[Hit]:
        """Справа за ШИФРОЮ. Каталог носить фонд, опис і номер окремими полями.

        ⚠ Без `repo` відповідь може прийти з кількох архівів одразу: номери
        фондів у різних архівах збігаються постійно, і зведення їх в одну
        знахідку зробило б із двох різних справ одну неіснуючу.
        """
        if self.catalog_source()[0] == "none":
            raise SourceError(self.NO_CATALOG)
        want = (_num(fond), _num(opys), _num(spr))
        if None in want:
            return []
        # 🔴 Фонд за числом і фонд за рядком — різні питання. «R-6453» і «6453»
        # — два фонди одного архіву, тож точний збіг (з префіксом) іде першим і
        # витісняє сусіда. Але якщо точного немає, відповідає фонд за числом:
        # людина часто набирає шифру без «Р-», і нуль тут був би хибним — у
        # знахідці однаково видно шифру з префіксом.
        want_fond = fond_key(fond)
        exact: list[Hit] = []
        loose: list[Hit] = []
        for row in self._catalog_rows():
            if repo and (row.get("repo") or "").upper() != repo.upper():
                continue
            got = (_num(row.get("fond_no")), _num(row.get("opys")),
                   _num(row.get("spr")))
            if got == want:
                same = fond_key(row.get("fond_no")) == want_fond
                (exact if same else loose).append(self._hit(row, ""))
        return exact or loose

    def _hit(self, row: dict[str, str], taken: str, *, short: int = 0) -> Hit:
        scans = row.get("scans") or ""
        note = (row.get("fond_title") or "")[:110]
        if taken:
            note = f"{note} · зріз каталогу від {taken}".strip(" ·")
        if short:
            # 🔴 Повнота каталогу — частина відповіді. Без цієї примітки
            # «знайшлось лише це» читалось би як «більше справ немає».
            note = (f"{note} · ⚠ каталог неповний: описів, що віддали менше "
                    f"справ, ніж обіцяє сайт, — {short}").strip(" ·")
        return Hit(
            source=self.id,
            ref=f"case:{row.get('case_id', '')}",
            title=(row.get("title") or "")[:200],
            years=row.get("date") or "",
            shifra=f"ф.{row.get('fond_no', '')}-{row.get('opys', '')}-"
                   f"{row.get('spr', '')}",
            repo=row.get("repo") or "",
            archive=row.get("arch") or "",
            fond=row.get("fond_no") or "",
            frames=int(scans) if scans.isdigit() else None,
            # Сканів нуль — справа в описі є, а копій немає; обіцяти
            # завантаження такої не можна, показати її в списку треба.
            acquirable=bool(scans.isdigit() and int(scans) > 0),
            url=f"{BASE}/archive/case/{row.get('case_id', '')}",
            note=note)

    # ── обхід ────────────────────────────────────────────────────────────────

    def crawl(self, groups: tuple[str, ...] | None = None, *,
              on_progress: ProgressFn | None = None,
              resume: bool = True) -> dict[str, int]:
        """Зібрати каталог справ. `groups` — id архівів майданчика, через кому.

        Обхід іде описами, а не справами: сторінка опису вже несе повний перелік
        справ із номерами, роками й числом сканів. Резюмується по описах —
        перерваний обхід не починається наново.

        🔴 Повнота кожного опису звіряється з `cases_count` самого майданчика.
        Сторінка опису пагінації не має, але довести це може лише число з
        іншого каналу: обрізаний перелік інакше ліг би в каталог як повний, і
        «такої справи немає» стало б відповіддю пошуку. Опис, що віддав менше,
        НЕ позначається пройденим — наступний запуск перечитає саме його, а вже
        взяті справи не задвояться (див. `_known_ids`). Ціна — ще один запит
        API на опис, тобто ~1800 запитів на весь сайт замість ~900.
        """
        if self.workspace is None:
            raise SourceError("для обходу потрібен робочий простір — каталог "
                              "лягає в нього")
        cat = self.workspace / self.CATALOG_REL
        cat.parent.mkdir(parents=True, exist_ok=True)
        state = self._read_state() if resume else {}
        done: set[str] = {str(d) for d in (state.get("descs_done") or [])}
        short: dict[str, list[int]] = dict(state.get("descs_short") or {})
        want = {str(g).strip() for g in (groups or ()) if str(g).strip()}
        funds = [f for f in self.funds()
                 if not want or str((f.get("archive") or {}).get("id")) in want]
        if want and not funds:
            raise SourceError(
                f"на майданчику немає архівів з id {sorted(want)} — перелік "
                f"дає `nysh browse {self.id}`. ⚠ Тут потрібен саме id: під одним "
                f"скороченням («ДАЧО») стоять три різні архіви.")
        plan = [(f, d) for f in funds for d in (f.get("descriptions") or [])]
        stats = {"archives": len({str((f.get("archive") or {}).get("id"))
                                  for f in funds}),
                 "fonds": len(funds), "inventories": 0, "cases": 0,
                 "skipped": 0, "short": 0}
        known = self._known_ids(cat) if resume and cat.exists() else set()
        new_file = not resume or not cat.exists() or cat.stat().st_size == 0
        with cat.open("w" if new_file else "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=self.CATALOG_FIELDS, delimiter="\t",
                               extrasaction="ignore")
            if new_file:
                w.writeheader()
            for i, (fund, desc) in enumerate(plan, 1):
                did = str(desc.get("id") or "")
                if not did:
                    continue
                if did in done:
                    stats["skipped"] += 1
                    continue
                stats["inventories"] += 1
                written, parsed = self._write_desc(w, fund, desc, did, known)
                stats["cases"] += written
                fh.flush()
                promised = self.cases_count(did)
                if promised is not None and promised != parsed:
                    short[did] = [parsed, promised]
                else:
                    short.pop(did, None)
                    done.add(did)
                self._write_state(done, short)
                if on_progress:
                    tail = f" · неповних описів {len(short)}" if short else ""
                    on_progress(done=i, total=len(plan), unit="опис",
                                note=f"справ зібрано {stats['cases']}{tail}")
        stats["short"] = len(short)
        return stats

    def _read_state(self) -> dict[str, Any]:
        """Стан обходу; відсутній або битий — порожній, а не виняток."""
        if self.workspace is None:
            return {}
        try:
            data = json.loads((self.workspace / self.STATE_REL)
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, done: set[str], short: dict[str, list[int]]) -> None:
        """Стан обходу — АТОМАРНО, через `.part` і заміну.

        🔴 Прямий запис, обірваний посередині, лишав напівфайл; його читання
        падало на `ValueError`, стан тихо ставав порожнім, і наступний обхід
        перечитував УСЕ — із дублями того, що вже лежало в каталозі.
        """
        if self.workspace is None:
            return
        payload = {"descs_done": sorted(done), "descs_short": short}
        atomic_write_bytes(self.workspace / self.STATE_REL,
                           json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    @staticmethod
    def _known_ids(cat: Path) -> set[str]:
        """Справи, що вже лежать у каталозі, — і лагодження обірваного хвоста.

        🔴 Обрив між дописом рядків і записом стану лишав опис непозначеним, і
        наступний запуск дописував ті самі справи вдруге: каталог «ріс», а
        пошук віддавав кожну знахідку двічі. Повтор тепер пропускає вже відомі
        `case_id`, тож перечитати опис безпечно завжди — на цьому й тримається
        повторне читання неповних описів.

        ⚠ Обрив посеред рядка лишав напівзаписаний рядок, і наступний допис
        приклеївся б до нього — зі зсувом полів посеред каталогу. Хвіст без
        переводу рядка відрізається до останнього цілого рядка.
        """
        raw = cat.read_bytes()
        if raw and not raw.endswith(b"\n"):
            with cat.open("r+b") as fh:
                fh.truncate(raw.rfind(b"\n") + 1)
        ids: set[str] = set()
        with cat.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                cid = (row.get("case_id") or "").strip()
                if cid:
                    ids.add(cid)
        return ids

    def _write_desc(self, w: Any, fund: dict[str, Any], desc: dict[str, Any],
                    did: str, known: set[str]) -> tuple[int, int]:
        """Дописати справи опису. Повертає (дописано, розібрано з таблиці).

        Два числа, а не одне: з `cases_count` звіряється РОЗІБРАНЕ — справи,
        що вже лежали в каталозі, теж є в описі, просто вдруге не пишуться.
        """
        arch = fund.get("archive") or {}
        arch_id = str(arch.get("id") or "")
        base = {
            "arch_id": arch_id, "arch": arch.get("short_name") or "",
            "repo": self.repo_for(arch_id),
            "fond_id": str(fund.get("id") or ""),
            "fond_no": fund.get("number") or "",
            "fond_title": _flat(str(fund.get("name") or "")),
            "desc_id": did, "opys": desc.get("number") or "",
        }
        written = parsed = 0
        for cid, cells in table_rows(self.page(f"/archive/desc/{did}"), "case"):
            parsed += 1
            if cid in known:
                continue
            spr = cells[0] if cells else ""
            title = cells[1] if len(cells) > 1 else ""
            date = cells[2] if len(cells) > 2 else ""
            scans = _count(cells[3]) if len(cells) > 3 else None
            w.writerow({**base, "case_id": cid, "spr": spr, "date": date,
                        "scans": "" if scans is None else str(scans),
                        "title": _flat(title)})
            known.add(cid)
            written += 1
        return written, parsed

    # ── справа ───────────────────────────────────────────────────────────────

    def _catalog_row(self, case_id: str) -> dict[str, str]:
        for row in self._catalog_rows():
            if row.get("case_id") == case_id:
                return row
        return {}

    #: Що саме тут не так із роздільністю — одним рядком, який видно в маніфесті.
    RESOLUTION_NOTE = (
        f"кадр приходить стисненим до {MAX_SIDE_PX} px по довшій стороні — це "
        f"стеля майданчика, а не налаштування: розмір входить у підпис адреси. "
        f"Для друкованого й канцелярського письма цього досить, для скоропису "
        f"XVIII-XIX ст. — на межі.")

    def manifest(self, ref: str) -> Manifest:
        kind, _, ident = ref.partition(":")
        if kind != "case":
            raise SourceError(f"завантажувати можна лише справу, а не {ref!r}")
        urls = frame_urls(self.page(f"/archive/case/{ident}"))
        row = self._catalog_row(ident)
        title = " · ".join(x for x in (
            f"ф.{row.get('fond_no', '')}-{row.get('opys', '')}-{row.get('spr', '')}"
            if row else "", row.get("title") or "") if x)
        if not urls:
            # 🔴 Код відповіді в обох станах однаковий (200), тож розрізняє їх
            # лише сам перелік кадрів. Мовчазний нуль читався б як «справа
            # скінчилась», а насправді її просто не оцифровано.
            raise SourceError(
                f"справа {ident}: сторінка є, а кадрів на ній немає — на цьому "
                f"майданчику так виглядає НЕоцифрована справа, а не порожня")
        return Manifest(source=self.id, ref=ref, title=title, frames=len(urls),
                        meta={"url": f"{BASE}/archive/case/{ident}",
                              "urls": urls,
                              "max_side_px": MAX_SIDE_PX,
                              "resolution": self.RESOLUTION_NOTE,
                              "shifra": {"repo": row.get("repo", ""),
                                         "fond": row.get("fond_no", ""),
                                         "opys": row.get("opys", ""),
                                         "spr": row.get("spr", "")} if row else {}})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        kind, _, ident = ref.partition(":")
        if kind != "case":
            raise SourceError(f"завантажувати можна лише справу, а не {ref!r}")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        urls = list(enumerate(frame_urls(self.page(f"/archive/case/{ident}")), 1))
        if frames:
            lo, hi = frames
            urls = [(p, u) for p, u in urls if lo <= p <= hi]
        res = FetchResult(dest=dest)
        total = len(urls)
        with self.media.client() as c:
            for done, (page, url) in enumerate(urls, 1):
                # Ім'я несе І порядок сторінки, І ім'я файлу в сховищі архіву:
                # за порядком читають, за іменем знаходять той самий кадр на
                # сайті, коли прочитане треба звірити з оригіналом.
                stem = s3_name(url).rpartition(".")[0]
                dst = dest / (f"{page:04d}_{stem}.jpg" if stem else f"{page:04d}.jpg")
                if dst.exists() and dst.stat().st_size > 0:
                    res.skipped += 1
                else:
                    try:
                        blob = self.media.get(url, client=c).content
                        atomic_write_bytes(dst, blob)
                        res.frames += 1
                        res.bytes += len(blob)
                    except (HttpError, OSError) as exc:
                        res.errors.append(f"кадр {page}: {exc}")
                if on_progress:
                    on_progress(done=done, total=total, unit="кадр")
        return res
