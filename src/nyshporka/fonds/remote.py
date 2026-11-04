"""🗂 Реєстри опису фондів із Супряги: узяти фонд, далі дотягувати лише змінене.

Реєстр опису — перелік справ фонду з назвою, роками й тим, де скан онлайн
(плівка FS із кадрами, Commons, Archium, сайт архіву). Збирати його самому —
години збирачів на фонд, а колонки FS дають лише знімки каталогу FS, яких у
людини немає. Тому Майстерня заливає свої реєстри в Супрягу, а решта бере їх
звідти: `nysh registry pull --repo DAHMO --fond 315`.

🔴 **Це не дзеркало Качиного Інспектора.** У Супрязі лише ті фонди, які
Майстерня збирає для своєї роботи, і свіжі вони рівно станом на її останню
заливку (`pushed_at`). Для решти фондів джерело — сам покажчик (збирач `duck`).

🔴 **Свій реєстр сильніший за взятий.** Якщо `data/raw/<slug>/f<фонд>_opys_merged.tsv`
лежить на диску, читається він, а не копія з Супряги: людина, яка зібрала опис
сама, бачить своє, навіть коли свіже чуже вже приїхало.

Як дотягується змінене. Сервер дає кожній зміні рядка номер `rev`. Стор
пам'ятає найбільший номер фонду й наступного разу просить лише рядки понад
нього. Видалений на сервері рядок приходить позначкою й видаляється тут.

Це ЄДИНЕ місце модуля `fonds`, що ходить у мережу, і лише на прямий виклик:
читання реєстру мережі не торкається ніколи.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Стеля сторінки читання — як на сервері (`app.rehistr.MAX_LIMIT`).
PAGE = 5000
#: Стеля рядків за одну заливку (`app.rehistr.MAX_RIADKIV`).
PUSH_CHUNK = 2000
#: Стеля тексту пачки: тіло запиту до API Супряги — до 1 МБ (nginx), з запасом.
PUSH_BYTES = 600_000
#: Після скількох днів узятий реєстр варто дотягнути. Лише підказка: реєстр
#: старіє повільно, бо назви й роки справ не змінюються, а стан онлайн — так.
SVIZHYI_DNIV = 30

STORE_NAME = "fonds.sqlite"
SCHEMA = "1"

_DDL = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    # Фонд, узятий із Супряги: `rev` — найбільший побачений номер зміни,
    # `pushed_at` — станом на коли реєстр у Супрязі, `refreshed_at` — коли
    # востаннє дотягували сюди.
    "CREATE TABLE IF NOT EXISTS fond ("
    " repo TEXT NOT NULL, fond TEXT NOT NULL, fond_id TEXT NOT NULL, label TEXT,"
    " rev INTEGER NOT NULL DEFAULT 0, rows INTEGER NOT NULL DEFAULT 0,"
    " schema TEXT, pushed_at TEXT, taken_at TEXT, refreshed_at TEXT, base TEXT,"
    " PRIMARY KEY (repo, fond))",
    "CREATE UNIQUE INDEX IF NOT EXISTS fond_by_id ON fond (fond_id)",
    "CREATE TABLE IF NOT EXISTS sprava ("
    " repo TEXT NOT NULL, fond TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,"
    " PRIMARY KEY (repo, fond, key))",
    # Бік власника: відбиток останньої заливки фонду, щоб `push --all` не
    # питав сервер про фонди, у яких нічого не змінилось.
    "CREATE TABLE IF NOT EXISTS pushed ("
    " repo TEXT NOT NULL, fond TEXT NOT NULL, digest TEXT NOT NULL, rows INTEGER,"
    " at TEXT, PRIMARY KEY (repo, fond))",
)


class RegistryRemoteError(RuntimeError):
    """Супряга не дала реєстру; текст призначений людині."""


class NotInSupriaha(RegistryRemoteError):
    """Цього фонду в Супрязі немає."""


# ── стор ──────────────────────────────────────────────────────────────────────

def store_path() -> Path:
    """`data/derived/supriaha/fonds.sqlite` — поруч зі зрізом пулу.

    У `derived`, а не в `data/raw`: це копія чужої заливки, яку можна стерти й
    узяти знову, а не зібране самим дослідником.
    """
    from nyshporka.core.workspace import workspace

    return workspace().derived / "supriaha" / STORE_NAME


def _connect(*, create: bool) -> sqlite3.Connection | None:
    p = store_path()
    if not p.is_file():
        if not create:
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    if create:
        with con:
            for ddl in _DDL:
                con.execute(ddl)
            con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA,))
    return con


def stamp() -> tuple[Any, ...]:
    """Штамп стору для memo читача: будь-яке дотягування міняє файл."""
    p = store_path()
    try:
        st = p.stat()
    except OSError:
        return (str(p), -1, -1)
    return (str(p), st.st_mtime_ns, st.st_size)


def taken() -> list[dict[str, Any]]:
    """Фонди, узяті з Супряги на цю машину."""
    con = _connect(create=False)
    if con is None:
        return []
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM fond WHERE rows > 0 ORDER BY repo, fond")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def taken_one(fond_id: str) -> dict[str, Any] | None:
    for f in taken():
        if f["fond_id"] == fond_id:
            return f
    return None


def rows_of(fond_id: str) -> list[dict[str, Any]] | None:
    """Сирі рядки взятого фонду (`data` із Супряги); `None` — фонд не взято."""
    con = _connect(create=False)
    if con is None:
        return None
    try:
        f = con.execute("SELECT repo, fond FROM fond WHERE fond_id = ? AND rows > 0",
                        (fond_id,)).fetchone()
        if f is None:
            return None
        return [json.loads(r["data"]) for r in con.execute(
            "SELECT data FROM sprava WHERE repo = ? AND fond = ?", (f["repo"], f["fond"]))]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def age_days(f: dict[str, Any]) -> int | None:
    """Скільки днів тому фонд дотягували; `None` — невідомо."""
    try:
        at = datetime.fromisoformat(str(f.get("refreshed_at") or ""))
    except ValueError:
        return None
    return (datetime.now(UTC) - at).days


# ── мережа ────────────────────────────────────────────────────────────────────

def _url(base: str, path: str, **params: Any) -> str:
    from urllib.parse import urlencode

    from nyshporka.share.catalog import base_url

    qs = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{base_url(base)}{path}" + (f"?{qs}" if qs else "")


def _get(url: str) -> dict[str, Any]:
    from nyshporka.share import vyklyky as V

    return V._get(url)


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    from nyshporka.share import vyklyky as V

    return V._post(url, body)


def remote_list(base: str = "") -> list[dict[str, Any]]:
    """Які реєстри фондів є в Супрязі і станом на коли."""
    got = _get(_url(base, "/fonds"))
    return [f for f in got.get("fonds") or [] if isinstance(f, dict)]


def _pages(base: str, repo: str, fond: str, since: int) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    cursor = since
    while True:
        page = _get(_url(base, "/fonds/rows", repo=repo, fond=fond, since=cursor,
                         limit=PAGE))
        yield page
        nxt = str(page.get("next") or "")
        if not nxt:
            return
        if nxt in seen:
            # Сервер повторив курсор — без цього цикл не скінчився б ніколи.
            raise RegistryRemoteError("Супряга повторила курсор гортання — реєстр не взято")
        seen.add(nxt)
        cursor = int(nxt)


def pull(repo: str, fond: str, base: str = "", *, full: bool = False) -> dict[str, Any]:
    """Узяти фонд із Супряги: першого разу весь, далі лише змінене.

    Спершу вся мережа, потім один запис у стор однією транзакцією: обрив
    посередині не лишає фонд наполовину оновленим.
    """
    from nyshporka.fonds.registry import fond_id_of
    from nyshporka.share.catalog import PoolError

    repo, fond = repo.strip().upper(), str(fond).strip()
    con = _connect(create=True)
    assert con is not None
    try:
        have = con.execute("SELECT rev FROM fond WHERE repo = ? AND fond = ? AND rows > 0",
                           (repo, fond)).fetchone()
        since = 0 if (full or have is None) else int(have["rev"])
        try:
            pages = list(_pages(base, repo, fond, since))
        except PoolError as exc:
            if exc.status == 404:
                raise NotInSupriaha(
                    f"реєстру {repo} ф.{fond} у Супрязі немає. Що там є — "
                    f"`nysh registry remote`; зібрати самому — `nysh registry sources`"
                ) from exc
            raise
        head = pages[-1]
        if since and int(head.get("rev") or 0) < since:
            # Номери на сервері почались наново (базу переналаштовано): «лише
            # змінене» тоді мовчки пропустило б усе. Беремо фонд цілком.
            return pull(repo, fond, base, full=True)
        got = [r for p in pages for r in (p.get("rows") or []) if isinstance(r, dict)]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        added = deleted = 0
        with con:
            if since == 0:
                con.execute("DELETE FROM sprava WHERE repo = ? AND fond = ?", (repo, fond))
            for r in got:
                key = str(r.get("key") or "")
                if not key:
                    continue
                if r.get("deleted"):
                    deleted += con.execute(
                        "DELETE FROM sprava WHERE repo = ? AND fond = ? AND key = ?",
                        (repo, fond, key)).rowcount
                    continue
                con.execute("INSERT OR REPLACE INTO sprava VALUES (?,?,?,?)",
                            (repo, fond, key,
                             json.dumps(r.get("data") or {}, ensure_ascii=False)))
                added += 1
            n = con.execute("SELECT count(*) FROM sprava WHERE repo = ? AND fond = ?",
                            (repo, fond)).fetchone()[0]
            raw_meta = head.get("meta")
            meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
            con.execute(
                "INSERT INTO fond (repo, fond, fond_id, label, rev, rows, schema, pushed_at,"
                " taken_at, refreshed_at, base) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (repo, fond) DO UPDATE SET label = excluded.label,"
                " rev = excluded.rev, rows = excluded.rows, schema = excluded.schema,"
                " pushed_at = excluded.pushed_at, refreshed_at = excluded.refreshed_at,"
                " base = excluded.base, fond_id = excluded.fond_id",
                (repo, fond, fond_id_of(repo, fond), str(head.get("label") or ""),
                 int(head.get("rev") or 0), int(n), str(meta.get("schema") or ""),
                 head.get("pushed_at"), now, now, base or ""))
    finally:
        con.close()
    return {"repo": repo, "fond": fond, "fond_id": fond_id_of(repo, fond),
            "label": str(head.get("label") or ""), "first": since == 0, "got": added,
            "deleted": deleted, "rows": int(n), "rev": int(head.get("rev") or 0),
            "pushed_at": head.get("pushed_at")}


def pull_taken(base: str = "") -> list[dict[str, Any]]:
    """Дотягнути всі вже взяті фонди. Помилка одного не спиняє решту."""
    out: list[dict[str, Any]] = []
    for f in taken():
        try:
            out.append(pull(f["repo"], f["fond"], base))
        except RegistryRemoteError as exc:
            out.append({"repo": f["repo"], "fond": f["fond"], "error": str(exc)})
        except Exception as exc:  # мережа, сервер — фонд лишається, яким був
            out.append({"repo": f["repo"], "fond": f["fond"],
                        "error": f"{type(exc).__name__}: {exc}"})
    return out


# ── бік власника: заливка ─────────────────────────────────────────────────────

def hash_data(data: dict[str, Any]) -> str:
    """Відбиток рядка — так само, як `app.rehistr.hash_danykh` на сервері."""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def row_key(row: dict[str, Any]) -> str:
    """Ключ справи в реєстрі Супряги: опис/номер+літера в каноні письма.

    Канон той самий, що в `registry.disk_key`: `355a` = `355а`, `1d` = `1д`, тож
    той самий рядок з іншим письмом не стає новою справою на сервері.
    """
    from nyshporka.fonds.registry import disk_key

    o, n, lt = disk_key(row.get("opys"), row.get("spr_int"), row.get("spr_letter"))
    return f"{o}/{n}{lt}"


def payload(fond_id: str) -> tuple[list[dict[str, Any]], int]:
    """Рядки фонду для заливки (лише білий список полів) і скільки ключів повторилось.

    Повтор ключа лишає ПЕРШИЙ рядок — так само, як його бере `registry_row`.
    """
    from nyshporka.fonds.registry import load_rows, public_data

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    dup = 0
    for r in load_rows(fond_id):
        key = row_key(r)
        if not key.strip("/"):
            continue
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        out.append({"key": key, "data": public_data(r)})
    return out, dup


def _chunks(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Пачки для заливки: не більше `PUSH_CHUNK` рядків і `PUSH_BYTES` тексту.

    🔴 Тіло запиту до API Супряги обмежене 1 МБ (nginx), а 2000 рядків реєстру
    з довгими назвами — близько 1,2 МБ: пачка за самою кількістю дістала б 413.
    """
    chunk: list[dict[str, Any]] = []
    size = 0
    for r in rows:
        n = len(json.dumps(r, ensure_ascii=False).encode("utf-8")) + 1
        if chunk and (len(chunk) >= PUSH_CHUNK or size + n > PUSH_BYTES):
            yield chunk
            chunk, size = [], 0
        chunk.append(r)
        size += n
    if chunk:
        yield chunk


