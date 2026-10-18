"""📓 Звірене оком ОДНЕ слово рядка (`note read --word`).

Людина здебільшого звіряє прізвище чи по батькові, а не весь рядок дослівно
(відгук 18.10.2026). Запис тоді — рядок рушія з цим словом, і в трен він іде
лише тоді, коли слово складне (рішення дослідника того ж дня).
"""
from __future__ import annotations

import pytest

from nyshporka.ops_notebook import with_word
from nyshporka.pagestore.models import CaseNote
from nyshporka.pagestore.notebook import wire_note
from nyshporka.share.gates import check_note
from nyshporka.train.notes import hard_word

ENGINE = "Ѳедоръ Саенко сынъ Ивановъ"


def test_the_word_takes_the_place_of_the_closest_one() -> None:
    text, word = with_word(ENGINE, "Саєнко")
    assert text == "Ѳедоръ Саєнко сынъ Ивановъ"
    assert word == {"index": 2, "text": "Саєнко"}


def test_an_explicit_index_wins() -> None:
    text, word = with_word(ENGINE, "Иоанновъ", 4)
    assert text.endswith("Иоанновъ") and word["index"] == 4


@pytest.mark.parametrize("engine, word, index", [
    ("", "Саєнко", 0),                 # рушій нічого не прочитав
    (ENGINE, "Саєнко", 9),             # такого слова немає
    ("Іван Іван", "Іванъ", 0),          # двозначно — не вгадуємо
    (ENGINE, "Шпак", 0),                # нічого схожого
])
def test_doubt_is_a_refusal_with_the_words_listed(engine: str, word: str,
                                                  index: int) -> None:
    with pytest.raises(ValueError):
        with_word(engine, word, index)


def _note(word: str, index: int, engine: str = ENGINE) -> CaseNote:
    text, w = with_word(engine, word, index)
    return CaseNote.model_validate({
        "kind": "reading", "page": "0031", "text": text, "word": w,
        "line": {"run": "r", "line_no": 3, "bbox": [1, 2, 3, 4]},
        "was": {"run": "r", "text": engine}, "reader": "human"})


def test_the_word_travels_to_the_pool_and_passes_the_gate() -> None:
    entry = wire_note(_note("Саєнко", 2))
    assert entry["word"] == {"index": 2, "text": "Саєнко"}
    assert check_note(entry).passed


def test_a_malformed_word_is_refused_at_the_gate() -> None:
    entry = wire_note(_note("Саєнко", 2))
    entry["word"] = {"index": 0, "text": ""}
    assert not check_note(entry).passed


def test_only_a_hard_word_goes_to_training() -> None:
    assert hard_word(_note("Саєнко", 2)), "довге й рушій помилився"
    assert not hard_word(_note("сынь", 3)), "коротке слово — лише в нотатнику"
    assert not hard_word(_note("Саенко", 2)), "рушій прочитав так само — нічого нового"
    whole = CaseNote.model_validate({"kind": "reading", "page": "0031", "text": ENGINE})
    assert hard_word(whole), "звірений цілий рядок іде в трен як і досі"


def test_a_pool_entry_with_an_easy_word_is_not_a_training_line() -> None:
    from nyshporka.train.notes import _pool_hard_word

    easy = wire_note(_note("сынь", 3))
    hard = wire_note(_note("Саєнко", 2))
    assert not _pool_hard_word(easy)
    assert _pool_hard_word(hard)
    assert _pool_hard_word({"text": ENGINE}), "цілий рядок — як і досі"
