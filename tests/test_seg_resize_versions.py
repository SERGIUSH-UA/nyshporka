"""Гард версій патча `seg_resize`: мовчить на звірених, кричить на решті.

Доти звіреною значилась лише torchvision 0.28, а `nysh htr install` ставить
0.25 (kraken 7.0.2 тримає torch ≤ 2.10). Тож кожен звичайний прогін друкував
попередження, якому не було причини, і справжнє розходження версій тонуло б
серед них.
"""
from __future__ import annotations

import importlib.metadata as md

import pytest

# Як модуль пакета, а не через `sys.path`: тека патчів у шляху імпорту
# змінює поведінку сусідніх тестів (ключ кешу сегментації бачить `seg_ceiling`).
from nyshporka.htr.patches import seg_resize


def _versions(monkeypatch: pytest.MonkeyPatch, **have: str) -> None:
    monkeypatch.setattr(md, "version", lambda pkg: have[pkg])


@pytest.mark.parametrize("tv", ["0.25.0+cu126", "0.25.0+cpu", "0.28.0"])
def test_zvireni_versii_movchat(monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str], tv: str) -> None:
    _versions(monkeypatch, kraken="7.0.2", torchvision=tv)
    seg_resize._warn_version_drift()
    assert capsys.readouterr().out == ""


def test_nezvirena_versiia_krychyt(monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    _versions(monkeypatch, kraken="7.0.2", torchvision="0.27.0")
    seg_resize._warn_version_drift()
    out = capsys.readouterr().out
    assert "torchvision 0.27.0" in out and "0.25.0, 0.28.0" in out
