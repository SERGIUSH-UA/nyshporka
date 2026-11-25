"""Виправи модулів описів: сторінки (`pages`) і розбір таблиці (`vl_table`)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from nyshporka.opysy import pages as PG


def _kadry(d: Path, imena: list[str]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(imena):
        Image.new("L", (30, 20), 10 + i).save(d / n)
    return d


def test_obrazy_natural_order(tmp_path: Path) -> None:
    d = _kadry(tmp_path / "k", ["1.jpg", "10.jpg", "2.jpg", "3.png"])
    assert [p.name for p in PG.obrazy(d)] == ["1.jpg", "2.jpg", "3.png", "10.jpg"]


def test_obrazy_same_width_order_and_fingerprint_unchanged(tmp_path: Path) -> None:
    imena = ["0003.jpg", "0001.jpg", "0010.jpg", "0002.png", "0002.jpg", "scan_0001.tif"]
    d = _kadry(tmp_path / "k", imena)
    stari = sorted(imena, key=str.lower)
    assert [p.name for p in PG.obrazy(d)] == stari
    # відбиток джерела (workdir) — за іменами в цьому порядку, тож він не змінюється
    def vidbytok(names: list[str]) -> str:
        h = hashlib.sha256()
        for n in names:
            h.update(n.encode() + b"\0")
        return h.hexdigest()
    assert vidbytok([p.name for p in PG.obrazy(d)]) == vidbytok(stari)


def test_render_resumes_partial_and_is_atomic(tmp_path: Path) -> None:
    src = _kadry(tmp_path / "k", [f"{i:03d}.jpg" for i in range(1, 6)])
    out = tmp_path / "pp"
    assert PG.render(src, out)["pages"] == 5
    for f in sorted(out.glob("*.jpg"))[2:]:
        f.unlink()
    (out / ".0003.tmp").write_bytes(b"half")  # залишок перерваного запису не рахується сторінкою
    res = PG.render(src, out, target_h=40)
    assert "skip" not in res
    assert sorted(p.name for p in out.glob("*.jpg")) == [f"{i:04d}.jpg" for i in range(1, 6)]
    assert PG.render(src, out, target_h=40)["skip"]


def test_render_pdf_resumes_partial(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    pdf = tmp_path / "a.pdf"
    doc = pdfium.PdfDocument.new()
    for _ in range(3):
        doc.new_page(100, 150)
    doc.save(str(pdf))
    doc.close()
    out = tmp_path / "pp"
    PG.render(pdf, out, target_h=60)
    (out / "0003.jpg").unlink()
    assert "skip" not in PG.render(pdf, out, target_h=60)
    assert (out / "0003.jpg").exists()
    assert PG.render(pdf, out, target_h=60)["skip"]


def test_render_16bit_tiff_scaled_not_clipped(tmp_path: Path) -> None:
    d = tmp_path / "k"
    d.mkdir()
    a = np.full((20, 30), 40000, dtype=np.uint16)
    Image.fromarray(a).save(d / "1.tif")
    assert Image.open(d / "1.tif").mode.startswith("I;16")
    PG.render(d, tmp_path / "pp", target_h=20)
    v = Image.open(tmp_path / "pp" / "0001.jpg").getpixel((5, 5))
    assert 150 <= v <= 165, v  # 40000/65535*255 ≈ 156; обрізання дало б 255


def test_render_multiframe_tiff_warns(tmp_path: Path) -> None:
    d = tmp_path / "k"
    d.mkdir()
    fr = [Image.new("L", (30, 20), v) for v in (10, 200)]
    fr[0].save(d / "1.tif", save_all=True, append_images=fr[1:])
    res = PG.render(d, tmp_path / "pp", target_h=20)
    assert res["pages"] == 1
    assert any("1.tif" in w and "перший" in w for w in res["warnings"])
    assert Image.open(tmp_path / "pp" / "0001.jpg").getpixel((5, 5)) < 60


# ── vl_table ─────────────────────────────────────────────────────────────────


def _tbl(*rows: list[str], attrs: str = "") -> str:
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td{attrs}>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def test_year_without_month_after_title_is_date_not_folio() -> None:
    from nyshporka.opysy import vl_table as VT

    md = _tbl(["1", "Дело о чём-то важном", "1850", "12"], ["2", "Дело о другом деле", "1851", "7"])
    sides, _ = VT.records(md)
    r = sides[0]
    assert [x["no"] for x in r] == [1, 2]
    assert r[0]["dates"] == ["1850"] and r[0]["folios"] == ["12"]
    assert r[1]["dates"] == ["1851"] and r[1]["folios"] == ["7"]


def test_year_as_last_cell_stays_folio_like_before() -> None:
    from nyshporka.opysy import vl_table as VT

    md = _tbl(["1", "Дело о чём-то важном", "1850"], ["2", "Дело о другом деле", "1851"])
    r = VT.records(md)[0][0]
    assert r[0]["folios"] == ["1850"] and r[0]["dates"] == []


def test_nonnumeric_rowspan_does_not_break_table() -> None:
    from nyshporka.opysy import vl_table as VT

    md = ("<table><tr><td rowspan=\"x\" colspan=\"\">1</td><td>Дело о чём-то важном</td><td>12</td></tr>"
          "<tr><td>2</td><td>Дело о другом деле</td><td>7</td></tr></table>")
    r = VT.records(md)[0][0]
    assert [x["no"] for x in r] == [1, 2]
