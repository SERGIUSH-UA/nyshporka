"""Файл черги, замки й журнал.

Усе лежить у `data/queue/`, а не в `data/derived`: перелік замовленого й
причини зупинок повторним запуском не відтворюються.

Два замки рівня ОС (`core.xrate._locked`), обидва зникають разом із процесом:

* `queue.lock` — коротка транзакція «прочитав → змінив → записав», щоб
  `queue add` з другого термінала не загубився під рукою виконавця;
* `run.lock` — єдиний виконавець на простір. Тримається весь час роботи, тож
  «чи веде хтось чергу» — це спроба його взяти, а не перевірка pid із файла:
  після вбитого процесу «вічного» виконавця не лишається.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SCHEMA = 1

# ── стани справи ─────────────────────────────────────────────────────────────
QUEUED = "queued"        # чекає своєї черги
RUNNING = "running"      # її зараз веде виконавець
RETRY = "retry"          # тимчасова відмова: сама повториться після `not_before`
BLOCKED = "blocked"      # чекає людину: є причина й команда
FAILED = "failed"        # остаточна відмова: повтор не допоможе
DONE = "done"
DROPPED = "dropped"      # знято людиною; з диска нічого не видалено

#: Стани, з яких справа ще піде далі сама.
LIVE = (QUEUED, RUNNING, RETRY)
#: Стани, що чекають рішення людини.
WAITING = (BLOCKED, FAILED)

NAZVY = {
    QUEUED: "у черзі", RUNNING: "у роботі", RETRY: "повторить сама",
    BLOCKED: "чекає вас", FAILED: "відмова", DONE: "зроблено", DROPPED: "знято",
}

# ── прапор зупинки ───────────────────────────────────────────────────────────
STOP_AFTER_CASE = "after_case"   # доробити поточну справу, наступну не брати
STOP_NOW = "now"                 # погасити читання; прочитане лишається

#: Скільки чекати на транзакцію, перш ніж сказати «файл черги зайнятий».
EDIT_WAIT_SEC = 10.0
#: Рядків журналу, які віддає читач.
JOURNAL_TAIL = 200


class QueueError(RuntimeError):
    """Із чергою не можна зробити те, що просили, — з причиною для людини."""


class RunnerBusy(QueueError):
    """Чергу вже веде інший процес."""

    def __init__(self, pid: int) -> None:
        who = f"процес {pid}" if pid else "інший процес"
        super().__init__(
            f"чергу вже веде {who}. Другий виконавець на тому самому просторі "
            f"читав би ті самі справи вдруге. Стан — `nysh queue`; зупинити після "
            f"поточної справи — `nysh queue stop`")
        self.pid = pid


def home() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().data / "queue"


def path() -> Path:
    return home() / "queue.json"


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "items": [], "stop": "", "runner": {}}


def load() -> dict[str, Any]:
    """Черга, як вона лежить на диску. Побитий файл — відмова, а не порожня черга."""
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(path(), default=None)
    except CorruptFileError as exc:
        raise QueueError(
            f"файл черги побитий ({path()}): {exc}. Він не перезаписується — "
            f"у ньому перелік замовлених справ. Полагодьте JSON або приберіть "
            f"файл і додайте справи наново") from None
    if raw is None:
        return _empty()
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise QueueError(f"файл черги має не ту будову ({path()}) — не чіпаю")
    return {**_empty(), **raw}


@contextlib.contextmanager
def edit() -> Iterator[dict[str, Any]]:
    """Транзакція над чергою: усередині — свіжий стан, на виході — запис.

    Виняток усередині запис скасовує.
    """
    from nyshporka.core.xrate import LockTimeout, _locked
    from nyshporka.utils.atomic import write_json

    try:
        with _locked(home() / "queue.lock", timeout=EDIT_WAIT_SEC):
            q = load()
            yield q
            write_json(path(), q)
    except LockTimeout:
        raise QueueError(
            f"файл черги зайнятий довше {EDIT_WAIT_SEC:.0f} с — повторіть команду") from None


# ── виконавець ───────────────────────────────────────────────────────────────
def runner_alive() -> bool:
    """Чи веде хтось чергу просто зараз. Судить замок, а не запис у файлі."""
    from nyshporka.core.xrate import LockTimeout, _locked

    if not home().is_dir():
        return False
    try:
        with _locked(home() / "run.lock", timeout=0.0):
            return False
    except LockTimeout:
        return True
    except OSError:
        return False


@contextlib.contextmanager
def own() -> Iterator[None]:
    """Стати єдиним виконавцем черги на весь час роботи."""
    from nyshporka.core.xrate import LockTimeout, _locked

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_locked(home() / "run.lock", timeout=0.0))
        except LockTimeout:
            pid = 0
            with contextlib.suppress(QueueError, ValueError, TypeError):
                pid = int((load().get("runner") or {}).get("pid") or 0)
            raise RunnerBusy(pid) from None
        with edit() as q:
            q["runner"] = {"pid": os.getpid(), "started": now()}
        try:
            yield
        finally:
            with contextlib.suppress(QueueError), edit() as q:
                q["runner"] = {}
            with contextlib.suppress(OSError):
                (home() / "pulse.json").unlink(missing_ok=True)


# ── справи ───────────────────────────────────────────────────────────────────
def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def stamp(text: str) -> float:
    """Час із рядка `now()`; нерозібраний — 0 («давно»)."""
    try:
        return time.mktime(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


def new_item(item_id: str, ref: dict[str, str], opts: dict[str, Any]) -> dict[str, Any]:
    from nyshporka.core.casekey import require_current

    # Нова справа черги несе ключ справи — до переносу обліку він ліг би поруч
    # зі старими. Хід уже доданих справ (демон) не стримується.
    require_current("справа в черзі")
    return {"id": item_id, "ref": ref, "opts": opts, "added": now(),
            "state": QUEUED, "stage": "", "code": "", "why": "", "fix": "",
            "attempts": {}, "not_before": "", "evidence": {}}


def _norm(text: Any) -> str:
    return str(text or "").replace("\\", "/").rstrip("/").casefold()


def find(q: dict[str, Any], ref: str) -> dict[str, Any] | None:
    """Справа черги за тим, як її назвала людина: ключ, тека або хвіст теки.

    Знятих не шукає: `add` після `drop` заводить справу наново.
    """
    from nyshporka.core import legacy_key

    want = _norm(legacy_key.current_key(str(ref or "")))
    if not want:
        return None
    items: list[dict[str, Any]] = [
        it for it in q["items"] if it.get("state") != DROPPED]
    # Обидві сторони — новим ключем: справи, заведені до переносу обліку,
    # тримають у черзі старий (`nysh cases rekey` переводить і їх).
    for it in items:
        names = (_norm(legacy_key.current_key(str(it.get("id") or ""))),
                 _norm(legacy_key.current_key(str((it.get("ref") or {}).get("key") or ""))),
                 _norm((it.get("ref") or {}).get("dir")))
        if want in names:
            return it
    tails = [it for it in items
             if _norm((it.get("ref") or {}).get("dir")).endswith("/" + want)]
    return tails[0] if len(tails) == 1 else None


def need(q: dict[str, Any], ref: str) -> dict[str, Any]:
    it = find(q, ref)
    if it is None:
        raise QueueError(f"у черзі немає справи «{ref}». Перелік — `nysh queue`")
    return it


def settle(it: dict[str, Any], state: str, *, stage: str = "", code: str = "",
           why: str = "", fix: str = "", not_before: str = "") -> None:
    """Записати, на чому справа стала."""
    it.update(state=state, stage=stage, code=code, why=why, fix=fix,
              not_before=not_before, updated=now())


# ── журнал і пульс ───────────────────────────────────────────────────────────
def journal(**fields: Any) -> None:
    """Рядок про завершений етап: що, чим скінчилось, скільки тривало."""
    from nyshporka.core.xrate import LockTimeout, _locked

    row = {"at": now(), **{k: v for k, v in fields.items() if v not in ("", None)}}
    home().mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(LockTimeout, OSError), \
            _locked(home() / "queue.lock", timeout=EDIT_WAIT_SEC), \
            (home() / "journal.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_journal(limit: int = JOURNAL_TAIL) -> list[dict[str, Any]]:
    """Хвіст журналу, старіші спершу. Побитий рядок рахується, а не зникає."""
    f = home() / "journal.jsonl"
    if not f.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in f.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            row = json.loads(line)
        except ValueError:
            row = {"broken": line[:120]}
        out.append(row if isinstance(row, dict) else {"broken": line[:120]})
    return out


def pulse(**fields: Any) -> None:
    """Прогрес поточного етапу. Пише лише виконавець, читає будь-хто."""
    from nyshporka.utils.atomic import write_json

    with contextlib.suppress(OSError):
        write_json(home() / "pulse.json", {"at": now(), **fields})


def read_pulse() -> dict[str, Any]:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(home() / "pulse.json", default={})
    except CorruptFileError:
        return {}
    return raw if isinstance(raw, dict) else {}
