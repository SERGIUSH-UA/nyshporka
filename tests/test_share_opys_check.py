"""Перед заливкою: чи названо той опис — пул і покажчик. Лише підказки.

27.09.2026 сімнадцять книг Нікополя поїхали в Супрягу під оп. 1 замість
оп. 3; під тими номерами в оп. 1 — інші села. Ворота цього не бачать і не
мусять: шифра правильна за формою. Бачить людина — якщо їй показати.
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka.share import opys_check as C

CASE = {"repo": "DADNO", "fond": "193", "opys": "1", "spr": "201",
        "shifra": "ДАДнО 193-1-201", "title": "Нікополь", "years": [1885, 1885]}


class _Cell:
    pass


def test_the_same_number_in_another_opys_in_the_pool_is_named(monkeypatch):
    from nyshporka.share import pool

    monkeypatch.setattr(pool, "by_fond", lambda repo, fond: {
        ("3", "201", ""): _Cell(), ("1", "201", ""): _Cell(), ("3", "202", ""): _Cell()})
    got = C.check(CASE, network=False)
    assert [w["code"] for w in got] == ["pool_other_opys"]
    assert "193-3-201" in got[0]["text"] and "193-3-202" not in got[0]["text"]


def test_no_pool_snapshot_is_silence_not_a_claim(monkeypatch):
    from nyshporka.share import pool

    monkeypatch.setattr(pool, "by_fond", lambda repo, fond: None)
    assert C.check(CASE, network=False) == []


def test_the_index_title_is_shown_next_to_the_card(monkeypatch):
    from nyshporka.share import pool

    monkeypatch.setattr(pool, "by_fond", lambda repo, fond: {})
    seen: list[str] = []

    def card(label: str, fond: str, opys: str, spr: str) -> dict[str, Any]:
        seen.append(f"{label}-{fond}-{opys}-{spr}")
        return {"title": "Екатеринославский уезд с. Волосское Преображенская церковь",
                "years": "1866"}

    monkeypatch.setattr(C, "_duck_card", card)
    got = C.check(CASE, network=True)
    assert seen == ["ДАДнО-193-1-201"]
    assert got[0]["code"] == "pokazhchyk"
    assert "Волосское" in got[0]["text"] and "Нікополь" in got[0]["text"]


def test_without_network_the_index_is_not_asked(monkeypatch):
    from nyshporka.share import pool

    monkeypatch.setattr(pool, "by_fond", lambda repo, fond: {})
    monkeypatch.setattr(C, "_duck_card", lambda *a: pytest.fail("мережа в пакуванні"))
    assert C.check(CASE, network=False) == []


def test_offline_environment_never_reaches_the_index(monkeypatch):
    """Тести й середовища без мережі не стукають у волонтерський сервіс."""
    from nyshporka.sources import http

    monkeypatch.setattr(http, "offline", lambda: True)
    assert C._duck_card("ДАДнО", "193", "1", "201") is None


def test_a_case_without_opys_gets_no_hints():
    assert C.check({**CASE, "opys": ""}, network=True) == []
