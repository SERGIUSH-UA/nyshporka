"""Кадр догори ногами (EXIF Orientation = 3): кроп і перегляд бачать його так, як рушій.

Стискач хмари повертає такі кадри (`cloud.frames.shrink`), і рамки рядків лежать
у координатах повернутого. Перегляд сторінки прогону мусить повертати так само,
інакше рамка лягає на протилежний кут аркуша (ЦДІАК 442-300-2, 24.11.2026).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.utils import exif as X

Image = pytest.importorskip("PIL.Image")


def _frame(path: Path, orientation: int) -> Path:
    from PIL import ImageDraw

    im = Image.new("RGB", (40, 60), "white")
    ImageDraw.Draw(im).rectangle([0, 0, 40, 20], fill="black")     # темне вгорі пікселів
    tags = Image.Exif()
    tags[0x0112] = orientation
    im.save(path, "JPEG", quality=95, exif=tags)
    return path


@pytest.mark.parametrize(("orientation", "flip"), [(1, False), (3, True), (6, False), (8, False)])
def test_only_the_upside_down_mark_counts(tmp_path: Path, orientation: int, flip: bool) -> None:
    with Image.open(_frame(tmp_path / "f.jpg", orientation)) as im:
        assert X.is_upside_down(im) is flip


def test_a_frame_without_exif_is_not_upside_down(tmp_path: Path) -> None:
    Image.new("RGB", (10, 10), "white").save(tmp_path / "f.jpg", "JPEG")
    with Image.open(tmp_path / "f.jpg") as im:
        assert X.is_upside_down(im) is False
    assert X.upright(im, False) is im


def test_the_run_page_view_turns_an_upside_down_frame(tmp_path: Path) -> None:
    from nyshporka.htr import view as V

    im = V._open_run_scan(_frame(tmp_path / "f.jpg", 3), 0)
    g = im.convert("L")
    assert g.getpixel((20, 2)) > 200 and g.getpixel((20, 57)) < 80
    plain = V._open_run_scan(_frame(tmp_path / "p.jpg", 1), 0).convert("L")
    assert plain.getpixel((20, 2)) < 80
