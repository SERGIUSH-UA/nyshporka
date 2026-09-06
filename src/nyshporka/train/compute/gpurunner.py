"""☁ Трен через gpurunner — якщо він стоїть на шляху.

`gpurunner` — сусідній інструмент, який сам орендує карту (Modal, Vast,
Kaggle…), заливає вхід, стежить і забирає результат. Ми не дублюємо його
бекенди: рендеримо команду `gpurunner run parseq_train …` з тими самими
параметрами, що поїхали б локально, читаємо `submitted <handle>` і далі
ходимо `status`/`fetch`/`cancel`.

🔴 Корпус на бекенд потрапляє по-різному, і це не приховується:
* modal — тгз мусить лежати в томі (`modal volume put <том> <tgz> datasets/…`);
  ми друкуємо команду й перевіряємо лише, що ім'я тому задане;
* vast/lightning/colab — `-p input_root=<тека> -p dataset=<ім'я>`, і тгз
  копіюється в `runs/<id>/inputs/<ім'я>/`;
* kaggle — `dataset=owner/slug`, датасет заливається окремо (`gpurunner dataset push`).

🔴 Vast тарифікує до `cancel`: після `fetch` — обов'язково `stop`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from nyshporka.train import sizing
from nyshporka.train.compute import ComputeError, ComputePlan, Pulse, TrainJob
from nyshporka.train.state import RunState, load_calib

JOB = "parseq_train"
_SUBMIT_RE = re.compile(r"submitted\s+(\w{6,16})", re.IGNORECASE)
#: Ключі params.json, які джоба не приймає (локальні прапорці).
_LOCAL_ONLY = {"input_root", "output_root", "no_pip", "progress_json"}
#: Бекенди, що беруть вхід текою на цій машині.
_INPUT_ROOT_BACKENDS = {"vast", "lightning", "colab", "beam", "saturn"}


def which() -> str | None:
    return shutil.which("gpurunner")


def dataset_args(job: TrainJob, st: RunState) -> tuple[list[str], list[str]]:
    """`-p dataset=…` за бекендом і примітки, що зробити руками."""
    b = (job.backend or "").lower()
    notes: list[str] = []
    if b == "modal":
        vol = str(job.params.get("modal_volume") or "")
        if not vol:
            raise ComputeError("для modal вкажіть -p modal_volume=<том>: корпус читається з тому")
        notes.append(f"перед стартом: modal volume put --force {vol} {job.corpus_tgz} "
                     f"datasets/{job.corpus_name}.tgz")
        return [f"dataset=datasets/{job.corpus_name}.tgz", f"modal_volume={vol}"], notes
    if b in _INPUT_ROOT_BACKENDS:
        root = st.dir() / "inputs"
        (root / job.corpus_name).mkdir(parents=True, exist_ok=True)
        dst = root / job.corpus_name / job.corpus_tgz.name
        if not dst.is_file() and job.corpus_tgz.is_file():
            shutil.copy2(job.corpus_tgz, dst)
        return [f"dataset={job.corpus_name}", f"input_root={root}"], notes
    if b == "kaggle":
        ds = str(job.params.get("dataset") or "")
        if "/" not in ds:
            raise ComputeError("для kaggle вкажіть -p dataset=owner/slug (датасет заливається "
                               "окремо: gpurunner dataset push)")
        return [f"dataset={ds}"], notes
    raise ComputeError(f"бекенд «{job.backend or '—'}» невідомий: modal | vast | lightning | "
                       f"colab | beam | saturn | kaggle")


def command(job: TrainJob, st: RunState, *, dry_run: bool = False) -> tuple[list[str], list[str]]:
    ds, notes = dataset_args(job, st)
    cmd = ["gpurunner", "run", JOB, "-b", job.backend]
    if job.gpu:
        cmd += ["--gpu", job.gpu]
    if dry_run:
        cmd.append("--dry-run")
    for a in ds:
        cmd += ["-p", a]
    for k, v in sorted(job.params.items()):
        if k in _LOCAL_ONLY or k in ("dataset", "modal_volume"):
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        cmd += ["-p", f"{k}={v}"]
    return cmd, notes


def parse_handle(text: str) -> str:
    m = _SUBMIT_RE.search(text or "")
    return m.group(1) if m else ""


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ComputeError(f"gpurunner не відповів: {exc}") from None


class GpurunnerTrainer:
    kind = "gpurunner"

    def available(self) -> tuple[bool, str]:
        exe = which()
        if not exe:
            return False, "gpurunner немає на шляху — трен через оренду недоступний"
        return True, exe

    def plan(self, job: TrainJob) -> ComputePlan:
        ok, why = self.available()
        st = RunState(run_id=job.run_id)
        try:
            cmd, notes = command(job, st, dry_run=True)
        except ComputeError as exc:
            return ComputePlan(kind=self.kind, command=[], ok=False, warnings=[str(exc)])
        plan = ComputePlan(kind=self.kind, command=cmd, ok=ok, notes=notes, gpu=job.gpu)
        if not ok:
            plan.warnings.append(why)
        est = sizing.predict(job.rows_train, int(job.params.get("epochs", 1)),
                             job.gpu or "T4", calib=load_calib())
        plan.hours, plan.usd = est.hours, est.usd
        plan.notes += est.notes
        plan.notes.append("ціна — порядок величини за таблицею оренди; рахунок виставляє бекенд")
        if (job.backend or "").lower() == "vast":
            plan.warnings.append("vast тарифікує до cancel: після fetch — обов'язково "
                                 "`nysh train stop`")
        return plan

    def start(self, job: TrainJob, st: RunState) -> RunState:
        ok, why = self.available()
        if not ok:
            raise ComputeError(why)
        cmd, notes = command(job, st)
        res = _run(cmd)
        handle = parse_handle(res.stdout + "\n" + res.stderr)
        if res.returncode != 0 or not handle:
            raise ComputeError(f"gpurunner run не прийняв (rc={res.returncode}): "
                               f"{(res.stdout + res.stderr)[-800:]}")
        st.compute = {"kind": self.kind, "backend": job.backend, "gpu": job.gpu,
                      "handle": handle, "command": cmd, "notes": notes}
        st.epochs = int(job.params.get("epochs") or 0)
        st.set_phase("running")
        st.save()
        return st

    def poll(self, st: RunState) -> Pulse:
        handle = str(st.compute.get("handle") or "")
        pulse = Pulse(epochs=st.epochs)
        if not handle:
            pulse.note = "handle відсутній — прогін не стартував"
            return pulse
        res = _run(["gpurunner", "status", handle], timeout=120)
        text = (res.stdout + res.stderr).strip()
        low = text.lower()
        pulse.note = text[-400:]
        pulse.finished = any(w in low for w in ("complete", "done", "finished", "succeeded"))
        pulse.alive = not pulse.finished and any(w in low for w in ("running", "queued",
                                                                     "pending", "starting"))
        if any(w in low for w in ("failed", "error", "cancel")):
            pulse.rc = 1
        elif pulse.finished:
            pulse.rc = 0
        out = st.out_dir()
        pulse.ckpts = len(list(out.glob("parseq_ep*.pt"))) if out.is_dir() else 0
        return pulse

    def fetch(self, st: RunState) -> Path:
        handle = str(st.compute.get("handle") or "")
        if not handle:
            raise ComputeError("handle відсутній — нема що забирати")
        out = st.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        res = _run(["gpurunner", "fetch", handle, "--out", str(out)], timeout=3600)
        if res.returncode != 0:
            raise ComputeError(f"gpurunner fetch (rc={res.returncode}): "
                               f"{(res.stdout + res.stderr)[-800:]}")
        return out

    def stop(self, st: RunState) -> None:
        handle = str(st.compute.get("handle") or "")
        if handle:
            _run(["gpurunner", "cancel", handle], timeout=300)


_ = Any
