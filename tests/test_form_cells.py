"""📋 Читання бланка поклітинно: сітка за лініями, голос `-cells`, пошук і кроп.

Усе на вигаданому бланку, намальованому PIL: рамка з горизонталей і вертикалей
на світлому тлі. Ні справжніх кадрів, ні справжніх імен.
"""
from __future__ import annotations

import dataclasses
import json
from itertools import pairwise
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
    for (y0, y1), (a, b) in zip(rows, pairwise(ROW_YS), strict=True):
        assert abs(y0 - a) <= 3 and abs(y1 - b) <= 3


def test_crop_boxes_pad_upward_and_stay_in_frame() -> None:
    from nyshporka.htr import form_cells as FC

    g = FC.find_grid(fake_form())
    cell, box = g.cells[1], g.crops[1]
    h = cell[3] - cell[1]
    assert box[1] == int(cell[1] - h * FC.PAD_UP)        # запас угору — на рукопис над лінією
    assert box[3] == int(cell[3] + h * FC.PAD_DOWN)
    assert all(0 <= b[0] < b[2] <= W and 0 <= b[1] < b[3] <= H for b in g.crops)


def test_a_skewed_form_is_levelled_and_still_found() -> None:
    """Нахил 2°: без вирівнювання горизонталі розсипаються й сітки немає."""
    from nyshporka.htr import form_cells as FC

    tilted = fake_form().rotate(2.0, resample=Image.Resampling.BILINEAR, fillcolor=(235, 235, 235))
    assert abs(FC.page_angle(tilted) - 2.0) <= 0.15
    g = FC.find_grid(tilted)
    assert g.found and len(g.crops) >= 40
    assert g.parts[0].angle != 0
    assert all(0 <= b[0] < b[2] <= W and 0 <= b[1] < b[3] <= H for b in g.crops)
    assert len(g.images(tilted)) == len(g.crops)


PW = 1900                                             # сторінка розвороту


def spread() -> Image.Image:
    """Розворот: дві сторінки з власними таблицями й порожнім корінцем посередині."""
    page = fake_form().resize((PW, H))
    im = Image.new("RGB", (2 * PW + 200, H), (235, 235, 235))
    im.paste(page, (0, 0))
    im.paste(page.rotate(1.5, resample=Image.Resampling.BILINEAR, fillcolor=(235, 235, 235)),
             (PW + 200, 0))
    return im


def test_a_spread_is_split_at_the_gutter_and_each_page_levelled() -> None:
    from nyshporka.htr import form_cells as FC

    im = spread()
    parts = FC.split_spread(im)
    assert len(parts) == 2 and PW <= parts[0][1] <= PW + 200
    g = FC.find_grid(im)
    assert [p.angle == 0 for p in g.parts] == [True, False]
    assert {a[0] for a in g.addr} == {0, 1}
    # альбомний бланк на всю ширину кадру — не розворот: горизонталі перетинають середину
    wide = fake_form().resize((H, W))
    assert FC.split_spread(wide) == [(0, H)]


def test_a_tall_cell_is_addressed_but_not_read() -> None:
    """Графа книжкового бланка (висока клітинка з кількома рядками руки) у кропи не
    йде: її рядки краще читає звичайна сегментація. Адресу ж має сусідня клітинка."""
    from nyshporka.htr import form_cells as FC

    im = Image.new("L", (W, H), 235)
    d = ImageDraw.Draw(im)
    ys = [300, 450, 600, 2400, 2550]                  # третій рядок таблиці — високий
    for y in ys:
        d.line([(150, y), (2250, y)], fill=40, width=4)
    for x in (150, 1200, 2250):
        d.line([(x, ys[0]), (x, ys[-1])], fill=40, width=4)
    g = FC.find_grid(im.convert("RGB"))
    assert g.found
    rows = {a[1] for a in g.addr}
    assert 2 not in rows and {0, 1, 3} <= rows
    assert any(c[3] - c[1] > H * FC.MAX_CELL_H for c in g.cells)   # сама графа відома


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
    assert disk["form_cells"] == {"pages_with_grid": 1, "pages_without_grid": 1,
                                  "no_grid": ["0002.jpg"]}
    # адреса кожного кропа: сторінка, рядок таблиці, колонка, підрядок
    assert len(geo["cells"]) == 48 and geo["cells"][0] == [0, 0, 0]
    assert {tuple(c[:2]) for c in geo["cells"]} == {(0, r) for r in range(8)}
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


