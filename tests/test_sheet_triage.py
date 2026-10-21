"""Відсів карток гортача: закривається лише не-прізвище, відоме згортається, решта — людині.

Родина вигадана (Вербицькі-Ковальчуки села Тихий Брід) — правило публічного пакета.
"""
from __future__ import annotations

from nyshporka.search import triage as TR


def card(text: str, matched: str, *, before: list[str] | None = None,
         after: list[str] | None = None, alt: str = "", page: str = "0001.jpg") -> dict:
    return {"text": text, "matched": matched, "before": before or [], "after": after or [],
            "alt": alt, "page": page}


STEMS = ["Ковальчинский"]
NONE = TR.Known()


def code(c: dict, known: TR.Known = NONE) -> str | None:
    got = TR.classify(c, known, STEMS)
    return got[0] if got else None


def test_name_in_children_list_is_closed() -> None:
    c = card("дѣтей, Томаша, Виктора, Ковальчинъ, Ку-", "Ковальчинъ")
    assert code(c) == TR.CLOSED


def test_numbered_daughters_across_lines_are_closed() -> None:
    c = card("2. Ковальчина", "Ковальчина", before=["Матвѣя дочери. 1 Анна"])
    assert code(c) == TR.CLOSED


def test_son_with_surname_is_not_closed() -> None:
    # «сынъ Иванъ Х-скій» — ім'я з прізвищем, не перелік: розділювача немає.
    assert code(card("сынъ Иванъ Ковальчинскій", "Ковальчинскій")) is None


def test_name_with_patronymic_before_comma_is_not_a_list() -> None:
    # «Иванъ Петровъ» без коми між ними — особа, тож кома перед прізвищем
    # не робить його пунктом переліку імен.
    assert code(card("сынъ Иванъ Петровъ, Ковальчинскій", "Ковальчинскій")) is None


def test_daughter_with_surname_carried_to_next_line_is_not_closed() -> None:
    # 🔴 межа рядка — не кома: «дочь Марія ⏎ Х-ская» несе прізвище.
    c = card("Ковальчинская", "Ковальчинская", before=["Его дочь Марія"])
    assert code(c) is None


def test_wife_is_not_a_kin_list() -> None:
    c = card("жена его, Марія, Ковальчинская", "Ковальчинская")
    assert code(c) is None


def test_first_item_after_kin_word_is_not_closed() -> None:
    # Між спорідненістю й хітом жодного пункту — це може бути й прізвище.
    assert code(card("дочь, Ковальчинская", "Ковальчинская")) is None


def test_toponym_is_closed() -> None:
    assert code(card("села Ковальчинъ уѣзда Тихобродскаго", "Ковальчинъ")) == TR.CLOSED


def test_short_token_is_closed() -> None:
    assert code(card("щинскій Ков", "Ков")) == TR.CLOSED


def test_garbled_form_is_never_closed_by_its_shape() -> None:
    # Чуже на вигляд слово без контексту — людині, а не в «закрито».
    assert code(card("Ковалищиканскаго Дворяни", "Ковалищиканскаго")) is None


def test_page_known_to_canon_or_eye_is_known() -> None:
    kn = TR.Known(pages={"0034": "аркуш цитує канон"})
    assert code(card("Адамъ Ковальчинскій", "Ковальчинскій", page="0034.JPG"), kn) == TR.KNOWN


def test_canon_person_name_in_window_is_known() -> None:
    kn = TR.Known(names={"adam": "Адам I9001"})
    c = card("щинскій съ нев", "щинскій", before=["Адамъ Коваль"])
    got = TR.classify(c, kn, STEMS)
    assert got and got[0] == TR.KNOWN and "I9001" in got[1]


def test_clergy_signature_with_tied_person_is_known() -> None:
    kn = TR.Known(tied=["Адам I9001"])
    got = TR.classify(card("Ковальчинскій съ псаломщикомъ", "Ковальчинскій"), kn, STEMS)
    assert got and got[0] == TR.KNOWN and "I9001" in got[1]


def test_clergy_word_without_tied_person_goes_to_verdict() -> None:
    # Ніхто з роду не пов'язаний зі справою — підпис може бути новою людиною.
    assert code(card("Ковальчинскій съ псаломщикомъ", "Ковальчинскій")) is None


