"""📷 Фотоархів Олександра Волока на Flickr — список альбомів.

Навіщо поруч з архівами
───────────────────────
Олександр Волок фотографує в архівах і бібліотеках підряд і викладає зйомку
альбомами на Flickr: справи РДІА (дворянство, Селянський поземельний банк,
плани міст), ДАДО, ДАКО (Курськ), ГА РФ, Бундесархів, плюс друковане —
родовідні книги, списки населених місць, губернські огляди. Альбомів тисячі
(4657 у списку від 12.09.2026), а пошуку по них Flickr не дає: знайти справу
можна лише в списку, яким автор ділиться зі спільнотою HTML-файлом.

🔴 Шукаємо лише в НАЗВАХ альбомів. Нуль означає «у списку на дату зрізу
немає альбому з такими словами в назві», а не «цієї справи ніхто не знімав»:
назву альбому пише автор, і топонім часто стоїть не в ній, а на самих кадрах.

🔴 Джерело нічого не качає і в мережу не ходить. Знахідка — це адреса
альбому; фотографії дивляться й беруть на Flickr.

🔴 Російські й українські назви пишуться впереміш («Мелитопольский уезд» і
«Мелітопольський повіт»), тож збіг рахується двічі: по назві як є і по
нормалізованій (`normalize_for_matching`), де обидва написання сходяться.

Список оновлюється, коли автор викладає новий файл. Вкладений у пакет зріз
лишається запасним; новіший кладеться в простір командою
`nysh crawl volok --from List<дата>.zip` і має перевагу.

Адресація (`ref`): `album:<id альбому Flickr>`.
"""
from __future__ import annotations

import csv
import datetime as _dt
import gzip
import hashlib
import html as _html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from nyshporka.sources.base import Hit, SourceError
from nyshporka.utils.atomic import atomic_write_bytes
from nyshporka.utils.translit import normalize_for_matching

FIELDS = ("album", "kind", "title", "archive", "shifra", "years")

SNAPSHOT_NAME = "volok_albums.tsv.gz"
SNAPSHOT_META = "volok_albums.json"