def _digest(rows: list[dict[str, Any]], label: str, schema: str) -> str:
    h = hashlib.sha256(f"{label}\n{schema}\n".encode())
    for r in sorted(rows, key=lambda x: x["key"]):
        h.update(f"{r['key']}:{hash_data(r['data'])}\n".encode())
    return h.hexdigest()


def push(fond_id: str, base: str = "") -> dict[str, Any]:
    """Залити свій реєстр фонду в Супрягу: лише змінене, видалене — позначкою.

    Заливати може лише власник Супряги: сервер іншим відповідає 404.
    """
    from nyshporka.fonds.registry import discover_fonds, schema_of
    from nyshporka.share.catalog import PoolError

    f = next((x for x in discover_fonds() if x["id"] == fond_id
              and x.get("source") == "disk"), None)
    if f is None:
        raise RegistryRemoteError(
            f"реєстру {fond_id} на диску немає — заливається лише зібраний тут "
            "(`data/raw/<slug>/f<фонд>_opys_merged.tsv`), а не взятий із Супряги")
    repo, fond, label = f["repo"], f["fond"], f["label"]
    rows, dup = payload(fond_id)
    schema = schema_of(fond_id)
    try:
        theirs = _get(_url(base, "/fonds/hashes", repo=repo, fond=fond)).get("hashes") or {}
    except PoolError as exc:
        if exc.status == 404:
            raise RegistryRemoteError(
                "заливати реєстри в Супрягу може лише її власник") from exc
        raise
    mine = {r["key"] for r in rows}
    changed = [r for r in rows if theirs.get(r["key"]) != hash_data(r["data"])]
    gone = sorted(k for k in theirs if k not in mine)
    meta = {"schema": schema}
    last: dict[str, Any] = {}
    sent = 0
    for chunk in _chunks(changed):
        last = _post(_url(base, "/fonds/rows"), {
            "repo": repo, "fond": fond, "label": label, "meta": meta, "rows": chunk})
        sent += len(chunk)
    # Останній виклик несе видалення, і він же — коли нічого не змінилось:
    # «станом на» в Супрязі тоді теж оновлюється.
    if gone or not changed:
        last = _post(_url(base, "/fonds/rows"), {
            "repo": repo, "fond": fond, "label": label, "meta": meta, "rows": [],
            "delete": gone})
    con = _connect(create=True)
    assert con is not None
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO pushed VALUES (?,?,?,?,?)",
                        (repo, fond, _digest(rows, label, schema), len(rows),
                         datetime.now(UTC).isoformat(timespec="seconds")))
    finally:
        con.close()
    return {"id": fond_id, "repo": repo, "fond": fond, "label": label, "rows": len(rows),
            "sent": sent, "deleted": len(gone), "same": len(rows) - len(changed),
            "dup": dup, "rev": last.get("rev"), "pushed_at": last.get("pushed_at")}