def test_family_act_near_clergy_word_goes_to_verdict() -> None:
    # 🔴 «сынъ псаломщика Х-скаго» — акт родини, не підпис: людині.
    kn = TR.Known(tied=["Ѳеодор I9002"])
    c = card("сынъ псаломщика Ѳеодора Ковальчинскаго", "Ковальчинскаго")
    assert code(c, kn) is None


def test_glued_hit_from_previous_line_is_not_weak() -> None:
    # Склейка «Х-скій ⏎ Стоматовскій»: прізвища в рядку хіта немає, тож другий
    # голос цього рядка нічого не каже про прізвище.
    c = card("Стоматовскій", "Ковальчинскій-Стоматовск", before=["Ковальчинскій"],
             alt="Стоматовскій")
    assert code(c) is None


def test_closed_wins_over_known() -> None:
    kn = TR.Known(pages={"0001": "аркуш цитує канон"})
    assert code(card("дѣтей, Томаша, Ковальчинъ", "Ковальчинъ"), kn) == TR.CLOSED


def test_second_voice_reading_something_else_is_weak() -> None:
    c = card("Руды, ⏎ Ковальчейская, Но), Шмейхель;", "Ковальчейская",
             alt="кмсіске, (но, Шмейхель,")
    assert code(c) == TR.WEAK


def test_second_voice_agreeing_keeps_card_for_verdict() -> None:
    c = card("Петръ Ковальчинскій", "Ковальчинскій", alt="Петра Ковальчинскаго")
    assert code(c) is None


def test_triage_counts_and_marks_every_card() -> None:
    cards = [card("дѣтей, Томаша, Ковальчинъ", "Ковальчинъ"),
             card("Петръ Ковальчинскій", "Ковальчинскій")]
    counts = TR.triage(cards, "Ковальчинский", "", STEMS, known=NONE)
    assert counts == {TR.CLOSED: 1, TR.KNOWN: 0, TR.WEAK: 0}
    assert cards[0]["triage"]["code"] == TR.CLOSED and cards[1]["triage"] is None


def test_child_named_like_known_person_goes_to_verdict() -> None:
    # «сынъ Адамъ Х-скій» — новий Адам, не відомий парох.
    kn = TR.Known(names={"adam": "Адам I9001"}, tied=["Адам I9001"])
    assert code(card("сынъ Адамъ Ковальчинскій", "Ковальчинскій"), kn) is None


def test_garbled_known_name_still_recognised() -> None:
    kn = TR.Known(names={"adam": "Адам I9001"})
    assert code(card("Священн Аданъ Ковальчинскій", "Ковальчинскій"), kn) == TR.KNOWN


def test_spouse_word_from_neighbour_column_does_not_block_signature() -> None:
    # Рядок декоду таблиці змішує графи: «жена» з графи батьків — не про підпис.
    kn = TR.Known(tied=["Адам I9001"])
    c = card("Ковальчинскій", "Ковальчинскій",
             before=["Петра Макаренка жена Ксенія Онуфріева Стоматовскимъ"],
             after=["Того же села крестьяне: Свящ. Адамъ"])
    assert code(c, kn) == TR.KNOWN


def test_family_word_ending_previous_line_still_blocks() -> None:
    kn = TR.Known(tied=["Ѳеодор I9002"])
    c = card("Ковальчинскаго", "Ковальчинскаго", before=["сынъ псаломщика Ѳеодора"])
    assert code(c, kn) is None


def test_toponym_on_next_line_does_not_close_signature() -> None:
    # 🔴 «Псаломщикъ Ѳеодоръ Х-скій ⏎ Бессарабской Губерніи» — підпис і новий запис.
    c = card("Тихобродской Губерніи Города", "Ковальчинскій-Тихоброд",
             before=["Псаломщикъ Ѳеодоръ Ковальчинскій"])
    assert code(c) != TR.CLOSED


def test_name_split_across_lines_without_hyphen_keeps_the_list() -> None:
    c = card("Ку-", "Ковальчинъ-Ку", before=["дѣтей, Томаша, Во", "ктора, Ковальчинъ,"])
    assert code(c) == TR.CLOSED


def test_count_of_female_births_does_not_count_as_wife() -> None:
    # «женска шесть» (рушій: «женека») — лічба народжених, не «жена».
    kn = TR.Known(tied=["Адам I9001"])
    c = card("Ковальчинскій", "Ковальчинскій", before=["пять (5) и женека шесть (6)"],
             after=["Того же села крестьяне: Священникъ"])
    assert code(c, kn) == TR.KNOWN


