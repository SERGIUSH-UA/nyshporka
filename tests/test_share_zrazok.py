"""📖 Зразкова справа з інсталятора не йде в Супрягу."""
from __future__ import annotations

from nyshporka.setup import sample
from nyshporka.share import card


def test_prohony_zrazka_ne_viddaiutsia() -> None:
    assert sample.tse_zrazok(sample.CASE_KEY, [sample.RUN_MAIN, sample.RUN_SIDE])
    assert sample.tse_zrazok("DAHMO/315/1/159", ["sample-skryba", "sample-pysar"])


def test_vlasne_chytannia_tiiei_zh_spravy_ide() -> None:
    assert not sample.tse_zrazok("DAHMO/315/1/159", ["adm1821-315-159"])
    assert not sample.tse_zrazok("DAHMO/315/1/159", ["sample-pysar", "moi-prohin"])
    assert not sample.tse_zrazok("DAHMO/315/1/159", [])
    assert not sample.tse_zrazok("DAVIO/177/1/856", ["sample-pysar"])


def test_roky_riadkom_ne_rozsypaiutsia() -> None:
    assert card.apply({"shifra": "x"}, {"years": "1829"})["years"] == [1829, 1829]
    assert card.apply({"shifra": "x"}, {"years": [1831, 1836]})["years"] == [1831, 1836]
