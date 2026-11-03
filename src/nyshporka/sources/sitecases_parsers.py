"""🗂 Розбір сторінок «оцифровані справи» на сайтах обласних архівів.

Кожен архів викладає скани по-своєму, тож тут по обходу на сайт, а
завантаження спільне (`sitecases.py`). Обхід віддає `CaseEntry` — шифру,
назву, роки й адреси файлів справи — і нічого не качає.

| парсер | сайт | що лежить за посиланням |
|---|---|---|
| `daoo` | archive.od.gov.ua, проєкт «Метрика» | PDF справи на самому сайті |
| `dadno` | dp.archives.gov.ua, «Метрика» | PDF частинами («Арк. 1-33») на Google Drive |
| `daho` | archives.kh.gov.ua, сторінки з таблицями | ZIP із JPG (частинами) або DjVu на daho.archives.gov.ua |
| `damo` | archive.mk.ua, «Цифровий архів» | ZIP із JPG на справу |
| `daheo` | kherson.archives.gov.ua, «Оцифровані документи» | PDF на Google Drive, посилання в тексті сторінки |

🔴 Розбір, що не знайшов на сторінці жодної справи, — не «справ немає». Обхід
рахує такі сторінки окремо (`empty_pages`), і каталог без них не видається за
повний: розмітку могли змінити.

🔴 Шифра береться з колонок таблиці чи з тексту поруч із посиланням, а не з
імені файла. Ім'я файла на ДАХО (`40_105_1a.zip`) пишеться латиницею, а в
таблиці — «1а»; на ДАДнО ім'я файла не несе шифри взагалі.
"""
from __future__ import annotations

import html as _html
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urljoin

#: Що лежить за адресою файла справи.
#:     pdf    — PDF напряму з сайту
#:     drive  — файл на Google Drive (`file/d/<id>`)
#:     zip    — ZIP із кадрами (JPG), читається поштучно через `Range`
#:     djvu   — DjVu одним файлом
#:     gallery — сторінка справи з галереєю JPG (кадри — посилання на сторінці)
KINDS = ("pdf", "drive", "zip", "djvu", "gallery")

#: Повнорозмірний кадр галереї NextGEN (ДАМО): посилання мініатюри веде на нього.
GALLERY_IMG = re.compile(r'<a\b[^>]*href="([^"]+/wp-content/gallery/[^"]+\.(?:jpe?g|png|tiff?))"',
                         re.I)


def gallery_images(base: str, page: str) -> list[str]:
    """Адреси кадрів галереї зі сторінки справи — без повторів, у порядку імен."""
    urls = {urljoin(base, _html.unescape(u)) for u in GALLERY_IMG.findall(page)}
    return sorted(urls, key=lambda u: unquote(u).rsplit("/", 1)[-1])


@dataclass(frozen=True)
class CaseFile:
    url: str
    kind: str
    label: str = ""          # «Арк. 1-33», «частина 2»


@dataclass
class CaseEntry:
    """Справа так, як її показує сайт."""

    fond: str
    opys: str
    sprava: str
    title: str = ""
    years: str = ""
    page: str = ""                     # сторінка, де справу знайдено
    files: list[CaseFile] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"fond": self.fond, "opys": self.opys, "sprava": self.sprava,
                "title": self.title, "years": self.years, "page": self.page,
                "files": [{"url": f.url, "kind": f.kind, "label": f.label}
                          for f in self.files]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CaseEntry:
        return cls(fond=str(d.get("fond") or ""), opys=str(d.get("opys") or ""),
                   sprava=str(d.get("sprava") or ""), title=str(d.get("title") or ""),
                   years=str(d.get("years") or ""), page=str(d.get("page") or ""),
                   files=[CaseFile(url=str(f["url"]), kind=str(f["kind"]),
                                   label=str(f.get("label") or ""))
                          for f in d.get("files") or []])


#: Завантажувач сторінки: адреса → (кінцева адреса після переадресацій, HTML).
GetPage = Callable[[str], tuple[str, str]]
#: Звіт про хід обходу: (пройдено сторінок, всього відомо, примітка).
Tick = Callable[[int, int, str], None]