# ── план: прапорець людини або паспорт справи ────────────────────────────────
def test_the_passport_field_form_turns_cells_on(tmp_path: Path) -> None:
    from nyshporka.htr import run as RUN

    assert RUN.form_of_case(tmp_path) == ""
    assert RUN._form_choice(tmp_path, None) == (False, "")
    (tmp_path / "_source.json").write_text(json.dumps({"form": "zags_birth"}),
                                           encoding="utf-8")
    got = RUN._form_choice(tmp_path, None)
    assert got[0] and "zags_birth" in got[1]
    (tmp_path / "_source.json").write_text(json.dumps({"form": True}), encoding="utf-8")
    assert RUN.form_of_case(tmp_path) == "true"
    # слово людини важить більше за паспорт
    assert RUN._form_choice(tmp_path, False)[0] is False


def test_the_runner_command_carries_the_flag(tmp_path: Path) -> None:
    from nyshporka.htr.run import Plan

    p = Plan(case_dir=tmp_path, out_dir=tmp_path / "out", model=tmp_path / "m.pt",
             script="cyrillic", frames=1, python=tmp_path / "py", runner=tmp_path / "r.py")
    assert "--form-cells" not in p.command()
    assert "--form-cells" in dataclasses.replace(p, form_cells=True).command()


def test_runner_completeness_counts_a_page_without_grid_as_done(tmp_path: Path) -> None:
    """Сторінка без сітки тексту голосу не має — лише позначку; повнота не бреше."""
    from nyshporka.htr import cells_read as CR
    from nyshporka.htr import runner as RN

    out, cells = tmp_path / "out", tmp_path / "out-cells"
    out.mkdir()
    frames = [tmp_path / "0001.jpg", tmp_path / "0002.jpg", tmp_path / "0003.jpg"]
    for f in frames:
        (out / f"{f.stem}.txt").write_text("текст\n", encoding="utf-8")
    CR.write_page(cells, "0001", (["клітинка"], {"size": [1, 1], "boxes": [[0, 0, 1, 1]],
                                                  "cells": [[0, 0, 0]], "parts": []}))
    CR.write_page(cells, "0002", None)
    assert RN.missing_pages(frames, out, (cells,)) == ["0003.jpg"]
    CR.write_failed(cells, "0003", "RuntimeError: тест")
    assert RN.missing_pages(frames, out, (cells,)) == []
    assert RN.missing_pages(frames, out) == []                 # без клітинок — як було
    meta = CR.finish(cells, names={f.stem: f.name for f in frames}, case_dir=tmp_path,
                     case_key="", model="m.pt", engine="parseq", script="cyrillic",
                     device="cpu", base_run="out")
    assert list(meta["pages"]) == ["0001.jpg"]
    assert meta["form_cells"]["no_grid"] == ["0002.jpg"]
    assert meta["form_cells"]["failed"] == ["0003.jpg"]
    # позначка «сітки немає» зникає, коли сторінку перечитали з сіткою
    CR.write_page(cells, "0002", (["x"], {"size": [1, 1], "boxes": [[0, 0, 1, 1]],
                                          "cells": [[0, 0, 0]], "parts": []}))
    assert not (cells / "0002.nogrid").exists()


def test_parse_ranges() -> None:
    from nyshporka.htr import cells_read as CR

    assert CR.parse_ranges("", 3) == {1, 2, 3}
    assert CR.parse_ranges("1-2,5", 9) == {1, 2, 5}


# ── хмара: ті самі модулі на боксі, повнота голосу клітинок ──────────────────
def test_cloud_assets_carry_the_form_modules(tmp_path: Path) -> None:
    from nyshporka.cloud import supervised as SUP

    names = {arc for arc, _src in SUP.assets_inputs([])}
    assert {f"{SUP.ARC_SCRIPTS}/form_cells.py", f"{SUP.ARC_SCRIPTS}/cells_read.py"} <= names
    assert all(src.is_file() for arc, src in SUP.assets_inputs([]) if arc.endswith("cells.py")
               or arc.endswith("cells_read.py"))


def test_cloud_verify_counts_a_page_without_grid_as_done(tmp_path: Path) -> None:
    from nyshporka.cloud import verify as V

    out, cells, diak = tmp_path / "r", tmp_path / "r-cells", tmp_path / "r-diak_v10"
    for d in (out, cells, diak):
        d.mkdir()
    frames = [tmp_path / "0001.jpg", tmp_path / "0002.jpg"]
    for f in frames:
        (out / f"{f.stem}.txt").write_text("т", encoding="utf-8")
        (diak / f"{f.stem}.txt").write_text("т", encoding="utf-8")
    (cells / "0001.txt").write_text("к", encoding="utf-8")
    (cells / "0002.nogrid").write_text("", encoding="utf-8")
    assert V.missing_pages(frames, out, V.voice_dirs(out)) == []
    (diak / "0002.txt").unlink()
    (diak / "0002.nogrid").write_text("", encoding="utf-8")
    assert V.missing_pages(frames, out, V.voice_dirs(out)) == ["0002.jpg"]
