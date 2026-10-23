"""🧮 Скільки ядер продано нам — для застосунку, без рушіїв.

🔴 Дзеркало `htr/runner.py::usable_cores` і `cgroup_quota_cores`. Раннер їде
під інтерпретатором середовища рушіїв, де пакета немає, тож свої копії мусить
мати сам. Пошук по стору тексту брав їх у раннера — і з ними numpy, який раннер
імпортує на рівні модуля: в установці «Основа» numpy немає, тож щойно в просторі
з'являвся стор тексту, «Пошук у прочитаному» падав `No module named 'numpy'`
(прохід новачка 23.10.2026). Рівність двох копій доводить
`tests/test_cpu_mirror.py`.
"""
from __future__ import annotations

import os
from pathlib import Path


def cgroup_quota_cores(root: Path | str = "/sys/fs/cgroup") -> float | None:
    """Квота cgroup у ядрах, або ``None`` якщо ліміту немає."""
    root = Path(root)
    try:  # cgroup v2: "<квота> <період>" або "max <період>"
        raw = (root / "cpu.max").read_text().split()
        if raw and raw[0] != "max":
            period = float(raw[1]) if len(raw) > 1 else 100000.0
            if period > 0:
                return float(raw[0]) / period
    except (OSError, ValueError, IndexError):
        pass
    try:  # cgroup v1
        quota = float((root / "cpu" / "cpu.cfs_quota_us").read_text().strip())
        period = float((root / "cpu" / "cpu.cfs_period_us").read_text().strip())
        if quota > 0 and period > 0:
            return quota / period
    except (OSError, ValueError):
        pass
    return None


def usable_cores() -> int:
    """Ядра, продані НАМ, а не наявні в хоста (квота cgroup, прив'язка процесу)."""
    cores = float(os.cpu_count() or 1)
    try:
        allowed = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
        if allowed:
            cores = min(cores, float(allowed))
    except (AttributeError, OSError):
        pass
    quota = cgroup_quota_cores()
    if quota and quota > 0:
        cores = min(cores, quota)
    return max(1, int(cores))
