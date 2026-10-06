"""🕯 «Український мартиролог ХХ ст.» — іменна база репресованих 1920–1950-х.

База Державної архівної служби (`archives.gov.ua/um.php`): на кожну особу —
дати життя, місце проживання на момент арешту, арешт, вирок, реабілітація і,
головне, шифра архівно-слідчої справи (архів, фонд, опис, справа). Тобто це
покажчик на справу, яку далі замовляють в архіві, а не сама справа.

🔴 **База покриває малу частку репресованих, і нерівно.** 170 468 осіб на
02.10.2026 у 27 архівах, і по областях різниця на два порядки: ДА Вінницької
області — 373 особи, ДА Хмельницької — 1 752, ДА Одеської — 10 196, ЦДАГОУ —
28 181 (лічильники сайту того ж дня). Нуль тут означає «цієї особи немає в
ЦІЙ базі», а не «репресій у роду не було». Тому лічильники по архівах їдуть у
знаменник кожної відповіді (`catalog_source()` → `coverage.basis[].by_archive`
конверта `catalog.search`), а не лишаються на сайті.

🔑 Збіг — ПІДРЯДОК без регістру по прізвищу: «евчук» знаходить і «Шевчук», і
«Кузьмюк-Шевчук». Ім'я — теж підрядком: «Шевчук Ян» дає і Дем'яна, і Тетяну. Шаблонів `_` і `%` сервер не знає (заміряно 06.10.2026:
«Шевч_к» → 0 при 139 на «Шевчук»), тож скалічене написання перебирається
шматками прізвища, а не зірочкою.

🛡 Сайт стоїть за Akamai: `httpx` і системний `curl` дістають 403 «Access
Denied» на будь-яку адресу, пропускає лише `curl_cffi`, що вдає рукостискання
Chrome. Тому запасного шляху через системний `curl`, який є в `CfClient`, тут
немає навмисно: він гарантовано дає 403, і відмова мусить назвати справжню
причину — бракує `nyshporka[cfshield]`.

⚠ Це база ОСІБ. Загальний пошук по каталогах (`nysh find` без `--source`)
питає «що є про моє село», і назва села, підставлена як прізвище, ловила б
чужих людей із тим самим підрядком. Тому джерело `explicit_only`: його
опитують лише явно, `nysh find "<прізвище> [ім'я]" --source martyrolog`.

Адресація (`ref`): `person:<id>` — номер картки в базі.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from nyshporka.sources.base import Hit, Hits, SourceAbout, SourceError, SourceScope
from nyshporka.sources.http import Fetcher, HttpError, offline

HOST = "https://archives.gov.ua"
PAGE = "/um.php"

#: Скільки записів сервер кладе на сторінку видачі. Не параметр запиту.
PAGE_SIZE = 50

#: Темп — спільний на машину (`core.xrate`): видача й картки йдуть одна за
#: одною, і пошук на 20 осіб — це 21 запит. Двадцять за двадцять секунд
#: тримають такий пошук у межах пів хвилини і не б'ють чергою.
RATE_KEY = "martyrolog"
RATE_MAX = 20
RATE_WINDOW = 20.0

#: Ознаки сторінки відсічі Akamai. Приходить зі статусом 403, але тіло
#: перевіряється окремо: двійник чи проксі може віддати її й зі 200.
DENIED_MARKS = ("Access Denied", "errors.edgesuite.net")

_ZERO = "пошук не дав результатів"
_TOTAL = re.compile(r"Результатів пошуку:\s*(\d+)")
#: Заголовок групи архіву у видачі або рядок особи — в одному проході, щоб
#: кожна особа дістала архів групи, під якою стоїть.
_LIST_ITEM = re.compile(
    r'<a[^>]*href="/um\.php\?a=(?P<arch_id>\d+)[^"]*">(?P<arch>.*?)</a>'
    r'|<span class="ind">\s*\d+\.\s*</span>\s*'
    r'<a href="[^"]*?[?&]id=(?P<id>\d+)">(?P<name>.*?)</a>\s*'
    r'<span class="rn">(?P<rn>.*?)</span>',
    re.S)
_PAGE_LINK = re.compile(r'[?&]p=(\d+)">\d+</a>')
_SIDEBAR = re.compile(r'<a href="/um\.php\?a=(\d+)">\s*<span>(.*?)&nbsp;–\s*(.*?)док\.', re.S)
_CARD_ARCH = re.compile(r'Повернутися</a>\s*>\s*<a href="[^"]*?a=(\d+)">(.*?)</a>', re.S)
_CARD_NAME = re.compile(r"<h3>(.*?)</h3>", re.S)
#: Поля картки двох видів: «підпис:</div><div><strong>значення» (шапка) і
#: «підпис: <strong>значення» (арешт, архівні дані).
_CARD_FIELD = re.compile(
    r"(?P<label>Національність|Рід занять або коротка характеристика|Дати життя|"
    r"Відомості щодо реабілітації|Місце проживання на момент арешту|Дата арешту|"
    r"Стаття звинувачення|Орган, який виніс вирок|Вирок|Дата вироку|Фонд|Опис|"
    r"Справа):\s*(?:</div>\s*<div[^>]*>\s*)?<strong>(?P<value>.*?)</strong>",
    re.S)
_CARD_ADDED = re.compile(
    r"Дата додавання інформації до бази даних</div>\s*<div[^>]*>\s*(.*?)\s*</div>", re.S)


def _text(fragment: str, *, sep: str = " ") -> str:
    """Шматок розмітки → рядок: без тегів, сутностей і зайвих пробілів.

    `sep=""` — для імен: сервер обгортає збіг у `<span>` посеред слова, і
    тег, замінений пробілом, розривав «Кузьмюк-Шевчук» на «Кузьмюк- Шевчук».
    """
    no_tags = re.sub(r"<[^>]+>", sep, fragment or "")
    return " ".join(_html.unescape(no_tags).replace("\xa0", " ").split())


def _blank(value: str) -> str:
    """«_невідомо» і «????» — це порожнеча бази, а не значення."""
    v = value.strip()
    return "" if not v or v.strip("?.– ") == "" or v == "_невідомо" else v


def denied(body: str) -> bool:
    """Чи це сторінка відсічі Akamai, а не відповідь бази."""
    head = (body or "")[:3000]
    return any(m in head for m in DENIED_MARKS)


def split_query(q: str) -> tuple[str, str, str]:
    """«Шевчук Ян Віцентович» → (прізвище, ім'я, по батькові).

    Перше слово — прізвище, друге — ім'я, решта — по батькові. Подвійне
    прізвище через дефіс лишається одним словом.
    """
    parts = (q or "").split()
    ln = parts[0] if parts else ""
    fn = parts[1] if len(parts) > 1 else ""
    sn = " ".join(parts[2:])
    return ln, fn, sn


@dataclass(frozen=True)
class Row:
    """Рядок видачі: хто, коли народився і в якому архіві його справа."""

    id: str
    name: str
    born: str
    archive: str
    archive_id: str


@dataclass(frozen=True)
class ResultPage:
    """Сторінка видачі. `total` — скільки осіб база знайшла всього."""

    total: int
    rows: list[Row]
    pages: int
    by_archive: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Card:
    """Картка особи. Порожнє поле — база його не має, а не «не розібрано»."""

    id: str
    name: str
    archive: str
    archive_id: str
    fields: dict[str, str]
    added: str

    def get(self, label: str) -> str:
        return self.fields.get(label, "")

    @property
    def shifra(self) -> str:
        parts = [(f"ф. {self.get('Фонд')}" if self.get("Фонд") else ""),
                 (f"оп. {self.get('Опис')}" if self.get("Опис") else ""),
                 (f"спр. {self.get('Справа')}" if self.get("Справа") else "")]
        return ", ".join(p for p in parts if p)


def parse_results(body: str) -> ResultPage:
    """Сторінка видачі → особи з архівами, загальне число й кількість сторінок.

    🔴 Сторінка без «Результатів пошуку» і без «пошук не дав результатів» — це
    НЕ нуль, а змінена розмітка: віддати тут `[]` означало б доповісти «такої
    особи в базі немає» з розбору, який нічого не прочитав. Те саме — коли
    сайт назвав число знайдених, а рядків не розібрано жодного.
    """
    if _ZERO in body:
        return ResultPage(total=0, rows=[], pages=0)
    m = _TOTAL.search(body)
    if not m:
        raise SourceError("сторінка бази не схожа на видачу пошуку — розмітка "
                          "змінилась, і нуль із неї був би вигаданим")
    total = int(m.group(1))
    head, _, block = body[m.end():].partition("<hr>")
    by_archive = {_text(a): int(n) for a, n in re.findall(
        r"<a [^>]*>(.*?)</a>&nbsp;\((\d+)\)", head)}
    # Кінець видачі — нижній перелік сторінок; без нього блок тягнувся б у
    # бічну панель з лічильниками, а там ті самі посилання `?a=`.
    block = block.split("Версія для друку", 1)[0]
    rows: list[Row] = []
    archive, archive_id = "", ""
    for it in _LIST_ITEM.finditer(block):
        if it.group("arch_id"):
            archive, archive_id = _text(it.group("arch")), it.group("arch_id")
            continue
        rn = _text(it.group("rn")).removeprefix("р.н.").strip()
        rows.append(Row(id=it.group("id"), name=_text(it.group("name"), sep=""),
                        born=_blank(rn), archive=archive, archive_id=archive_id))
    if total and not rows:
        raise SourceError(f"база каже «знайдено {total}», а рядків видачі не "
                          f"розібрано жодного — розмітка рядків змінилась, і нуль "
                          f"із неї був би вигаданим")
    pages = max((int(p) for p in _PAGE_LINK.findall(block)), default=1)
    return ResultPage(total=total, rows=rows, pages=max(pages, 1),
                      by_archive=by_archive)


def parse_card(body: str, person_id: str) -> Card:
    """Картка особи → поля. Без імені в `<h3>` — не картка, а щось інше."""
    nm = _CARD_NAME.search(body)
    if not nm:
        raise SourceError(f"картка {person_id} не схожа на картку особи — "
                          f"розмітка змінилась")
    am = _CARD_ARCH.search(body)
    fields: dict[str, str] = {}
    for f in _CARD_FIELD.finditer(body):
        value = _blank(_text(f.group("value")))
        if value:
            fields.setdefault(f.group("label"), value)
    added = _CARD_ADDED.search(body)
    return Card(id=person_id, name=_text(nm.group(1), sep=""),
                archive=_text(am.group(2)) if am else "",
                archive_id=am.group(1) if am else "",
                fields=fields, added=_text(added.group(1)) if added else "")


def parse_coverage(body: str) -> dict[str, int]:
    """Бічна панель сайту: скільки осіб у базі від кожного архіву."""
    out: dict[str, int] = {}
    for _aid, name, count in _SIDEBAR.findall(body):
        digits = re.sub(r"\D", "", _html.unescape(count))
        if digits:
            out[_text(name)] = int(digits)
    return out


def _life(card: Card, born: str) -> str:
    """«1898–?» із «??.??.1898 – ??.??.????»: рік видно, невідоме — знаком питання."""
    raw = card.get("Дати життя")
    years = re.findall(r"(\d{4}|\?{4})", raw)
    if len(years) >= 2:
        lo, hi = (y if y.isdigit() else "?" for y in years[:2])
        return f"{lo}–{hi}" if (lo, hi) != ("?", "?") else ""
    return born


class MartyrologSource:
    """База «Український мартиролог ХХ ст.». Живий запит, каталогу на диску немає."""

    id = "martyrolog"
    label = "Український мартиролог ХХ ст. (ДАС, репресовані 1920–1950-х)"
    caps = frozenset({"search"})
    #: Не опитується загальним `catalog.search`: база осіб, а не справ за селом.
    explicit_only = True
    about = SourceAbout(
        answers="чи був репресований цей предок і де лежить його архівно-слідча справа",
        gives="особу з датами життя, місцем проживання на час арешту, арештом, "
              "вироком, реабілітацією і шифрою справи (архів, фонд, опис, справа)",
        not_gives="самої справи чи її сторінок; репресованих поза базою — вона "
                  "покриває малу частку, по областях нерівно; розкуркулених і "
                  "депортованих без кримінальної справи",
        where_class="іменна база репресованих",
        scope=SourceScope(years=(1920, 1959),
                          genres=("архівно-слідчі справи",),
                          note="ЦДАВО, ЦДАГОУ, ЦДАМЛМ і держархіви областей; "
                               "лічильник по архівах — у знаменнику відповіді"),
        match_on=("person_name",), match_how="substring",
        zero_means="цієї особи немає в ЦІЙ базі на сьогодні; база покриває частку "
                   "репресованих (у ДА Вінницької області — сотні осіб) і "
                   "поповнюється партіями — нуль не означає, що репресій у роду "
                   "не було",
        pitfalls=("збіг — підрядок прізвища; шаблонів `_` і `%` сервер не знає, тож "
                  "скалічене написання перебирати шматками",
                  "ім'я теж іде підрядком: «Ян» дає Дем'яна, Тетяну й Касяна — "
                  "перелік за іменем переглядати, а не довіряти",
                  "сайт за Akamai: без `curl_cffi` (`nyshporka[cfshield]`) запит "
                  "не проходить узагалі",
                  "загальний `nysh find` цю базу не питає — лише `--source martyrolog`"))

    def __init__(self, workspace: Path | None = None, *, client: Any = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._client = client
        self._http: Fetcher | None = None
        #: Лічильники по архівах з останньої відповіді — знаменник нуля.
        self._coverage: dict[str, int] = {}

    # ── транспорт ────────────────────────────────────────────────────────────

    def _fetcher(self) -> Fetcher:
        """`Fetcher` поверх клієнта, що проходить Akamai.

        ⚠ Створюється ліниво, як у «Бабиного Яру»: реєстр будує джерело на
        кожен виклик `nysh`, і перевірка `curl_cffi` при побудові зламала б
        `nysh sources` на машині без нього.
        """
        if self._http is None:
            limiter = None
            if self._client is None:
                from nyshporka.core.xrate import CrossProcessLimiter
                from nyshporka.sources.cfclient import CfClient, ShieldError, have_curl_cffi
                from nyshporka.sources.http import proxy_url

                if not have_curl_cffi():
                    raise SourceError(
                        "база ДАС стоїть за Akamai, і пройти його вміє лише "
                        "curl_cffi — постав `pip install nyshporka[cfshield]`; "
                        "системний curl і httpx дістають 403 на кожен запит")
                try:
                    self._client = CfClient(proxy=proxy_url())
                except ShieldError as exc:
                    raise SourceError(str(exc)) from exc
                limiter = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX,
                                              window=RATE_WINDOW)
            self._http = Fetcher(base=HOST, client=self._client, delay=0.0,
                                 limiter=limiter)
        return self._http

    def page(self, query: str) -> str:
        """HTML сторінки бази за рядком запиту (`ln=…&p=2`, `id=…`)."""
        if offline() and self._client is None:
            raise SourceError("мережу вимкнено в цьому середовищі — базу не опитано")
        try:
            r = self._fetcher().get(f"{HOST}{PAGE}?{query}")
        except HttpError as exc:
            if exc.status == 403 or denied(exc.body):
                raise SourceError(
                    "Akamai відсік запит до бази ДАС (403) — це відмова сайту, "
                    "а не нуль") from exc
            raise SourceError(f"база ДАС не відповіла: {exc}") from exc
        except OSError as exc:
            raise SourceError(f"база ДАС не відповіла: {exc}") from exc
        body = str(getattr(r, "text", "") or "")
        if denied(body):
            raise SourceError("Akamai відсік запит до бази ДАС — це відмова сайту, "
                              "а не нуль")
        cov = parse_coverage(body)
        if cov:
            self._coverage = cov
        return body

    # ── пошук ────────────────────────────────────────────────────────────────

    @staticmethod
    def _query(ln: str, fn: str, sn: str, *, p: int = 1) -> str:
        args = [("ln", ln), ("fn", fn), ("sn", sn)]
        q = "&".join(f"{k}={quote(v)}" for k, v in args if v)
        return q + (f"&p={p}" if p > 1 else "")

    def results(self, q: str, *, limit: int) -> ResultPage:
        """Видача за «прізвище [ім'я [по батькові]]», сторінками до `limit` осіб."""
        ln, fn, sn = split_query(q)
        first = parse_results(self.page(self._query(ln, fn, sn)))
        rows = list(first.rows)
        p = 1
        while len(rows) < min(limit, first.total) and p < first.pages:
            p += 1
            # Порожня наступна сторінка вже відмовляє в `parse_results`
            # (`total` є, рядків немає) — обрізка не видасться за весь перелік.
            rows += parse_results(self.page(self._query(ln, fn, sn, p=p))).rows
        return ResultPage(total=first.total, rows=rows[:limit], pages=first.pages,
                          by_archive=first.by_archive)

    @staticmethod
    def _our_repo(archive: str) -> str:
        """«ЦДАГОУ» → `CDAHOU`; архів, якого пак не знає, лишається порожнім.

        Через `resolve_code` паку, як у `ridni`: другої таблиці перекладу назв
        архівів тут не заводимо — вона першою й розійшлася б.
        """
        from nyshporka.archives import active

        pk = active()
        code = pk.resolve_code(archive)
        return pk.canon_repo(code) if code else ""

    def card(self, person_id: str) -> Card:
        return parse_card(self.page(f"id={quote(person_id)}"), person_id)

    def coverage(self) -> dict[str, int]:
        """Скільки осіб у базі від кожного архіву — з останньої сторінки сайту."""
        return dict(self._coverage)

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Живий запит; обсяг бази — з лічильників сайту, якщо вже їх бачили.

        🔴 `by_archive` — знаменник нуля: покриття нерівне на два порядки, і
        «немає» в архіві з кількома сотнями осіб важить інакше, ніж у тому,
        що дав десятки тисяч.
        """
        total = sum(self._coverage.values()) or None
        return "live", {"taken": "", "rows": total, "host": HOST,
                        "by_archive": dict(self._coverage) or None,
                        "scope": "особи, репресовані 1920–1950-х, у 27 архівах"}

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Особи за прізвищем. Запит: «Шевчук» або «Шевчук Ян Віцентович».

        Кожна особа — з картки: шифра справи є лише там. Тому пошук на N осіб
        коштує N+1 запитів, і `limit` тут — ще й темп.

        🔴 Скільки знайшла база всього і по яких архівах — у `Hits.truncated`,
        коли показано не всіх. «Показано 20» без «з 139» читалось би як повний
        перелік однофамільців.
        """
        ln, _fn, _sn = split_query(q)
        if not ln:
            return Hits()
        res = self.results(q, limit=limit)
        if not res.rows:
            return Hits()
        spread = ", ".join(f"{a} {n}" for a, n in res.by_archive.items())
        out = Hits()
        for row in res.rows:
            c = self.card(row.id)
            note = " · ".join(x for x in (
                f"арешт {c.get('Дата арешту')}" if c.get("Дата арешту") else "",
                c.get("Стаття звинувачення"),
                f"вирок: {c.get('Вирок')}" if c.get("Вирок") else "",
                f"реабілітація: {c.get('Відомості щодо реабілітації')}"
                if c.get("Відомості щодо реабілітації") else "",
                c.get("Рід занять або коротка характеристика")) if x)
            out.append(Hit(
                source=self.id, ref=f"person:{row.id}",
                title=c.name or row.name,
                years=_life(c, row.born),
                place=c.get("Місце проживання на момент арешту"),
                shifra=" ".join(x for x in (c.archive or row.archive, c.shifra) if x),
                repo=self._our_repo(c.archive or row.archive),
                archive=c.archive or row.archive, fond=c.get("Фонд"),
                acquirable=False,
                url=f"{HOST}{PAGE}?id={row.id}",
                note=note[:600]))
        if res.total > len(out):
            out.truncated = (f"показано {len(out)} з {res.total} осіб за цим "
                             f"прізвищем ({spread}) — звузь іменем чи по батькові")
        return out
