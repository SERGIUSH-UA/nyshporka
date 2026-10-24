"""🗄 Текстовий стор: усе прочитане в одному файлі SQLite, з тригамним індексом.

## Навіщо

Пошук по декоду платив не за текст, а за файли. Заміряно 07.09.2026 на
приватному корпусі (1452 прогони, 582 тис. сторінок, понад мільйон дрібних
файлів на NTFS): `rg` по теці прогонів — 7–41 хв, одноразовий python по всіх
`*.txt` — 7 хв 38 с, свіп по gzip-індексу — хвилина, з якої 52 с іде на
розпакування. Ліміт командного рядка в 120 с перетворював це на роботу у фоні
й опитування `sleep`. Ворог — обхід дерева, і жоден швидший regex його не лікує.

Тут дерево обходиться ОДИН раз, при індексації. Далі кожне питання до тексту —
запит до одного файлу: без `glob`, без відкриття тисяч файлів, без розпакування
корпусу заради одного прізвища.

## Що лежить

`data/derived/text_store.sqlite`:

* `runs` — прогін, його штамп свіжості, ключ справи, модель;
* `pages` — сторінка прогону з СИРИМ текстом (zlib), щоб контекст, регекс і
  картка справи не торкались диска з кадрами;
* `lines` — рядок: токени як у тексті (кирилиця лишається кирилицею) плюс рамка
  з `.lines.json`, коли прогін її записав;
* `fts` — FTS5 з тригамами по НОРМАЛІЗОВАНОМУ рядку, без вмісту: лише індекс;
* `pages.cands` — ГОТОВІ кандидати кожного рядка сторінки (норми одиночних
  слів, пар, трійок, склейок через рядок і через колонку), zlib. Це те, що
  тримав gzip-індекс, і саме тому він зіставляв за секунду: породити
  кандидати наново в Python для 700 тис. рядків коштувало 190 с на запит.

🔴 Rowid рядка = `сторінка × 4096 + номер рядка`. Це не оптимізація, а спосіб
не тримати таблицю на двадцять мільйонів рядків заради зв'язку «рядок →
сторінка»: сторінка й номер відновлюються двома діленнями.

🔴 Кожен нормалізований рядок обрамлений маркерами `|`: «| ivan kovals |».
Перенесене прізвище лишає на рядку лише свій початок — і саме В КІНЦІ рядка.
Фраза «doli |» знаходить такі хвости, не тягнучи за собою кожне «Долина» посеред
тексту: заміряно, що префікс без маркера дає 150 тис. зайвих рядків на корпус.

🔴 Норма — у індексі, сире — у рядку, і це навмисно. `normalize_archival`
транслітерує в латиницю, і пошук кириличного кореня в нормі дає завжди нуль
(так уже закривали напрям, у якому рід був). Тому стем шукається в `fts`, а
регекс людини — у `lines.toks`, де стоїть те, що прочитав рушій.

## Як шукає

Тригамний індекс не рахує схожості. Він відповідає на одне питання: у яких
рядках є такий-от підрядок. Тому пошук іде в два кроки: FTS звужує корпус до
рядків, що містять хоч один k-грам стема, далі rapidfuzz судить кандидатів
цих рядків тими самими правилами, що й досі (`htr_store.page_candidates` +
`decode._matches`). Довжину k підбирає довжина стема: для повної форми
прізвища п'ять літер, для короткого кореня — три.

Заміряно на ф.904 (84 прогони, 32 тис. сторінок, 68 сторінок зі згадками роду,
які нинішній канал бачить із балом ≥ 78): передфільтр 5-грамами лишає 0.9%
рядків за 53 мс і не губить ЖОДНОЇ сторінки зі згадкою повної форми. Губляться
лише форми ІНШОГО прізвища з тим самим коренем — не через фільтр, а тому, що
вони не є формою стема.

🔴 Стор — похідне. Його можна видалити будь-коли: наступна індексація збере
його наново з прогонів. Тому він у `data/derived`, а не поруч із доказами.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import inspect
import io
import itertools
import json
import os
import re
import sqlite3
import sys
import time
import tokenize
import zlib
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

FILE = "text_store.sqlite"
#: Маркер краю рядка в нормалізованому тексті індексу.
MARK = "|"
#: Версія схеми. Змінилась розкладка — старий файл перебудовується цілком.
SCHEMA = 3
#: Скільки рядків на сторінку вміщує rowid. Kraken на розвороті дає до ~300.
LINE_BITS = 12
MAX_LINES = (1 << LINE_BITS) - 1

#: Довжина k-грама передфільтра за довжиною стема.
#:
#: 🔴 Чотири, а не п'ять, для повних форм — куплено пропуском. Пари 5-грам
#: губили «dalicinskago» (96 балів, справжня згадка): пропуск однієї літери
#: зсуває всі 5-грами, і спільною лишається одна. Пари 4-грам із розривом ≥ 3
#: її ловлять («dali» + «cins») і при цьому дають МЕНШЕ рядків на корпус
#: (99 тис. проти 184 тис.), бо розрив вимагає двох далеких доказів.
#: Короткий корінь («kovals», 6 літер) лишається на тригамах.
def kgram_len(stem: str) -> int:
    return 4 if len(stem) >= 8 else 3


#: Скільки SQLite сам чекає чужий замок на запис, перш ніж відповісти «locked».
BUSY_TIMEOUT = 60.0
#: Скільки індексація одного прогону чекає стор, зайнятий іншою сесією
#: (`optimize` на 37 ГБ, перебудова), перш ніж здатися. Доти не чекала зовсім:
#: прогін мовчки йшов у `LOCKED_SKIPPED`, і справа після хмарного прогону
#: лишалась поза пошуком (24.09.2026 — дві справи).
INDEX_WAIT_SEC = 1800.0
#: Що каже поступ, поки прогін чекає чужого запису.
PHASE_WAIT = "чекаю стор: пише інша сесія"

#: Мінімальний розрив між двома грамами пари: далекі докази, не сусідні.
PAIR_GAP = 2
#: Стільки прогонів — «суттєва збірка», після якої варто злити сегменти FTS.
OPTIMIZE_MIN = 50
#: До скількох сторінок в області передфільтр бере ГОЛІ триграми. Заміряно
#: 08.09 на 36 прогонах (7.4 тис. стор.): триграми — 40 термів, 6 с, пропущено
#: 2 з 5376 хітів gzip; пари грам — 326 термів, 37 с, пропущено 341. На корпусі
#: триграми тягнуть 9.4 млн рядків, тож там лишаються пари.
TRIGRAM_SCOPE_PAGES = 60_000
#: Від якої довжини стема доказом є лише ПАРА грам. Коротшим вистачає одної:
#: заміряно, що пари губили «kovlskii», «fedor», «ivnova» (91–94 бали).
PAIR_MIN_LEN = 11


def path() -> Path:
    from nyshporka.core.workspace import workspace

    ws = workspace()
    return (ws.text_store_dir or ws.derived) / FILE


# ── схема ────────────────────────────────────────────────────────────────────
_DDL = """
create table if not exists meta(key text primary key, value text);
create table if not exists runs(
    id integer primary key, run text unique not null, stamp text not null,
    case_key text default '', case_dir text default '', model text default '',
    script text default '', engine_ids text default '[]',
    pages int default 0, lines int default 0, geo int default 0,
    indexed_at text default '', rules text default '');
create table if not exists pages(
    id integer primary key, run_id int not null, page text not null,
    stem text not null, nlines int default 0, geo int default 0, raw blob,
    cands blob);
create index if not exists pages_run on pages(run_id, stem);
create table if not exists lines(
    id integer primary key, toks text not null,
    x0 int, y0 int, x1 int, y1 int, succ int);
create virtual table if not exists fts using fts5(
    norm, content='', tokenize='trigram', contentless_delete=1);
create table if not exists sweeps(
    run_id int not null, key text not null, body blob, primary key(run_id, key));
