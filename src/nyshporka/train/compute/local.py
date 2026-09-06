"""🖥 Трен на своїй карті: середовище рушіїв + раннер-гість, процес відчеплено.

Той самий інтерпретатор, що читає справи (`nysh htr install` кладе туди torch
і strhub), той самий вендорений раннер, що поїхав би на сервер. Процес
відчіплюється від сесії: трен на ніч не повинен помирати разом із терміналом,
а стан його читається з диска (`ptrain.log`, `parseq_ep*.pt`,
`ptrain_summary.json`), а не з пам'яті того, хто запустив.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from nyshporka.core.progress import parse as parse_progress
from nyshporka.core.workspace import WorkspaceError
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
STDOUT_LOG = "ptrain.stdout.log"


def engine_python() -> Path | None:
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    try:
        venv = doc.engine_venv()
    except WorkspaceError:
        return None
    py = E.venv_python(venv)
    return py if py.exists() else None


def gpu_memory() -> tuple[str, float, float] | None:
    """(назва, всього ГіБ, вільно ГіБ) з `nvidia-smi`, або None."""
    from nyshporka.htr import gpu as G

    smi = G._smi_path()
    if not smi:
        return None
    row = G._ask(smi, "name,memory.total,memory.free", 15)
    if not row or len(row) < 3:
        return None
    try:
        return row[0], float(row[1]) / 1024.0, float(row[2]) / 1024.0
    except ValueError:
        return None


def render_params(job: TrainJob, st: RunState) -> dict[str, Any]:
    """`params.json` раннера: рецепт + корені + локальні прапорці."""
    p = with_local_base(job.params)
    p.update({"dataset": job.corpus_name, "input_root": str(st.input_dir()),
              "output_root": str(st.out_dir()), "no_pip": True, "progress_json": True})
    if os.name == "nt":
        p["ddp"] = "off"
    return p


def command(python: Path, params_path: Path) -> list[str]:
    return [str(python), str(GUEST), "--params", str(params_path)]


class LocalTrainer:
    kind = "local"

    def available(self) -> tuple[bool, str]:
        py = engine_python()
        if py is None:
            return False, "середовища рушіїв немає — nysh htr install"
        if not GUEST.is_file():
            return False, f"раннера-гостя немає: {GUEST}"
        return True, str(py)

    def plan(self, job: TrainJob) -> ComputePlan:
        ok, why = self.available()
        py = engine_python()
        st = RunState(run_id=job.run_id)
        cmd = command(py or Path("python"), st.params_path())
        plan = ComputePlan(kind=self.kind, command=cmd, ok=ok)
        if not ok:
            plan.warnings.append(why)
        mem = gpu_memory()
        calib = load_calib()
        if mem is None:
            plan.gpu = ""
            plan.warnings.append("карти NVIDIA не видно — трен піде на процесорі; на 100 тис. "
                                 "рядків це дні, а не години")
            est = sizing.predict(job.rows_train, int(job.params.get("epochs", 1)), "cpu",
                                 calib=calib, usd_per_hour=0.0)
            est.hours *= 25.0   # порядок величини: CPU проти T4 (заміряно на смоуках)
            plan.notes.append("оцінка для процесора — ×25 від T4, порядок величини")
        else:
            name, total, free = mem
            plan.gpu = name
            est = sizing.predict(job.rows_train, int(job.params.get("epochs", 1)), name,
                                 calib=calib, usd_per_hour=0.0)
            plan.notes.append(f"карта {name}: {total:.1f} ГіБ, вільно {free:.1f}")
            peak = float((calib.get(sizing.gpu_class(name)) or {}).get("gpu_peak_gib") or 0)
            batch = int(job.params.get("batch", 64))
            if peak and peak > free * 0.9:
                plan.warnings.append(f"минулого разу пік пам'яті був {peak:.1f} ГіБ, вільно "
                                     f"{free:.1f} — зменшити batch (зараз {batch})")
            elif not peak and free < 6 and batch >= 64:
                plan.warnings.append(f"вільно {free:.1f} ГіБ — batch {batch} може не влізти; "
                                     f"для 4 ГіБ карти беруть 16–24")
        plan.hours = est.hours
        plan.usd = 0.0
        plan.notes += est.notes
        fits, ep = sizing.fits_wall(est, float(job.params.get("wall_limit_h", 0)))
        if not fits:
            plan.warnings.append(f"за стелею wall_limit_h раннер зупиниться на епосі ~{ep} "
                                 f"із {est.epochs}")
        return plan

    def start(self, job: TrainJob, st: RunState) -> RunState:
        py = engine_python()
        if py is None:
            raise ComputeError("середовища рушіїв немає — nysh htr install")
        if not job.corpus_tgz.is_file():
            raise ComputeError(f"корпусу немає: {job.corpus_tgz}")
        run_dir = st.dir()
        st.input_dir().mkdir(parents=True, exist_ok=True)
        st.out_dir().mkdir(parents=True, exist_ok=True)
        dst = st.input_dir() / job.corpus_tgz.name
        if not dst.is_file():
            try:
                os.link(job.corpus_tgz, dst)
            except OSError:
                shutil.copy2(job.corpus_tgz, dst)
        base = base_file(job.params)
        if base is not None:
            bdir = st.input_dir() / "base"
            bdir.mkdir(parents=True, exist_ok=True)
            if not (bdir / base.name).is_file():
                shutil.copy2(base, bdir / base.name)
        params = render_params(job, st)
        st.params_path().write_text(json.dumps(params, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        log = st.out_dir() / STDOUT_LOG
        cmd = command(py, st.params_path())
        kw: dict[str, Any] = {"cwd": str(run_dir), "stdin": subprocess.DEVNULL}
        if str(params.get("device") or "auto") == "cpu":
            # Карту ховаємо від процесу цілком: раннер сам бере cuda, якщо її видно.
            kw["env"] = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}
        if os.name == "nt":
            kw["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            kw["start_new_session"] = True
        with log.open("ab") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, **kw)
        created = 0.0
        try:
            import psutil

            created = float(psutil.Process(proc.pid).create_time())
        except Exception:
            created = 0.0
        st.compute = {"kind": self.kind, "pid": proc.pid, "created": created,
                      "python": str(py), "log": str(log)}
        st.epochs = int(params.get("epochs") or 0)
        st.set_phase("running")
        st.save()
        return st

    def poll(self, st: RunState) -> Pulse:
        from nyshporka.core.lock import process_alive

        out = st.out_dir()
        pulse = Pulse(epochs=st.epochs)
        pulse.ckpts = len(list(out.glob("parseq_ep*.pt"))) if out.is_dir() else 0
        log = out / STDOUT_LOG
        if log.is_file():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                ev = parse_progress(line)
                if ev is not None and ev.phase == "train":
                    pulse.epoch = max(pulse.epoch, ev.i)
                    pulse.epochs = ev.n or pulse.epochs
        pulse.finished = (out / "ptrain_summary.json").is_file()
        pid = int(st.compute.get("pid") or 0)
        created = float(st.compute.get("created") or 0.0)
        alive = process_alive(pid, created) if pid else False
        pulse.alive = bool(alive) and not pulse.finished
        if pulse.finished:
            pulse.rc = 0
            pulse.note = "ptrain_summary.json на місці"
        elif not alive and pid:
            pulse.rc = 1
            pulse.note = f"процес {pid} не живий, а підсумку немає — дивитись {log.name}"
        return pulse

    def fetch(self, st: RunState) -> Path:
        return st.out_dir()

    def stop(self, st: RunState) -> None:
        pid = int(st.compute.get("pid") or 0)
        if not pid:
            return
        try:
            import psutil

            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(10)
            except psutil.TimeoutExpired:
                p.kill()
        except Exception:  # процесу вже нема або psutil відсутній — останній засіб
            with contextlib.suppress(OSError):
                os.kill(pid, 9)
