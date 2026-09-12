"""🖧 Трен на своїй машині по SSH — тим самим `nyshporka.cloud`, що читає справи.

Бекенд `ssh` уже вміє взяти машину з `nysh cloud hosts`, під'єднатись,
покласти файл, запустити відчеплений процес і забрати результат; середовище
рушіїв на ній збирає `nysh cloud prepare` (torch і strhub там ті самі). Тут
лишається трен-специфічне: корпус і раннер-гість на машину, `params.json` з
віддаленими коренями, `go.sh`, пульс із диска машини й архів ваг назад.

🔴 Порядок `fetch → stop` той самий, що в читанні: гасити нічого (машина
своя), але ваги епох живуть на ній, доки їх не привезли.
"""
from __future__ import annotations

import json
import shlex
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from nyshporka.core.progress import parse as parse_progress
from nyshporka.train import sizing
from nyshporka.train.compute import (
    ComputeError,
    ComputePlan,
    Pulse,
    TrainJob,
    base_file,
    with_local_base,
)
from nyshporka.train.state import RunState, load_calib

GUEST = Path(__file__).resolve().parents[1] / "guest" / "parseq_train_runner.py"
SUB = "train"
DONE_FLAG = "_done"
RC_FILE = "_rc"
CMD_TIMEOUT = 900.0


def _backend() -> Any:
    from nyshporka.cloud.registry import load as load_registry

    reg = load_registry()
    got = reg.get("ssh")
    if got is None:
        raise ComputeError("бекенда ssh немає — extra `cloud` не встановлений "
                           "(pip install 'nyshporka[cloud]')")
    return got


def _remote_dir(box: Any, run_id: str) -> str:
    raw = box.meta.get("host") if isinstance(box.meta, dict) else None
    workdir = "~/nysh-run"
    if isinstance(raw, dict) and raw.get("workdir"):
        workdir = str(raw["workdir"])
    return f"{workdir.rstrip('/')}/{SUB}/{run_id}"


def go_script(remote_dir: str, python: str) -> str:
    d = shlex.quote(remote_dir)
    return "\n".join([
        "#!/bin/sh",
        f"cd {d} || exit 97",
        f"rm -f {DONE_FLAG} {RC_FILE}",
        "mkdir -p logs out",
        f"{shlex.quote(python)} parseq_train_runner.py --params params.json "
        f"> logs/train.log 2>&1",
        "rc=$?",
        f"echo $rc > {RC_FILE}",
        f"touch {DONE_FLAG}",
        "exit $rc",
    ]) + "\n"


def remote_params(job: TrainJob, remote_dir: str) -> dict[str, Any]:
    p = with_local_base(job.params)
    p.update({"dataset": job.corpus_name, "input_root": f"{remote_dir}/input",
              "output_root": f"{remote_dir}/out", "no_pip": True, "progress_json": True})
    return p


def engine_ready(session: Any, remote_dir: str) -> tuple[bool, str, str]:
    """(готово, python, деталь): середовище рушіїв машини зі strhub."""
    py = f"{PurePosixPath(session.resolve(remote_dir)).parent.parent.parent}/.venv/bin/python"
    code = "import torch, strhub, PIL, numpy; print('OK', torch.__version__, torch.cuda.is_available())"
    got = session.run(f"{shlex.quote(py)} -c {shlex.quote(code)} 2>&1 || true", timeout=300.0)
    ok = "OK" in got.out
    return ok, py, got.out.strip()[:300]


