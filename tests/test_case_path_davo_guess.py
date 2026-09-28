"""Архів ДАВіО не вгадується з трьох чисел через дефіс.

28.09.2026 тека `1890-18-1-1873` (рік 1890 і шифра ДАХмО 18-1-1873) поїхала в
пул шифрою «ДАВіО 890-18-1»: правило для тек завантажувача ДАВіО
(`010904-24-00114`) ковтало провідну «1» і за відсутності архіву в шляху
підставляло ДАВіО. Фонд 890 у ДАВіО — Липовецьке духовне правління 1800–1836,
тож метрика Чернелівки лягла під чужу книгу.
"""
from __future__ import annotations

import pytest

from nyshporka.library import parse_case_path


@pytest.mark.parametrize("rel", ["1890-18-1-1873", "data/raw/1890-18-1-1873"])
def test_rik_pered_shyfroiu_ne_stae_fondom_davio(rel: str) -> None:
    got = parse_case_path(rel)
    assert got is None or got[0] != "DAVIO", got


@pytest.mark.parametrize("rel, want", [
    ("data/raw/davo/010904-24-00114", ("DAVIO", "904", "24", "114")),
    ("E:/скани/010904-24-00199", ("DAVIO", "904", "24", "199")),
    ("data/raw/davio_603/010603-1-00012", ("DAVIO", "603", "1", "12")),
    ("data/raw/davo/f904_wiki/904-24-8", ("DAVIO", "904", "24", "8")),
])
def test_teky_davio_yak_i_buly(rel: str, want: tuple[str, ...]) -> None:
    assert parse_case_path(rel) == want
