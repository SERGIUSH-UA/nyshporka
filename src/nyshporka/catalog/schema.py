"""🗂 Схема паків каталогу — довідкових даних, які їдуть у комплекті.

Пак — це **незмінний файл SQLite з одним зрізом одного джерела**: газетир ЦДІАК,
опис одного фонду, поаркушевий покажчик плівок. Не одна база на все і не вічний
файл, який дописують.

🔴 **Чому пак на фонд, а не одна `opys.sqlite`.** Зріз кожного фонду має свою
дату: ф.315 зібраний у березні і ф.230 зібраний учора — це два різні твердження
про світ. В одному файлі спільна дата зрізу була б брехнею для одного з них, а
дата зрізу тут не декорація: саме нею вимірюється, чого відповідь не покриває.
Плюс покриття мусить бути видним пофондово — «вашого ф.196 тут немає» це
відповідь, а порожній список ні.

🔴 **`on_disk` у пак не їде ніколи.** У зведеному TSV реєстру опису є колонка
«на диску» — але вона описує диск дослідника на момент злиття. Правило жорстке:

    пак несе лише те, що існує в архіві;
    що лежить на диску, каже бібліотека (`fonds.registry.live_on_disk`).

Інакше кожен користувач отримав би чужий стан диска як факт про архів, а
позначка «реєстр розходиться з бібліотекою» перестала б щось означати.

## FTS5 — за формою запиту, а не за таблицею

| таблиця | токенізатор | чому |
|---|---|---|
| `places` | `trigram` | назва села коротка, а питають її трьома способами: префікс («Мяст»), інфікс («ястків») і фаззі. Триграма покриває всі три Й прискорює `LIKE '%…%'` — тобто рівно те, що зараз робиться повним сканом 4566 рядків |
| `alfavitka` | `trigram` | прізвище набирають цілком, але воно скалічене OCR |
| `opys.cases` | `unicode61` + `prefix` | заголовок справи набирають словами. Триграма роздула б індекс у 3-5 разів від тексту заради можливості, якою не користуються |
| `geog.cases` | **немає** | вільного тексту в рядку немає: `doc_type` — закритий словник, `parish` дублює назву з `places`. FTS по 348 408 рядках коштувала б мегабайти й не відповідала б на жодне питання |

🔑 **Колонка `translit`** рахується на збірці пака: `normalize_for_matching`
української назви плюс російської. Саме вона робить `Miastkowka` → `miastkovka`
знаходженим через `MATCH`, а не повним сканом із `rapidfuzz`.
"""
from __future__ import annotations

import sqlite3

#: Версія схеми паків. Читач звіряє її й відмовляється працювати з чужою:
#: мовчазна робота на незнайомій схемі дала б неповні відповіді, а не помилку.
SCHEMA_VERSION = 1

#: Сторінка 8 КБ: рядки тут короткі й численні, і на 4 КБ база помітно більша.
_PRAGMA = "PRAGMA page_size=8192;"

#: Спільне для кожного пака — тут живе «нуль мусить щось означати».
_COMMON = """
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE coverage_scope (
    dim   TEXT NOT NULL,   -- 'opys' | 'section' | 'fond' | 'region'
    value TEXT NOT NULL,
    n     INTEGER,         -- скільки маємо
    denom INTEGER,         -- скільки має бути (NULL = невідомо, і це чесно)
    note  TEXT
);
"""

GEOG = _PRAGMA + _COMMON + """
CREATE TABLE places (
    card TEXT PRIMARY KEY, section TEXT, institution TEXT,
    village_uk TEXT, village_ru TEXT,
    hist_place TEXT, uezd_gub TEXT, modern_place TEXT, church TEXT,
    eparchy TEXT, parishes TEXT, note TEXT,
    norm_uk TEXT, norm_ru TEXT,
    translit TEXT,
    n_cases INTEGER DEFAULT 0
);
CREATE INDEX ix_places_uk  ON places(norm_uk);
CREATE INDEX ix_places_ru  ON places(norm_ru);
CREATE INDEX ix_places_tr  ON places(translit);
CREATE INDEX ix_places_sec ON places(section);

-- 🔴 Словники, а не повторювані рядки. `doc_type` має близько двох десятків
-- значень на 348 408 рядків, `parish` дублює назви з `places`; у сирому вигляді
-- вони й давали більшу частину 62 МБ. Саме ця економія й оплачує FTS.
CREATE TABLE doc_types (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE parishes  (id INTEGER PRIMARY KEY, name TEXT UNIQUE);

CREATE TABLE cases (
    card TEXT NOT NULL, fond TEXT, opys TEXT,
    spr TEXT, spr_int INTEGER,
    year_from INTEGER, year_to INTEGER,
    doc_type_id INTEGER, parish_id INTEGER
);
CREATE INDEX ix_cases_card ON cases(card);
CREATE INDEX ix_cases_fond ON cases(fond, opys, spr_int);

-- 🔴 FTS тут немає, і це рішення за виміром, а не за замовчуванням.
--
-- План передбачав `places_fts` (триграма) для двох задач, і жодна не вийшла:
--   • **конфузери** — двоступеневий відбір розійшовся зі старим результатом на
--     2362 картках із 4566, у 1348 конфузерів було втрачено: `fuzz.ratio`
--     набирає 78 і на розсіяних збігах, без спільного тризнакового шматка;
--   • **латинський пошук** — `LIMIT` без ранжування обрізав кандидатів
--     довільно, і `Miastkowka` віддавала нуль при збігу 94.7 з «Мястковка».
--
-- Причина спільна: **таблиця замала**. 4566 рядків повний скан із `rapidfuzz`
-- проходить за десятки мілісекунд — стільки ж, скільки коштував би FTS-шлях,
-- але без ризику тихо вкоротити відповідь. Індекс важив 2-3 МБ у кожного
-- користувача й не заробляв нічого.
--
-- ⚠ Підстава повернеться, якщо газетир виросте на порядок. Це «прибрано за
-- відсутністю користі», а не «визнано непридатним назавжди».
"""

