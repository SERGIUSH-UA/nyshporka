"""Чисті правила над текстом мітки: маркери, белькіт, нормалізація."""
from __future__ import annotations

import pytest

from nyshporka.train import text as T


def test_conflict_marks_keep_the_first_variant() -> None:
    assert T.strip_conflict_marks("Николай ‹Ивановъ|Ивановь› сынъ") == "Николай Ивановъ сынъ"
    assert T.strip_conflict_marks("без маркерів") == "без маркерів"
    assert T.has_conflict_marks("а|б") and not T.has_conflict_marks("аб")


@pytest.mark.parametrize("line,babble", [
    ("по тому объ обу объ", True),          # повтор коротких — рушій ходить по колу
    ("Въ селѣ Ходъ", False),                 # законний уривок без повтору
    ("Итого 12 душъ мужеска", False),        # цифра — комірка формуляра
    ("Николай Ивановъ Петрушенко сынъ", False),  # є слово ≥5 літер
    ("а а", False),                          # менше трьох токенів
])
def test_babble_detector(line: str, babble: bool) -> None:
    assert T.is_babble(line) is babble


def test_loose_norm_folds_pre_reform_letters() -> None:
    assert T.norm_loose("Ѳеодоръ  Ивановъ") == "феодор иванов"
    assert T.norm_strict("Ѳеодоръ  Ивановъ") == "Ѳеодоръ Ивановъ"
    assert T.unify_i("Iванъ") == "Іванъ"