"""


def connect(*, readonly: bool = False, migrate: bool = False,
            any_thread: bool = False) -> sqlite3.Connection:
    """З'єднання зі стором. Схема створюється при першому відкритті.

    🔴 WAL, бо стор читають під час індексації: пошук з іншої вкладки або
    агент не мусять чекати, поки збірка дійде до кінця корпусу.

    🔴 Стор чужої схеми ЗНОСИТЬ лише `migrate=True`, тобто явна збірка. Доти
    будь-який читач, що відкривав стор на запис (`is_fresh` з каналу якорів),
    після оновлення пакета мовчки дропав 6.5 ГБ (рецензія 08.09). Тепер
    невідповідність — помилка з підказкою, а не дія.

    `any_thread` — з'єднання відкриває потік-читач, а закриває викликач.
    """
    p = path()
    if readonly and not p.is_file():
        raise FileNotFoundError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=BUSY_TIMEOUT, check_same_thread=not any_thread)
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma synchronous=normal")
    # Потік-читач бере кожну сторінку один раз, і кеш йому ні до чого, а
    # 100 МБ на кожне з восьми з'єднань у кожному воркері свіпу — це гігабайти
    # (рецензія 20.10.2026).
    conn.execute(f"pragma cache_size={-8000 if any_thread else -100000}")
    if not readonly:
        _ensure_schema(conn, migrate=migrate)
    else:
        row = None
        with contextlib.suppress(sqlite3.Error):
            row = conn.execute("select value from meta where key='schema'").fetchone()
        if row is not None and int(row[0]) != SCHEMA:
            conn.close()
            raise RuntimeError(f"стор зібрано схемою {row[0]}, чинна {SCHEMA} — "
                               f"перебудувати: nysh text index --rebuild")
    return conn


def _add_run_rules_column(conn: sqlite3.Connection) -> None:
    """Відбиток правил на КОЖНОМУ прогоні, а не один на весь стор.

    🔴 Стало причиною тихої брехні 08.09.2026. `ensure_all(force, reset_rules)`
    стирала єдиний рядок `meta.rules`, і перший же переіндексований прогін
    ставив туди НОВИЙ відбиток — після чого стор рапортував «правила
    збігаються», хоч решта 1327 прогонів ще тримала старих кандидатів.
    Перебудову на 6.8 ГБ убило браком пам'яті посеред, і `nysh text state`
    показав «1328 із 1328 · застаріло 0» на сторі, де 234 прогони були
    зібрані іншим правилом склейки. Знайшлось це лише прямою звіркою блобів.

    Міграція нічого не вигадує: наявним рядкам ставиться той відбиток, який
    стор і так про себе заявляв. Це не робить їх доведено свіжими — це рівно
    та сама (слабша) заява, перенесена на рівень, де її видно поштучно.
    """
    have = {r[1] for r in conn.execute("pragma table_info(runs)")}
    if "rules" in have:
        return
    conn.execute("alter table runs add column rules text default ''")
    row = conn.execute("select value from meta where key='rules'").fetchone()
    if row:
        conn.execute("update runs set rules=?", (row[0],))
    conn.commit()


def _add_run_shared_column(conn: sqlite3.Connection) -> None:
    """Чий це прогін: порожньо — свій, інакше ім'я того, хто поділився.

    🔴 Міграцією, а не підняттям `SCHEMA`. Бамп версії зносить стор цілком і
    змушує перебирати прогони наново — на цій машині це 8 ГБ і години — заради
    одного порожнього поля, яке доіснуючим рядкам однаково нічого не дасть.
    Зразок узято з `_add_run_rules_column`: додати колонку, лишити наявним
    рядкам їхню (слабшу) заяву про себе.

    🔴 Навіщо взагалі в сторі: пошук зобов'язаний називати знаменник, а «не
    знайшлось на 3770 сторінках» звучить однаково на своєму декоді й на
    чужому — при тому, що чужий читала інша модель і відповідати за нього
    ніхто тут не може.
    """
    have = {r[1] for r in conn.execute("pragma table_info(runs)")}
    if "shared" in have:
        return
    conn.execute("alter table runs add column shared text default ''")
    conn.commit()


def _ensure_schema(conn: sqlite3.Connection, *, migrate: bool = False) -> None:
    conn.executescript(_DDL)
    with contextlib.suppress(sqlite3.Error):
        _add_run_rules_column(conn)
    with contextlib.suppress(sqlite3.Error):
        _add_run_shared_column(conn)
    row = conn.execute("select value from meta where key='schema'").fetchone()
    if row is None:
        conn.execute("insert into meta(key,value) values('schema',?)", (str(SCHEMA),))
        conn.commit()
    elif int(row[0]) != SCHEMA and not migrate:
        conn.close()
        raise RuntimeError(f"стор зібрано схемою {row[0]}, чинна {SCHEMA} — "
                           f"перебудувати: nysh text index --rebuild")
    elif int(row[0]) != SCHEMA:
        # Розкладка інша — перебудова цілком. Індекси попередньої схеми не
        # мають нічого, що варто рятувати: усе відтворюється з прогонів.
        conn.executescript("drop table if exists fts; drop table if exists lines;"
                           "drop table if exists pages; drop table if exists runs;"
                           "delete from meta;")
        conn.executescript(_DDL)
        conn.execute("insert into meta(key,value) values('schema',?)", (str(SCHEMA),))
        conn.commit()


def exists() -> bool:
    return path().is_file()


def _code_text(fn: Callable[..., Any]) -> str:
    """Текст функції без коментарів і порожніх рядків — тіло відбитка правил.

    🔴 Не `ast.dump`: його вивід залежить від версії Python (поля вузлів
    міняються між мінорними), і той самий код у venv на 3.12 і 3.13 давав два
    різні відбитки. Заміряно 07.10.2026: стор показував «3346 прогонів зібрані
    ІНШИМ правилом склейки» при тотожному коді, бо наглядач хмари індексує під
    3.12, а venv проєкту дослідження — під 3.13. Коментар tokenize знаходить однаково в усіх
    версіях, тож правка коментаря, як і раніше, перебудови не вимагає.
    """
    src = inspect.getsource(fn)
    lines = src.splitlines()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(ln.rstrip() for ln in lines if ln.strip())


@functools.lru_cache(maxsize=1)
def rules_hash() -> str:
    """Відбиток правил, з яких зроблені кандидати в блобах.

    🔴 Приймач для `pages.cands`: правила склейки (`page_candidates`),
    нормалізація й геометричні константи можуть змінитись без зміни `SCHEMA`,
    і стор тоді мовчки тримав би старих кандидатів під свіжими штампами.

    🪤 Рахується РАЗ НА ПРОЦЕС, і це не оптимізація. `inspect.getsource` бере
    текст із файла НА ДИСКУ за номерами рядків код-об'єкта: якщо модуль
    правлять, поки триває довга індексація, ті самі функції нарізаються по
    зсунутих рядках і відбиток міняється посеред заходу. Заміряно 08.09.2026 —
    доіндексація 234 прогонів проставила їм відбиток, якого немає в жодної
    версії коду, і стор виглядав змішаним при тотожних кандидатах.
    """
    from nyshporka import htr_store as S
    from nyshporka.utils import translit as T

    parts: list[str] = []
    # `page_candidates` тепер вьюха — правила живуть у повній версії, і саме
    # її зміна мусить робити кандидатів застарілими.
    for fn in (S.page_candidates_full, T.normalize_archival, successors, _geo_cands):
        try:
            # Без коментарів: правка коментаря не має вимагати перебудови.
            parts.append(_code_text(fn))
        except (OSError, TypeError, SyntaxError, tokenize.TokenError):
            parts.append(f"{fn.__module__}.{fn.__name__}")
    parts += [str(S.LINE_BREAK_WINDOW), str(COL_GAP), str(SUCC_REACH), str(MARK)]
    # 🔴 Префікс версії САМОГО відбитка. Спосіб рахувати (джерело → AST)
    # змінився в минулому коміті, і живий стор на 6.5 ГБ став «застарілим за
    # правилами» без жодної зміни правил (рецензія 08.09, третій раунд). Зміна
    # способу тепер видима як така, а дослідник приймає відбиток без
    # перебудови: `nysh text index --accept-rules`. v3 — текст без коментарів
    # замість `ast.dump`, що залежав від версії Python (див. `_code_text`).
    return "v3:" + hashlib.blake2b("\n".join(parts).encode("utf-8"), digest_size=8).hexdigest()


def rules_stale(conn: sqlite3.Connection) -> bool:
    """Чи кандидати стору зроблені іншими правилами, ніж чинні."""
    row = conn.execute("select value from meta where key='rules'").fetchone()
    return bool(row) and row[0] != rules_hash()


def runs_of_other_rules(conn: sqlite3.Connection) -> list[str]:
    """Прогони, чиї кандидати зроблені НЕ чинним правилом склейки.

    🔴 Головна відмінність від `rules_stale`: там одна відповідь на весь стор,
    тут — поштучно. Перебудова, яку вбили посеред, лишає стор змішаним, і
    єдиний спільний відбиток тоді бреше на користь свіжості: він уже новий,
    бо його поставив перший переіндексований прогін.
    """
    h = rules_hash()
    try:
        return [r[0] for r in conn.execute(
            "select run from runs where coalesce(rules,'') <> ? order by run", (h,))]
    except sqlite3.Error:
        return []


def accept_rules() -> str:
    """Записати чинний відбиток правил як той, яким зібрано стор.

    Рішення дослідника, не автоматика: кажеться лише тоді, коли правила
    склейки насправді не мінялись (змінився спосіб їх рахувати), інакше
    кандидати в блобах лишаться старими під свіжим відбитком.
    """
    h = rules_hash()
    conn = connect()
    try:
        conn.execute("insert or replace into meta(key,value) values('rules',?)", (h,))
        # Заява стосується ВСІХ прогонів разом, тож і ставиться на всі: інакше
        # поштучний облік показував би незгоду там, де дослідник її щойно зняв.
        with contextlib.suppress(sqlite3.Error):
            conn.execute("update runs set rules=?", (h,))
        conn.commit()
    finally:
        conn.close()
    return h


# ── свіжість ─────────────────────────────────────────────────────────────────
def stamp_of(run: str) -> str:
    """Той самий штамп, що й у gzip-індексу: мета + тека, без обходу."""
    from nyshporka.search import decode as D

    return D.stamp_of(run)


def stamps_for(runs: list[str]) -> dict[str, str]:
    """`stamp_of` для багатьох прогонів: від `BULK_RUNS` — одним переліком кореня.

    🔴 Свіп по корпусу питав штамп кожного з 16 тис. прогонів по три `stat`,
    і не раз: свіжість, знаменник, ще раз після доіндексації — ~5 с послідовно
    перед кожним корпусним пошуком (замір 22.10.2026). Штамп той самий до байта
    (`decode.stamps_of`).
    """
    from nyshporka.search import decode as D

    if len(runs) >= BULK_RUNS:
        return D.stamps_of(runs)
    return {r: stamp_of(r) for r in runs}


#: Штампи прогонів на один захід — див. `one_stamps`.
_STAMPS: ContextVar[dict[str, Any] | None] = ContextVar("store_stamps", default=None)


@contextlib.contextmanager
def one_stamps() -> Iterator[None]:
    """Одне читання штампів стору на захід, доки захід сам нічого не пише.

    🔴 Пошук по серії питав усі штампи стору тричі на справу (свіп, знаменник,
    свіжість) — 3 с на 40 справ (замір 19.10.2026). Будь-який запис у стор
    (`_begin_write`) знімок скидає: прогін, доіндексований посеред заходу,
    видно одразу.
    """
    if _STAMPS.get() is not None:
        yield
        return
    tok = _STAMPS.set({})
    try:
        yield
    finally:
        _STAMPS.reset(tok)


def stamps(conn: sqlite3.Connection) -> dict[str, str]:
    snap = _STAMPS.get()
    if snap is not None and "v" in snap:
        return dict(snap["v"])
    got = {r[0]: r[1] for r in conn.execute("select run, stamp from runs")}
    if snap is not None:
        snap["v"] = got
        return dict(got)
    return got


def is_fresh(run: str, conn: sqlite3.Connection | None = None) -> bool:
    st = stamp_of(run)
    if not st:
        return False
    own = conn is None
    if own and not path().is_file():
        return False
    try:
        c = conn or connect(readonly=True)
    except RuntimeError:
        # Стор чужої схеми: для читача це «не свіжий», а не падіння —
        # канал якорів ішов би далі файлами, як і пошук.
        return False
    try:
        row = c.execute("select stamp from runs where run=?", (run,)).fetchone()
    finally:
        if own:
            c.close()
    return bool(row) and row[0] == st


# ── індексація ───────────────────────────────────────────────────────────────
_TOKEN_RE: re.Pattern[str] | None = None


def _tokens(s: str) -> list[str]:
    from nyshporka import htr_store as S

    return S._TOKEN_RE.findall(s)


def _norm(s: str) -> str:
    from nyshporka import htr_store as S

    return S._norm(s)


def _geometry_for(run_dir: Path, run: str, stem: str, nlines: int,
                  meta: dict[str, Any] | None = None) -> list[list[int]] | None:
    """Рамки рядків сторінки: свої, а як їх немає — з прогону-побратима.

    🔴 Голос Дяка не пише `.lines.json` — він читає ті самі рядки тією самою
    сегментацією, що й основний прогін, тож рамки в нього ТІ САМІ. Без цього
    другий голос лишався б без геометрії, а з нею у стора склейка за колонкою.
    Береться лише при збігу кількості рядків: інакше це інша нарізка.
    """
    own = run_dir / f"{stem}.lines.json"
    cands = [own]
    if "-" in run:
        base = run_dir.parent / run.rsplit("-", 1)[0]
        # 🔴 Побратим — лише прогін ТІЄЇ САМОЇ справи. Обрізання імені по
        # останньому дефісу з «met1863-904-25» давало «met1863-904» — іншу
        # справу, чиї рамки на коротких сторінках збігались числом рядків.
        if base.is_dir() and _same_case(meta, base):
            cands.append(base / f"{stem}.lines.json")
    for f in cands:
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        boxes = data.get("boxes") or []
        if boxes and len(boxes) == nlines:
            return [[int(v) for v in b[:4]] for b in boxes]
    return None


def _page_cands(lines: list[str]) -> dict[int, list[str]]:
    """Норми кандидатів кожного рядка — тими самими правилами, що й пошук.

    🔴 `page_candidates` не копіюється, а кличеться: друга копія правил
    склейки розійшлася б із першою тихо, і стор знаходив би не те, що вміє
    пояснити гортач.
    """
    from nyshporka import htr_store as S

    out: dict[int, list[str]] = {}
    for no, _raw, cands in S.page_candidates(lines):
        ns = [n for _w, n in cands if n]
        if ns:
            out[no] = ns
    return out


def _geo_cands(cands: dict[int, list[str]], lines: list[Line],
               succ: dict[int, int]) -> None:
    """Склейка за наступником на аркуші — хвіст рядка + голова того, що під ним.

    🔴 Кандидат кладеться на ОБИДВІ половини. Передфільтр знаходить або хвіст
    («doli |»), або голову («| scins»), і з якого боку прийде запит, наперед
    невідомо; кандидат на одній половині лишав би другий шлях сліпим.
    """
    first: dict[int, str] = {}
    last: dict[int, str] = {}
    for ln in lines:
        toks = ln.toks.split(" ")
        if toks and toks[0]:
            first[ln.no] = toks[0]
            last[ln.no] = toks[-1]
    for prev, nxt in succ.items():
        pt, head = last.get(prev, ""), first.get(nxt, "")
        if len(pt) < 3 or len(head) < 3 or len(pt) + len(head) < 7:
            continue
        n = _norm(pt + head)
        if not n:
            continue
        for target in (prev, nxt):
            cands.setdefault(target, []).append(n)


def _page_blob(lines: list[str], page_lines: list[Line], *, has_geo: bool,
               ) -> tuple[str, dict[int, int]]:
    """Текст блоба `pages.cands` сторінки і наступники за колонкою.

    🔴 Одна функція на збірку й на звірку (`verify`). Друга копія цих кількох
    рядків у звірці розійшлась би з першою так само тихо, як розходяться
    правила склейки, — і приймач мовчки перевіряв би сам себе.
    """
    cands = _page_cands(lines)
    succ = successors(page_lines) if has_geo else {}
    if succ:
        _geo_cands(cands, page_lines, succ)
    text = "\n".join(f"{no}\t{' '.join(ns)}" for no, ns in sorted(cands.items()) if ns)
    return text, succ


def _same_case(meta: dict[str, Any] | None, base: Path) -> bool:
    """Чи прогін `base` про ту саму справу, що й `meta`."""
    from nyshporka import htr_store as S

    if not meta:
        return False
    other = S.load_meta(base.name) or {}
    # Канонічні ключі: мета пише і шифру паспорта, і ключ до 0.22.
    key = S._canon_case_key((meta.get("case_key") or "").strip())
    okey = S._canon_case_key((other.get("case_key") or "").strip())
    cd, ocd = (meta.get("case_dir") or "").strip(), (other.get("case_dir") or "").strip()
    return bool((key and key == okey) or (cd and cd == ocd))


def _delete_run(conn: sqlite3.Connection, run_id: int) -> None:
    pids = [r[0] for r in conn.execute("select id from pages where run_id=?", (run_id,))]
    for pid in pids:
        lo, hi = pid << LINE_BITS, ((pid + 1) << LINE_BITS) - 1
        conn.execute("delete from fts where rowid between ? and ?", (lo, hi))
        conn.execute("delete from lines where id between ? and ?", (lo, hi))
    conn.execute("delete from pages where run_id=?", (run_id,))
    conn.execute("delete from sweeps where run_id=?", (run_id,))
    conn.execute("delete from runs where id=?", (run_id,))


def _locked_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _begin_write(conn: sqlite3.Connection, *, wait: float,
                 waiting: Callable[[], None] | None = None) -> None:
    """Транзакція із замком на запис ОДРАЗУ (`begin immediate`).

    🔴 Не простий `begin`. Відкладена транзакція спершу читала (`runs`), а
    писати пробувала вже після чужого коміту — і SQLite у режимі WAL відповідає
    на це «locked» одразу, без очікування `BUSY_TIMEOUT`: знімок, з якого
    читали, застарів. Повна індексація комітить після кожного прогону, тож
    паралельний `index --case` програвав майже завжди (тест
    `test_index_waits_for_another_writer_instead_of_skipping`).

    Замок, який чужа сесія тримає довше за `BUSY_TIMEOUT` (`optimize`,
    перебудова), чекається повторами до `wait` секунд.
    """
    snap = _STAMPS.get()
    if snap is not None:
        snap.pop("v", None)
    deadline = time.monotonic() + wait
    while True:
        try:
            conn.execute("begin immediate")
            return
        except sqlite3.OperationalError as exc:
            if not _locked_error(exc) or time.monotonic() >= deadline:
                raise
            if waiting:
                waiting()
            time.sleep(1.0)


def index_run(conn: sqlite3.Connection, run: str, *, wait: float = 0.0,
              waiting: Callable[[], None] | None = None) -> int:
    """Проіндексувати один прогін примусово. Повертає число рядків."""
    got = _index(conn, run, only_stale=False, wait=wait, waiting=waiting)
    return int(got or 0)


def index_run_if_stale(conn: sqlite3.Connection, run: str, *, wait: float = 0.0,
                       waiting: Callable[[], None] | None = None) -> int | None:
    """Проіндексувати прогін, якщо він ще застарілий. `None` — уже свіжий.

    🔴 Свіжість перевіряється ПІД замком на запис: поки цей процес чекав, той
    самий прогін міг проіндексувати інший (наглядач хмари й сесія агента після
    тієї самої справи). Тоді вдруге він не збирається — запити зливаються.
    """
    return _index(conn, run, only_stale=True, wait=wait, waiting=waiting)


def _run_key(run: str, meta: dict[str, Any]) -> str:
    """Ключ справи прогону для стору — рішення реєстру, а не сирий ключ мети.

    🔴 Мета прогону незмінна, тож після `cases bind` у ній лишається старий
    ключ (`DAVIO/10800/1/8` замість `DAVIO/800/1/8a`), і `text index --rebuild`
    переписував його в стор знову (відгук 18.10.2026). Нерозв'язаний прогін
    лишає ключ мети як був.
    """
    from nyshporka import htr_store as S

    raw = (meta.get("case_key") or "").strip()
    try:
        row = _ROWS.get(run) or next(
            (r for r in S.list_cases() if r.get("name") == run),
            {"name": run, "case_key": raw})
        return S.proven_key(row, _bound())
    except Exception:
        return raw


_BOUND: tuple[Any, dict[str, str | None]] | None = None
#: Рядки переліку прогонів на час одного проходу `ensure_all`.
_ROWS: dict[str, dict[str, Any]] = {}


def _bound() -> dict[str, str | None]:
    """Прив'язки людини, перечитані лише коли змінився `overrides.json`.

    Стор збирає тисячі прогонів поспіль, а прив'язок — одиниці.
    """
    global _BOUND
    from nyshporka import htr_store as S
    from nyshporka.cases.resolve import overrides_path

    try:
        st = overrides_path().stat()
        sig: Any = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if _BOUND is None or _BOUND[0] != sig:
        _BOUND = (sig, S._bound_runs())
    return _BOUND[1]


def _text_unchanged(d: Path, pages: int, indexed_at: str) -> bool:
    """Чи текст прогону той самий, що ліг у стор, — хоч штамп мети й інший.

    🔴 Штамп — час і розмір `_htr_meta.json` та теки, а мету переписує багато
    що, крім читання: позначка проєкту, постійна тека справи, ключ. Одна така
    правка 22.10.2026 зробила «застарілими» 9 394 прогони з 16 079, і пошук
    пропонував перечитати в стор 3,4 млн сторінок, яких ніхто не міняв.

    Тож штамп — лише сигнал «могло змінитись», а відповідь дає сам текст:
    скільки `.txt` і чи жоден файл прогону (крім мети) не новіший за збірку.
    Час — файлової системи цієї машини, а не годинника в меті: прогін із хмари
    приходить із часом машини, що його читала.
    """
    try:
        # Мікросекунди (з 0.37) відкидаються: секунда вниз — помилка в обережний бік.
        since = time.mktime(time.strptime(indexed_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return False
    n = 0
    try:
        with os.scandir(d) as it:
            for e in it:
                name = e.name
                if name.startswith("_htr_meta") or name.endswith(".tmp") or not e.is_file():
                    continue
                # Секунда збірки обрізана вниз: файл тієї самої секунди — «новіший»,
                # і прогін переіндексується. Помилка лише в обережний бік.
                if e.stat().st_mtime >= since:
                    return False
                if name.endswith(".txt"):
                    n += 1
    except OSError:
        return False
    return n > 0 and n == pages


def _index(conn: sqlite3.Connection, run: str, *, only_stale: bool, wait: float,
           waiting: Callable[[], None] | None) -> int | None:
    """Проіндексувати один прогін. Повертає число рядків.

    🔴 Спершу видалення старого, потім вставка нового, і все в ОДНІЙ
    транзакції: обірваний захід (Ctrl+C, диск) лишає стор у попередньому
    стані, а не з половиною справи під свіжим штампом.
    """
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D

    d = D._run_dir(run)
    if d is None:
        return 0
    stamp = stamp_of(run)
    meta = S.load_meta(run) or {}
    stem2page = {Path(pg).stem: pg for pg in (meta.get("pages") or {})}
    txts = sorted(d.glob("*.txt"))
    _begin_write(conn, wait=wait, waiting=waiting)
    if only_stale:
        row = conn.execute("select stamp, coalesce(rules,''), coalesce(indexed_at,''), "
                           "coalesce(pages,0) from runs where run=?", (run,)).fetchone()
        if row and stamp and row[0] == stamp and row[1] == rules_hash():
            conn.rollback()
            return None
        if (row and stamp and row[1] == rules_hash()
                and _text_unchanged(d, int(row[3]), str(row[2]))):
            # Змінилась лише мета: новий штамп і поля з неї, текст — як був.
            conn.execute(
                "update runs set stamp=?, case_key=?, case_dir=?, model=?, script=?, "
                "engine_ids=?, shared=? where run=?",
                (stamp, _run_key(run, meta), meta.get("case_dir") or "",
                 meta.get("model") or "", meta.get("script") or "",
                 json.dumps(S.run_engine_ids(meta)), S.shared_of(meta), run))
            conn.commit()
            return None
    old = conn.execute("select id from runs where run=?", (run,)).fetchone()
    if old:
        _delete_run(conn, int(old[0]))
    if not txts:
        # 🔴 Тека без жодного `.txt` у стор не лягає: рядок `runs` зі штампом
        # робив її «свіжою» і «прочесаною», тобто знаменник ріс на прогін, у
        # якому нема чого шукати (рецензія 08.09, третій раунд).
        conn.commit()
        return 0
    if conn.execute("select 1 from meta where key='rules'").fetchone() is None:
        conn.execute("insert into meta(key,value) values('rules',?)", (rules_hash(),))
    conn.execute(
        "insert into runs(run, stamp, case_key, case_dir, model, script, engine_ids, "
        "indexed_at, rules, shared) values(?,?,?,?,?,?,?,?,?,?)",
        (run, stamp, _run_key(run, meta), meta.get("case_dir") or "",
         meta.get("model") or "", meta.get("script") or "",
         # 🔴 З мікросекундами: позначка тексту швидкого індексу (`fastidx`) —
         # саме вона, і перечитаний у ту саму секунду прогін (SQLite міг видати
         # той самий id) інакше лишився б «тим самим».
         json.dumps(S.run_engine_ids(meta)),
         datetime.now().isoformat(timespec="microseconds"),
         rules_hash(), S.shared_of(meta)))
    run_id = int(conn.execute("select id from runs where run=?", (run,)).fetchone()[0])
    n_pages = n_lines = n_geo = 0
    for txt in txts:
        try:
            text = txt.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES]
        # 🔴 Без запису в меті сторінка зветься ОСНОВОЮ імені, не «0002.txt»:
        # ім'я з «.txt» протікало у вердикти та кроп як неіснуючий скан.
        page = stem2page.get(txt.stem, txt.stem)
        boxes = _geometry_for(d, run, txt.stem, len(lines), meta)
        conn.execute(
            "insert into pages(run_id, page, stem, nlines, geo, raw) values(?,?,?,?,?,?)",
            (run_id, page, txt.stem, len(lines), int(boxes is not None),
             zlib.compress("\n".join(lines).encode("utf-8"), 6)))
        pid = int(conn.execute("select last_insert_rowid()").fetchone()[0])
        rows: list[tuple[int, str, int | None, int | None, int | None, int | None,
                         int | None]] = []
        ftsrows: list[tuple[int, str]] = []
        page_lines: list[Line] = []
        for i, ln in enumerate(lines, 1):
            toks = _tokens(ln)
            if not toks:
                continue
            b = boxes[i - 1] if boxes else None
            page_lines.append(Line(i, " ".join(toks),
                                   (b[0], b[1], b[2], b[3]) if b else None))
        blob, succ = _page_blob(lines, page_lines, has_geo=bool(boxes))
        conn.execute("update pages set cands=? where id=?",
                     (zlib.compress(blob.encode("utf-8"), 6), pid))
        for pl in page_lines:
            rid = (pid << LINE_BITS) + pl.no
            bx = pl.box
            nxt = succ.get(pl.no)
            rows.append((rid, pl.toks,
                         bx[0] if bx else None, bx[1] if bx else None,
                         bx[2] if bx else None, bx[3] if bx else None,
                         (pid << LINE_BITS) + nxt if nxt else None))
            norms = " ".join(_norm(tk) for tk in pl.toks.split(" ") if len(tk) >= 3)
            if norms:
                ftsrows.append((rid, f"{MARK} {norms} {MARK}"))
        conn.executemany("insert into lines(id,toks,x0,y0,x1,y1,succ) values(?,?,?,?,?,?,?)",
                         rows)
        conn.executemany("insert into fts(rowid,norm) values(?,?)", ftsrows)
        n_pages += 1
        n_lines += len(rows)
        n_geo += int(boxes is not None)
    conn.execute("update runs set pages=?, lines=?, geo=? where id=?",
                 (n_pages, n_lines, n_geo, run_id))
    conn.commit()
    return n_lines


def ensure(run: str, conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    c = conn or connect()
    try:
        if is_fresh(run, c):
            return True
        got = index_run_if_stale(c, run)
        return got is None or got > 0
    finally:
        if own:
            c.close()


#: Прогони, які остання збірка пропустила через замок іншої сесії. Мовчазний
#: пропуск виглядав як «тека без .txt» (рецензія 08.09, третій раунд).
LOCKED_SKIPPED: list[str] = []


def ensure_all(runs: list[str], *, force: bool = False, reset_rules: bool = False,
               progress: Callable[[int, int, str], None] | None = None,
               optimize: bool | None = None,
               ) -> Iterator[str]:
    """Догнати стор по переліку прогонів, звітуючи про кожен.

    Генератор навмисно: перша збірка корпусу триває десятки хвилин, і той, хто
    її запустив, мусить бачити, де вона зараз. `force` перебудовує й свіже —
    після зміни правил розбору токенів чи геометрії.

    `optimize` — злиття ВСІХ сегментів FTS у кінці. Типово воно йде з `force`
    або після ≥`OPTIMIZE_MIN` зібраних прогонів. `False` — для точкової
    переіндексації кількох прогонів (розбивка теки, прийом пакета): злиття
    стору на десятки ГБ під write-lock коштувало хвилин на кожну теку й
    тримало замок для сусідніх процесів (14.10.2026).
    """
    from nyshporka.core import progress as P

    built = 0
    LOCKED_SKIPPED.clear()
    conn = connect(migrate=True)
    try:
        if force and reset_rules:
            conn.execute("delete from meta where key='rules'")
            conn.commit()
        known = stamps(conn)
        # 🔴 Прогін вважається свіжим за ДВОМА умовами: незмінений штамп теки
        # І той самий відбиток правил склейки. Доти друга умова була одна на
        # весь стор, і перебудова, вбита посеред, лишала змішаний стор, який
        # рапортував повну свіжість. Тепер недороблене доганяється звичайним
        # `text index`, без другої перебудови на 40 хвилин.
        rules_now = rules_hash()
        by_rules = {r[0]: (r[1] or "") for r in
                    conn.execute("select run, coalesce(rules,'') from runs")}
        # 🔴 Поступ — лише по тих, кого справді збираємо. Свіжі проскакують за
        # мілісекунди, і в одному знаменнику з ними оцінка «лишилось ≈» на
        # консолі виходила годинами там, де робота триває хвилини (16
        # застарілих із 4860 стояли першими й задавали темп на всі 4860).
        todo: list[str] = []
        for run in runs:
            st = stamp_of(run)
            if st and known.get(run) == st and by_rules.get(run) == rules_now \
                    and not force:
                yield run
                continue
            todo.append(run)
        total = len(todo)
        gave_up = False
        # Ключ справи кожного прогону береться з переліку (`_run_key`); перелік
        # — один на весь прохід, а не обхід кореня прогонів на кожен прогін.
        _ROWS.clear()
        if todo:
            from nyshporka import htr_store as S

            with contextlib.suppress(Exception):
                _ROWS.update({str(r.get("name")): r for r in S.list_cases()})
        for i, run in enumerate(todo, 1):
            if gave_up:
                # Стор тримають довше за `INDEX_WAIT_SEC`: решту не чекаємо по
                # пів години кожен — вони названі в `LOCKED_SKIPPED`.
                LOCKED_SKIPPED.append(run)
                continue
            if progress:
                progress(i, total, run)
            P.report(i, total, "прогонів")

            def waiting(i: int = i) -> None:
                if progress:
                    progress(i, total, PHASE_WAIT)
                P.report(i, total, PHASE_WAIT)

            try:
                if force:
                    got: int | None = index_run(conn, run, wait=INDEX_WAIT_SEC,
                                                waiting=waiting)
                else:
                    got = index_run_if_stale(conn, run, wait=INDEX_WAIT_SEC,
                                             waiting=waiting)
            except sqlite3.OperationalError as exc:
                if not _locked_error(exc):
                    raise
                with contextlib.suppress(sqlite3.Error):
                    conn.rollback()
                LOCKED_SKIPPED.append(run)
                gave_up = True
                continue
            if got is None:
                # Уже зібрав інший процес, поки ми чекали замка.
                yield run
            elif got > 0:
                built += 1
                yield run
        # `optimize` зливає ВСІ сегменти FTS під write-lock — на 6.5 ГБ це
        # не для кожного `index --case`; лише коли зібрано багато або примусово.
        # Зайнятий стор — не причина валити вже зроблену індексацію: злиття
        # сегментів лише прискорює, і його зробить наступна збірка.
        if optimize if optimize is not None else (force or built >= OPTIMIZE_MIN):
            try:
                conn.execute("insert into fts(fts) values('optimize')")
                conn.commit()
            except sqlite3.OperationalError as exc:
                if not _locked_error(exc):
                    raise
                with contextlib.suppress(sqlite3.Error):
                    conn.rollback()
    finally:
        _ROWS.clear()
        conn.close()


def stale_count(runs: list[str], conn: sqlite3.Connection | None = None) -> int:
    """Скільки з цих прогонів стор ще не має або має застарілими."""
    if not path().is_file():
        return len(runs)
    own = conn is None
    c = conn or connect(readonly=True)
    try:
        known = stamps(c)
    finally:
        if own:
            c.close()
    # Штамп — один раз на прогін: це `stat` на теку й мету, а прогонів у
    # простору буває 12 тис. (два виклики коштували 7 с на кожне «Огляду»).
    st = stamps_for(runs)
    return sum(1 for r in runs if not st[r] or known.get(r) != st[r])


def stats() -> dict[str, Any]:
    """Скільки прогонів у сторі, скільки застаріло, скільки важить."""
    from nyshporka import htr_store as S

    try:
        runs = [c["name"] for c in S.list_cases()]
    except Exception:
        runs = []
    p = path()
    if not p.is_file():
        return {"runs": len(runs), "indexed": 0, "stale": len(runs), "bytes": 0,
                "pages": 0, "lines": 0, "geo": 0, "file": str(p), "exists": False}
    conn = connect(readonly=True)
    try:
        known = stamps(conn)
        st = stamps_for(runs)
        fresh = sum(1 for r in runs if known.get(r) and known[r] == st[r])
        row = conn.execute("select coalesce(sum(pages),0), coalesce(sum(lines),0), "
                           "coalesce(sum(geo),0) from runs").fetchone()
        rstale = rules_stale(conn)
        other = runs_of_other_rules(conn)
    finally:
        conn.close()
    return {"runs": len(runs), "indexed": fresh, "stale": len(runs) - fresh,
            "bytes": p.stat().st_size, "pages": int(row[0]), "lines": int(row[1]),
            "geo": int(row[2]), "file": str(p), "exists": True,
            # Правила склейки змінились після збірки: кандидати в блобах старі,
            # штампи цього не бачать — лише `text index --rebuild`.
            "rules_stale": rstale,
            # 🔴 А це — ПОШТУЧНО: скільки прогонів зібрані іншим правилом.
            # Саме його бракувало, коли перебудову вбило посеред і стор
            # рапортував «застаріло 0» на 234 прогонах зі старими кандидатами.
            "rules_other": len(other)}


# ── звірка блобів ────────────────────────────────────────────────────────────
def _sample(ids: list[int], k: int) -> list[int]:
    """Перша, остання й рівномірно між ними; `k <= 0` — усі."""
    if k <= 0 or len(ids) <= k:
        return list(ids)
    if k == 1:
        return [ids[0]]
    step = (len(ids) - 1) / (k - 1)
    return list(dict.fromkeys(ids[round(i * step)] for i in range(k)))


def _verify_page(conn: sqlite3.Connection, pid: int, cands: bytes | None,
                 geo: int) -> list[str]:
    """Що на сторінці розійшлось із чинним кодом: `toks`, `succ`, `cands`."""
    lines = _raw_lines(conn, pid)
    stored = _page_lines(conn, pid)
    what: list[str] = []
    want_toks = {i: " ".join(t) for i, ln in enumerate(lines, 1) if (t := _tokens(ln))}
    if want_toks != {ln.no: ln.toks for ln in stored}:
        what.append("toks")
    text, succ = _page_blob(lines, stored, has_geo=bool(geo))
    if succ != {ln.no: ln.succ for ln in stored if ln.succ}:
        what.append("succ")
    have = zlib.decompress(cands).decode("utf-8") if cands is not None else None
    if have != text:
        what.append("cands")
    return what


def verify(runs: list[str] | None = None, *, sample: int = 3) -> dict[str, Any]:
    """Звірка блобів: чи дає чинний код тих самих кандидатів, що лежать у сторі.

    🔴 Єдиний приймач однорідності стору після обірваної перебудови. Відбиток
    правил (`runs.rules`) — лише заява про те, яким кодом зібрано прогін, і
    08.09.2026 вона збрехала в обидва боки: спершу «правила чинні» на 234
    прогонах зі старими кандидатами, потім «правила інші» на 234 прогонах із
    тотожними (відбиток посеред заходу нарізався по зсунутих рядках). Обидва
    рази правду сказала лише пряма звірка, і досі її робили разовим скриптом.

    Звірка читає лише БД: сирий текст сторінки, рядки й рамки лежать там же,
    тож обходу тек прогонів немає. Кандидати перераховуються `_page_blob` —
    тією самою функцією, що й при збірці.

    `differ[].rules_same` розводить два діагнози: `False` — прогін просто
    зібраний старим правилом, його доганяє `text index`; `True` — відбиток
    каже «чинне», а кандидати інші, і `text index` такого прогону не побачить.
    """
    from nyshporka.core import progress as P

    h = rules_hash()
    conn = connect(readonly=True)
    try:
        rows = conn.execute(
            "select id, run, coalesce(rules,'') from runs order by run").fetchall()
        missing: list[str] = []
        if runs is not None:
            want = set(runs)
            rows = [r for r in rows if r[1] in want]
            missing = sorted(want - {r[1] for r in rows})
        differ: list[dict[str, Any]] = []
        fingerprint_only: list[str] = []
        n_pages = 0
        for i, (rid, run, rules) in enumerate(rows, 1):
            P.report(i, len(rows), "прогонів")
            pids = [r[0] for r in conn.execute(
                "select id from pages where run_id=? order by id", (rid,))]
            bad: list[dict[str, Any]] = []
            for pid in _sample(pids, sample):
                page, cands, geo = conn.execute(
                    "select page, cands, geo from pages where id=?", (pid,)).fetchone()
                n_pages += 1
                what = _verify_page(conn, pid, cands, geo)
                if what:
                    bad.append({"page": page, "what": what})
            if bad:
                differ.append({"run": run, "rules_same": rules == h, "pages": bad})
            elif rules != h:
                fingerprint_only.append(run)
    finally:
        conn.close()
    return {"runs_checked": len(rows), "pages_checked": n_pages, "sample": sample,
            "rules": h, "differ": differ, "fingerprint_only": fingerprint_only,
            "missing": missing}


# ── читання сторінки зі стору ────────────────────────────────────────────────
@dataclass
class Line:
    no: int
    toks: str
    box: tuple[int, int, int, int] | None
    #: Номер рядка, який іде за цим НА АРКУШІ (за геометрією), коли він не
    #: наступний у файлі. Рахується при індексації — `successors()`.
    succ: int | None = None


def _page_id(conn: sqlite3.Connection, run: str, page: str) -> int | None:
    row = conn.execute(
        "select p.id from pages p join runs r on r.id=p.run_id "
        "where r.run=? and (p.page=? or p.stem=?)", (run, page, Path(page).stem)).fetchone()
    return int(row[0]) if row else None


def page_text(run: str, page: str, conn: sqlite3.Connection | None = None) -> list[str] | None:
    """Сирий текст сторінки як у `.txt`, без походу на диск із прогонами."""
    own = conn is None
    c = conn or connect(readonly=True)
    try:
        pid = _page_id(c, run, page)
        if pid is None:
            return None
        return _raw_lines(c, pid)
    finally:
        if own:
            c.close()


def _raw_lines(conn: sqlite3.Connection, pid: int) -> list[str]:
    row = conn.execute("select raw from pages where id=?", (pid,)).fetchone()
    if not row or row[0] is None:
        return []
    return zlib.decompress(row[0]).decode("utf-8").split("\n")


def _page_lines(conn: sqlite3.Connection, pid: int) -> list[Line]:
    lo, hi = pid << LINE_BITS, ((pid + 1) << LINE_BITS) - 1
    out: list[Line] = []
    for rid, toks, x0, y0, x1, y1, succ in conn.execute(
            "select id,toks,x0,y0,x1,y1,succ from lines where id between ? and ? order by id",
            (lo, hi)):
        box = (int(x0), int(y0), int(x1), int(y1)) if x0 is not None else None
        out.append(Line(rid - lo, toks, box, (succ - lo) if succ else None))
    return out


def _page_boxes(conn: sqlite3.Connection, pid: int) -> dict[int, tuple[int, int, int, int]]:
    """Рамки рядків сторінки: {номер рядка: рамка} — те саме, що `_page_lines`
    дає в `box`, але без блоба кандидатів, який каналу запису не потрібен
    (0,7 с на справу в 1228 сторінок, замір 21.10.2026)."""
    lo, hi = pid << LINE_BITS, ((pid + 1) << LINE_BITS) - 1
    return {rid - lo: (int(x0), int(y0), int(x1), int(y1))
            for rid, x0, y0, x1, y1 in conn.execute(
                "select id,x0,y0,x1,y1 from lines where id between ? and ? "
                "and x0 is not null", (lo, hi))}


# ── склейка за колонкою ──────────────────────────────────────────────────────
#: Частка ширини сторінки, більша за яку прогалина між лівими краями рядків
#: означає нову колонку.
COL_GAP = 0.12
#: Скільки висот рядка вниз шукати наступника в колонці.
SUCC_REACH = 2.5


def successors(lines: list[Line]) -> dict[int, int]:
    """Рядок → рядок, який іде за ним НА АРКУШІ, а не в файлі.

    🔴 Сегментація табличного бланка віддає рядки не в порядку читання: на
    еталонному розвороті метрики хвіст прізвища стоїть у рядку 15, а голова —
    у рядку 24, хоча на аркуші вони одна під одною. Вікно склейки в три рядки
    до неї не дістає, і прізвище лишається невидимим.

    Правило: колонки — це скупчення лівих країв; хвіст рядка належить колонці,
    у якій закінчується його правий край (широкий рядок починається зліва, а
    закінчується в сусідній колонці); наступник — найближчий знизу рядок тієї
    колонки. Повертає лише ті пари, яких файловий порядок не дає сам.

    ⚠ Рахується при індексації для кожної сторінки з рамками, тож мусить бути
    дешевим: колонки відсортовані за верхнім краєм, наступник береться
    двійковим пошуком.
    """
    from bisect import bisect_left

    boxed = [ln for ln in lines if ln.box]
    if len(boxed) < 6:
        return {}
    width = max(b.box[2] for b in boxed if b.box) or 1
    xs = sorted(b.box[0] for b in boxed if b.box)
    cols: list[list[int]] = [[xs[0]]]
    for x in xs[1:]:
        if x - cols[-1][-1] > COL_GAP * width:
            cols.append([x])
        else:
            cols[-1].append(x)
    lefts = [min(c) for c in cols if len(c) >= 3]
    if len(lefts) < 2:
        return {}
    # Допуск малий навмисно: правий край рядка лівої колонки стоїть за кілька
    # десятків пікселів від лівого краю правої, і широкий допуск відносив би
    # звичайний рядок лівої колонки до правої.
    tol = width * 0.01

    def col_of(x: int) -> int:
        best = 0
        for i, left in enumerate(lefts):
            if left - tol <= x:
                best = i
        return best

    heights = sorted(b.box[3] - b.box[1] for b in boxed if b.box)
    h = max(heights[len(heights) // 2], 1)
    by_col: dict[int, list[tuple[int, int]]] = {}
    for ln in boxed:
        assert ln.box
        by_col.setdefault(col_of(ln.box[0]), []).append((ln.box[1], ln.no))
    for arr in by_col.values():
        arr.sort()
    out: dict[int, int] = {}
    for ln in boxed:
        assert ln.box
        col = by_col.get(col_of(ln.box[2]))
        if not col:
            continue
        arr = col
        ys = [y for y, _no in arr]
        i = bisect_left(ys, int(ln.box[1] + h * 0.3) + 1)
        while i < len(arr):
            y0, no = arr[i]
            if y0 - ln.box[3] >= h * SUCC_REACH:
                break
            if no != ln.no:
                if no != ln.no + 1:
                    out[ln.no] = no
                break
            i += 1
    return out


# ── зіставлення ──────────────────────────────────────────────────────────────
def whole_stems(stems: list[str], keep: tuple[str, ...] | list[str] = ()
                ) -> tuple[list[str], list[str]]:
    """Лишити цілі написання; голови, хвости й склейки переносу — геть.

    Фрагмент — стем із дефісом чи пробілом, або строгий СУФІКС іншого стема
    («alskii» ⊂ «kovalskii» — хвіст переносу). Префікс фрагментом не є:
    «kovalska» ⊂ «kovalskago» — це відмінкова форма, не уламок.

    🔴 `keep` — те, що набрала людина: воно не викидається ніколи. «Анна» після
    розкриття гнізда імен давала «ganna», і суфіксне правило викидало саме
    набране слово (рецензія 08.09). Повертає (цілі, відкинуті).
    """
    asked = set(keep)
    clean = [s for s in stems if s and (("-" not in s and " " not in s) or s in asked)]
    out: list[str] = []
    dropped: list[str] = [s for s in stems if s not in clean]
    for s in clean:
        frag = s not in asked and any(o != s and len(o) > len(s) and o.endswith(s)
                                      for o in clean)
        (dropped if frag else out).append(s)
    return out, dropped


def match_expr(stems: list[str], *, wide: bool = False) -> str:
    """Вираз FTS: доказ, що рядок ВАРТО судити rapidfuzz.

    Три способи, кожен сам по собі достатній:

    * дві k-грами одного стема, взяті з різних місць (розрив ≥ 3 для 4-грам),
      — слово з покаліченою серединою чи хвостом;
    * початок стема в КІНЦІ рядка («doli |») — хвіст перенесеного прізвища;
    * k-грама стема на ПОЧАТКУ рядка («| scins») — голова перенесеного.

    🔴 Одна k-грама будь-де — замало. Заміряно на корпусі з 42 млн рядків:
    самі 5-грами тягнули 496 тис. рядків (кінцівка «-нскій» стоїть у кожному
    прізвищі), пари — 72 тис.; на еталоні ф.904 пари з маркерами не губили
    жодної згадки, яку губили б не через розрив рядка.
    """
    terms: set[str] = set()
    if not wide:
        # 🔴 У межах справи чи фонду — голі триграми. Ціна запиту FTS росте з
        # числом термів, а не рядків; триграми майже повторюють gzip-свіп
        # (2 пропуски з 5376) і в шість разів швидші за пари.
        for s in stems:
            terms.update(f'"{s[i:i + 3]}"' for i in range(max(1, len(s) - 2)))
        return " OR ".join(sorted(terms))
    for s in stems:
        k = kgram_len(s)
        if len(s) <= k + 1:
            terms.add(f'"{s}"')
            continue
        grams = [s[i:i + k] for i in range(len(s) - k + 1)]
        # Тригамні пари з розривом ≥ 3 — острівець із п'яти літер посеред
        # покаліченого слова («scin»+«cins»), який пари 4-грам не бачать.
        tri = [s[i:i + 3] for i in range(len(s) - 2)]
        for i, a in enumerate(tri):
            for b in tri[i + 3:]:
                terms.add(f'("{a}" AND "{b}")')
        if len(s) < PAIR_MIN_LEN:
            # 🔴 Короткому стему пари не лишають місця: одна правка в
            # «kovalskii» (9 літер) вбиває три сусідні грами, і другого доказу
            # немає — «kovlskii» (94 бали) губився. Для таких — будь-яка грама.
            terms.update(f'"{g}"' for g in grams)
        gap = PAIR_GAP if k >= 4 else 2
        for i, a in enumerate(grams):
            for b in grams[i + gap:]:
                terms.add(f'("{a}" AND "{b}")')
        # Хвіст перенесеного прізвища — БУДЬ-ЯКИЙ початок стема від трьох
        # літер, і саме в кінці рядка: «ков |», «коваль |», «ковальск |».
        for cut in range(3, len(s)):
            terms.add(f'"{s[:cut]} {MARK}"')
        for g in grams[1:]:
            terms.add(f'"{MARK} {g}"')
    return " OR ".join(sorted(terms))


def _run_ids(conn: sqlite3.Connection, runs: list[str], *, fresh_only: bool = False
             ) -> dict[str, int]:
    """run → id. `fresh_only` бере лише прогони зі свіжим штампом: дочитана
    справа зі старим текстом у сторі — це прочесане «вчорашнє», і воно не
    може зараховуватись як покрите (рецензія 08.09)."""
    out: dict[str, int] = {}
    if len(runs) >= BULK_RUNS:
        # Велика область — одним запитом і одним переліком кореня, а не
        # запитом і трьома `stat` на прогін (1,2 с на корпусний `grep`).
        from nyshporka.search import decode as D

        rows = {str(r): (int(i), str(s)) for r, i, s in
                conn.execute("select run, id, stamp from runs")}
        fresh = D.stamps_of(runs) if fresh_only else {}
        for run in runs:
            got = rows.get(run)
            if got is None or (fresh_only and got[1] != fresh.get(run, "")):
                continue
            out[run] = got[0]
        return out
    for run in runs:
        row = conn.execute("select id, stamp from runs where run=?", (run,)).fetchone()
        if not row:
            continue
        if fresh_only and row[1] != stamp_of(run):
            continue
        out[run] = int(row[0])
    return out


#: З якої кількості прогонів `_run_ids` бере всі рядки й штампи гуртом:
#: перелік кореня коштує ~0,2 с, три `stat` прогону — ~0,07 мс.
BULK_RUNS = 200


def _pages_for(conn: sqlite3.Connection, pids: set[int], run_ids: set[int]
               ) -> dict[int, tuple[int, str]]:
    """pid → (run_id, page) лише для названих сторінок — а не для всього корпусу
    заради трьох хітів (мапа 512 тис. сторінок коштувала 2 с на кожен `grep`)."""
    out: dict[int, tuple[int, str]] = {}
    ordered = sorted(pids)
    for i in range(0, len(ordered), 500):
        chunk = ordered[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for pid, rid, page in conn.execute(
                f"select id, run_id, page from pages where id in ({marks})", chunk):
            if int(rid) in run_ids:
                out[int(pid)] = (int(rid), str(page))
    return out


#: Літери латинки, якими диграф ПОЧИНАЄТЬСЯ (sz, cz, rz, ch, sch, gh) і
#: якими ЗАКІНЧУЄТЬСЯ. «h» у голові — для «sch»/«gh», зрізаних перед голосною
#: («Kowalsch» з «Kowalschinski»: норма «kowalsh» не є підрядком «kowalskinski»). Літерал, розрізаний посеред диграфа, нормалізується не
#: так, як ціле слово («zczynski»→«zcinski» ⊄ «kowalscinski»), тож з країв
#: зрізаються лише ті літери, що могли бути половиною диграфа через зріз.
#: Кирилиця диграфів не має — не чіпається.
_DIGRAPH_HEAD = set("sczrgh")
_DIGRAPH_TAIL = set("zchie")


def _literal_core(lit: str) -> str:
    if not re.search(r"[A-Za-z]", lit):
        return lit
    core = lit
    while core and core[0].lower() in _DIGRAPH_TAIL:
        core = core[1:]
    while core and core[-1].lower() in _DIGRAPH_HEAD:
        core = core[:-1]
    return core


def _page_texts(conn: sqlite3.Connection, pids: list[int], run_ids: set[int]
                ) -> Iterator[tuple[int, str, bytes | None]]:
    """(run_id, page, стиснений текст) названих сторінок області — за зростанням id.

    🔴 Одне читання рядка `pages` на сторінку. Доти `grep` брав спершу назву
    (`_pages_for`), а потім текст (`_raw_lines`) — два випадкові звертання до
    таблиці на 3,4 млн рядків, і на широкому літералі саме вони, а не регекс,
    коштували дві третини часу (замір 21.10.2026).
    """
    for i in range(0, len(pids), 500):
        chunk = pids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"select id, run_id, page, raw from pages where id in ({marks})", chunk).fetchall()
        rows.sort(key=lambda r: int(r[0]))
        for _pid, rid, page, raw in rows:
            if int(rid) in run_ids:
                yield int(rid), str(page), raw


def _run_texts(conn: sqlite3.Connection, run_ids: list[int]
               ) -> Iterator[tuple[int, str, bytes | None]]:
    """Те саме для ВСІХ сторінок прогонів області — повний прохід без передфільтра.

    Уся база — одним послідовним проходом по таблиці; менша область — номери
    сторінок за індексом прогону, далі тим самим порядком, що й `_page_texts`.
    """
    want = set(run_ids)
    if not want:
        return
    if len(want) >= _runs_total(conn):
        for _pid, rid, page, raw in conn.execute(
                "select id, run_id, page, raw from pages order by id"):
            if int(rid) in want:
                yield int(rid), str(page), raw
        return
    pids: list[int] = []
    for rid in run_ids:
        pids.extend(int(p) for (p,) in conn.execute(
            "select id from pages where run_id=?", (rid,)))
    yield from _page_texts(conn, sorted(set(pids)), want)


#: Стільки прогонів ще варто обмежувати діапазонами rowid у запиті FTS.
#: Заміряно: той самий вираз по всьому корпусу — 6–14 с, у діапазоні одного
#: прогону — мілісекунди. Понад стелю область і так майже весь корпус.
SCOPE_RANGES_MAX = 300


def _fts_rows(conn: sqlite3.Connection, expr: str, run_ids: list[int]
              ) -> Iterator[tuple[int]]:
    """Rowid рядків, що відповідають виразу, — у межах прогонів області.

    🔴 Діапазон rowid у самому запиті, а не фільтр після. Сторінки прогону
    вставляються підряд, тож його рядки лежать одним відрізком rowid; FTS5
    користується цим і не читає постингів поза ним. Без цього пошук по ОДНІЙ
    справі коштував стільки ж, скільки по корпусу (18 с замість долі секунди).

    ⚠ ОДИН запит на область, а не по прогону: вираз зі ста термами коштує
    півсекунди на саме розгортання, і 84 прогони еталона давали 58 с. Береться
    спільний відрізок від найменшого до найбільшого rowid області; чужі
    сторінки всередині нього відсіює викликач по `pages`.
    """
    total = conn.execute("select count(*) from runs").fetchone()[0]
    blocks = _scope_blocks(conn, run_ids) if run_ids and len(run_ids) < int(total) else []
    if not run_ids or len(run_ids) >= int(total) or len(blocks) > SCOPE_RANGES_MAX:
        yield from conn.execute("select rowid from fts where fts match ?", (expr,))
        return
    # 🔴 Блоки, а не один спільний відрізок. Голос, доіндексований пізніше,
    # лежить у кінці файлу, і відрізок від першого до останнього накривав
    # третину корпусу: 6.6 с проти 2.2 с сумою блоків (рецензія 08.09).
    for lo, hi in blocks:
        yield from conn.execute(
            "select rowid from fts where fts match ? and rowid between ? and ?",
            (expr, lo, hi))


def _scope_blocks(conn: sqlite3.Connection, run_ids: list[int]) -> list[tuple[int, int]]:
    """Суцільні відрізки rowid, які накривають сторінки цих прогонів."""
    spans: list[tuple[int, int]] = []
    for rid in run_ids:
        row = conn.execute("select min(id), max(id) from pages where run_id=?",
                           (rid,)).fetchone()
        if row and row[0] is not None:
            spans.append((int(row[0]), int(row[1])))
    spans.sort()
    out: list[tuple[int, int]] = []
    for a, b in spans:
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [(a << LINE_BITS, ((b + 1) << LINE_BITS) - 1) for a, b in out]


#: Скільки з'єднань читають блоби сторінок одночасно. Сторінки-кандидати
#: розкидані по всьому стору, і кожна — окреме випадкове читання з диска: один
#: потік стоїть у черзі глибини 1 й чекає ~0.2 мс на сторінку. Вісім потоків
#: читають ту саму пачку з 20 тис. сторінок за 0.45 с замість 4.2 с, далі
#: виграшу майже немає (16 — 0.35 с; замір 20.10.2026, NVMe, холодний кеш).
READ_THREADS = 8
#: Сторінок в одному запиті потоку-читача.
READ_CHUNK = 250
#: Від скількох сторінок читати потоками: старт з'єднань — мілісекунди.
READ_PARALLEL_FROM = 2 * READ_CHUNK


def _blobs_of(conn: sqlite3.Connection, chunk: list[int]) -> list[tuple[int, str]]:
    marks = ",".join("?" * len(chunk))
    return [(int(pid), zlib.decompress(blob).decode("utf-8"))
            for pid, blob in conn.execute(
                f"select id, cands from pages where id in ({marks})", chunk)
            if blob is not None]


def _blob_chunks(conn: sqlite3.Connection, pids: list[int], *,
                 progress: Callable[[int, int, str], None] | None,
                 cancel: Callable[[], bool] | None,
                 ) -> Iterator[list[tuple[int, str]]]:
    """Розпаковані блоби пачками, у порядку `pids`.

    🔴 Дооцінку швидкого каналу й свіп тримало не зіставлення, а диск: на
    пачці з 20 тис. сторінок читання блобів займало 4–8 с, бал — 1–2 с (замір
    20.10.2026). Тому велика вибірка читається кількома з'єднаннями в потоках:
    sqlite і zlib відпускають GIL, а розбір рядків лишається у викликача.

    ⚠ Потоки беруть СВОЇ з'єднання, тож бачать лише закомічене. Тому вони
    вмикаються, тільки коли викликач не тримає відкритої транзакції.
    """
    if len(pids) < READ_PARALLEL_FROM or conn.in_transaction:
        for i in range(0, len(pids), 500):
            if cancel and cancel():
                return
            if progress:
                progress(i, len(pids), "")
            yield _blobs_of(conn, pids[i:i + 500])
        return
    import threading
    from collections import deque
    from concurrent.futures import Future, ThreadPoolExecutor

    local = threading.local()
    opened: list[sqlite3.Connection] = []
    lock = threading.Lock()

    def job(chunk: list[int]) -> list[tuple[int, str]]:
        c = getattr(local, "conn", None)
        if c is None:
            c = local.conn = connect(readonly=True, any_thread=True)
            with lock:
                opened.append(c)
        return _blobs_of(c, chunk)

    chunks = [pids[i:i + READ_CHUNK] for i in range(0, len(pids), READ_CHUNK)]
    from nyshporka.core.cpu import usable_cores

    threads = max(1, min(READ_THREADS, usable_cores()))
    ex = ThreadPoolExecutor(max_workers=threads)
    # Вікно наперед, а не всі пачки разом: розпаковані сторінки в кілька разів
    # більші за потрібні рядки, і повна вибірка лягала б у пам'ять цілком.
    ahead: deque[Future[list[tuple[int, str]]]] = deque()
    try:
        nxt = 0
        for i in range(len(chunks)):
            while nxt < len(chunks) and len(ahead) < 2 * threads:
                ahead.append(ex.submit(job, chunks[nxt]))
                nxt += 1
            if cancel and cancel():
                return
            if progress:
                progress(i * READ_CHUNK, len(pids), "")
            yield ahead.popleft().result()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        for c in opened:
            c.close()


def _cands_batch(conn: sqlite3.Connection, wanted: dict[int, set[int]], *,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None,
                 ) -> Iterator[tuple[int, int, list[str]]]:
    """Кандидати потрібних рядків для всіх сторінок."""
    for part in _blob_chunks(conn, sorted(wanted), progress=progress, cancel=cancel):
        for pid, text in part:
            for no, rest in _lines_of(text, wanted[pid]):
                yield pid, no, rest.split(" ")


def _lines_of(text: str, nos: set[int]) -> Iterator[tuple[int, str]]:
    """Рядки блоба з потрібними номерами, за зростанням номера.

    🔴 Пошуком «⏎номер⇥» у C, а не розбором усієї сторінки в Python: потрібних
    рядків — 2–3 % (пачка з 20 тис. сторінок — 40 тис. рядків із 1.2–2.6 млн),
    і розбір решти був найдорожчою частиною дооцінки, щойно диск перестав нею
    бути (замір 20.10.2026). Блоб пише `_page_blob`: рядок на номер, номери
    зростають, слова через пробіл.
    """
    for no in sorted(nos):
        head = f"{no}\t"
        if text.startswith(head):
            start = len(head)
        else:
            at = text.find(f"\n{head}")
            if at < 0:
                continue
            start = at + 1 + len(head)
        end = text.find("\n", start)
        rest = text[start:] if end < 0 else text[start:end]
        if rest:
            yield no, rest


def _match_unique(norms: list[str], stems: list[str], thresh: int
                  ) -> dict[int, tuple[float, int]]:
    """Те саме, що `decode._matches`, гуртом на всі кандидати.

    З numpy — один `cdist` на всі стеми й усі ядра; без нього — `extract` по
    стему, як у gzip-індексу, по унікальних формах.

    ⚠ Дедуплікація форм тут свідомо НЕ робиться з numpy: у межах блока на
    60 тис. сторінок різних форм дві третини (склейки унікальні за побудовою),
    і словник на 4.5 млн рядків коштував 2.7 с проти 0.4 с виграшу в `cdist`
    (замір 08.09, третій раунд).
    """
    from nyshporka.search import decode as D

    got = _match_cdist(norms, stems, thresh)
    if got is not None:
        return got
    uniq: dict[str, int] = {}
    order: list[str] = []
    back: list[int] = []
    for n in norms:
        k = uniq.get(n)
        if k is None:
            k = len(order)
            uniq[n] = k
            order.append(n)
        back.append(k)
    best_u = D._matches(order, stems, thresh)
    out: dict[int, tuple[float, int]] = {}
    for j, k in enumerate(back):
        hit = best_u.get(k)
        if hit is not None:
            out[j] = hit
    return out


def _partial_bound(stem_len: int, lens: Any, thresh: int) -> Any:
    """Нижня межа `ratio`, без якої `partial_ratio ≥ thresh` неможливий.

    `ratio` = 200·LCS/(S+L). `partial_ratio` — це `ratio` стема проти вікна
    кандидата; вікно може бути коротшим за стем лише скраю, і найкоротше
    вікно w, здатне дати thresh, — w = t·S/(200−t). Звідси LCS зі стемом не
    менший за t/100·(S+w)/2, а LCS із цілим кандидатом — не менший за LCS із
    його вікном. Тож `ratio` цілого кандидата ≥ 200·LCS_min/(S+L). Мінус
    одиниця — запас на округлення до uint8.
    """
    import numpy as np

    w_min = thresh * stem_len / (200 - thresh)
    lcs_min = thresh / 100 * (stem_len + w_min) / 2
    return np.floor(200 * lcs_min / (stem_len + lens)) - 1


def _match_cdist(order: list[str], stems: list[str], thresh: int
                 ) -> dict[int, tuple[float, int]] | None:
    """Гуртове зіставлення через numpy, або None, якщо numpy немає."""
    try:
        import numpy as np
        from rapidfuzz import fuzz
        from rapidfuzz.process import cdist
    except ImportError:
        return None
    if not order:
        return {}
    lens = np.fromiter((len(n) for n in order), dtype=np.int32, count=len(order))
    best: dict[int, tuple[float, int]] = {}
    # Правило те саме, що в `decode._matches`: закороткий кандидат не
    # порівнюється, `partial_ratio` — лише коли кандидат не коротший за стем.
    # 🔴 `ratio` рахується з НИЗЬКИМ порогом: він і хіт, і передфільтр для
    # `partial_ratio`, який коштував 60 % зіставлення (27.6 млн пар на 16 тис.
    # сторінок), — див. `_partial_bound`. Той самий результат до бала.
    # `np.max`, а не метод: заглушки numpy 2.5 не мають перевантаження `ndarray.max()`
    # без осі (ні порожнього, ні з `axis=None`).
    lmax = int(np.max(lens)) if len(lens) else 0
    cutoff = 0
    if stems:
        cutoff = max(0, int(min(float(_partial_bound(len(s), np.int32(lmax), thresh))
                                for s in stems)))
    # ⚡ Один гуртовий прохід. Сам `ratio` дешевий; дорогі тут перетворення
    # пів мільйона рядків на кожен виклик `cdist` і маски numpy на кожен стем
    # (замір 21.10.2026 на пачці 0.53 млн слів × 22 стеми: другий прохід
    # 0.19 с, маски 0.29 с із 0.73). `score_hint`, `score_cutoff` і понад два
    # потоки на цей прохід не впливають.
    r = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=cutoff,
              dtype=np.uint8, workers=-1)
    span = np.arange(lmax + 1, dtype=np.int32)
    gates: dict[int, Any] = {}
    for si, stem in enumerate(stems):
        size = len(stem)
        need = max(4, int(size * 0.6))
        floor = max(need, size)
        gate = gates.get(size)
        if gate is None:
            # Межа `partial` залежить лише від довжин стема й слова: таблиця на
            # довжину стема, закороткому слову — недосяжна (256).
            b = _partial_bound(size, span, thresh)
            gate = gates[size] = np.where(span >= floor, np.clip(b, 0, 255),
                                          256).astype(np.int16)[lens]
        row = r[si]
        hit: dict[int, int] = {}
        # ⚠ Хіт за `ratio` — із порогом у самому rapidfuzz: там поріг
        # порівнюється з дробовим балом, а uint8 округлює 77.8 до 78. Тож
        # округлений бал ≥ порога лише відбирає кандидатів (дробовий ≥ порога
        # завжди округлюється не нижче), а точний бал рахується на них.
        cand = np.flatnonzero(row >= thresh)
        if len(cand):
            cand = cand[lens[cand] >= need]
        if len(cand):
            exact = cdist([stem], [order[int(j)] for j in cand], scorer=fuzz.ratio,
                          score_cutoff=thresh, dtype=np.uint8, workers=-1)[0]
            for j, v in zip(cand.tolist(), exact.tolist(), strict=True):
                if v >= thresh:
                    hit[j] = v
        idx = np.flatnonzero(row >= gate)
        if len(idx):
            pr = cdist([stem], [order[int(j)] for j in idx], scorer=fuzz.partial_ratio,
                       score_cutoff=thresh, dtype=np.uint8, workers=-1)[0]
            for j, v in zip(idx.tolist(), pr.tolist(), strict=True):
                if v >= thresh and v > hit.get(j, 0):
                    hit[j] = v
        for j, v in hit.items():
            cur = best.get(j)
            if cur is None or v > cur[0]:
                best[j] = (float(v), si)
    return best


def _cands_of(conn: sqlite3.Connection, pid: int, nos: set[int]
              ) -> list[tuple[int, list[str]]]:
    """Кандидати потрібних рядків сторінки з блоба `pages.cands`."""
    row = conn.execute("select cands from pages where id=?", (pid,)).fetchone()
    if not row or row[0] is None:
        return []
    return [(no, rest.split(" "))
            for no, rest in _lines_of(zlib.decompress(row[0]).decode("utf-8"), nos)]


# ── кеш свіпів по прогонах ───────────────────────────────────────────────────
#: Версія формату кешу свіпів; зміна зіставлення — новий ключ, старі рядки
#: просто не читаються.
SWEEP_CACHE_VERSION = 1

#: Один хіт у кеші: сторінка, рядок, форма, бал, стем.
SweepRow = tuple[int, int, str, int, str]


def _sweep_key(stems: list[str], thresh: int) -> str:
    return hashlib.blake2b(
        json.dumps([sorted(stems), int(thresh), SWEEP_CACHE_VERSION],
                   ensure_ascii=False).encode("utf-8"), digest_size=10).hexdigest()


def _pack(rows: list[SweepRow]) -> bytes:
    return zlib.compress("\n".join(
        f"{pid}\t{no}\t{norm}\t{score}\t{stem}" for pid, no, norm, score, stem in rows
    ).encode("utf-8"), 6)


def _unpack(body: bytes | None) -> list[SweepRow]:
    if not body:
        return []
    out: list[SweepRow] = []
    for line in zlib.decompress(body).decode("utf-8").split("\n"):
        if not line:
            continue
        pid, no, norm, score, stem = line.split("\t")
        out.append((int(pid), int(no), norm, int(score), stem))
    return out


def _blocks_by_pages(conn: sqlite3.Connection, run_ids: list[int]) -> list[list[int]]:
    """Прогони блоками не більше `TRIGRAM_SCOPE_PAGES` сторінок, за порядком id."""
    sizes: dict[int, int] = {}
    ids = sorted(run_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for rid, n in conn.execute(f"select id, pages from runs where id in ({marks})", chunk):
            sizes[int(rid)] = int(n or 0)
    out: list[list[int]] = []
    cur: list[int] = []
    acc = 0
    for rid in ids:
        n = sizes.get(rid, 0)
        if cur and acc + n > TRIGRAM_SCOPE_PAGES:
            out.append(cur)
            cur, acc = [], 0
        cur.append(rid)
        acc += n
    if cur:
        out.append(cur)
    return out


def _sweep_block(conn: sqlite3.Connection, stems: list[str], run_ids: list[int],
                 thresh: int, *, progress: Callable[[int, int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None,
                 ) -> dict[int, list[SweepRow]] | None:
    """Свіп одного блока прогонів триграмами. None — перервано."""
    from nyshporka import htr_store as S

    expr = match_expr(stems)
    run_set = set(run_ids)
    raw: dict[int, set[int]] = {}
    for (rid,) in _fts_rows(conn, expr, run_ids):
        raw.setdefault(rid >> LINE_BITS, set()).add(rid & MAX_LINES)
    pages = _pages_for(conn, set(raw), run_set)
    # 🔴 Разом із рядком беруться кілька наступних. Склейка переносу
    # («Липовень» ⏎ «комъ») приписується рядку з ГОЛОВОЮ, а k-грам стема
    # стоїть у рядку з хвостом; без розширення хіт зникав би саме там, де
    # прізвище розірване, — рівно те, заради чого склейка існує.
    reach = S.LINE_BREAK_WINDOW
    wanted: dict[int, set[int]] = {}
    for pid, nos in raw.items():
        if pid in pages:
            wanted[pid] = {n for no in nos for n in range(no, no + reach + 1)}
    # Один виклик rapidfuzz на всі кандидати, а не по рядку, і кандидати —
    # ГОТОВІ, з блоба сторінки: породжувати їх наново в Python для сотень
    # тисяч рядків коштувало 190 с на запит по корпусу.
    norms: list[str] = []
    starts: list[int] = []
    owner: list[tuple[int, int]] = []
    for pid, no, ns in _cands_batch(conn, wanted, progress=progress, cancel=cancel):
        starts.append(len(norms))
        owner.append((pid, no))
        norms.extend(ns)
    if cancel and cancel():
        return None
    by_line: dict[tuple[int, int], tuple[float, int, int]] = {}
    for j, (sc, si) in _match_unique(norms, stems, thresh).items():
        key = owner[bisect_right(starts, j) - 1]
        cur = by_line.get(key)
        if cur is None or sc > cur[0]:
            by_line[key] = (sc, j, si)
    out: dict[int, list[SweepRow]] = {rid: [] for rid in run_ids}
    for (pid, no), (sc, j, si) in by_line.items():
        out[pages[pid][0]].append((pid, no, norms[j], round(sc), stems[si]))
    return out


#: Скільки процесів чешуть корпус одночасно; `None` — від заліза (`sweep_workers`).
#: Блок — розбір блобів кандидатів у Python (GIL), тож паралелять процеси, не потоки.
SWEEP_WORKERS: int | None = None
#: Змінна оточення, що перебиває і залізо, і `SWEEP_WORKERS`; `1` — по одному.
SWEEP_WORKERS_ENV = "NYSH_SWEEP_WORKERS"
#: Пам'ять одного воркера, ГБ. Пачка дооцінки швидкого каналу (20 тис. сторінок)
#: — пік 0,61 приватної пам'яті (замір 22.10.2026), тут із запасом.
#: 🔴 Блок свіпу триграмами — НЕ 1,5 ГБ, як записали 13.10: корпусний свіп роду
#: (23 написання, без швидкого індексу) тримав у трьох воркерах 2,5 / 5,1 / 7,7 ГБ
#: приватної пам'яті, і система зняла процеси через брак пам'яті, не дочекавшись
#: піку (22.10.2026). 8 — нижня межа поміряного, а не стеля; цей шлях вмикається,
#: коли швидкий індекс відмовив запиту як заширокому.
BLOCK_WORKER_GB = 8.0
FAST_WORKER_GB = 0.75
#: Яку частку ВІЛЬНОЇ пам'яті можна віддати воркерам. 11.10.2026 система вбила
#: три важкі процеси, що стояли поруч із WSL і редактором, — половина лишає
#: запас на те, що запуститься поруч під час свіпу.
MEM_SHARE = 0.5


def sweep_workers(n_blocks: int, *, worker_gb: float = BLOCK_WORKER_GB) -> int:
    """Скільки процесів дати свіпу: від заліза, а не сталою.

    🔴 Нишпорка йде на різне залізо: стала «3» на ноутбуці з 8 ГБ — це 4,5 ГБ
    воркерам понад сам процес пошуку, а на машині з 12 ядрами й 32 ГБ вона
    лишає половину ядер без роботи (корпус: 3 процеси — 79 с, 6 — 62–67 с, замір
    22.10.2026). Тому: фізичні ядра, половина вільної пам'яті на пам'ять
    воркера, не більше пачок. Змінна оточення чи
    `SWEEP_WORKERS` перебивають розрахунок.
    """
    raw = os.environ.get(SWEEP_WORKERS_ENV, "").strip()
    n: int | None = None
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = None
    if n is None:
        n = SWEEP_WORKERS if SWEEP_WORKERS is not None else _hardware_workers(worker_gb)
    return max(1, min(n, n_blocks))


def _hardware_workers(worker_gb: float) -> int:
    from nyshporka.core.cpu import usable_cores

    by_cores = usable_cores()
    try:
        import psutil

        # Фізичні ядра, а не логічні: бал rapidfuzz у кожному воркері й так бере
        # кілька потоків, і понад фізичні ядра процеси лише ділять ті самі. На
        # 6 фізичних / 12 логічних: 6 процесів — 67 с, 11 — 64 с за вдвічі
        # більшої пам'яті (замір 22.10.2026).
        physical = psutil.cpu_count(logical=False)
        if physical:
            by_cores = min(by_cores, int(physical))
        free_gb = psutil.virtual_memory().available / 2 ** 30
    except Exception:
        return max(1, min(by_cores, 2))     # пам'ять невідома — обережно
    by_mem = int(free_gb * MEM_SHARE / max(worker_gb, 0.1))
    return max(1, min(by_cores, by_mem))


def _block_init(ws: Any) -> None:
    """Воркер працює в просторі того, хто кликав: `--workspace` живе лише в
    батьківському процесі, і без цього воркер відкрив би чужий стор."""
    from nyshporka.core.workspace import use

    use(ws)


def _block_job(stems: list[str], block: list[int], thresh: int
               ) -> dict[int, list[SweepRow]] | None:
    conn = connect(readonly=True)
    try:
        return _sweep_block(conn, stems, block, thresh)
    finally:
        conn.close()


def _sweep_parallel(conn: sqlite3.Connection, stems: list[str], blocks: list[list[int]],
                    thresh: int, key: str, workers: int, *,
                    progress: Callable[[int, int, str], None] | None = None,
                    cancel: Callable[[], bool] | None = None,
                    ) -> tuple[list[dict[int, list[SweepRow]] | None], bool]:
    """Блоки в `workers` процесах. Кеш кожного блока пишеться, щойно він готовий:
    обірваний свіп не губить прочесане. Повертає результати В ПОРЯДКУ блоків —
    той самий порядок хітів, що й у послідовного проходу."""
    import multiprocessing as mp
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    from nyshporka.core.workspace import workspace

    out: list[dict[int, list[SweepRow]] | None] = [None] * len(blocks)
    ctx = mp.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                             initializer=_block_init, initargs=(workspace(),))
    cancelled = False
    try:
        futs = {ex.submit(_block_job, stems, b, thresh): i for i, b in enumerate(blocks)}
        pending = set(futs)
        done_n = 0
        while pending:
            if cancel and cancel():
                cancelled = True
                break
            # Таймаут лише заради `cancel`: блок іде десятки секунд, і людина,
            # що натиснула «стоп», не мусить чекати його кінця.
            done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for f in done:
                got = f.result()
                i = futs[f]
                out[i] = got
                done_n += 1
                if progress:
                    progress(done_n, len(blocks), PHASE_SWEEP)
                if got is not None:
                    _sweep_put(conn, key, got)
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    return out, cancelled


def _sweep_put(conn: sqlite3.Connection, key: str, got: dict[int, list[SweepRow]]) -> bool:
    """Покласти результати блока в кеш; замок іншої сесії — просто без кешу."""
    try:
        conn.execute("begin")
        conn.executemany("insert or replace into sweeps(run_id, key, body) values(?,?,?)",
                         [(rid, key, _pack(rows)) for rid, rows in got.items()])
        conn.commit()
        return True
    except sqlite3.OperationalError:
        with contextlib.suppress(sqlite3.Error):
            conn.rollback()
        return False


#: Фази свіпу для поступу. Людина бачить їх у черзі робіт: «індекс нових
#: прогонів 3 із 8» і «блоки корпусу 12 із 40» — дві різні роботи, і одне
#: «прогін 0 із 0» на обидві виглядало як зависання (холодний прохід 07.10.2026).
PHASE_INDEX = "індекс нових прогонів"
PHASE_SWEEP = "блоки корпусу"
PHASE_PAGES = "сторінки корпусу"
PHASE_FAST = "швидкий індекс: рядки-кандидати"


def sweep(stems: list[str], runs: list[str], *, thresh: int = 78,
          build_budget: int = 0,
          progress: Callable[[int, int, str], None] | None = None,
          cancel: Callable[[], bool] | None = None,
          fast: bool | None = None) -> dict[str, Any]:
    """Прочесати прогони через стор. Та сама відповідь, що `decode.sweep`.

    🔴 Або всі, або жоден — як і в gzip-індексу: якщо застарілих прогонів
    більше за бюджет, жоден не збирається, і `unindexed` каже, скільки лишилось
    поза пошуком. Зібрати «скільки встигнеться» означало б віддати нуль зі
    знаменником, що залежить від порядку тек.

    🔴 Кеш по ПРОГОНАХ, ключ — стеми й поріг. Той самий рід шукають по корпусу
    щосесії, а прочитаних справ між сесіями додається кілька: перший свіп
    рахує все (хвилини), кожен наступний — лише нові чи перечитані прогони.
    Кеш живе з прогоном: перечитали — `_delete_run` зніс і його рядок кешу.

    🔴 Один режим передфільтра — триграми, блоками до `TRIGRAM_SCOPE_PAGES`.
    Режим «корпусу» на парах грам губив 5 % сторінок саме в смузі 78–84, де
    живуть скалічені форми, і при цьому коштував 48 с FTS (рецензія 08.09,
    третій раунд); триграми в межах блока на 30 тис. сторінок губили 0 сторінок.
    """

    conn = connect()
    try:
        known = stamps(conn)
        st = stamps_for(runs)
        stale = [r for r in runs if st[r] and known.get(r) != st[r]]
        if 0 < len(stale) <= max(0, build_budget):
            for i, r in enumerate(stale, 1):
                if cancel and cancel():
                    # Спинили посеред індексування: прочісувати нічого не
                    # починаємо — відповідь була б на індексі, що сам не знає,
                    # скільки в ньому бракує.
                    return {"hits": [], "scanned": 0, "runs": len(runs),
                            "unindexed": len(runs), "backend": "store", "cached": 0,
                            "computed": 0, "cancelled": True,
                            "rules_stale": rules_stale(conn)}
                if progress:
                    progress(i, len(stale), PHASE_INDEX)
                try:
                    # Пошук людини не чекає пів години: лише `BUSY_TIMEOUT`.
                    index_run_if_stale(conn, r)
                except sqlite3.OperationalError as exc:
                    # Інша сесія тримає стор на запис: цей прогін лишається
                    # поза пошуком і йде в `unindexed`, а не валить запит.
                    if not _locked_error(exc):
                        raise
                    with contextlib.suppress(sqlite3.Error):
                        conn.rollback()
            known = stamps(conn)
            st = stamps_for(runs)
        ready = [r for r in runs if st[r] and known.get(r) == st[r]]
        missing = len(runs) - len(ready)
        ids = _run_ids(conn, ready)
        by_id = {v: k for k, v in ids.items()}
        hits: list[dict[str, Any]] = []
        rstale = rules_stale(conn)
        if not ids or not stems:
            return {"hits": hits, "scanned": len(ready), "runs": len(runs),
                    "unindexed": missing, "backend": "store", "cached": 0,
                    "computed": 0, "rules_stale": rstale}
        key = _sweep_key(stems, thresh)
        run_ids = list(ids.values())
        cached: dict[int, bytes | None] = {}
        with contextlib.suppress(sqlite3.OperationalError):
            for i in range(0, len(run_ids), 500):
                chunk = run_ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for rid, body in conn.execute(
                        f"select run_id, body from sweeps where key=? and run_id in ({marks})",
                        [key, *chunk]):
                    cached[int(rid)] = body
        todo = [rid for rid in run_ids if rid not in cached]
        rows: list[SweepRow] = []
        for body in cached.values():
            rows.extend(_unpack(body))
        # ⚡ Передфільтр Tantivy (`search.fastidx`) для прогонів, які індекс несе
        # під свіжим штампом; решта — триграмами, як завжди.
        fast_runs: list[int] = []
        fast_rows = 0
        fast_error = ""
        cancelled = False
        if todo and _fast_wanted(fast):
            from nyshporka.search import fastidx as FX

            # Запит до індексу — 12–50 с незалежно від області; свіп малої
            # області дешевший. Індекс береться, коли область велика, коли
            # відповідь для цих стемів уже порахована, або коли його просили явно.
            if fast or FX.known(stems) or _pages_of_runs(conn, todo) >= FAST_MIN_PAGES:
                fast_runs = FX.covered(conn, todo)
        if fast_runs:
            try:
                got_fast = _sweep_fast_cached(conn, stems, fast_runs, thresh, key,
                                              whole=len(fast_runs) == _runs_total(conn),
                                              progress=progress, cancel=cancel)
            except _FastCancelled:
                cancelled = True
                fast_runs = []
                todo = []
            except Exception as exc:  # індекс лише прискорює
                # Зіпсований чи зайнятий індекс не валить пошук: ті самі прогони
                # іде прочесати точний шлях, триграми (рецензія 20.10.2026).
                fast_error = f"{type(exc).__name__}: {exc}"
                from nyshporka.search import fastidx as FX

                why = ("заширокий для швидкого індексу" if isinstance(exc, FX.TooBroad)
                       else "швидкий індекс недоступний")
                print(f"⚠ {why} ({exc}) — шукаю свіпом", file=sys.stderr)
                fast_runs = []
            else:
                for lst in got_fast.values():
                    rows.extend(lst)
                    fast_rows += len(lst)
                fast_set = set(fast_runs)
                todo = [rid for rid in todo if rid not in fast_set]
        blocks = _blocks_by_pages(conn, todo)
        workers = sweep_workers(len(blocks))
        if workers > 1:
            outs, cancelled = _sweep_parallel(conn, stems, blocks, thresh, key, workers,
                                              progress=progress, cancel=cancel)
            for got in outs:
                if got is None:
                    continue
                for lst in got.values():
                    rows.extend(lst)
            blocks = []
        for bi, block in enumerate(blocks, 1):
            if progress:
                progress(bi, len(blocks), PHASE_SWEEP)
            # Один блок — поступ зсередини нього (сторінки кандидатів): інакше на
            # весь пошук стояло «блоки корпусу 1 із 1».
            inner = None
            if progress and len(blocks) == 1:
                def inner(i: int, n: int, _w: str) -> None:
                    progress(i, n, PHASE_PAGES)
            got = _sweep_block(conn, stems, block, thresh, progress=inner, cancel=cancel)
            if got is None:
                cancelled = True
                break
            for lst in got.values():
                rows.extend(lst)
            _sweep_put(conn, key, got)
        if fast_runs and not fast_rows and not cancelled:
            # 🔴 Нуль не друкується на передфільтрі: швидкий канал губить частину
            # смуги 90–94, тож «немає» по області підтверджує свіп триграмами.
            # Рахуються рядки САМЕ швидкої частини: хіти з кешу свіпу по інших
            # прогонах тієї ж області нуля швидкого каналу не підтверджують
            # (рецензія 20.10.2026). Одиниця — область, як усюди в пакеті: пошук
            # по серії питає справу за справою, і нуль справи підтверджує свіп
            # цієї справи; поштучно по прогонах корпусу це був би повний свіп.
            for block in _blocks_by_pages(conn, fast_runs):
                got = _sweep_block(conn, stems, block, thresh, cancel=cancel)
                if got is None:
                    cancelled = True
                    break
                for lst in got.values():
                    rows.extend(lst)
                _sweep_put(conn, key, got)
            fast_runs = []
        pages = _pages_for(conn, {r[0] for r in rows}, set(run_ids))
        for pid, no, norm, score, stem in rows:
            got_page = pages.get(pid)
            if got_page is None:
                continue
            hits.append({"name": by_id[got_page[0]], "page": got_page[1], "line_no": no,
                         "line_index": no - 1, "norm": norm, "stem": stem, "score": score})
        return {"hits": hits, "scanned": len(ready), "runs": len(runs),
                "unindexed": missing, "backend": "store", "cached": len(cached),
                "computed": len(todo), "cancelled": cancelled, "rules_stale": rstale,
                "fast_runs": len(fast_runs), "fast_error": fast_error}
    finally:
        conn.close()


#: Змінна оточення: `0` — не брати передфільтр Tantivy, навіть якщо індекс є.
FAST_ENV = "NYSH_FAST"
#: Від скількох сторінок в області передфільтр Tantivy дешевший за свіп: свіп
#: корпусу (3 млн стор.) — ~4,6 хв трьома воркерами, запит до індексу — 12–50 с
#: плюс дооцінка рядків (заміри 20.10.2026).
FAST_MIN_PAGES = 200_000


def _pages_of_runs(conn: sqlite3.Connection, run_ids: list[int]) -> int:
    total = 0
    for i in range(0, len(run_ids), 500):
        chunk = run_ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        total += int(conn.execute(f"select coalesce(sum(pages), 0) from runs where id in ({marks})",
                                  chunk).fetchone()[0])
    return total


def _fast_wanted(fast: bool | None) -> bool:
    if fast is not None:
        return fast
    if os.environ.get(FAST_ENV, "").strip() == "0":
        return False
    from nyshporka.search import fastidx as FX

    return FX.exists()


def _runs_total(conn: sqlite3.Connection) -> int:
    return int(conn.execute("select count(*) from runs").fetchone()[0])


class _FastCancelled(Exception):
    """Людина спинила пошук посеред швидкого каналу: нічого не кешувати."""


def _sweep_fast_cached(conn: sqlite3.Connection, stems: list[str], run_ids: list[int],
                       thresh: int, key: str, *, whole: bool,
                       progress: Callable[[int, int, str], None] | None = None,
                       cancel: Callable[[], bool] | None = None,
                       ) -> dict[int, list[SweepRow]]:
    """Прогони через Tantivy, з кешем під окремим ключем: його відповідь не та
    сама, що в триграм, і змішувати їх в одному рядку кешу не можна."""
    from nyshporka.search import fastidx as FX

    fkey = f"{key}{FAST_KEY_SUFFIX}:s{FX.SCHEMA}q{FX.QUERY_VERSION}"
    out: dict[int, list[SweepRow]] = {}
    with contextlib.suppress(sqlite3.OperationalError):
        for i in range(0, len(run_ids), 500):
            chunk = run_ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for rid, body in conn.execute(
                    f"select run_id, body from sweeps where key=? and run_id in ({marks})",
                    [fkey, *chunk]):
                out[int(rid)] = _unpack(body)
    todo = [rid for rid in run_ids if rid not in out]
    if todo:
        got = _sweep_fast(conn, stems, todo, thresh, whole=whole and not out,
                          progress=progress, cancel=cancel)
        _sweep_put(conn, fkey, got)
        out.update(got)
    return out


#: Ключ кешу відповідей швидкого каналу — поруч із ключем свіпу.
FAST_KEY_SUFFIX = ":fast"


def _sweep_fast(conn: sqlite3.Connection, stems: list[str], run_ids: list[int],
                thresh: int, *, whole: bool = False,
                progress: Callable[[int, int, str], None] | None = None,
                cancel: Callable[[], bool] | None = None) -> dict[int, list[SweepRow]]:
    """Рядки-кандидати з Tantivy → той самий `_match_unique` лише по них.
    `whole` — прогони покривають увесь стор, фільтр за ними зайвий.

    🔴 Дооцінка поширеного прізвища — мільйони рядків, і в одному процесі вона
    програвала свіпу, який іде трьома воркерами («Мельник» на корпусі: 6 хв
    дооцінки проти 4 хв усього свіпу, замір 20.10.2026). Тому від
    `FAST_PARALLEL_PAGES` сторінок вона йде тими самими воркерами, що й свіп.
    """
    from nyshporka.search import fastidx as FX

    # Прогін кожного рядка індекс віддає сам (поле `run`): звірка сторінок зі
    # стором (`_pages_for`) на мільйоні кандидатів коштувала 121 с — більше за
    # усю дооцінку (замір 20.10.2026).
    if progress:
        progress(0, 1, PHASE_FAST)
    got = FX.by_run(stems)
    if cancel and cancel():
        raise _FastCancelled
    run_of: dict[int, int] = {}
    wanted: dict[int, set[int]] = {}
    for rid in (got.keys() if whole else run_ids):
        for pid, no in got.get(rid, ()):
            run_of[pid] = rid
            wanted.setdefault(pid, set()).add(no)
    pids = sorted(wanted)
    chunks = [{p: sorted(wanted[p]) for p in pids[i:i + FAST_CHUNK_PAGES]}
              for i in range(0, len(pids), FAST_CHUNK_PAGES)]
    workers = (sweep_workers(len(chunks), worker_gb=FAST_WORKER_GB)
               if len(pids) >= FAST_PARALLEL_PAGES else 1)
    if workers > 1:
        import multiprocessing as mp
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

        from nyshporka.core.workspace import workspace

        parts: list[list[SweepRow]] = []
        ex = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_block_init, initargs=(workspace(),))
        try:
            pending = {ex.submit(_fast_job, stems, ch, thresh) for ch in chunks}
            while pending:
                # Таймаут лише заради `cancel`: пачка йде секунди, і «стоп» не
                # мусить чекати кінця всієї дооцінки (рецензія 20.10.2026).
                if cancel and cancel():
                    raise _FastCancelled
                done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                parts.extend(f.result() for f in done)
                if progress:
                    progress(len(parts), len(chunks), PHASE_FAST)
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
    else:
        parts = []
        for i, ch in enumerate(chunks, 1):
            if cancel and cancel():
                raise _FastCancelled
            parts.append(_rerank_lines(conn, stems, ch, thresh))
            if progress:
                progress(i, len(chunks), PHASE_FAST)
    out: dict[int, list[SweepRow]] = {rid: [] for rid in run_ids}
    for part in parts:
        for pid, no, norm, sc, stem in part:
            out.setdefault(run_of[pid], []).append((pid, no, norm, sc, stem))
    return out


#: Сторінок-кандидатів на одну пачку дооцінки.
FAST_CHUNK_PAGES = 20_000
#: Від скількох сторінок-кандидатів дооцінка йде воркерами: старт процесу —
#: секунди, і для малої видачі він дорожчий за саму роботу.
FAST_PARALLEL_PAGES = 40_000


def _rerank_lines(conn: sqlite3.Connection, stems: list[str], chunk: dict[int, list[int]],
                  thresh: int) -> list[SweepRow]:
    """(pid, рядок, слово, бал, стем) для рядків пачки з балом не нижче порога."""
    norms: list[str] = []
    starts: list[int] = []
    owner: list[tuple[int, int]] = []
    for pid, no, ns in _cands_batch(conn, {p: set(v) for p, v in chunk.items()}):
        starts.append(len(norms))
        owner.append((pid, no))
        norms.extend(ns)
    by_line: dict[tuple[int, int], tuple[float, int, int]] = {}
    for j, (sc, si) in _match_unique(norms, stems, thresh).items():
        k = owner[bisect_right(starts, j) - 1]
        cur = by_line.get(k)
        if cur is None or sc > cur[0]:
            by_line[k] = (sc, j, si)
    return [(pid, no, norms[j], round(sc), stems[si])
            for (pid, no), (sc, j, si) in by_line.items()]


def _fast_job(stems: list[str], chunk: dict[int, list[int]], thresh: int) -> list[SweepRow]:
    conn = connect(readonly=True)
    try:
        return _rerank_lines(conn, stems, chunk, thresh)
    finally:
        conn.close()


# ── друге слово поруч із першим ──────────────────────────────────────────────
#: Місце першого слова: прогін, сторінка, рядок (з одиниці), слово-кандидат.
Spot = tuple[str, int | str, int, str]


def near_lines(stems: list[str], spots: list[Spot], *, window: int = 1,
               thresh: int = 78, first: list[str] | None = None,
               ) -> dict[int, tuple[int, str, int, str]]:
    """Друге слово у вікні ±`window` рядків довкола кожного місця першого.

    Повертає індекс місця → (рядок, слово, бал, стем) найкращого збігу; на
    рівних балах — ближчий рядок. Бал виносить той самий `_match_unique`, що й
    прізвищний свіп, тож поріг і правило довжини ті самі.

    🔴 Друге слово судиться лише на рядках біля першого, а не по всій області:
    ім'я чи село на корпусі стоїть на мільйонах рядків, і окремий свіп по ньому
    коштував би більше, ніж перший. Перетин після двох свіпів дав би ту саму
    відповідь за в рази більшу ціну.

    🔴 Кандидат, схожий на перше слово (`first` — його стеми) не менше, ніж на
    друге, другим не зараховується: це саме перше слово або склейка з ним.
    Без цього «Іван» знаходився б усередині «Іваненко» на тому самому місці.
    Правило «не міститься в першому» тут не годиться: кандидати стору — це й
    пари слів, і перше слово часто знайдене парою «Иванъ Вербищинскій», яка
    містить справжнє ім'я поруч.
    """
    if not spots or not stems:
        return {}
    conn = connect(readonly=True)
    try:
        at = _spot_pids(conn, spots)
        wanted: dict[int, set[int]] = {}
        for (_run, _page, no, _w), pid in zip(spots, at, strict=True):
            if pid is not None:
                wanted.setdefault(pid, set()).update(range(max(0, no - window), no + window + 1))
        norms: list[str] = []
        owner: list[tuple[int, int]] = []
        for pid, no, ns in _cands_batch(conn, wanted):
            norms.extend(ns)
            owner.extend([(pid, no)] * len(ns))
    finally:
        conn.close()
    by_line: dict[tuple[int, int], list[tuple[int, str, int]]] = {}
    for j, (sc, si) in _match_unique(norms, stems, thresh).items():
        by_line.setdefault(owner[j], []).append((round(sc), norms[j], si))
    as_first: dict[str, int] = {}
    if first:
        words = sorted({w for hits in by_line.values() for _sc, w, _si in hits})
        as_first = {words[j]: round(sc)
                    for j, (sc, _si) in _match_unique(words, first, thresh).items()}
    out: dict[int, tuple[int, str, int, str]] = {}
    for i, (_run, _page, no, word) in enumerate(spots):
        pid = at[i]
        if pid is None:
            continue
        best: tuple[tuple[int, int, int], int, str, int] | None = None
        for dist in range(window + 1):
            for line in (no,) if dist == 0 else (no - dist, no + dist):
                for sc, w, si in by_line.get((pid, line), ()):
                    if w == word or as_first.get(w, 0) >= sc:
                        continue
                    # на рівних — ближчий рядок, далі найкоротший кандидат:
                    # саме слово, а не пара з ним («Иванъ», не «родился Иванъ»)
                    key = (sc, -dist, -len(w))
                    if best is None or key > best[0]:
                        best = (key, line, w, si)
        if best is not None:
            out[i] = (best[1], best[2], best[0][0], stems[best[3]])
    return out


def _spot_pids(conn: sqlite3.Connection, spots: list[Spot]) -> list[int | None]:
    """pid сторінки кожного місця (None — сторінки в сторі немає)."""
    run_ids = _run_ids(conn, sorted({str(s[0]) for s in spots}))
    pid_of: dict[tuple[str, str], int] = {}
    for run, rid in run_ids.items():
        for pid, page in conn.execute("select id, page from pages where run_id=?", (rid,)):
            pid_of[(run, str(page))] = int(pid)
    return [pid_of.get((str(run), str(page))) for run, page, _no, _w in spots]


#: Пара слів одного рядка: (слово, бал, стем) лівого й (слово, бал, стем) правого.
Follow = tuple[tuple[str, int, str], tuple[str, int, str]]


def follow_lines(left: list[str], right: list[str], spots: list[Spot], *,
                 thresh: int = 78) -> dict[int, Follow]:
    """Праве слово ОДРАЗУ після лівого в тому самому рядку: ім'я + по батькові.

    Повертає індекс місця → найсильніша така пара в рядку місця. Слова — норми
    токенів сирого рядка, бал — той самий `_match_unique`, що в свіпі.

    🔴 Порядок і сусідство судяться по сирому рядку, а не по кандидатах стору:
    кандидати — це ще й пари та склейки слів, записані без роздільника, тож із
    них не видно, котре слово стоїть за котрим. Через це `near` на корпусі давав
    «Кирила Осипова» (по батькові навпаки) і двох різних людей сусідніх рядків
    на рівних із «Іосифъ Кириловъ» — 97 тис. пар, верхні 300 усі з балом 100
    (20.10.2026).

    ⚠ Правила `near_lines` «схоже на перше — не друге» тут немає й не треба:
    ліве й праве — різні токени рядка, тож саме перше слово другим стати не
    може, а «Петръ Петровъ» (ім'я й по батькові одного кореня) — справжня пара.
    Тому й відбір рядків для цього режиму (`textops.near`) іде без нього.

    ⚠ Межа — рядок: пара, розірвана переносом («…Іосифъ» / «Кириловъ…»), тут
    не знаходиться; її ловить звичайний `near` з вікном 1.
    """
    if not spots or not left or not right:
        return {}
    conn = connect(readonly=True)
    try:
        at = _spot_pids(conn, spots)
        nos: dict[int, set[int]] = {}
        for (_run, _page, no, _w), pid in zip(spots, at, strict=True):
            if pid is not None:
                nos.setdefault(pid, set()).add(no)
        line_of: dict[tuple[int, int], str] = {}
        for pid, want in nos.items():
            lines = _raw_lines(conn, pid)
            for no in want:
                if 0 < no <= len(lines):
                    line_of[(pid, no)] = lines[no - 1]
    finally:
        conn.close()
    from nyshporka import htr_store as S

    # Сусіди — лише через пробіл: кома, крапка чи риска між словами — це вже
    # перелік чи межа речення («Іосифъ, Кириловъ» — двоє людей), а не ім'я з
    # по батькові.
    adj: list[list[tuple[str, str]]] = []
    for (_run, _page, no, _w), pid in zip(spots, at, strict=True):
        line = line_of.get((pid, no), "") if pid is not None else ""
        ms = list(S._TOKEN_RE.finditer(line))
        adj.append([(_norm(m.group()), _norm(n.group())) for m, n in itertools.pairwise(ms)
                    if line[m.end():n.start()].isspace()])
    words = sorted({w for ps in adj for pair in ps for w in pair if w})
    as_left = {words[j]: (round(sc), si)
               for j, (sc, si) in _match_unique(words, left, thresh).items()}
    as_right = {words[j]: (round(sc), si)
                for j, (sc, si) in _match_unique(words, right, thresh).items()}
    out: dict[int, Follow] = {}
    for i, ps in enumerate(adj):
        best: tuple[int, Follow] | None = None
        for a, b in ps:
            la, rb = as_left.get(a), as_right.get(b)
            if la is None or rb is None:
                continue
            got = ((a, la[0], left[la[1]]), (b, rb[0], right[rb[1]]))
            if best is None or la[0] + rb[0] > best[0]:
                best = (la[0] + rb[0], got)
        if best is not None:
            out[i] = best[1]
    return out


# ── регекс по сирому тексту ──────────────────────────────────────────────────
_LIT_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_VERBOSE_FLAG = re.compile(r"\(\?[a-zA-Z-]*x[a-zA-Z-]*[:)]")


def literals_of(pattern: str) -> list[str] | None:
    """Літерали, без яких рядок регексу не збігається, — по одному на гілку.

    Повертає перелік, де кожна верхньорівнева гілка представлена своїм
    найдовшим літералом (≥ 3 літери), або None, якщо хоч одна гілка такого не
    має: тоді передфільтр не звужує без втрат, і сканується все.

    ⚠ Свідомо груба розкладка. Літерал, за яким іде квантифікатор, вкорочується
    на останню літеру; символ, що стоїть перед `|` у групі, не розбирається.
    Гірше, що може статись, — надто широкий передфільтр; звузити нуль він не
    може, бо береться найдовший літерал гілки, а не всі.
    """
    # 🔴 Прапор «x» (verbose): пробіли й «# коментар» регекс ігнорує, а
    # розкладка брала б слова коментаря як обов'язковий літерал — хибний нуль.
    if _VERBOSE_FLAG.search(pattern):
        return None
    depth = 0
    branches: list[str] = [""]
    # 🔴 Група з альтернативою «(Дол|Дал)» або з квантифікатором «(Долищ)?»
    # не гарантує ЖОДНОЇ своєї літери: перша версія брала «Дол» як обов'язкове
    # і передфільтр відсіював усі «Далищ…» — на корпусі 1 370 рядків замість
    # 24 318 (рецензія 08.09). Тепер уміст такої групи стирається до `\x00`.
    groups: list[tuple[int, bool]] = []      # (позиція початку в гілці, є «|»)
    i = 0
    in_class = False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            branches[-1] += "\x00\x00"
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
                branches[-1] += "\x00"
            i += 1
            continue
        if ch == "[":
            in_class = True
        elif ch == "(":
            branches[-1] += "\x00"
            special = i + 1 < len(pattern) and pattern[i + 1] == "?"
            if special and pattern.startswith("(?:", i):
                i += 2
                groups.append((len(branches[-1]), False))
            elif special and pattern.startswith("(?P<", i):
                j = pattern.find(">", i)
                i = j if j > 0 else i + 3
                groups.append((len(branches[-1]), False))
            else:
                # (?!…), (?<!…), (?=…), (?#…), (?i)… — їхній уміст не є
                # обов'язковим текстом рядка; група стирається при «)».
                groups.append((len(branches[-1]), special))
                if special:
                    i += 1
            depth += 1
        elif ch == ")":
            depth -= 1
            start, alt = groups.pop() if groups else (0, False)
            quant = i + 1 < len(pattern) and pattern[i + 1] in "?*+{"
            if alt or quant:
                branches[-1] = branches[-1][:start]
            branches[-1] += "\x00"
        elif ch == "|" and depth == 0:
            branches.append("")
        elif ch == "|":
            if groups:
                groups[-1] = (groups[-1][0], True)
            branches[-1] += "\x00"
        elif ch in "?*+{":
            # квантифікатор робить попередню літеру необов'язковою
            if branches[-1] and branches[-1][-1] != "\x00":
                branches[-1] = branches[-1][:-1] + "\x00"
            if ch == "{":
                j = pattern.find("}", i)
                i = j if j > 0 else i
        elif ch in ".^$":
            branches[-1] += "\x00"
        else:
            branches[-1] += ch
        i += 1
    out: list[str] = []
    for br in branches:
        lits = _LIT_RE.findall(br)
        if not lits:
            return None
        out.append(max(lits, key=len))
    return out


#: Група з самих літер «(Ков|Кав)» / «(?:ов|ев|)» і клас із самих літер
#: «[оа]», без квантифікатора після, не екрановані.
_ALT_GROUP = re.compile(r"(?<!\\)\((?:\?:)?([^\W\d_]*(?:\|[^\W\d_]*)+)\)(?![?*+{])")
_LETTER_CLASS = re.compile(r"(?<!\\)\[([^\W\d_]{2,})\](?![?*+{])")
#: Стеля варіантів: далі передфільтр із сотні фраз дорожчий за виграш.
VARIANTS_MAX = 32


def _variants(pattern: str) -> list[str]:
    """Регекс → варіанти, у яких малі групи й класи з літер розгорнуто.

    🔴 Лише для ПЕРЕДФІЛЬТРА: кожен збіг регексу проходить рівно одну гілку
    групи без квантифікатора (чи одну літеру класу), тож містить літерал
    принаймні одного варіанта — звуження без втрат. Сам регекс по рядках
    іде як є. Без цього «(Ков|Кав)альчинск» давав передфільтр «альчинск»: на
    корпусі гілки прізвища так читали вдесятеро більше сторінок (замір 21.10.2026).

    ⚠ Розгортаються лише групи без вкладених дужок і без метасимволів; решту
    `literals_of` стирає, як і раніше. Більше `VARIANTS_MAX` — не розгортати.
    """
    out = [pattern]
    while True:
        nxt: list[str] = []
        grew = False
        for p in out:
            m = _ALT_GROUP.search(p) or _LETTER_CLASS.search(p)
            if m is None:
                nxt.append(p)
                continue
            body = m.group(1)
            alts = body.split("|") if m.re is _ALT_GROUP else list(dict.fromkeys(body))
            nxt.extend(p[:m.start()] + a + p[m.end():] for a in alts)
            grew = True
        if not grew:
            return out
        nxt = list(dict.fromkeys(nxt))
        if len(nxt) > VARIANTS_MAX:
            return out
        out = nxt


def _prefilter_phrases(pattern: str) -> list[str] | None:
    """Нормалізовані фрази передфільтра — по одній на варіант гілки, або None.

    Кожен варіант мусить дати фразу ≥ 3 нормалізованих літер, інакше
    передфільтр не звужує без втрат (див. `grep`).
    """
    if _VERBOSE_FLAG.search(pattern):
        return None
    phrases: list[str] = []
    for var in _variants(pattern):
        lits = literals_of(var)
        if not lits:
            return None
        for lit in lits:
            n = _norm(_literal_core(lit))
            if len(n) < 3:
                return None
            phrases.append(n)
    return list(dict.fromkeys(phrases))


#: Скільки нормалізованих літер фрази йде в FTS — див. `_cheap_window`.
PHRASE_WINDOW = 6
#: Частоти трійок за вибіркою стору — одна на процес.
_TRIGRAMS: dict[str, Any] = {}


def _trigram_freq(conn: sqlite3.Connection) -> dict[str, int]:
    """Частота трійок літер у нормалізованих словах — за вибіркою рядків стору.

    Лише для вибору вікна фрази, тож точність не потрібна: «kov» і «nsk»
    трапляються в мільйонах рядків, «stk» і «dol» — у десятки разів рідше, і
    вибірка в кілька тисяч рядків це розрізняє.
    """
    got = _TRIGRAMS.get(str(path()))
    if got is not None:
        return dict(got)
    top = int(conn.execute("select max(id) from pages").fetchone()[0] or 0)
    # 🔴 Вибірка коштує 0,3–0,7 с, а кожен `nysh text grep` — новий процес:
    # пошук по справі за 0,05 с ставав 0,3 с. Частоти мови від нових справ
    # майже не рухаються, тож файл живе, доки стор не виріс удвічі.
    cache = Path(f"{path()}.trigrams.json")
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if int(saved["top"]) > 0 and top <= 2 * int(saved["top"]):
            _TRIGRAMS[str(path())] = dict(saved["freq"])
            return dict(saved["freq"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    freq: dict[str, int] = {}
    step = max(1, top // 400)
    for pid in range(1, int(top) + 1, step):
        lo, hi = pid << LINE_BITS, ((pid + 1) << LINE_BITS) - 1
        for (toks,) in conn.execute(
                "select toks from lines where id between ? and ?", (lo, hi)):
            for tk in str(toks or "").split(" "):
                if len(tk) < 3:
                    continue
                n = _norm(tk)
                for i in range(len(n) - 2):
                    freq[n[i:i + 3]] = freq.get(n[i:i + 3], 0) + 1
    _TRIGRAMS[str(path())] = dict(freq)
    if top:
        try:
            from nyshporka.utils.atomic import write_json

            write_json(cache, {"top": top, "freq": freq}, indent=None)
        except OSError:
            pass                    # кеш — зручність: наступний процес порахує знову
    return dict(freq)


def _cheap_window(phrase: str, freq: dict[str, int]) -> str:
    """Найдешевша частина нормалізованої фрази на `PHRASE_WINDOW` літер.

    🔴 FTS5 платить за фразу сумою довжин списків її трійок, а не числом
    збігів: на корпусі п'ять літер — 0,9 с, ті самі сім (з частою трійкою
    «kov», 8 млн рядків) — 6,5 с; у межах однієї справи фраза на десять літер —
    1,6 с при нулі збігів (замір 21.10.2026). Рідкісні трійки водночас і дешеві, і
    вибіркові, тож вікно з найменшою сумою частот звужує майже так само.
    Частина нормалізованої фрази — підрядок нормалізованого рядка, тож
    звуження лишається без втрат.
    """
    if len(phrase) <= PHRASE_WINDOW:
        return phrase
    best, at = -1, 0
    for i in range(len(phrase) - PHRASE_WINDOW + 1):
        w = phrase[i:i + PHRASE_WINDOW]
        cost = sum(freq.get(w[j:j + 3], 0) for j in range(PHRASE_WINDOW - 2))
        if best < 0 or cost < best:
            best, at = cost, i
    return phrase[at:at + PHRASE_WINDOW]


def _prefilter(conn: sqlite3.Connection, pattern: str
               ) -> tuple[list[str], list[str]] | None:
    """(фрази для FTS, цілі фрази) передфільтра, або None.

    Цілі фрази — по одній на варіант розгорнутої групи; у FTS іде найдешевша
    частина кожної (`_cheap_window`). Частоти трійок потрібні лише тоді, коли
    якась фраза довша за вікно.
    """
    full = _prefilter_phrases(pattern)
    if not full:
        return None
    freq = _trigram_freq(conn) if any(len(n) > PHRASE_WINDOW for n in full) else {}
    return list(dict.fromkeys(_cheap_window(n, freq) for n in full)), full


def _line_gate_safe(pattern: str) -> bool:
    """Чи можна відсіяти сторінку одним пошуком по всьому її тексту.

    Збіг у рядку лишається збігом у тексті сторінки (з `re.MULTILINE`), крім
    конструкцій, що бачать за межу рядка інакше: абсолютні якорі (`\\A`,
    `\\Z`), заперечні перевірки (`(?!`, `(?<!` — за межею рядка тепер стоїть
    `\\n`, а не порожнеча), вимкнення прапорів (`(?-`) і атомарні та
    посесивні конструкції (`(?>`, `*+`, `++`, `?+`, `}+`): `x\\s*+$` на сторінці
    з'їдає `\\n` і вже не відкочується до кінця рядка (рецензія 22.10.2026).
    """
    if any(t in pattern for t in ("\\A", "\\Z", "(?!", "(?<!", "(?-", "(?>")):
        return False
    # Посесивний квантифікатор — «+» одразу після квантифікатора, не екранований.
    return not re.search(r"(?<!\\)(?:[*+?]|\})\+", pattern)


def grep(pattern: str, runs: list[str], *, ignore_case: bool = True,
         limit: int = 200, context: int = 0) -> dict[str, Any]:
    """Регекс по сирому тексту прогонів — те, що робив `rg --no-ignore`, але
    без обходу дерева й без сліпоти `.gitignore`.

    Літерали регексу звужують корпус через FTS (нормалізовані, як фрази), далі
    сам регекс іде по сирих рядках лише тих сторінок. Регекс без літерала ≥ 3
    літер сканує всі рядки області, і відповідь про це каже.
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return {"hits": [], "error": f"регекс не розбирається: {exc}"}
    # Відсів сторінки одним пошуком по її тексту — див. `_line_gate_safe`.
    gate = (re.compile(pattern, flags | re.MULTILINE) if _line_gate_safe(pattern)
            else None)
    conn = connect(readonly=True)
    try:
        ids = _run_ids(conn, runs, fresh_only=True)
        by_id = {v: k for k, v in ids.items()}
        lits = literals_of(pattern)
        # 🔴 Кожна гілка (і кожен варіант розгорнутої групи) мусить дати фразу.
        # «ськ» після нормалізації — «sk», дві літери; доти така гілка мовчки
        # випадала з OR, а порожній вираз давав нуль сторінок із позначкою
        # «звужено» (рецензія 08.09).
        chosen = _prefilter(conn, pattern) if lits else None
        phrases = chosen[1] if chosen else None
        run_set = set(ids.values())
        pids: list[int] | None = None
        if chosen:
            expr = " OR ".join(f'"{n}"' for n in chosen[0])
            pids = sorted({rid >> LINE_BITS
                           for (rid,) in _fts_rows(conn, expr, list(ids.values()))})
            prefiltered = True
            n_pages = _pages_of_runs(conn, list(ids.values()))
        else:
            prefiltered = False
            n_pages = 0
            if _pages_of_runs(conn, list(ids.values())) >= GREP_PARALLEL_PAGES:
                pids = _scope_pids(conn, list(ids.values()))
        if pids is not None and len(pids) >= GREP_PARALLEL_PAGES:
            found, total, scanned_pages = _grep_parallel(pattern, flags, pids, run_set,
                                                         limit, context)
        else:
            source = (_page_texts(conn, pids, run_set) if pids is not None
                      else _run_texts(conn, list(ids.values())))
            found, total, scanned_pages = _grep_scan(source, rx, gate, limit, context)
        hits = [{"name": by_id[h.pop("run_id")], **h} for h in found]
        literal_pages: int | None = None
        if not prefiltered:
            n_pages = scanned_pages
        elif not total:
            # Нуль регексу: скільки сторінок мають ЦІЛИЙ літерал у нормі (а не
            # лише вікно передфільтра) — це й каже «орфографія, а не слово».
            full = " OR ".join(f'"{n}"' for n in phrases or [])
            literal_pages = len(_pages_for(
                conn, {rid >> LINE_BITS for (rid,) in _fts_rows(conn, full, list(ids.values()))},
                run_set))
        return {"hits": hits, "total": total, "runs": len(ids),
                "runs_asked": len(runs), "unindexed": len(runs) - len(ids),
                "pages": n_pages, "pages_scanned": scanned_pages,
                "prefiltered": prefiltered, "literals": lits or [],
                # Скільки сторінок мали літерал У НОРМІ: нуль регексу при
                # непорожньому передфільтрі означає орфографію («ь»/«ъ»), а
                # не відсутність слова — і про це треба сказати.
                # ⚠ Рахується лише на нулі: з хітами його ніхто не читає, а
                # повна фраза в FTS — найдорожча частина `grep`.
                "literal_pages": literal_pages}
    finally:
        conn.close()


