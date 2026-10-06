"""➡ Порада «далі» несе запит: «Каталоги →» з картки села відкриваються з селом.

Холодний прохід 07.10.2026: газетир радив пошукати, де взяти справи села, а
кнопка відкривала порожнє поле — назву людина набирала вдруге. І в рядках
газетира не було видно, чий це архів: лише ім'я паку «geog-cdiak» унизу.
"""
from __future__ import annotations

import pytest

from nyshporka.catalog.query import _tag, pack_archive
from nyshporka.core.envelope import NextStep, ok
from nyshporka.ops_catalog import _place_word


def test_args_travel_in_the_envelope_and_in_the_text() -> None:
    env = ok({}).suggest("catalog.search", "де взяти справи", args={"q": "Липовеньке"})
    d = env.as_dict()["next"][0]
    assert d["args"] == {"q": "Липовеньке"}
    assert "q='Липовеньке'" in env.as_agent_text()


def test_a_step_without_args_stays_as_it_was() -> None:
    d = NextStep("geog.card", "подивитись").as_dict()
    assert "args" not in d


@pytest.mark.parametrize(("raw", "word"), [
    ("Липовеньке, с.", "Липовеньке"),
    ("Вірмени (Армяни), с.", "Вірмени"),
    ("Антонівка с.", "Антонівка"),
    ("Чайківка, с.*", "Чайківка"),
    ("Багачка, м-ко", "Багачка"),
    ("Біла Церква, м-ко", "Біла Церква"),
    ("Багринівці ,с.", "Багринівці"),
    ("Архангело-Михайлівська слобода", "Архангело-Михайлівська слобода"),
])
def test_place_word_drops_type_and_variants(raw: str, word: str) -> None:
    """Каталоги шукають підрядком — «Вірмени (Армяни), с.» не збіглося б ні з чим."""
    assert _place_word({"village_uk": raw}) == word


def test_gazetteer_rows_name_their_archive() -> None:
    assert pack_archive("geog-cdiak") == ("CDIAK", "ЦДІАК")
    row = _tag({"card": "x"}, "geog-cdiak")
    assert row["archive_label"] == "ЦДІАК" and row["repo"] == "CDIAK"


def test_a_pack_without_an_archive_gets_none_invented() -> None:
    """Церкви Шади й точки Wikidata — не архів; вигадати його — збрехати."""
    assert pack_archive("churches-szady-2026.09") == ("", "")
    assert pack_archive("places-wikidata-2026.09") == ("", "")
    assert pack_archive("own") == ("", "")
    assert "archive_label" not in _tag({}, "own")


def test_a_row_keeps_its_own_repo() -> None:
    row = _tag({"repo": "DAHMO"}, "geog-cdiak")
    assert row["repo"] == "DAHMO"
