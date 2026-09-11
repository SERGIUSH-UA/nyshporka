"""📖 Чтиво — архівна копія е-бібліотеки chtyvo.org.ua на shron.org.

Навіщо поруч з архівами
───────────────────────
Архіви відповідають «де документ», а тут друковане: краєзнавчі праці, збірники
документів, словники говірок, історії парафій і повітів — книги, у яких наші
села й прізвища трапляються вже прочитаними кимось. Бібліотека закрилась у
березні 2026; її копія на shron.org стоїть на DSpace, і DSpace шукає по
ПОВНОМУ ТЕКСТУ файлів, а не лише по назві: «Липовеньк*» знаходить словник
говірок, у метаданих якого цього слова немає (замір 11.09.2026).

🔴 Уривка сервер не дає (`hitHighlights` порожній). Знахідка каже «слово є
десь у книзі або в її описі», а де саме — показує лише текстовий шар після
завантаження (`nysh get chtyvo …`, далі `nysh text grep --dir <тека>`).

🔴 Сторінка видачі — не більше 100. На `size=500` сервер віддає сто рядків і
каже, що всього їх сто, хоча за тим самим запитом їх 445: знаменник бреше саме
тоді, коли його просять більшим. Тому `PAGE_MAX`, і справжня кількість їде в
примітку кожної знахідки.

🔴 Твори з позначкою «файли ще не відновлені» в DSpace відсутні взагалі —
сайт бібліотеки знає про них лише посилання на веб-архів. Нуль звідси означає
«серед відновленого немає», а не «такої книги не існує».

🔴 У chtyvo.shron.org не ходимо. Її robots.txt закриває все для роботів
(`Disallow: /`), тоді як shron.org відкриває API. Адресу сторінки звідти
приймаємо як ВХІД і розв'язуємо через метадані DSpace, сторінку не качаючи.

Адресація (`ref`): `chtyvo:<Автор>/<Твір>` — слаг бібліотеки, той самий, що в
адресі сторінки; ще приймаються адреса сторінки на chtyvo.shron.org чи
chtyvo.org.ua, `item:<uuid>` і `handle:shron/<номер>`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from nyshporka.sources.base import FetchResult, Hit, Manifest, Node, SourceError
from nyshporka.sources.http import Fetcher, HttpError, app_ua, offline

if TYPE_CHECKING:
    from nyshporka.sources.base import ProgressFn

HOST = "https://shron.org"
API = "/server/api"
#: Сайт бібліотеки. Лише для адрес, які ми ДРУКУЄМО, — запитів туди немає.
SITE = "https://chtyvo.shron.org"
#: Колекція «ЧТИВО» в DSpace. Поки що вона на сервері єдина, але пошук без
#: `scope` почав би віддавати чуже, щойно там з'явиться друга.
COLLECTION = "9ac3a705-237c-4f5c-9995-9b4e834bffb5"

#: Найбільша сторінка видачі, на яку сервер відповідає чесно (див. докстрінг).
PAGE_MAX = 100

#: Спільна на машину черга: сервер волонтерський, і дві сесії з бездоганною
#: паузою кожна давали б подвійний темп.
RATE_KEY = "shron"
RATE_MAX = 3
RATE_WINDOW = 3.0

_PAGE_RX = re.compile(
    r"^https?://chtyvo\.(?:shron\.org|org\.ua)/authors/([^/?#]+)/([^/?#]+)", re.IGNORECASE)
_UUID_RX = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)
_HANDLE_RX = re.compile(r"^shron/\d+$")

_MIME_SHORT = {"application/pdf": "PDF", "image/vnd.djvu": "DjVu",
               "application/msword": "DOC", "text/plain": "TXT",
               "application/epub+zip": "EPUB", "application/rtf": "RTF"}


def _values(md: dict[str, Any], key: str) -> list[str]:
    vals = md.get(key) or []
    if not isinstance(vals, list):
        return []
    return [" ".join(str(v.get("value") or "").split())
            for v in vals if isinstance(v, dict) and v.get("value")]


def _first(md: dict[str, Any], key: str) -> str:
    vals = _values(md, key)
    return vals[0] if vals else ""


def _url(value: str) -> str:
    """Посилання з чужих метаданих — лише http(s), інакше порожньо.

    🔴 Рядок іде в `href` консолі як є; `javascript:` звідси виконався б в
    origin застосунку.
    """
    return value if value.lower().startswith(("http://", "https://")) else ""


def slug_of(ref: str) -> str:
    """Слаг бібліотеки (`<Автор>/<Твір>`) з адреси. Порожньо — адреса не така.

    Приймає `chtyvo:<Автор>/<Твір>` і адресу сторінки твору на обох хостах
    бібліотеки. Сама сторінка при цьому не запитується.
    """
    s = (ref or "").strip()
    m = _PAGE_RX.match(s)
    if m:
        return f"{unquote(m.group(1))}/{unquote(m.group(2))}"
    kind, _, ident = s.partition(":")
    if kind != "chtyvo":
        return ""
    ident = ident.strip().strip("/")
    parts = ident.split("/")
    return ident if len(parts) == 2 and all(parts) else ""


@dataclass(frozen=True)
class Work:
    """Твір бібліотеки — те, що DSpace знає про нього в метаданих."""

    uuid: str
    slug: str
    title: str
    handle: str = ""
    author: str = ""
    year: str = ""
    genre: str = ""
    mime: tuple[str, ...] = ()
    #: Сторінка твору на копії бібліотеки — туди людина йде читати опис.
    page_url: str = ""
    #: Адреса на закритому chtyvo.org.ua — щоб зіставити зі старими нотатками.
    old_url: str = ""

    @property
    def ref(self) -> str:
        return f"chtyvo:{self.slug}" if self.slug else f"item:{self.uuid}"

    def as_meta(self) -> dict[str, object]:
        return {"title": self.title, "author": self.author, "year": self.year,
                "genre": self.genre, "slug": self.slug, "dspace_item": self.uuid,
                "handle": self.handle, "page": self.page_url,
                "page_old": self.old_url}


def work_of(obj: dict[str, Any]) -> Work:
    """Item DSpace (з пошуку чи напряму) → `Work`."""
    md = obj.get("metadata") or {}
    if not isinstance(md, dict):
        md = {}
    other = _first(md, "dc.identifier.other")
    slug = other.removeprefix("chtyvo:") if other.startswith("chtyvo:") else ""
    page = _url(_first(md, "dc.identifier.uri"))
    if not page and slug:
        page = f"{SITE}/authors/{quote(slug, safe='/')}/"
    return Work(uuid=str(obj.get("uuid") or ""), slug=slug,
                title=_first(md, "dc.title") or str(obj.get("name") or ""),
                handle=str(obj.get("handle") or ""),
                author=", ".join(_values(md, "dc.contributor.author")),
                year=_first(md, "dc.date.issued"),
                genre=", ".join(_values(md, "dc.subject")),
                mime=tuple(_values(md, "dc.format.mimetype")),
                page_url=page, old_url=_url(_first(md, "dc.source")))


@dataclass(frozen=True)
class BookFile:
    """Файл твору в DSpace: ім'я, розмір і сума, яку назвав сам сервер."""

    name: str
    size: int
    md5: str
    url: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def files_of(data: Any) -> list[BookFile]:
    """Файли твору з бандла ORIGINAL. Мініатюри й службові бандли — повз.

    🔴 Обрізаний перелік — відмова, а не менше файлів. Сервер вкладає
    bitstream-и сторінкою; якщо вона неповна, мовчки взятий хвіст дав би теку,
    де «всі файли твору» — лише ті, що влізли.
    """
    bundles = ((data or {}).get("_embedded") or {}).get("bundles") if isinstance(data, dict) else None
    if not isinstance(bundles, list):
        raise SourceError("shron.org відповів не переліком бандлів — API змінився")
    out: list[BookFile] = []
    for b in bundles:
        if not isinstance(b, dict) or b.get("name") != "ORIGINAL":
            continue
        emb = ((b.get("_embedded") or {}).get("bitstreams") or {})
        rows = (emb.get("_embedded") or {}).get("bitstreams") or []
        total = (emb.get("page") or {}).get("totalElements")
        if isinstance(total, int) and total > len(rows):
            raise SourceError(
                f"сервер назвав {total} файлів твору, а віддав {len(rows)} — "
                f"перелік обрізаний, тож качати його як повний не можна")
        for bs in rows:
            if not isinstance(bs, dict):
                continue
            ck = bs.get("checkSum") or {}
            md5 = (str(ck.get("value") or "").lower()
                   if str(ck.get("checkSumAlgorithm") or "").upper() == "MD5" else "")
            href = str(((bs.get("_links") or {}).get("content") or {}).get("href") or "")
            if not href.startswith(HOST + "/"):
                href = f"{HOST}{API}/core/bitstreams/{bs.get('uuid')}/content"
            out.append(BookFile(name=str(bs.get("name") or ""),
                                size=int(bs.get("sizeBytes") or 0), md5=md5, url=href))
    return out