def _pushed_digest(repo: str, fond: str) -> str:
    con = _connect(create=False)
    if con is None:
        return ""
    try:
        got = con.execute("SELECT digest FROM pushed WHERE repo = ? AND fond = ?",
                          (repo, fond)).fetchone()
        return str(got["digest"]) if got else ""
    except sqlite3.Error:
        return ""
    finally:
        con.close()


def push_config() -> dict[str, Any]:
    """`[registry.push]` маркера Майстерні: `enabled`, `exclude` (ідентифікатори фондів).

    Порожньо — самозаливки немає: у людини, яка не є власником Супряги, злиття
    не має куди заливати.
    """
    from nyshporka.core.workspace import MARKER, _read_toml, workspace

    reg = _read_toml(workspace().hub / MARKER).get("registry") or {}
    got = reg.get("push") if isinstance(reg, dict) else None
    return got if isinstance(got, dict) else {}


def excluded(fond_id: str, cfg: dict[str, Any] | None = None) -> bool:
    cfg = push_config() if cfg is None else cfg
    return fond_id in {str(x) for x in cfg.get("exclude") or []}


def push_all(base: str = "", *, force: bool = False) -> list[dict[str, Any]]:
    """Залити всі свої реєстри, крім виключених; незмінені від минулої заливки — пропустити."""
    from nyshporka.fonds.registry import discover_fonds, schema_of

    cfg = push_config()
    out: list[dict[str, Any]] = []
    for f in discover_fonds():
        if f.get("source") != "disk":
            continue
        if excluded(f["id"], cfg):
            out.append({"id": f["id"], "skipped": "excluded"})
            continue
        rows, _ = payload(f["id"])
        if not rows:
            out.append({"id": f["id"], "skipped": "empty"})
            continue
        if not force and _pushed_digest(f["repo"], f["fond"]) == _digest(
                rows, f["label"], schema_of(f["id"])):
            out.append({"id": f["id"], "skipped": "same"})
            continue
        try:
            out.append(push(f["id"], base))
        except Exception as exc:  # один фонд не спиняє решту
            out.append({"id": f["id"], "error": f"{type(exc).__name__}: {exc}"})
    return out


def auto_push(fond_id: str) -> dict[str, Any] | None:
    """Самозаливка після злиття, якщо її ввімкнено в `[registry.push]`.

    `None` — вимкнено або фонд виключено. Збій повертається словником з
    `error`: злиття вже відбулося, і заливка його не скасовує.
    """
    cfg = push_config()
    if not cfg.get("enabled") or excluded(fond_id, cfg):
        return None
    try:
        return push(fond_id)
    except Exception as exc:
        return {"id": fond_id, "error": f"{type(exc).__name__}: {exc}"}
