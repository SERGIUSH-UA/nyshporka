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
    kody = synonyms(key[0])
    if not any(covers(k, fond) for k in kody):
        return None

    con = _connect()
    if con is None:
        return None
    handle = _handle()
    out: dict[tuple[str, str, str], PoolCell] = {}
    try:
        for kod in kody:
            rows = con.execute(
                "SELECT opys, spr, n, pages, geom, publishers, updated "
                "FROM pool WHERE repo = ? AND fond = ?", (kod, key[1])).fetchall()
            for r in rows:
                spr = str(r["spr"] or "")
                i = len(spr)
                while i and not spr[i - 1].isdigit():
                    i -= 1
                out.setdefault((str(r["opys"] or ""), spr[:i], spr[i:]),
                               _cell(r, handle))
    except sqlite3.Error:
        return None
    finally:
        con.close()

    _FOND_CACHE[key] = (stamp, out)
    return out


def by_key(key: str) -> PoolCell | None:
    """Одна книга за канонічним ключем. `None` — немає зрізу або немає книги.

    Код архіву в ключі пробується з усіма синонімами (`DAVO` = `DAVIO`).
    Чи питали пул про цей фонд узагалі, каже `covers`, а не ця функція.
    """
    con = _connect()
    if con is None or meta() is None:
        return None
    head, _, tail = (key or "").partition("/")
    try:
        for kod in synonyms(head):
            row = con.execute(
                "SELECT opys, spr, n, pages, geom, publishers, updated "
                "FROM pool WHERE key = ?", (f"{kod}/{tail}",)).fetchone()
            if row:
                return _cell(row, _handle())
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None


def known(key: str) -> str | None:
    """Стан книги в зрізі: `none | text | text+geom`, або `None` — не питали.

    Одна відповідь на три випадки, які доти плутались: зрізу немає, фонд
    поза охопленням зрізу, книги в охопленому фонді немає.
    """
    if meta() is None:
        return None
    parts = (key or "").split("/")
    if len(parts) < 2 or not any(covers(k, parts[1]) for k in synonyms(parts[0])):
        return None
    cell = by_key(key)
    if cell is not None and cell.mine is False:
        # Книга є, але не ваша — для «чи віддавати своє» це «немає».
        return "none"
    return state_of(cell)


def synonyms(repo: str) -> list[str]:
    """Код архіву й усі коди того самого архіву (`same_as` в обидва боки).

    🔴 Пул пише Вінницький архів каноном пакета `DAVIO`, а дослідницький
    простір може лишатись на давньому `DAVO`. Без цього справа, що давно в
    пулі, показувалась «готовою» до віддачі, а колонка «пул» у `cases fond
    DAVO …` — порожньою на всьому фонді.
    """
    code = (repo or "").strip().upper()
    out = [code]
    try:
        from nyshporka.archives import active

        repos = active().repositories
    except Exception:
        return out
    same = str(getattr(repos.get(code), "same_as", "") or "").upper()
    for c, r in repos.items():
        other = str(getattr(r, "same_as", "") or "").upper()
        if c.upper() != code and (other == code or c.upper() == same
                                  or (same and other == same)):
            out.append(c.upper())
    return list(dict.fromkeys(out))


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
    """Швидкий шлях: `/keys` віддає рядок на КНИГУ з лічильниками.

    ⚠ `base_url()` уже закінчується на `/v1`, тож тут лише `/keys` — доти
    запит ішов на `/v1/v1/keys`, і швидкого шляху фактично не було.
    """
    from urllib.parse import urlencode

    from nyshporka.share.catalog import PoolError, _get, base_url

    out: list[dict[str, Any]] = []
    cursor = ""
    seen: set[str] = set()
    while True:
        params = {"limit": 5000, "repo": repo, "fond": fond, "cursor": cursor}
        qs = urlencode({k: v for k, v in params.items() if v})
        got = _get(f"{base_url(base)}/keys?{qs}")
        out.extend(r for r in (got.get("rows") or []) if isinstance(r, dict))
        cursor = str(got.get("next") or "")
        if not cursor:
            break
        if cursor in seen:
            # Сервер повторив курсор — без цього цикл не скінчився б ніколи.
            raise PoolError("пул повторив курсор гортання — зріз не знято")
        seen.add(cursor)
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
            cur["pages"] = max(_int(cur["pages"]), _int(r.pages))
            cur["geom"] = bool(cur["geom"] or getattr(r, "geom_url", ""))
            if r.publisher and r.publisher not in cur["publishers"]:
                cur["publishers"].append(r.publisher)
            cur["updated"] = max(str(cur["updated"]), str(r.added or ""))
        offset += len(rows)
        if _usiogo and offset >= _usiogo:
            break
    return list(zvedeni.values()), "search"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


#: Позначка повного зрізу в `meta.scope`.
ALL = "*"