#: Від скількох сторінок `grep` іде процесами (старт процесу — секунди).
GREP_PARALLEL_PAGES = 30_000
#: Сторінок на одну пачку процесу.
GREP_CHUNK_PAGES = 20_000
#: Пам'ять процесу `grep`, ГБ: сторінки йдуть потоком, у пам'яті — лише хіти пачки.
GREP_WORKER_GB = 0.3


def _grep_scan(source: Iterable[tuple[int, str, bytes | None]], rx: re.Pattern[str],
               gate: re.Pattern[str] | None, limit: int, context: int,
               ) -> tuple[list[dict[str, Any]], int, int]:
    """(перші `limit` хітів із `run_id`, усього збігів, прочесано сторінок)."""
    hits: list[dict[str, Any]] = []
    total = 0
    scanned = 0
    for rid_, page, blob in source:
        scanned += 1
        if blob is None:
            continue
        text = zlib.decompress(blob).decode("utf-8")
        if gate is not None and not gate.search(text):
            continue
        raw = text.split("\n")
        for i, ln in enumerate(raw, 1):
            if not rx.search(ln):
                continue
            total += 1
            if len(hits) >= limit:
                continue
            h: dict[str, Any] = {"run_id": rid_, "page": page, "line_no": i,
                                 "line_index": i - 1, "line": ln}
            if context:
                h["before"] = raw[max(0, i - 1 - context):i - 1]
                h["after"] = raw[i:i + context]
            hits.append(h)
    return hits, total, scanned


