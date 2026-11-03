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
    # Лапки будь-які: таблиця ДАЛуО пише `href='…'`.
    for m in re.finditer(r"""<a\b[^>]*href=(?:"([^"#]+)"|'([^'#]+)')[^>]*>(.*?)</a>""",
                         fragment, re.S | re.I):
        # 🔴 Невидимі знаки напрямку (`‎`) і пробіли в кінці адреси — з
        # копіювання в редакторі сайту; з ними сервер відповідає 404 (ДАХеО р-1887).
        href = _INVISIBLE.sub("", _html.unescape(m.group(1) or m.group(2))).strip()
        # 🔴 Шматок JavaScript у розмітці (`href='" + href + "'`, ДАОО): у справжній
        # адресі в одинарних лапках подвійної лапки не буває. Узятий за посилання,
        # він ставав «підсторінкою» фонду й заступав саму сторінку: каталог ДАОО
        # 03.11.2026 вийшов лише з ф.37 замість п'яти фондів.
        if m.group(2) is not None and '"' in href:
            continue
        if href:
            out.append((urljoin(base, href), text(m.group(3))))
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
    # Рядок без відкривного `<tr>` (ДАМО ф.218: `<tbody>` одразу з `<td>`)
    # губився — дописуємо пропущений тег.
    html_text = re.sub(r"(<tbody\b[^>]*>|</tr>)(\s*)(?=<t[dh]\b)", r"\1\2<tr>",
                       html_text, flags=re.I)
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
        case = next(((u, t) for u, t in ls if re.search(r"/[a-z]?\d{3,5}-[\w]+-[\w]+/?$", u, re.I)), None)
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


_PART = re.compile(r"[,;\s]*\(?\s*(?:ч\.|част\.|частина)\s*(\d+|[IVX]+)\s*\)?\s*$", re.I)


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


# ── ДАЛуО: «Е-архів» (ф.Р-303, ZIP) і страховий фонд (`/fonds/`, PDF) ─────────

DALUO_PUB = "/pages/fonds-publications.html"
DALUO_SFD = "/fonds/"
_DALUO_ZIP = re.compile(r"/P-(\d+)_Op(\d+[а-яa-z]?)_C-(\d+[а-яa-z]?)\.zip$", re.I)


def daluo_fond(raw: str) -> str:
    """«Ф-54» → «54» (дореволюційний), «Р-303» / «P-303» → «Р-303»."""
    v = re.sub(r"\s+", "", raw).replace("‑", "-")
    m = re.fullmatch(r"([ФфРрPpПп])?-?(\d+[а-яa-z]?)", v)
    if not m:
        return norm_num(v)
    letter = (m.group(1) or "").upper()
    if letter in ("", "Ф"):
        return norm_num(m.group(2))
    return f"{'П' if letter == 'П' else 'Р'}-{norm_num(m.group(2))}"


def parse_daluo_pub(base: str, page: str) -> list[CaseEntry]:
    """Вкладка «Е-архів»: книги РАЦС ф.Р-303, ZIP на справу.

    Шифра — з імені файла (`P-303_Op3_C-6.zip`): у тексті поруч лише «справа № 6»,
    а фонд і опис — у заголовку блока. Назва справи — заголовок опису (відділ РАЦС
    і роки), бо окремої назви сайт не дає.
    ⚠ Метрики й сповідні в кінці вкладки підписано лише фондом, без опису й справи:
    шифри немає, тож у каталог вони не йдуть.
    """
    a = page.find('id="tab60"')
    if a < 0:
        return []
    b = page.find('id="tab', a + 10)
    seg = page[a: b if b > 0 else len(page)]
    out: list[CaseEntry] = []
    for blk in re.split(r"(?=Опис\s*№)", seg)[1:]:
        head = re.sub(r"^Опис\s*№\s*\S+\s*", "", text(blk.split("<a", 1)[0]))
        head = re.sub(r"\s*справа\s*№.*$", "", head).strip(" ,.")
        head = re.sub(r"^справ\s+постійного\s+зберігання[,\s]*", "", head, flags=re.I)
        for u, _t in links(base, blk):
            m = _DALUO_ZIP.search(u)
            if not m:
                continue
            out.append(CaseEntry(fond=f"Р-{m.group(1)}", opys=norm_num(m.group(2)),
                                 sprava=norm_num(m.group(3)), title=head,
                                 years=years_of(head), page=base,
                                 files=[CaseFile(url=u, kind="zip")]))
    return out


