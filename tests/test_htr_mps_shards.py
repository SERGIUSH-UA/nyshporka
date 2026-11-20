"""Шарди на карті Apple (MPS): ділять карту, як на CUDA, але sato лишають на ній.

Замір 17.11.2026 (M5 Pro, 16 кадрів, Писар + Дяк голосом): 1 процес 106 с,
2 — 63 с, 3 — 55 с, 4 — 56 с; тексти 1685/1685 рядків тотожні з одиночним
прогоном. Sato на карті при двох шардах — 75 с, знятий із неї — 79 с.
Лок карти на MPS темпу не міняє (63 с із ним і без), як і на CUDA: він тримає
піки пам'яті, а пам'ять Apple-карти — це пам'ять машини.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from nyshporka.htr import gpu as G

RUNNER_SRC = (Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr"
              / "runner.py").read_text(encoding="utf-8")


def _plan(tmp_path: Path):
    from nyshporka.htr.run import Plan

    return Plan(case_dir=tmp_path / "справа", out_dir=tmp_path / "out",
                model=tmp_path / "m.pt", script="cyrillic", frames=100,
                python=tmp_path / "py", runner=tmp_path / "runner.py")


def test_mps_shards_are_not_folded(tmp_path: Path) -> None:
    cmds, notes = _plan(tmp_path).shards(2, device="mps")
    assert len(cmds) == 2
    for cmd in cmds:
        assert "--shard" in cmd and "--gpu-lock" in cmd and "--claim" in cmd
        assert "--no-gpu-sato" not in cmd, "на MPS sato лишається на карті"
    assert any("Apple" in n for n in notes)


def test_cuda_shards_still_take_sato_off_the_card(tmp_path: Path) -> None:
    cmds, _ = _plan(tmp_path).shards(2, device="cuda:0")
    assert all("--no-gpu-sato" in c for c in cmds)


def test_cpu_shards_still_fold(tmp_path: Path) -> None:
    cmds, notes = _plan(tmp_path).shards(3, device="")
    assert len(cmds) == 1 and any("згорнуто" in n for n in notes)


def test_runner_locks_and_frees_the_apple_card() -> None:
    """Лок виводиться й ставиться для будь-якої карти, і на MPS віддає кеш Metal."""
    assert "if not args.gpu_lock and shard_n > 1 and on_accelerator(device):" in RUNNER_SRC
    assert "if args.gpu_lock and on_accelerator(device) and not (" in RUNNER_SRC
    lock = RUNNER_SRC[RUNNER_SRC.index("def install_gpu_lock("):]
    lock = lock[:lock.index("\ndef ")]
    assert "torch.mps.empty_cache()" in lock


# ── де читатимуть шарди: дзеркало вибору раннера ──────────────────────────────

def _rep(mps: bool = True, torch: str = "2.14.0") -> types.SimpleNamespace:
    return types.SimpleNamespace(mps=mps, torch=torch)


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(G, "detect_card", lambda: None)
    monkeypatch.delenv(G.DEVICE_ENV, raising=False)
    return monkeypatch


def test_proven_apple_card_reads_the_shards(mac: pytest.MonkeyPatch) -> None:
    assert G.shard_device(_rep()) == "mps"


def test_unproven_torch_reads_on_the_cpu_unless_chosen(mac: pytest.MonkeyPatch) -> None:
    assert G.shard_device(_rep(torch="2.15.0")) == ""
    mac.setenv(G.DEVICE_ENV, "mps")
    assert G.shard_device(_rep(torch="2.15.0")) == "mps"


def test_cpu_pin_and_missing_card(mac: pytest.MonkeyPatch) -> None:
    assert G.shard_device(_rep(mps=False)) == ""
    mac.setenv(G.DEVICE_ENV, "cpu")
    assert G.shard_device(_rep()) == ""


def test_nvidia_card_wins_like_in_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(G.DEVICE_ENV, raising=False)
    monkeypatch.setattr(G, "detect_card", lambda: G.Card(name="RTX 3050"))
    assert G.shard_device(_rep()) == "cuda"


def test_no_apple_card_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(G, "detect_card", lambda: None)
    monkeypatch.setenv(G.DEVICE_ENV, "mps")
    assert G.shard_device(_rep()) == ""
