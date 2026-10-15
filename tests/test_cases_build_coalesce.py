"""🔁 Перезбірка реєстру зливає одночасні запити: скільки б не попросили, збірок
дві — та, що йде, і одна після неї для всіх, хто попросив під час неї.

🔴 Друга половина твердження важить не менше за першу: запит, зроблений ПІД ЧАС
збірки, нею не закривається — вона читала диск до того, як його попросили.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def slow_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Фальшива збірка: рахує виклики, кожна триває `dur` секунд."""
    from nyshporka.cases import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "case_index.sqlite")
    # 2 с, а не 0.6: на повільному раннері CI десять потоків інколи не
    # встигали стартувати за першу збірку, і запізнілий запит законно давав
    # третю (py3.11 · ubuntu, 15.10.2026).
    state: dict[str, Any] = {"n": 0, "running": 0, "max_running": 0, "dur": 2.0,
                             "started": threading.Event()}
    lock = threading.Lock()

    def fake(*, rescan: bool = True, fetch_cloud: bool = False) -> dict[str, Any]:
        with lock:
            state["n"] += 1
            n = state["n"]
            state["running"] += 1
            state["max_running"] = max(state["max_running"], state["running"])
        state["started"].set()
        time.sleep(state["dur"])
        with lock:
            state["running"] -= 1
        return {"build": n, "rescanned": rescan}

    monkeypatch.setattr(db, "_rebuild_now", fake)
    return state


def _run(n: int) -> tuple[list[threading.Thread], list[dict[str, Any]]]:
    from nyshporka.cases import db

    out: list[dict[str, Any]] = []
    ts = [threading.Thread(target=lambda: out.append(db.rebuild())) for _ in range(n)]
    for t in ts:
        t.start()
    return ts, out


def test_burst_during_a_build_costs_one_more_build(slow_build: dict[str, Any]) -> None:
    first, got1 = _run(1)
    assert slow_build["started"].wait(5)
    time.sleep(0.1)
    later, got2 = _run(10)
    for t in first + later:
        t.join(30)
    assert slow_build["n"] == 2, "десять запитів під час збірки — одна збірка після неї"
    assert slow_build["max_running"] == 1, "дві збірки одночасно"
    assert got1 == [{"build": 1, "rescanned": True}]
    # Жоден із пізніх запитів не закрито збіркою, що вже йшла.
    assert len(got2) == 10 and {r["build"] for r in got2} == {2}
    assert sum(1 for r in got2 if r.get("coalesced")) == 9


def test_simultaneous_requests_build_at_most_twice(slow_build: dict[str, Any]) -> None:
    ts, got = _run(4)
    for t in ts:
        t.join(30)
    assert len(got) == 4
    assert 1 <= slow_build["n"] <= 2 and slow_build["max_running"] == 1


def test_a_request_after_the_build_builds_again(slow_build: dict[str, Any]) -> None:
    from nyshporka.cases import db

    slow_build["dur"] = 0.0
    assert db.rebuild()["build"] == 1
    assert db.rebuild()["build"] == 2, "закінчена збірка не закриває новий запит"


def test_narrow_build_is_not_merged(slow_build: dict[str, Any]) -> None:
    from nyshporka.cases import db

    slow_build["dur"] = 0.0
    assert db.rebuild(rescan=False) == {"build": 1, "rescanned": False}
    assert db.rebuild()["build"] == 2, "збірка без диска не закриває повний запит"
