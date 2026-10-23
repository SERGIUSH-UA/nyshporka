"""Перелік мет прогонів без `glob`: один обхід кореня, порядок як у `sorted(Path)`."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nyshporka import htr_store as S


def test_meta_stats_skips_runs_without_meta_and_keeps_path_order(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, meta in (("B-run", True), ("c-run", False), ("a-run", True), ("d-run", True)):
        d = tmp_path / name
        d.mkdir()
        (d / "0001.txt").write_text("рядок", encoding="utf-8")
        if meta:
            (d / "_htr_meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "stray.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path)

    got = [name for name, _ in S._meta_stats()]
    want = [p.parent.name for p in sorted(tmp_path.glob("*/_htr_meta.json"))]
    assert got == want
    assert "c-run" not in got and len(got) == 3
    if os.name == "nt":
        # без регістру, як `sorted(Path)` на Windows: «a-run» перед «B-run»
        assert got == ["a-run", "B-run", "d-run"]


def test_stamp_and_meta_list_share_one_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Штамп і перелік мет — один обхід кореня на запит (доти два: 33 тис. `stat`)."""
    from nyshporka.core.scope import read_scope

    for name in ("a-run", "b-run"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "_htr_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path)
    walks: list[int] = []
    real = S._scan_now
    monkeypatch.setattr(S, "_scan_now", lambda: walks.append(1) or real())
    with read_scope():
        stamp = S._runs_stamp()
        names = [n for n, _ in S._meta_stats()]
    assert walks == [1] and stamp[0] == 2 and names == ["a-run", "b-run"]
