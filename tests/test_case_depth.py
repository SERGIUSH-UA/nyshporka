"""Глибина обходу тек справ — з простору, а обрізане стелею видно (відгук №6).

Тека-група над архівом (партія завантаження) додає рівень, і при зашитій стелі 4
вся гілка під нею зникала з бібліотеки мовчки: пропущена справа нічим не
відрізнялась від справи, якої немає.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.cases import walk
from nyshporka.core import workspace as W


def _frame(root: Path, rel: str) -> None:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "0001.jpg").write_bytes(b"x")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _frame(tmp_path, "DAVIO/137/2/6")
    _frame(tmp_path, "batch-2/DAVIO/137/2/6")
    return tmp_path


def _cases(base: Path, **kw: object) -> list[str]:
    return ["/".join(s.rel_parts) for s in walk.walk_root(base, **kw)  # type: ignore[arg-type]
            if s.n_img]


def test_ceiling_reports_the_branch_it_cut(tree: Path) -> None:
    cut: list[tuple[int, list[Path]]] = []
    got = _cases(tree, max_depth=4, on_truncate=lambda d, below: cut.append((d, below)))
    assert got == ["DAVIO/137/2/6"]
    assert cut == [(4, [tree / "batch-2" / "DAVIO" / "137" / "2"])]


def test_deeper_ceiling_sees_the_case_and_cuts_nothing(tree: Path) -> None:
    cut: list[object] = []
    got = _cases(tree, max_depth=6, on_truncate=lambda d, below: cut.append(below))
    assert sorted(got) == ["DAVIO/137/2/6", "batch-2/DAVIO/137/2/6"]
    assert cut == []


def test_service_subfolder_of_a_case_is_not_a_cut(tmp_path: Path) -> None:
    """Тека справи з кадрами й `_crops` усередині — не тека-група."""
    _frame(tmp_path, "DAVIO/137/2/6")
    (tmp_path / "DAVIO/137/2/6/_crops/x").mkdir(parents=True)
    cut: list[object] = []
    list(walk.walk_root(tmp_path, max_depth=4, on_truncate=lambda d, b: cut.append(b)))
    assert cut == []


def test_depth_comes_from_the_workspace(tree: Path) -> None:
    W.use(W.Workspace(root=tree, name="тест", origin="test", case_depth=6))
    try:
        assert walk.case_depth() == 6
        assert sorted(_cases(tree)) == ["DAVIO/137/2/6", "batch-2/DAVIO/137/2/6"]
    finally:
        W.reset()


@pytest.mark.parametrize(("cfg", "want"), [({}, 4), ({"case_depth": 6}, 6),
                                           ({"case_depth": "шість"}, 4),
                                           ({"case_depth": 0}, 4), ({"case_depth": -3}, 1)])
def test_marker_value_is_read_safely(cfg: dict[str, object], want: int) -> None:
    assert W._case_depth(cfg) == want


def test_full_scan_records_the_cut_for_doctor(tree: Path) -> None:
    from nyshporka import library as L
    from nyshporka.setup import doctor

    W.use(W.Workspace(root=tree, name="тест", origin="test",
                      extra_case_roots=(tree,)))
    try:
        L._scan_disk_cases()
        rep = walk.cut_report()
        assert rep is not None
        assert rep["depth"] == 4
        assert rep["cut"] == ["batch-2/DAVIO/137/2"]
        check = doctor._case_depth()
        assert check.level == "warn"
        assert "case_depth = 6" in check.detail
    finally:
        W.reset()
