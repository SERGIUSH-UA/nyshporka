"""Запас угору в раннері: межа рядка піднімається лише над базовою лінією, геометрія виходу — вихідна."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

RUNNER = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"


def _lift_lines():
    """`_lift_lines` з раннера без імпорту самого раннера (він тягне kraken і torch)."""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_lift_lines")
    ns: dict = {"np": np}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(RUNNER), "exec"), ns)
    return ns["_lift_lines"]


def _seg():
    from dataclasses import dataclass

    @dataclass
    class Line:
        baseline: list
        boundary: list

    @dataclass
    class Seg:
        lines: list

    # рядок заввишки 100: базова лінія y=80, межа — прямокутник y 0…100
    return Seg(lines=[Line(baseline=[(0, 80), (200, 80)], boundary=[(0, 0), (200, 0), (200, 100), (0, 100)])])


def test_lift_moves_only_the_top_of_the_line():
    out = _lift_lines()(_seg(), 0.1)
    # верх (над базовою лінією) піднято на 10 % висоти, але не вище краю сторінки; низ на місці
    assert out.lines[0].boundary == [(0, 0), (200, 0), (200, 100), (0, 100)]
    seg = _seg()
    seg.lines[0].boundary = [(0, 30), (200, 30), (200, 130), (0, 130)]
    seg.lines[0].baseline = [(0, 110), (200, 110)]
    out = _lift_lines()(seg, 0.1)
    assert out.lines[0].boundary == [(0, 20), (200, 20), (200, 130), (0, 130)]
    assert out.lines[0].baseline == [(0, 110), (200, 110)]


def test_lift_leaves_the_source_segmentation_untouched():
    seg = _seg()
    seg.lines[0].boundary = [(0, 30), (200, 30), (200, 130), (0, 130)]
    seg.lines[0].baseline = [(0, 110), (200, 110)]
    _lift_lines()(seg, 0.1)
    assert seg.lines[0].boundary == [(0, 30), (200, 30), (200, 130), (0, 130)]


def test_zero_lift_returns_the_same_object():
    seg = _seg()
    assert _lift_lines()(seg, 0.0) is seg
