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
    indexed_at text default '');
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
"""


def connect(*, readonly: bool = False) -> sqlite3.Connection:
    """З'єднання зі стором. Схема створюється при першому відкритті.

    🔴 WAL, бо стор читають під час індексації: пошук з іншої вкладки або
    агент не мусять чекати, поки збірка дійде до кінця корпусу.
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
        _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    row = conn.execute("select value from meta where key='schema'").fetchone()
    if row is None:
        conn.execute("insert into meta(key,value) values('schema',?)", (str(SCHEMA),))
        conn.commit()
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
    c = conn or connect()
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


def _geometry_for(run_dir: Path, run: str, stem: str, nlines: int
                  ) -> list[list[int]] | None:
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
        if base.is_dir():
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


def _delete_run(conn: sqlite3.Connection, run_id: int) -> None:
    pids = [r[0] for r in conn.execute("select id from pages where run_id=?", (run_id,))]
    for pid in pids:
        lo, hi = pid << LINE_BITS, ((pid + 1) << LINE_BITS) - 1
        conn.execute("delete from fts where rowid between ? and ?", (lo, hi))
        conn.execute("delete from lines where id between ? and ?", (lo, hi))
    conn.execute("delete from pages where run_id=?", (run_id,))
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
    conn.execute(
        "insert into runs(run, stamp, case_key, case_dir, model, script, engine_ids, "
        "indexed_at) values(?,?,?,?,?,?,?,?)",
        (run, stamp, (meta.get("case_key") or "").strip(), meta.get("case_dir") or "",
         meta.get("model") or "", meta.get("script") or "",
         json.dumps(S.run_engine_ids(meta)), time.strftime("%Y-%m-%dT%H:%M:%S")))
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
        page = stem2page.get(txt.stem, txt.name)
        boxes = _geometry_for(d, run, txt.stem, len(lines))
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


def ensure_all(runs: list[str], *, force: bool = False,
               progress: Callable[[int, int, str], None] | None = None,
               ) -> Iterator[str]:
    """Догнати стор по переліку прогонів, звітуючи про кожен.

    Генератор навмисно: перша збірка корпусу триває десятки хвилин, і той, хто
    її запустив, мусить бачити, де вона зараз. `force` перебудовує й свіже —
    після зміни правил розбору токенів чи геометрії.
    """
    from nyshporka.core import progress as P

    conn = connect()
    try:
        known = stamps(conn)
        total = len(runs)
        for i, run in enumerate(runs, 1):
            if progress:
                progress(i, total, run)
            P.report(i, total, "прогонів")
            st = stamp_of(run)
            if st and known.get(run) == st and not force:
                yield run
                continue
            if index_run(conn, run) > 0:
                yield run
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
    finally:
        conn.close()
    return {"runs": len(runs), "indexed": fresh, "stale": len(runs) - fresh,
            "bytes": p.stat().st_size, "pages": int(row[0]), "lines": int(row[1]),
            "geo": int(row[2]), "file": str(p), "exists": True}


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
def whole_stems(stems: list[str]) -> tuple[list[str], list[str]]:
    """Лишити цілі написання; голови, хвости й склейки переносу — геть.

    Фрагмент — стем із дефісом чи пробілом, або строгий префікс/суфікс іншого
    стема. Повертає (цілі, відкинуті); порядок цілих збережено.
    """
    clean = [s for s in stems if s and "-" not in s and " " not in s]
    keep: list[str] = []
    dropped: list[str] = [s for s in stems if s not in clean]
    for s in clean:
        # Хвіст — строгий СУФІКС іншого стема («alskii» ⊂ «kovalskii»).
        # Префікс не є фрагментом: відмінкові форми одного слова є префіксами
        # одна одної («kovalska» ⊂ «kovalskago»), і викинути їх означало
        # б втратити самі відмінки, заради яких профіль їх тримає.
        tail = any(o != s and len(o) > len(s) and o.endswith(s) for o in clean)
        (dropped if tail else keep).append(s)
    return keep, dropped


def match_expr(stems: list[str]) -> str:
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
    for s in stems:
        k = kgram_len(s)
        if len(s) <= k + 1:
            terms.add(f'"{s}"')
            continue
        grams = [s[i:i + k] for i in range(len(s) - k + 1)]
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


def _run_ids(conn: sqlite3.Connection, runs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for run in runs:
        row = conn.execute("select id from runs where run=?", (run,)).fetchone()
        if row:
            out[run] = int(row[0])
    return out


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
    if not run_ids or len(run_ids) >= min(SCOPE_RANGES_MAX, int(total)):
        yield from conn.execute("select rowid from fts where fts match ?", (expr,))
        return
    marks = ",".join("?" * len(run_ids))
    row = conn.execute(f"select min(id), max(id) from pages where run_id in ({marks})",
                       run_ids).fetchone()
    if not row or row[0] is None:
        return
    lo, hi = int(row[0]) << LINE_BITS, ((int(row[1]) + 1) << LINE_BITS) - 1
    yield from conn.execute(
        "select rowid from fts where fts match ? and rowid between ? and ?",
        (expr, lo, hi))


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
    """Те саме, що `decode._matches`, але кожна ФОРМА порівнюється один раз.

    🔴 На корпусі 11.4 млн кандидатів, з них унікальних утричі менше: ті самі
    «священникъ» і «крестьяне» стоять на кожній сторінці. Зіставляти їх по
    сто тисяч разів означало 294 с на запит із 26 стемами.

    Коли є numpy, порівняння йде `cdist` по всіх стемах одразу й на всіх
    ядрах; без нього — `extract` по стему, як у gzip-індексу.
    """
    from nyshporka.search import decode as D

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
    best_u = _match_cdist(order, stems, thresh)
    if best_u is None:
        best_u = D._matches(order, stems, thresh)
    out: dict[int, tuple[float, int]] = {}
    for j, k in enumerate(back):
        got = best_u.get(k)
        if got is not None:
            out[j] = got
    return out


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
    r = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=thresh,
              dtype=np.uint8, workers=-1)
    pr = cdist(stems, order, scorer=fuzz.partial_ratio, score_cutoff=thresh,
               dtype=np.uint8, workers=-1)
    for si, stem in enumerate(stems):
        need = max(4, int(len(stem) * 0.6))
        ok_r = (r[si] >= thresh) & (lens >= need)
        ok_p = (pr[si] >= thresh) & (lens >= max(need, len(stem)))
        sc = np.where(ok_r, r[si], 0).astype(np.int32)
        sc = np.maximum(sc, np.where(ok_p, pr[si], 0).astype(np.int32))
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


