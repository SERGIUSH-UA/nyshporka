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
import json
import re
import sqlite3
import time
import zlib
from bisect import bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass
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

    return workspace().derived / FILE


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


def connect(*, readonly: bool = False, migrate: bool = False) -> sqlite3.Connection:
    """З'єднання зі стором. Схема створюється при першому відкритті.

    🔴 WAL, бо стор читають під час індексації: пошук з іншої вкладки або
    агент не мусять чекати, поки збірка дійде до кінця корпусу.

    🔴 Стор чужої схеми ЗНОСИТЬ лише `migrate=True`, тобто явна збірка. Доти
    будь-який читач, що відкривав стор на запис (`is_fresh` з каналу якорів),
    після оновлення пакета мовчки дропав 6.5 ГБ (рецензія 08.09). Тепер
    невідповідність — помилка з підказкою, а не дія.
    """
    p = path()
    if readonly and not p.is_file():
        raise FileNotFoundError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=60)
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma synchronous=normal")
    conn.execute("pragma cache_size=-100000")
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


def _ensure_schema(conn: sqlite3.Connection, *, migrate: bool = False) -> None:
    conn.executescript(_DDL)
    with contextlib.suppress(sqlite3.Error):
        _add_run_rules_column(conn)
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
    import ast

    from nyshporka import htr_store as S
    from nyshporka.utils import translit as T

    parts: list[str] = []
    # `page_candidates` тепер вьюха — правила живуть у повній версії, і саме
    # її зміна мусить робити кандидатів застарілими.
    for fn in (S.page_candidates_full, T.normalize_archival, successors, _geo_cands):
        try:
            # AST без коментарів: правка коментаря не має вимагати перебудови.
            parts.append(ast.dump(ast.parse(inspect.getsource(fn))))
        except (OSError, TypeError, SyntaxError):
            parts.append(f"{fn.__module__}.{fn.__name__}")
    parts += [str(S.LINE_BREAK_WINDOW), str(COL_GAP), str(SUCC_REACH), str(MARK)]
    # 🔴 Префікс версії САМОГО відбитка. Спосіб рахувати (джерело → AST)
    # змінився в минулому коміті, і живий стор на 6.5 ГБ став «застарілим за
    # правилами» без жодної зміни правил (рецензія 08.09, третій раунд). Зміна
    # способу тепер видима як така, а дослідник приймає відбиток без
    # перебудови: `nysh text index --accept-rules`.
    return "v2:" + hashlib.blake2b("\n".join(parts).encode("utf-8"), digest_size=8).hexdigest()


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


def stamps(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("select run, stamp from runs")}


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


def _same_case(meta: dict[str, Any] | None, base: Path) -> bool:
    """Чи прогін `base` про ту саму справу, що й `meta`."""
    from nyshporka import htr_store as S

    if not meta:
        return False
    other = S.load_meta(base.name) or {}
    key, okey = (meta.get("case_key") or "").strip(), (other.get("case_key") or "").strip()
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


def index_run(conn: sqlite3.Connection, run: str) -> int:
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
    conn.execute("begin")
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
        "indexed_at, rules) values(?,?,?,?,?,?,?,?,?)",
        (run, stamp, (meta.get("case_key") or "").strip(), meta.get("case_dir") or "",
         meta.get("model") or "", meta.get("script") or "",
         json.dumps(S.run_engine_ids(meta)), time.strftime("%Y-%m-%dT%H:%M:%S"),
         rules_hash()))
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
        cands = _page_cands(lines)
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
        succ = successors(page_lines) if boxes else {}
        if succ:
            _geo_cands(cands, page_lines, succ)
        conn.execute("update pages set cands=? where id=?",
                     (zlib.compress("\n".join(
                         f"{no}\t{' '.join(ns)}" for no, ns in sorted(cands.items()) if ns
                     ).encode("utf-8"), 6), pid))
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
        return index_run(c, run) > 0
    finally:
        if own:
            c.close()


#: Прогони, які остання збірка пропустила через замок іншої сесії. Мовчазний
#: пропуск виглядав як «тека без .txt» (рецензія 08.09, третій раунд).
LOCKED_SKIPPED: list[str] = []