def _scope_pids(conn: sqlite3.Connection, run_ids: list[int]) -> list[int]:
    """Номери всіх сторінок області за зростанням."""
    if len(set(run_ids)) >= _runs_total(conn):
        return [int(p) for (p,) in conn.execute("select id from pages order by id")]
    out: list[int] = []
    for rid in run_ids:
        out.extend(int(p) for (p,) in conn.execute("select id from pages where run_id=?", (rid,)))
    return sorted(set(out))


def _grep_job(pattern: str, flags: int, pids: list[int], run_set: set[int], limit: int,
              context: int) -> tuple[list[dict[str, Any]], int, int]:
    rx = re.compile(pattern, flags)
    gate = re.compile(pattern, flags | re.MULTILINE) if _line_gate_safe(pattern) else None
    conn = connect(readonly=True)
    try:
        return _grep_scan(_page_texts(conn, pids, run_set), rx, gate, limit, context)
    finally:
        conn.close()


def _grep_parallel(pattern: str, flags: int, pids: list[int], run_set: set[int],
                   limit: int, context: int) -> tuple[list[dict[str, Any]], int, int]:
    """Той самий прохід пачками в процесах — від заліза (`sweep_workers`).

    🔴 Пачки — відрізки сторінок за зростанням номера, і складаються вони в
    тому ж порядку, тож перші `limit` хітів ті самі, що в одному процесі: пачці
    досить віддати свої перші `limit`. Регекс без літерала — це кожна сторінка
    області, і в одному процесі такий прохід по корпусу йшов хвилини.
    """
    chunks = [pids[i:i + GREP_CHUNK_PAGES] for i in range(0, len(pids), GREP_CHUNK_PAGES)]
    workers = sweep_workers(len(chunks), worker_gb=GREP_WORKER_GB)
    hits: list[dict[str, Any]] = []
    total = scanned = 0
    ex: Any = None
    if workers <= 1:
        parts: Iterable[tuple[list[dict[str, Any]], int, int]] = (
            _grep_job(pattern, flags, ch, run_set, limit, context) for ch in chunks)
    else:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        from nyshporka.core.workspace import workspace

        ex = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_block_init, initargs=(workspace(),))
        n = len(chunks)
        parts = ex.map(_grep_job, [pattern] * n, [flags] * n, chunks, [run_set] * n,
                       [limit] * n, [context] * n)
    try:
        for got, t, sc in parts:
            total += t
            scanned += sc
            hits.extend(got[:max(0, limit - len(hits))])
    finally:
        if ex is not None:
            ex.shutdown(wait=True, cancel_futures=True)
    return hits, total, scanned



def runs_named(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("select run from runs order by run")]

