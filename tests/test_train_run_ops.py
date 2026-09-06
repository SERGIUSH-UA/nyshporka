"""Операції трену наскрізь на синтетиці: plan → build → start (план) → status."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.train import sets as S
from nyshporka.train import state as ST


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    reg = S.registry(ws)
    for name, role in (("a", "train"), ("h", "holdout")):
        spec = S.SetSpec(name=name, role=role)
        reg.save(spec)
        for i in range(6):
            p = reg.crops_of(spec) / "0001" / f"line_{i:03d}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.new("L", (240, 32), 220).save(p)
            reg.append_mark(name, "0001", i, f"Іоаннъ Петровъ рядок {i} довгий", "ok")
    yield ws
    W.reset()


def test_plan_build_start_status_round_trip(space: W.Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    env = O.call("train.plan", {"recipe": "own"})
    assert env.ok and {s["id"] for s in env.data["sources"]} == {"gt"}
    assert env.data["holdout"] == ["h"] and "hist" in env.data
    assert not O.call("train.plan", {"recipe": "нема"}).ok

    env = O.call("train.build", {"name": "v1", "recipe": "own"})
    assert env.ok and env.data["rows_train"] > 0 and Path(env.data["tgz"]).is_file()
    assert any(n.op == "train.start" for n in env.next)
    assert not O.call("train.build", {"name": "v1", "recipe": "own"}).ok, "без --force перезбирає"

    # план без запуску: local без середовища рушіїв — план є, старту немає
    env = O.call("train.start", {"corpus": "v1", "compute": "local", "params": "epochs=2"})
    assert env.ok and not env.data["started"] and env.data["params"]["epochs"] == 2
    assert env.data["params"]["min_epochs"] <= 2
    assert env.data["plan"]["kind"] == "local" and env.data["run_id"].startswith("v1__own__")
    codes = {w.code for w in env.warnings}
    assert "confirm" in codes or "not_ready" in codes
    assert not O.call("train.start", {"corpus": "nope"}).ok
    assert not O.call("train.start", {"corpus": "v1", "params": "epochs=x=1"}).ok

    # gpurunner без CLI на шляху — план з відмовою, без старту
    monkeypatch.setattr("shutil.which", lambda name: None)
    env = O.call("train.start", {"corpus": "v1", "compute": "gpurunner", "backend": "vast",
                                 "gpu": "RTX_3090", "yes": True})
    assert env.ok and not env.data["started"] and env.data["plan"]["ok"] is False

    # status без прогонів — відмова з поясненням; з підкладеним станом — пульс
    assert not O.call("train.status", {}).ok
    st = ST.RunState(run_id="v1__own__ffffffff", recipe="own", corpus={"name": "v1"},
                     compute={"kind": "local", "pid": 0})
    st.set_phase("running").save()
    out = st.out_dir()
    out.mkdir(parents=True)
    (out / "ptrain_summary.json").write_text(json.dumps({"history": []}), encoding="utf-8")
    env = O.call("train.status", {})
    assert env.ok and env.data["pulse"]["finished"] and env.data["state"]["phase"] == "fetched"
    env = O.call("train.status", {"all": True})
    assert env.ok and len(env.data["runs"]) == 1
    env = O.call("train.fetch", {"run": "v1__own__ffffffff"})
    assert env.ok and env.data["summary"] is True
    env = O.call("train.stop", {"run": "v1__own__ffffffff"})
    assert env.ok
    assert not O.call("train.eval", {"run": "v1__own__ffffffff"}).ok, "без чекпойнтів — відмова"
    assert not O.call("train.promote", {"run": "v1__own__ffffffff", "as_name": "pysar_cyr_v1.pt",
                                        "why": "x"}).ok
