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


def test_kadr_bere_chas_pdf(tmp_path: Path) -> None:
    import os

    _pdf_zi_skanamy(tmp_path / "a.pdf", 2)
    davno = 1_700_000_000.0
    os.utime(tmp_path / "a.pdf", (davno, davno))
    pdfpage.vytiahnuty_kadry(tmp_path)
    assert (tmp_path / "0001.jpg").stat().st_mtime == davno
    assert (tmp_path / "0002.jpg").stat().st_mtime == davno


def _stara_sprava(tmp_path: Path) -> Path:
    import os

    d = tmp_path / "op73-spr-509"
    d.mkdir()
    _pdf_zi_skanamy(d / "sprava.pdf", 3)
    davno = 1_700_000_000.0
    os.utime(d / "sprava.pdf", (davno, davno))
    return d


def test_khmara_bere_spravu_pdf_za_tekoiu(tmp_path: Path) -> None:
    from nyshporka.cloud import frames as F
    from nyshporka.cloud import go

    d = _stara_sprava(tmp_path)
    ref = go.resolve_case(str(d))
    assert ref.frames_dir == d
    rep = F.check_frames(ref.frames_dir)
    assert rep.n == 3
    # Розгорнуте щойно не мусить виглядати як тека, що ще качається.
    assert rep.still_writing_min is None


def test_khmara_bere_spravu_pdf_za_shyfroiu(tmp_path: Path, monkeypatch) -> None:
    from nyshporka.cloud import go

    d = _stara_sprava(tmp_path)

    class Index:
        def __init__(self) -> None:
            self.by_key = {"DAZHO/1/73/509": {"path": str(d), "frames": 3}}

        def canonical(self, arg: str) -> str:
            return "DAZHO/1/73/509"

    monkeypatch.setattr(go, "_index", lambda: Index())
    ref = go.resolve_case("DAZHO/1/73/509")
    assert ref.frames_dir == d
    assert ref.frames_expected == 3
    assert len(list(d.glob("*.jpg"))) == 3