def test_similar_name_with_other_first_letter_is_not_the_known_person() -> None:
    kn = TR.Known(names={"anna": "Анна I9003"})
    assert code(card("Жанна Ковальчинская", "Ковальчинская"), kn) is None


# ── знахідки рецензії 21.10.2026 ─────────────────────────────────────────────

def test_family_act_on_known_page_goes_to_verdict() -> None:
    # Аркуш уже в сховищі (`partial`) не робить відомими всіх людей на ньому.
    kn = TR.Known(pages={"0034": "аркуш уже у сховищі"})
    c = card("сынъ Адамъ Ковальчинскій", "Ковальчинскій", page="0034.jpg")
    assert code(c, kn) is None


def test_father_word_blocks_known_name() -> None:
    kn = TR.Known(names={"feodor": "Ѳеодор I9002"})
    assert code(card("отецъ Ѳеодоръ Ковальчинскій", "Ковальчинскій"), kn) is None


def test_known_name_far_from_hit_does_not_fold() -> None:
    # Ім'я відомої особи за два рядки від хіта — інша графа, не підпис.
    kn = TR.Known(names={"adam": "Адам I9001"})
    c = card("Петръ Ковальчинскій", "Ковальчинскій", before=["Адамъ Стоматовскій", "крестьяне"])
    assert code(c, kn) is None


def test_place_two_words_after_surname_is_not_a_toponym() -> None:
    assert code(card("Адамъ Ковальчинскій Тихобродскаго уѣзда", "Ковальчинскій")) is None


def test_surname_after_surname_is_not_a_toponym() -> None:
    # «gub» префіксом ловив «Губаренко».
    assert code(card("Ковальчинскій Губаренко", "Ковальчинскій")) is None


def test_son_name_comma_surname_is_not_a_list() -> None:
    assert code(card("сынъ Иванъ, Ковальчинскій", "Ковальчинскій")) is None


def test_year_is_not_a_list_separator() -> None:
    assert code(card("сынъ Иванъ 1802 Ковальчинскій", "Ковальчинскій")) is None


def test_surname_like_kin_prefix_does_not_block_signature() -> None:
    # «Синицкій» — прізвище, не «сынъ»: префікс «sin» більше не спорідненість.
    kn = TR.Known(tied=["Адам I9001"])
    c = card("Синицкій Ковальчинскій съ псаломщикомъ", "Ковальчинскій")
    assert code(c, kn) == TR.KNOWN


def test_surname_like_clergy_word_is_not_a_signature() -> None:
    # «Дацюкъ», «Пономаревъ» — прізвища, не «дьячокъ», «пономарь».
    kn = TR.Known(tied=["Адам I9001"])
    assert code(card("Дацюкъ и Ковальчинскій Пономаревъ", "Ковальчинскій"), kn) is None


def test_comma_at_line_end_carries_to_next_line() -> None:
    c = card("Ковальчинъ, Ку-", "Ковальчинъ", before=["дѣтей, Томаша,", "Виктора,"])
    assert code(c) == TR.CLOSED


def test_lines_without_word_end_are_not_glued() -> None:
    # «Иванъ, ⏎ дочь …» — кома в кінці, склеювати не можна.
    c = card("дочь Марія Ковальчинская", "Ковальчинская", before=["сынъ Иванъ,"])
    assert code(c) is None


def test_short_query_surname_is_not_an_empty_token() -> None:
    c = card("Петръ Бут", "Бут")
    assert TR.classify(c, NONE, ["Бут"]) is None


def test_query_itself_is_never_closed_as_empty_token() -> None:
    """«Щеб» — три літери, у нормі чотири: коротким запитом не вважався, а порожнім
    токеном — так, і точний збіг із запитом ішов у «закрито» (рецензія 22.10.2026)."""
    c = card("Петръ Щеб", "Щеб")
    assert TR.classify(c, NONE, ["Щеб"]) is None
    assert TR.classify(c, NONE, [TR._norm("Щеб")]) is None


def test_short_second_stem_of_the_query_is_not_closed() -> None:
    """Короткий запит другим стемом («Бут» після довгого написання) — сам запит, не «закрито»."""
    c = card("Петръ Бут", "Бут")
    assert TR.classify(c, NONE, ["Ковальчинскій", "Бут"]) is None
    assert TR.classify(card("щинскій Ков", "Ков"), NONE, ["Ковальчинскій", "Бут"]) == (
        TR.CLOSED, "порожній токен «Ков»")
