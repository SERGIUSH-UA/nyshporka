"""Fuzzy score: чи зовнішній запис відповідає одній з канонічних осіб.

Стратегія — поверхнева транслітерація через `normalize_for_matching` +
`rapidfuzz.WRatio`. Точність свідомо обмежена: ми не претендуємо на ML;
кінцеве слово завжди за людиною у `nysh review`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from nyshporka.models import Person
from nyshporka.utils.translit import normalize_for_matching

# Ваги факторів (сума = 1.0).
_W_SURNAME = 0.4
_W_GIVEN = 0.3
_W_PATRONYMIC = 0.1
_W_YEAR = 0.15
_W_PLACE = 0.05

_YEAR_SIGMA = 3.0


@dataclass
class Score:
    """Підсумковий бал + розбивка по факторах."""

    total: float
    breakdown: dict[str, float]


def _norm(s: str | None) -> str:
    return normalize_for_matching(s or "")


def _string_score(a: str | None, b: str | None) -> float:
    """0..1 на основі WRatio після transliteration."""
    a_n, b_n = _norm(a), _norm(b)
    if not a_n or not b_n:
        return 0.0
    return fuzz.WRatio(a_n, b_n) / 100.0


def _year_score(year: int | None, person_year: int | None) -> float:
    """Gaussian: 1.0 при збігу, ≈0.61 при σ=3 років, →0 далі."""
    if year is None or person_year is None:
        return 0.0
    diff = year - person_year
    return math.exp(-(diff**2) / (2 * _YEAR_SIGMA**2))


def _place_score(place_a: str | None, place_b: str | None) -> float:
    """Спрощено — fuzzy на нормованих назвах."""
    return _string_score(place_a, place_b)


def score_record(record: dict[str, Any], person: Person) -> Score:
    """Обчислити збіг extracted-запису з canonical-особою.

    `record` (Geneteka/FamilySearch) має поля:
    - given_name, surname, patronymic (optional), birth_year (int)
    - birth_place (string)
    """
    primary = next((n for n in person.names if n.primary), person.names[0])

    surname = _string_score(record.get("surname"), primary.surname)
    given = _string_score(record.get("given_name"), primary.given)
    # 🔴 Порівнювати по батькові нема З чим: канонічна особа несе лише
    # `given`/`surname`, поля патроніма в `NameVariant` немає. Було
    # `_string_score(record["patronymic"], None)` — а це завжди 0.0, при тому
    # що вага 0.1 застосовувалась саме тоді, коли патронім у записі Є. Тобто
    # запис із по батькові виходив на 10% слабшим за той самий запис без нього,
    # і при порозі перегляду 0.6 з черги випадав найінформативніший із двох.
    # Доки поля немає, фактор не бере участі в оцінці взагалі.
    patronymic_comparable = False
    patronymic = 0.0

    person_birth_year = _extract_person_birth_year(person)
    year = _year_score(record.get("birth_year"), person_birth_year)
    place = _place_score(record.get("birth_place"), _extract_person_birth_place(person))

    breakdown = {
        "surname": surname,
        "given": given,
        "patronymic": patronymic,
        "year": year,
        "place": place,
    }
    # Вага фактора, який не порівнювався, перерозподіляється пропорційно на
    # ім'я й прізвище: інакше недоступне поле штрафувало б повний збіг по решті.
    weights = {
        "surname": _W_SURNAME,
        "given": _W_GIVEN,
        "patronymic": _W_PATRONYMIC if patronymic_comparable else 0.0,
        "year": _W_YEAR,
        "place": _W_PLACE,
    }
    if not patronymic_comparable:
        leftover = _W_PATRONYMIC
        weights["surname"] += leftover * (_W_SURNAME / (_W_SURNAME + _W_GIVEN))
        weights["given"] += leftover * (_W_GIVEN / (_W_SURNAME + _W_GIVEN))

    total = sum(breakdown[k] * weights[k] for k in breakdown)
    return Score(total=total, breakdown=breakdown)


def _extract_person_birth_year(person: Person) -> int | None:
    for f in person.facts:
        if f.type == "birth" and f.date and f.date.value[:4].isdigit():
            return int(f.date.value[:4])
    return None


def _extract_person_birth_place(person: Person) -> str | None:
    """Локально лишимо просту версію — `place_id` без resolve у Place.name.

    Якщо матчер у майбутньому отримає мапу `place_id → Place.name`, ми можемо
    замінити це на повне ім'я. Поки що повертаємо `place_id` як рядок.
    """
    for f in person.facts:
        if f.type == "birth" and f.place_id:
            return f.place_id
    return None
