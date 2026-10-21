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