def ensure_all(runs: list[str], *, force: bool = False, reset_rules: bool = False,
               progress: Callable[[int, int, str], None] | None = None,
               ) -> Iterator[str]:
    """Догнати стор по переліку прогонів, звітуючи про кожен.

    Генератор навмисно: перша збірка корпусу триває десятки хвилин, і той, хто
    її запустив, мусить бачити, де вона зараз. `force` перебудовує й свіже —
    після зміни правил розбору токенів чи геометрії.
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
        total = len(runs)
        for i, run in enumerate(runs, 1):
            if progress:
                progress(i, total, run)
            P.report(i, total, "прогонів")
            st = stamp_of(run)
            if st and known.get(run) == st and by_rules.get(run) == rules_now \
                    and not force:
                yield run
                continue
            try:
                if index_run(conn, run) > 0:
                    built += 1
                    yield run
            except sqlite3.OperationalError as exc:
                # Друга сесія індексує той самий стор: цей прогін пропускаємо,
                # решта переліку не валиться; штамп скаже, що він застарілий.
                if "locked" not in str(exc).lower():
                    raise
                with contextlib.suppress(sqlite3.Error):
                    conn.rollback()
                LOCKED_SKIPPED.append(run)
        # `optimize` зливає ВСІ сегменти FTS під write-lock — на 6.5 ГБ це
        # не для кожного `index --case`; лише коли зібрано багато або примусово.
        if force or built >= OPTIMIZE_MIN:
            conn.execute("insert into fts(fts) values('optimize')")
            conn.commit()
    finally:
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
    return sum(1 for r in runs if not stamp_of(r) or known.get(r) != stamp_of(r))


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
        fresh = sum(1 for r in runs if known.get(r) and known[r] == stamp_of(r))
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
    for run in runs:
        row = conn.execute("select id, stamp from runs where run=?", (run,)).fetchone()
        if not row:
            continue
        if fresh_only and row[1] != stamp_of(run):
            continue
        out[run] = int(row[0])
    return out


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


def _pages_of(conn: sqlite3.Connection, run_ids: list[int]) -> dict[int, tuple[int, str]]:
    """pid → (run_id, page) для прогонів області."""
    out: dict[int, tuple[int, str]] = {}
    for rid in run_ids:
        for pid, page in conn.execute("select id, page from pages where run_id=?", (rid,)):
            out[int(pid)] = (rid, page)
    return out


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


def _cands_batch(conn: sqlite3.Connection, wanted: dict[int, set[int]], *,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None,
                 ) -> Iterator[tuple[int, int, list[str]]]:
    """Кандидати потрібних рядків для всіх сторінок — блоби пачками по 500."""
    pids = sorted(wanted)
    for i in range(0, len(pids), 500):
        if cancel and cancel():
            return
        if progress:
            progress(i, len(pids), "")
        chunk = pids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for pid, blob in conn.execute(
                f"select id, cands from pages where id in ({marks})", chunk):
            if blob is None:
                continue
            nos = wanted[int(pid)]
            for line in zlib.decompress(blob).decode("utf-8").split("\n"):
                no_s, _sep, rest = line.partition("\t")
                if not rest:
                    continue
                try:
                    no = int(no_s)
                except ValueError:
                    continue
                if no in nos:
                    yield int(pid), no, rest.split(" ")


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
    lmax = int(lens.max()) if len(lens) else 0
    cutoff = 0
    if stems:
        cutoff = max(0, int(min(float(_partial_bound(len(s), np.int32(lmax), thresh))
                                for s in stems)))
    r = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=cutoff,
              dtype=np.uint8, workers=-1)
    # ⚠ Хіт за `ratio` — окремим проходом із порогом у самому rapidfuzz: поріг
    # там порівнюється з дробовим балом, а uint8 округлює 77.8 до 78, і без
    # цього проходу межові кандидати проходили б усупереч `decode._matches`.
    r_hit = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=thresh,
                  dtype=np.uint8, workers=-1)
    for si, stem in enumerate(stems):
        need = max(4, int(len(stem) * 0.6))
        floor = max(need, len(stem))
        row = r[si]
        sc = np.where((r_hit[si] >= thresh) & (lens >= need), r_hit[si], 0).astype(np.int32)
        idx = np.flatnonzero((lens >= floor) & (row >= _partial_bound(len(stem), lens, thresh)))
        if len(idx):
            pr = cdist([stem], [order[int(j)] for j in idx], scorer=fuzz.partial_ratio,
                       score_cutoff=thresh, dtype=np.uint8, workers=-1)[0]
            sub_sc = np.where(pr >= thresh, pr, 0).astype(np.int32)
            sc[idx] = np.maximum(sc[idx], sub_sc)
        for j in np.flatnonzero(sc):
            v = float(sc[j])
            cur = best.get(int(j))
            if cur is None or v > cur[0]:
                best[int(j)] = (v, si)
    return best


def _cands_of(conn: sqlite3.Connection, pid: int, nos: set[int]
              ) -> list[tuple[int, list[str]]]:
    """Кандидати потрібних рядків сторінки з блоба `pages.cands`."""
    row = conn.execute("select cands from pages where id=?", (pid,)).fetchone()
    if not row or row[0] is None:
        return []
    out: list[tuple[int, list[str]]] = []
    for line in zlib.decompress(row[0]).decode("utf-8").split("\n"):
        no_s, _sep, rest = line.partition("\t")
        if not rest:
            continue
        try:
            no = int(no_s)
        except ValueError:
            continue
        if no in nos:
            out.append((no, rest.split(" ")))
    return out


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


def sweep(stems: list[str], runs: list[str], *, thresh: int = 78,
          build_budget: int = 0,
          progress: Callable[[int, int, str], None] | None = None,
          cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
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
        st = {r: stamp_of(r) for r in runs}
        stale = [r for r in runs if st[r] and known.get(r) != st[r]]
        if 0 < len(stale) <= max(0, build_budget):
            for i, r in enumerate(stale, 1):
                if progress:
                    progress(i, len(stale), r)
                try:
                    index_run(conn, r)
                except sqlite3.OperationalError as exc:
                    # Інша сесія тримає стор на запис: цей прогін лишається
                    # поза пошуком і йде в `unindexed`, а не валить запит.
                    if "locked" not in str(exc).lower():
                        raise
                    with contextlib.suppress(sqlite3.Error):
                        conn.rollback()
            known = stamps(conn)
            st = {r: stamp_of(r) for r in runs}
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
        blocks = _blocks_by_pages(conn, todo)
        cancelled = False
        for bi, block in enumerate(blocks, 1):
            if progress:
                progress(bi, len(blocks), f"блок {bi}/{len(blocks)}")
            got = _sweep_block(conn, stems, block, thresh, cancel=cancel)
            if got is None:
                cancelled = True
                break
            for lst in got.values():
                rows.extend(lst)
            _sweep_put(conn, key, got)
        pages = _pages_for(conn, {r[0] for r in rows}, set(run_ids))
        for pid, no, norm, score, stem in rows:
            got_page = pages.get(pid)
            if got_page is None:
                continue
            hits.append({"name": by_id[got_page[0]], "page": got_page[1], "line_no": no,
                         "line_index": no - 1, "norm": norm, "stem": stem, "score": score})
        return {"hits": hits, "scanned": len(ready), "runs": len(runs),
                "unindexed": missing, "backend": "store", "cached": len(cached),
                "computed": len(todo), "cancelled": cancelled, "rules_stale": rstale}
    finally:
        conn.close()


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
    conn = connect(readonly=True)
    try:
        ids = _run_ids(conn, runs, fresh_only=True)
        by_id = {v: k for k, v in ids.items()}
        lits = literals_of(pattern)
        pids: set[int]
        phrases: list[str] = []
        for lit in lits or []:
            n = _norm(_literal_core(lit))
            if len(n) >= 3:
                phrases.append(f'"{n}"')
        # 🔴 Кожна гілка мусить дати фразу. «ськ» після нормалізації — «sk»,
        # дві літери; доти така гілка мовчки випадала з OR, а порожній вираз
        # давав нуль сторінок із позначкою «звужено» (рецензія 08.09).
        if lits and len(phrases) == len(lits):
            expr = " OR ".join(phrases)
            raw_pids = {rid >> LINE_BITS for (rid,) in _fts_rows(conn, expr, list(ids.values()))}
            pages = _pages_for(conn, raw_pids, set(ids.values()))
            pids = set(pages)
            prefiltered = True
        else:
            pages = _pages_of(conn, list(ids.values()))
            pids = set(pages)
            prefiltered = False
        hits: list[dict[str, Any]] = []
        total = 0
        scanned_pages = 0
        for pid in sorted(pids):
            raw = _raw_lines(conn, pid)
            scanned_pages += 1
            rid_, page = pages[pid]
            for i, ln in enumerate(raw, 1):
                if not rx.search(ln):
                    continue
                total += 1
                if len(hits) >= limit:
                    continue
                h: dict[str, Any] = {"name": by_id[rid_], "page": page, "line_no": i,
                                     "line_index": i - 1, "line": ln}
                if context:
                    h["before"] = raw[max(0, i - 1 - context):i - 1]
                    h["after"] = raw[i:i + context]
                hits.append(h)
        n_pages = (len(pages) if not prefiltered
                   else int(conn.execute(
                       f"select coalesce(sum(pages),0) from runs where id in "
                       f"({','.join('?' * len(ids))})", list(ids.values())).fetchone()[0])
                   if ids else 0)
        return {"hits": hits, "total": total, "runs": len(ids),
                "runs_asked": len(runs), "unindexed": len(runs) - len(ids),
                "pages": n_pages, "pages_scanned": scanned_pages,
                "prefiltered": prefiltered, "literals": lits or [],
                # Скільки сторінок мали літерал У НОРМІ: нуль регексу при
                # непорожньому передфільтрі означає орфографію («ь»/«ъ»), а
                # не відсутність слова — і про це треба сказати.
                "literal_pages": len(pids) if prefiltered else None}
    finally:
        conn.close()


def runs_named(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("select run from runs order by run")]

