"""▶️ Читання бланка поклітинно: план і запуск (`nysh read <тека> --form-cells`).

Сама робота — у `cells_read.py` під інтерпретатором середовища рушіїв; тут лише
те, що знає простір: яка тека кадрів, де основний прогін справи, чия шифра, яку
модель брати. Результат — сестринська тека `<прогін>-cells`, ще один голос тієї
самої справи (`htr.form_cells` — про сам пошук клітинок).
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nyshporka.htr.run import ReadError

#: Маніфест кадрів, що лежать лише в хмарному сховищі (`cloud.verify.REMOTE_FRAMES`).
REMOTE_MANIFEST = "_r2_frames.json"
#: Суфікс теки голосу. Дзеркало `cells_read.VOICE_TAG`.
SUFFIX = "cells"


@dataclass(frozen=True)
class CellsPlan:
    case_dir: Path
    out_dir: Path
    #: Основний прогін справи: звідти кути повороту кадрів. Його може не бути.
    base_run: Path
    base_exists: bool
    model: Path
    script: str
    frames: int
    python: Path
    runner: Path

    def command(self, *, case_key: str = "", pages: str = "") -> list[str]:
        cmd = [str(self.python), str(self.runner),
               "--case-dir", str(self.case_dir), "--out-dir", str(self.out_dir),
               "--model", str(self.model), "--script", self.script]
        if self.base_exists:
            cmd += ["--base-run", str(self.base_run)]
        if case_key:
            cmd += ["--case-key", case_key]
        if pages:
            cmd += ["--pages", pages]
        return cmd


def plan(case_dir: str | Path, *, model: str = "", out_dir: str | Path = "",
         script: str = "") -> CellsPlan:
    """Зібрати план або пояснити, чого бракує. Кадри мусять лежати на цій машині."""
    from nyshporka.core.workspace import workspace
    from nyshporka.htr import env as E
    from nyshporka.htr import run as RUN
    from nyshporka.htr.runname import run_name
    from nyshporka.setup import doctor as doc

    case = Path(case_dir).expanduser().resolve()
    if not case.is_dir():
        raise ReadError(f"теки немає: {case}")
    frames = RUN.count_frames(case)
    if not frames:
        if (case / REMOTE_MANIFEST).is_file():
            raise ReadError(
                f"кадрів справи на цій машині немає: у теці лише маніфест "
                f"{REMOTE_MANIFEST} (кадри в хмарному сховищі). Читання бланка "
                f"поклітинно працює лише з кадрами на диску — хмарного шляху "
                f"поки немає")
        raise ReadError(f"у теці {case} немає зображень сторінок")

    venv = doc.engine_venv()
    rep = E.inspect_cached(venv)
    if not rep.ok or rep.python is None:
        why = "; ".join(rep.problems) or (
            f"бракує: {', '.join(rep.missing)}" if rep.missing else "не зібране")
        raise RUN.EngineMissing(f"середовище рушіїв не готове ({why}) — `nysh htr install`")

    ws = workspace()
    base = ws.htr_reports / run_name(case, RUN.case_key_for(case)[0])
    if model:
        weights, scr = RUN.resolve_model(model)
        default_out = ws.htr_reports / f"{base.name}-{SUFFIX}_{RUN.model_tag(weights)}"
    else:
        guess = RUN.guess_script_full(case, script)
        scr = guess.script if guess.script in ("latin", "cyrillic") else "cyrillic"
        weights, _ = RUN.pick_model(scr)
        default_out = ws.htr_reports / f"{base.name}-{SUFFIX}"
    runner = Path(__file__).resolve().parent / "cells_read.py"
    return CellsPlan(
        case_dir=case, out_dir=Path(out_dir) if out_dir else default_out,
        base_run=base, base_exists=(base / "_htr_meta.json").is_file(),
        model=weights, script=scr, frames=frames, python=rep.python, runner=runner)


def read(p: CellsPlan, *, case_key: str = "", pages: str = "",
         on_line: Callable[[str], None] | None = None) -> int:
    """Прогнати скрипт, віддаючи його рядки викликачеві. Повертає код завершення."""
    from nyshporka.htr.env import foreign_env

    p.out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        p.command(case_key=case_key, pages=pages), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1, env=foreign_env())
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line is not None:
            on_line(line.rstrip())
    return int(proc.wait() or 0)