@dataclass
class CrawlStats:
    pages: int = 0
    empty_pages: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # посилання, яких розбір не розуміє


# ── спільне ──────────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_DRIVE_FILE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?[^\"']*?id=)([\w-]{20,})")
_YEARS = re.compile(r"(1[5-9]\d\d)(?:\s*[-–—]\s*(1[5-9]\d\d|\d\d))?")


def text(fragment: str) -> str:
    """HTML-уривок → рядок тексту без тегів і зайвих пробілів."""
    return _WS.sub(" ", _html.unescape(_TAG.sub(" ", fragment or "")).replace("\xa0", " ")).strip()


def links(base: str, fragment: str) -> list[tuple[str, str]]:
    """(абсолютна адреса, текст) усіх посилань уривка, у порядку появи."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', fragment, re.S | re.I):
        # 🔴 Невидимі знаки напрямку (`‎`) і пробіли в кінці адреси — з
        # копіювання в редакторі сайту; з ними сервер відповідає 404 (ДАХеО р-1887).
        href = _INVISIBLE.sub("", _html.unescape(m.group(1))).strip()
        if href:
            out.append((urljoin(base, href), text(m.group(2))))
    return out


_INVISIBLE = re.compile("[​-‏‪-‮⁠﻿]")


def drive_id(url: str) -> str:
    m = _DRIVE_FILE.search(url)
    return m.group(1) if m else ""


def years_of(s: str) -> str:
    """Роки з підпису: «1908, 1909, 1910 рр.» → «1908–1910», «1774-1812» → «1774–1812»."""
    found: list[int] = []
    for m in _YEARS.finditer(s or ""):
        a = int(m.group(1))
        found.append(a)
        if m.group(2):
            b = m.group(2)
            found.append(int(b) if len(b) == 4 else int(str(a)[:2] + b))
    if not found:
        return ""
    lo, hi = min(found), max(found)
    return str(lo) if lo == hi else f"{lo}–{hi}"


#: Латинські двійники в номерах («1a» на сайті, «1а» в описі).
_LAT2CYR = str.maketrans("abceiABCEI", "абсеіАБСЕІ")


def norm_num(s: str) -> str:
    """Номер фонду, опису чи справи як його пише людина: «0029» → «29», «1a» → «1а»."""
    t = text(s).strip(" .,:;№").replace(" ", "")
    t = t.translate(_LAT2CYR)
    m = re.fullmatch(r"0*(\d+)(.*)", t)
    return (m.group(1) + m.group(2).lower()) if m else t


def rows(html_text: str) -> list[list[str]]:
    """Таблиці сторінки → рядки → сирий HTML клітинок."""
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        if cells:
            out.append(cells)
    return out


def _kind(url: str) -> str:
    low = unquote(url).lower().split("?")[0]
    if drive_id(url):
        return "drive"
    for k in ("pdf", "zip", "djvu"):
        if low.endswith("." + k):
            return k
    return ""


# ── ДАОО: проєкт «Метрика» ───────────────────────────────────────────────────

DAOO_INDEX = "/main/elektronnyj-arhiv-fondy-opysy-dokumenty/proekt-metpyka-metrychni-knygy-on-lajn/"
_DAOO_ITEM = re.compile(
    r"Ф\.\s*(?P<fond>[\w-]+)\.?\s*[–—-]\s*Оп\.\s*(?P<opys>[\wа-яґіїє-]+)\.?\s*[–—-]\s*"
    r"Спр\.\s*(?P<spr>[\wа-яґіїє/-]+)\.?(?P<rest>.*?)(?=Ф\.\s*[\w-]+\.?\s*[–—-]\s*Оп\.|$)",
    re.S | re.I)


def parse_daoo_opys(base: str, page: str) -> list[CaseEntry]:
    # 🔴 Теги всередині тексту прибираються БЕЗ пробілу: номер справи буває
    # розірваний виділенням («Спр. 20<strong>3</strong>»), і з пробілом на місці
    # тегу він читався як справа 20 — чужа, вже наявна шифра (191 дубль на ф.37).
    # Блокові теги (абзац, рядок) лишають пробіл, посилання лишаються цілими.
    body = re.sub(r"</?(?:p|br|div|li|tr|td)\b[^>]*>", " ", page, flags=re.I)
    body = re.sub(r"<(?!/?a\b)[^>]+>", "", body)
    body = _html.unescape(body).replace("\xa0", " ")
    out = []
    for m in _DAOO_ITEM.finditer(body):
        files = [CaseFile(url=u, kind=_kind(u), label=t)
                 for u, t in links(base, m.group("rest")) if _kind(u)]
        if not files:
            continue
        title = text(re.sub(r"<a\b.*?</a>", " ", m.group("rest"), flags=re.S))
        title = re.sub(r"\[\s*\]", " ", title)
        title = " ".join(title.split()).strip(" –—-.")
        out.append(CaseEntry(fond=norm_num(m.group("fond")), opys=norm_num(m.group("opys")),
                             sprava=norm_num(m.group("spr")), title=title,
                             years=years_of(title), page=base, files=files))
    return out


def crawl_daoo(get: GetPage, site_url: str, stats: CrawlStats,
               tick: Tick | None = None) -> Iterator[CaseEntry]:
    base, index = get(site_url.rstrip("/") + DAOO_INDEX)
    # 🔴 Лише адреси ПІД самим індексом. Сторінка дає кожен фонд двічі, і
    # другий варіант (`/main/arhiv/…`) — давня адреса, що відповідає 404.
    under = base.rstrip("/") + "/"
    fonds = list(dict.fromkeys(u for u, _ in links(base, index)
                               if u.startswith(under)
                               and re.search(r"/metryka-fond-[\w-]+/?$", u)))
    pages: list[str] = []
    for f in fonds:
        fb, ft = get(f)
        stats.pages += 1
        subs = list(dict.fromkeys(u for u, _ in links(fb, ft)
                                  if u.startswith(f.rstrip("/") + "/") and u.rstrip("/") != f.rstrip("/")))
        pages += subs or [f]
        if tick:
            tick(stats.pages, len(fonds), f"фонд {f.rstrip('/').rsplit('-', 1)[-1]}")
    for p in dict.fromkeys(pages):
        pb, pt = get(p)
        stats.pages += 1
        got = parse_daoo_opys(pb, pt)
        if not got:
            stats.empty_pages.append(p)
        yield from got
        if tick:
            tick(stats.pages, len(fonds) + len(pages), p.rstrip("/").rsplit("/", 1)[-1])


# ── ДАДнО: «Метрика», PDF частинами на Google Drive ──────────────────────────

DADNO_INDEX = "/index.php/digitized-documents/metryka"
_DADNO_PAGE = re.compile(r"/index\.php/system-box/\d+-metryka/\d+[\w-]*/?$")
#: Запобіжник від зациклення: сторінок метрик на сайті — кілька сотень.
DADNO_MAX_PAGES = 3000


def parse_dadno_page(base: str, page: str) -> list[CaseEntry]:
    out = []
    for cells in rows(page):
        nums = [text(c) for c in cells]
        # Колонки: [порожня], фонд, опис, справа, назва з роками й посиланнями.
        idx = next((i for i in range(len(nums) - 3)
                    if re.fullmatch(r"[\w-]{1,8}", nums[i] or "")
                    and re.fullmatch(r"[\w-]{1,6}", nums[i + 1] or "")
                    and re.fullmatch(r"[\w/-]{1,8}", nums[i + 2] or "")
                    and re.search(r"\d", nums[i] + nums[i + 1] + nums[i + 2])), None)
        if idx is None:
            continue
        rest = "".join(cells[idx + 3:])
        files = [CaseFile(url=u, kind=_kind(u), label=t) for u, t in links(base, rest) if _kind(u)]
        if not files:
            continue
        strongs = [text(s) for s in re.findall(r"<strong>(.*?)</strong>", rest, re.S)]
        title = strongs[0] if strongs else text(re.sub(r"<a\b.*?</a>", " ", rest, flags=re.S))
        yrs = years_of(" ".join(strongs[1:]) or text(rest))
        out.append(CaseEntry(fond=norm_num(nums[idx]), opys=norm_num(nums[idx + 1]),
                             sprava=norm_num(nums[idx + 2]), title=title.strip(" ."),
                             years=yrs, page=base, files=files))
    return out


def crawl_dadno(get: GetPage, site_url: str, stats: CrawlStats,
                tick: Tick | None = None) -> Iterator[CaseEntry]:
    # Індекс дворівневий: сторінка розділу («Метричні книги Катеринославського
    # повіту») посилається на сторінки церков, і лише на них таблиці. Тому обхід
    # іде за посиланнями `system-box/…-metryka/<id>` усіх рівнів, а не за списком
    # першої сторінки — той показує близько десятка з сотень.
    root = site_url.rstrip("/")
    queue = [root + DADNO_INDEX]
    seen: set[str] = set()
    while queue and len(seen) < DADNO_MAX_PAGES:
        url = queue.pop(0)
        key = re.sub(r"^https?://", "", url.split("?")[0].split("#")[0]).rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        pb, pt = get(url)
        stats.pages += 1
        got = parse_dadno_page(pb, pt)
        nxt = [u for u, _ in links(pb, pt) if _DADNO_PAGE.search(u)]
        queue += [u for u in dict.fromkeys(nxt)
                  if re.sub(r"^https?://", "", u.split("?")[0]).rstrip("/") not in seen]
        if not got and not nxt and url != root + DADNO_INDEX:
            stats.empty_pages.append(url)
        yield from got
        if tick:
            tick(len(seen), len(seen) + len(queue), url.rsplit("/", 1)[-1][:60])


# ── ДАХО: таблиці з ZIP/DjVu на daho.archives.gov.ua ─────────────────────────

#: Сторінки з таблицями оцифрованих справ (метрики ф.40 оп.105 тощо).
DAHO_PAGES = ("/?page_id=25402",)


def parse_daho_page(base: str, page: str) -> list[CaseEntry]:
    out: list[CaseEntry] = []
    for cells in rows(page):
        if len(cells) < 4:
            continue
        nums = [text(c) for c in cells[:3]]
        files = [CaseFile(url=u, kind=_kind(u), label=t)
                 for u, t in links(base, "".join(cells[3:])) if _kind(u)]
        if not files:
            continue
        if not all(nums) or not re.search(r"\d", nums[0]):
            # Рядок-продовження: частини тієї самої справи без шифри.
            if out:
                out[-1].files += files
            continue
        # Назва — текст клітинки без підписів посилань. У справ частинами
        # посилання підписані «Частина 1 – Zip – 0,98 Гб», а назва стоїть
        # окремо (або в посиланні, якщо частина одна).
        title = text(re.sub(r"<a\b.*?</a>", " ", cells[3], flags=re.S | re.I)).strip(" –-")
        if not title and not re.match(r"(частина|zip|djvu)\b", files[0].label, re.I):
            title = files[0].label
        for f in files:
            m = re.search(r"частина\s*(\d+)", unquote(f.url), re.I)
            if m and not f.label.lower().startswith("частина"):
                files[files.index(f)] = CaseFile(url=f.url, kind=f.kind, label=f"частина {m.group(1)}")
        out.append(CaseEntry(fond=norm_num(nums[0]), opys=norm_num(nums[1]),
                             sprava=norm_num(nums[2]), title=title, years=years_of(title),
                             page=base, files=files))
    return out


def crawl_daho(get: GetPage, site_url: str, stats: CrawlStats,
               tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    for i, rel in enumerate(DAHO_PAGES, 1):
        pb, pt = get(root + rel)
        stats.pages += 1
        got = parse_daho_page(pb, pt)
        if not got:
            stats.empty_pages.append(root + rel)
        yield from got
        if tick:
            tick(i, len(DAHO_PAGES), rel)


# ── ДАМО: «Цифровий архів», ZIP на справу ────────────────────────────────────

DAMO_SECTIONS = ("/digital-archive/before-1917/", "/digital-archive/after-1917/",
                 "/digital-archive/party-archive/")
_DAMO_FOND = re.compile(r"/digital-archive/(?P<slug>[a-zа-я]?\d{3,5}[a-zа-я]?)/?$", re.I)
_DAMO_PREFIX = {"f": "", "r": "Р-", "p": "П-", "n": "Н-"}


def damo_fond(slug: str) -> str:
    """`f0335` → «335», `r0510` → «Р-510», `n1016` → «Н-1016»."""
    m = re.fullmatch(r"([a-z]?)0*(\d+)([a-z]?)", slug.lower())
    if not m:
        return slug
    return _DAMO_PREFIX.get(m.group(1), m.group(1).upper() + "-") + m.group(2) + m.group(3)


def parse_damo_opys(base: str, page: str, fond: str) -> list[CaseEntry]:
    out = []
    for cells in rows(page):
        ls = links(base, "".join(cells))
        case = next(((u, t) for u, t in ls if re.search(r"/\d{3,5}-[\w]+-[\w]+/?$", u)), None)
        zips = [CaseFile(url=u, kind="zip") for u, _ in ls if _kind(u) == "zip"]
        if case is None:
            continue
        if not zips:
            # Частина описів (ф.35–39 тощо) без колонки ZIP: кадри лише
            # галереєю JPG на сторінці справи.
            zips = [CaseFile(url=case[0], kind="gallery")]
        slug = case[0].rstrip("/").rsplit("/", 1)[-1]
        parts = slug.split("-")
        if len(parts) < 3:
            continue
        out.append(CaseEntry(fond=fond, opys=norm_num(parts[1]), sprava=norm_num("-".join(parts[2:])),
                             title=case[1], years=years_of(case[1]), page=case[0], files=zips))
    return out


def crawl_damo(get: GetPage, site_url: str, stats: CrawlStats,
               tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    fonds: list[str] = []
    for sec in DAMO_SECTIONS:
        sb, st = get(root + sec)
        stats.pages += 1
        fonds += [u for u, _ in links(sb, st) if _DAMO_FOND.search(u)]
    fonds = list(dict.fromkeys(fonds))
    for i, f in enumerate(fonds, 1):
        slug = _DAMO_FOND.search(f).group("slug")  # type: ignore[union-attr]
        fond = damo_fond(slug)
        fb, ft = get(f)
        stats.pages += 1
        opysy = list(dict.fromkeys(u for u, _ in links(fb, ft)
                                   if re.search(re.escape(f.rstrip("/")) + r"/[\w-]+/?$", u)))
        if not opysy:
            got = parse_damo_opys(fb, ft, fond)
            if not got:
                stats.empty_pages.append(f)
            yield from got
        for o in opysy:
            ob, ot = get(o)
            stats.pages += 1
            got = parse_damo_opys(ob, ot, fond)
            if not got:
                stats.empty_pages.append(o)
            yield from got
        if tick:
            tick(i, len(fonds), f"ф.{fond}")


# ── ДАХеО: «Оцифровані документи», посилання на Drive у тексті ───────────────

DAHEO_INDEX = "/fondy-ta-dovidkovyj-aparat/oczyfrovani-dokumenty/"
_DAHEO_FOND = re.compile(r"Фонд\s*№?\s*(?P<f>[РрПпRrPp]?[-‑]?\s*\d+[\wа-я]*)", re.I)
_DAHEO_OPYS = re.compile(r"Опис\s*№?\s*(?P<o>[\wа-яґіїє-]+)", re.I)
_DAHEO_SPR = re.compile(r"Справ[аи]\s*№?\s*(?P<s>\d+[\wа-яґіїє/]*)", re.I)


def _crumbs(page: str) -> list[str]:
    seg = re.search(r'class="breadcrumbs.*?</div>', page, re.S)
    return [text(x) for x in re.findall(r'itemprop="name">(.*?)</span>|breadcrumbs__current">(.*?)</span>',
                                       seg.group(0) if seg else "", re.S) for x in x if x]


def _daheo_fond_label(s: str) -> str:
    v = re.sub(r"\s+", "", s).replace("‑", "-")
    m = re.fullmatch(r"([РрПпRrPp])-?(\d+[\wа-я]*)", v)
    if m:
        letter = {"r": "Р", "p": "П"}.get(m.group(1).lower(), m.group(1).upper())
        return f"{letter}-{m.group(2)}"
    return norm_num(v)


def parse_daheo_page(base: str, page: str) -> list[CaseEntry]:
    crumbs = _crumbs(page)
    fond = opys = ""
    for c in crumbs:
        mf = _DAHEO_FOND.search(c)
        if mf and not fond:
            fond = _daheo_fond_label(mf.group("f"))
        mo = _DAHEO_OPYS.search(c)
        if mo:
            opys = norm_num(mo.group("o"))
    m = re.search(r'<div class="entry[^"]*">(.*?)<div class="clear">', page, re.S)
    body = m.group(1) if m else page
    out: dict[str, CaseEntry] = {}
    for u, t in links(base, body):
        k = _kind(u)
        if not k:
            continue
        ms = _DAHEO_SPR.search(t)
        if not ms or not fond:
            continue
        spr = norm_num(ms.group("s"))
        e = out.get(spr)
        if e is None:
            e = out[spr] = CaseEntry(fond=fond, opys=opys, sprava=spr, title=t,
                                     years=years_of(t), page=base)
        e.files.append(CaseFile(url=u, kind=k, label=t))
    return list(out.values())


def crawl_daheo(get: GetPage, site_url: str, stats: CrawlStats,
                tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    base, index = get(root + DAHEO_INDEX)
    stats.pages += 1
    fonds = list(dict.fromkeys(u for u, _ in links(base, index)
                               if "fond" in unquote(u).lower()
                               and u.rstrip("/") != base.rstrip("/")))
    seen: set[str] = set()
    for i, f in enumerate(fonds, 1):
        fb, ft = get(f)
        stats.pages += 1
        got = parse_daheo_page(fb, ft)
        yield from got
        subs = list(dict.fromkeys(u for u, _ in links(fb, ft)
                                  if unquote(u).rstrip("/").startswith(unquote(fb).rstrip("/") + "/")))
        if not subs and not got:
            stats.empty_pages.append(f)
        for s in subs:
            if s in seen:
                continue
            seen.add(s)
            sb, st = get(s)
            stats.pages += 1
            sg = parse_daheo_page(sb, st)
            if not sg:
                stats.empty_pages.append(s)
            yield from sg
        if tick:
            tick(i, len(fonds), unquote(f).rstrip("/").rsplit("/", 1)[-1][:50])


_PART = re.compile(r"[,;\s]*\(?\s*(?:ч\.|част\.|частина)\s*(\d+)\s*\)?\s*$", re.I)


def merge_parts(entries: Iterator[CaseEntry] | list[CaseEntry]) -> list[CaseEntry]:
    """Записи однієї справи з тієї самої сторінки → одна справа з кількома файлами.

    ДАОО пише велику справу частинами окремими рядками («Спр. 150 ч.1» … «ч.11»),
    кожен зі своїм PDF. Без зведення це одинадцять «справ» з однаковою шифрою, і
    `nysh get` узяв би лише першу частину, звітуючи повну справу.
    🔴 Зводиться лише в межах сторінки: однакова шифра на різних сторінках —
    інша річ (різні описи з помилкою, «відновлена з фотокопій»), і склеїти їх
    означало б змішати дві справи в одній теці.
    """
    out: list[CaseEntry] = []
    index: dict[tuple[str, str, str, str], CaseEntry] = {}
    for e in entries:
        part = _PART.search(e.title)
        k = (e.fond, e.opys, e.sprava, e.page)
        head = index.get(k)
        if head is None:
            if part:
                e.files = [CaseFile(url=f.url, kind=f.kind, label=f"ч.{part.group(1)}")
                           for f in e.files]
                e.title = _PART.sub("", e.title).strip(" ,.–-")
            index[k] = e
            out.append(e)
            continue
        label = f"ч.{part.group(1)}" if part else ""
        head.files += [CaseFile(url=f.url, kind=f.kind, label=label or f.label) for f in e.files]
        if not head.title:
            head.title = _PART.sub("", e.title).strip(" ,.–-")
        if e.years and not head.years:
            head.years = e.years
    return out


CRAWLERS: dict[str, Callable[..., Iterator[CaseEntry]]] = {
    "daoo": crawl_daoo,
    "dadno": crawl_dadno,
    "daho": crawl_daho,
    "damo": crawl_damo,
    "daheo": crawl_daheo,
}
