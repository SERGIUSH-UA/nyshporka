"""Фіча-флаги: функція в пакеті є, але без флагу її не видно."""
from __future__ import annotations

import pytest

from nyshporka import features


@pytest.mark.parametrize("value", ["1", "true", "YES", " on ", "так"])
def test_flag_on_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(features.OPYSY, value)
    assert features.opysy()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "пізніше"])
def test_flag_off_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(features.OPYSY, value)
    assert not features.opysy()


def test_flag_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(features.OPYSY, raising=False)
    assert not features.opysy()


def test_library_imports_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервер бере ворота з пакета — модулі не залежать від флагу."""
    monkeypatch.delenv(features.OPYSY, raising=False)
    from nyshporka.opysy import gates, names, schema  # noqa: F401
