"""🗄 Стан прогону трену — файл, а не пам'ять процесу.

Трен триває години і йде в іншому процесі (або на іншій машині), тож усе, що
про нього треба знати після перезапуску застосунку, лежить у
`data/derived/train/runs/<run_id>/state.json`: фаза, де рахується, який pid
чи handle, який корпус і з якою сумою параметрів.

`run_id` детермінований (`layout.run_id_for`): повторний `start` з тим самим
корпусом і параметрами підхоплює свій прогін замість другого рахунку.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nyshporka.core.workspace import Workspace, workspace
from nyshporka.train import layout as L
from nyshporka.utils.atomic import read_json, write_json

PHASES = ("planned", "staging", "running", "fetched", "evaluated", "promoted", "failed")
STATE_FILE = "state.json"
PARAMS_FILE = "params.json"


class StateError(ValueError):
    """Прогону немає або його стан не читається."""


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def params_sha(params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class RunState:
    run_id: str
    phase: str = "planned"
    recipe: str = ""
    corpus: dict[str, Any] = field(default_factory=dict)
    compute: dict[str, Any] = field(default_factory=dict)
    params_sha: str = ""
    epochs: int = 0
    epochs_done: int = 0
    started: str = ""
    updated: str = ""
    incidents: list[str] = field(default_factory=list)
    note: str = ""

    # -- шляхи --
    def dir(self, ws: Workspace | None = None) -> Path:
        return L.runs_root(ws) / self.run_id

    def out_dir(self, ws: Workspace | None = None) -> Path:
        return self.dir(ws) / "out"

    def input_dir(self, ws: Workspace | None = None) -> Path:
        return self.dir(ws) / "input"

    def eval_dir(self, ws: Workspace | None = None) -> Path:
        return self.dir(ws) / "eval"

    def params_path(self, ws: Workspace | None = None) -> Path:
        return self.dir(ws) / PARAMS_FILE

    # -- серіалізація --
    def as_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "phase": self.phase, "recipe": self.recipe,
                "corpus": self.corpus, "compute": self.compute,
                "params_sha": self.params_sha, "epochs": self.epochs,
                "epochs_done": self.epochs_done, "started": self.started,
                "updated": self.updated, "incidents": self.incidents, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        return cls(run_id=str(d.get("run_id") or ""), phase=str(d.get("phase") or "planned"),
                   recipe=str(d.get("recipe") or ""), corpus=dict(d.get("corpus") or {}),
                   compute=dict(d.get("compute") or {}),
                   params_sha=str(d.get("params_sha") or ""),
                   epochs=int(d.get("epochs") or 0), epochs_done=int(d.get("epochs_done") or 0),
                   started=str(d.get("started") or ""), updated=str(d.get("updated") or ""),
                   incidents=[str(x) for x in (d.get("incidents") or [])],
                   note=str(d.get("note") or ""))

    def set_phase(self, phase: str, note: str = "") -> RunState:
        if phase not in PHASES:
            raise StateError(f"невідома фаза «{phase}»; є: {', '.join(PHASES)}")
        self.phase = phase
        if note:
            self.note = note
        return self

    def incident(self, text: str) -> RunState:
        self.incidents.append(f"{_utc()} {text}")
        return self

    def save(self, ws: Workspace | None = None) -> Path:
        if not self.started:
            self.started = _utc()
        self.updated = _utc()
        p = self.dir(ws) / STATE_FILE
        write_json(p, self.as_dict())
        return p


def load(run_id: str, ws: Workspace | None = None) -> RunState:
    if not L.valid_name(run_id):
        raise StateError(f"неприпустиме ім'я прогону: {run_id!r}")
    p = L.runs_root(ws) / run_id / STATE_FILE
    got = read_json(p, default=None)
    if not isinstance(got, dict):
        raise StateError(f"прогону «{run_id}» немає: {p}")
    return RunState.from_dict(got)


def list_runs(ws: Workspace | None = None) -> list[RunState]:
    root = L.runs_root(ws)
    if not root.is_dir():
        return []
    out: list[RunState] = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / STATE_FILE).is_file():
            try:
                out.append(load(d.name, ws))
            except StateError:
                continue
    return out


def latest(ws: Workspace | None = None) -> RunState | None:
    runs = list_runs(ws)
    if not runs:
        return None
    return max(runs, key=lambda r: r.updated or r.started)


def calib_path(ws: Workspace | None = None) -> Path:
    return L.derived_root(ws) / "calib.json"


def load_calib(ws: Workspace | None = None) -> dict[str, Any]:
    got = read_json(calib_path(ws), default={})
    return got if isinstance(got, dict) else {}


def save_calib(data: dict[str, Any], ws: Workspace | None = None) -> None:
    write_json(calib_path(ws), data)


_ = workspace  # реекспорт для тестів, які підставляють простір
