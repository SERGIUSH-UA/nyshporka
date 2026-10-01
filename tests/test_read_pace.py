"""Підсумок `nysh read`: темп машини, з яким можна порівнювати.

01.10.2026 люди в чаті прислали «19 с/стор» і «14–16 с/стор», і ці числа не
лягли поруч ні між собою, ні з нашими: рядок раннера не казав ні пристрою, ні
шардів, ні голосів, ні щільності, і рахувався від старту процесу разом із
завантаженням моделей.
"""
from __future__ import annotations

from nyshporka.core.progress import Event
from nyshporka.htr import runner as R
from nyshporka.htr.session import Pace


def _page(lines: int, sec: float) -> Event:
    return Event(phase="htr", i=1, n=9, item="x.jpg",
                 extra={"lines": lines, "sec": sec, "hw": "GTX 1650", "voices": 2})


def test_temp_mashyny_bez_zavantazhennia_modelei() -> None:
    p = Pace(shards=3)
    # Три шарди читають паралельно: сторінки закінчуються на 110, 112, 120 с,
    # кожна по 10 с. Завантаження моделей до сотої секунди в темп не входить.
    p.page(_page(80, 10.0), 110.0)
    p.page(_page(60, 10.0), 112.0)
    p.page(_page(100, 10.0), 120.0)
    assert round(p.sec_per_page, 2) == round((120.0 - 100.0) / 3, 2)
    line = p.line()
    for part in ("6.7 с/стор", "3 стор", "80 рядк/стор", "голосів 2",
                 "шардів 3", "GTX 1650"):
        assert part in line, part


def test_propuski_i_chuzhi_podii_ne_rakhuiutsia() -> None:
    p = Pace()
    p.page(Event(phase="htr", extra={"skipped": True}), 5.0)
    p.page(Event(phase="case_done", extra={"rc": 0}), 6.0)
    assert p.pages == 0 and p.line() == ""


def test_zalizo_na_procesori_nazvane() -> None:
    label = R.machine_label("cpu")
    assert "потоків" in label and not label.startswith(",")
