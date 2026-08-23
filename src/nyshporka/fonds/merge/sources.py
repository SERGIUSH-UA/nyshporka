"""📚 Джерела реєстру опису: що читаємо й наскільки кожному віримо.

🔴 Ранг — політика довіри, спільна для всіх архівів, і тому вона в КОДІ, а не в
паку. Три причини. Ранг нерозривний із переліком джерел — розвести їх по коду й
даних означає створити два місця, які мусять збігатися, а розходяться мовчки.
Цінне тут не числа, а обґрунтування під кожним, і YAML його не перевіряє. І
головне: чужий пак, що підняв ранг, дав би ІНШІ заголовки в тих самих рядках —
без жодної ознаки в реєстрі, бо `title_src` чесно назве джерело, а не політику,
яка його обрала.

Потреба «іншої політики» задовольняється не гвинтиком, а НОВИМ іменованим
джерелом зі своїм рангом і своїм обґрунтуванням — саме так з'явилось `manual`.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    """Джерело реєстру. `rank=None` — позарангове: заповнює свої поля, але за
    заголовок не змагається."""

    name: str
    filename: str = ""
    glob: str = ""
    glob_skip: str = ""
    rank: int | None = None
    why: str = ""


#: 🔴 Ранг заголовка: більше — сильніше.
SOURCES: tuple[Source, ...] = (
    # 👁 Опис, прочитаний ОКОМ зі скану самого опису. Найсильніший не через
    # довіру до ока, а тому що це ТОЙ САМИЙ документ без посередника: решта
    # текстових джерел — чужі транскрипції тієї ж таблиці.
    # ⚠ Ціна рангу: помилка ока тут переважить усі машинні джерела, тож єдиний
    # приймач цього джерела — `src_note` з адресою прочитання.
    Source("manual", "manual.tsv", rank=70,
           why="опис, прочитаний оком зі скану"),
    # 🏛 Опис на сайті САМОГО архіву: та сама таблиця, але без посередника й без
    # обрізання. Єдине джерело адреси посторінкових кадрів.
    Source("archium", "archium.tsv", rank=65,
           why="опис на сайті архіву + адреса кадрів"),
    Source("wikisource", "wikisource.tsv", rank=60,
           why="транскрипція таблиці опису"),
    # 📕 ДРУКОВАНИЙ каталог архіву — єдине джерело про те, що існує В ПРИРОДІ
    # (решта описує лише вже оцифроване), і єдине, яке називає ПАРАФІЮ.
    Source("catalog", "catalog2012.tsv", rank=58,
           why="друкований каталог архіву: парафія й тип запису"),
    # 🔴 Знімок попереднього реєстру. Без нього дані джерела, якого зараз немає
    # під рукою, ЗНИКАЛИ б із кожною перезбіркою — реєстр будується з нуля.
    Source("legacy", "legacy.tsv", rank=55,
           why="знімок попереднього реєстру"),
    Source("ukrfamily", "ukrfamily.tsv", rank=50,
           why="чужа транскрипція опису"),
    # 🦆 Зведений покажчик. Навмисно НИЖЧЕ за всі людські транскрипції: це копія
    # тих самих описів через посередника. Цінний переліком, не заголовком.
    Source("duck", "duck.tsv", rank=45,
           why="зведений покажчик: перелік справ фонду"),
    # OCR друкованого опису: єдине джерело номера тому й сторінки прочитання.
    Source("ocr", glob="ocr_opys*.tsv", glob_skip="_pages.tsv", rank=30,
           why="OCR таблиці опису"),
    # 🎞 Найповніший перелік ІСНУЮЧИХ справ там, де опису немає зовсім
    # (ф.315: 12 812 проти 1 440 у текстових джерелах).
    Source("fs", "fs.tsv", rank=20,
           why="плівки: DGS, кадри, місце"),

    # ── позарангові: заповнюють свої поля, за заголовок не змагаються ────────
    Source("commons", "commons.tsv", why="скани: обсяг і склад файлів"),
    Source("mirror", "mirror.tsv", why="дзеркало сканів"),
    Source("covers", "covers.tsv", why="обкладинка, прочитана оком"),
    Source("alfavitka", "alfavitka.tsv", why="прізвища роду за алфавіткою архіву"),
)

#: 🔴 Порядок обробки текстових джерел: СЛАБКІ → СИЛЬНІ. Він несе байти —
#: черга розбіжностей будується в цьому ж порядку, тож будь-яка перестановка
#: змінить її вміст. Ніколи не `set` і не порядок словника.
TEXT_ORDER: tuple[str, ...] = ("fs", "ocr", "duck", "catalog", "ukrfamily",
                               "legacy", "wikisource", "archium", "manual")

TITLE_RANK: dict[str, int] = {s.name: s.rank for s in SOURCES if s.rank is not None}

#: Порядок і склад колонок вихідного реєстру. Власним кортежем, а не похідним
#: від переліку читалки: там інший порядок, і файл мусить лишитись тим самим.
COLUMNS: tuple[str, ...] = (
    "opys", "spr_int", "spr_letter", "title", "title_src", "title_alt",
    "year_from", "year_to", "years_src", "folios", "folios_src", "dv_no",
    "commons_title", "commons_url", "commons_size", "commons_pages",
    "commons_files", "commons_kind", "commons_size_max", "commons_parts",
    "mirror_url", "mirror_size", "truncated_mirror", "on_disk",
    "src_page", "page_quality", "num_src", "surnames",
    "cover_place", "cover_letters", "cover_note",
    "cat_place", "cat_attached", "cat_uezd", "cat_confession", "cat_district",
    "cat_parishes_n", "record_types",
    "fs_dgs", "fs_film", "fs_url", "fs_record_type", "fs_place", "fs_frames",
    "archium_file", "archium_url",
    "duck_url", "duck_online", "duck_copy_url",
    "sources")


@dataclass
class SourceBook:
    """Усе прочитане з теки джерел. Порожнє джерело лишається в переліку.

    🔴 «Джерела не було» і «джерело дало нуль» — різні відповіді, і плутати їх
    означає ховати прогалину: реєстр, зібраний без алфавітки, виглядав би так
    само, як зібраний з порожньою.
    """

    rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    library: list[dict[str, Any]] = field(default_factory=list)
    has_library: bool = False

    def counts(self) -> tuple[tuple[str, int], ...]:
        return tuple((s.name, len(self.rows.get(s.name, ()))) for s in SOURCES)


def read_tsv(path: Path) -> list[dict[str, str]]:
    """Рядки TSV; немає файла — порожньо, і це не помилка."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh, delimiter="\t")]