def parse_daluo_sfd(base: str, page: str) -> list[CaseEntry]:
    """Таблиця страхового фонду: фонд · опис · справа · склад · дати · аркуші · PDF."""
    out: list[CaseEntry] = []
    for cells in rows(page):
        if len(cells) < 8:
            continue
        fond, opys, spr = (text(c) for c in cells[:3])
        if not (re.search(r"\d", fond) and re.fullmatch(r"\d+[а-яa-z]?", opys)
                and re.fullmatch(r"\d+[а-яa-z]?", spr)):
            continue
        pdf = [u for u, _ in links(base, cells[-1]) if _kind(u) == "pdf"]
        if not pdf:
            continue
        title = text(cells[3])
        out.append(CaseEntry(fond=daluo_fond(fond), opys=norm_num(opys), sprava=norm_num(spr),
                             title=title, years=years_of(" ".join(text(c) for c in cells[4:6])),
                             page=base, files=[CaseFile(url=pdf[0], kind="pdf")]))
    return out


def crawl_daluo(get: GetPage, site_url: str, stats: CrawlStats,
                tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    for i, (rel, parse) in enumerate(((DALUO_PUB, parse_daluo_pub),
                                      (DALUO_SFD, parse_daluo_sfd)), 1):
        pb, pt = get(root + rel)
        stats.pages += 1
        got = parse(pb, pt)
        if not got:
            stats.empty_pages.append(root + rel)
        yield from got
        if tick:
            tick(i, 2, rel)


# ── ДАРО: «Оцифровані справи» — таблиця «номер справи · заголовок · PDF» ─────

#: Сторінка опису на сайті (`period`, `fund`, `annotation`) → (фонд, опис).
#: 🔴 Шифри на сторінці НЕМАЄ — ні фонду, ні опису, лише номер справи. Відповідність
#: звірено 03.11.2026 з розділом «Оцифровані описи» (`/ocifrovani-opisi/5`) за
#: кількістю одиниць і роками опису: 6→оп.4 (825, 1842–1925), 10→оп.5 (28,
#: 1873–1925), 11→оп.6 (701, 1870–1931), 12→оп.15 (131, 1859–1944; оп.10 має ті
#: самі 131, але 1883–1944), 14→оп.7 (220, 1882–1933; дайджест Укрдержархіву
#: жовтня 2026 — р-740 оп.7 спр.11–40). 9→оп.2: роки 1840–1914 збігаються, на
#: сайті 785 од. проти 786 в описі, але номери справ ідуть до 786.
#: ⚠ `annotation=13` (метрики 1939–1948) свідомо поза переліком: «277 од. зб.»
#: проти 270 в оп.16, а номери справ ідуть до 282 — шифра не доведена. Невідомий
#: опис не вгадується: краще без справи, ніж справа під чужою шифрою.
DARO_OPYSY: dict[tuple[int, int, int], tuple[str, str]] = {
    (5, 5, 6): ("Р-740", "4"), (5, 5, 9): ("Р-740", "2"), (5, 5, 10): ("Р-740", "5"),
    (5, 5, 11): ("Р-740", "6"), (5, 5, 12): ("Р-740", "15"), (5, 5, 14): ("Р-740", "7"),
}


def parse_daro_opys(base: str, page: str, fond: str, opys: str) -> list[CaseEntry]:
    out: list[CaseEntry] = []
    for cells in rows(page):
        if len(cells) < 2:
            continue
        num = text(cells[0])
        if not re.fullmatch(r"\d+[а-яa-z]?", num):
            continue
        pdf = [u for u, _ in links(base, "".join(cells[1:])) if _kind(u) == "pdf"]
        if not pdf:
            continue
        title = text(cells[1])
        out.append(CaseEntry(fond=fond, opys=opys, sprava=norm_num(num), title=title,
                             years=years_of(title), page=base,
                             files=[CaseFile(url=pdf[0], kind="pdf")]))
    return merge_parts(out)


def crawl_daro(get: GetPage, site_url: str, stats: CrawlStats,
               tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    for i, ((p, f, a), (fond, opys)) in enumerate(DARO_OPYSY.items(), 1):
        url = f"{root}/ocifrovani-sprav?period={p}&&fund={f}&&annotation={a}"
        pb, pt = get(url)
        stats.pages += 1
        got = parse_daro_opys(pb, pt, fond, opys)
        if not got:
            stats.empty_pages.append(url)
        yield from got
        if tick:
            tick(i, len(DARO_OPYSY), f"ф.{fond} оп.{opys}")


# ── ДАСО: «Документи on-line» — «Фонд … Опис … Справа 1, 2, 3» з PDF ─────────

#: Сторінки розділів зі справами. `metrika1.php` (метрики) — поза ними: книги там
#: підписано плівкою FamilySearch і справою, без фонду й опису, шифри немає.
#: `dracs3.php` дає лише скани описів.
_DASO_PAGE = re.compile(r"/(?:r\d+p\d+|r5[a-z]+\d?)\.php$")
_DASO_TOKEN = re.compile(
    r"Фонд\s*[-–]?\s*(?P<f>(?:[РрPpПпRr]\s*[-–]?\s*)?\d+[а-яa-z]?)\b"
    r"|Опис\s*№?\s*(?P<o>\d+[а-яa-z]?)\b"
    r"|⟦(?P<l>\d+)⟧", re.I)   # «Опис 1Л» — літера велика
#: Кнопка справи: «Справа 1», «2», «10-1» / «17-II» (справа частинами), «619 Назва».
_DASO_CASE = re.compile(r"(?:Справа\s*№?\s*)?(?P<n>\d+[а-яa-z]?)"
                        r"(?:\s*[-_]\s*(?P<p>\d+|[IVX]+)\b|\s*[(,]?\s*ч\.?\s*(?P<c>\d+)\)?)?"
                        r"(?:\s+(?P<rest>\D.*))?", re.I)


def daso_fond(raw: str) -> str:
    """«Р 1655», «P-7720» (латиницею) → «Р-1655»; «П-4459» → «П-4459»; «442» → «442»."""
    v = re.sub(r"[\s–-]+", "", raw)
    m = re.fullmatch(r"([РрPpПпRr]?)(\d+[а-яa-z]?)", v)
    if not m:
        return norm_num(v)
    letter = m.group(1)
    if not letter:
        return norm_num(m.group(2))
    return f"{'П' if letter in 'Пп' else 'Р'}-{norm_num(m.group(2))}"


def parse_daso_page(base: str, page: str) -> list[CaseEntry]:
    """Обійти текст сторінки: поточні фонд і опис, далі кожна кнопка-PDF — справа.

    Назва справи — опис складу опису (текст між «Опис N» і першою кнопкою): назв
    окремих справ сайт не дає.
    """
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S | re.I)
    found: list[tuple[str, str]] = []

    def mark(m: re.Match[str]) -> str:
        # 🔴 Скан опису (`storage/opus/`) — не справа, але напис на ньому («Опис 1Л»)
        # і є номером опису: вирізаний разом із посиланням, він губився, і справи
        # опису лишались без шифри (ф.721, ф.814).
        if "/storage/opus/" in m.group(0):
            return " " + m.group(1) + " "
        found.append((m.group(0), ""))
        return f" ⟦{len(found) - 1}⟧ "

    body = re.sub(r"""<a\b[^>]*href=["'][^"']+\.(?:pdf|djvu)["'][^>]*>(.*?)</a>""", mark,
                  body, flags=re.S | re.I)
    files = [links(base, a)[0] for a, _ in found]
    flat = text(body)
    fond = opys = desc = ""
    desc_from = -1
    out: list[CaseEntry] = []
    for m in _DASO_TOKEN.finditer(flat):
        if m.group("f"):
            fond, opys, desc, desc_from = daso_fond(m.group("f")), "", "", -1
        elif m.group("o"):
            opys, desc, desc_from = norm_num(m.group("o")), "", m.end()
        else:
            if desc_from >= 0:
                desc = re.sub(r"⟦\d+⟧", "", flat[desc_from:m.start()]).strip(" .,-–")
                desc_from = -1
            url, label = files[int(m.group("l"))]
            if not (fond and opys):
                continue
            c = _DASO_CASE.fullmatch(label.strip())
            if not c:
                continue
            part = c.group("p") or c.group("c")
            title = (c.group("rest") or desc).strip() + (f", ч.{part}" if part else "")
            out.append(CaseEntry(fond=fond, opys=opys, sprava=norm_num(c.group("n")),
                                 title=title, years=years_of(c.group("rest") or desc),
                                 page=base, files=[CaseFile(url=url, kind=_kind(url))]))
    return merge_parts(out)


def crawl_daso(get: GetPage, site_url: str, stats: CrawlStats,
               tick: Tick | None = None) -> Iterator[CaseEntry]:
    root = site_url.rstrip("/")
    rb, rt = get(root + "/")
    stats.pages += 1
    # 🔴 Сирі `href`, а не `links()`: у меню частина `<a>` не закрита, і через
    # `links()` обхід бачив 24 розділи з 49 — половину справ сайту.
    hrefs = re.findall(r"""href=["']([^"'#]+\.php)["']""", rt, re.I)
    pages = list(dict.fromkeys(u for u in (urljoin(rb, h) for h in hrefs) if _DASO_PAGE.search(u)))
    seen: set[str] = set()
    for i, p in enumerate(pages, 1):
        pb, pt = get(p)
        stats.pages += 1
        got = parse_daso_page(pb, pt)
        if not got:
            stats.empty_pages.append(p)
        # Та сама справа тими самими файлами на двох сторінках розділів (ф.992) —
        # одна справа, а не дві копії.
        for e in got:
            urls = {f.url for f in e.files}
            if urls & seen:
                continue
            seen |= urls
            yield e
        if tick:
            tick(i, len(pages), p.rsplit("/", 1)[-1])


CRAWLERS: dict[str, Callable[..., Iterator[CaseEntry]]] = {
    "daoo": crawl_daoo,
    "dadno": crawl_dadno,
    "daho": crawl_daho,
    "damo": crawl_damo,
    "daheo": crawl_daheo,
    "daluo": crawl_daluo,
    "daro": crawl_daro,
    "daso": crawl_daso,
}