def _put_text(session: Any, remote: str, text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / PurePosixPath(remote).name
        p.write_text(text, encoding="utf-8", newline="\n")
        session.put(p, remote)


class SshTrainer:
    kind = "ssh"

    def __init__(self, backend: Any = None) -> None:
        self._backend = backend

    def backend(self) -> Any:
        if self._backend is None:
            self._backend = _backend()
        return self._backend

    def available(self) -> tuple[bool, str]:
        try:
            import paramiko  # noqa: F401
        except ImportError:
            return False, "paramiko не встановлений — pip install 'nyshporka[cloud]'"
        try:
            from nyshporka.cloud import ssh as C

            hosts = [h.name for h in C.load_hosts()]
        except Exception as exc:
            return False, f"хости не читаються: {exc}"
        if not hosts:
            return False, "жодної машини не записано — nysh cloud hosts add <ім'я> <user@host>"
        return True, ", ".join(hosts)

    def plan(self, job: TrainJob) -> ComputePlan:
        ok, why = self.available()
        plan = ComputePlan(kind=self.kind, command=["sh", "go.sh"], ok=ok)
        if not ok:
            plan.warnings.append(why)
            return plan
        if not job.host:
            plan.ok = False
            plan.warnings.append("для ssh вкажіть --host <ім'я з nysh cloud hosts>")
            return plan
        from nyshporka.cloud import ssh as C

        host = C.find_host(job.host)
        if host is None:
            plan.ok = False
            plan.warnings.append(f"машини «{job.host}» немає серед записаних: {why}")
            return plan
        gpu = f"gpus={host.gpus} vram={host.vram_gb}" if getattr(host, "gpus", 0) else ""
        plan.gpu = gpu
        est = sizing.predict(job.rows_train, int(job.params.get("epochs", 1)), job.gpu or "T4",
                             calib=load_calib(), usd_per_hour=0.0)
        plan.hours = est.hours
        plan.notes += est.notes
        plan.notes.append(f"машина {host.target}; середовище рушіїв перевіриться при старті "
                          f"(зібрати: nysh cloud prepare {host.name})")
        return plan

    def start(self, job: TrainJob, st: RunState) -> RunState:
        from nyshporka.cloud.base import Need

        if not job.corpus_tgz.is_file():
            raise ComputeError(f"корпусу немає: {job.corpus_tgz}")
        backend = self.backend()
        box = backend.acquire(Need(pages=0, bytes_in=job.corpus_tgz.stat().st_size),
                              target=job.host)
        session = backend.connect(box)
        try:
            remote_dir = session.resolve(_remote_dir(box, st.run_id))
            ready, py, detail = engine_ready(session, remote_dir)
            if not ready:
                raise ComputeError(f"на машині немає середовища рушіїв зі strhub ({detail}). "
                                   f"Зібрати один раз: nysh cloud prepare {job.host}")
            session.mkdirs(f"{remote_dir}/input")
            session.mkdirs(f"{remote_dir}/out")
            session.mkdirs(f"{remote_dir}/logs")
            session.put(job.corpus_tgz, f"{remote_dir}/input/{job.corpus_tgz.name}")
            base = base_file(job.params)
            if base is not None:
                session.mkdirs(f"{remote_dir}/input/base")
                session.put(base, f"{remote_dir}/input/base/{base.name}")
            session.put(GUEST, f"{remote_dir}/parseq_train_runner.py")
            params = remote_params(job, remote_dir)
            _put_text(session, f"{remote_dir}/params.json",
                      json.dumps(params, ensure_ascii=False, indent=1))
            _put_text(session, f"{remote_dir}/go.sh", go_script(remote_dir, py))
            pid = session.spawn(f"sh {shlex.quote(remote_dir + '/go.sh')}",
                                log=f"{remote_dir}/logs/go.log", pidfile=f"{remote_dir}/_pid")
        finally:
            session.close()
        st.compute = {"kind": self.kind, "host": job.host, "box": box.as_dict(),
                      "remote_dir": remote_dir, "pid": pid, "python": py}
        st.epochs = int(job.params.get("epochs") or 0)
        st.set_phase("running")
        st.save()
        return st

    def _session(self, st: RunState) -> tuple[Any, Any]:
        from nyshporka.cloud.base import Box

        if not st.compute.get("box"):
            raise ComputeError("у стані прогону немає машини")
        backend = self.backend()
        box = Box.from_dict(st.compute["box"])
        return backend, backend.connect(box)

    def poll(self, st: RunState) -> Pulse:
        pulse = Pulse(epochs=st.epochs)
        _, session = self._session(st)
        try:
            d = shlex.quote(str(st.compute.get("remote_dir") or ""))
            got = session.run(
                f"echo ckpts=$(ls {d}/out/parseq_ep*.pt 2>/dev/null | wc -l); "
                f"echo done=$(test -f {d}/{DONE_FLAG} && echo 1 || echo 0); "
                f"echo rc=$(cat {d}/{RC_FILE} 2>/dev/null || echo -); "
                f"echo summary=$(test -f {d}/out/ptrain_summary.json && echo 1 || echo 0); "
                f"grep '@@PROGRESS@@' {d}/logs/train.log 2>/dev/null | tail -1",
                timeout=CMD_TIMEOUT)
            kv: dict[str, str] = {}
            for line in got.out.splitlines():
                if line.startswith("@@PROGRESS@@"):
                    ev = parse_progress(line.strip())
                    if ev is not None:
                        pulse.epoch, pulse.epochs = ev.i, ev.n or pulse.epochs
                    continue
                key, sep, val = line.strip().partition("=")
                if sep:
                    kv[key] = val.strip()
            pulse.ckpts = int(kv["ckpts"]) if kv.get("ckpts", "").isdigit() else 0
            pulse.finished = kv.get("done") == "1" and kv.get("summary") == "1"
            rc = kv.get("rc", "-")
            pulse.rc = int(rc) if rc.lstrip("-").isdigit() else None
            pid = int(st.compute.get("pid") or 0)
            pulse.alive = bool(session.alive(pid)) if pid else False
            if kv.get("done") == "1" and kv.get("summary") != "1":
                pulse.note = "процес завершився без ptrain_summary.json — дивитись logs/train.log"
        finally:
            session.close()
        return pulse

    def fetch(self, st: RunState) -> Path:
        from nyshporka.core.workspace import workspace

        out_dir = st.out_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        _, session = self._session(st)
        try:
            d = str(st.compute.get("remote_dir") or "")
            session.run(f"cd {shlex.quote(d)} && rm -f result.tar && tar -cf result.tar out logs "
                        f"2>/dev/null || tar -cf result.tar out 2>/dev/null || true",
                        timeout=CMD_TIMEOUT)
            remote_tar = f"{d}/result.tar"
            if not session.exists(remote_tar):
                raise ComputeError("на машині нема чого забирати — тека out порожня")
            local_tar = workspace().derived / "train" / "tmp" / f"{st.run_id}.result.tar"
            local_tar.parent.mkdir(parents=True, exist_ok=True)
            session.get(remote_tar, local_tar)
        finally:
            session.close()
        # 🔴 Імена в архіві — з чужої машини. Той самий гард, що в читанні
        # справи (`cloud.run.unpack`): покомпонентно, бо на Windows `\` і `C:`
        # живуть УСЕРЕДИНІ одного POSIX-компонента, і ще раз на готовому шляху.
        from nyshporka.cloud.run import _safe_member_part, _under

        try:
            with tarfile.open(local_tar, "r") as tar:
                for m in tar.getmembers():
                    if not m.isfile():
                        continue
                    parts = PurePosixPath(m.name).parts
                    if not parts or parts[0] not in ("out", "logs"):
                        continue
                    if len(parts) < 2 or not all(_safe_member_part(p) for p in parts[1:]):
                        continue
                    rel = Path(*parts[1:]) if parts[0] == "out" else Path("logs", *parts[1:])
                    dst = out_dir / rel
                    if not _under(dst, out_dir):
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(m)
                    if src is not None:
                        dst.write_bytes(src.read())
        finally:
            local_tar.unlink(missing_ok=True)
        return out_dir

    def stop(self, st: RunState) -> None:
        pid = int(st.compute.get("pid") or 0)
        try:
            backend, session = self._session(st)
        except ComputeError:
            return
        try:
            if pid:
                session.kill(pid)
        finally:
            session.close()
        from nyshporka.cloud.base import Box

        backend.release(Box.from_dict(st.compute["box"]), why="трен зупинено")