def _scope_items(repo: str, fond: str) -> list[str]:
    """Що саме покриває зріз: `*`, `DAHMO` або `DAHMO/315`."""
    r = (repo or "").strip().upper()
    f = str(fond or "").strip()
    if not r and not f:
        return [ALL]
    if r and f:
        return [f"{r}/{f}"]
    # Фонд без архіву — його номер повторюється в кожному архіві, тож
    # покриття пишеться окремою формою: «цей фонд у будь-якому архіві».
    return [r] if r else [f"*/{f}"]


def scope() -> list[str]:
    """Покриття зрізу. Старий зріз без списку — прочитати з рядка."""
    m = meta()
    if not m:
        return []
    raw = str(m.get("scope_items") or "")
    if raw:
        try:
            got = json.loads(raw)
            if isinstance(got, list):
                return [str(x) for x in got]
        except ValueError:
            pass
    return [ALL] if str(m.get("scope") or "все") == "все" else []


def covers(repo: str, fond: str) -> bool:
    """Чи питали пул про цей фонд.

    🔴 Без цього зріз одного фонду (`sync --fond 315`) відповідав «у пулі
    немає» про решту фондів — тобто «не питали» знову ставало «немає», і
    людина замовляла прогін справи, яка лежить готова.
    """
    items = scope()
    r = (repo or "").strip().upper()
    f = str(fond or "").strip()
    return (ALL in items or r in items or f"{r}/{f}" in items
            or f"*/{f}" in items)


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
    from nyshporka.share.catalog import PoolError, base_url

    try:
        rows, via = _rows_from_keys(base, repo, fond)
    except PoolError as exc:
        # Сервер може не знати `/keys` — тоді збираємо зі `search`. 🔴 Лише
        # на 404: будь-яка інша відмова (лежить, немає ключа) повторилась би
        # і на пошуку, тобто людина чекала б удвічі довше тієї самої помилки.
        if exc.status != 404:
            raise
        rows, via = _rows_from_search(base, repo, fond)

    novi = _scope_items(repo, fond)
    if novi != [ALL]:
        # Пошуковий шлях шукає рядком «архів фонд» і приносить сусідів —
        # у зріз лягає лише те, що справді в охопленні.
        rows = [r for r in rows if _in_scope(r, novi)]

    # 🔴 Частковий зріз ДОПИСУЄТЬСЯ до наявного, а не замінює його. Інакше
    # `sync --fond 315` стирав усі інші фонди, і вони читались «у пулі
    # немає» — хоч про них просто не питали.
    stari = [] if novi == [ALL] else _old_rows_outside(novi)
    bulo = [] if novi == [ALL] else [s for s in scope() if s not in novi]
    pokryttia = [ALL] if ALL in bulo else bulo + novi
    old_meta = meta() or {}

    pool_dir().mkdir(parents=True, exist_ok=True)
    tmp = snapshot_path().with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        for ddl in _DDL:
            con.execute(ddl)
        for old in stari:
            con.execute("INSERT OR REPLACE INTO pool VALUES (?,?,?,?,?,?,?,?,?,?)", old)
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
                 _int(r.get("n")), _int(r.get("pages")),
                 1 if r.get("geom") else 0,
                 json.dumps(list(pubs) if isinstance(pubs, list) else [],
                            ensure_ascii=False),
                 str(r.get("updated") or "")))
        now = datetime.now(UTC).isoformat(timespec="seconds")
        # Вік зрізу — вік НАЙСТАРШОЇ його частини: освіжений фонд не робить
        # свіжими решту, а показ «зрізу годину» над ними був би неправдою.
        taken = (str(old_meta.get("taken_at") or now) if stari or bulo else now)
        total = con.execute("SELECT COUNT(*) FROM pool").fetchone()[0]
        opys_scope = "все" if pokryttia == [ALL] else ", ".join(pokryttia)
        for k, v in (("schema", str(SCHEMA)), ("base", base_url(base)),
                     ("taken_at", taken), ("refreshed_at", now),
                     ("of", str(total)), ("scope", opys_scope),
                     ("scope_items", json.dumps(pokryttia, ensure_ascii=False)),
                     ("via", via)):
            con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
        con.commit()
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()

    tmp.replace(snapshot_path())
    invalidate()
    scope_text = " ".join(x for x in (repo, fond) if x) or "все"
    return {"of": len(rows), "total": total, "via": via, "scope": scope_text,
            "covers": pokryttia, "path": str(snapshot_path())}


def _in_scope(row: dict[str, Any], items: list[str]) -> bool:
    r = str(row.get("repo") or "").strip().upper()
    f = str(row.get("fond") or "").strip()
    return any(s in (ALL, r, f"{r}/{f}", f"*/{f}") for s in items)


def _old_rows_outside(items: list[str]) -> list[tuple[Any, ...]]:
    """Рядки наявного зрізу поза новим охопленням — вони лишаються як були."""
    con = _connect()
    if con is None or meta() is None:
        return []
    try:
        rows = con.execute(
            "SELECT key, repo, fond, opys, spr, n, pages, geom, publishers, updated "
            "FROM pool").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [tuple(r) for r in rows if not _in_scope(dict(r), items)]
