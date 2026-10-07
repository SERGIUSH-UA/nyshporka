"""⏸ Стан прогону: дочитано · читається зараз · не дочитано.

Холодний прохід 07.10.2026: на «Огляді» спинений прогін нічим не відрізнявся
від дочитаного, а на «Прогонах» стояв під значком поступу «◐», ніби йде.
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka import htr_store as H


class _Live:
    def __init__(self, case: str) -> None:
        self.case = case


def _rows() -> list[dict[str, Any]]:
    return [{"name": "a", "case_dir": "data/raw/a", "pages_done": 11, "frames": 11},
            {"name": "b", "case_dir": "data/raw/b", "pages_done": 3, "frames": 11},
            {"name": "c", "case_dir": "data/raw/c", "pages_done": 3, "frames": 11},
            {"name": "d", "case_dir": "data/raw/d", "pages_done": 5, "frames": 0,
             "done": True}]


def test_states(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.htr import runs as LIVE

    monkeypatch.setattr(LIVE, "alive", lambda: [_Live("c")])
    rows = _rows()
    H.mark_run_states(rows)
    assert [r["state"] for r in rows] == ["done", "stopped", "reading", "done"]


def test_without_a_live_registry_nothing_claims_to_be_reading(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Реєстр не читається — краще «не дочитано», ніж вигадане «читається»."""
    from nyshporka.htr import runs as LIVE

    def boom() -> list[Any]:
        raise OSError("реєстр зайнято")

    monkeypatch.setattr(LIVE, "alive", boom)
    rows = _rows()
    H.mark_run_states(rows)
    assert "reading" not in {r["state"] for r in rows}
