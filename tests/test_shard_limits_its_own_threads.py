"""Шард мусить обмежувати себе сам, хоч би хто його запустив.

Вада, проти якої стоїть цей файл: шард, запущений без `OMP_NUM_THREADS`
сімейства, бачить ядра ХОСТА, а не квоту контейнера, і розгортає BLAS/OpenMP на
них. Флот тоді не рахує паралельно, а перемикає контекст, і темп падає до темпу
ОДНОГО шарда. Замір 04.09.2026 на Tesla V100 (96 видимих ядер проти квоти
46.08): 208 стор/год замість 1579 на тому самому боксі й тій самій справі.

🔴 Чому саме тест, а не запис у пам'яті: батьківський раннер ці змінні виставляє
правильно, тож бойовий шлях був справний і сховав ваду. Виліз вона на ручному
запуску шардів по SSH — а це штатний спосіб щось поміряти. Запобіжник мусить
жити в місці, яке не обійти, і мати перевірку, яка падає.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from nyshporka.htr.runner import (
    _THREAD_VARS,
    _limit_own_threads,
    _shards_from_argv,
    cgroup_quota_cores,
    usable_cores,
)

RUNNER_SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"


@pytest.fixture(autouse=True)
def _clean_thread_env():
    """`_limit_own_threads` пише в `os.environ` НАПРЯМУ, а не через monkeypatch,
    бо саме так вона працює в житті. Тому прибирати за собою треба тут: інакше
    перший тест лишає змінну, і наступний бачить «запускач уже вирішив»."""
    saved = {var: os.environ.pop(var, None) for var in _THREAD_VARS}
    yield
    for var, was in saved.items():
        os.environ.pop(var, None)
        if was is not None:
            os.environ[var] = was


def test_shard_count_is_read_from_both_spellings_of_the_flag() -> None:
    assert _shards_from_argv(["--shard", "3/8"]) == 8
    assert _shards_from_argv(["--shard=3/8"]) == 8
    assert _shards_from_argv(["--case-dir", "x", "--shard", "1/16", "--device", "cuda:0"]) == 16
    # Немає прапорця — ми самі: машина ділиться на одного.
    assert _shards_from_argv(["--case-dir", "x"]) == 1
    # Спотворений аргумент не сміє валити прогін на кілька годин.
    assert _shards_from_argv(["--shard", "нісенітниця"]) == 1
    assert _shards_from_argv(["--shard", "1/0"]) == 1


def test_quota_beats_the_host_core_count(tmp_path: Path) -> None:
    """Рівно той рядок, що лежав на боксі 04.09.2026: 46.08 ядра при 96 видимих."""
    (tmp_path / "cpu.max").write_text("4608000 100000")
    assert cgroup_quota_cores(tmp_path) == 46.08


def test_cgroup_v1_layout_is_read_too(tmp_path: Path) -> None:
    v1 = tmp_path / "cpu"
    v1.mkdir()
    (v1 / "cpu.cfs_quota_us").write_text("800000")
    (v1 / "cpu.cfs_period_us").write_text("100000")
    assert cgroup_quota_cores(tmp_path) == 8.0


def test_no_limit_reads_as_no_limit(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("max 100000")
    assert cgroup_quota_cores(tmp_path) is None
    assert cgroup_quota_cores(tmp_path / "немає") is None


def test_the_shard_takes_its_share_and_not_the_whole_machine(monkeypatch) -> None:
    for var in _THREAD_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("nyshporka.htr.runner.usable_cores", lambda: 46)

    got = _limit_own_threads(["--shard", "3/8"])

    assert got == 5, "46 ядер на 8 шардів — це 5, а не 46 і не 12 від видимих 96"
    for var in _THREAD_VARS:
        assert os.environ[var] == "5", f"{var} лишилась невиставленою"


def test_an_explicit_choice_by_the_launcher_is_respected(monkeypatch) -> None:
    """Батьківський раннер рахує краще: він знає розкладку по картах. Якщо він
    сказав — не перебивати, інакше з'явиться друга правда про те саме."""
    for var in _THREAD_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMP_NUM_THREADS", "3")

    assert _limit_own_threads(["--shard", "1/8"]) is None
    assert os.environ["OMP_NUM_THREADS"] == "3"


def test_usable_cores_never_returns_zero(monkeypatch) -> None:
    """Нуль потоків — це зупинка прогону, тобто дорожче за будь-яку неточність."""
    monkeypatch.setattr("nyshporka.htr.runner.cgroup_quota_cores", lambda *a: 0.4)
    assert usable_cores() >= 1
    assert _limit_own_threads(["--shard", "1/64"]) == 1


def test_the_limit_is_set_before_numpy_is_imported() -> None:
    """🔴 Приймач порядку. BLAS читає змінні при завантаженні бібліотеки, тож
    ліміт, поставлений після `import numpy`, не діє взагалі — а виглядає
    цілком правильним кодом."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    limit = src.index("_SELF_LIMITED_TO = _limit_own_threads()")
    numpy = re.search(r"^import numpy as np", src, re.MULTILINE)
    assert numpy is not None
    assert limit < numpy.start(), (
        "ліміт потоків мусить стояти ПЕРЕД `import numpy` — інакше він мовчазно "
        "нічого не робить")
