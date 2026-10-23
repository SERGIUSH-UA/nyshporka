"""▶ «Зараз читається»: одне читання — один рядок, і гаситься лише свій процес."""
from __future__ import annotations

import time
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.htr import runs as LIVE


def _live(pid: int, case: str, shard: str = "") -> LIVE.Live:
    now = time.time()
    return LIVE.Live(pid=pid, created=now - 600, case=case, case_key="TEST/1/1/1",
                     shard=shard, since=now - 300)


@pytest.fixture
def two_shards(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from nyshporka import htr_store as S

    rows = [_live(4101, "spr-1", "1/2"), _live(4102, "spr-1", "2/2")]
    monkeypatch.setattr(LIVE, "alive", lambda: list(rows))
    monkeypatch.setattr(S, "list_cases", lambda: [
        {"name": "spr-1", "case_dir": "D:/скани/spr-1", "case_key": "TEST/1/1/1",
         "shifra": "ТЕСТ 1-1-1", "title": "Сповідка", "model": "m", "pages_done": 6,
         "frames": 27, "done": False, "updated": "2026-10-23T21:20:00"},
        {"name": "spr-1-old", "case_dir": "D:/скани/spr-1", "pages_done": 27, "frames": 27,
         "done": True, "updated": "2026-10-20T10:00:00"}])
    return [4101, 4102]


def test_shards_of_one_case_are_one_row_with_progress(two_shards: list[int]) -> None:
    env = O.call("reading.now", {})
    assert env.ok, env.error
    items = env.data["items"]
    local = [i for i in items if i["where"] == "local"]
    assert len(local) == 1
    it = local[0]
    assert (it["shifra"], it["done"], it["total"], it["shards"]) == ("ТЕСТ 1-1-1", 6, 27, 2)
    assert it["run"] == "spr-1", "недочитаний прогін, а не старий дочитаний"
    assert it["via"] in ("terminal", "console", "queue")


def test_stop_kills_only_processes_that_are_still_ours(two_shards: list[int],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.core import lock
    from nyshporka.htr import session

    killed: list[int] = []
    dropped: list[int] = []
    # Другий PID ОС уже віддала іншій програмі — час старту не той.
    monkeypatch.setattr(lock, "process_alive", lambda pid, created: pid == 4101)
    monkeypatch.setattr(session, "kill_tree", lambda pid, *a, **k: killed.append(pid) or [])
    monkeypatch.setattr(LIVE, "drop", lambda pid: dropped.append(pid))
    env = O.call("read.stop", {"case": "spr-1"})
    assert env.ok, env.error
    assert killed == [4101] and dropped == [4101] and env.data["stopped"] == [4101]


def test_stop_of_a_case_that_is_not_reading_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LIVE, "alive", lambda: [])
    env = O.call("read.stop", {"case": "spr-9"})
    assert not env.ok and "не читається" in env.error


def test_cloud_runs_join_the_same_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.cloud import state as CST

    class Run:
        run_id = "r1"
        case_dir = "T:/кадри/spr-2"
        case_key = "TEST/1/1/2"
        pages_done = 40
        frames_total = 120

        def human_phase(self) -> str:
            return "читає"

    monkeypatch.setattr(LIVE, "alive", lambda: [])
    monkeypatch.setattr(CST, "all_runs", lambda: [Run()])
    monkeypatch.setattr(CST, "is_live", lambda s: True)
    items: list[dict[str, Any]] = O.call("reading.now", {}).data["items"]
    assert [(i["where"], i["run"], i["done"], i["total"]) for i in items] == [("cloud", "r1", 40, 120)]
