"""Зріз Супряги на диску: що з наших справ уже прочитано в пулі.

Третій шар поруч із двома наявними. Реєстр опису каже, що справа ІСНУЄ;
бібліотека — що вона в МЕНЕ на диску; цей зріз — що її вже ПРОЧИТАНО, і текст
можна взяти замість того, щоб платити за прогін удруге.

🔴 Окремий модуль, а не доважок до `share/catalog.py`, і це не смак. `catalog`
— це дріт: він ходить у мережу за побудовою. `pool` — це диск: він у мережу не
ходить НІКОЛИ, і рівно тому обіцянку «показ колонки не робить запитів» можна
довести тестом. Зведи їх в один файл — і доводити стане нічим.

Хто ходить у мережу: тільки `sync()`, і тільки коли її покликали ім'ям.

Три значення, а не два
----------------------

🔴 «У пулі є», «у пулі немає» і **«ми не питали»** — різні відповіді, і третя
трапляється найчастіше: доки зрізу не знято, вона єдина правдива. Тому
`by_fond()` віддає `None` (зрізу немає) і `{}` (зріз є, у фонді порожньо), а не
порожній словник на обидва випадки.

Ціна плутанини конкретна: людина бачить «у пулі немає» там, де ми просто не
дивились, і замовляє прогін справи, текст якої лежить готовий. Це той самий
припис, що `layers.summary()` тримає для реєстру справ: `None` ≠ `0`.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import workspace

#: Версія розкладки зрізу. Росте з кожною зміною таблиць: читач старшої версії
#: мусить сказати «зрізу немає» й попросити зняти наново, а не розбирати
#: наосліп чужі колонки.
SCHEMA = 1

DIR_NAME = "supriaha"
FILE_NAME = "pool.sqlite"

#: Скільки днів зріз вважається свіжим. Не термін протухання: зріз не
#: самознищується й не оновлюється сам. Це лише межа, за якою вік починають
#: показувати попередженням, а не сірим рядком.
SVIZHYI_DNIV = 7
STARYI_DNIV = 30


@dataclass(frozen=True)
class PoolCell:
    """Що пул знає про одну книгу."""

    n: int = 0
    pages: int = 0
    geom: bool = False
    publishers: tuple[str, ...] = ()
    #: `None` — не `False`: у профілі порожній псевдонім, і відповіді немає.
    #: Людина без `handle` не має права бачити «не ваш» там, де невідомо.
    mine: bool | None = None
    updated: str = ""


# ── адреси ────────────────────────────────────────────────────────────────────

def pool_dir() -> Path:
    return workspace().derived / DIR_NAME


def snapshot_path() -> Path:
    """🔴 У `derived`, а не в `data/share/`.

    Критерій постійного сховища: воно тримає те, що САМЕ СОБОЮ щось доводить і
    не відтворюється. Журнал обміну доводить походження чужого факту; прийнятий
    пакет — доказ-файл. Зріз пулу не доводить нічого й відтворюється повторним
    запитом, тож його можна знести чисткою без утрати.
    """
    return pool_dir() / FILE_NAME


def have_snapshot() -> bool:
    return snapshot_path().is_file()


# ── ключ ──────────────────────────────────────────────────────────────────────

def quad_key(repo: str, fond: str, opys: str, spr: str) -> str:
    """Канонічна четвірка `DAHMO/315/1/84a` — той самий канон, що на сервері.

    🔴 Нормалізують ТІ САМІ функції бібліотеки, які кличе `pagestore.resolve_case`,
    а `resolve_case` — це те, чим нормалізує сервер (`app/shifra.py` імпортує
    саме його). Тобто дві нормалізації — буквально один код, і розійтись вони
    можуть лише разом.

    ⚠ Чому не кликати `resolve_case` прямо: він робить `load_library()` і
    розв'язує неоднозначності по диску. У циклі на 4885 рядків реєстру це
    неприйнятно, а тут потрібен чистий нормалізатор без жодного I/O.
    """
    from nyshporka.library import _norm_fond, _norm_spr

    r = (repo or "").strip().upper()
    f = _norm_fond(fond) or ""
    o = _norm_spr(opys) or ""
    s = _norm_spr(spr) or ""
    if not (r and f and s):
        return ""
    return f"{r}/{f}/{o}/{s}"


def _stamp(p: Path) -> tuple[Any, ...]:
    """Штамп файла, якого може не бути: відсутність — теж стан, і її кешуємо."""
    try:
        st = p.stat()
        return (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(p), -1, -1)


#: memo: (repo, fond) → (штамп зрізу, мапа). Штамп протухає сам після `sync`,
#: скидати руками не треба — за зразком `fonds.registry._CACHE`.
_FOND_CACHE: dict[tuple[str, str], tuple[tuple[Any, ...], dict[tuple[str, str, str], PoolCell]]] = {}
_META_CACHE: tuple[tuple[Any, ...], dict[str, Any] | None] | None = None


def invalidate() -> None:
    """Забути memo. Потрібно тестам і після `sync` у тому самому процесі."""
    global _META_CACHE
    _FOND_CACHE.clear()
    _META_CACHE = None


# ── читання ───────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection | None:
    """Зріз лише на читання. `None`, якщо його немає або він чужої версії."""
    path = snapshot_path()
    if not path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def meta() -> dict[str, Any] | None:
    """Паспорт зрізу, або `None` — зрізу немає.

    Ключі: `base`, `taken_at`, `of` (скільки книг), `scope`, `via`, `schema`.
    """
    global _META_CACHE
    stamp = _stamp(snapshot_path())
    if _META_CACHE is not None and _META_CACHE[0] == stamp:
        return _META_CACHE[1]

    out: dict[str, Any] | None = None
    con = _connect()
    if con is not None:
        try:
            rows = con.execute("SELECT key, value FROM meta").fetchall()
            got = {r["key"]: r["value"] for r in rows}
            if int(got.get("schema") or 0) == SCHEMA:
                got["of"] = int(got.get("of") or 0)
                out = got
        except sqlite3.Error:
            out = None
        finally:
            con.close()
    _META_CACHE = (stamp, out)
    return out


def age_days() -> float | None:
    """Скільки днів зрізу. `None`, якщо зрізу немає або дата нечитна."""
    m = meta()
    if not m or not m.get("taken_at"):
        return None
    try:
        taken = datetime.fromisoformat(str(m["taken_at"]))
    except ValueError:
        return None
    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=UTC)
    return (datetime.now(UTC) - taken).total_seconds() / 86400


def stale() -> bool:
    """Чи час попередити про вік. Без зрізу — ні: там інша розмова."""
    age = age_days()
    return age is not None and age > STARYI_DNIV


def _cell(row: sqlite3.Row, handle: str) -> PoolCell:
    pubs = tuple(json.loads(row["publishers"] or "[]"))
    return PoolCell(
        n=int(row["n"] or 0),
        pages=int(row["pages"] or 0),
        geom=bool(row["geom"]),
        publishers=pubs,
        # 🔴 `None`, коли псевдоніма немає: «не ваш» і «невідомо» — різні речі.
        mine=(handle in pubs) if handle else None,
        updated=str(row["updated"] or ""),
    )


def _handle() -> str:
    try:
        from nyshporka.share.profile import load

        return str(load().handle or "").strip()
    except Exception:
        return ""


def by_fond(repo: str, fond: str) -> dict[tuple[str, str, str], PoolCell] | None:
    """Зріз одного фонду: `(opys, spr_int, letter) → PoolCell`.

    🔴 `None` = зрізу немає; `{}` = зріз є, а в цьому фонді пулу порожньо.
    Саме ця різниця не дає намалювати «у пулі немає» там, де не питали.

    Ключ навмисно той самий, що в `registry.live_on_disk` і `live_frames`, щоб
    `row_status` не мав другого способу адресувати рядок.
    """
    key = ((repo or "").upper(), str(fond))
    stamp = _stamp(snapshot_path())
    hit = _FOND_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]

    if meta() is None:
        return None

    con = _connect()
    if con is None:
        return None
    handle = _handle()
    out: dict[tuple[str, str, str], PoolCell] = {}
    try:
        rows = con.execute(
            "SELECT opys, spr, n, pages, geom, publishers, updated "
            "FROM pool WHERE repo = ? AND fond = ?", key).fetchall()
        for r in rows:
            spr = str(r["spr"] or "")
            i = len(spr)
            while i and not spr[i - 1].isdigit():
                i -= 1
            out[(str(r["opys"] or ""), spr[:i], spr[i:])] = _cell(r, handle)
    except sqlite3.Error:
        return None
    finally:
        con.close()

    _FOND_CACHE[key] = (stamp, out)
    return out


def by_key(key: str) -> PoolCell | None:
    """Одна книга за канонічним ключем. `None` — немає зрізу або немає книги."""
    con = _connect()
    if con is None or meta() is None:
        return None
    try:
        row = con.execute(
            "SELECT opys, spr, n, pages, geom, publishers, updated "
            "FROM pool WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return _cell(row, _handle()) if row else None


def state_of(cell: PoolCell | None) -> str:
    """`none | text | text+geom`. Про відсутність ЗРІЗУ каже не ця функція."""
    if cell is None or not cell.n:
        return "none"
    return "text+geom" if cell.geom else "text"


def disk_keys() -> set[str]:
    """Канонічні ключі всієї бібліотеки — для зворотного боку.

    Коли людина гортає каталог пулу, вона має бачити, що справа вже лежить у
    неї. 🔴 Рахується ПІСЛЯ того, як відповідь пулу прийшла, і в запит не
    потрапляє нічого: це дзеркало правила `catalog/schema.py`, за яким `on_disk`
    не їде в пак. Що маю на диску — не чужа справа.
    """
    out: set[str] = set()
    try:
        from nyshporka.library import load_library
    except Exception:
        return out
    for case in load_library() or []:
        key = quad_key(str(case.get("repo") or ""), str(case.get("fond") or ""),
                       str(case.get("opys") or ""), str(case.get("spr") or ""))
        if key:
            out.add(key)
    return out


# ── зняття зрізу: ЄДИНЕ місце цього модуля, що ходить у мережу ────────────────

_DDL = (
    "CREATE TABLE pool ("
    " key TEXT PRIMARY KEY, repo TEXT, fond TEXT, opys TEXT, spr TEXT,"
    " n INTEGER, pages INTEGER, geom INTEGER, publishers TEXT, updated TEXT)",
    "CREATE INDEX pool_fond ON pool (repo, fond)",
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)",
)


def _rows_from_keys(base: str, repo: str, fond: str) -> tuple[list[dict[str, Any]], str]:
    """Швидкий шлях: `/v1/keys` віддає рядок на КНИГУ з лічильниками."""
    from nyshporka.share.catalog import _get, base_url

    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        url = f"{base_url(base)}/v1/keys?limit=5000"
        if repo:
            url += f"&repo={repo}"
        if fond:
            url += f"&fond={fond}"
        if cursor:
            url += f"&cursor={cursor}"
        got = _get(url)
        out.extend(r for r in (got.get("rows") or []) if isinstance(r, dict))
        cursor = str(got.get("next") or "")
        if not cursor:
            break
    return out, "keys"


def _rows_from_search(base: str, repo: str, fond: str) -> tuple[list[dict[str, Any]], str]:
    """Запасний шлях для старого сервера: збирати з `/v1/search` сторінками.

    ⚠ Дорожчий у рази: `/search` віддає рядок на ВНЕСОК із дев'ятнадцятьма
    колонками й має стелю 100. Тому шлях має ім'я (`via`), щоб повільність
    називалась, а не виглядала поломкою.
    """
    from nyshporka.share.catalog import search

    zvedeni: dict[str, dict[str, Any]] = {}
    offset, query = 0, (f"{repo} {fond}".strip())
    while True:
        # 🔴 `search` віддає ТРІЙКУ (рядки, збіглося, усього в пулі), а не
        # список: третє число несе рядок «пакетів N» у клієнта.
        rows, _zbihlos, _usiogo = search(query, base, limit=100, offset=offset)
        if not rows:
            break
        for r in rows:
            key = quad_key(r.repo, r.fond, r.opys, r.spr)
            if not key:
                continue
            cur = zvedeni.setdefault(key, {
                "key": key, "repo": r.repo.upper(), "fond": r.fond,
                "opys": r.opys, "spr": r.spr, "n": 0, "pages": 0,
                "geom": False, "publishers": [], "updated": ""})
            cur["n"] += 1
            cur["pages"] = max(int(cur["pages"]), int(r.pages or 0))
            cur["geom"] = bool(cur["geom"] or getattr(r, "geom_url", ""))
            if r.publisher and r.publisher not in cur["publishers"]:
                cur["publishers"].append(r.publisher)
            cur["updated"] = max(str(cur["updated"]), str(r.added or ""))
        offset += len(rows)
    return list(zvedeni.values()), "search"


def sync(base: str = "", *, repo: str = "", fond: str = "") -> dict[str, Any]:
    """Зняти зріз пулу й покласти на диск. Повертає підсумок.

    🔴 Єдина функція модуля, що ходить у мережу, і кличеться лише з волі
    людини. Читачі вище (`by_fond`, `by_key`, `meta`) мережі не знають — на
    цьому стоїть обіцянка PRIVACY, що показ колонки нічого нікуди не шле.

    ⚠ Наявний зріз лишається недоторканим, якщо мережа підвела: старий зріз із
    чесним віком кращий за порожній. Запис атомарний (`.tmp` + `replace`), бо
    обрив посеред сторінкування не має права лишити напівзріз, який виглядає
    повним.
    """
    try:
        rows, via = _rows_from_keys(base, repo, fond)
    except RuntimeError:
        # Сервер може не знати `/v1/keys` — тоді збираємо зі `search`.
        rows, via = _rows_from_search(base, repo, fond)

    from nyshporka.share.catalog import base_url

    pool_dir().mkdir(parents=True, exist_ok=True)
    tmp = snapshot_path().with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        for ddl in _DDL:
            con.execute(ddl)
        for r in rows:
            key = str(r.get("key") or quad_key(
                str(r.get("repo") or ""), str(r.get("fond") or ""),
                str(r.get("opys") or ""), str(r.get("spr") or "")))
            if not key:
                continue
            pubs = r.get("publishers") or []
            con.execute(
                "INSERT OR REPLACE INTO pool VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, str(r.get("repo") or "").upper(), str(r.get("fond") or ""),
                 str(r.get("opys") or ""), str(r.get("spr") or ""),
                 int(r.get("n") or 0), int(r.get("pages") or 0),
                 1 if r.get("geom") else 0,
                 json.dumps(list(pubs), ensure_ascii=False),
                 str(r.get("updated") or "")))
        scope = " ".join(x for x in (repo, fond) if x) or "все"
        for k, v in (("schema", str(SCHEMA)), ("base", base_url(base)),
                     ("taken_at", datetime.now(UTC).isoformat(timespec="seconds")),
                     ("of", str(len(rows))), ("scope", scope), ("via", via)):
            con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
        con.commit()
    finally:
        con.close()

    tmp.replace(snapshot_path())
    invalidate()
    return {"of": len(rows), "via": via, "scope": scope, "path": str(snapshot_path())}
