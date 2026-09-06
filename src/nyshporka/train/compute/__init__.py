"""⚙ Де рахується трен: своя карта, свій сервер, gpurunner.

Один контракт на три шляхи — і той самий `params.json` для всіх. Відрізняється
лише те, ЯК корпус потрапляє до раннера і ЯК звідти забираються ваги:

* `local` — середовище рушіїв цієї машини, раннер-гість, процес відчеплено;
* `ssh` — своя машина через `nyshporka.cloud` (той самий, що читає справи);
* `gpurunner` — сусідній інструмент, якщо стоїть на шляху: він сам орендує
  карту, а ми лише рендеримо команду й забираємо результат.

🔴 План друкується завжди, старт — окремо: годину карти й гроші не витрачають
на те, чого не бачили. `--dry-run` = лише план.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from nyshporka.train.state import RunState

KINDS = ("local", "ssh", "gpurunner")


class ComputeError(ValueError):
    """Шлях обчислень недоступний або запуск не вдався."""


def base_file(params: dict[str, Any]) -> Path | None:
    """Якщо `pretrained` — файл ваг на диску, повернути його; інакше None.

    Раннер знає два джерела бази: id репозиторію на хабі й `local` (перший
    `*.pt` під входом). Шлях до файла — третій, наш: файл кладеться під вхід
    у теку `base/`, а параметри стають `pretrained=local`.
    """
    spec = str(params.get("pretrained") or "")
    if not spec or spec in ("local", "scratch"):
        return None
    p = Path(spec).expanduser()
    return p if p.suffix == ".pt" and p.is_file() else None


def with_local_base(params: dict[str, Any]) -> dict[str, Any]:
    p = dict(params)
    if base_file(params) is not None:
        p["pretrained"] = "local"
        p["pretrained_dataset"] = "base"
    return p


@dataclass
class TrainJob:
    run_id: str
    corpus_name: str
    corpus_tgz: Path
    params: dict[str, Any]          # TrainParams.as_params()
    rows_train: int = 0
    gpu: str = ""                   # бажана карта (gpurunner) або та, що є (local)
    backend: str = ""               # gpurunner: modal|vast|kaggle|…
    host: str = ""                  # ssh: ім'я хоста з nysh cloud hosts


@dataclass
class ComputePlan:
    kind: str
    command: list[str]
    hours: float = 0.0
    usd: float = 0.0
    gpu: str = ""
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "command": self.command, "hours": round(self.hours, 2),
                "usd": round(self.usd, 2), "gpu": self.gpu, "warnings": self.warnings,
                "notes": self.notes, "ok": self.ok}


@dataclass
class Pulse:
    alive: bool = False
    finished: bool = False
    rc: int | None = None
    epoch: int = 0
    epochs: int = 0
    ckpts: int = 0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"alive": self.alive, "finished": self.finished, "rc": self.rc,
                "epoch": self.epoch, "epochs": self.epochs, "ckpts": self.ckpts,
                "note": self.note}


class Trainer(Protocol):
    kind: str

    def available(self) -> tuple[bool, str]: ...
    def plan(self, job: TrainJob) -> ComputePlan: ...
    def start(self, job: TrainJob, st: RunState) -> RunState: ...
    def poll(self, st: RunState) -> Pulse: ...
    def fetch(self, st: RunState) -> Path: ...
    def stop(self, st: RunState) -> None: ...


def select(kind: str = "auto", *, host: str = "", backend: str = "") -> Trainer:
    """Шлях за явними прапорцями: `--host` → ssh, `--backend` → gpurunner, інакше local."""
    from nyshporka.train.compute import gpurunner as G
    from nyshporka.train.compute import local as Lc

    if kind == "auto":
        kind = "ssh" if host else ("gpurunner" if backend else "local")
    if kind == "local":
        return Lc.LocalTrainer()
    if kind == "gpurunner":
        return G.GpurunnerTrainer()
    if kind == "ssh":
        import importlib

        try:
            mod = importlib.import_module("nyshporka.train.compute.ssh")
        except ImportError as exc:
            raise ComputeError(f"шлях ssh недоступний: {exc}") from None
        trainer: Trainer = mod.SshTrainer()
        return trainer
    raise ComputeError(f"невідомий шлях обчислень «{kind}»; є: {', '.join(KINDS)}")


def detect() -> dict[str, dict[str, Any]]:
    """Що з трьох шляхів є на цій машині — і чому ні."""
    out: dict[str, dict[str, Any]] = {}
    for k in KINDS:
        try:
            ok, why = select(k).available()
        except ComputeError as exc:
            ok, why = False, str(exc)
        out[k] = {"ok": ok, "why": why}
    return out
