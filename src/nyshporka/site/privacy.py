"""Редакція канонічних даних для публічного рендеру (docs/).

Canonical зберігає **повні** факти живих осіб. Це джерело істини для родини.
У docs/ потрапляє відредагована версія: точні дати → десятиліття, медіа
прибирається, наратив (notes) замінюється на маркер «дані приховані».

Канон лишається повним; редакція захищає від випадкової публікації приватної
збірки.
"""

from __future__ import annotations

from nyshporka.models import Fact, Person


def redact_person(p: Person) -> Person:
    """Повернути копію Person з редагованими полями для приватних осіб."""
    if not p.private:
        return p
    return p.model_copy(
        update={
            "facts": [_redact_fact(f) for f in p.facts],
            "media": [],
            "notes": "_Особисті дані приховані для захисту приватності._",
        }
    )


def _redact_fact(f: Fact) -> Fact:
    if f.date is None:
        return f
    new_date = f.date.model_copy(
        update={
            "value": _to_decade(f.date.value),
            "precision": "decade",
            "range_end": None,
        }
    )
    return f.model_copy(update={"date": new_date})


def _to_decade(value: str) -> str:
    head = value.split("-")[0]
    try:
        year = int(head)
    except ValueError:
        return value
    return f"{year // 10 * 10}"
