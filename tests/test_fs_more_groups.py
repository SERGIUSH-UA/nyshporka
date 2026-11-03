"""🎞 Справа на кількох групах FamilySearch: реєстр мусить знати всі.

🔴 Вада: збирач копій покажчика знав другу групу справи (`fs_more`), а злиття її
не переносило. ДАІФО 631-3-5 значилась у реєстрі однією групою 116959441
(т.II, 1866–1900), а т.I 1901–1931 (116959390) не мав де лягти — так 906 справ
ф.631 і 2164 ф.127 виглядали повними на пів справи.
"""
from __future__ import annotations

from nyshporka.fonds.merge import sources as S
from nyshporka.fonds.merge import titles as TT
from nyshporka.fonds.registry import FIELDS as REGISTRY_FIELDS

KEY = ("3", "5", "")


def _reg(**kw: str) -> dict:
    r = S.blank_row(KEY)
    r.update(kw)
    return {KEY: r}


def _copy(dgs: str, more: str = "") -> dict[str, str]:
    return {"opys": "3", "spr_int": "5", "spr_letter": "", "fs_dgs": dgs,
            "fs_more": more, "fs_url": f"https://fs/{dgs}", "duck_copy_url": f"https://fs/{dgs}"}


def test_the_column_is_carried_from_merge_to_reader() -> None:
    assert "fs_more" in S.COLUMNS
    assert "fs_more" in REGISTRY_FIELDS
    # Останньою — позиційні читачі давніх реєстрів не мусять зсунутись.
    assert S.COLUMNS[-1] == "fs_more" and REGISTRY_FIELDS[-1] == "fs_more"


def test_every_group_of_the_case_reaches_the_registry() -> None:
    reg = _reg()
    TT.fuse_fs(reg, [], [], [_copy("116959441", "007803695_002_M9MV-LVL;116959390")])
    r = reg[KEY]
    assert r["fs_dgs"] == "116959441"
    assert r["fs_more"] == "007803695_002_M9MV-LVL;116959390"


def test_a_known_first_group_is_not_displaced_and_not_repeated() -> None:
    reg = _reg(fs_dgs="116959390")
    TT.fuse_fs(reg, [], [], [_copy("116959441", "116959390")])
    r = reg[KEY]
    assert r["fs_dgs"] == "116959390"
    assert r["fs_more"] == "116959441"


def test_a_film_number_in_the_head_gets_no_groups() -> None:
    """Номер мікроплівки (7 цифр) — інша нумерація того самого: який DGS йому
    відповідає, з рядка не видно, тож дописати групи означало б дати дубль."""
    reg = _reg(fs_dgs="2268975", fs_film="2268975")
    TT.fuse_fs(reg, [], [], [_copy("116959441", "116959390")])
    assert reg[KEY]["fs_more"] == ""


def test_groups_of_the_fs_index_go_in_too() -> None:
    reg = _reg()
    fs = [{"opys": "3", "spr": "5", "dgs": "116959441", "fs_film": "116959441;116959390"}]
    TT.fuse_fs(reg, fs, [], [])
    assert reg[KEY]["fs_dgs"] == "116959441"
    assert reg[KEY]["fs_more"] == "116959390"


def test_wider_fs_years_widen_the_case() -> None:
    """Рішення дослідника 03.11.2026: межі груп FS, коли вони ширші, з `years_src=fs`."""
    reg = _reg(year_from="1866", year_to="1900", years_src="duck")
    fs = [{"opys": "3", "spr": "5", "dgs": "116959441", "year_from": "1866", "year_to": "1931"}]
    TT.fuse_fs(reg, fs, [], [])
    r = reg[KEY]
    assert (r["year_from"], r["year_to"]) == ("1866", "1931")
    assert r["years_src"] == "duck+fs"


def test_narrower_fs_years_change_nothing() -> None:
    reg = _reg(year_from="1850", year_to="1935", years_src="wikisource")
    fs = [{"opys": "3", "spr": "5", "dgs": "116959441", "year_from": "1866", "year_to": "1900"}]
    TT.fuse_fs(reg, fs, [], [])
    r = reg[KEY]
    assert (r["year_from"], r["year_to"], r["years_src"]) == ("1850", "1935", "wikisource")
