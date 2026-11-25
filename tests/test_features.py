"""Фіча-флаги: функція в пакеті є, але без флагу її не видно."""
from __future__ import annotations

import pytest

from nyshporka import features


@pytest.mark.parametrize("value", ["1", "true", "YES", " on ", "так"])
def test_flag_on_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(features.OPYSY, value)
    assert features.opysy()


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "ні"])
def test_flag_off_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(features.OPYSY, value)
    assert not features.opysy()


@pytest.mark.parametrize("value", [None, "", "пізніше"])
def test_launched_flag_on_unless_explicitly_off(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """Засіки запущено в 0.49.0: без змінної, порожня чи невідоме значення — увімкнено (вимикає лише
    явне «0/false/no/off/ні»)."""
    if value is None:
        monkeypatch.delenv(features.OPYSY, raising=False)
    else:
        monkeypatch.setenv(features.OPYSY, value)
    assert features.opysy()


def test_unlaunched_flag_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Флаг поза `DEFAULT_ON` вмикає лише явне значення."""
    monkeypatch.delenv("NYSH_PROBA_FLAGU", raising=False)
    assert not features.enabled("NYSH_PROBA_FLAGU")
    monkeypatch.setenv("NYSH_PROBA_FLAGU", "пізніше")
    assert not features.enabled("NYSH_PROBA_FLAGU")


def test_library_imports_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервер бере ворота з пакета — модулі не залежать від флагу."""
    monkeypatch.delenv(features.OPYSY, raising=False)
    from nyshporka.opysy import gates, names, schema  # noqa: F401
