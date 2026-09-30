"""Писар у fp16 — лише там, де карта від цього швидша.

Заміряно 30.09.2026: RTX 3060 fp32 → fp16 ×2.7 на розпізнаванні, GTX 1650
(Turing без тензорних ядер) — утричі повільніше. Тож `auto` вирішує за картою,
а не «fp16 скрізь».
"""
from __future__ import annotations

import sys
import types

import pytest

from nyshporka.htr import runner as R


def _fake_torch(monkeypatch: pytest.MonkeyPatch, name: str, cap: tuple[int, int]) -> None:
    cuda = types.SimpleNamespace(get_device_name=lambda i: name,
                                 get_device_capability=lambda i: cap)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))


@pytest.mark.parametrize(("name", "cap", "want"), [
    ("NVIDIA GeForce RTX 3060", (8, 6), True),
    ("Tesla V100-PCIE-32GB", (7, 0), True),
    ("Quadro RTX 8000", (7, 5), True),
    ("NVIDIA GeForce GTX 1650", (7, 5), False),
    ("NVIDIA GeForce GTX 1080 Ti", (6, 1), False),
])
def test_auto_za_kartoiu(monkeypatch: pytest.MonkeyPatch, name: str,
                         cap: tuple[int, int], want: bool) -> None:
    _fake_torch(monkeypatch, name, cap)
    got, why = R.pysar_fp16_wanted("auto", "cuda:0")
    assert got is want
    assert name in why


def test_ruchky_i_procesor(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_torch(monkeypatch, "NVIDIA GeForce GTX 1650", (7, 5))
    assert R.pysar_fp16_wanted("on", "cuda:0")[0] is True
    _fake_torch(monkeypatch, "NVIDIA GeForce RTX 3060", (8, 6))
    assert R.pysar_fp16_wanted("off", "cuda:0")[0] is False
    # на процесорі fp16 не буває, навіть примусово
    assert R.pysar_fp16_wanted("on", "cpu")[0] is False
