"""Гнізда імен: латинські й галицькі форми, і те, що старі ключі не зсунулись.

🔴 `norm_given` — ключ зводу осіб і якорів. Нова форма в гнізді безпечна, а нове
гніздо, що відібрало форму в старого, мовчки перероблює канонічні ключі всіх
осіб: тож тут стережеться, що жодна форма не стоїть у двох гніздах і що
ключі відомих форм ті самі, що були до розширення.
"""
from __future__ import annotations

import pytest

from nyshporka.records import names as N
from nyshporka.utils.translit import normalize_archival as norm


def test_no_form_belongs_to_two_nests() -> None:
    seen: dict[str, str] = {}
    for key, variants in N._ALIASES.items():
        for form in {norm(key), *(norm(v) for v in variants)}:
            owner = seen.setdefault(form, norm(key))
            assert owner == norm(key), f"«{form}» у гніздах {owner} і {norm(key)}"


#: Ключі, зняті ДО розширення гнізд (norm_given відомих форм).
OLD_KEYS = {
    "Іоаннъ": "ivan", "Ѳеодоръ": "fedor", "Осип": "iosif", "Григорій": "grigorii",
    "Явдоха": "evdokia", "Михайло": "mihail", "Микола": "nikolai", "Степан": "stefan",
    "Тетяна": "tatana", "Настя": "anastasia", "Параска": "paraskeva", "Олексій": "aleksei",
    "Катерина": "ekaterina", "Петро": "petr", "Прокопій": "prokop", "Ілля": "ila",
    "Софія": "sofia", "Дмитро": "dmitrii",
}


@pytest.mark.parametrize(("form", "key"), sorted(OLD_KEYS.items()))
def test_old_canonical_keys_do_not_move(form: str, key: str) -> None:
    assert N.norm_given(form) == key


@pytest.mark.parametrize("latin", [
    "Georgius", "Gregorius", "Michael", "Michaël", "Joannes", "Nicolaus", "Stephanus",
    "Demetrius", "Basilius", "Petrus", "Theodorus", "Alexius", "Lucas", "Elias",
    "Procopius", "Parascevia", "Eudoxia", "Catharina", "Theodosia", "Sophia", "Tatianna",
])
def test_latin_forms_join_their_nest(latin: str) -> None:
    assert N.known_given(latin), latin
    assert N.norm_given(latin) != norm(latin)


@pytest.mark.parametrize(("a", "b"), [
    ("Юрко", "Georgius"), ("Юрій", "Jerzy"), ("Гринь", "Григорій"), ("Гриць", "Gregorius"),
    ("Michaël", "Михайло"), ("Параня", "Параскевія"), ("Феся", "Теодозія"),
    ("Кася", "Катерина"), ("Олекса", "Alexius"), ("Ілько", "Ілля"), ("Євдоха", "Eudoxia"),
    ("Матвій", "Matthaeus"), ("Матвій", "Mathaeus"), ("Матвей", "Matheus"),
    ("Пантелеймон", "Pantaleon"), ("Яким", "Joachimus"), ("Остап", "Eustachius"),
    ("Гнат", "Ignatius"), ("Сидір", "Isidorus"), ("Захар", "Zacharias"), ("Корній", "Cornelius"),
    ("Кирило", "Cyrillus"), ("Ярема", "Jeremias"), ("Хівря", "Febronia"), ("Розалія", "Rosalia"),
    ("Єва", "Ewa"),
])
def test_galician_and_latin_forms_are_one_name(a: str, b: str) -> None:
    assert N.norm_given(a) == N.norm_given(b)
    assert set(N.expand_given(a)) == set(N.expand_given(b))


def test_a_diaeresis_form_is_found_by_the_plain_one() -> None:
    assert N.norm_given("Michaël") == N.norm_given("Michael")


def test_the_three_letter_form_is_not_in_a_nest() -> None:
    """«Jur» коротший за поріг порівняння й лише додавав би шум у стеми."""
    assert not N.known_given("Jur")
