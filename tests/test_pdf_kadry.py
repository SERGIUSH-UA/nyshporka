"""Справа-PDF розгортається в кадри перед читанням.

`nysh look` бачив «один PDF, 321 стор.», а `nysh read` казав «зображень
немає» — людині лишалось розбирати PDF самій.
"""
from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from nyshporka.htr import pdfpage


def _pdf_zi_skanamy(path: Path, storinok: int) -> list[bytes]:
    """PDF, де кожна сторінка — один вбудований JPEG, як у Commons."""
    doc = pdfium.PdfDocument.new()
    jpegs = []
    for i in range(storinok):
        buf = io.BytesIO()
        Image.new("RGB", (400, 600), (200 - i * 20, 180, 160)).save(buf, format="JPEG")
        jpegs.append(buf.getvalue())
        page = doc.new_page(400, 600)
        img = pdfium.PdfImage.new(doc)
        img.load_jpeg(io.BytesIO(jpegs[-1]), inline=True)
        img.set_matrix(pdfium.PdfMatrix().scale(400, 600))
        page.insert_obj(img)
        page.gen_content()
    doc.save(str(path))
    doc.close()
    return jpegs


def test_kadry_z_pdf_bez_perestysnennia(tmp_path: Path) -> None:
    jpegs = _pdf_zi_skanamy(tmp_path / "a.pdf", 3)
    assert pdfpage.vytiahnuty_kadry(tmp_path) == 3
    kadry = sorted(p.name for p in tmp_path.glob("*.jpg"))
    assert kadry == ["0001.jpg", "0002.jpg", "0003.jpg"]
    assert (tmp_path / "0002.jpg").read_bytes() == jpegs[1], "скан мусить лягти як є"
    # Нумерація та, яку доводить переглядач: кадр → сторінка того самого PDF.
    m = pdfpage.mapping(tmp_path, kadry)
    assert m.locate(3) == (tmp_path / "a.pdf", 2)


def test_dochytuie_a_ne_pochynaie_znovu(tmp_path: Path) -> None:
    _pdf_zi_skanamy(tmp_path / "a.pdf", 2)
    (tmp_path / "0001.jpg").write_bytes(b"vzhe")
    assert pdfpage.vytiahnuty_kadry(tmp_path) == 1
    assert (tmp_path / "0001.jpg").read_bytes() == b"vzhe"


def test_bez_pdf_nichoho(tmp_path: Path) -> None:
    assert pdfpage.vytiahnuty_kadry(tmp_path) == 0
