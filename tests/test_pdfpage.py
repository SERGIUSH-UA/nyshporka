"""📄 Кадр → сторінка PDF: відповідність ДОВОДИТЬСЯ, а не вгадується.

Ціна помилки тут асиметрична й тиха. Людина звіряє прочитане з оригіналом і
робить висновок про рід; по чужій сторінці цей висновок буде хибним — і
виглядатиме обґрунтованим, бо аркуш же показали.

Тому доказ повний: щільна нумерація кадрів `1..N` плюс сума сторінок усіх PDF
справи, що дорівнює рівно `N`. Не сходиться бодай одне — відмова.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.htr import pdfpage as P


def _frames(n: int, start: int = 1) -> list[str]:
    return [f"{i:05d}.jpg" for i in range(start, start + n)]


# ── арифметика ───────────────────────────────────────────────────────────────
def test_locate_walks_across_several_pdfs(tmp_path: Path) -> None:
    """🔴 Межа між томами — саме те місце, де зсув найлегший.

    Справа лежить трьома PDF по 1217+1313+1242; кадр 1218 це НУЛЬОВА сторінка
    другого файлу, а не 1218-та першого.
    """
    m = P.Mapping(pdfs=(tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"),
                  counts=(1217, 1313, 1242), frames=3772)
    assert m.locate(1) == (tmp_path / "a.pdf", 0)
    assert m.locate(1217) == (tmp_path / "a.pdf", 1216)
    assert m.locate(1218) == (tmp_path / "b.pdf", 0)
    assert m.locate(2530) == (tmp_path / "b.pdf", 1312)
    assert m.locate(2531) == (tmp_path / "c.pdf", 0)
    assert m.locate(3772) == (tmp_path / "c.pdf", 1241)


def test_locate_refuses_a_frame_outside_the_case(tmp_path: Path) -> None:
    m = P.Mapping(pdfs=(tmp_path / "a.pdf",), counts=(10,), frames=10)
    for bad in (0, 11, -1):
        with pytest.raises(P.PdfPageError, match="кадру"):
            m.locate(bad)


def test_frame_number_reads_the_name(tmp_path: Path) -> None:
    assert P.frame_number("00042.jpg") == 42
    assert P.frame_number("page_007") == 7
    assert P.frame_number("титул.jpg") is None


# ── доказ ────────────────────────────────────────────────────────────────────
@pytest.fixture
def case(tmp_path: Path, monkeypatch):
    """Тека справи з двома «PDF» і підміненим лічильником сторінок."""
    d = tmp_path / "справа"
    d.mkdir()
    (d / "частина_1.pdf").write_bytes(b"%PDF-1.4\n")
    (d / "частина_2.pdf").write_bytes(b"%PDF-1.4\n")
    counts = {"value": [6, 4]}
    monkeypatch.setattr(P, "page_counts", lambda pdfs: counts["value"])
    return d, counts


def test_mapping_is_proven_when_the_numbers_agree(case) -> None:
    d, _ = case
    m = P.mapping(d, _frames(10))
    assert m.frames == 10
    assert m.counts == (6, 4)
    assert m.locate(7)[1] == 0, "сьомий кадр — перша сторінка другого тому"


def test_page_count_mismatch_is_a_refusal(case) -> None:
    """🔴 Інша кількість = інший матеріал або інший рендер.

    «Приблизно те саме» тут не буває: зсув на одну сторінку тягнеться до кінця
    справи й ніде себе не виявляє.
    """
    d, counts = case
    counts["value"] = [6, 5]                 # 11 сторінок проти 10 кадрів
    with pytest.raises(P.PdfPageError, match=r"не сходиться|сторінок"):
        P.mapping(d, _frames(10))


def test_hole_in_frame_numbering_is_a_refusal(case) -> None:
    """Діра означає, що рендер не був суцільним — і далі все поїхало."""
    d, _ = case
    frames = _frames(10)
    frames.remove("00004.jpg")
    frames.append("00011.jpg")
    with pytest.raises(P.PdfPageError, match="не щільна"):
        P.mapping(d, frames)


def test_case_without_pdfs_says_so(tmp_path: Path) -> None:
    d = tmp_path / "порожня"
    d.mkdir()
    with pytest.raises(P.PdfPageError, match="немає PDF"):
        P.mapping(d, _frames(3))


def test_pdfs_are_taken_in_name_order(tmp_path: Path) -> None:
    """Порядок томів — за іменем, бо саме так їх бачив рендер."""
    d = tmp_path / "справа"
    d.mkdir()
    for n in ("частина_2.pdf", "частина_1.pdf", "частина_3.pdf"):
        (d / n).write_bytes(b"%PDF-1.4\n")
    (d / "нотатки.txt").write_bytes(b"")
    assert [p.name for p in P.case_pdfs(d)] == [
        "частина_1.pdf", "частина_2.pdf", "частина_3.pdf"]
