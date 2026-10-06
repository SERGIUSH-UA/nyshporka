"""🚦 Ворота запису нотатника: загальне знання про справу їде, особисте — ні.

Ті самі ворота стоять і в пулі (він пінить пакет), тож хибна відмова тут —
це загальне знання, яке людина не змогла віддати, а хибний пропуск — родинна
нотатка в публічному каталозі.
"""
from __future__ import annotations

import pytest

from nyshporka.share.gates import check_note


def _rules(entry: dict) -> list[str]:
    return [d["rule"] for d in check_note(entry).refusal_details]


@pytest.mark.parametrize("text", [
    "тут записаний мій дід",
    "Прабаба моя Марія, донька Івана",
    "це прабаба Миколи",
    "нашого роду тут немає",
    "мого прадіда хрестили 1834",
    "здесь мой дед",
])
def test_family_notes_are_refused(text: str) -> None:
    assert _rules({"kind": "about", "text": text}) == ["personal"]


@pytest.mark.parametrize("text", [
    "Метрична книга Покровської церкви, роки 1850-1860 1870",
    "копія в консисторії: ДАВіО 904-24-54",
    "у ревізії дід записаний як однодворець",
    "наші матеріали з цієї справи: аркуші 31зв–45",
    "архів подає 1834, а книга веде 1834–1836",
])
def test_general_knowledge_passes(text: str) -> None:
    assert check_note({"kind": "about", "text": text}).passed


def test_a_personal_kind_never_passes() -> None:
    assert _rules({"kind": "note", "text": "будь-що"}) == ["note_private_kind"]


def test_tree_links_and_contacts_are_refused() -> None:
    assert "tree_links" in _rules({"kind": "about", "text": "див. [[Іван Коваль]]"})
    assert "contact" in _rules({"kind": "about", "text": "пишіть на a.b@example.org"})
    assert "contact" in _rules({"kind": "about", "text": "тел. +380 67 123 45 67"})


def test_the_engine_reading_is_checked_too() -> None:
    entry = {"kind": "reading", "page": "0031", "text": "Прухницкая",
             "was": {"text": "мій дід Пухтицкій"}}
    assert _rules(entry) == ["personal"]


def test_research_fields_never_ride_along() -> None:
    assert "private_keys" in _rules({"kind": "about", "text": "опис", "comment": "x"})


def test_a_retraction_always_passes() -> None:
    assert check_note({"retracts": "abc", "kind": "note"}).passed
