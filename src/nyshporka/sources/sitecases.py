"""🗂 Оцифровані справи з власних сайтів обласних архівів.

Частина архівів викладає скани не в ARCHIUM, а на своєму сайті: таблицею зі
шифрами й посиланнями на PDF, ZIP чи Google Drive. Пошуку там немає, переліку
справ поза сторінками теж, і архівний дайджест щомісяця додає сотні нових
справ саме туди (ДАДнО ф.193, ДАОО ф.37, ДАХО ф.40, ДАХеО ф.259, ДАМО ф.335).

Джерело одне на всі такі сайти, а розбір сторінок — свій на кожен
(`sitecases_parsers.py`). Майданчик у паку: `sites: {cases: {url, parser}}`.

    nysh crawl site-daoo             # обійти сторінки сайту → каталог справ
    nysh find "Миколаївська" --source site-daoo
    nysh browse site-daoo 37         # описи фонду, далі справи
    nysh get site-daoo 37/3а/228     # файли справи в теку

🔴 Каталог — знімок сторінок на дату обходу. Нуль пошуку по ньому означає
«на сторінках сайту на цю дату такої справи не було», а не «справи не
оцифровано»: сайт міг викласти її пізніше чи на сторінці, якої розбір не знає
(їх обхід рахує окремо — `empty_pages`).

Як лягають файли:

| що на сайті | що в теці |
|---|---|
| PDF (напряму чи з Google Drive) | PDF як є; одиниця обліку — файл |
| DjVu | DjVu як є |
| ZIP із JPG | JPG поштучно, без самого ZIP: архів читається через `Range` за центральним каталогом, тож можна взяти й частину кадрів (`--frames`) |

🔴 ZIP на ДАХО — 600–900 МБ на частину справи, а частин буває до семи.
Поштучне читання не тягне архів на диск двічі (zip + розпаковані кадри) і не
лишає півгігабайтного `.part` після обриву: обірвано — догружаються лише
відсутні кадри.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Hits,
    Manifest,
    Node,
    SourceAbout,
    SourceError,
    SourceScope,
    crawl_complete,
    mark_crawl,
)
from nyshporka.sources.http import Fetcher, HttpError, offline
from nyshporka.sources.sitecases_parsers import (
    CRAWLERS,
    CaseEntry,
    CaseFile,
    CrawlStats,
    drive_id,
    gallery_images,
    merge_parts,
    norm_num,
)
from nyshporka.utils.atomic import atomic_write_bytes

if TYPE_CHECKING:
    from nyshporka.archives.pack import Site
    from nyshporka.sources.base import ProgressFn

#: Сайти державних архівів, не CDN: темп спільний на машину й помірний.
RATE_MAX = 4
RATE_WINDOW = 2.0
#: Google Drive віддає файли сам; темп окремий, щоб не ділити його з сайтом.
DRIVE_RATE_MAX = 4
DRIVE_RATE_WINDOW = 4.0
DRIVE_URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
#: Стеля на один файл (PDF частини справи на ДАДнО — до ~300 МБ).
FILE_MAX_BYTES = 4 << 30
#: Хвіст ZIP, у якому шукається кінцевий запис каталогу (EOCD + коментар).
ZIP_TAIL = 1 << 16
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
#: Типи файлів, що лягають у теку КАДРАМИ (решта — файлом).
FRAME_KINDS = frozenset({"zip", "gallery"})


# ── шифра ────────────────────────────────────────────────────────────────────

def key_of(e: CaseEntry) -> str:
    return f"{e.fond}/{e.opys}/{e.sprava}"


def _norm_part(s: str) -> str:
    return norm_num(s).casefold().replace("-", "").replace("р", "р")


def parse_key(ref: str) -> tuple[str, str, str]:
    """`37/3а/228`, «37-3а-228», «ф.37 оп.3а спр.228» → (фонд, опис, справа).

    Опис і справа можуть бути порожні — тоді це адреса фонду чи опису.
    """
    s = (ref or "").strip()
    s = re.sub(r"^(?:[А-ЯҐІЇЄA-Z]{2,7}\b[\s,:/-]*)?", "", s) if re.match(
        r"^[А-ЯҐІЇЄA-Z]{2,7}\s", s) else s
    m = re.match(r"^\s*(?:ф\.?|фонд)?\s*([РПНрпн]?-?\s*\d+[\wа-я]*)\s*"
                 r"(?:[/,\s-]+\s*(?:оп\.?|опис)?\s*([\wа-яґіїє]+))?\s*"
                 r"(?:[/,\s-]+\s*(?:спр\.?|справа)?\s*([\wа-яґіїє/]+))?\s*$", s, re.I)
    if not m:
        raise SourceError(f"незрозуміла адреса {ref!r} — очікується `<фонд>/<опис>/<справа>`, "
                          f"наприклад `37/3а/228`")
    fond = re.sub(r"\s+", "", m.group(1))
    lm = re.fullmatch(r"([РПНрпн])-?(\d+[\wа-я]*)", fond)
    fond = f"{lm.group(1).upper()}-{lm.group(2)}" if lm else norm_num(fond)
    return fond, norm_num(m.group(2) or ""), norm_num(m.group(3) or "")


def _eq(a: str, b: str) -> bool:
    return _norm_part(a) == _norm_part(b)


# ── віддалений ZIP ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ZipMember:
    name: str
    offset: int        # зсув локального заголовка
    csize: int
    usize: int
    method: int        # 0 — без стиснення, 8 — deflate


class RemoteZip:
    """ZIP на сервері, що вміє `Range`: каталог і окремі файли без завантаження цілого."""

    def __init__(self, get_range: Any, url: str) -> None:
        self._get = get_range       # (url, start, end) -> (status, bytes, total)
        self.url = url
        self.size = 0

    def members(self) -> list[ZipMember]:
        status, _head, total = self._get(self.url, 0, 0)
        if status != 206 or not total:
            raise _NoRange(self.url)
        self.size = total
        start = max(0, total - ZIP_TAIL)
        _, tail, _ = self._get(self.url, start, total - 1)
        i = tail.rfind(b"PK\x05\x06")
        if i < 0:
            raise SourceError(f"{unquote(self.url)}: кінця каталогу ZIP не знайдено — файл "
                              f"битий або не ZIP")
        count, cd_size, cd_off = struct.unpack("<HII", tail[i + 10:i + 20])
        if cd_off == 0xFFFFFFFF or count == 0xFFFF:
            raise _NoRange(self.url)     # ZIP64: поштучне читання не підтримано
        _, cd, _ = self._get(self.url, cd_off, cd_off + cd_size - 1)
        out: list[ZipMember] = []
        pos = 0
        while True:
            j = cd.find(b"PK\x01\x02", pos)
            if j < 0:
                break
            (method,) = struct.unpack("<H", cd[j + 10:j + 12])
            csize, usize = struct.unpack("<II", cd[j + 20:j + 28])
            nlen, elen, clen = struct.unpack("<HHH", cd[j + 28:j + 34])
            (off,) = struct.unpack("<I", cd[j + 42:j + 46])
            flags = struct.unpack("<H", cd[j + 8:j + 10])[0]
            raw = cd[j + 46:j + 46 + nlen]
            name = raw.decode("utf-8" if flags & 0x800 else "cp866", "replace")
            out.append(ZipMember(name=name, offset=off, csize=csize, usize=usize, method=method))
            pos = j + 46 + nlen + elen + clen
        if len(out) != count:
            raise SourceError(f"{unquote(self.url)}: каталог ZIP обіцяє {count} файлів, "
                              f"прочитано {len(out)} — архів битий")
        return out

    def read(self, m: ZipMember) -> bytes:
        # Локальний заголовок 30 байт + ім'я + extra; довжину extra знає лише він,
        # тож беремо із запасом і зрізаємо за його ж полями.
        want = 30 + len(m.name.encode("utf-8")) + 1024 + m.csize
        _, blob, _ = self._get(self.url, m.offset, min(self.size - 1, m.offset + want - 1))
        if blob[:4] != b"PK\x03\x04":
            raise SourceError(f"{m.name}: локального заголовка ZIP на зсуві {m.offset} немає")
        nlen, elen = struct.unpack("<HH", blob[26:30])
        data = blob[30 + nlen + elen:30 + nlen + elen + m.csize]
        if len(data) < m.csize:
            _, data, _ = self._get(self.url, m.offset + 30 + nlen + elen,
                                   m.offset + 30 + nlen + elen + m.csize - 1)
        out: bytes
        if m.method == 0:
            out = bytes(data)
        elif m.method == 8:
            out = bytes(zlib.decompressobj(-15).decompress(data))
        else:
            raise SourceError(f"{m.name}: метод стиснення {m.method} не підтримано")
        if len(out) != m.usize:
            raise SourceError(f"{m.name}: розпаковано {len(out)} байт замість {m.usize}")
        return out


class _NoRange(Exception):
    """Сервер не віддає шматків файла — ZIP доведеться брати цілим."""


def frames_of(members: list[ZipMember]) -> list[ZipMember]:
    """Кадри справи в ZIP: зображення, у порядку імен (каталог ZIP порядку не обіцяє)."""
    imgs = [m for m in members if m.name.lower().endswith(IMAGE_EXT) and not m.name.endswith("/")]
    return sorted(imgs, key=lambda m: m.name)


# ── джерело ──────────────────────────────────────────────────────────────────

class SiteCasesSource:
    """Справи зі сторінок «оцифровані документи» сайту архіву."""

    caps = frozenset({"search", "browse", "manifest", "fetch", "address"})
    about = SourceAbout(
        answers="чи виклав архів справу на власному сайті (не в ARCHIUM) і де взяти її "
                "файли за шифрою",
        gives="каталог справ зі сторінок сайту: шифра, назва, роки, адреси файлів; "
              "PDF, DjVu чи кадри з ZIP у теку справи з паспортом",
        not_gives="справ, яких на сторінках сайту немає; тексту — скани без текстового "
                  "шару читаються окремо",
        where_class="переглядач архіву",
        scope=SourceScope(note="лише сторінки «оцифровані справи» сайтів, для яких є "
                               "розбір: ДАОО, ДАДнО, ДАХО, ДАМО, ДАХеО"),
        match_on=("title",), match_how="normalized",
        zero_means="на сторінках сайту на дату обходу справи з таким словом у назві не "
                   "було — не «не оцифровано»",
        pitfalls=("каталог — знімок на дату обходу; нові справи з'являються щомісяця, "
                  "`nysh crawl <id>` перед висновком",
                  "назва справи на сайті буває обрізана або без років (ДАОО дає лише "
                  "шифру), тож пошук за назвою там слабкий — шукати шифрою",
                  "у ДАХеО одна справа буває кількома файлами (оригінал і «відновлена з "
                  "фотокопій») — обидва ляжуть у теку"),
        card="sitecases")

    def __init__(self, workspace: Path | None = None, *, site: Site, repo: str,
                 fetcher: Fetcher | None = None, drive: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self.site = site
        self.repo = repo.upper()
        self.base = site.url.rstrip("/")
        self.id = site.source_id or f"site-{self.repo.lower()}"
        self.parser = site.parser
        if self.parser not in CRAWLERS:
            raise SourceError(f"для {self.repo} у паку вказано розбір «{self.parser}», "
                              f"а відомі лише: {', '.join(sorted(CRAWLERS))}")
        from nyshporka.archives import active

        self.label = f"Сайт архіву ({active().repo_label(self.repo)})"
        self._fetcher = fetcher
        self._drive = drive
        self._entries: list[CaseEntry] | None = None

    # ── шляхи ────────────────────────────────────────────────────────────────

    @property
    def slug(self) -> str:
        return f"{self.repo.lower()}_site"

    @property
    def catalog_rel(self) -> Path:
        return Path("data") / "raw" / self.slug / "_crawl" / "cases.json"

    def _catalog(self) -> Path:
        if self.workspace is None:
            raise SourceError("для каталогу сайту потрібен робочий простір")
        return self.workspace / self.catalog_rel

    # ── транспорт ────────────────────────────────────────────────────────────

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        lim = CrossProcessLimiter(f"site-{self.repo.lower()}", max_events=RATE_MAX,
                                  window=RATE_WINDOW)
        self._fetcher = Fetcher(base=self.base, delay=0.0, limiter=lim)
        return self._fetcher

    def _drive_http(self) -> Fetcher:
        if self._drive is not None:
            return self._drive
        from nyshporka.core.xrate import CrossProcessLimiter

        lim = CrossProcessLimiter("google-drive", max_events=DRIVE_RATE_MAX,
                                  window=DRIVE_RATE_WINDOW)
        self._drive = Fetcher(delay=0.0, limiter=lim)
        return self._drive

    def _online(self) -> None:
        if offline() and self._fetcher is None:
            raise SourceError("мережу вимкнено в цьому середовищі — сайт архіву не опитано")

    def _get_page(self, url: str) -> tuple[str, str]:
        try:
            r = self._http().get(url)
        except HttpError as exc:
            raise SourceError(f"сайт {self.base} не віддав сторінку {unquote(url)}: {exc}") from exc
        return str(getattr(r, "url", "") or url), str(r.text)

    def _get_range(self, url: str, start: int, end: int) -> tuple[int, bytes, int]:
        """Шматок файла `[start, end]`: (статус, байти, повний розмір із `Content-Range`).

        🔴 Потоком і зі стелею. Сервер ДАХО на тій самій справі віддав одну частину
        шматком (206), а іншу — цілим файлом (200, ~1 ГБ), проігнорувавши `Range`.
        Звичайний `get` читав тіло повністю, і запит на один байт тягнув гігабайт
        у пам'ять. Тепер статус дивиться до тіла: не 206 — `_NoRange` без
        читання, а тіло 206 обрізається на запитаній довжині.
        """
        http = self._http()
        if http.limiter is not None:
            http.limiter.acquire(url)
        want = end - start + 1
        for attempt in (1, 2):
            try:
                with http.client() as c, c.stream(
                        "GET", url, headers={"Range": f"bytes={start}-{end}"}) as r:
                    code = int(r.status_code)
                    if code >= 400:
                        raise SourceError(f"{unquote(url)}: HTTP {code}")
                    if code != 206:
                        if attempt == 1:
                            continue      # кеш перед сервером буває непослідовним — ще раз
                        raise _NoRange(url)
                    cr = str(r.headers.get("content-range") or "")
                    m = re.search(r"/(\d+)\s*$", cr)
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) >= want:
                            break
                    return code, bytes(buf[:want]), int(m.group(1)) if m else 0
            except (SourceError, _NoRange):
                raise
            except Exception as exc:
                raise SourceError(f"{unquote(url)}: сервер не відповів ({exc})") from exc
        raise _NoRange(url)

    # ── каталог ──────────────────────────────────────────────────────────────

    def crawl(self, groups: tuple[str, ...] | None = None, *,
              on_progress: ProgressFn | None = None,
              resume: bool = True) -> dict[str, Any]:
        """Обійти сторінки сайту й записати каталог справ.

        `groups` і `resume` не діють: обхід сайту — десятки чи сотні сторінок,
        і обірваний дешевше повторити, ніж зшивати.

        🔴 Каталог пишеться цілим наприкінці; позначка «не завершено» стоїть від
        старту, тож обрив лишає попередній каталог із чесною позначкою.
        """
        _ = (groups, resume)
        path = self._catalog()
        self._online()
        mark_crawl(path, complete=False) if path.is_file() else None
        stats = CrawlStats()

        def tick(done: int, total: int, note: str) -> None:
            if on_progress is not None:
                on_progress(done=done, total=total, unit="сторінка", note=note)

        first = [True]

        def get(url: str) -> tuple[str, str]:
            # Індекс сайту не відповів — обходу немає, і це відмова. Окрема
            # сторінка всередині (битe посилання редактора, 404) — пропуск із
            # записом: інакше одна мертва адреса з сотень зривала весь обхід.
            try:
                return self._get_page(url)
            except SourceError:
                if first[0]:
                    raise
                stats.skipped.append(url)
                return url, ""
            finally:
                first[0] = False

        entries = merge_parts(CRAWLERS[self.parser](get, self.base, stats, tick))
        if not entries:
            raise SourceError(
                f"на сайті {self.base} розбір «{self.parser}» не знайшов жодної справи "
                f"({stats.pages} сторінок) — розмітка змінилась; каталог не записано, "
                f"«справ немає» з цього було б вигаданим")
        taken = _dt.date.today().isoformat()
        payload = {"taken": taken, "site": self.base, "parser": self.parser,
                   "pages": stats.pages, "empty_pages": stats.empty_pages,
                   "failed_pages": stats.skipped,
                   "cases": [e.as_dict() for e in entries]}
        atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        mark_crawl(path, complete=True)
        self._entries = entries
        files = sum(len(e.files) for e in entries)
        summary = (f"справ {len(entries)} · файлів {files} · сторінок {stats.pages}"
                   + (f" · без справ {len(stats.empty_pages)}" if stats.empty_pages else "")
                   + (f" · не відкрилось {len(stats.skipped)}" if stats.skipped else "")
                   + f" · знімок від {taken}")
        out: dict[str, Any] = {"summary": summary, "cases": len(entries), "files": files,
                               "pages": stats.pages, "empty_pages": len(stats.empty_pages)}
        if stats.skipped:
            # `short` — ключ, на який `nysh crawl` друкує попередження: каталог
            # без цих сторінок неповний, і нуль по ньому мусить це знати.
            out["short"] = f"{len(stats.skipped)} сторінок сайту не відкрилось"
        return out

    def entries(self) -> list[CaseEntry]:
        if self._entries is not None:
            return self._entries
        path = self._catalog()
        if not path.is_file():
            raise SourceError(f"каталогу сайту ще немає — спершу `nysh crawl {self.id}` "
                              f"(без нього «справи немає» нічого б не означало)")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._entries = [CaseEntry.from_dict(d) for d in data.get("cases") or []]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"каталог {path} не читається ({exc}) — `nysh crawl {self.id}` "
                              f"збере його заново") from exc
        return self._entries

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        path = self._catalog()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "none", {"taken": "", "rows": None, "host": self.base}
        return "crawl", {"taken": str(data.get("taken") or ""),
                         "rows": len(data.get("cases") or []) or None, "host": self.base,
                         "complete": crawl_complete(path)}

    def _refs(self) -> list[tuple[str, CaseEntry]]:
        """Адреса кожної справи; однакова шифра двічі — `…~2` для другої."""
        seen: dict[str, int] = {}
        out = []
        for e in self.entries():
            k = key_of(e)
            seen[k] = seen.get(k, 0) + 1
            out.append((k if seen[k] == 1 else f"{k}~{seen[k]}", e))
        return out

    def _resolve(self, ref: str) -> CaseEntry:
        r = (ref or "").strip()
        exact = [e for k, e in self._refs() if k == r]
        if exact:
            return exact[0]
        fond, opys, spr = parse_key(r.split("~")[0])
        if not (opys and spr):
            raise SourceError(f"«{ref}» — не справа: потрібні фонд, опис і справа "
                              f"(`nysh browse {self.id} {fond}` покаже описи)")
        hit = [e for e in self.entries()
               if _eq(e.fond, fond) and _eq(e.opys, opys) and _eq(e.sprava, spr)]
        if not hit:
            raise SourceError(self._absent(fond, opys, spr))
        if len(hit) > 1 and "~" not in r:
            return hit[0]
        n = int(r.split("~")[1]) if "~" in r and r.split("~")[1].isdigit() else 1
        if n > len(hit):
            raise SourceError(f"у {fond}/{opys}/{spr} лише {len(hit)} записів на сайті")
        return hit[n - 1]

    def _absent(self, fond: str, opys: str, spr: str) -> str:
        data = self.catalog_source()[1]
        of = [e for e in self.entries() if _eq(e.fond, fond)]
        where = (f"опис {opys} фонду {fond} на сайті є ({len([e for e in of if _eq(e.opys, opys)])} "
                 f"справ)" if any(_eq(e.opys, opys) for e in of)
                 else f"фонду {fond} на сторінках сайту немає" if not of
                 else f"у фонді {fond} на сайті описи: "
                      + ", ".join(sorted({e.opys for e in of})[:20]))
        return (f"справи {fond}/{opys}/{spr} на сторінках сайту {self.base} немає "
                f"(каталог від {data.get('taken') or '?'}); {where}. Це не «не "
                f"оцифровано»: сайт оновлюється щомісяця — `nysh crawl {self.id}`")

    # ── пошук і перегляд ─────────────────────────────────────────────────────

    def _hit(self, ref: str, e: CaseEntry) -> Hit:
        return Hit(source=self.id, ref=ref, title=e.title or f"Справа {key_of(e)}",
                   years=e.years, shifra=f"{self.label_short} {e.fond}-{e.opys}-{e.sprava}",
                   frames=None, acquirable=True, url=e.page, repo=self.repo, fond=e.fond,
                   note=", ".join(sorted({f.kind for f in e.files})))

    @property
    def label_short(self) -> str:
        from nyshporka.archives import active

        return active().repo_label(self.repo)

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        from nyshporka.utils import text as T

        needle = T.strip_invisible(q or "").casefold().replace("ё", "е").strip()
        if not needle:
            return []
        out = Hits()
        for ref, e in self._refs():
            hay = f"{e.title} {e.fond}-{e.opys}-{e.sprava}".casefold().replace("ё", "е")
            if needle in hay:
                out.append(self._hit(ref, e))
                if len(out) >= limit:
                    out.truncated = f"показано перші {limit}"
                    break
        return out

    def find_case(self, fond: str, opys: str, spr: str, *, repo: str = "") -> list[Hit]:
        if repo and repo.upper() != self.repo:
            return []
        f, o, s = parse_key(f"{fond}/{opys}/{spr}")
        return [self._hit(ref, e) for ref, e in self._refs()
                if _eq(e.fond, f) and _eq(e.opys, o) and _eq(e.sprava, s)]

    def browse(self, ref: str | None = None) -> list[Node]:
        entries = self.entries()
        if not ref:
            by: dict[str, int] = {}
            for e in entries:
                by[e.fond] = by.get(e.fond, 0) + 1
            return [Node(ref=f, label=f"Фонд {f} — справ: {n}") for f, n in by.items()]
        fond, opys, spr = parse_key(ref)
        if spr:
            e = self._resolve(ref)
            return [Node(ref=f.url, label=f"{f.kind}: {f.label or unquote(f.url).rsplit('/', 1)[-1]}",
                         kind="file") for f in e.files]
        of = [(k, e) for k, e in self._refs() if _eq(e.fond, fond)]
        if not of:
            raise SourceError(f"фонду {fond} на сторінках сайту немає")
        if not opys:
            ops: dict[str, int] = {}
            for _, e in of:
                ops[e.opys] = ops.get(e.opys, 0) + 1
            return [Node(ref=f"{fond}/{o}", label=f"Опис {o} — справ: {n}") for o, n in ops.items()]
        return [Node(ref=k, label=f"Спр. {e.sprava}: {e.title}" + (f" · {e.years}" if e.years else ""),
                     kind="case") for k, e in of if _eq(e.opys, opys)]

    # ── маніфест і завантаження ──────────────────────────────────────────────

    def _frame_plan(self, e: CaseEntry) -> list[_Frame]:
        """Кадри справи з ZIP і галерей — у порядку частин, а в частині за іменем.

        🔴 Номер кадру (`--frames 3-5`) рахується наскрізно через усі частини:
        «кадр 4» справи з трьох ZIP — це перший кадр другої частини, а не
        четвертий кожної.
        """
        parts = [f for f in e.files if f.kind in FRAME_KINDS]
        multi = len(parts) > 1
        out: list[_Frame] = []
        for p, f in enumerate(parts, 1):
            prefix = f"p{p}_" if multi else ""
            if f.kind == "zip":
                rz = RemoteZip(self._get_range, f.url)
                for m in frames_of(rz.members()):
                    out.append(_Frame(name=prefix + m.name.rsplit("/", 1)[-1], size=m.usize,
                                      read=_zip_reader(rz, m)))
            else:
                pb, pt = self._get_page(f.url)
                imgs = gallery_images(pb, pt)
                if not imgs:
                    raise SourceError(f"на сторінці справи {f.url} кадрів галереї не знайдено — "
                                      f"розмітка змінилась або справу прибрали")
                for u in imgs:
                    out.append(_Frame(name=prefix + unquote(u).rsplit("/", 1)[-1], size=0,
                                      read=self._image_reader(u)))
        return out

    def _image_reader(self, url: str) -> Any:
        def read() -> bytes:
            try:
                return bytes(self._http().get(url).content)
            except HttpError as exc:
                raise SourceError(f"{unquote(url)}: {exc}") from exc
        return read

    def manifest(self, ref: str) -> Manifest:
        e = self._resolve(ref)
        self._online()
        kinds = {f.kind for f in e.files}
        frames: int | None
        unit = "файл"
        note = ""
        if kinds <= FRAME_KINDS:
            try:
                frames, unit = len(self._frame_plan(e)), "кадр"
            except _NoRange:
                frames, note = None, "сервер не віддає шматків ZIP — архів ляже цілим і розпакується"
        else:
            frames = len(e.files)
        return Manifest(
            source=self.id, ref=ref,
            title=(f"{self.label_short} {e.fond}-{e.opys}-{e.sprava}"
                   + (f": {e.title}" if e.title else ""))[:200],
            frames=frames,
            meta={"unit": unit, "files": [{"url": f.url, "kind": f.kind, "label": f.label}
                                          for f in e.files],
                  "page": e.page, "years": e.years, "note": note,
                  "suggested_dest": f"data/raw/{self.repo.lower()}_{e.fond.lower()}/"})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        e = self._resolve(ref)
        self._online()
        dest.mkdir(parents=True, exist_ok=True)
        res = FetchResult(dest=dest)
        kinds = {f.kind for f in e.files}
        if frames is not None and not kinds <= FRAME_KINDS:
            raise SourceError("справа приходить файлами (PDF/DjVu), тож окремі кадри звідси "
                              "не беруться — качається все, а сторінки вибирає читання")
        files_meta: list[dict[str, Any]] = []
        if kinds & FRAME_KINDS:
            self._fetch_frames(e, dest, frames, res, files_meta, on_progress)
        rest = [f for f in e.files if f.kind not in FRAME_KINDS]
        for i, f in enumerate(rest, 1):
            self._fetch_file(e, f, i, len(rest), dest, res, files_meta, on_progress)
        from nyshporka.cases.acquire import patch_meta

        patch_meta(dest, {"site_cases": {"source": self.id, "repo": self.repo,
                                         "fond": e.fond, "opys": e.opys, "sprava": e.sprava,
                                         "title": e.title, "years": e.years, "page": e.page,
                                         "files": [f.url for f in e.files]},
                          "files": files_meta})
        return res

    # PDF, DjVu, Drive — файлом
    def _fetch_file(self, e: CaseEntry, f: CaseFile, i: int, total: int, dest: Path,
                    res: FetchResult, files_meta: list[dict[str, Any]],
                    on_progress: ProgressFn | None) -> None:
        from nyshporka.utils.fsname import UnsafeName, safe_filename

        ext = {"pdf": ".pdf", "drive": ".pdf", "djvu": ".djvu"}.get(f.kind, "")
        stem = f"{e.fond}-{e.opys}-{e.sprava}" + (f"_{i:02d}" if total > 1 else "")
        if f.label and total > 1:
            lab = re.sub(r"[^\w.-]+", "_", f.label).strip("_")[:40]
            stem += f"_{lab}" if lab else ""
        try:
            out = dest / safe_filename(stem + ext)
        except UnsafeName as exc:
            res.errors.append(f"{f.url}: ім'я файла не годиться для диска ({exc})")
            return
        if out.is_file() and out.stat().st_size > 0 and _magic_ok(out, f.kind):
            res.skipped += 1
            res.bytes += out.stat().st_size
            files_meta.append({"file": out.name, "size": out.stat().st_size,
                               "source_url": f.url})
            return
        if f.kind == "drive":
            url, http = DRIVE_URL.format(id=drive_id(f.url)), self._drive_http()
        else:
            url, http = f.url, self._http()

        def _tick(done: int) -> None:
            if on_progress is not None:
                on_progress(done=done, total=None, unit="байт", note=out.name)

        try:
            got = http.download(url, out, on_chunk=_tick, max_bytes=FILE_MAX_BYTES)
        except (HttpError, OSError) as exc:
            res.errors.append(f"{out.name}: {exc}")
            return
        if not _magic_ok(out, f.kind):
            head = out.read_bytes()[:200]
            out.unlink(missing_ok=True)
            why = ("Google Drive віддав сторінку замість файла — доступ закрито або "
                   "перевищено ліміт завантажень" if f.kind == "drive" and b"<html" in head.lower()
                   else f"початок файла не схожий на {ext.lstrip('.').upper()}")
            res.errors.append(f"{out.name}: {why}; у теку він не ліг")
            return
        res.frames += 1
        res.bytes += got
        files_meta.append({"file": out.name, "size": got, "sha1": _sha1(out), "source_url": f.url})

    # ZIP і галерея — кадрами
    def _fetch_frames(self, e: CaseEntry, dest: Path, frames: tuple[int, int] | None,
                      res: FetchResult, files_meta: list[dict[str, Any]],
                      on_progress: ProgressFn | None) -> None:
        parts = [f for f in e.files if f.kind in FRAME_KINDS]
        try:
            plan = self._frame_plan(e)
        except _NoRange:
            if frames is not None:
                raise SourceError("сервер не віддає шматків ZIP — окремі кадри не беруться, "
                                  "лише вся справа") from None
            for p, f in enumerate(parts, 1):
                self._fetch_whole_zip(f, dest, res, multi=len(parts) > 1, part=p)
            files_meta += [{"part": f.url, "kind": f.kind, "label": f.label} for f in parts]
            return
        lo, hi = frames if frames else (1, len(plan))
        for n, fr in enumerate(plan, 1):
            if n < lo or n > hi:
                continue
            out = dest / fr.name
            if out.is_file() and out.stat().st_size > 0 and (not fr.size or out.stat().st_size == fr.size):
                res.skipped += 1
                res.bytes += out.stat().st_size
                continue
            try:
                blob = fr.read()
            except SourceError as exc:
                res.errors.append(str(exc))
                continue
            atomic_write_bytes(out, blob)
            res.frames += 1
            res.bytes += len(blob)
            if on_progress is not None:
                on_progress(done=n - lo + 1, total=hi - lo + 1, unit="кадр", note=fr.name)
        files_meta += [{"part": f.url, "kind": f.kind, "label": f.label} for f in parts]

    def _fetch_whole_zip(self, f: CaseFile, dest: Path, res: FetchResult, *,
                         multi: bool, part: int) -> None:
        import zipfile

        tmp = dest / f".part{part}.zip"
        try:
            self._http().download(f.url, tmp, max_bytes=FILE_MAX_BYTES)
            with zipfile.ZipFile(tmp) as z:
                for info in sorted(z.infolist(), key=lambda i: i.filename):
                    if info.is_dir() or not info.filename.lower().endswith(IMAGE_EXT):
                        continue
                    name = (f"p{part}_" if multi else "") + info.filename.rsplit("/", 1)[-1]
                    out = dest / name
                    if out.is_file() and out.stat().st_size == info.file_size:
                        res.skipped += 1
                        continue
                    atomic_write_bytes(out, z.read(info))
                    res.frames += 1
                    res.bytes += info.file_size
        except (HttpError, OSError, zipfile.BadZipFile) as exc:
            res.errors.append(f"{unquote(f.url)}: {exc}")
        finally:
            tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class _Frame:
    name: str                 # ім'я кадру в теці справи
    size: int                 # очікуваний розмір; 0 — невідомо (галерея)
    read: Any                 # () -> bytes


def _zip_reader(rz: RemoteZip, m: ZipMember) -> Any:
    return lambda: rz.read(m)


def _magic_ok(path: Path, kind: str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    if kind in ("pdf", "drive"):
        return head.startswith(b"%PDF-")
    if kind == "djvu":
        return head.startswith(b"AT&TFORM")
    return bool(head)


def _sha1(path: Path) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sources_from_pack(workspace: Path | None) -> Iterator[SiteCasesSource]:
    """По джерелу на кожен майданчик `cases` у паку архівів."""
    from nyshporka.archives import active

    for repo, site in active().sites("cases"):
        yield SiteCasesSource(workspace, site=site, repo=repo)
