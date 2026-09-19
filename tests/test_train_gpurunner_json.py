"""Стик із gpurunner: машинний вивід, а текст — лише відкат для старих версій.

Підстава. Адаптер читав людський вивід сусіднього інструмента: регекс на
`submitted <id>` і пошук слів `running`/`failed` у панелі статусу. Такий стик
не падає в жодному CI — він падає в людини, коли карту вже орендовано, а
handle не розібрався. gpurunner 0.2 відповідає одним JSON-об'єктом останнім
рядком stdout (`docs/contract.md` у його репозиторії).
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import workspace as W
from nyshporka.train.compute import TrainJob
from nyshporka.train.compute import gpurunner as G
from nyshporka.train.state import RunState


@pytest.fixture
def space(tmp_path: Path) -> Iterator[W.Workspace]:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    yield ws
    W.reset()


def _fake_cli(monkeypatch: pytest.MonkeyPatch, version: str,
              replies: dict[str, str]) -> list[list[str]]:
    """Підмінити виклики gpurunner: `--version` і відповіді за підкомандою."""
    calls: list[list[str]] = []
    G._speaks_json.clear()
    monkeypatch.setattr(G, "which", lambda: "gpurunner")

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, f"gpurunner {version}\n", "")
        return subprocess.CompletedProcess(cmd, 0, replies.get(cmd[1], ""), "")

    monkeypatch.setattr(G.subprocess, "run", run)
    return calls


def _job(tmp_path: Path) -> TrainJob:
    tgz = tmp_path / "corpus.tgz"
    tgz.write_bytes(b"x")
    return TrainJob(run_id="r1", corpus_tgz=tgz, corpus_name="corpus", backend="vast",
                    gpu="RTX_4090", params={"epochs": 3}, rows_train=1000)


def test_the_last_json_line_wins_over_sdk_noise() -> None:
    noisy = 'uploading 10%\n{"progress": 1}\nготово\n{"schema": 1, "short": "abcd1234"}\n'
    assert G.last_json(noisy) == {"schema": 1, "short": "abcd1234"}
    assert G.last_json("жодного об'єкта") == {}
    assert G.last_json("{обірваний") == {}


def test_a_new_gpurunner_is_asked_for_json(space: W.Workspace, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_cli(monkeypatch, "0.2.0", {
        "run": 'прогрес SDK\n{"schema": 1, "ok": true, "short": "abcd1234", "handle": "abcd1234ffff"}\n',
        "status": '{"schema": 1, "ok": true, "state": "running", "refreshed": true, "message": "ep 2"}\n',
    })
    st = G.GpurunnerTrainer().start(_job(tmp_path), RunState(run_id="r1"))
    assert st.compute["handle"] == "abcd1234"
    assert calls[1][-1] == "--json"

    pulse = G.GpurunnerTrainer().poll(st)
    assert pulse.alive and not pulse.finished and "ep 2" in pulse.note
    assert calls[-1] == ["gpurunner", "status", "abcd1234", "--json"]


def test_an_old_gpurunner_still_works_through_the_text(space: W.Workspace, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """0.1 не знає `--json`: прапорець дав би «No such option» і зірваний старт."""
    calls = _fake_cli(monkeypatch, "0.1.0", {"run": "✓ submitted  abcd1234  →  remote\n",
                                             "status": "status    completed\n"})
    st = G.GpurunnerTrainer().start(_job(tmp_path), RunState(run_id="r1"))
    assert st.compute["handle"] == "abcd1234"
    assert "--json" not in calls[1]
    assert G.GpurunnerTrainer().poll(st).finished


@pytest.mark.parametrize(("state", "finished", "alive", "rc"), [
    ("queued", False, True, None), ("running", False, True, None),
    ("completed", True, False, 0), ("failed", False, False, 1),
    ("cancelled", False, False, 1), ("unknown", False, False, None),
])
def test_every_contract_state_maps_to_a_pulse(space: W.Workspace, state: str, finished: bool,
                                              alive: bool, rc: int | None) -> None:
    from nyshporka.train.compute import Pulse

    pulse = G._pulse_from_reply(Pulse(epochs=1), {"state": state}, RunState(run_id="r1"))
    assert (pulse.finished, pulse.alive) == (finished, alive)
    assert getattr(pulse, "rc", None) == rc


def test_a_stale_state_is_named_as_stale(space: W.Workspace) -> None:
    from nyshporka.train.compute import Pulse

    pulse = G._pulse_from_reply(Pulse(epochs=1), {"state": "running", "refreshed": False},
                                RunState(run_id="r1"))
    assert pulse.alive and "маніфесту" in pulse.note
