"""Скільки процесів дати свіпу — від заліза, а не сталою; штампи свіжості гуртом."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nyshporka.search import store as ST

GB = 2 ** 30


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch):
    """Залізо під контролем тесту: ядра й вільна пам'ять."""
    import psutil

    state = {"cores": 12, "physical": 6, "free_gb": 20.0}
    monkeypatch.setattr("nyshporka.htr.runner.usable_cores", lambda: state["cores"])
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: (
        state["cores"] if logical else state["physical"]))
    monkeypatch.setattr(psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=int(state["free_gb"] * GB)))
    monkeypatch.delenv(ST.SWEEP_WORKERS_ENV, raising=False)
    monkeypatch.setattr(ST, "SWEEP_WORKERS", None)
    return state


def test_strong_machine_gets_more_workers_than_weak(machine) -> None:
    machine.update(cores=12, physical=6, free_gb=20.0)
    strong = ST.sweep_workers(100, worker_gb=ST.FAST_WORKER_GB)
    machine.update(cores=4, physical=2, free_gb=3.0)
    weak = ST.sweep_workers(100, worker_gb=ST.FAST_WORKER_GB)
    assert strong == 6                  # фізичні ядра, не логічні
    assert weak == 2                    # 3 ГБ · 0,5 / 0,75 — пам'ять тісніша за ядра
    assert ST.sweep_workers(100) == 1   # блок свіпу триграмами на тій самій машині


def test_memory_limits_before_cores(machine) -> None:
    machine.update(cores=32, physical=16, free_gb=64.0)
    assert ST.sweep_workers(100) == int(64.0 * ST.MEM_SHARE / ST.BLOCK_WORKER_GB) < 16


def test_trigram_block_on_this_kind_of_machine_gets_one_worker(machine) -> None:
    """32 ГБ, ~19 вільних: блок свіпу триграмами бере 2,5–7,7 ГБ і більше — один процес.

    Саме тут 22.10.2026 шість процесів за старою цифрою (1,5 ГБ) поклали б систему.
    """
    machine.update(cores=12, physical=6, free_gb=19.0)
    assert ST.sweep_workers(100) == 1
    assert ST.sweep_workers(100, worker_gb=ST.FAST_WORKER_GB) == 6


def test_never_more_than_blocks_and_never_zero(machine) -> None:
    machine.update(cores=12, physical=6, free_gb=20.0)
    assert ST.sweep_workers(2, worker_gb=ST.FAST_WORKER_GB) == 2
    machine.update(cores=1, physical=1, free_gb=0.2)
    assert ST.sweep_workers(100) == 1


def test_env_and_constant_override_hardware(machine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ST, "SWEEP_WORKERS", 5)
    assert ST.sweep_workers(100) == 5
    monkeypatch.setenv(ST.SWEEP_WORKERS_ENV, "3")
    assert ST.sweep_workers(100) == 3
    monkeypatch.setenv(ST.SWEEP_WORKERS_ENV, "не число")
    assert ST.sweep_workers(100) == 5


def test_container_quota_caps_physical_cores(machine) -> None:
    """Квота контейнера (usable_cores) менша за фізичні ядра хоста — береться квота."""
    machine.update(cores=4, physical=48, free_gb=100.0)
    assert ST.sweep_workers(100, worker_gb=ST.FAST_WORKER_GB) == 4


def test_unknown_memory_is_cautious(machine, monkeypatch: pytest.MonkeyPatch) -> None:
    import psutil

    def broken():
        raise OSError("немає")

    monkeypatch.setattr(psutil, "virtual_memory", broken)
    assert ST.sweep_workers(100) == 2


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    for run in ("проба-а", "проба-б", "проба-в"):
        d = tmp_path / "reports" / "htr" / run
        d.mkdir(parents=True)
        (d / "0001.txt").write_text("Ковальчинскій\n", encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps(
            {"model": "pysar_cyr_v17.pt", "pages": {"0001.jpg": {"lines": 1}}}), encoding="utf-8")
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(["проба-а", "проба-б"]))
    yield tmp_path
    W.reset()


def test_bulk_stamps_and_counts_match_per_run(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = ["проба-а", "проба-б", "проба-в", "немає-такого", "ПРОБА-А"]
    one = ST.stamps_for(runs)
    assert one == {r: ST.stamp_of(r) for r in runs}
    stale_one = ST.stale_count(runs[:4])
    monkeypatch.setattr(ST, "BULK_RUNS", 1)
    assert ST.stamps_for(runs) == one
    if (space / "reports" / "htr" / "ПРОБА-А").exists():  # тека без регістру: Windows, macOS
        assert ST.stamps_for(runs)["ПРОБА-А"] == one["проба-а"] != ""
    assert ST.stale_count(runs[:4]) == stale_one == 2  # «в» не зібрано, «немає» немає
    meta = space / "reports" / "htr" / "проба-а" / "_htr_meta.json"
    meta.write_text(meta.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert ST.stale_count(runs[:4]) == 3              # дописана мета — несвіжий і гуртом


def test_bulk_stamp_ignores_case_of_the_run_folder(space: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Тека з великими літерами, запит малими — той самий прогін, як у `stamp_of` на Windows."""
    d = space / "reports" / "htr" / "Проба-Верх"
    d.mkdir()
    (d / "_htr_meta.json").write_text("{}", encoding="utf-8")
    want = ST.stamp_of("проба-верх")
    if (d.parent / "проба-верх").exists():
        assert want, "без регістру (Windows) `stamp_of` знаходить теку"
    monkeypatch.setattr(ST, "BULK_RUNS", 1)
    assert ST.stamps_for(["проба-верх"]) == {"проба-верх": want}