OPYS = _PRAGMA + _COMMON + """
CREATE TABLE cases (
    opys TEXT, spr_int INTEGER, spr_letter TEXT, spr TEXT, shifra TEXT,
    title TEXT, title_norm TEXT, title_src TEXT, title_alt TEXT,
    commons_title TEXT,
    year_from INTEGER, year_to INTEGER, years_src TEXT,
    folios TEXT, folios_src TEXT, dv_no TEXT,
    uezd TEXT,                       -- матеріалізовано на збірці, не regex у запиті
    -- commons_size/pages — сума всіх файлів справи (їх буває кілька: томи
    -- «Частина 1..3» або витяг однієї парафії поруч із повним томом);
    -- commons_size_max — найбільший файл, за ним міряють обрізаність дзеркала
    commons_url TEXT, commons_size INTEGER, commons_pages INTEGER,
    commons_files INTEGER, commons_kind TEXT,
    commons_size_max INTEGER, commons_parts TEXT,
    mirror_url TEXT, mirror_size INTEGER, truncated_mirror INTEGER,
    src_page TEXT, page_quality TEXT, num_src TEXT, surnames TEXT,
    cover_place TEXT, cover_letters TEXT, cover_note TEXT,
    fs_dgs TEXT, fs_film TEXT, fs_url TEXT, fs_record_type TEXT,
    fs_place TEXT, fs_frames INTEGER,
    sources TEXT,
    PRIMARY KEY (opys, spr_int, spr_letter)
);
CREATE INDEX ix_opys_year ON cases(year_from, year_to);
CREATE INDEX ix_opys_film ON cases(fs_film);
CREATE INDEX ix_opys_uezd ON cases(uezd);

CREATE TABLE alfavitka (
    surname TEXT, surname_norm TEXT, opys TEXT, spr TEXT, note TEXT
);
CREATE INDEX ix_alf_norm ON alfavitka(surname_norm);

CREATE TABLE conflicts (
    opys TEXT, spr TEXT, field TEXT, a TEXT, b TEXT, note TEXT
);

-- 🔴 FTS тут теж немає, і причина інша, ніж у газетира: не «замало користі», а
-- **інша семантика пошуку**.
--
-- Фільтр `q` у реєстрі опису — це пошук підрядка (`fonds.registry.filter_rows`:
-- `if ql not in hay.lower()`). FTS5 з `unicode61` шукає словами й префіксами.
-- Це не швидший спосіб зробити те саме, а інший спосіб зробити інше: фрагмент
-- «ястків» сьогодні знаходить «М'ястківку», а через FTS не знайшов би.
--
-- Тобто заміна виглядала б як оптимізація, а була б тихою зміною того, які
-- справи знаходяться. Ціна відмови мала: 12 824 рядки скануються за ~20 мс, і
-- результат уже кешується за штампом файла.
"""

#: Домен → DDL. Ключ домену входить в ім'я пака: `geog-cdiak-2026.08.sqlite`.
DDL: dict[str, str] = {"geog": GEOG, "opys": OPYS}


def apply(con: sqlite3.Connection, domain: str) -> None:
    """Створити схему домену в порожній базі."""
    ddl = DDL.get(domain)
    if ddl is None:
        raise ValueError(f"невідомий домен пака: {domain!r}; є: {', '.join(DDL)}")
    con.executescript(ddl)


def check(con: sqlite3.Connection, domain: str) -> str:
    """Порожньо, якщо пак придатний; інакше — чому ні.

    Відмова, а не мовчазна робота: пак чужої схеми віддав би неповний набір
    колонок, тобто відповідь із дірками, яку ніхто не відрізнить від повної.
    """
    try:
        row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    except sqlite3.Error as exc:
        return f"не читається як пак каталогу ({exc})"
    if row is None:
        return "у паку немає версії схеми"
    try:
        got = int(row[0])
    except (TypeError, ValueError):
        return f"версія схеми не число: {row[0]!r}"
    if got != SCHEMA_VERSION:
        return (f"пак схеми v{got}, а застосунок знає v{SCHEMA_VERSION} — "
                f"оновіть каталог: nysh catalog update")
    try:
        dom = con.execute("SELECT v FROM meta WHERE k='domain'").fetchone()
    except sqlite3.Error:
        dom = None
    if dom is not None and str(dom[0]) != domain:
        return f"це пак домену «{dom[0]}», а не «{domain}»"
    return ""
