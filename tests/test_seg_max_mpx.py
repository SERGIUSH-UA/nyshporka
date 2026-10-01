"""Стеля входу сегментатора: стискається лише кадр ширший за стелю, і кеш це знає.

ANRM 134-249 (01.10.2026): етикетка плівки FamilySearch 7461×1802 — вісім
«рядків» — узяла 6.8 ГБ VRAM проти 2.2 ГБ звичайної сторінки, бо kraken зводить
кадр до висоти 1800 зі збереженням пропорцій, і пам'ять росте з ШИРИНОЮ.
"""
from __future__ import annotations

from PIL import Image

from nyshporka.htr import runner as R


def _seg(max_mpx: float = 8.0, seg_height: int = 0) -> R.Segmenter:
    return R.Segmenter("blla.mlmodel", "cpu", seg_height=seg_height, max_mpx=max_mpx)


def test_strip_gets_a_lower_input_height() -> None:
    h = _seg()._page_height(Image.new("L", (7461, 1802)))
    assert h == 1390
    assert h * h * 7461 / 1802 <= 8.0e6        # площа входу в межах стелі


def test_normal_pages_and_spreads_are_untouched() -> None:
    s = _seg()
    assert s._page_height(Image.new("L", (3600, 2700))) == 0      # 4.3 Мп
    assert s._page_height(Image.new("L", (4400, 1800))) == 0      # розворот 2.4:1, 7.9 Мп


def test_cap_off_and_explicit_seg_height() -> None:
    assert _seg(max_mpx=0)._page_height(Image.new("L", (7461, 1802))) == 0
    # заданий `--seg-height 1200`: площа рахується від нього, смуга 1200² × 4.14 = 6 Мп
    assert _seg(seg_height=1200)._page_height(Image.new("L", (7461, 1802))) == 0
    assert _seg(max_mpx=4, seg_height=1200)._page_height(Image.new("L", (7461, 1802))) == 982


def test_floor_keeps_lines_apart() -> None:
    assert _seg(max_mpx=1)._page_height(Image.new("L", (20000, 1000))) == R.SEG_MIN_HEIGHT


def test_cache_key_differs_only_for_capped_pages() -> None:
    s = _seg()
    plain = s._full_key()
    s._page_h = 1390
    capped = s._full_key()
    s._page_h = 0
    assert plain["seg_height"] == 0 and capped["seg_height"] == 1390
    assert s._full_key() == plain               # наявний кеш звичайних сторінок дійсний
