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


def test_povernuta_storinka_renderytsia_a_ne_bokom(tmp_path: Path) -> None:
    """Фото з телефона лежить у PDF боком, прямо його ставить `/Rotate 90`.

    ДАК 312-1-51: сирі байти дали рушію аркуш на боці — 3 рядки на сторінку.
    """
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), (120, 120, 120)).save(buf, format="JPEG")
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(600, 400)
    img = pdfium.PdfImage.new(doc)
    img.load_jpeg(io.BytesIO(buf.getvalue()), inline=True)
    img.set_matrix(pdfium.PdfMatrix().scale(600, 400))
    page.insert_obj(img)
    page.gen_content()
    page.set_rotation(90)
    doc.save(str(tmp_path / "a.pdf"))
    doc.close()

    assert pdfpage.vytiahnuty_kadry(tmp_path) == 1
    kadr = (tmp_path / "0001.jpg").read_bytes()
    assert kadr != buf.getvalue(), "повернуту сторінку не можна віддавати сирими байтами"
    w, h = Image.open(io.BytesIO(kadr)).size
    assert h > w, f"кадр мусить стояти, як у PDF (портрет), а маємо {w}×{h}"


def _bokovyi_pdf(path: Path) -> bytes:
    """PDF з однією сторінкою-фото, поставленою прямо `/Rotate 90`; сирий JPEG."""
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), (120, 120, 120)).save(buf, format="JPEG")
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(600, 400)
    img = pdfium.PdfImage.new(doc)
    img.load_jpeg(io.BytesIO(buf.getvalue()), inline=True)
    img.set_matrix(pdfium.PdfMatrix().scale(600, 400))
    page.insert_obj(img)
    page.gen_content()
    page.set_rotation(90)
    doc.save(str(path))
    doc.close()
    return buf.getvalue()


def test_bokovyi_kadr_staroi_versii_rozghortaietsia_nanovo(tmp_path: Path) -> None:
    """🔴 Версія до 0.27 поклала сирі байти повернутої сторінки — аркуш боком.

    Наявні кадри не переписуються, тож без цього «перечитайте після
    оновлення» читало б ті самі бокові кадри.
    """
    syryi = _bokovyi_pdf(tmp_path / "a.pdf")
    (tmp_path / "0001.jpg").write_bytes(syryi)
    ryadky: list[str] = []
    assert pdfpage.vytiahnuty_kadry(tmp_path, on_line=ryadky.append) == 1
    w, h = Image.open(tmp_path / "0001.jpg").size
    assert h > w, f"кадр мусить стояти прямо, а маємо {w}×{h}"
    assert any("боком" in r for r in ryadky), "людині сказано, що перечитати"
    # Виправлений кадр — уже не відбиток вади: повтор нічого не робить.
    assert pdfpage.vytiahnuty_kadry(tmp_path) == 0


def test_chuzhyi_kadr_ne_perepysuietsia(tmp_path: Path) -> None:
    """Кадр, що не є сирим образом сторінки, поклав не цей код — не чіпати."""
    _bokovyi_pdf(tmp_path / "a.pdf")
    chuzhyi = io.BytesIO()
    Image.new("RGB", (600, 400), (10, 10, 10)).save(chuzhyi, format="JPEG")
    (tmp_path / "0001.jpg").write_bytes(chuzhyi.getvalue())
    assert pdfpage.vytiahnuty_kadry(tmp_path) == 0
    assert (tmp_path / "0001.jpg").read_bytes() == chuzhyi.getvalue()


def test_lyshe_bokovi_ne_dorendeniuie_vidsutni(tmp_path: Path) -> None:
    """Тека з кадрами: інші кадри могли прийти не з цього PDF — не задвоювати."""
    _pdf_zi_skanamy(tmp_path / "a.pdf", 2)
    (tmp_path / "0001.jpg").write_bytes(b"vzhe")
    assert pdfpage.vytiahnuty_kadry(tmp_path, lyshe_bokovi=True) == 0
    assert not (tmp_path / "0002.jpg").exists()


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


# ── роздільність і швидкість розгортання ────────────────────────────────────
def _pdf_zi_skanom_ne_jpeg(path: Path, storinok: int, px: tuple[int, int],
                           pt: tuple[int, int]) -> None:
    """PDF, де скан — не JPEG (бітмапа без DCT), як JPEG 2000 у ДАЖО 1-78."""
    doc = pdfium.PdfDocument.new()
    for i in range(storinok):
        page = doc.new_page(*pt)
        img = pdfium.PdfImage.new(doc)
        img.set_bitmap(pdfium.PdfBitmap.from_pil(Image.new("RGB", px, (100 + i, 120, 140))))
        img.set_matrix(pdfium.PdfMatrix().scale(*pt))
        page.insert_obj(img)
        page.gen_content()
    doc.save(str(path))
    doc.close()


def test_kilka_procesiv_ta_sama_numeratsiia(tmp_path: Path, monkeypatch) -> None:
    """Робітники ділять сторінки, але кадр N — це сторінка N, байти як є, час PDF."""
    import os

    jpegs = _pdf_zi_skanamy(tmp_path / "a.pdf", 4)
    _pdf_zi_skanom_ne_jpeg(tmp_path / "b.pdf", 3, (800, 600), (400, 300))
    davno = 1_700_000_000.0
    os.utime(tmp_path / "a.pdf", (davno, davno))
    monkeypatch.setattr(pdfpage, "PARALLEL_MIN", 2)
    said: list[str] = []
    assert pdfpage.vytiahnuty_kadry(tmp_path, jobs=3, on_line=said.append) == 7
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == [f"{i:04d}.jpg" for i in range(1, 8)]
    assert (tmp_path / "0003.jpg").read_bytes() == jpegs[2]
    assert (tmp_path / "0004.jpg").stat().st_mtime == davno
    with Image.open(tmp_path / "0006.jpg") as im:
        assert im.size[0] == pdfpage.DEFAULT_WIDTH
    assert any("у 3 процесах" in s for s in said)
    assert not any("впав" in s for s in said), "робітники справді працювали"


def test_robitnyk_vpav_storinky_dorendereni(tmp_path: Path, monkeypatch) -> None:
    """Робітник без пакета, без пам'яті, без чого завгодно — справа однаково ціла."""
    import subprocess

    _pdf_zi_skanamy(tmp_path / "a.pdf", 6)

    class Dead:
        def __init__(self, *a, **kw) -> None:
            self.stdin = io.StringIO()
            self.stderr = io.StringIO("ModuleNotFoundError: nyshporka")

        def wait(self) -> int:
            return 1

    monkeypatch.setattr(subprocess, "Popen", Dead)
    monkeypatch.setattr(pdfpage, "PARALLEL_MIN", 2)
    said: list[str] = []
    assert pdfpage.vytiahnuty_kadry(tmp_path, jobs=2, on_line=said.append) == 6
    assert len(list(tmp_path.glob("*.jpg"))) == 6
    assert any("впав" in s for s in said)
