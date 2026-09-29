"""Час сторінки за етапами: де саме він іде і на чому рахується.

🔴 «Карта ледь зайнята» людина читала як «читає процесором», хоча мережа
сегментації, sato й розпізнавання йшли на карті — просто недовго (звіт
користувача 29.09.2026). Без поетапного часу це здогад, а не відповідь.
"""
from __future__ import annotations

import pytest

from nyshporka.htr import runner as R


@pytest.fixture(autouse=True)
def _chysto() -> None:
    R.STAGES.clear()
    yield
    R.STAGES.clear()


def test_etap_rakhuie_chas_i_nakopychuie() -> None:
    f = R._timed(lambda x: x + 1, "sato")
    assert f(1) == 2 and f(2) == 3
    assert R.STAGES["sato"] >= 0.0
    assert list(R.STAGES) == ["sato"]


def test_etap_rakhuie_i_pry_vyniatku() -> None:
    def bad() -> None:
        raise ValueError("x")

    with pytest.raises(ValueError):
        R._timed(bad, "polygon")()
    assert "polygon" in R.STAGES


def test_obhortka_dilyt_atrybuty_z_funktsiieiu() -> None:
    """🔴 `ocr_page` пише собі `boxes`, а `_geom_of` читає їх через обгортку."""
    def inner() -> None:
        inner.boxes = [1]

    wrapped = R._timed(inner, "ocr")
    wrapped()
    assert wrapped.boxes == [1]
    wrapped.polys = [2]
    assert inner.polys == [2]


def test_pokhidni_etapy_storinky() -> None:
    R.STAGES.update({"ocr": 5.0, "segment": 3.0, "seg_net": 1.0, "sato": 1.5})
    got = R.page_stages(sec=6.0)
    assert got["recognize"] == 2.0, "ocr − segment"
    assert got["other"] == 1.0, "сторінка − ocr"
    assert got["sato"] == 1.5


def test_pidsumok_kazhe_de_rakhuietsia() -> None:
    total = {"segment": 6.0, "seg_net": 2.0, "gpu_wait": 1.0, "sato": 2.0,
             "polygon": 1.0, "recognize": 4.0, "other": 2.0}
    s = R.stages_summary(total, 2, "cuda:0", gpu_sato=True)
    assert "сегментація 3.0 с" in s and "чекання карти 0.5 с" in s
    assert "sato 1.0 с · карта" in s and "полігони 0.5 с · процесор" in s
    assert "розпізнавання 2.0 с · карта" in s
    assert "sato 1.0 с · процесор" in R.stages_summary(total, 2, "cuda:0", gpu_sato=False)
    assert R.stages_summary({}, 0, "cpu", gpu_sato=False) == ""
