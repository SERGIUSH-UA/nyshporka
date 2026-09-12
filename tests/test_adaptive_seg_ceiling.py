"""Адаптивна стеля сегментації: густу справу читати раз, а не двічі (10.09.2026).

На сповіді 1802 р. (ДАХмО 316-1-39) у стелю 200 рядків уперлась кожна п'ята
сторінка, і кожна така читалась удруге — 62 с проти 20. Коли таких сторінок
багато, раннер піднімає базову стелю для решти справи й каже про це сусідам.
"""
from __future__ import annotations

from pathlib import Path

from nyshporka.htr import runner as R


def test_dense_case_raises_the_ceiling_from_its_densest_page() -> None:
    # 3 з 12 у стелі, найгустіша — 317 рядків → 317×2×1.25 = 792.5 → 800
    assert R.adapt_ceiling(12, 3, [231, 317, 260], current=400, retry=1600) == 800


def test_rare_hits_leave_the_ceiling_alone() -> None:
    assert R.adapt_ceiling(40, 1, [250], current=400, retry=1600) == 0      # одна
    assert R.adapt_ceiling(40, 3, [250, 240, 230], current=400, retry=1600) == 0  # 7.5%


def test_no_verdict_before_enough_pages() -> None:
    assert R.adapt_ceiling(5, 3, [300, 300, 300], current=400, retry=1600) == 0


def test_never_above_the_retry_ceiling_and_never_down() -> None:
    assert R.adapt_ceiling(10, 5, [900], current=400, retry=1600) == 1600
    assert R.adapt_ceiling(10, 5, [210], current=400, retry=1600) == 550   # щонайменше +100
    assert R.adapt_ceiling(10, 5, [300], current=1600, retry=1600) == 0    # нікуди
    assert R.adapt_ceiling(10, 5, [300], current=400, retry=0) == 0        # перепуск вимкнено


def test_the_same_evidence_does_not_raise_the_ceiling_twice() -> None:
    """🔴 Лічильники справи накопичуються, тож після підйому частка «в стелі»
    лишається тією самою — і стеля повзла б на +100 за КОЖНУ наступну сторінку,
    аж до стелі перепуску, хоча жодна нова сторінка в стелю не впиралась.
    Висока стеля роздуває пам'ять шарда, тож без нового доказу — ні кроку."""
    # 2 з 8 у стелі 400, найгустіша 230 рядків → 575 → 600
    assert R.adapt_ceiling(8, 2, [230, 230], current=400, retry=1600) == 600
    # далі легкі сторінки: у стелю 600 не вперлась жодна
    for pages in range(9, 30):
        assert R.adapt_ceiling(pages, 2, [230, 230], current=600, retry=1600) == 0
    # а нова густа сторінка вже при стелі 600 — знову доказ
    assert R.adapt_ceiling(30, 3, [230, 230, 330], current=600, retry=1600) == 850


def test_shared_ceiling_only_goes_up(tmp_path: Path) -> None:
    assert R.shared_ceiling(tmp_path) == 0
    R.publish_ceiling(tmp_path, 800)
    R.publish_ceiling(tmp_path, 600)          # нижчу сусід не нав'яже
    assert R.shared_ceiling(tmp_path) == 800
    R.publish_ceiling(tmp_path, 1000)
    assert R.shared_ceiling(tmp_path) == 1000
    (tmp_path / R.CEILING_FILE).write_text("бите", encoding="utf-8")
    assert R.shared_ceiling(tmp_path) == 0
