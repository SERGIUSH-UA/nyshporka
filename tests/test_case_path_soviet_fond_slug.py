"""Тека радянського фонду `dahmo_R-6380/spr-215` розбирається з імені.

01.10.2026 `cases take` поклав ДАХмО Р-6380-1-215 у `data/raw/dahmo_R-6380/`,
а бібліотека справи не побачила: slug приймав лише числовий фонд, а паспорт
`meta.json` шифри рядком не несе, тож і запасний шлях через сайдкар мовчав.
"""
from __future__ import annotations

import pytest

from nyshporka.library import parse_case_path


@pytest.mark.parametrize("rel, fond, spr", [
    ("data/raw/dahmo_R-6380/spr-215", "R-6380", "215"),
    ("data/raw/dahmo_r-6380/spr-225", "R-6380", "225"),
    ("data/raw/dahmo_315/spr-8433", "315", "8433"),
])
def test_fond_iz_slug_z_literoiu(rel: str, fond: str, spr: str) -> None:
    got = parse_case_path(rel)
    assert got is not None, rel
    assert (got[1], got[3]) == (fond, spr)