_ANCHOR = re.compile(r"<a\s[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_ALBUM = re.compile(r"^https?://(?:www\.)?flickr\.com/photos/[^/]+/albums/(\d+)/?$",
                    re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
#: Рід запису — слово великими літерами на початку назви: «КНИГА», «АРХІВ».
_KIND = re.compile(r"^([А-ЯІЇЄҐA-Z][А-ЯІЇЄҐA-Z’']{2,})\b(?:\s+-\s+|\s+)")
#: Шифра «фонд-опис-справа». Опис буває з суфіксом («001пош», «001л»), фонд — з
#: «Р-» чи «Р » (ГА РФ пише і так, і так); без цього третина справ ДАДО лишалась
#: без шифри, а «Р» з пробілом прилипала до назви архіву.
_SHIFRA = re.compile(r"(?<![\w-])((?:[РрR][-\s]?)?\d{1,5}[а-яa-z]?-\d{1,4}[а-яa-z]{0,3}"
                     r"-\d{1,6}[а-яА-Яa-zA-Z]{0,2})(?![\w-])")
_YEARS_PAREN = re.compile(r"\(([^()]*\d{4}[^()]*)\)")
_YEARS_TAIL = re.compile(r"\b(\d{4}(?:\s*[-–/]\s*\d{2,4})?)\s*$")
_LIST_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def _flat(s: str) -> str:
    return " ".join((s or "").split())


def _fold(s: str) -> str:
    return s.casefold().replace("ё", "е").replace("’", "'").replace("ʼ", "'")


@dataclass(frozen=True)
class Album:
    album: str
    kind: str
    title: str
    archive: str = ""
    shifra: str = ""
    years: str = ""

    def row(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in FIELDS}


def album_of(album_id: str, text: str) -> Album:
    """Назва альбому → поля. Розбирається лише те, що розбирається однозначно.

    🔴 Архів лише для записів «АРХІВ» і лише тоді, коли знайшлась шифра: назва
    архіву стоїть між родом запису й шифрою. Без шифри межі немає, і «архівом»
    ставала б уся назва.
    """
    title = _flat(text)
    kind = ""
    m = _KIND.match(title)
    if m:
        kind = m.group(1)
        title = title[m.end():].strip()
    archive = shifra = ""
    sm = _SHIFRA.search(title)
    if sm:
        shifra = sm.group(1)
        if kind == "АРХІВ":
            archive = title[:sm.start()].strip(" -")
    years = ""
    paren = _YEARS_PAREN.findall(title)
    if paren:
        years = _flat(paren[-1])
    else:
        tm = _YEARS_TAIL.search(title)
        if tm and not (shifra and title.endswith(shifra)):
            years = tm.group(1)
    return Album(album=album_id, kind=kind, title=title, archive=archive,
                 shifra=shifra, years=years)


def parse_list(html: str) -> tuple[list[Album], int]:
    """HTML-список → альбоми й кількість посилань, що альбомами не є.

    🔴 Посилання не на альбом не відкидається мовчки: число їде в паспорт
    зрізу. Якщо автор змінить формат списку, знаменник покаже це одразу, а не
    тоді, коли пошук почне віддавати нуль.
    """
    out: list[Album] = []
    seen: set[str] = set()
    other = 0
    for href, inner in _ANCHOR.findall(html or ""):
        m = _ALBUM.match(_html.unescape(href).strip())
        if not m:
            other += 1
            continue
        album_id = m.group(1)
        if album_id in seen:
            continue
        seen.add(album_id)
        out.append(album_of(album_id, _html.unescape(_TAG.sub(" ", inner))))
    return out, other


def read_list_file(path: Path) -> tuple[str, str]:
    """Файл списку (`.zip` з одним `.htm` або сам `.htm`) → (HTML, ім'я файлу).

    🔴 Архів із кількома HTML — відмова, а не перший-ліпший: два списки різних
    дат злились би в один зріз з однією датою.
    """
    if not path.is_file():
        raise SourceError(f"файлу списку немає: {path}")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise SourceError(f"архів пошкоджений: {bad} не читається")
            pages = [n for n in zf.namelist() if n.lower().endswith((".htm", ".html"))]
            if len(pages) != 1:
                raise SourceError(
                    f"в архіві очікується рівно один HTML-список, а їх {len(pages)}")
            raw, name = zf.read(pages[0]), Path(pages[0]).name
    else:
        raw, name = path.read_bytes(), path.name
    try:
        return raw.decode("utf-8"), name
    except UnicodeDecodeError:
        return raw.decode("cp1251"), name


def write_snapshot(albums: list[Album], out_dir: Path, *, taken: str, origin: str,
                   sha256: str, skipped: int) -> dict[str, Any]:
    """Покласти зріз: стиснений TSV і паспорт поруч."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    w.writeheader()
    for a in albums:
        w.writerow(a.row())
    out_dir.mkdir(parents=True, exist_ok=True)
    # `mtime=0` — щоб той самий список давав побітово той самий файл.
    atomic_write_bytes(out_dir / SNAPSHOT_NAME,
                       gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))
    meta = {"taken": taken, "rows": len(albums), "origin": origin,
            "sha256": sha256, "not_albums": skipped,
            "author": "Олександр Волок", "host": "https://www.flickr.com/photos/alexander_volok/"}
    atomic_write_bytes(out_dir / SNAPSHOT_META,
                       (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return meta


@lru_cache(maxsize=4)
def _load(path: Path, mtime_ns: int, size: int) -> tuple[tuple[dict[str, str], str, str], ...]:
    """Рядки зрізу разом із двома формами назви для збігу. Ключ — штамп файлу."""
    _ = (mtime_ns, size)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    return tuple((r, _fold(r["title"]), normalize_for_matching(r["title"])) for r in rows)


class VolokSource:
    """Пошук по назвах альбомів зі списку Олександра Волока."""

    id = "volok"
    label = "Фотоархів О. Волока (альбоми Flickr)"
    caps = frozenset({"search"})

    LIST_REL = Path("data") / "raw" / "volok" / "_list"

    def __init__(self, workspace: Path | None = None, *,
                 bundled_dir: Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self.bundled_dir = bundled_dir or (
            Path(__file__).resolve().parent.parent / "archives" / "data")

    def _snapshot(self) -> tuple[str, Path] | None:
        if self.workspace is not None:
            d = self.workspace / self.LIST_REL
            if (d / SNAPSHOT_NAME).is_file():
                return "workspace", d
        if (self.bundled_dir / SNAPSHOT_NAME).is_file():
            return "bundled", self.bundled_dir
        return None

    def catalog_source(self) -> tuple[str, dict[str, Any]]:
        got = self._snapshot()
        if got is None:
            return "none", {}
        kind, d = got
        try:
            meta = json.loads((d / SNAPSHOT_META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        return kind, {"path": str(d / SNAPSHOT_NAME), "taken": meta.get("taken", ""),
                      "rows": meta.get("rows"), "origin": meta.get("origin", ""),
                      "scope": "назви альбомів (не вміст кадрів)"}

    def search(self, q: str, *, limit: int = 30) -> list[Hit]:
        """Альбоми, у назві яких є ВСІ слова запиту (як є або після нормалізації).

        ⚠ Збіг — підрядок, відмінків він не знає: «Мелітопольський» знаходить 1
        альбом, «Мелітопол» — 15 (замір по списку від 12.09.2026). Шукати основою.

        🔴 Кількість збігів їде в примітку, коли видача обрізана: «показано 30»
        без «з 212» читалось би як повний перелік.
        """
        words = _flat(q).split()
        if not words:
            return []
        kind, info = self.catalog_source()
        if kind == "none":
            raise SourceError(
                "списку альбомів немає ні в просторі, ні в пакеті — нуль тут нічого не "
                "означав би. Покладіть список: `nysh crawl volok --from List<дата>.zip`")
        path = Path(info["path"])
        st = path.stat()
        folded = [_fold(w) for w in words]
        normed = [normalize_for_matching(w) for w in words]
        found: list[dict[str, str]] = []
        for row, t_fold, t_norm in _load(path, st.st_mtime_ns, st.st_size):
            if all(f in t_fold or (n and n in t_norm) for f, n in zip(folded, normed, strict=True)):
                found.append(row)
        taken = info.get("taken") or ""
        tail = f" · з {len(found)} за запитом" if len(found) > limit else ""
        out: list[Hit] = []
        for row in found[:limit]:
            note = " · ".join(x for x in (row["kind"].capitalize(), "фото на Flickr",
                                          f"список від {taken}" if taken else "") if x)
            out.append(Hit(source=self.id, ref=f"album:{row['album']}",
                           title=row["title"][:200], years=row["years"],
                           shifra=row["shifra"], archive=row["archive"],
                           acquirable=False,
                           url=f"https://www.flickr.com/photos/alexander_volok/albums/{row['album']}",
                           note=note + tail))
        return out

    def import_list(self, path: Path) -> dict[str, Any]:
        """Новий список автора → зріз у просторі. Дата — з імені файлу списку.

        🔴 Без дати відмова: зріз без дати не відповідає на питання «на коли
        цей нуль», а дата зміни файлу — це дата завантаження, не списку.
        """
        if self.workspace is None:
            raise SourceError("простору немає — класти список нікуди")
        html, name = read_list_file(Path(path))
        albums, skipped = parse_list(html)
        if not albums:
            raise SourceError(
                f"у «{name}» немає жодного посилання на альбом Flickr — це не список "
                f"Волока або автор змінив формат")
        m = _LIST_DATE.search(name) or _LIST_DATE.search(Path(path).name)
        if not m:
            raise SourceError(
                f"з імені «{name}» не видно дати списку (очікується List<РРРРММДД>)")
        taken = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return write_snapshot(albums, self.workspace / self.LIST_REL, taken=taken,
                              origin=Path(path).name, sha256=sha, skipped=skipped)
