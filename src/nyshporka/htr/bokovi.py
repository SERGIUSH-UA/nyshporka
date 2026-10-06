"""↪ Кадри, які версії до 0.27 розгорнули з PDF боком, — і прочитане з них.

Фото з телефона лежить у PDF боком, а прямо його ставить `/Rotate 90`
сторінки. Версії до 0.27 віддавали такі сторінки сирими байтами образу, тож
кадр лежав на боці, і рушій читав з аркуша 3–9 рядків замість ~60 (ДАК
312-1-51, 05.10.2026). Розгорнути кадр наново — пів справи: текст, рамки
рядків і кеш сегментації, зняті з бокового кадру, лишались би поруч із прямим.

🔴 Тому разом із кадром відкладається все, що з нього прочитано:

- `<сторінка>.txt` і `<сторінка>.lines.json` кожного прогону цієї справи
  переїжджають у `<прогін>/_bokom/` (не видаляються), а сторінка виходить із
  мети прогону. Прочитане з бокового кадру не відповідає прямому: рамки
  рядків показували б кропи не з тих місць, а мета казала б «уже прочитано».
  Звичайне «Читати» тепер дочитує саме ці сторінки — без `--rerun` і без
  окремої теки;
- кеш сегментації цих сторінок знімається: ключ кешу — ім'я кадру й
  параметри нарізки, а не вміст, і він повернув би розмітку бокового кадру.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Тека в прогоні, куди відкладено прочитане з бокових кадрів.
ASIDE = "_bokom"


@dataclass
class Bokovi:
    """Що виправлено: кадри, прогони з відкладеним прочитаним, кеш."""

    frames: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    pages_aside: int = 0
    seg_dropped: int = 0
    problems: list[str] = field(default_factory=list)

    def message(self) -> str:
        """Рядок для людини й агента; порожньо — нічого не виправлялось."""
        if not self.frames:
            return ""
        out = (f"{len(self.frames)} кадрів лежали боком (їх розгорнула версія "
               f"до 0.27) — розгорнуто наново")
        if self.runs:
            out += (f". Прочитане з них ({self.pages_aside} стор.) у прогонах "
                    f"{', '.join(self.runs[:4])}{'…' if len(self.runs) > 4 else ''} "
                    f"відкладено в `{ASIDE}/`: «Читати» дочитає саме ці сторінки")
        else:
            out += ". Прочитаного з них на цій машині немає"
        if self.problems:
            out += f". ⚠ Не вийшло: {'; '.join(self.problems[:3])}"
        return out


def rozvernuty(case_dir: Path, *, on_line: Any = None) -> Bokovi:
    """Розгорнути бокові кадри справи й відкласти прочитане з них.

    Кличеться там, де кадри вже є (`htr.run.plan`, хмарний план і захід):
    відсутні кадри тут не дорендерюються.
    """
    from nyshporka.htr import pdfpage

    rep = Bokovi()
    case = Path(case_dir)
    if not pdfpage.case_pdfs(case):
        return rep
    pdfpage.vytiahnuty_kadry(case, lyshe_bokovi=True, vypravleni=rep.frames)
    if not rep.frames:
        return rep
    stems = {Path(f).stem for f in rep.frames}
    for run_dir in _runs_of(case, rep):
        moved = _aside(run_dir, stems, rep)
        if moved:
            rep.runs.append(run_dir.name)
            rep.pages_aside += moved
        rep.seg_dropped += _drop_seg(run_dir / "data" / "derived" / "htr_seg", stems)
    for d in _local_seg(case, rep):
        rep.seg_dropped += _drop_seg(d, stems)
    if on_line is not None:
        on_line(f"⚠ {rep.message()}")
    return rep


def _runs_of(case: Path, rep: Bokovi) -> list[Path]:
    """Теки прогонів цієї справи, включно з теками голосів."""
    try:
        from nyshporka import htr_store as S

        out: list[Path] = []
        for row in S.find_runs_for_case(str(case)):
            d = S._case_dir(str(row.get("name") or ""))
            if d is not None and d.is_dir() and d not in out:
                out.append(d)
        return out
    except Exception as exc:  # простору немає, мета побита
        rep.problems.append(f"прогони справи не знайдено ({type(exc).__name__}: {exc})")
        return []


def _local_seg(case: Path, rep: Bokovi) -> list[Path]:
    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.htr.seg import candidates

        ws = workspace()
        return [d for d in candidates(case, base_out=ws.htr_reports / "_",
                                      derived=ws.derived)]
    except Exception as exc:
        rep.problems.append(f"кеш сегментації не знайдено ({type(exc).__name__})")
        return []


def _aside(run_dir: Path, stems: set[str], rep: Bokovi) -> int:
    """Відкласти текст і рамки сторінок у `_bokom/` і вивести їх із мети."""
    moved: set[str] = set()
    for stem in sorted(stems):
        for name in (f"{stem}.txt", f"{stem}.lines.json"):
            src = run_dir / name
            if not src.is_file():
                continue
            dest = run_dir / ASIDE / name
            try:
                dest.parent.mkdir(exist_ok=True)
                src.replace(dest)
                moved.add(stem)
            except OSError as exc:
                rep.problems.append(f"{run_dir.name}/{name}: {exc}")
    dropped = _drop_from_meta(run_dir, stems, rep)
    return len(moved | dropped)


def _drop_from_meta(run_dir: Path, stems: set[str], rep: Bokovi) -> set[str]:
    """Прибрати сторінки з `pages` мети прогону (і її шардових частин)."""
    from nyshporka.utils.atomic import atomic_write_text

    gone: set[str] = set()
    for path in [run_dir / "_htr_meta.json", *run_dir.glob("_htr_meta.part*.json")]:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pages = meta.get("pages")
        if not isinstance(pages, dict):
            continue
        hit = [k for k in pages if Path(str(k)).stem in stems]
        if not hit:
            continue
        for k in hit:
            pages.pop(k, None)
            gone.add(Path(str(k)).stem)
        if meta.get("done"):
            meta["done"] = False
        try:
            atomic_write_text(path, json.dumps(meta, ensure_ascii=False, indent=1))
        except OSError as exc:
            rep.problems.append(f"{run_dir.name}/{path.name}: {exc}")
    return gone


def _drop_seg(seg_dir: Path, stems: set[str]) -> int:
    """Зняти кеш сегментації цих сторінок: `<сторінка>.o<поворот>….seg.json.gz`."""
    if not seg_dir.is_dir():
        return 0
    n = 0
    for d in [seg_dir, *(x for x in seg_dir.iterdir() if x.is_dir())]:
        for f in d.glob("*.seg.json.gz"):
            m = re.match(r"(.+?)\.o\d+", f.name)
            if m and m.group(1) in stems:
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    continue
    return n
