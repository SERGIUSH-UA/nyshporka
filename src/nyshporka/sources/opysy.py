"""📑 Описи фондів архіву в PDF зі сторінки-каталогу архіву (ЦДІАЛ: `index5.html`).

Архів тримає описи фондів скановані PDF-файлами на своєму сайті. Тексту в них
немає (скан без текстового шару), тож джерело лише КЛАДЕ файл у теку з
паспортом; розпізнавання — окрема робота читання.

🔴 Назви файлів НЕ вгадуються. Вони нерегулярні: `F. 20 op. 16.pdf`,
`F. 20, op. XVI.pdf` (римськими), `F. 146 op.4-1.pdf` (частини), `F. 146 op. 7а.pdf`
(літера), `Ф. 19, оп. 16.pdf` (кирилицею — з ASCII-«F.» сервер відповідає 500),
а в кількох іменах кириличні «ор.» набрано в різних абетках. Єдине джерело
правди — сама сторінка: біля кожного посилання стоїть підпис «Опис 16» під
заголовком «Фонд 20». Шифра «ф.20 оп.16» розв'язується через цей каталог, а де
запису немає, відповідь «опису онлайн немає», а не підібране ім'я.

🔴 Кодування сторінки — windows-1251 (`<meta charset="windows-1251">`; другий
`<meta>` каже `iso-8859-1`, і вірити йому не можна — «мініатюра» кирилиці
перетворюється на «�»). Читається за першим оголошенням і СТРОГО: розбіжність —
відмова, а не `errors="replace"`, бо зіпсована назва фонду чи опису дала б
хибний нуль.

🛡 Хост за Akamai: `httpx`, системний `curl` і headless-браузер дістають 403
«Access Denied» (`errors.edgesuite.net`) навіть із повним набором заголовків —
ріже TLS-відбиток. Тому майданчик у паку (`sites.opysy`) має `shield: tls`, і
HTTP-шар (`Fetcher(tls=True)`) вдає рукостискання Chrome через `curl_cffi`
(`pip install nyshporka[cfshield]`). Без нього — відмова вголос, а не тихий
перехід на клієнта, якого однаково відсічуть.

Адреса (`ref`): `<фонд>/<опис>` — `20/16`, `146/4 т.1`; приймається й «ф.20 оп.16»,
«ЦДІАЛ 20-16», «F. 146 op. 7а». `file:<ім'я файла зі сторінки>` — файл довідника.
Нічого, крім фонду й опису: третє число — номер СПРАВИ, а це PDF опису, не справи.

Куди класти: `nysh get cdial-opysy 20/16 --out <простір>/data/raw/cdial_20/` — тека
`data/raw/<slug>/`, як решта теченців фондів Майстерні (`dahmo_230`).
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from nyshporka.sources.base import (
    FetchResult,
    Manifest,
    Node,
    SourceAbout,
    SourceError,
    SourceScope,
)
from nyshporka.sources.http import Fetcher, HttpError, offline

if TYPE_CHECKING:
    from nyshporka.archives.pack import Site
    from nyshporka.sources.base import ProgressFn

#: Темп спільний на машину: сайт державного архіву, а не CDN.
RATE_KEY = "tsdial"
RATE_MAX = 3
RATE_WINDOW = 10.0
#: Скільки днів живе кеш сторінки-каталогу.
CATALOG_TTL_DAYS = 7
#: Стеля на сторінку-каталог (заміряно 25.10.2026: ~200 КБ).
PAGE_MAX_BYTES = 8 * 1024 * 1024
#: Стеля на один PDF: найбільший опис на сторінці — ~135 МБ.
PDF_MAX_BYTES = 1024 * 1024 * 1024


# ── зведення написань ────────────────────────────────────────────────────────

#: Латинські двійники кириличних літер (у підписах «Опис 1б» буває «b», «a»).
_LATIN = str.maketrans({"a": "а", "c": "с", "e": "е", "i": "і", "o": "о", "p": "р",
                        "x": "х", "y": "у", "k": "к", "t": "т", "m": "м", "h": "н",
                        "b": "б"})
_ROMAN_RX = re.compile(r"^[IVXLCХІ]+$")
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman(s: str) -> int | None:
    """XVI → 16; кириличні Х та І (OCR і набір руками) читаються як латинські."""
    t = s.upper().replace("Х", "X").replace("І", "I")
    if not _ROMAN_RX.match(t) or any(ch not in _ROMAN for ch in t):
        return None
    total = 0
    for i, ch in enumerate(t):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(t) and _ROMAN[t[i + 1]] > v else v
    return total


def opys_keys(label: str) -> set[str]:
    """Ключі, за якими опис упізнається: «4 т.1» ≡ «4-1» ≡ «4т1», «XVI» ≡ «16»."""
    raw = _html.unescape(label or "").replace("\xa0", " ")
    t = raw.casefold().translate(_LATIN)
    t = re.sub(r"[\s.,]+", "", t)
    keys = {t} if t else set()
    m = re.fullmatch(r"(\d+)(?:т|том|-)(\d+)", t)
    if m:
        keys |= {f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}т{m.group(2)}"}
    r = _roman(t)
    if r is not None:
        keys.add(str(r))
    return keys


def fond_key(fond: str) -> str:
    return re.sub(r"[\s.]+", "", _html.unescape(fond or "")).casefold().translate(_LATIN)


# ── каталог ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    """Рядок сторінки: опис фонду й файл, що йому відповідає."""

    fond: str           # «146», «У-9», «KMF-1»
    fond_title: str     # «Галицьке намісництво, м. Львів»
    label: str          # «Опис 4 т.1» без слова «Опис»: «4 т.1»
    name: str           # ім'я файла зі сторінки: «F. 146 op.4-1.pdf»
    size_hint: int      # байтів за підписом «(70,7 MB)»; 0 — підпису немає

    @property
    def keys(self) -> set[str]:
        return opys_keys(self.label) | _file_keys(self.name)

    @property
    def ref(self) -> str:
        return f"{self.fond}/{self.label}"


def _file_keys(name: str) -> set[str]:
    """Опис, названий в імені файла: `op.4-1`, `оп. XVI`, `ор. 23 б`."""
    stem = re.sub(r"\.pdf$", "", _html.unescape(name), flags=re.IGNORECASE)
    m = re.search(r"(?:^|[\s,])(?:[oо][pр]|оп)\.?\s*(.+)$", stem, re.IGNORECASE)
    return opys_keys(m.group(1)) if m else set()


_HEAD_RX = re.compile(r"<b>\s*(?P<head>[^<]*?)\s*</b>\s*(?P<title>[^<]*?)\s*<br\s*/?>",
                      re.IGNORECASE)
_ROW_RX = re.compile(
    r'Опис(?:&nbsp;|\s)+(?P<label>[^<]*?)(?:&nbsp;|\s)*<a href="pdf/(?P<name>[^"]+)"[^>]*>'
    r"\s*Файл[^(<]*\((?P<size>[\d.,]+)\s*(?P<unit>[МMКKГG][BВ]?)\)", re.IGNORECASE)
_MARK_RX = re.compile(r"<b>|Опис(?:&nbsp;|\s)+[^<]*?(?:&nbsp;|\s)*<a href=\"pdf/",
                      re.IGNORECASE)


def decode_page(raw: bytes) -> str:
    """Сторінка → текст за ПЕРШИМ оголошеним кодуванням; строго.

    Другий `<meta>` сторінки каже `iso-8859-1` і суперечить першому: кирилиця
    через нього стає «�». Не декодується — відмова, а не заміна.
    """
    m = re.search(rb'<meta[^>]+charset=["\']?([A-Za-z0-9_-]+)', raw[:4000], re.IGNORECASE)
    enc = m.group(1).decode("ascii").lower() if m else "utf-8"
    try:
        return raw.decode(enc)
    except (UnicodeDecodeError, LookupError) as exc:
        raise SourceError(
            f"сторінка-каталог не читається як {enc} ({exc}) — кодування змінилось, "
            f"і назви фондів зі сторінки були б зіпсовані") from exc


def _size(num: str, unit: str) -> int:
    try:
        v = float(num.replace(",", "."))
    except ValueError:
        return 0
    k = unit.upper()[:1]
    return int(v * (1 << 30 if k in "ГG" else 1 << 20 if k in "МM" else 1 << 10))


def parse_catalog(text: str) -> list[Entry]:
    """Сторінка → описи. 🔴 Порожній розбір — відмова, а не «описів немає»."""
    entries: list[Entry] = []
    fond, title = "", ""
    pos = 0
    while True:
        m = _MARK_RX.search(text, pos)
        if m is None:
            break
        if m.group(0).lower().startswith("<b>"):
            h = _HEAD_RX.match(text, m.start())
            if h:
                head = _html.unescape(h.group("head")).replace("\xa0", " ").strip()
                fm = re.match(r"Фонд\s+(\S+)", head)
                if fm:
                    fond, title = fm.group(1), _tidy(h.group("title"))
                elif head:
                    # «Колекція мікрофільмів №1»: ключ — з імені файла нижче
                    fond, title = "", _tidy(head + " " + h.group("title"))
            pos = m.end()
            continue
        r = _ROW_RX.match(text, m.start())
        if r is None:
            pos = m.end()
            continue
        name = _html.unescape(r.group("name")).strip()
        label = _tidy(r.group("label"))
        f = fond or _fond_of_file(name)
        if f:
            entries.append(Entry(fond=f, fond_title=title, label=label, name=name,
                                 size_hint=_size(r.group("size"), r.group("unit"))))
        pos = r.end()
    if not entries:
        raise SourceError("на сторінці-каталозі не знайдено жодного опису — розмітка "
                          "змінилась, і «описів немає» з цього розбору було б вигаданим")
    return entries


def _fond_of_file(name: str) -> str:
    m = re.match(r"(KMF-\d+)", name)
    return m.group(1) if m else ""


def _tidy(s: str) -> str:
    return " ".join(_html.unescape(s or "").replace("\xa0", " ").split())


# ── адреса ───────────────────────────────────────────────────────────────────

_PREFIX_RX = re.compile(r"^\s*(?:ЦДІАЛ|ЦДИАЛ|CDIAL|TSDIAL)\b[\s,:/-]*", re.IGNORECASE)
_FOND_RX = re.compile(r"^(?:фонд\s+|[ФF][.,]?\s*)?(?P<fond>[A-ZА-ЯҐІЇЄ]{1,4}-\d+|\d+)", re.IGNORECASE)
_OPYS_MARK_RX = re.compile(r"^[\s,/-]*(?:(?:оп|ор|op|опис)\.?\s*)?", re.IGNORECASE)


def parse_ref(ref: str) -> tuple[str, str]:
    """`20/16`, «ф.20 оп.16», «ЦДІАЛ 146-4-1» → (фонд, опис). Опис може бути порожнім.

    🔴 Лише фонд і опис. «19-16-115» — це справа, а не опис: джерело віддає PDF
    опису, і мовчки відкинути номер справи означало б віддати не те, про що
    питали.
    """
    s = _PREFIX_RX.sub("", (ref or "").strip())
    m = _FOND_RX.match(s)
    if not m:
        raise SourceError(f"незрозуміла адреса: {ref!r} — очікується `<фонд>/<опис>`, "
                          f"наприклад `20/16`")
    fond = m.group("fond")
    rest = _OPYS_MARK_RX.sub("", s[m.end():], count=1).strip()
    return fond, rest


class OpysySource:
    """Описи фондів у PDF зі сторінки-каталогу архіву; лише кладе файл і паспорт."""

    id = "cdial-opysy"
    label = "Описи фондів ЦДІАЛ у PDF (сторінка архіву)"
    caps = frozenset({"browse", "manifest", "fetch"})
    CATALOG_REL = Path("data") / "raw" / "cdial_opysy" / "_crawl" / "index.json"
    about = SourceAbout(
        answers="чи виставлено опис фонду онлайн і де взяти його PDF за шифрою "
                "«фонд + опис»",
        gives="PDF опису з паспортом (адреса, розмір, час); перелік описів фонду й "
              "фондів зі сторінки архіву",
        not_gives="тексту опису — це скан без текстового шару, розпізнавання "
                  "окремо; описів, яких на сторінці немає; справ із цих описів",
        where_class="реєстр опису фонду",
        scope=SourceScope(archives=("CDIAL",),
                          note="лише те, що виставлено на сторінці-каталозі архіву"),
        match_on=(), match_how=None,
        zero_means="не шукає; «опису онлайн немає» каже каталог зі сторінки архіву "
                   "на дату кешу — не «опису в архіві немає»",
        pitfalls=("сайт за Akamai: без `curl_cffi` (`nyshporka[cfshield]`) не "
                  "проходить узагалі — це відмова сайту, не відсутність опису",
                  "назви файлів нерегулярні, тому шифра розв'язується через "
                  "сторінку-каталог, а не складається",
                  "частини опису («4 т.1», «4 т.2») — окремі файли: «4» без "
                  "уточнення неоднозначне"))

    def __init__(self, workspace: Path | None = None, *, site: Site | None = None,
                 repo: str = "CDIAL", fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self.repo = repo
        self._site = site
        self._fetcher = fetcher
        self._entries: list[Entry] | None = None
        self._note = ""

    # ── транспорт ────────────────────────────────────────────────────────────

    def site(self) -> Site:
        if self._site is None:
            from nyshporka.archives import active

            self._site = active().site(self.repo, "opysy")
        if self._site is None or not self._site.url or not self._site.page:
            raise SourceError(f"у паку архівів для {self.repo} немає майданчика "
                              f"`opysy` (url і page) — звідки брати описи, невідомо")
        return self._site

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        site = self.site()
        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        # Один запит — одна спроба: на цьому хості неіснуюче ім'я відповідає 500, і
        # шість спроб із відступом лише розтягнули б відповідь «такого файла немає».
        return Fetcher(base=site.url, delay=0.0, limiter=lim, attempts=1,
                       retry_429=False, tls=site.shield == "tls",
                       headers={"Referer": f"{site.url}/{site.page}"})

    def _online(self) -> None:
        if offline() and self._fetcher is None:
            raise SourceError("мережу вимкнено в цьому середовищі — сторінку архіву "
                              "не опитано")

    def _url(self, name: str) -> str:
        # Ім'я зі сторінки (декодоване з windows-1251) — у UTF-8: так його знає
        # файлова система сервера (перевірено 25.10.2026 на «Ф. 19, оп. 16.pdf»).
        return f"{self.site().url}/pdf/{quote(name, safe='')}".replace("%2F", "/")

    def _fail(self, exc: BaseException, what: str) -> SourceError:
        from nyshporka.sources.cfclient import ShieldError, akamai_denied

        if isinstance(exc, ShieldError):
            return SourceError(str(exc))
        body = str(getattr(exc, "body", "") or "")
        status = getattr(exc, "status", None)
        if status == 403 or akamai_denied(body):
            return SourceError(
                f"Akamai відсік запит ({what}, 403) навіть із відбитком Chrome — "
                f"це відмова сайту (мережа чи IP), а не відсутність опису")
        if status == 500:
            return SourceError(f"сервер архіву відповів 500 ({what}) — такого файла "
                               f"на ньому немає під цим іменем")
        return SourceError(f"сайт архіву не відповів ({what}): {exc}")

    # ── каталог ──────────────────────────────────────────────────────────────

    def entries(self) -> list[Entry]:
        if self._entries is not None:
            return self._entries
        path = self.workspace / self.CATALOG_REL if self.workspace else None
        stale: dict[str, Any] | None = None
        if path is not None and path.is_file():
            try:
                stale = json.loads(path.read_text(encoding="utf-8"))
                age = (time.time() - float(stale["fetched"])) / 86400
                if age < CATALOG_TTL_DAYS and stale.get("entries"):
                    self._entries = [Entry(**e) for e in stale["entries"]]
                    return self._entries
            except (ValueError, TypeError, KeyError, OSError):
                stale = None
        site = self.site()
        self._online()
        try:
            r = self._http().get(f"{site.url}/{site.page}")
            raw = bytes(r.content)
            if len(raw) > PAGE_MAX_BYTES:
                raise SourceError(f"сторінка-каталог завелика ({len(raw)} байт) — не те, що очікувалось")
            entries = parse_catalog(decode_page(raw))
        except HttpError as exc:
            err = self._fail(exc, "сторінка-каталог")
        except SourceError as exc:
            err = exc
        except Exception as exc:       # ShieldError і транспорт curl_cffi
            err = self._fail(exc, "сторінка-каталог")
        else:
            self._entries = entries
            if path is not None:
                from nyshporka.utils.atomic import write_json

                write_json(path, {"fetched": time.time(), "page": site.page,
                                  "entries": [asdict(e) for e in entries]}, indent=None)
            return entries
        if stale and stale.get("entries"):
            self._entries = [Entry(**e) for e in stale["entries"]]
            self._note = f"каталог із кешу, оновити не вдалось: {err}"
            return self._entries
        raise err

    def _resolve(self, ref: str) -> Entry:
        entries = self.entries()
        r = (ref or "").strip()
        if r.lower().startswith("file:"):
            name = r[5:].strip()
            hit = [e for e in entries if e.name == name]
            if not hit:
                raise SourceError(f"на сторінці-каталозі немає файла «{name}»")
            return hit[0]
        fond, opys = parse_ref(r)
        fk = fond_key(fond)
        of_fond = [e for e in entries if fond_key(e.fond) == fk]
        if not of_fond:
            raise SourceError(
                f"фонду {fond} немає на сторінці-каталозі {self.site().page} "
                f"({len({e.fond for e in entries})} фондів, {len(entries)} описів"
                f"{'; ' + self._note if self._note else ''}) — опису онлайн немає; "
                f"в архіві він може бути")
        if not opys:
            if len(of_fond) == 1:
                return of_fond[0]
            raise SourceError(f"у фонді {fond} {len(of_fond)} описів — назвіть один: "
                              f"{self._list(of_fond)}")
        want = opys_keys(opys)
        hit = [e for e in of_fond if e.keys & want]
        if len(hit) == 1:
            return hit[0]
        if hit:
            raise SourceError(f"«{opys}» у фонді {fond} підходить до кількох файлів — "
                              f"назвіть один: {self._list(hit)}")
        case = re.match(r"(.+?)[-/\s]+(\d+)$", opys)
        if case:
            one = [e for e in of_fond if e.keys & opys_keys(case.group(1))]
            if len(one) == 1:
                raise SourceError(
                    f"«{ref.strip()}» схоже на шифру СПРАВИ: джерело віддає PDF опису, "
                    f"а не справи. Опис ф.{fond} оп.{one[0].label} є: "
                    f"`nysh get cdial-opysy {one[0].ref}`")
        raise SourceError(f"опису {opys} фонду {fond} онлайн немає: на сторінці є "
                          f"{self._list(of_fond)}")

    @staticmethod
    def _list(entries: list[Entry]) -> str:
        return ", ".join(e.ref for e in entries[:24]) + (" …" if len(entries) > 24 else "")

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        n = len(self._entries or [])
        return "live", {"taken": "", "rows": n or None, "host": self.site().url}

    # ── browse / manifest / fetch ────────────────────────────────────────────

    def browse(self, ref: str | None = None) -> list[Node]:
        entries = self.entries()
        if not ref:
            by: dict[str, list[Entry]] = {}
            for e in entries:
                by.setdefault(e.fond, []).append(e)
            return [Node(ref=f, label=f"Фонд {f} «{es[0].fond_title}» — описів: {len(es)}",
                         kind="folder") for f, es in by.items()]
        fk = fond_key(parse_ref(ref)[0])
        of_fond = [e for e in entries if fond_key(e.fond) == fk]
        if not of_fond:
            raise SourceError(f"фонду {ref} немає на сторінці-каталозі — опису онлайн "
                              f"немає")
        return [Node(ref=e.ref, label=f"Опис {e.label} — {e.name}", kind="file",
                     size=e.size_hint or None) for e in of_fond]

    def _probe(self, e: Entry) -> tuple[int, str]:
        """Розмір PDF із відповіді сервера (`Content-Range`) і ознака `%PDF`."""
        self._online()
        url = self._url(e.name)
        fetcher = self._http()
        try:
            if fetcher.limiter is not None:
                fetcher.limiter.acquire(url)
            with fetcher.client() as c:
                r = c.get(url, headers={"Range": "bytes=0-4"})
        except Exception as exc:
            raise self._fail(exc, e.name) from exc
        code = int(getattr(r, "status_code", 0) or 0)
        if code >= 400:
            raise self._fail(HttpError(f"{url}: HTTP {code}", status=code,
                                       body=str(getattr(r, "text", "") or "")), e.name)
        head = bytes(getattr(r, "content", b"") or b"")[:5]
        hdr = getattr(r, "headers", None) or {}
        total = 0
        cr = str(hdr.get("content-range") or hdr.get("Content-Range") or "")
        m = re.search(r"/(\d+)\s*$", cr)
        if m:
            total = int(m.group(1))
        elif str(hdr.get("content-length") or "").isdigit() and code == 200:
            total = int(hdr["content-length"])
        if head != b"%PDF-":
            raise SourceError(f"{e.name}: відповідь не схожа на PDF (початок {head!r}) — "
                              f"сайт віддав не файл опису")
        return total, "application/pdf"

    def manifest(self, ref: str) -> Manifest:
        e = self._resolve(ref)
        total, _mime = self._probe(e)
        return Manifest(
            source=self.id, ref=ref, title=f"{self.repo} ф.{e.fond} оп.{e.label}: "
                                           f"{e.fond_title}"[:200],
            # Одиниця — ФАЙЛ: опис тут один PDF без текстового шару, сторінки
            # рахує читання.
            frames=1, bytes_estimate=total or e.size_hint or None,
            meta={"url": self._url(e.name), "name": e.name, "fond": e.fond,
                  "opys": e.label, "fond_title": e.fond_title, "unit": "файл",
                  "size_hint": e.size_hint, "text_layer": False,
                  "suggested_dest": f"data/raw/cdial_{fond_key(e.fond)}/"})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        """PDF опису цілком у `dest`; паспорт — `nysh get` (і `meta.json` тут)."""
        from nyshporka.utils.fsname import UnsafeName, safe_filename

        if frames is not None:
            raise SourceError("опис — один PDF; окремі кадри звідси не беруться "
                              "(скан без текстового шару, сторінки вибирає читання)")
        e = self._resolve(ref)
        total, _mime = self._probe(e)
        try:
            out = dest / safe_filename(e.name)
        except UnsafeName as exc:
            raise SourceError(f"ім'я файла зі сторінки не годиться для диска: {exc}") from exc
        dest.mkdir(parents=True, exist_ok=True)
        res = FetchResult(dest=dest)
        if out.is_file() and total and out.stat().st_size == total \
                and _is_pdf(out):
            res.skipped = 1
            res.bytes = total
            self._passport(dest, e, out, total)
            return res
        url = self._url(e.name)

        def _tick(done: int) -> None:
            if on_progress is not None:
                on_progress(done=done, total=total or None, unit="байт", note=e.name)

        self._online()
        try:
            got = self._http().download(url, out, on_chunk=_tick,
                                        max_bytes=total or PDF_MAX_BYTES)
        except Exception as exc:    # HttpError, OSError, ShieldError, транспорт
            res.errors.append(f"{e.name}: {self._fail(exc, e.name)}")
            return res
        # 🔴 Приймач — розмір, який назвав сервер, і сигнатура PDF, а не «файл є».
        if total and got != total:
            out.unlink(missing_ok=True)
            res.errors.append(f"{e.name}: отримано {got} байт замість {total} — файл "
                              f"неповний, у теку він не ліг")
            return res
        if not _is_pdf(out):
            out.unlink(missing_ok=True)
            res.errors.append(f"{e.name}: файл не починається з %PDF — сайт віддав не опис")
            return res
        res.frames = 1
        res.bytes = got
        self._passport(dest, e, out, got)
        res.notes.append("скан без текстового шару: шукати в ньому регексом не вийде, "
                         "розпізнавання — окрема робота читання")
        return res

    def _passport(self, dest: Path, e: Entry, out: Path, size: int) -> None:
        from nyshporka.cases.acquire import patch_meta

        patch_meta(dest, {
            "cdial_opysy": {"repo": self.repo, "fond": e.fond, "opys": e.label,
                            "fond_title": e.fond_title, "file": out.name,
                            "url": self._url(e.name),
                            "page": f"{self.site().url}/{self.site().page}",
                            "text_layer": False},
            "files": [{"file": out.name, "size": size, "sha1": _sha1(out),
                       "source_url": self._url(e.name)}]})

    def search(self, q: str, *, limit: int = 30) -> list[Any]:
        """🔴 Відмова, а не порожній список: пошуку за текстом тут немає."""
        raise SourceError(
            "перелік описів — `nysh browse cdial-opysy [<фонд>]`; пошуку за текстом "
            "джерело не має, тож нуль звідси нічого б не означав")


def _is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def _sha1(path: Path) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
