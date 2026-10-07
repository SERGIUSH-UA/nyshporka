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

🔴 Порядок саме такий: спершу відкласти прочитане, і лише потім переписати
кадр. Переписаний кадр уже не впізнати як боковий, тож прочитане, яке не
вдалось відкласти, лишилось би назавжди — текст бокового аркуша, що в меті
рахується прочитаним. Кадр, з яким так сталось, лишається боком, і наступний
запуск спробує знову.

🔴 Розгортає лише запуск читання. План (`nysh read --dry-run`, `read.plan`,
хмарний план) тільки каже, скільки кадрів лежить боком: подивитись план не
означає погодитись, що прочитане з них зникне з пошуку до перечитування.
"""
from __future__ import annotations

import json
import os
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
    #: План: кадри лише знайдено, нічого не змінено.
    planned: bool = False
    #: Бокові кадри, що лишились боком, бо прочитане з них не відкладено.
    kept: list[str] = field(default_factory=list)

    def message(self) -> str:
        """Рядок для людини й агента; порожньо — нічого не знайдено."""
        if self.planned:
            return self._plan_message()
        if not self.frames and not self.kept:
            return ""
        if self.frames:
            out = (f"{len(self.frames)} кадрів лежали боком (їх розгорнула версія "
                   f"до 0.27) — розгорнуто наново")
            if self.runs:
                out += (f". Прочитане з них ({self.pages_aside} стор.) у прогонах "
                        f"{_names(self.runs)} відкладено в `{ASIDE}/`: «Читати» "
                        f"дочитає саме ці сторінки")
            else:
                out += ". Прочитаного з них на цій машині немає"
        else:
            out = f"{len(self.kept)} кадрів лежать боком (їх розгорнула версія до 0.27)"
        if self.kept:
            out += (f". ⚠ {len(self.kept)} кадрів лишено боком: прочитане з них "
                    f"не вдалось відкласти — наступний запуск спробує знову")
        if self.problems:
            out += f". ⚠ Не вийшло: {'; '.join(self.problems[:3])}"
        return out

    def _plan_message(self) -> str:
        if not self.frames:
            return ""
        out = (f"{len(self.frames)} кадрів лежать боком (їх розгорнула версія до "
               f"0.27) — запуск читання розгорне їх наново")
        if self.runs:
            out += (f", а прочитане з них ({self.pages_aside} стор.) у прогонах "
                    f"{_names(self.runs)} відкладе в `{ASIDE}/` і дочитає ці сторінки")
        if self.problems:
            out += f". ⚠ {'; '.join(self.problems[:3])}"
        return out


def _names(runs: list[str]) -> str:
    return f"{', '.join(runs[:4])}{'…' if len(runs) > 4 else ''}"


def rozvernuty(case_dir: Path, *, on_line: Any = None, plan: bool = False) -> Bokovi:
    """Розгорнути бокові кадри справи й відкласти прочитане з них.

    Кличеться там, де кадри вже є (запуск читання, хмарний захід): відсутні
    кадри тут не дорендерюються. `plan` — лише порахувати, нічого не змінюючи
    (план читання).
    """
    from nyshporka.htr import pdfpage

    rep = Bokovi(planned=plan)
    case = Path(case_dir)
    side = pdfpage.bokovi_kadry(case)
    if not side:
        return rep
    stems = {Path(f).stem for f in side}
    runs = _runs_of(case, rep)
    if plan:
        rep.frames = side
        for run_dir in runs:
            n = len(_read_stems(run_dir, stems))
            if n:
                rep.runs.append(run_dir.name)
                rep.pages_aside += n
        return rep
    failed: set[str] = set()
    if rep.problems:
        # Прогонів не знайдено через збій — прочитане не відкласти, тож кадри
        # лишаються боком, щоб наступний запуск їх упізнав.
        failed = set(stems)
    else:
        for run_dir in runs:
            moved = _aside(run_dir, stems, rep, failed)
            if moved:
                rep.runs.append(run_dir.name)
                rep.pages_aside += moved
            _drop_seg(run_dir / "data" / "derived" / "htr_seg", stems, rep, failed)
        for d in _local_seg(case, rep, failed, stems):
            _drop_seg(d, stems, rep, failed)
    ok = {f for f in side if Path(f).stem not in failed}
    rep.kept = sorted(set(side) - ok)
    if ok:
        pdfpage.vytiahnuty_kadry(case, lyshe_bokovi=True, vypravleni=rep.frames,
                                 tilky=ok)
    if on_line is not None and rep.message():
        on_line(f"⚠ {rep.message()}")
    return rep


def _runs_of(case: Path, rep: Bokovi) -> list[Path]:
    """Теки прогонів цієї справи, включно з теками голосів.

    🔴 За будь-якою формою шляху. Прогін записано під тим шляхом, яким теку
    назвали на старті, — часто через junction (`data/raw/<архів>` → диск з
    кадрами), а сюди тека приходить розкритою (`resolve()`). Пошук лише за
    одним написанням давав «прочитаного немає», і текст бокових кадрів
    лишався в пошуку назавжди.
    """
    try:
        from nyshporka import htr_store as S

        target = _norm(case)
        rows = list(S.find_runs_for_case(str(case)))
        for key, found in S.runs_by_case_dir().items():
            if _norm(key) == target:
                rows += found
        out: list[Path] = []
        for row in rows:
            d = S._case_dir(str(row.get("name") or ""))
            if d is not None and d.is_dir() and d not in out:
                out.append(d)
        return out
    except Exception as exc:  # простору немає, мета побита
        rep.problems.append(f"прогони справи не знайдено ({type(exc).__name__}: {exc})")
        return []


def _norm(path: str | Path) -> str:
    """Одна форма шляху для порівняння: розкриті junction, регістр Windows."""
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(path)))


def _read_stems(run_dir: Path, stems: set[str]) -> set[str]:
    """Які з цих сторінок прогін має прочитаними (файлом чи в меті)."""
    got = {s for s in stems
           if (run_dir / f"{s}.txt").is_file() or (run_dir / f"{s}.lines.json").is_file()}
    for path in [run_dir / "_htr_meta.json", *run_dir.glob("_htr_meta.part*.json")]:
        try:
            pages = json.loads(path.read_text(encoding="utf-8")).get("pages")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(pages, dict):
            got |= {Path(str(k)).stem for k in pages} & stems
    return got


def _local_seg(case: Path, rep: Bokovi, failed: set[str], stems: set[str]) -> list[Path]:
    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.htr.seg import candidates

        ws = workspace()
        return [d for d in candidates(case, base_out=ws.htr_reports / "_",
                                      derived=ws.derived)]
    except Exception as exc:
        # Кеш, якого не знайшли, міг лишитись — кадр розгортати не можна.
        rep.problems.append(f"кеш сегментації не знайдено ({type(exc).__name__})")
        failed |= stems
        return []


def _aside(run_dir: Path, stems: set[str], rep: Bokovi, failed: set[str]) -> int:
    """Відкласти текст і рамки сторінок у `_bokom/` і вивести їх із мети.

    Сторінка, яку не вдалось відкласти чи вивести з мети, йде у `failed`.
    """
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
                failed.add(stem)
    dropped = _drop_from_meta(run_dir, stems, rep, failed)
    return len(moved | dropped)


def _drop_from_meta(run_dir: Path, stems: set[str], rep: Bokovi,
                    failed: set[str]) -> set[str]:
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
        hit = {Path(str(k)).stem for k in pages if Path(str(k)).stem in stems}
        if not hit:
            continue
        for k in [k for k in pages if Path(str(k)).stem in hit]:
            pages.pop(k, None)
        if meta.get("done"):
            meta["done"] = False
        try:
            atomic_write_text(path, json.dumps(meta, ensure_ascii=False, indent=1))
        except OSError as exc:
            rep.problems.append(f"{run_dir.name}/{path.name}: {exc}")
            failed |= hit
            continue
        gone |= hit
    return gone


def _drop_seg(seg_dir: Path, stems: set[str], rep: Bokovi, failed: set[str]) -> None:
    """Зняти кеш сегментації цих сторінок: `<сторінка>.o<поворот>….seg.json.gz`.

    Кеш, що лишився, повернув би прямому кадру розмітку бокового — така
    сторінка йде у `failed`.
    """
    if not seg_dir.is_dir():
        return
    for d in [seg_dir, *(x for x in seg_dir.iterdir() if x.is_dir())]:
        for f in d.glob("*.seg.json.gz"):
            m = re.match(r"(.+?)\.o\d+", f.name)
            if m and m.group(1) in stems:
                try:
                    f.unlink()
                    rep.seg_dropped += 1
                except OSError as exc:
                    rep.problems.append(f"{f.name}: {exc}")
                    failed.add(m.group(1))
