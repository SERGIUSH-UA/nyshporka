"""🗜 `nysh disk compact`: перевести геометрію старих прогонів у стиснуту форму.

З 0.40.0 прогін пише рамки рядків як `<стор>.lines.json.gz` (`nyshporka.htr.layout`).
Старі прогони лежать із простим `<стор>.lines.json`, і саме ці файли — найбільша
частина простору (ідея №11 порталу: 21 ГБ із 33; у Майстерні — 46 КБ на сторінку,
gzip лишає ~28 %). Ця команда стискає їх один раз.

🔴 Порядок на кожен файл — щоб обрив на будь-якому кроці не втратив рамок:

1. прочитати байти простого файлу;
2. стиснути й записати `<стор>.lines.json.gz.<pid>.tmp`;
3. розтиснути записане й звірити з оригіналом байт у байт;
4. перенести на `.gz` час оригіналу (`os.utime`) і атомарно перейменувати;
5. лише тоді видалити простий файл.

Між 4 і 5 на диску лежать обидва — читачі беруть `.gz` (`layout.GEOMETRY_SUFFIXES`),
а повтор команди звірить пару й доприбере простий.

🔴 Стор тексту від цього не перебудовується. Штамп прогону — мета плюс час
теки, і поява `.gz` той час міняє; тому після теки її час повертається. А навіть
якби штамп змінився, `search.store._text_unchanged` дивиться на час КОЖНОГО файлу
— і бачить час оригіналу, тобто «текст той самий».

🔴 За сумніву — лишити (правило всього `disk`). Не чіпаються:

* прогони живих локальних читань (`htr.runs.alive()`) і живих хмарних заходів
  (`disk._live_runs()`); стан хмари не прочитався — `--apply` відмовляє;
* теки, де простий файл геометрії свіжіший за `FRESH_SEC`: його міг щойно
  покласти хтось, кого реєстри не бачать (`cloud fetch`, сторонній скрипт), і
  наступна його копія лягла б поруч зі стиснутою старою.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.htr import layout as HL

#: Простий файл геометрії, свіжіший за це, означає, що в теку ще пишуть.
FRESH_SEC = 600


class CompactError(RuntimeError):
    """Захід не почато — з причиною для людини."""


@dataclass
class RunResult:
    run: str
    files: int = 0            # простих файлів геометрії знайдено
    done: int = 0             # стиснуто (або доприбрано пару)
    before: int = 0           # байтів простих файлів
    after: int = 0            # байтів стиснутих (оцінка на --dry-run — з вибірки)
    skipped: str = ""         # чому тека не чіпалась
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"run": self.run, "files": self.files, "done": self.done,
                "before": self.before, "after": self.after, "skipped": self.skipped,
                "errors": self.errors}


@dataclass
class Report:
    runs: list[RunResult] = field(default_factory=list)
    apply: bool = False
    #: Частка стиснення з вибірки на --dry-run (без запису).
    ratio: float | None = None

    def as_json(self) -> dict[str, Any]:
        live = [r for r in self.runs if not r.skipped]
        return {
            "apply": self.apply,
            "runs": len(self.runs),
            "runs_with_plain": sum(1 for r in live if r.files),
            "files": sum(r.files for r in live),
            "done": sum(r.done for r in live),
            "before": sum(r.before for r in live),
            "after": sum(r.after for r in live),
            "ratio": self.ratio,
            "skipped": [{"run": r.run, "why": r.skipped} for r in self.runs if r.skipped],
            "errors": [f"{r.run}: {e}" for r in self.runs for e in r.errors],
        }


# ── один файл ────────────────────────────────────────────────────────────────

def compact_file(plain: Path) -> tuple[int, int]:
    """Стиснути один простий файл геометрії. Повертає (байтів було, байтів стало).

    Будь-яка невдача — виняток, і простий файл тоді лишається на місці.
    """
    stem = HL.geometry_stem(plain.name)
    if stem is None or not plain.name.endswith(HL.PLAIN_SUFFIX):
        raise ValueError(f"{plain.name}: це не простий файл геометрії")
    gz = plain.with_name(HL.geometry_name(stem))
    st = plain.stat()
    raw = plain.read_bytes()
    # Полігони — без точок на прямій (`htr.geom_simplify`): контур і маска ті самі,
    # а коли прорідити нічого — ті самі байти.
    want = HL.thinned_bytes(raw)
    if gz.is_file():
        # Пара після обриву (або писач уже дописав стиснуту): простий файл
        # прибирається, лише якщо `.gz` має ТОЙ САМИЙ вміст — до проріджування
        # чи після. Інакше — дві різні правди, і вирішувати, котра справжня, тут
        # не можна.
        if HL.geometry_bytes(gz) not in (raw, want):
            raise ValueError(f"{plain.name}: поруч лежить {gz.name} з іншим вмістом — "
                             f"не чіпаю жодного")
        size = gz.stat().st_size
        plain.unlink()
        return len(raw), size
    check_thinning(plain.name, raw, want)
    blob = HL.gz_blob(want)
    tmp = gz.with_name(f"{gz.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(blob)
        if gzip.decompress(tmp.read_bytes()) != want:
            raise ValueError(f"{plain.name}: стиснуте не розтискається в той самий вміст")
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, gz)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    plain.unlink()
    return len(raw), len(blob)


def check_thinning(name: str, raw: bytes, want: bytes) -> None:
    """🔴 Друга рука над проріджуванням, незалежна від його коду: усе, крім
    полігонів, те саме; кожен полігон — підпослідовність свого оригіналу, а
    кожна викинута точка лежить на відрізку між лишеними сусідами."""
    if want == raw:
        return
    a, b = json.loads(raw.decode("utf-8")), json.loads(want.decode("utf-8"))
    rest_a = {k: v for k, v in a.items() if k != "polys"}
    rest_b = {k: v for k, v in b.items() if k != "polys"}
    if rest_a != rest_b:
        raise ValueError(f"{name}: проріджування зачепило не лише полігони")
    pa, pb = a.get("polys") or [], b.get("polys") or []
    if len(pa) != len(pb):
        raise ValueError(f"{name}: після проріджування інше число полігонів")
    for p, q in zip(pa, pb, strict=True):
        if p != q and not _thin_ok(p, q):
            raise ValueError(f"{name}: проріджений полігон — не той самий контур")


def _on_segment(a: Any, b: Any, c: Any) -> bool:
    """Чи точка b на відрізку a–c (включно з кінцями)."""
    if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) != 0:
        return False
    return bool(min(a[0], c[0]) <= b[0] <= max(a[0], c[0])
                and min(a[1], c[1]) <= b[1] <= max(a[1], c[1]))


def _thin_ok(orig: Any, thin: Any) -> bool:
    if not isinstance(orig, list) or not isinstance(thin, list) or len(thin) < 3:
        return False
    keep: list[int] = []
    j = 0
    for i, pt in enumerate(orig):
        if j < len(thin) and pt == thin[j]:
            keep.append(i)
            j += 1
    if j != len(thin):
        return False
    for k, i in enumerate(keep):
        nxt = keep[(k + 1) % len(keep)]
        span = (list(range(i + 1, nxt)) if nxt > i
                else list(range(i + 1, len(orig))) + list(range(nxt)))
        if not all(_on_segment(orig[i], orig[m], orig[nxt]) for m in span):
            return False
    return True


# ── тека прогону ─────────────────────────────────────────────────────────────

def _plain_files(run_dir: Path) -> list[Path]:
    out: list[Path] = []
    try:
        with os.scandir(run_dir) as it:
            for e in it:
                if e.name.endswith(HL.PLAIN_SUFFIX) and e.is_file():
                    out.append(Path(e.path))
    except OSError:
        pass
    return sorted(out)


def compact_run(run_dir: Path, *, apply: bool, now: float | None = None,
                sample: list[Path] | None = None) -> RunResult:
    """Стиснути геометрію однієї теки. Без `apply` — лише порахувати.

    `sample` — куди класти кілька файлів для оцінки частки на --dry-run.
    """
    res = RunResult(run=run_dir.name)
    files = _plain_files(run_dir)
    res.files = len(files)
    if not files:
        return res
    t = time.time() if now is None else now
    try:
        stats = [(f, f.stat()) for f in files]
    except OSError as exc:
        res.skipped = f"не читається: {exc}"
        return res
    fresh = [f for f, st in stats if t - st.st_mtime < FRESH_SEC]
    if fresh:
        res.skipped = (f"{len(fresh)} файл(ів) геометрії змінено менше ніж "
                       f"{FRESH_SEC // 60} хв тому ({fresh[0].name}) — у теку ще пишуть")
        return res
    res.before = sum(st.st_size for _, st in stats)
    if not apply:
        if sample is not None and len(sample) < 64:
            sample.extend(files[:2])
        return res
    try:
        dst = run_dir.stat()
    except OSError as exc:
        res.skipped = f"не читається: {exc}"
        return res
    res.before = 0
    for f in files:
        try:
            was, now_b = compact_file(f)
        except (OSError, ValueError) as exc:
            res.errors.append(str(exc))
            continue
        res.done += 1
        res.before += was
        res.after += now_b
    # Час теки — назад: інакше штамп стору (мета + тека) назвав би прогін зміненим.
    try:
        os.utime(run_dir, ns=(dst.st_atime_ns, dst.st_mtime_ns))
    except OSError as exc:
        res.errors.append(f"час теки не повернуто: {exc}")
    return res


# ── вибір прогонів ───────────────────────────────────────────────────────────

def _run_rows(case: list[str]) -> list[dict[str, Any]]:
    from nyshporka import htr_store as S

    if not case:
        return list(S.list_cases())
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope in case:
        try:
            got = S.runs_for_scope(scope)
        except ValueError as exc:
            raise CompactError(str(exc)) from exc
        found = got.get("rows") or []
        if not found:
            raise CompactError(f"для «{scope}» прогонів не знайдено (nysh text state)")
        for r in found:
            name = str(r.get("name") or "")
            if name and name not in seen:
                seen.add(name)
                rows.append(r)
    return rows


def _busy() -> tuple[Callable[[str, dict[str, Any]], str], bool]:
    """Перевірка «у цю теку зараз пишуть» і чи стан хмари прочитався."""
    from nyshporka import disk as D
    from nyshporka.htr import runs as R

    try:
        local = R.alive()
    except Exception:
        local = None
    cloud = D._live_runs()
    loc_keys = {str(x.case_key) for x in local or [] if x.case_key}
    loc_dirs = {os.path.normcase(str(x.case)) for x in local or [] if x.case}
    cl_names = {Path(str(s.out_dir)).name for s in cloud or [] if getattr(s, "out_dir", "")}
    cl_keys = {str(s.case_key) for s in cloud or [] if getattr(s, "case_key", "")}

    def why(name: str, row: dict[str, Any]) -> str:
        if local is None:
            return "реєстр живих читань не прочитався"
        key = str(row.get("case_key") or "")
        cdir = os.path.normcase(str(row.get("case_dir") or ""))
        if (key and key in loc_keys) or (cdir and cdir in loc_dirs):
            return "справу зараз читають на цій машині"
        base = name.rsplit("-", 1)[0]
        if name in cl_names or base in cl_names or (key and key in cl_keys):
            return "справа в живому хмарному заході"
        return ""

    return why, cloud is not None


def _auto_workers() -> int:
    return max(1, min(16, os.cpu_count() or 1))


def compact(*, case: list[str] | None = None, apply: bool = False,
            limit: int = 0, progress: Callable[[int, int, str], None] | None = None,
            workers: int = 1) -> Report:
    """Стиснути геометрію прогонів простору (або названих справ).

    `workers` > 1 (0 — за числом ядер) розводить ТЕКИ по процесах: кожна тека
    цілком в одному процесі, тож пара файлів однієї сторінки ніколи не
    стискається двома руками. Вузьке місце — дрібні файлові операції NTFS
    (тимчасовий файл, заміна, видалення, час), а не gzip, тому процеси, не
    потоки. З `limit` — послідовно: межа рахує лише теки з простими файлами.
    """
    from nyshporka.core.workspace import workspace

    rows = _run_rows(list(case or []))
    why, cloud_ok = _busy()
    if apply and not cloud_ok:
        raise CompactError("стан хмарних заходів не прочитався — не знаю, куди зараз "
                           "забирають результати, тож нічого не стискаю. Подивіться "
                           "nysh cloud state і повторіть")
    root = workspace().htr_reports
    rep = Report(apply=apply)
    sample: list[Path] = []
    total = len(rows)
    n_workers = _auto_workers() if workers <= 0 else workers
    if apply and n_workers > 1 and not limit:
        _compact_parallel(rows, root, why, rep, n_workers, progress)
        return rep
    done_runs = 0
    for i, row in enumerate(rows, 1):
        name = str(row.get("name") or "")
        if not name:
            continue
        d = root / name
        if progress:
            progress(i, total, name)
        if not d.is_dir():
            continue
        busy = why(name, row)
        if busy:
            r = RunResult(run=name, files=len(_plain_files(d)), skipped=busy)
            if r.files:
                rep.runs.append(r)
            continue
        r = compact_run(d, apply=apply, sample=sample)
        if r.files or r.skipped or r.errors:
            rep.runs.append(r)
        if r.files and not r.skipped:
            done_runs += 1
            if limit and done_runs >= limit:
                break
    if not apply and sample:
        was = got = 0
        for f in sample:
            try:
                raw = f.read_bytes()
            except OSError:
                continue
            was += len(raw)
            got += len(HL.gz_blob(raw))
        if was:
            rep.ratio = got / was
            for r in rep.runs:
                if not r.skipped:
                    r.after = int(r.before * rep.ratio)
    return rep


def _compact_parallel(rows: list[dict[str, Any]], root: Path,
                      why: Callable[[str, dict[str, Any]], str], rep: Report,
                      n_workers: int,
                      progress: Callable[[int, int, str], None] | None) -> None:
    """`--apply` по теках у `n_workers` процесах; порядок звіту — як у переліку."""
    from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait

    total = len(rows)
    slots: list[RunResult | None] = []
    todo: list[tuple[int, str, Path]] = []
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        d = root / name
        if not d.is_dir():
            continue
        busy = why(name, row)
        if busy:
            r = RunResult(run=name, files=len(_plain_files(d)), skipped=busy)
            slots.append(r if r.files else None)
            continue
        slots.append(None)
        todo.append((len(slots) - 1, name, d))
    seen = total - len(todo)
    # Не більше двох тек на процес у черзі: обрив (Ctrl+C) не лишає тисяч
    # поставлених завдань, а пам'ять не росте від переліку на 30 тис. тек.
    cap = n_workers * 2
    it = iter(todo)
    live: dict[Future[RunResult], tuple[int, str, Path]] = {}
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        def feed() -> None:
            while len(live) < cap:
                nxt = next(it, None)
                if nxt is None:
                    return
                live[pool.submit(compact_run, nxt[2], apply=True)] = nxt
        feed()
        while live:
            got, _ = wait(live, return_when=FIRST_COMPLETED)
            for fut in got:
                idx, name, _d = live.pop(fut)
                try:
                    r = fut.result()
                except Exception as exc:  # процес упав — тека лишається як була
                    r = RunResult(run=name, errors=[f"процес стиснення впав: {exc}"])
                if r.files or r.skipped or r.errors:
                    slots[idx] = r
                seen += 1
                if progress:
                    progress(seen, total, name)
            feed()
    rep.runs.extend(r for r in slots if r is not None)
