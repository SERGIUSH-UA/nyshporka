"""`--whole-line`: кадр — це вже рядок; у модель іде сам кадр, без сегментації й повороту.

Раннер тягне kraken і torch, тож функції беруться з його тексту (`ast`), як у
`test_runner_line_lift.py`.
"""
from __future__ import annotations

import ast
from pathlib import Path

from PIL import Image

RUNNER = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"
TEXT = RUNNER.read_text(encoding="utf-8")


def _ns():
    tree = ast.parse(TEXT)
    want = {"_line_crops", "WHOLE_LINE_TAG", "PARSEQ_MIN_CROP_W"}
    body = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in want:
            body.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if isinstance(tgt, ast.Name) and tgt.id in want:
                body.append(n)
    ns: dict = {"Image": Image}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(RUNNER), "exec"), ns)
    return ns


class _Seg:
    def __init__(self, tag):
        self.imagename = tag
        self.lines = []


def test_whole_line_crop_is_the_frame_itself():
    ns = _ns()
    im = Image.new("RGB", (120, 40), "white")
    crops = ns["_line_crops"](im, _Seg(ns["WHOLE_LINE_TAG"]))
    assert crops == [im]
    assert ns["_line_crops"].boxes == [[0, 0, 120, 40]]
    assert len(ns["_line_crops"].polys) == 1


def test_too_narrow_frame_gives_no_line_but_no_crash():
    ns = _ns()
    im = Image.new("RGB", (ns["PARSEQ_MIN_CROP_W"] - 1, 40), "white")
    assert ns["_line_crops"](im, _Seg(ns["WHOLE_LINE_TAG"])) == []
    assert ns["_line_crops"].boxes == []


def test_flag_switches_off_orientation_enhance_and_segmenter():
    assert '"--whole-line"' in TEXT
    assert 'args.force_orient, args.enhance, args.orient_check = 0, "none", False' in TEXT
    assert "segmenter = WholeLineSegmenter()" in TEXT
    # сегментатор без сегментації — відмова, а не порожній прохід
    assert "whole-line + segment-only" in TEXT


def test_go_density_without_local_probe():
    """`-p whole_line=1` і `-p lines_per_page=N` — щільність без сегментації вибірки на
    локальній карті (21.11.2026: вибірка ганяла kraken на кропах номерів і смугах)."""
    from nyshporka.cloud import go as G

    assert G._whole_line(["whole_line=1"]) and not G._whole_line(["whole_line=0"])
    assert G._param_float(["pace=cheap", "lines_per_page=20"], "lines_per_page") == 20.0
    said = []
    assert G._Fixed(20.0).of(None, None, "", lambda k, s: said.append(s)) == 20.0
    assert G._WholeLine().of(None, None, "", lambda k, s: said.append(s)) == 1.0
    assert len(said) == 2