def read_book(reg_dir: Path, library: Path | None = None) -> SourceBook:
    """Прочитати всі джерела фонду."""
    import json

    book = SourceBook()
    for s in SOURCES:
        if s.glob:
            # ⚠ Сортування навмисне: від нього залежить, який OCR-рядок виграє
            # правило «перше непорожнє».
            rows: list[dict[str, str]] = []
            for p in sorted(reg_dir.glob(s.glob)):
                if s.glob_skip and s.glob_skip in p.name:
                    continue
                rows.extend(read_tsv(p))
            book.rows[s.name] = rows
        else:
            book.rows[s.name] = read_tsv(reg_dir / s.filename)

    if library is not None and library.is_file():
        try:
            book.library = json.loads(library.read_text(encoding="utf-8")).get("cases") or []
            book.has_library = True
        except (OSError, ValueError):
            book.library = []
    return book


def blank_row(key: tuple[str, str, str]) -> dict[str, Any]:
    """Порожній рядок реєстру — УСІ поля одразу.

    🔴 Раніше два поля (`truncated_mirror`, `on_disk`) створювались лише в
    циклі дзеркала, а джерела, що додають справи ПІСЛЯ нього (обкладинки),
    лишали рядок без них — і друк підсумків падав на фонді, де в обкладинках є
    справа, якої немає в жодному текстовому джерелі. На наявних даних таких
    нуль, тобто вада чекала на дані, яких ще не було.
    """
    row: dict[str, Any] = {c: "" for c in COLUMNS}
    row["opys"], row["spr_int"], row["spr_letter"] = key
    row["title_alt"] = []
    row["surnames"] = []
    row["src"] = set()
    return row
