"""Трійка чисел в імені теки не завжди «фонд-опис-справа».

Підстава — аудит ключів 2026-09-10. Під slug'ом `dahmo_315_pages` лежали теки
`met1870-315-10037`, `klir1799-315-6743`: фонд давав slug (315), а `_SHIFRA_RE`
брав з імені «1870-315-10037» як фонд-опис-справа — і в опис потрапляв номер
ФОНДУ. 53 записи з описом «315» аудит читав як колізію описів, а внесення фонду
в `_OPYS_IN_KEY` розвалило б кожну книгу на справжню й сміттєву. Там само
`dahmo_315_small/m904-24-25` (ДАВіО 904-24-25) ставала «ДАХмО 315-24-25» —
чужою книгою під ключем ф.315.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def lib(tmp_path: Path):
    """Бібліотека на ТИМЧАСОВОМУ просторі — див. шапку `test_case_key_builder`."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L

    return L


@pytest.mark.parametrize("rel, spr", [
    ("data/raw/dahmo_315_pages/met1870-315-10037", "10037"),
    ("data/raw/dahmo_315_pages/klir1799-315-6743", "6743"),
    ("dahmo_315_fs/shrunk/klir1895-315-12528", "12528"),   # відносно кореня архіву
])
def test_genre_year_prefix_is_not_a_fond_opys_pair(lib, rel, spr) -> None:
    """«<жанр><рік>-<фонд>-<справа>»: опис невідомий, а не дорівнює фонду."""
    got = lib.parse_case_path(rel)
    assert got == ("DAHMO", "315", None, spr), got


@pytest.mark.parametrize("rel", [
    "data/raw/dahmo_315_small/m904-24-25",
    "data/raw/dahmo_315_small/m357-1-23",
])
def test_a_foreign_shifra_is_not_claimed_by_the_slug(lib, rel) -> None:
    """Ім'я несе ЧУЖИЙ фонд — справа не приписується фонду slug'а.

    Без паспорта в теці такій справі краще лишитись без шифри, ніж тихо лягти
    чужою книгою в ф.315.
    """
    assert lib.parse_case_path(rel) is None


@pytest.mark.parametrize("rel, want", [
    ("data/raw/dahmo_315/315-1-10117", ("DAHMO", "315", "1", "10117")),
    ("data/raw/dahmo_315/spr-8591", ("DAHMO", "315", None, "8591")),
    ("data/raw/dahmo_196/196-8-712", ("DAHMO", "196", "8", "712")),
    ("data/raw/dahmo_230/230-1-2а", ("DAHMO", "230", "1", "2a")),
])
def test_ordinary_names_are_unchanged(lib, rel, want) -> None:
    assert lib.parse_case_path(rel) == want


def test_fond_196_splits_opys_1_and_8(lib) -> None:
    """ДАХмО ф.196 спр.712 існує в оп.1 і оп.8 — два різні ключі."""
    a = lib._mk_key("DAHMO", "196", "712", "1")
    b = lib._mk_key("DAHMO", "196", "712", "8")
    assert a == "DAHMO/196-1/712" and b == "DAHMO/196-8/712"
