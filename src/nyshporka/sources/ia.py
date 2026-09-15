"""🗃 Internet Archive — повний текст колекцій і записів archive.org.

Навіщо поруч з архівами
───────────────────────
На archive.org лежить друковане, якого немає ніде більше одним входом: газети
діаспори («Свобода» 1893–2014, 23 180 чисел з OCR), єпархіальні відомості,
пам'ятні книжки. Сайт шукає по ТЕКСТУ цих сканів і на кожну знахідку віддає лист
і рамку слова, тож знахідка приходить разом із кропом — око бачить рядок до
завантаження. Замір 15.09.2026: «Креницька» у «Свободі» — три числа, у 1910-01
на листі 2 з рамкою кожного входження; у ПЕВ (запис із томом на кожен рік)
збіг приходить із назвою тому й листом.

🔴🔴 Індекс шукає ЛИШЕ точне слово
────────────────────────────────────
Замір 15.09.2026 на відомому позитиві: «Креницька» — 3 документи, «Креницьк*»,
«Креницьк» і «Креницкую~» — 0. Зірки, морфології й нечіткого пошуку немає;
`OR`/`AND` дають 0 на тих самих словах, що окремо знаходяться; слово зі змішаним
письмом (латинська K у кириличному слові) — 0. Фраза в лапках і пробіл як «і»
працюють, регістр байдужий. Тому такі запити тут ВІДМОВА, а не видача: нуль від
синтаксису, якого сервер не розуміє, читався б як «слова в текстах немає».

🔴 OCR-калік точним словом не ловиться: «Долищннскнме» ПЕВ 1862 стоїть у
djvu.txt, а пошук його не знаходить. Нуль звідси закриває лише перелічені форми;
калік ловить нечіткий пошук по тексту, взятому `nysh get ia`.

🪤 Латинка сліпа НЕ всюди. Глобально «Jersey» — 5,7 млн документів, а в межах
`svoboda_newspaper` «Jersey», «Svoboda» й «Ukrainian» — 0, хоча стоять у шапці
кожного числа 1985 року (замір 15.09.2026). Виміряні сліпі межі — `LATIN_BLIND`;
латинський запит у них відмовляє.

🪤 Збій бекенду приходить як HTTP 400, а не 5xx: тіло каже «the FTS API
request failed … HTTP 502», і той самий запит за хвилину відповідає. Тому 400
тут — відмова «не опитано», а не «запит поганий» (замір 15.09.2026).

🔴 Самоперевірка 15.09.2026: 18 із 21 випадкової фрази з різних епох «Свободи»
знайшлись; один промах — ранжування (994 документи), два не пояснені. Перенос
індекс не склеює: хвіст «трополита» шукається окремим словом.

Нумерація листів
────────────────
`inside.php` віддає номер ЛИСТА з нуля — той самий, що в імені `…_0521.jp2`,
у `usemap` сторінки `_djvu.xml` і в адресі переглядача `/page/n521`. Звірено
оком на двох записах (Svoboda-1910-01 лист 2, PEV.1900 лист 521). Відповідь із
`leaf0_missing: true` означає зсув, якого ми не міряли, — там кроп не будується.
Файли тексту й кадрів названо так само: `n0521.txt`, `n0521.jpg`.

⚠ `year` у фільтрі — рік ЗАПИСУ. У записі з багатьма документами (ПЕВ 1862–1905
одним записом) він один на всі, тож межа `year:` там ріже мимо; рік документа
береться з його імені.

Адресація (`ref`): `ia:<запис>` для запису з одним документом, `ia:<запис>/<doc>`
для кількох (`ia:podillya_vidomosti/PEV.1900`); приймається й адреса
`archive.org/details/<запис>[/<doc>]`.
Межі пошуку — у самому запиті: `in:<колекція або запис>` і `year:1900-1920`.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from nyshporka.sources.base import FetchResult, Hit, Manifest, SourceError
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://archive.org"
IIIF = "https://iiif.archive.org/image/iiif/3"
SEARCH = "/services/search/beta/page_production/"

#: Найбільша сторінка видачі, яку просимо. Глибше `page × розмір > 10 000` сервер
#: відповідає 400 (замір 15.09.2026), тож далі першої сторінки ми не йдемо.
PAGE_MAX = 100
#: Скільки документів отримують позицію й кроп. Кожен — окремий запит до
#: `inside.php`, а пошук без `--source` іде в усі джерела разом.
POSITION_MAX = 10

#: Спільна на машину черга до archive.org.
RATE_KEY = "archive.org"
RATE_MAX = 3
RATE_WINDOW = 3.0

#: Межі, де латинка в індексі сліпа (замір 15.09.2026, див. докстрінг).
LATIN_BLIND = frozenset({"svoboda_newspaper"})

#: Скільки промахів поспіль при завантаженні кадрів зупиняють прохід.
MISS_MAX = 10

_REF_RX = re.compile(r"^ia:([A-Za-z0-9._-]+)(?:/(.+))?$")
_DETAILS_RX = re.compile(
    r"^https?://(?:www\.)?archive\.org/details/([A-Za-z0-9._-]+)(?:/([^?#]*))?", re.IGNORECASE)
_SCOPE_RX = re.compile(r"(?<!\S)in:(\S+)")
_YEAR_RX = re.compile(r"(?<!\S)year:(\d{3,4})(?:-(\d{3,4}))?(?!\S)")
_OPERATOR_RX = re.compile(r"(?<!\S)(?:OR|AND|NOT)(?!\S)")
_LATIN_RX = re.compile(r"[A-Za-z]")
_CYR_RX = re.compile(r"[Ѐ-ӿ]")
_LEAF_RX = re.compile(r"_(\d{4,})\.djvu$")
_DOC_YEAR_RX = re.compile(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)")
_MATCH_OPEN = "<IA_FTS_MATCH>"
_MATCH_CLOSE = "</IA_FTS_MATCH>"


@dataclass(frozen=True)
class Query:
    """Запит, розібраний на слова й межі."""

    text: str
    scope: str = ""
    year_from: str = ""
    year_to: str = ""


def parse_query(q: str) -> Query:
    """Вирізати з рядка `in:<id>` і `year:рік[-рік]`; решта — слова пошуку."""
    s = " ".join((q or "").split())
    scope = ""
    m = _SCOPE_RX.search(s)
    if m:
        scope = m.group(1)
        s = _SCOPE_RX.sub(" ", s)
    y_from = y_to = ""
    m = _YEAR_RX.search(s)
    if m:
        y_from, y_to = m.group(1), m.group(2) or m.group(1)
        s = _YEAR_RX.sub(" ", s)
    return Query(text=" ".join(s.split()), scope=scope, year_from=y_from, year_to=y_to)


def check_terms(text: str, *, latin_blind: bool = False, scope: str = "") -> None:
    """🔴 Відмова на синтаксис, якого індекс не розуміє, — замість його нуля."""
    if "*" in text or "?" in text:
        raise SourceError(
            "індекс archive.org не знає зірки й форм слова: «Креницьк*» дає 0 там, де "
            "«Креницька» дає 3 (замір 15.09.2026) — перелічіть потрібні форми окремими "
            "запитами")
    if _OPERATOR_RX.search(text):
        raise SourceError(
            "OR/AND індекс archive.org не розуміє і віддає на них 0 — кожну форму "
            "треба шукати окремим запитом; пробіл між словами вже означає «і»")
    for word in re.findall(r"\w+", text):
        if _LATIN_RX.search(word) and _CYR_RX.search(word):
            raise SourceError(
                f"слово «{word}» змішує латинку й кирилицю — такого слова в індексі "
                f"немає, і нуль на нього нічого б не значив")
    if latin_blind and _LATIN_RX.search(text):
        raise SourceError(
            f"у межах «{scope}» латинка в індексі archive.org сліпа: «Jersey» дає 0, "
            f"хоча стоїть у шапці чисел (замір 15.09.2026) — шукайте кирилицею або "
            f"візьміть текст (`nysh get ia`) і шукайте в ньому")


def address_of(ref: str) -> tuple[str, str]:
    """`ref` → (запис, документ). Порожній документ — адреса його не назвала."""
    s = (ref or "").strip()
    m = _REF_RX.match(s) or _DETAILS_RX.match(s)
    if not m:
        raise SourceError(
            f"незрозуміла адреса: {ref!r} — тут очікується `ia:<запис>`, "
            f"`ia:<запис>/<doc>` або адреса archive.org/details/<запис>")
    doc = (m.group(2) or "").strip("/")
    # Адреса переглядача несе хвіст `/page/n521/mode/1up` — це не документ.
    doc = re.split(r"(?:^|/)(?:page|mode|search)/", doc)[0].strip("/")
    return m.group(1), doc


def iiif_id(ident: str, doc: str, leaf: int) -> str:
    """Ідентифікатор сторінки для IIIF — повний шлях до jp2 усередині архіву.

    🪤 Коротка форма `<запис>$<лист>` відповідає лише на `info.json` (через
    переадресацію), а на вирізку — 404 (замір 15.09.2026).
    """
    return "%2f".join((quote(ident, safe=""), f"{quote(doc, safe='')}_jp2.zip",
                       f"{quote(doc, safe='')}_jp2", f"{quote(doc, safe='')}_{leaf:04d}.jp2"))


def crop_url(ident: str, doc: str, leaf: int, box: dict[str, Any], *,
             page_width: int | None = None, page_height: int | None = None) -> str:
    """Вирізка навколо слова: рядок-два над і під ним, щоб око бачило контекст."""
    left, top, right, bottom = (int(box[k]) for k in ("l", "t", "r", "b"))
    h = max(1, bottom - top)
    pad_x = max(right - left, 12 * h)
    pad_y = 3 * h
    x0, y0 = max(0, left - pad_x), max(0, top - pad_y)
    x1, y1 = right + pad_x, bottom + pad_y
    if page_width:
        x1 = min(x1, int(page_width))
    if page_height:
        y1 = min(y1, int(page_height))
    region = f"{x0},{y0},{max(1, x1 - x0)},{max(1, y1 - y0)}"
    return f"{IIIF}/{iiif_id(ident, doc, leaf)}/{region}/max/0/default.jpg"


def viewer_url(ident: str, doc: str, leaf: int | None = None, q: str = "") -> str:
    base = f"{HOST}/details/{quote(ident, safe='')}"
    if doc and doc != ident:
        base += f"/{quote(doc, safe='')}"
    if leaf is not None:
        base += f"/page/n{leaf}/mode/1up"
    return base + (f"?q={quote(q, safe='')}" if q else "")


def snippet(text: str, width: int = 90) -> str:
    """Уривок навколо першого збігу; маркери сервера → «»."""
    s = " ".join((text or "").split())
    i = s.find(_MATCH_OPEN)
    if i >= 0:
        s = s[max(0, i - width):i + width + len(_MATCH_OPEN) + len(_MATCH_CLOSE)]
    s = s.replace(_MATCH_OPEN, "«").replace(_MATCH_CLOSE, "»")
    return s.replace("{{{", "«").replace("}}}", "»").strip()


def leaves_of_scandata(xml: str) -> list[int]:
    """Листи, що пішли в доступні формати (тобто мають сторінку й текст)."""
    root = ET.fromstring(xml)
    out: list[int] = []
    for page in root.iter("page"):
        num = page.get("leafNum")
        if num is None or not num.isdigit():
            continue
        flag = (page.findtext("addToAccessFormats") or "true").strip().lower()
        if flag != "false":
            out.append(int(num))
    return out


def pages_of_djvu_xml(path: Path) -> list[tuple[int, str]]:
    """`_djvu.xml` → [(лист, текст сторінки)] у порядку файла.

    🔴 Лист береться з `usemap`, а не з позиції: сторінка, яку скан не пустив у
    доступні формати, випадає з файла, і позиція після неї розходиться з номером
    листа, за яким будуються кроп і кадр.
    """
    out: list[tuple[int, str]] = []
    leaf: int | None = None
    lines: list[str] = []
    words: list[str] = []
    for event, el in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if el.tag == "OBJECT":
                m = _LEAF_RX.search(el.get("usemap") or "")
                leaf = int(m.group(1)) if m else None
                lines, words = [], []
            continue
        if el.tag == "WORD":
            if el.text and el.text.strip():
                words.append(el.text.strip())
        elif el.tag == "LINE":
            if words:
                lines.append(" ".join(words))
            words = []
        elif el.tag == "OBJECT":
            if leaf is None:
                raise SourceError(
                    f"сторінка №{len(out) + 1} у {path.name} не називає свого листа "
                    f"(usemap) — нумерацію тексту не можна звірити з кадрами")
            out.append((leaf, "\n".join(lines)))
            el.clear()
    return out


def _md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class IaSource:
    """Повнотекстовий пошук archive.org зі сторінкою й кропом; текст і кадри."""

    id = "ia"
    label = "Internet Archive (повний текст)"
    caps = frozenset({"search", "manifest", "fetch"})

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher
        self._meta_cache: dict[str, dict[str, Any]] = {}

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        return Fetcher(base=HOST, delay=0.0, limiter=lim, headers={"User-Agent": app_ua()})

    def _online(self) -> None:
        # 🔴 Вимкнена мережа — відмова, а не порожня видача.
        if offline() and self._fetcher is None:
            raise SourceError("мережу вимкнено в цьому середовищі — archive.org не опитано")

    def _json(self, url: str, what: str) -> Any:
        self._online()
        try:
            r = self._http().get(url)
        except (HttpError, OSError) as exc:
            raise SourceError(f"archive.org не відповів ({what}): {exc}") from exc
        try:
            return json.loads(getattr(r, "text", "") or "")
        except ValueError:
            raise SourceError(
                f"archive.org відповів не JSON ({what}) — API змінився або сервер "
                f"віддав сторінку-заглушку") from None

    def _text(self, url: str, what: str) -> str:
        self._online()
        try:
            return str(getattr(self._http().get(url), "text", "") or "")
        except (HttpError, OSError) as exc:
            raise SourceError(f"archive.org не відповів ({what}): {exc}") from exc

    def meta(self, ident: str) -> dict[str, Any]:
        """Метадані запису. 🪤 На неіснуючий запис сервер віддає `{}`, а не 404."""
        if ident not in self._meta_cache:
            data = self._json(f"{HOST}/metadata/{quote(ident, safe='')}", f"запис {ident}")
            if not isinstance(data, dict) or not isinstance(data.get("metadata"), dict):
                raise SourceError(f"на archive.org немає запису «{ident}»")
            self._meta_cache[ident] = data
        return self._meta_cache[ident]

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Живий запит по повному тексту; межі — у самому запиті."""
        return "live", {"taken": "", "rows": None,
                        "scope": "повний текст archive.org: лише точні слова й фраза в "
                                 "лапках; межа — in:<колекція|запис>, year:рік-рік",
                        "host": HOST}

    # ── пошук ────────────────────────────────────────────────────────────────

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Документи, де слово є, і для перших `POSITION_MAX` — кожен його лист.

        ⚠ Знахідка без `page` — документ, до якого позиція не запитувалась або
        сервер її не дав; чому саме — у примітці.
        """
        if not " ".join((q or "").split()):
            return []
        query = parse_query(q)
        if not query.text:
            raise SourceError("у запиті лише межі (in:/year:), а слова для пошуку немає")
        filters: dict[str, dict[str, str]] = {}
        if query.scope:
            md = self.meta(query.scope)["metadata"]
            kind = "collection" if md.get("mediatype") == "collection" else "identifier"
            filters[kind] = {query.scope: "inc"}
        if query.year_from:
            filters["year"] = {query.year_from: "gte", query.year_to: "lte"}
        check_terms(query.text, latin_blind=query.scope in LATIN_BLIND, scope=query.scope)

        params: dict[str, Any] = {"user_query": query.text, "service_backend": "fts",
                                  "hits_per_page": max(1, min(limit, PAGE_MAX)), "page": 1}
        if filters:
            params["filter_map"] = json.dumps(filters, ensure_ascii=False)
        data = self._json(f"{HOST}{SEARCH}?{urlencode(params)}", "пошук")
        try:
            block = data["response"]["body"]["hits"]
            total = int(block["total"])
            rows = list(block.get("hits") or [])
        except (KeyError, TypeError, ValueError):
            raise SourceError(
                "відповідь archive.org не схожа на видачу повнотекстового пошуку") from None

        out: list[Hit] = []
        for n, row in enumerate(rows):
            if len(out) >= limit:
                break
            if not isinstance(row, dict):
                continue
            f = row.get("fields") or {}
            ident = str(f.get("identifier") or "")
            if not ident:
                continue
            doc = str(f.get("file_basename") or ident)
            hl = ((row.get("highlight") or {}).get("text") or [""])[0]
            base = self._doc_hit(ident, doc, f, total)
            if n >= POSITION_MAX:
                out.append(_with(base, note=_note(snippet(hl), total,
                                                  f"позицію не запитано (лише перші "
                                                  f"{POSITION_MAX} документів)"),
                                 url=viewer_url(ident, doc, q=query.text)))
                continue
            try:
                placed = self._placed(base, ident, doc, query.text, total)
            except SourceError as exc:
                placed = []
                why = f"позиції сервер не дав: {exc}"
            else:
                why = "позиції сервер не дав: збіг є в документі, а рамки немає"
            if placed:
                out.extend(placed[:max(0, limit - len(out))])
            else:
                out.append(_with(base, note=_note(snippet(hl), total, why),
                                 url=viewer_url(ident, doc, q=query.text)))
        return out

    def _doc_hit(self, ident: str, doc: str, f: dict[str, Any], total: int) -> Hit:
        title = str(f.get("title") or ident)
        if doc != ident:
            title = f"{title} — {doc}"
            m = _DOC_YEAR_RX.search(doc)
            years = m.group(1) if m else ""
        else:
            years = str(f.get("year") or "")
        ref = f"ia:{ident}" if doc == ident else f"ia:{ident}/{doc}"
        return Hit(source=self.id, ref=ref, title=title[:200], years=years,
                   acquirable=True, archive="archive.org")

    def _placed(self, base: Hit, ident: str, doc: str, text: str, total: int) -> list[Hit]:
        """Кожне входження слова в документі — окрема знахідка з листом і кропом."""
        md = self.meta(ident)
        server, path = str(md.get("server") or ""), str(md.get("dir") or "")
        if not server or not path:
            raise SourceError("метадані запису не називають сервера з текстом")
        url = f"https://{server}/fulltext/inside.php?" + urlencode(
            {"item_id": ident, "doc": doc, "path": path, "q": text})
        data = self._json(url, f"позиція в {doc}")
        if not isinstance(data, dict):
            raise SourceError("відповідь inside.php не схожа на перелік збігів")
        shifted = data.get("leaf0_missing") is True
        out: list[Hit] = []
        seen: set[tuple[int, int, int]] = set()
        for m in data.get("matches") or []:
            snip = snippet(str(m.get("text") or ""))
            for par in m.get("par") or []:
                for box in par.get("boxes") or []:
                    try:
                        leaf = int(box.get("page", par.get("page")))
                        key = (leaf, int(box["l"]), int(box["t"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    # 🪤 Рамка слова буває без краю («Звід пам'яток», замір
                    # 15.09.2026: лише t, b, l). Абзац навколо має всі чотири —
                    # кроп стає ширшим, але слово в ньому є.
                    whole = _box(box)
                    frame = whole or _box(par)
                    if key in seen:
                        continue
                    seen.add(key)
                    if shifted:
                        out.append(_with(base, url=viewer_url(ident, doc, q=text), note=_note(
                            snip, total, f"сервер назвав лист {leaf}, але позначив зсув "
                                         f"нумерації (leaf0_missing) — кроп не будую, "
                                         f"сторінку звіряти в переглядачі")))
                        continue
                    where = f"лист n{leaf}"
                    if frame is None:
                        where += " · рамки слова й абзацу сервер не дав — кроп не будую"
                    elif whole is None:
                        where += " · рамка слова неповна — кроп по абзацу"
                    out.append(_with(
                        base, page=leaf, url=viewer_url(ident, doc, leaf, text),
                        crop_url=crop_url(ident, doc, leaf, frame,
                                          page_width=par.get("page_width"),
                                          page_height=par.get("page_height"))
                        if frame is not None else "",
                        note=_note(snip, total, where)))
        return out

    # ── запис і завантаження ────────────────────────────────────────────────

    def _files(self, md: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(f.get("name")): f for f in md.get("files") or [] if isinstance(f, dict)}

    def _doc(self, ident: str, doc: str, md: dict[str, Any]) -> str:
        names = self._files(md)
        docs = sorted({n[:-len(sfx)] for n in names
                       for sfx in ("_djvu.xml", "_jp2.zip") if n.endswith(sfx)})
        if doc:
            if doc not in docs:
                raise SourceError(f"у записі «{ident}» немає документа «{doc}» "
                                  f"(є: {', '.join(docs[:8]) or 'жодного'})")
            return doc
        if len(docs) == 1:
            return docs[0]
        if not docs:
            raise SourceError(f"у записі «{ident}» немає сторінок з OCR — ні тексту, "
                              f"ні кадрів звідси не буде")
        raise SourceError(
            f"у записі «{ident}» {len(docs)} документів — адреса має назвати один: "
            f"ia:{ident}/<doc>, напр. {', '.join(f'ia:{ident}/{d}' for d in docs[:3])}")

    def _leaves(self, ident: str, doc: str, md: dict[str, Any]) -> list[int] | None:
        """Листи документа зі скану. Невідомо — `None`, а не порожньо."""
        name = f"{doc}_scandata.xml"
        if name in self._files(md):
            xml = self._text(f"{HOST}/download/{quote(ident, safe='')}/{quote(name)}",
                             f"перелік листів {doc}")
            try:
                return leaves_of_scandata(xml)
            except ET.ParseError:
                raise SourceError(f"{name} не читається як XML") from None
        count = (md.get("metadata") or {}).get("imagecount")
        if doc == ident and str(count or "").isdigit():
            return list(range(int(str(count))))
        return None

    def manifest(self, ref: str) -> Manifest:
        """Скільки листів у документі й скільки важить його текст — до початку.

        «Кадр» тут — лист. Текст приходить одним `_djvu.xml` і розкладається по
        листах, кадри — по одному JPEG на лист.
        """
        ident, doc = address_of(ref)
        md = self.meta(ident)
        doc = self._doc(ident, doc, md)
        leaves = self._leaves(ident, doc, md)
        xml = self._files(md).get(f"{doc}_djvu.xml") or {}
        title = str((md.get("metadata") or {}).get("title") or ident)
        if doc != ident:
            title = f"{title} — {doc}"
        return Manifest(
            source=self.id, ref=ref, title=title,
            frames=len(leaves) if leaves is not None else None,
            bytes_estimate=int(xml["size"]) if str(xml.get("size") or "").isdigit() else None,
            meta={"url": viewer_url(ident, doc), "identifier": ident, "doc": doc,
                  "leaves": leaves or [],
                  "files": [{"name": xml.get("name"), "size": xml.get("size"),
                             "md5": xml.get("md5")}] if xml else []})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        """Без `frames` — текст по листах; з `frames` — JPEG цих листів."""
        ident, doc = address_of(ref)
        md = self.meta(ident)
        doc = self._doc(ident, doc, md)
        leaves = self._leaves(ident, doc, md)
        dest.mkdir(parents=True, exist_ok=True)
        if frames is None:
            return self._fetch_text(ident, doc, md, leaves, dest, on_progress)
        return self._fetch_frames(ident, doc, leaves, frames, dest, on_progress)

    def _fetch_text(self, ident: str, doc: str, md: dict[str, Any],
                    leaves: list[int] | None, dest: Path,
                    on_progress: ProgressFn | None) -> FetchResult:
        """🔴 Приймач — сума й розмір, які назвав сервер, а не «файл є»."""
        import httpx

        from nyshporka.cases.acquire import patch_meta

        name = f"{doc}_djvu.xml"
        f = self._files(md).get(name)
        if f is None:
            raise SourceError(f"у документа «{doc}» немає тексту OCR ({name}) — "
                              f"візьміть кадри: --frames")
        size = int(f["size"]) if str(f.get("size") or "").isdigit() else 0
        md5 = str(f.get("md5") or "").lower()
        url = f"{HOST}/download/{quote(ident, safe='')}/{quote(name)}"
        out = dest / name
        res = FetchResult(dest=dest)
        fresh = not (out.is_file() and (not size or out.stat().st_size == size)
                     and (not md5 or _md5(out) == md5) and (size or md5))
        if fresh:
            self._online()

            def _tick(done: int) -> None:
                if on_progress is not None:
                    on_progress(done=done, total=size or None, unit="байт", note=name)

            try:
                got = self._http().download(url, out, on_chunk=_tick)
            except (HttpError, OSError, httpx.HTTPError) as exc:
                out.with_name(out.name + ".part").unlink(missing_ok=True)
                res.errors.append(f"{name}: {exc}")
                return res
            if size and got != size:
                out.unlink(missing_ok=True)
                res.errors.append(f"{name}: отримано {got} байт замість {size} — файл "
                                  f"неповний, тож у теку він не ліг")
                return res
            if md5 and _md5(out) != md5:
                out.unlink(missing_ok=True)
                res.errors.append(f"{name}: контрольна сума не зійшлась із тією, що "
                                  f"назвав сервер — файл пошкоджений, у теку не ліг")
                return res
            res.bytes = got
        try:
            pages = pages_of_djvu_xml(out)
        except ET.ParseError as exc:
            res.errors.append(f"{name}: не читається як XML ({exc})")
            return res

        folder = dest / f"{doc}.text"
        folder.mkdir(parents=True, exist_ok=True)
        # Старі сторінки попереднього розбору відповідали б регексу за текст,
        # якого в цьому файлі вже немає.
        for old in folder.glob("n*.txt"):
            old.unlink()
        wanted = set(leaves) if leaves is not None else None
        written = with_text = 0
        extra: list[int] = []
        for leaf, body in pages:
            (folder / f"n{leaf:04d}.txt").write_text(body + "\n" if body else "",
                                                     encoding="utf-8")
            if wanted is not None and leaf not in wanted:
                extra.append(leaf)
                continue
            written += 1
            with_text += bool(body)
        if fresh:
            res.frames = written
        else:
            res.skipped = written
        if wanted is not None:
            missing = sorted(wanted - {leaf for leaf, _ in pages})
            if missing:
                res.notes.append(f"у тексті немає {len(missing)} листів скану: "
                                 f"{', '.join(f'n{x}' for x in missing[:10])}")
        if extra:
            res.notes.append(f"текст має листи поза переліком скану: "
                             f"{', '.join(f'n{x}' for x in extra[:10])} — записано, не пораховано")
        if written and with_text < written:
            res.notes.append(f"{written - with_text} з {written} листів без тексту в OCR")
        patch_meta(dest, {
            "ia": {"identifier": ident, "doc": doc, "url": viewer_url(ident, doc)},
            "files": [{"file": name, "size": size, "md5": md5, "source_url": url}],
            "text_layer": {"folder": folder.name, "pages": written,
                           "pages_with_text": with_text,
                           "numbering": "n = номер листа IA (як у переглядачі й IIIF)"}})
        return res

    def _fetch_frames(self, ident: str, doc: str, leaves: list[int] | None,
                      frames: tuple[int, int], dest: Path,
                      on_progress: ProgressFn | None) -> FetchResult:
        """JPEG листів через IIIF. Номери в `frames` — номери листів (`n…`)."""
        from PIL import Image

        from nyshporka.cases.acquire import patch_meta
        from nyshporka.utils.atomic import atomic_write_bytes

        lo, hi = min(frames), max(frames)
        known = set(leaves) if leaves is not None else None
        res = FetchResult(dest=dest)
        if known is None:
            res.notes.append("перелік листів цього документа невідомий — діапазон "
                             "не звірено зі сканом")
        todo = list(range(lo, hi + 1))
        misses = 0
        http = self._http()
        self._online()
        with http.client() as c:
            for i, leaf in enumerate(todo, 1):
                if on_progress is not None:
                    on_progress(done=i - 1, total=len(todo), unit="кадр", note=f"n{leaf}")
                if known is not None and leaf not in known:
                    span = f"n{min(known)}–n{max(known)}" if known else "жодного"
                    res.errors.append(f"лист n{leaf}: у документі такого листа немає ({span})")
                    continue
                out = dest / f"n{leaf:04d}.jpg"
                if out.is_file() and out.stat().st_size > 0:
                    res.skipped += 1
                    continue
                url = f"{IIIF}/{iiif_id(ident, doc, leaf)}/full/max/0/default.jpg"
                try:
                    r = http.get(url, client=c)
                    blob = bytes(getattr(r, "content", b"") or b"")
                    want = (getattr(r, "headers", None) or {}).get("content-length")
                    if want is not None and str(want).isdigit() and int(want) != len(blob):
                        raise SourceError(f"отримано {len(blob)} байт замість {want}")
                    try:
                        Image.open(BytesIO(blob)).verify()
                    except Exception:  # PIL кидає різне на різні пошкодження
                        raise SourceError("відповідь не читається як зображення") from None
                    atomic_write_bytes(out, blob)
                except (HttpError, OSError, SourceError) as exc:
                    res.errors.append(f"лист n{leaf}: {exc}")
                    misses += 1
                    if misses >= MISS_MAX:
                        res.notes.append(f"{MISS_MAX} промахів поспіль — прохід зупинено")
                        break
                    continue
                misses = 0
                res.frames += 1
                res.bytes += len(blob)
        patch_meta(dest, {"ia": {"identifier": ident, "doc": doc,
                                 "url": viewer_url(ident, doc),
                                 "frames_numbering": "n = номер листа IA (як у переглядачі й IIIF)"}})
        return res

    def browse(self, ref: str | None = None) -> list[Any]:
        """🔴 Відмова, а не порожній список: дерева тут немає."""
        raise SourceError(
            "у archive.org тут немає дерева: межу пошуку задає сам запит — "
            "`nysh find \"<слово> in:<колекція або запис>\" --source ia`")


def _note(snip: str, total: int, where: str) -> str:
    parts = (f"«{snip}»" if snip and not snip.startswith("«") else snip, where,
             f"з {total} документів за запитом", "лише точне слово")
    return " · ".join(p for p in parts if p)


def _box(obj: dict[str, Any]) -> dict[str, int] | None:
    """Рамка з усіма чотирма краями числами — або `None`."""
    try:
        return {k: int(obj[k]) for k in ("l", "t", "r", "b")}
    except (KeyError, TypeError, ValueError):
        return None


def _with(hit: Hit, **changes: Any) -> Hit:
    from dataclasses import replace

    return replace(hit, **changes)
