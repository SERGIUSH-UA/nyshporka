"""🎙 Голоси набору: що прочитав рушій на тих самих кропах.

Голос — це текст на індекс кропа. Перший голос набір дістає задарма з
прогону, з якого нарізаний. Другий і далі — двома способами:

* `--from-run` — сусідній прогін тієї самої справи (друга модель, друга
  гілка `-diak_v4`). Текст не копіюється: набір посилається на прогін.
  🔴 Приймач вирівнювання — число рядків на КОЖНІЙ нарізаній сторінці збігається
  з числом рамок набору. Не збіглось — відмова, а не «взяти скільки є»: рядок N
  чужого прогону належав би іншому кропу, і арбітр читав би голос не з того
  рядка, не маючи як це помітити.
* `--models` — прогнати ваги Писаря по кропах набору в середовищі рушіїв
  (`htr/pysar_lines_infer.py`): вихід лягає у `drafts/<id>/<page>.txt`.

Навіщо взагалі ≥2 голоси: черга розмітки ранжується РОЗБІЖНІСТЮ голосів, а
завдання арбітрам зводять їх у злиття. З одним голосом і те, і те сліпе.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from nyshporka.core.workspace import Workspace, WorkspaceError, workspace
from nyshporka.train import cut as C
from nyshporka.train import sets as S


class VoiceError(ValueError):
    """Голос не вирівняний, ваг немає або середовище рушіїв не готове."""


@dataclass
class VoiceReport:
    set: str
    voice: str
    pages: int = 0
    lines: int = 0
    warnings: list[str] = field(default_factory=list)


def _voice_id_for_run(run: str, spec: S.SetSpec) -> str:
    """Ім'я голосу з прогону: тег гілки (`-diak_v4` → `diak_v4`) або модель."""
    base = spec.source_run
    if base and run.startswith(base + "-"):
        return run[len(base) + 1:]
    try:
        meta = C.run_meta(run)
        model = str(meta.get("model") or "")
        if model:
            return Path(model).stem
    except C.CutError:
        pass
    return run


def add_from_run(name: str, run: str, *, voice_id: str = "",
                 ws: Workspace | None = None) -> VoiceReport:
    """Долучити текст сусіднього прогону як голос — після звірки вирівнювання."""
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    C.run_dir(run, w)  # відмова з поясненням, якщо прогону нема
    vid = voice_id or _voice_id_for_run(run, spec)
    if vid == S.MERGE_ID:
        raise VoiceError(f"ім'я «{S.MERGE_ID}» зарезервоване за злиттям арбітрів")
    pages = reg.crop_pages(spec)
    if not pages:
        raise VoiceError(f"у наборі «{name}» немає кропів — спершу `nysh train cut`")
    cut_meta = (reg.cut_meta(spec).get("pages") or {})
    rep = VoiceReport(set=name, voice=vid)
    bad: list[str] = []
    for page in pages:
        lines = C.page_text(run, page, w)
        want = len((cut_meta.get(page) or {}).get("boxes") or [])
        if lines is None:
            bad.append(f"{page}: у прогоні «{run}» сторінки немає")
            continue
        if want and len(lines) != want:
            bad.append(f"{page}: рядків у прогоні {len(lines)}, рамок у наборі {want}")
            continue
        rep.pages += 1
        rep.lines += len(lines)
    if bad:
        raise VoiceError("голос не вирівняний з кропами набору, тому не береться:\n  "
                         + "\n  ".join(bad[:8]))
    spec.drafts = [d for d in spec.drafts if d.id != vid] + [S.Draft(id=vid, run=run)]
    reg.save(spec)
    return rep


def _resolve_model(model: str) -> Path:
    """Шлях до ваг: явний файл або ім'я в теках моделей (`htr/run.model_dirs`)."""
    p = Path(model).expanduser()
    if p.is_file():
        return p.resolve()
    from nyshporka.htr import run as R

    for d in R.model_dirs():
        cand = d / model
        if cand.is_file():
            return cand.resolve()
        for f in d.glob(f"*{model}*.pt"):
            return f.resolve()
    raise VoiceError(f"ваг «{model}» немає ні як файла, ні в теках моделей "
                     f"({', '.join(str(d) for d in R.model_dirs()) or '—'})")


def run_model(name: str, model: str, *, voice_id: str = "", device: str = "cuda:0",
              ws: Workspace | None = None) -> VoiceReport:
    """Прогнати ваги Писаря по кропах набору в середовищі рушіїв."""
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    if not reg.crop_pages(spec):
        raise VoiceError(f"у наборі «{name}» немає кропів — спершу `nysh train cut`")
    path = _resolve_model(model)
    if path.suffix != ".pt":
        raise VoiceError(f"{path.name}: голосом по кропах уміє лише Писар (.pt)")
    vid = voice_id or path.stem
    if vid == S.MERGE_ID:
        raise VoiceError(f"ім'я «{S.MERGE_ID}» зарезервоване за злиттям арбітрів")
    try:
        venv = doc.engine_venv()
    except WorkspaceError as exc:
        raise VoiceError(str(exc)) from None
    py = E.venv_python(venv)
    if not py.exists():
        raise VoiceError("середовища рушіїв немає — `nysh htr install`")
    infer = Path(__file__).resolve().parents[1] / "htr" / "pysar_lines_infer.py"
    out = reg.set_dir(name) / S.DRAFTS_DIR / vid
    cmd = [str(py), str(infer), "--model", str(path), "--lines", str(reg.crops_of(spec)),
           "--out", str(out), "--device", device]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if res.returncode != 0:
        raise VoiceError(f"інфер упав (rc={res.returncode}): {(res.stderr or '')[-600:]}")
    rep = VoiceReport(set=name, voice=vid)
    for f in sorted(out.glob("*.txt")):
        rep.pages += 1
        rep.lines += len(f.read_text(encoding="utf-8", errors="replace").splitlines())
    spec.drafts = [d for d in spec.drafts if d.id != vid] + [
        S.Draft(id=vid, dir=f"{S.DRAFTS_DIR}/{vid}")]
    reg.save(spec)
    return rep
