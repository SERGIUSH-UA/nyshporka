"""Доставка плану заходу переживає обрив мережі на машині людини.

Підстава — лист 20.10.2026: ноутбук вийшов з мережі, друга черга партії не
стартувала з «план заходу не доставився», а повтор тієї самої команди все
дочитав. Повтор безпечний: залите раніше вдруге не їде.
"""
from __future__ import annotations

import pytest

from nyshporka.cloud import supervised as SUP


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Стан мережі по черзі опитувань; останній повторюється."""
    monkeypatch.delenv("NYSHPORKA_NO_NETWORK", raising=False)
    monkeypatch.setattr(SUP.time, "sleep", lambda _s: None)
    states: list[bool] = [True]

    def up(timeout: float = 5.0) -> bool:
        return states.pop(0) if len(states) > 1 else states[0]

    monkeypatch.setattr(SUP, "_net_up", up)
    return states


def _step(results: list[bool], calls: list[int]):
    def step() -> bool:
        calls.append(1)
        return results.pop(0)
    return step


def test_a_step_that_failed_while_offline_is_repeated_when_the_net_returns(
        net: list[bool]) -> None:
    net[:] = [False, False, True]
    calls: list[int] = []
    said: list[str] = []
    assert SUP._with_net_retry(_step([False, True], calls), "доставка плану",
                               lambda *a: said.append(a[-1]))
    assert len(calls) == 2
    assert any("мережі немає" in s for s in said)


def test_a_real_failure_with_the_net_up_gives_up_after_the_attempts(net: list[bool]) -> None:
    calls: list[int] = []
    assert not SUP._with_net_retry(_step([False] * 5, calls), "доставка плану",
                                   lambda *a: None)
    assert len(calls) == SUP.STAGE_ATTEMPTS


def test_the_net_that_never_returns_ends_the_wait(net: list[bool],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    net[:] = [False]
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(SUP.time, "monotonic", lambda: float(next(clock)))
    calls: list[int] = []
    said: list[str] = []
    assert not SUP._with_net_retry(_step([False, True], calls), "доставка плану",
                                   lambda *a: said.append(a[-1]))
    assert len(calls) == 1, "без мережі повтор марний"
    assert any("не повернулась" in s for s in said)


def test_no_retry_where_the_network_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    monkeypatch.setattr(SUP, "_net_up", lambda timeout=5.0: pytest.fail("мережу не питати"))
    calls: list[int] = []
    assert not SUP._with_net_retry(_step([False, True], calls), "x", lambda *a: None)
    assert len(calls) == 1
