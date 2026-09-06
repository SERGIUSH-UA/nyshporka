"""Стан прогону, оцінка часу, рендер команд локально і для gpurunner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.train import compute as CP
from nyshporka.train import layout as L
from nyshporka.train import sizing as SZ
from nyshporka.train import state as ST
from nyshporka.train.compute import gpurunner as G
from nyshporka.train.compute import local as LC


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    yield ws
    W.reset()


def _job(tmp_path: Path, **kw: object) -> CP.TrainJob:
    tgz = tmp_path / "v1.tgz"
    tgz.write_bytes(b"x")
    params = {"epochs": 12, "batch": 64, "lr": 3e-4, "amp": True, "wall_limit_h": 11.0,
              "modal_volume": "", "dataset": ""}
    params.update(kw.pop("params", {}))
    return CP.TrainJob(run_id="v1__own__abcd1234", corpus_name="v1", corpus_tgz=tgz,
                       params=params, rows_train=100_000, **kw)


def test_run_id_is_deterministic_and_state_round_trips(space: W.Workspace) -> None:
    a = L.run_id_for("v1", "own", {"epochs": 12, "lr": 3e-4})
    b = L.run_id_for("v1", "own", {"lr": 3e-4, "epochs": 12})
    assert a == b and a.startswith("v1__own__")
    assert L.run_id_for("v1", "own", {"epochs": 13}) != a
    st = ST.RunState(run_id=a, recipe="own", corpus={"name": "v1"})
    st.set_phase("running").incident("тест").save()
    got = ST.load(a)
    assert got.phase == "running" and got.incidents and got.started
    assert [r.run_id for r in ST.list_runs()] == [a]
    with pytest.raises(ST.StateError):
        st.set_phase("weird")
    with pytest.raises(ST.StateError):
        ST.load("nope")


def test_sizing_uses_measured_points_and_own_calibration() -> None:
    est = SZ.predict(100_000, 12, "Tesla T4")
    assert est.gpu == "T4" and est.measured and 6.5 < est.hours < 8.0
    est = SZ.predict(100_000, 12, "NVIDIA A100-SXM4-40GB")
    assert est.gpu == "A100" and 2.3 < est.hours < 2.8
    est = SZ.predict(100_000, 12, "GeForce RTX 3090")
    assert est.gpu == "3090" and not est.measured and est.notes
    est = SZ.predict(100_000, 12, "Radeon", calib={"T4": {"rows_per_sec": 200.0}})
    assert est.measured and abs(est.min_per_epoch - 100_000 / 200 / 60) < 0.01
    fits, ep = SZ.fits_wall(SZ.predict(100_000, 40, "T4"), 11.0)
    assert not fits and 0 < ep < 40
    cal = SZ.calibration_from_summary(
        {"history": [{"rows_per_sec": 97.0, "gpu_peak_gib": 9.1}, {"rows_per_sec": 99.0}],
         "n_train": 101169, "world_size": 2}, "Tesla T4")
    assert cal and cal["rows_per_sec"] == 98.0 and cal["gpu_peak_gib"] == 9.1
    assert SZ.calibration_from_summary({"history": []}, "T4") is None


def test_local_params_and_command(space: W.Workspace, tmp_path: Path) -> None:
    job = _job(tmp_path)
    st = ST.RunState(run_id=job.run_id)
    p = LC.render_params(job, st)
    assert p["no_pip"] is True and p["progress_json"] is True
    assert p["input_root"] == str(st.input_dir()) and p["output_root"] == str(st.out_dir())
    cmd = LC.command(Path("py.exe"), st.params_path())
    assert cmd[0] == "py.exe" and cmd[1].endswith("parseq_train_runner.py") and "--params" in cmd


def test_local_poll_reads_disk_not_memory(space: W.Workspace) -> None:
    st = ST.RunState(run_id="r1", epochs=3, compute={"kind": "local", "pid": 0})
    out = st.out_dir()
    out.mkdir(parents=True)
    (out / LC.STDOUT_LOG).write_text(
        'ep1 …\n@@PROGRESS@@ {"v": 1, "phase": "train", "i": 1, "n": 3}\n'
        '@@PROGRESS@@ {"v": 1, "phase": "train", "i": 2, "n": 3, "val_cer": 0.2}\n',
        encoding="utf-8")
    (out / "parseq_ep01.pt").write_bytes(b"")
    (out / "parseq_ep02.pt").write_bytes(b"")
    pulse = LC.LocalTrainer().poll(st)
    assert pulse.epoch == 2 and pulse.epochs == 3 and pulse.ckpts == 2 and not pulse.finished
    (out / "ptrain_summary.json").write_text("{}", encoding="utf-8")
    pulse = LC.LocalTrainer().poll(st)
    assert pulse.finished and pulse.rc == 0 and not pulse.alive


def test_gpurunner_command_per_backend(space: W.Workspace, tmp_path: Path) -> None:
    job = _job(tmp_path, backend="vast", gpu="RTX_3090")
    st = ST.RunState(run_id=job.run_id)
    cmd, notes = G.command(job, st, dry_run=True)
    assert cmd[:5] == ["gpurunner", "run", "parseq_train", "-b", "vast"]
    assert "--gpu" in cmd and "--dry-run" in cmd
    assert "-p" in cmd and "dataset=v1" in cmd and any(a.startswith("input_root=") for a in cmd)
    assert "amp=true" in cmd and "epochs=12" in cmd
    assert not any(a.startswith(("no_pip", "progress_json", "output_root")) for a in cmd)
    assert (st.dir() / "inputs" / "v1" / "v1.tgz").is_file()
    job = _job(tmp_path, backend="modal", params={"modal_volume": "my-htr"})
    cmd, notes = G.command(job, st)
    assert "dataset=datasets/v1.tgz" in cmd and "modal_volume=my-htr" in cmd
    assert notes and "modal volume put" in notes[0]
    with pytest.raises(CP.ComputeError, match="modal_volume"):
        G.command(_job(tmp_path, backend="modal"), st)
    with pytest.raises(CP.ComputeError, match="owner/slug"):
        G.command(_job(tmp_path, backend="kaggle"), st)
    with pytest.raises(CP.ComputeError, match="невідомий"):
        G.command(_job(tmp_path, backend="cloud9"), st)
    assert G.parse_handle("ok\nsubmitted a1b2c3d4\n") == "a1b2c3d4"
    assert G.parse_handle("nothing") == ""


def test_select_by_flags_and_detect(space: W.Workspace) -> None:
    assert CP.select("auto").kind == "local"
    assert CP.select("auto", backend="modal").kind == "gpurunner"
    with pytest.raises(CP.ComputeError):
        CP.select("mars")
    d = CP.detect()
    assert set(d) == {"local", "ssh", "gpurunner"}
    assert all("ok" in v and "why" in v for v in d.values())


def test_gpurunner_plan_names_the_cost_and_the_vast_trap(space: W.Workspace, tmp_path: Path) -> None:
    job = _job(tmp_path, backend="vast", gpu="RTX_3090")
    plan = G.GpurunnerTrainer().plan(job)
    assert plan.hours > 0 and plan.usd > 0 and plan.gpu == "RTX_3090"
    assert any("cancel" in w for w in plan.warnings)
    assert json.dumps(plan.as_dict(), ensure_ascii=False)
