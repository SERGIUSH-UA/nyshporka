"""📋 Читання бланка поклітинно: сітка за лініями, голос `-cells`, пошук і кроп.

Усе на вигаданому бланку, намальованому PIL: рамка з горизонталей і вертикалей
на світлому тлі. Ні справжніх кадрів, ні справжніх імен.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

W, H = 2400, 3200
ROW_YS = [400 + i * 200 for i in range(9)]            # 9 горизонталей → 8 рядків
COL_XS = [150, 700, 1300, 1800, 2250]                 # 5 вертикалей → 4 колонки + поля


def fake_form(*, skew: bool = False) -> Image.Image:
    im = Image.new("L", (W, H), 235)
    d = ImageDraw.Draw(im)
    for y in ROW_YS:
        d.line([(COL_XS[0], y), (COL_XS[-1], y)], fill=40, width=4)
    for x in COL_XS:
        d.line([(x, ROW_YS[0]), (x, ROW_YS[-1])], fill=40, width=4)
    return im.convert("RGB")


def book_page() -> Image.Image:
    """Книжкова сторінка: рядки «тексту» короткими рисками, жодної таблиці."""
    im = Image.new("L", (W, H), 235)
    d = ImageDraw.Draw(im)
    for k in range(40):
        y = 300 + k * 65
        for x in range(300, 2000, 90):
            d.line([(x, y), (x + 55, y + 3)], fill=60, width=5)
    return im.convert("RGB")


def test_grid_cells_count_and_positions() -> None:
    from nyshporka.htr import form_cells as FC

    g = FC.find_grid(fake_form())
    assert g.found and g.h_lines == len(ROW_YS)
    # 8 рядків × (ліве поле + 4 колонки + праве поле)
    assert len(g.cells) == 8 * 6
    first = g.cells[:6]
    xs = sorted({x for c in first for x in (c[0], c[2])})
    assert xs[0] == 0 and xs[-1] == W
    for want, got in zip(COL_XS, xs[1:-1], strict=True):
        assert abs(want - got) <= 3
    rows = sorted({(c[1], c[3]) for c in g.cells})
    assert len(rows) == 8
    for (y0, y1), (a, b) in zip(rows, zip(ROW_YS, ROW_YS[1:], strict=False), strict=True):
        assert abs(y0 - a) <= 3 and abs(y1 - b) <= 3


def test_crop_boxes_pad_upward_and_stay_in_frame() -> None:
    from nyshporka.htr import form_cells as FC

    g = FC.find_grid(fake_form())
    cell, box = g.cells[1], g.crops[1]
    h = cell[3] - cell[1]
    assert box[1] == int(cell[1] - h * FC.PAD_UP)        # запас угору — на рукопис над лінією
    assert box[3] == int(cell[3] + h * FC.PAD_DOWN)
    assert all(0 <= b[0] < b[2] <= W and 0 <= b[1] < b[3] <= H for b in g.crops)


def test_empty_and_book_pages_give_no_cells() -> None:
    from nyshporka.htr import form_cells as FC

    assert not FC.find_grid(Image.new("RGB", (W, H), "white")).found
    assert FC.find_grid(Image.new("RGB", (W, H), "white")).crops == []
    book = FC.find_grid(book_page())
    assert not book.found and book.crops == []


def test_tiny_image_does_not_crash() -> None:
    from nyshporka.htr import form_cells as FC

    assert not FC.find_grid(Image.new("RGB", (4, 4), "white")).found


# ── голос `-cells` у сторінці стору ──────────────────────────────────────────
@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W_

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W_.reset()
    W_.use(W_.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W_.reset()


def _make_case(space: Path) -> tuple[Path, Path]:
    case_dir = space / "data" / "raw" / "проба" / "spr-1"
    case_dir.mkdir(parents=True)
    fake_form().save(case_dir / "0001.jpg", quality=90)
    book_page().save(case_dir / "0002.jpg", quality=90)
    # основний прогін: мета з кутом повороту, текст і рамки
    base = space / "reports" / "htr" / "проба"
    base.mkdir(parents=True)
    (base / "0001.txt").write_text("основний рядок\n", encoding="utf-8")
    (base / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic", "case_dir": str(case_dir),
        "case_key": "ТЕСТ 1-1-1",
        "pages": {"0001.jpg": {"lines": 1, "orient": 0},
                  "0002.jpg": {"lines": 1, "orient": 0}}}), encoding="utf-8")
    return case_dir, base


def _run_cells(case_dir: Path, base: Path) -> tuple[dict, Path]:
    from nyshporka.htr import cells_read as CR

    seen: list[int] = []

    def decode(crops):
        seen.append(len(crops))
        # впізнаваний «текст» у кожній клітинці: номер за порядком
        return [f"клітинка {n:03d}" for n in range(len(crops))]

    frames = sorted(case_dir.glob("*.jpg"))
    out = base.parent / f"{base.name}-cells"
    meta = CR.process(
        frames, out, decode, orient_of=CR.base_orient(base),
        want=CR.parse_ranges("", len(frames)), say=lambda _l: None,
        meta_args=dict(case_dir=case_dir, case_key="ТЕСТ 1-1-1",
                       model="pysar_cyr_v17.pt", engine="parseq", script="cyrillic",
                       device="cpu", base_run=base.name))
    assert seen == [48]                                    # книжкову сторінку не читали
    return meta, out


def test_cells_run_layout_and_meta(space: Path) -> None:
    case_dir, base = _make_case(space)
    meta, out = _run_cells(case_dir, base)
    assert out.name == "проба-cells"
    # сторінка з сіткою — файли є; книжкова — жодного файла, а не порожній
    assert (out / "0001.txt").is_file() and (out / "0001.lines.json").is_file()
    assert not (out / "0002.txt").exists() and not (out / "0002.lines.json").exists()
    assert len((out / "0001.txt").read_text(encoding="utf-8").splitlines()) == 48
    geo = json.loads((out / "0001.lines.json").read_text(encoding="utf-8"))
    assert geo["size"] == [W, H] and len(geo["boxes"]) == 48
    disk = json.loads((out / "_htr_meta.json").read_text(encoding="utf-8"))
    assert disk == meta
    assert disk["case_key"] == "ТЕСТ 1-1-1" and disk["engine"] == "parseq"
    assert disk["case_dir"] == str(case_dir).replace("\\", "/")
    assert disk["model"] == "pysar_cyr_v17.pt+cells" and disk["voice"] == "cells"
    assert disk["cells_of"] == "проба"
    assert disk["form_cells"] == {"pages_with_grid": 1, "pages_without_grid": 1}
    assert list(disk["pages"]) == ["0001.jpg"] and disk["pages"]["0001.jpg"]["lines"] == 48


def test_cells_voice_is_searchable_and_crop_hits_the_cell(space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    case_dir, base = _make_case(space)
    _meta, out = _run_cells(case_dir, base)
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(["проба", "проба-cells"]))

    names = {r["name"] for r in T.scope_runs("проба")["rows"]}
    assert names == {"проба", "проба-cells"}

    hits = ST.grep("клітинка 007", ["проба-cells"])
    assert hits, "голос -cells не знайдено текстовим пошуком"

    geo = json.loads((out / "0001.lines.json").read_text(encoding="utf-8"))
    crop = T.crop("проба-cells", "1", 8, with_next=False, pad=0, out=space / "c.png")
    assert not crop.get("error"), crop
    assert crop["text"] == "клітинка 007"
    assert crop["box"] == geo["boxes"][7]                 # рядок 8 = восьма клітинка
    with Image.open(space / "c.png") as im:
        assert im.size == (crop["box"][2] - crop["box"][0], crop["box"][3] - crop["box"][1])


# ── план і відмови ───────────────────────────────────────────────────────────
def test_plan_refuses_a_case_with_frames_only_in_the_cloud(tmp_path: Path) -> None:
    from nyshporka.htr import cells as CE
    from nyshporka.htr.run import ReadError

    (tmp_path / "_r2_frames.json").write_text(json.dumps({"frames": [{"name": "1.jpg"}]}),
                                              encoding="utf-8")
    with pytest.raises(ReadError, match="лише маніфест"):
        CE.plan(tmp_path)


def test_plan_refuses_missing_and_empty_dirs(tmp_path: Path) -> None:
    from nyshporka.htr import cells as CE
    from nyshporka.htr.run import ReadError

    with pytest.raises(ReadError, match="теки немає"):
        CE.plan(tmp_path / "нема")
    with pytest.raises(ReadError, match="немає зображень"):
        CE.plan(tmp_path)


def test_parse_ranges() -> None:
    from nyshporka.htr import cells_read as CR

    assert CR.parse_ranges("", 3) == {1, 2, 3}
    assert CR.parse_ranges("1-2,5", 9) == {1, 2, 5}
