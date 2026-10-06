"""📚 Зведення бібліотеки рахує СПРАВИ, а «на диску» — лише справи з кадрами.

Холодний прохід 07.10.2026: бібліотека казала «2512 справ · 2512 на диску»
при 2385 різних справах (решта — теки-фрагменти тих самих справ) і лише 1241
справі з кадрами (решта знята з диска заради місця).
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka.cases import layers as LY


def _rows() -> list[dict[str, Any]]:
    return [
        # одна справа — дві теки-фрагменти
        {"key": "A/1/1/1", "on_disk": True, "frames": 10, "state": "on_disk",
         "htr_stage": "none", "fuzzy_stage": "none"},
        {"key": "A/1/1/1", "on_disk": True, "frames": 5, "state": "on_disk",
         "htr_stage": "none", "fuzzy_stage": "none"},
        # знята з диска: тека є, кадрів немає
        {"key": "A/1/1/2", "on_disk": True, "frames": 0, "state": "archived",
         "htr_stage": "pysar", "fuzzy_stage": "swept"},
        # тека без кадрів і без позначки
        {"key": "A/1/1/3", "on_disk": True, "frames": 0, "state": "on_disk",
         "htr_stage": "none", "fuzzy_stage": "none"},
    ]


def test_cases_not_folders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LY, "has_layers", lambda: True)
    s = LY.summary(_rows())
    assert s["all"] == 3 and s["folders"] == 4
    assert s["frames"] == 15, "кадри рахуються по всіх теках"


def test_on_disk_means_frames_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LY, "has_layers", lambda: True)
    s = LY.summary(_rows())
    assert s["on_disk"] == 1, "тека без кадрів — не «на диску»"
    assert s["offloaded"] == 1, "знята з диска справа названа окремо"


def test_layer_counts_are_per_case_not_per_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LY, "has_layers", lambda: True)
    s = LY.summary(_rows())
    assert s["no_htr"] == 2, "дві теки однієї справи не подвоюють «без декоду»"
    assert s["read"] == 1


def test_without_registry_offloaded_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LY, "has_layers", lambda: False)
    assert LY.summary(_rows())["offloaded"] is None
