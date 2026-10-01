"""Від'єднаний захід, що вже скінчився, не заважає новому заходу в ту саму теку.

01.10.2026: повторне читання ДАВіО 474-103 Писарем відмовлялось — «у теку вже
пише інший захід», — хоча захід Скриби скінчився годину тому й машину
погашено. Від'єднаний захід свого запису не оновлює, і той лишався «running».
"""
from __future__ import annotations

import types

import pytest

from nyshporka.cloud import go as G
from nyshporka.cloud import state as ST
from nyshporka.cloud import supervised as SUP

OUT = "E:/prostir/reports/htr/010474-01-00103"


def _plan() -> types.SimpleNamespace:
    return types.SimpleNamespace(out_dir=OUT)


def _st(run_id: str, phase: str = "running", supervisor: str = "htr-x") -> ST.RunState:
    return ST.RunState(run_id=run_id, out_dir=OUT.replace("/", "\\"), phase=phase,
                       supervisor=supervisor)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):
    runs: list[ST.RunState] = []
    supervisor: dict[str, dict] = {}
    asked: list[str] = []
    monkeypatch.setattr(ST, "live", lambda: list(runs))
    monkeypatch.setattr(ST, "load", lambda run_id: None)
    monkeypatch.setattr(G, "_run_ids", lambda plan, frames_dir: {"own__1"})

    def state_of(st):
        asked.append(st.run_id)
        return supervisor.get(st.run_id, {})

    def absorb(st, data):
        st.phase = "done"
        st.verdict = "ok"
        return st

    monkeypatch.setattr(SUP, "state_of", state_of)
    monkeypatch.setattr(SUP, "finished", lambda data: data.get("phase") == "finished")
    monkeypatch.setattr(SUP, "absorb", absorb)
    return runs, supervisor, asked


def test_finished_detached_run_is_settled_not_a_clash(world, tmp_path) -> None:
    runs, supervisor, asked = world
    runs.append(_st("old__skryba"))
    supervisor["old__skryba"] = {"phase": "finished", "verdict": "ok"}
    _, clash = G._find_live(_plan(), tmp_path)
    assert clash is None
    assert asked == ["old__skryba"]
    assert runs[0].phase == "done"


def test_live_detached_run_still_blocks(world, tmp_path) -> None:
    runs, supervisor, _ = world
    runs.append(_st("busy__pysar"))
    supervisor["busy__pysar"] = {"phase": "running"}
    _, clash = G._find_live(_plan(), tmp_path)
    assert clash is not None and clash.run_id == "busy__pysar"


def test_unreachable_supervisor_stays_cautious(world, tmp_path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    runs, _, _ = world
    runs.append(_st("ghost__1"))

    def missing(st):
        raise SUP.SupervisorMissing("наглядача немає")

    monkeypatch.setattr(SUP, "state_of", missing)
    _, clash = G._find_live(_plan(), tmp_path)
    assert clash is not None, "не знаємо — не пускаємо"


def test_other_out_dirs_are_not_asked(world, tmp_path) -> None:
    runs, _, asked = world
    other = _st("other__1")
    other.out_dir = "E:/prostir/reports/htr/spr-1"
    runs.append(other)
    _, clash = G._find_live(_plan(), tmp_path)
    assert clash is None and asked == [], "наглядача питаємо лише про ту саму теку"
