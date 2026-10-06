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


def test_tree_links_are_refused_even_in_a_reading() -> None:
    """Текст документа не перевіряється на «родинне», але посилання на особу
    дерева в документі бути не може — це завжди нотатка дослідника."""
    entry = {"kind": "reading", "page": "0031", "text": "Прухницкая",
             "was": {"text": "див. [[Іван Коваль]]"}}
    assert _rules(entry) == ["tree_links"]


def test_research_fields_never_ride_along() -> None:
    assert "private_keys" in _rules({"kind": "about", "text": "опис", "comment": "x"})


def test_a_retraction_always_passes() -> None:
    assert check_note({"retracts": "abc", "kind": "note"}).passed


@pytest.mark.parametrize("source", [
    "правнук его Иван 5 лет",
    "Отец наш Феодор просит",
    "сестра моя Анна свидѣтельствую",
    "братія наша и мой сын Петро",
])
def test_a_verified_reading_is_the_documents_own_words(source: str) -> None:
    """🔴 Звірене читання — текст ДОКУМЕНТА: ревізії, прохання, свідчення."""
    assert check_note({"kind": "reading", "page": "0031", "text": source,
                       "was": {"text": source}}).passed


@pytest.mark.parametrize("text", [
    "Mój dziadek mieszkał w tej wsi",
    "my great-grandfather was baptised here",
    "тут жив мій син Петро",
    "запис про мою дружину",
])
def test_family_notes_in_other_languages_and_kin(text: str) -> None:
    assert _rules({"kind": "about", "text": text}) == ["personal"]


def test_sheet_numbers_are_not_a_phone_but_a_labelled_number_is() -> None:
    assert check_note({"kind": "about", "text": "аркуші 093 125 12 11 переплутані"}).passed
    assert _rules({"kind": "about", "text": "тел. 093 125 12 11"}) == ["contact"]


@pytest.mark.parametrize("entry", [
    {"kind": "catalog-error", "field": {"a": 1}, "actually": "x"},
    {"kind": "copy", "other": "x", "relation": ["a"]},
    {"kind": "reading", "page": "мій прадід Іван", "text": "x"},
    {"kind": "reading", "page": "0031", "text": "x", "line": {"run": "r", "line_no": "3"}},
    {"kind": "about", "text": "x", "model": "my grandfather phone"},
    {"kind": "about", "text": 5},
])
def test_malformed_fields_are_refused_by_name(entry: dict) -> None:
    """Об'єкт замість рядка клав сторінку книги в 500 (перевірка 0.26.0)."""
    assert "shape" in _rules(entry)
