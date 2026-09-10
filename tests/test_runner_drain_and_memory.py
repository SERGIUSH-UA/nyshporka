"""Злив шарда і пам'ять сторінки — те, на чому стоїть регулятор флоту в хмарі.

Регулятор звужує флот не вбивством, а зливом: файл `<out>/_drain/<k>` просить
шард дочитати поточну сторінку й не брати нових. Цього мало, якщо наглядач
шарда (`supervise`) побачить недочитані сусідами сторінки як свої пропуски й
підніме дитину знову — тоді злив не діяв би взагалі.
"""
from __future__ import annotations

import argparse
import subprocess
import types
from pathlib import Path

import pytest

from nyshporka.htr import runner as R


@pytest.fixture
def case(tmp_path: Path) -> Path:
    d = tmp_path / "case"
    d.mkdir()
    for n in range(1, 7):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    return d


def _args(shard: str = "2/4") -> argparse.Namespace:
    return argparse.Namespace(shard=shard, claim=True, pages="", limit=0, supervise=2,
                              progress_json=False)


def _fake_run(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (calls.append(a), types.SimpleNamespace(returncode=0))[1])
    monkeypatch.setattr(R.sys, "argv", ["htr_case_run.py", "--shard", "2/4", "--claim"])
    return calls


def test_drain_is_addressed_to_one_shard(tmp_path: Path) -> None:
    assert not R.drain_requested(tmp_path, 1)
    (tmp_path / R.DRAIN_DIR).mkdir()
    (tmp_path / R.DRAIN_DIR / "2").write_text("t", encoding="utf-8")
    assert R.drain_requested(tmp_path, 1)          # 0-based 1 = шард «2/N»
    assert not R.drain_requested(tmp_path, 0)


def test_a_drained_shard_is_not_restarted_by_its_supervisor(
        case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    (out / R.DRAIN_DIR).mkdir(parents=True)
    (out / R.DRAIN_DIR / "2").write_text("t", encoding="utf-8")
    calls = _fake_run(monkeypatch)
    assert R.supervise(_args(), case, out) == 0
    assert len(calls) == 1


def test_an_undrained_shard_is_still_restarted(case: Path, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Контроль: без зливу недочитане — пропуски, і наглядач робить свою роботу."""
    out = tmp_path / "out"
    out.mkdir()
    calls = _fake_run(monkeypatch)
    assert R.supervise(_args(), case, out) == 3
    assert len(calls) == 3


def test_page_memory_on_cpu_reports_no_vram() -> None:
    mem = R.page_memory("cpu")
    assert "vram_peak_mb" not in mem
    assert all(isinstance(v, int) and v > 0 for v in mem.values())
