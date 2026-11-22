"""Шаблон нормалізації назв і розбір відповіді моделі."""
from __future__ import annotations

import pytest

from nyshporka.opysy import normalize as NZ


def test_prompt_fills_source_and_orthography() -> None:
    p = NZ.prompt("ДАОО, фонд 445, Балтський повітовий суд", "ru_modern")
    assert "ДАОО, фонд 445" in p and "{source}" not in p and "{orthography}" not in p
    assert "⟨?слово⟩" in p and "СУЧАСНОЮ" in p
    assert "як в оригіналі" in NZ.prompt("x", "keep")
    with pytest.raises(ValueError):
        NZ.prompt("x", "uk_modern")  # type: ignore[arg-type]


def test_request_appends_json_array() -> None:
    r = NZ.request("джерело", ["Дело о «крестьянине»"])
    assert r.endswith('["Дело о «крестьянине»"]')


def test_batches_cover_everything_in_order() -> None:
    got = list(NZ.batches([str(i) for i in range(45)]))
    assert [off for off, _ in got] == [0, 20, 40]
    assert sum(len(b) for _, b in got) == 45


def test_parse_strict_length_and_type() -> None:
    assert NZ.parse('ось: ["а", " б "]', 2) == ["а", "б"]
    with pytest.raises(NZ.NormError, match=r"у відповіді 1"):
        NZ.parse('["а"]', 2)
    with pytest.raises(NZ.NormError):
        NZ.parse("[1, 2]", 2)
    with pytest.raises(NZ.NormError):
        NZ.parse("немає масиву", 1)
