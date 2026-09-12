"""Група справ одним рядком опису в збирачах покажчика й сайту архіву.

📚 Описи бібліотек і частини архівів записують кілька справ одним рядком: «29-35»,
аркуші на всю групу. Рядок лишається один, з ключем за першим номером, а кінець
групи йде в `spr_to`. Без нього покриття звітує решту номерів групи відсутніми —
прогалиною там, де опис повний.
"""
from __future__ import annotations

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect.archium import ArchiumCollector
from nyshporka.fonds.collect.duck import FIELDS as DUCK_FIELDS
from nyshporka.fonds.collect.duck import DuckCollector
from nyshporka.fonds.registry import FIELDS as READER_FIELDS
from nyshporka.sources.archium import CaseRow


def test_group_end_forms() -> None:
    assert T.group_end("29-35") == "35"
    assert T.group_end("Справа 29–35") == "35", "префікс переглядача й довге тире"
    assert T.group_end("24а") == ""
    assert T.group_end("12") == ""
    assert T.group_end("вільний номер") == ""


def test_abbreviated_group_end_is_expanded() -> None:
    """🔴 «3548-550» — це 3548–3550. Без розгортання кінець менший за початок, і
    група мовчки ставала однією справою."""
    assert T.group_end("3548-550") == "3550"
    assert T.group_end("1219-21") == "1221"


def test_end_not_above_start_is_not_a_group() -> None:
    assert T.group_end("35-29") == ""
    assert T.group_end("3548-548") == ""


def test_one_digit_end_is_not_expanded() -> None:
    """«10-9», «12-3» — сміття набору, а не 10–19 і 12–13."""
    assert T.group_end("10-9") == ""
    assert T.group_end("12-3") == ""
    assert T.group_end("100-5") == ""


def test_coverage_clips_a_group_at_the_opys_bound() -> None:
    """Група, що виходить за межу опису, не робить «присутніх» більше за номери."""
    from nyshporka.archives.pack import OpysBound
    from nyshporka.fonds.merge.coverage import classify

    rows = [{"opys": "1", "spr_int": "1", "spr_letter": "", "spr_to": ""},
            {"opys": "1", "spr_int": "8", "spr_letter": "", "spr_to": "3500"}]
    cov = classify(rows, {"1": OpysBound(opys="1", last=10, basis="official")})
    assert cov["1"]["present"] == 4            # 1 і 8, 9, 10
    assert cov["1"]["absent"] == 6


def test_the_key_of_a_group_is_its_first_number() -> None:
    """Ключ групи — перший номер: `split_code` не мусить змінитись."""
    assert T.split_code("29-35") == (29, "")


def test_duck_row_carries_the_group_end() -> None:
    row = DuckCollector._row({"id": "f1", "code": "29-35", "title": "Інвентар",
                              "years": [{"start_year": 1845, "end_year": 1866}]},
                             "ДАВіО", "6", "1", {})
    assert (row["spr_int"], row["spr_to"]) == (29, "35")
    single = DuckCollector._row({"id": "f2", "code": "22", "title": "Інвентар",
                                 "years": [{}]}, "ДАВіО", "6", "1", {})
    assert single["spr_to"] == ""


def test_archium_row_carries_the_group_end() -> None:
    case = CaseRow(file_id="70029", number="Справа 29-35", date="1845-1866",
                   description="Інвентар села", sheets=67)
    row = ArchiumCollector._row(case, "1", "https://архів")
    assert row is not None
    assert (row["spr_int"], row["spr_to"], row["folios"]) == (29, "35", "67")


def test_the_column_is_known_to_the_reader() -> None:
    """Колонку, якої не знає читалка, злиття мовчки відкидає."""
    assert "spr_to" in DUCK_FIELDS
    assert "spr_to" in READER_FIELDS