def _md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _same(out: Path, f: BookFile) -> bool:
    """Чи файл на диску — той самий, що на сервері. Невідомо — ні."""
    if not out.is_file() or not (f.size or f.md5):
        return False
    if f.size and out.stat().st_size != f.size:
        return False
    return not f.md5 or _md5(out) == f.md5


class ChtyvoSource:
    """Пошук по повному тексту Чтива й завантаження твору зі звіркою MD5."""

    id = "chtyvo"
    label = "Чтиво (архівна копія на shron.org)"
    caps = frozenset({"search", "manifest", "fetch"})

    def __init__(self, workspace: Path | None = None, *,
                 fetcher: Fetcher | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._fetcher = fetcher

    def _http(self) -> Fetcher:
        if self._fetcher is not None:
            return self._fetcher
        from nyshporka.core.xrate import CrossProcessLimiter

        # `delay=0`, бо темп тримає черга: два механізми складалися б.
        lim = CrossProcessLimiter(RATE_KEY, max_events=RATE_MAX, window=RATE_WINDOW)
        return Fetcher(base=HOST, delay=0.0, limiter=lim,
                       headers={"User-Agent": app_ua()})

    def _json(self, path: str, what: str, *, missing: str = "") -> Any:
        # 🔴 Вимкнена мережа — відмова, а не порожня видача: інакше вона
        # читалась би як «такої книги немає».
        if offline() and self._fetcher is None:
            raise SourceError("мережу вимкнено в цьому середовищі — Чтиво не опитано")
        try:
            r = self._http().get(path)
        except (HttpError, OSError) as exc:
            if missing and "HTTP 404" in str(exc):
                raise SourceError(missing) from None
            raise SourceError(f"shron.org не відповів ({what}): {exc}") from exc
        try:
            return json.loads(getattr(r, "text", "") or "")
        except ValueError:
            raise SourceError(
                f"shron.org відповів не JSON ({what}) — API змінився або сервер "
                f"віддав сторінку-заглушку") from None

    def _discover(self, query: str, size: int) -> tuple[list[dict[str, Any]], int]:
        size = max(1, min(size, PAGE_MAX))
        path = (f"{API}/discover/search/objects?scope={COLLECTION}&dsoType=ITEM"
                f"&size={size}&page=0&query={quote(query, safe='')}")
        data = self._json(path, "пошук")
        try:
            sr = data["_embedded"]["searchResult"]
            total = int(sr["page"]["totalElements"])
        except (KeyError, TypeError, ValueError):
            raise SourceError("відповідь shron.org не схожа на видачу пошуку DSpace") from None
        objs = (sr.get("_embedded") or {}).get("objects") or []
        items = [o["_embedded"]["indexableObject"] for o in objs
                 if isinstance(o, dict)
                 and isinstance((o.get("_embedded") or {}).get("indexableObject"), dict)]
        return items, total

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        """Живий запит: нуль означає «немає серед відновленого зараз»."""
        return "live", {"taken": "", "rows": None,
                        "scope": "Чтиво: повний текст відновлених творів (~79 тис.)",
                        "host": HOST}

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Пошук по тексту й метаданих творів. Запит іде як є: `*` і лапки працюють.

        ⚠ Знахідка не каже, ДЕ в книзі слово, — лише що воно там є. Тому в
        примітці стоїть, скільки всього творів за запитом: при сотнях це слово
        занадто загальне, і відповідь треба звужувати, а не гортати.
        """
        needle = " ".join((q or "").split())
        if not needle:
            return []
        items, total = self._discover(needle, limit)
        out: list[Hit] = []
        for obj in items:
            w = work_of(obj)
            if not (w.slug or w.uuid):
                continue
            fmt = ", ".join(_MIME_SHORT.get(m, m.rsplit("/", 1)[-1].upper()) for m in w.mime)
            parts = (w.author, w.genre, fmt, "збіг у тексті або описі",
                     f"з {total} за запитом")
            out.append(Hit(source=self.id, ref=w.ref, title=w.title[:200], years=w.year,
                           acquirable=True, note=" · ".join(p for p in parts if p),
                           url=w.page_url))
        return out

    def _item(self, path: str, label: str) -> Work:
        data = self._json(path, f"твір {label}",
                          missing=f"у DSpace-архіві shron.org немає твору «{label}»")
        if not isinstance(data, dict) or not data.get("uuid"):
            raise SourceError(f"shron.org не віддав опису твору «{label}»")
        return work_of(data)

    def _by_slug(self, slug: str) -> Work:
        """Слаг → твір. Пошук фразою, а рівність перевіряється тут.

        🔴 Пошук нечіткий: схожий слаг сусіднього твору того самого автора
        прийшов би першим і приписав теці чужу книгу.
        """
        items, _ = self._discover(f'"chtyvo:{slug.replace(chr(34), "")}"', 5)
        for obj in items:
            w = work_of(obj)
            if w.slug == slug:
                return w
        page = f"{SITE}/authors/{quote(slug, safe='/')}/"
        raise SourceError(
            f"у DSpace-архіві shron.org твору «{slug}» немає. Найімовірніше, його "
            f"файли не відновлено — такі твори лишились лише сторінкою бібліотеки "
            f"з посиланням на веб-архів: {page}")

    def resolve(self, ref: str) -> Work:
        """Будь-яка з прийнятих адрес → твір у DSpace."""
        s = (ref or "").strip()
        slug = slug_of(s)
        if slug:
            return self._by_slug(slug)
        kind, _, ident = s.partition(":")
        ident = ident.strip()
        if kind == "item" and _UUID_RX.match(ident):
            return self._item(f"{API}/core/items/{ident}", ident)
        if kind == "handle" and _HANDLE_RX.match(ident):
            return self._item(f"{API}/pid/find?id={quote(ident, safe='/')}", ident)
        raise SourceError(
            f"незрозуміла адреса: {ref!r} — тут очікується `chtyvo:<Автор>/<Твір>`, "
            f"адреса сторінки твору, `item:<uuid>` або `handle:shron/<номер>`")

    def _files(self, w: Work) -> list[BookFile]:
        data = self._json(f"{API}/core/items/{w.uuid}/bundles?embed=bitstreams",
                          "файли твору")
        files = files_of(data)
        if not files:
            raise SourceError(f"у твору «{w.title}» немає файлів у DSpace-архіві")
        return files

    def manifest(self, ref: str) -> Manifest:
        """Які файли принесе завантаження і скільки вони важать — до початку.

        🔴 «Кадр» тут — ФАЙЛ твору, а не аркуш. Книга приходить файлами
        (PDF, DjVu), і сторінок сервер не називає; зате він називає, скільки
        файлів і яка сума в кожного. Так `nysh get` отримує справжній
        знаменник «обіцяно / взято», а не «повноту не міряю».
        """
        w = self.resolve(ref)
        files = self._files(w)
        return Manifest(source=self.id, ref=ref, title=w.title, frames=len(files),
                        bytes_estimate=sum(f.size for f in files) or None,
                        meta={"url": w.page_url, **w.as_meta(),
                              "files": [f.as_dict() for f in files]})

    def fetch(self, ref: str, dest: Path, *, frames: tuple[int, int] | None = None,
              on_progress: ProgressFn | None = None) -> FetchResult:
        """Завантажити всі файли твору, звірити розмір і MD5, витягти текст PDF.

        🔴 Приймач — сума, яку назвав сервер, а не «файл є». Обірвана чи
        пошкоджена закачка під правильним іменем лягла б в облік як книга, і
        виявилось би це тоді, коли регекс не знайде в ній рядка, якого немає в
        недовантаженій частині.
        """
        if frames is not None:
            raise SourceError(
                "Чтиво віддає твір файлами, а не кадрами, тож окремі сторінки звідси "
                "не беруться — качається файл цілком, а сторінки вибирає читання")
        import httpx

        from nyshporka.utils.fsname import UnsafeName, safe_filename
        from nyshporka.utils.pdftext import extract

        w = self.resolve(ref)
        files = self._files(w)
        http = self._http()
        res = FetchResult(dest=dest)
        total = sum(f.size for f in files) or None
        base = 0
        rows: list[dict[str, object]] = []
        layers: dict[str, object] = {}
        for f in files:
            try:
                out = dest / safe_filename(f.name)
            except UnsafeName as exc:
                res.errors.append(f"{f.name}: ім'я не годиться для диска: {exc}")
                continue
            if _same(out, f):
                res.skipped += 1
            else:
                def _tick(done: int, _base: int = base, _name: str = f.name) -> None:
                    if on_progress is not None:
                        on_progress(done=_base + done, total=total, unit="байт", note=_name)

                try:
                    got = http.download(f.url, out, on_chunk=_tick)
                except (HttpError, OSError, httpx.HTTPError) as exc:
                    out.with_name(out.name + ".part").unlink(missing_ok=True)
                    res.errors.append(f"{f.name}: {exc}")
                    continue
                if f.size and got != f.size:
                    out.unlink(missing_ok=True)
                    res.errors.append(f"{f.name}: отримано {got} байт замість {f.size} — "
                                      f"файл неповний, тож у теку він не ліг")
                    continue
                if f.md5 and _md5(out) != f.md5:
                    out.unlink(missing_ok=True)
                    res.errors.append(f"{f.name}: контрольна сума не зійшлась із тією, "
                                      f"що назвав сервер — файл пошкоджений, у теку не ліг")
                    continue
                res.frames += 1
                res.bytes += got
            base += f.size
            rows.append({"file": out.name, "size": f.size, "md5": f.md5,
                         "source_url": f.url})
            if out.suffix.lower() == ".pdf":
                try:
                    layer = extract(out)
                except Exception as exc:   # pypdfium2 кидає власний PdfiumError
                    # Битий PDF не привід загубити вже звірений файл.
                    layers[out.name] = {"verdict": "error", "why": str(exc)}
                    res.notes.append(f"{out.name}: текст із PDF не витягся ({exc})")
                    continue
                layers[out.name] = layer.as_dict()
                msg = layer.explain(out.name)
                if msg:
                    res.notes.append(msg)
            else:
                layers[out.name] = {"verdict": "not_pdf"}
        if rows and not any(str(r["file"]).lower().endswith(".pdf") for r in rows):
            res.notes.append("у твору немає PDF — текстового шару не буде, регекс цих "
                             "файлів не бачить; шукати в них лише оком або після OCR")
        if rows:
            from nyshporka.cases.acquire import patch_meta

            try:
                patch_meta(dest, {"book": w.as_meta(), "files": rows, "text_layer": layers})
            except OSError as exc:
                res.notes.append(f"паспорт книги не записався: {exc}")
        return res

    def browse(self, ref: str | None = None) -> list[Node]:
        """🔴 Відмова, а не порожній список.

        Дерево авторів і розділів є лише на сайті бібліотеки, а він роботам
        закритий (robots.txt); DSpace же тримає твори пласкою колекцією.
        """
        raise SourceError(
            "у Чтива тут немає дерева: перелік авторів і розділів живе на сайті "
            "бібліотеки, закритому для роботів. Шукай: `nysh find <слово> --source chtyvo`")
