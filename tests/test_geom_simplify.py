"""📐 Беззбиткове прорідження полігонів: контур і маска ті самі, точок менше.

Замір 03.11.2026 (15,6 тис. полігонів справжніх прогонів): 28–31 точка на
полігон, з них 8–9 на прямій; поверх gzip це −17 % геометрії. Тут доводиться, що
маска рядка не змінюється ні на піксель, що «шпичку» не зрізано, і що раннер
(без пакета) проріджує рівно так само, як ядро.
"""
from __future__ import annotations

import ast
import gzip
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from nyshporka.htr import layout as HL
from nyshporka.htr.geom_simplify import drop_collinear, simplify_payload

SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka"


def _mask(poly: list[list[int]], w: int = 220, h: int = 90) -> np.ndarray:
    im = Image.new("1", (w, h), 0)
    ImageDraw.Draw(im).polygon([tuple(p) for p in poly], fill=1)
    return np.array(im, dtype=bool)


def _line_poly(rng: random.Random) -> list[list[int]]:
    """Полігон рядка як у сегментатора: верх і низ ламаними, з точками на прямій,
    дублікатами й рівними ділянками."""
    xs = sorted(rng.sample(range(5, 210), rng.randint(4, 14)))
    top = []
    for x in xs:
        y = rng.randint(10, 30)
        top.append([x, y])
        if rng.random() < 0.4:                       # точка посеред рівного відрізка
            top.append([x + 2, y])
            top.append([x + 4, y])
        if rng.random() < 0.15:                      # дублікат
            top.append([x + 4, y] if top[-1] == [x + 4, y] else list(top[-1]))
    bottom = [[x, rng.randint(50, 80)] for x in reversed(xs)]
    for k in range(len(bottom) - 1):                 # колінеарна точка між вершинами
        if rng.random() < 0.3:
            (ax, ay), (bx, by) = bottom[k], bottom[k + 1]
            if (ax - bx) % 2 == 0 and (ay - by) % 2 == 0:
                bottom.insert(k + 1, [(ax + bx) // 2, (ay + by) // 2])
    return top + bottom


def test_masks_are_identical_on_random_line_polygons() -> None:
    rng = random.Random(11)
    dropped = 0
    for _ in range(2000):
        p = _line_poly(rng)
        q = drop_collinear(p)
        dropped += len(p) - len(q)
        assert np.array_equal(_mask(p), _mask(q)), p
        assert all(pt in p for pt in q)
    assert dropped > 1000, "перевірка беззмістовна: проріджувати не було чого"


def test_spike_is_kept() -> None:
    """Колінеарна точка, де контур розвертається, — не лишня: растр її малює."""
    p = [[0, 0], [10, 0], [20, 0], [15, 0], [15, 10], [0, 10]]
    q = drop_collinear(p)
    assert [20, 0] in q
    assert np.array_equal(_mask(p), _mask(q))


def test_straight_runs_go_duplicates_stay() -> None:
    p = [[0, 0], [5, 0], [10, 0], [10, 5], [10, 10], [0, 10], [0, 5]]
    assert drop_collinear(p) == [[0, 0], [10, 0], [10, 10], [0, 10]]
    # 🔴 Дубль сусідньої точки — не лишній: на справжніх прогонах його зняття
    # змінювало маску на піксель.
    d = [[0, 0], [5, 0], [5, 0], [10, 0], [10, 10], [0, 10]]
    assert drop_collinear(d).count([5, 0]) == 2


def test_slanted_collinear_point_stays() -> None:
    """🔴 Справжній випадок 127-1015-210: точка точно на похилому відрізку, а растр
    PIL ламаної й прямого відрізка різниться на піксель — тож вона лишається."""
    p = [[429, 892], [480, 895], [483, 881], [483, 829], [466, 829], [435, 808],
         [430, 878], [429, 892]]
    q = drop_collinear(p)
    assert [430, 878] in q
    assert np.array_equal(_mask([[x - 425, y - 805] for x, y in p], 70, 100),
                          _mask([[x - 425, y - 805] for x, y in q], 70, 100))


def test_real_duplicate_case_keeps_the_mask() -> None:
    """Форма зі справжнього прогону 127-1015-210: дубль вершини дав +1 піксель."""
    p = [[0, 0], [40, 2], [40, 2], [80, 0], [80, 30], [40, 31], [0, 30]]
    assert np.array_equal(_mask(p), _mask(drop_collinear(p)))


def test_degenerate_inputs_are_left_alone() -> None:
    assert drop_collinear(None) is None
    assert drop_collinear([[0, 0], [1, 1], [2, 2]]) == [[0, 0], [1, 1], [2, 2]]
    assert drop_collinear([]) == []
    assert simplify_payload({"boxes": [[0, 0, 1, 1]]}) == {"boxes": [[0, 0, 1, 1]]}


def test_runner_mirror_matches_core() -> None:
    """Раннер їде на бокс без пакета — його `drop_collinear` мусить бути тим самим."""
    tree = ast.parse((SRC / "htr" / "runner.py").read_text(encoding="utf-8"))
    names = {"drop_collinear", "_geom_redundant"}
    code = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in code} == names
    ns: dict = {}
    exec(compile(ast.Module(body=code, type_ignores=[]), "runner_mirror", "exec"), ns)
    rng = random.Random(3)
    for _ in range(1500):
        p = _line_poly(rng)
        assert ns["drop_collinear"](p) == drop_collinear(p)


def test_writer_thins_polys(tmp_path: Path) -> None:
    p = [[0, 0], [5, 0], [10, 0], [10, 10], [0, 10]]
    HL.write_geometry(tmp_path, "0001", {"boxes": [[0, 0, 10, 10]], "polys": [p]})
    got = HL.load_geometry(tmp_path, "0001")
    assert got == {"boxes": [[0, 0, 10, 10]], "polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]}


def test_thinned_bytes_keeps_bytes_when_nothing_to_drop() -> None:
    raw = json.dumps({"boxes": [[0, 0, 1, 1]], "polys": [[[0, 0], [9, 0], [9, 9], [0, 9]]]},
                     ensure_ascii=False).encode()
    assert HL.thinned_bytes(raw) is raw


# ── compact ──────────────────────────────────────────────────────────────────

def _plain(d: Path, stem: str, geo: dict) -> Path:
    f = d / f"{stem}.lines.json"
    f.write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    t = time.time() - 3600
    os.utime(f, (t, t))
    return f


def test_compact_thins_and_keeps_everything_else(tmp_path: Path) -> None:
    from nyshporka.disk import compact as C

    geo = {"size": [100, 50], "boxes": [[0, 0, 10, 10]],
           "polys": [[[0, 0], [5, 0], [10, 0], [10, 10], [0, 10]]]}
    f = _plain(tmp_path, "0001", geo)
    C.compact_file(f)
    got = json.loads(gzip.decompress((tmp_path / "0001.lines.json.gz").read_bytes()))
    assert got == {**geo, "polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]}


def test_compact_refuses_thinning_that_changed_anything_else(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Друга рука: проріджувач, що зачепив рамки чи контур, не проходить."""
    from nyshporka.disk import compact as C

    geo = {"boxes": [[0, 0, 10, 10]], "polys": [[[0, 0], [5, 0], [10, 0], [10, 10], [0, 10]]]}
    f = _plain(tmp_path, "0001", geo)
    bad_boxes = json.dumps({**geo, "boxes": [[0, 0, 9, 9]]}).encode()
    monkeypatch.setattr(C.HL, "thinned_bytes", lambda raw: bad_boxes)
    with pytest.raises(ValueError):
        C.compact_file(f)
    cut_corner = json.dumps({**geo, "polys": [[[0, 0], [10, 10], [0, 10]]]}).encode()
    monkeypatch.setattr(C.HL, "thinned_bytes", lambda raw: cut_corner)
    with pytest.raises(ValueError):
        C.compact_file(f)
    assert f.is_file() and not list(tmp_path.glob("*.gz"))


def test_compact_accepts_an_unthinned_gz_pair(tmp_path: Path) -> None:
    """Пара з обриву, де `.gz` лишився від стиснення до проріджування, — той самий вміст."""
    from nyshporka.disk import compact as C

    geo = {"boxes": [[0, 0, 10, 10]], "polys": [[[0, 0], [5, 0], [10, 0], [10, 10], [0, 10]]]}
    f = _plain(tmp_path, "0001", geo)
    (tmp_path / "0001.lines.json.gz").write_bytes(HL.gz_blob(f.read_bytes()))
    C.compact_file(f)
    assert not f.exists()
