"""☁️ Хмара як операції консолі — без мережі, без наглядача і без грошей.

🔴 `GO.go` тут ніде не викликається по-справжньому: навіть сухий прогін
відчепленого шляху ходить до наглядача. Операцію перевіряємо шпигуном на місці
`GO.go` — що вона йому передає, — а сам захід покривають `test_cloud_go` і
`test_cloud_supervised`. Головне: без `run=true` оренди не буває.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from test_cloud_go import space  # noqa: F401  (фікстура простору)

from nyshporka import ops as O
from nyshporka.cloud import control as CTL
from nyshporka.cloud import go as GO
from nyshporka.cloud import state as ST


def _spy_go(monkeypatch: pytest.MonkeyPatch, **res: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(case: Any, **kw: Any) -> GO.GoResult:
        calls.append({"case": case, **kw})
        return GO.GoResult(**{"verdict": "dry_run", **res})

    monkeypatch.setattr(GO, "go", fake)
    return calls


def _run(run_id: str, **kw: Any) -> ST.RunState:
    st = ST.RunState(run_id=run_id, case_dir="/x/sprava", backend="fake", **kw)
    ST.save(st)
    return st


def test_go_without_run_is_only_a_dry_run(space: Path, monkeypatch) -> None:  # noqa: F811
    calls = _spy_go(monkeypatch, launch="needs_confirm", fork_low=0.4, fork_high=1.1)
    env = O.call("cloud.go", {"case": ["TEST/1/1/1"]})
    assert env.ok and env.data["verdict"] == "dry_run"
    assert calls[0]["dry_run"] is True and calls[0]["confirm"] is False
    assert env.data["launch"] == "needs_confirm"
    assert "confirm=true" in env.next[0].why


def test_go_with_run_rents_and_passes_the_human_permission(space: Path,  # noqa: F811
                                                           monkeypatch) -> None:
    calls = _spy_go(monkeypatch, verdict="detached")
    env = O.call("cloud.go", {"case": ["TEST/1/1/1"], "run": True, "confirm": True,
                              "budget": 2.5})
    assert env.ok
    assert (calls[0]["dry_run"], calls[0]["confirm"], calls[0]["budget"]) == (False, True, 2.5)


def test_go_refusal_is_a_failed_envelope_with_the_result(space: Path,  # noqa: F811
                                                         monkeypatch) -> None:
    _spy_go(monkeypatch, verdict="no_credit", why="бракує балансу")
    env = O.call("cloud.go", {"case": ["TEST/1/1/1"], "run": True})
    assert not env.ok and "бракує балансу" in env.error
    assert env.data["verdict"] == "no_credit"


def test_state_lists_live_first_and_counts_money(space: Path) -> None:  # noqa: F811
    now = time.time()
    _run("old", phase="done", released=True)
    live = _run("burning", phase="running", bills=True,
                box={"price_usd_h": 0.5})
    live.rent_started = now - 3600
    ST.save(live)
    env = O.call("cloud.state", {"limit": 1})
    ids = [r["run_id"] for r in env.data["runs"]]
    assert ids == ["burning"], "живий — завжди, навіть понад межу"
    row = env.data["runs"][0]
    assert row["phase_human"] == "читає" and row["needs_release"]
    assert row["spent_usd"] == pytest.approx(0.5, abs=0.01)
    assert env.data["live"] == 1 and env.data["total"] == 2
    assert any(w.code == "needs_release" for w in env.warnings)
    one = O.call("cloud.state", {"run_id": "old"}).data
    assert one["runs"][0]["run_id"] == "old" and one["live"] == 0
    assert not O.call("cloud.state", {"run_id": "нема"}).ok


def test_stop_and_fetch_name_the_run_or_refuse(space: Path, monkeypatch) -> None:  # noqa: F811
    assert "жодного заходу" in O.call("cloud.stop", {}).error
    _run("a", phase="running")
    _run("b", phase="running")
    assert "кілька" in O.call("cloud.stop", {}).error, "не «візьму перший»"
    stopped: list[tuple[str, bool]] = []
    monkeypatch.setattr(CTL, "stop", lambda st, force=False, on_line=None:
                        stopped.append((st.run_id, force)) or CTL.Stopped(ok=True, detached=False))
    env = O.call("cloud.stop", {"run_id": "b", "force": True})
    assert env.ok and stopped == [("b", True)]


def test_fetch_of_a_detached_run_is_refused(space: Path) -> None:  # noqa: F811
    _run("d", phase="running", supervisor="sess-1")
    env = O.call("cloud.fetch", {"run_id": "d"})
    assert not env.ok and "наглядач sess-1" in env.error


def test_stop_reports_a_killed_supervisor_as_a_live_machine(space: Path,  # noqa: F811
                                                            monkeypatch) -> None:
    _run("k", phase="running", supervisor="sess-2")
    monkeypatch.setattr(CTL, "stop", lambda st, force=False, on_line=None: CTL.Stopped(
        ok=True, detached=True, killed=True, machine="42"))
    env = O.call("cloud.stop", {"run_id": "k", "force": True})
    assert env.ok and any(w.code == "machine_alive" and "42" in w.text
                          for w in env.warnings)
