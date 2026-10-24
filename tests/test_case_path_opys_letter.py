"""Літера опису в імені теки: ЦДІАЛ ф.201 має опис «4а» (ще 1а, 1б, 1в, 2а).

Тека `op4a-spr-5904` губила літеру й діставала ключ `CDIAL/201/4/5904`, а паспорт
«ЦДІАЛ 201-4а-5904» давав `CDIAL/201/4a/5904` — бібліотека й паспорт розходились.
"""
from __future__ import annotations

import pytest

from nyshporka import library as lib


def _key(rel: str):
    return lib.parse_case_path(rel)


@pytest.mark.parametrize("folder, opys", [
    ("op4a-spr-5904", "4a"),
    ("op4а-spr-5904", "4a"),      # кирилична «а»
    ("op1б-spr-5904", "1b"),      # норм. зводить кирилицю до латинки, як у ключі з паспорта
    ("op24-spr-5904", "24"),
    ("op2-spr-5904", "2"),
])
def test_opys_letter_from_folder(folder: str, opys: str):
    got = _key(f"data/raw/cdial_201/{folder}")
    assert got is not None
    repo, fond, got_opys, spr = got
    assert (fond, got_opys, spr) == ("201", opys, "5904")


def test_folder_key_equals_passport_key():
    from nyshporka.core import casekey as ck

    folder = _key("data/raw/cdial_201/op4a-spr-5904")
    cyr = _key("data/raw/cdial_201/op4а-spr-5904")
    assert folder == cyr
    # паспорт: опис «4а» кирилицею → той самий нормований опис
    assert folder[2] == ck.norm_part("4а")


def test_letter_does_not_swallow_spr_separator():
    got = _key("data/raw/cdial_201/op2-spr-148")
    assert got is not None and got[2] == "2" and got[3] == "148"
    got = _key("data/raw/cdial_201/op4a_spr_148")
    assert got is not None and got[2] == "4a" and got[3] == "148"


def test_fsub_folder_with_letter():
    got = _key("data/raw/davio/f904_op24a/spr-5")
    assert got is not None and got[2] == "24a"
    got = _key("data/raw/davio/f904_op24/spr-5")
    assert got is not None and got[2] == "24"
