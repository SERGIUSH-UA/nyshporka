"""Рядок, який kraken викинув на полігонізації, видно в мети сторінки.

🔴 «Polygonizer failed on line 0» — не косметика: `blla.py` кладе рядок у
сторінку лише з полігоном, тож базова лінія без нього зникає разом із текстом.
У лозі не було кадру (лінії полігонізуються поодинці — індекс завжди нуль), і
90 таких подій на справі не мали адреси (звіт користувача 29.09.2026).
"""
from __future__ import annotations

import logging
import sys
import types

import pytest

from nyshporka.htr import runner as R


def test_vtracheni_riadky_lyahaiut_u_metu_storinky() -> None:
    watch = R.GeomWatch()
    log = logging.getLogger("kraken.lib.segmentation")

    watch.start()
    log.warning("Polygonizer failed on line 0: TopologyException: side location conflict")
    log.warning("Polygonizer failed on line 0: index 1 is out of bounds for axis 0 with size 0")
    log.warning("щось інше від kraken")
    got = watch.page()
    assert got["geom_lost"] == 2
    assert got["needs_review"] is True
    assert got["geom_why"][0].startswith("TopologyException")

    watch.start()
    assert watch.page() == {}, "наступна сторінка не успадковує втрат попередньої"


def test_riatunok_zapasnym_shliakhom_rakhuietsia(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace(FALLBACKS={"calc_roi": 0, "boundary_tracing": 0})
    monkeypatch.setitem(sys.modules, "fast_geom", fake)
    watch = R.GeomWatch()
    watch.start()
    fake.FALLBACKS["calc_roi"] += 2
    assert watch.page() == {"geom_rescued": 2}


def test_shvydkyi_shliakh_padaie_oryhinal_dovodyt() -> None:
    """🔴 Упав патч — рядок доводить оригінал kraken, і це рахується."""
    pytest.importorskip("shapely")
    from nyshporka.htr.patches import fast_geom as F

    def fast(x: int) -> int:
        raise IndexError("index 1 is out of bounds for axis 0 with size 0")

    before = F.FALLBACKS["calc_roi"]
    call = F._with_fallback(fast, lambda x: x * 2, "calc_roi")
    assert call(21) == 42
    assert F.FALLBACKS["calc_roi"] == before + 1
