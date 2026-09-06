"""SSH-бекенд трену на підставній машині: старт, пульс, забір, зупинка."""
from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from nyshporka.cloud.base import Box, Need
from nyshporka.core import workspace as W
from nyshporka.train import compute as CP
from nyshporka.train import state as ST
from nyshporka.train.compute import ssh as SS


@dataclass
class Got:
    rc: int = 0
    out: str = ""
    err: str = ""


@dataclass
class FakeSession:
    files: dict[str, bytes] = field(default_factory=dict)
    cmds: list[str] = field(default_factory=list)
    ready: bool = True
    progress: str = ""
    done: bool = False
    pid_alive: bool = True
    closed: int = 0

    def resolve(self, remote: str) -> str:
        return remote.replace("~", "/srv/nysh")

    def run(self, cmd: str, *, timeout: float | None = None, on_line: Any = None) -> Got:
        self.cmds.append(cmd)
        if "import torch, strhub" in cmd:
            return Got(out="OK 2.4 True" if self.ready else "ModuleNotFoundError: strhub")
        if "echo ckpts=" in cmd:
            return Got(out=f"ckpts=2\ndone={'1' if self.done else '0'}\nrc={'0' if self.done else '-'}\n"
                           f"summary={'1' if self.done else '0'}\n{self.progress}\n")
        if "tar -cf result.tar" in cmd:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tf:
                for name, blob in (("out/parseq_ep01.pt", b"ep1"), ("out/ptrain_summary.json", b"{}"),
                                   ("logs/train.log", b"log")):
                    ti = tarfile.TarInfo(name)
                    ti.size = len(blob)
                    tf.addfile(ti, io.BytesIO(blob))
            self.files["/srv/nysh/nysh-run/train/r1/result.tar"] = buf.getvalue()
        return Got()

    def spawn(self, cmd: str, *, log: str, pidfile: str) -> int:
        self.cmds.append(cmd)
        return 4242

    def alive(self, pid: int) -> bool:
        return self.pid_alive

    def kill(self, pid: int) -> None:
        self.pid_alive = False

    def put(self, local: Path, remote: str) -> int:
        self.files[remote] = local.read_bytes()
        return len(self.files[remote])

    def get(self, remote: str, local: Path) -> int:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.files[remote])
        return len(self.files[remote])

    def exists(self, remote: str) -> bool:
        return remote in self.files

    def mkdirs(self, remote: str) -> None:
        self.cmds.append(f"mkdir {remote}")

    def close(self) -> None:
        self.closed += 1


@dataclass
class FakeBackend:
    session: FakeSession
    released: list[str] = field(default_factory=list)
    id: str = "ssh"

    def acquire(self, need: Need, *, target: str = "") -> Box:
        assert need.bytes_in > 0
        return Box(id=target, backend="ssh", label=f"u@{target}",
                   meta={"host": {"name": target, "host": target, "user": "u",
                                  "workdir": "~/nysh-run"}})

    def connect(self, box: Box) -> FakeSession:
        return self.session

    def release(self, box: Box, *, why: str = "") -> None:
        self.released.append(why)


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    yield ws
    W.reset()


def _job(tmp_path: Path) -> CP.TrainJob:
    tgz = tmp_path / "v1.tgz"
    tgz.write_bytes(b"corpus")
    return CP.TrainJob(run_id="r1", corpus_name="v1", corpus_tgz=tgz,
                       params={"epochs": 3, "batch": 16}, rows_train=500, host="box1")


def test_ssh_start_puts_corpus_runner_params_and_spawns(space: W.Workspace, tmp_path: Path) -> None:
    sess = FakeSession()
    tr = SS.SshTrainer(backend=FakeBackend(sess))
    st = ST.RunState(run_id="r1")
    tr.start(_job(tmp_path), st)
    assert st.phase == "running" and st.compute["pid"] == 4242
    rd = st.compute["remote_dir"]
    assert rd == "/srv/nysh/nysh-run/train/r1"
    assert f"{rd}/input/v1.tgz" in sess.files and f"{rd}/parseq_train_runner.py" in sess.files
    params = sess.files[f"{rd}/params.json"].decode("utf-8")
    assert f'"input_root": "{rd}/input"' in params and '"no_pip": true' in params
    go = sess.files[f"{rd}/go.sh"].decode("utf-8")
    assert "parseq_train_runner.py --params params.json" in go and "_done" in go
    assert sess.closed == 1


def test_ssh_refuses_without_strhub(space: W.Workspace, tmp_path: Path) -> None:
    sess = FakeSession(ready=False)
    tr = SS.SshTrainer(backend=FakeBackend(sess))
    with pytest.raises(CP.ComputeError, match="nysh cloud prepare"):
        tr.start(_job(tmp_path), ST.RunState(run_id="r1"))


def test_ssh_poll_fetch_stop(space: W.Workspace, tmp_path: Path) -> None:
    sess = FakeSession(progress='@@PROGRESS@@ {"v": 1, "phase": "train", "i": 2, "n": 3}')
    be = FakeBackend(sess)
    tr = SS.SshTrainer(backend=be)
    st = ST.RunState(run_id="r1")
    tr.start(_job(tmp_path), st)
    pulse = tr.poll(st)
    assert pulse.alive and not pulse.finished and pulse.epoch == 2 and pulse.ckpts == 2
    sess.done = True
    pulse = tr.poll(st)
    assert pulse.finished and pulse.rc == 0
    out = tr.fetch(st)
    assert (out / "parseq_ep01.pt").read_bytes() == b"ep1"
    assert (out / "ptrain_summary.json").is_file() and (out / "logs" / "train.log").is_file()
    tr.stop(st)
    assert not sess.pid_alive and be.released == ["трен зупинено"]


def test_ssh_plan_needs_a_host(space: W.Workspace, tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.host = ""
    plan = SS.SshTrainer(backend=FakeBackend(FakeSession())).plan(job)
    assert not plan.ok