def sweep(stems: list[str], runs: list[str], *, thresh: int = 78,
          build_budget: int = 0,
          progress: Callable[[int, int, str], None] | None = None,
          cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Прочесати прогони через стор. Та сама відповідь, що `decode.sweep`.

    🔴 Або всі, або жоден — як і в gzip-індексу: якщо застарілих прогонів
    більше за бюджет, жоден не збирається, і `unindexed` каже, скільки лишилось
    поза пошуком. Зібрати «скільки встигнеться» означало б віддати нуль зі
    знаменником, що залежить від порядку тек.
    """

    conn = connect()
    try:
        known = stamps(conn)
        stale = [r for r in runs if stamp_of(r) and known.get(r) != stamp_of(r)]
        if 0 < len(stale) <= max(0, build_budget):
            for i, r in enumerate(stale, 1):
                if progress:
                    progress(i, len(stale), r)
                index_run(conn, r)
            known = stamps(conn)
        ready = [r for r in runs if stamp_of(r) and known.get(r) == stamp_of(r)]
        missing = len(runs) - len(ready)
        ids = _run_ids(conn, ready)
        by_id = {v: k for k, v in ids.items()}
        pages = _pages_of(conn, list(ids.values()))
        hits: list[dict[str, Any]] = []
        if not pages or not stems:
            return {"hits": hits, "scanned": len(ready), "runs": len(runs),
                    "unindexed": missing, "backend": "store"}
        expr = match_expr(stems)
        wanted: dict[int, set[int]] = {}
        # 🔴 Разом із рядком беруться кілька наступних. Склейка переносу
        # («Липовень» ⏎ «комъ») приписується рядку з ГОЛОВОЮ, а k-грам стема
        # стоїть у рядку з хвостом; без розширення хіт зникав би саме там, де
        # прізвище розірване, — рівно те, заради чого склейка існує.
        from nyshporka import htr_store as S

        reach = S.LINE_BREAK_WINDOW
        for (rid,) in _fts_rows(conn, expr, list(ids.values())):
            pid, no = rid >> LINE_BITS, rid & MAX_LINES
            if pid in pages:
                wanted.setdefault(pid, set()).update(range(no, no + reach + 1))
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
        by_line: dict[tuple[int, int], tuple[float, int, int]] = {}
        for j, (sc, si) in _match_unique(norms, stems, thresh).items():
            key = owner[bisect_right(starts, j) - 1]
            cur = by_line.get(key)
            if cur is None or sc > cur[0]:
                by_line[key] = (sc, j, si)
        for (pid, no), (sc, j, si) in by_line.items():
            rid_, page = pages[pid]
            hits.append({"name": by_id[rid_], "page": page, "line_no": no,
                         "line_index": no - 1, "norm": norms[j],
                         "stem": stems[si] if si < len(stems) else "",
                         "score": round(sc)})
        return {"hits": hits, "scanned": len(ready), "runs": len(runs),
                "unindexed": missing, "backend": "store"}
    finally:
        conn.close()


# ── регекс по сирому тексту ──────────────────────────────────────────────────
_LIT_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


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
    depth = 0
    branches: list[str] = [""]
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
            depth += 1
            branches[-1] += "\x00"
        elif ch == ")":
            depth -= 1
            branches[-1] += "\x00"
        elif ch == "|" and depth == 0:
            branches.append("")
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
        ids = _run_ids(conn, runs)
        by_id = {v: k for k, v in ids.items()}
        pages = _pages_of(conn, list(ids.values()))
        lits = literals_of(pattern)
        pids: set[int]
        if lits:
            phrases = []
            for lit in lits:
                n = _norm(lit)
                if len(n) >= 3:
                    phrases.append(f'"{n}"')
            expr = " OR ".join(phrases)
            pids = set()
            if expr:
                for (rid,) in conn.execute("select rowid from fts where fts match ?", (expr,)):
                    pid = rid >> LINE_BITS
                    if pid in pages:
                        pids.add(pid)
            prefiltered = True
        else:
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
        return {"hits": hits, "total": total, "runs": len(ids),
                "runs_asked": len(runs), "unindexed": len(runs) - len(ids),
                "pages": len(pages), "pages_scanned": scanned_pages,
                "prefiltered": prefiltered, "literals": lits or []}
    finally:
        conn.close()


def runs_named(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("select run from runs order by run")]

