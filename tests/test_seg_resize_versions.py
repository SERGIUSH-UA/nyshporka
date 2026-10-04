"""Гард версій патча `seg_resize`: мовчить на звірених, кричить на решті.

Звірених torchvision кілька: 0.29.1 ставить `nysh htr install` на kraken
7.1.1, а 0.25 і 0.28 лишаються в середовищах, оновлених на місці (torch там не
перекачується). Якби патч кричав на кожній із них, справжнє розходження версій
тонуло б серед попереджень, яким не було причини.
"""
from __future__ import annotations

import importlib.metadata as md

import pytest

# Як модуль пакета, а не через `sys.path`: тека патчів у шляху імпорту
# змінює поведінку сусідніх тестів (ключ кешу сегментації бачить `seg_ceiling`).
from nyshporka.htr.patches import seg_resize


def _versions(monkeypatch: pytest.MonkeyPatch, **have: str) -> None:
    monkeypatch.setattr(md, "version", lambda pkg: have[pkg])


@pytest.mark.parametrize("tv", ["0.25.0+cu126", "0.25.0+cpu", "0.28.0", "0.29.1+cu126"])
def test_zvireni_versii_movchat(monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str], tv: str) -> None:
    _versions(monkeypatch, kraken="7.1.1", torchvision=tv)
    seg_resize._warn_version_drift()
    assert capsys.readouterr().out == ""


def test_nezvirena_versiia_krychyt(monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    _versions(monkeypatch, kraken="7.1.1", torchvision="0.27.0")
    seg_resize._warn_version_drift()
    out = capsys.readouterr().out
    assert "torchvision 0.27.0" in out and "0.29.1" in out
