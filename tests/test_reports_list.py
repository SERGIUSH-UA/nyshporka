"""📝 Звіти досліджень для консолі: перелік і читання, без виходу за межі.

Шлях у `reports.read` приходить із браузера, тож тест головний — що `../`,
абсолютний шлях і `htr/` відмовляють, а не читають.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    rep = tmp_path / "reports"
    (rep / "research").mkdir(parents=True)
    (rep / "htr").mkdir()
    (rep / "top.md").write_text("без заголовка\n", encoding="utf-8")
    (rep / "research" / "sydoruk.md").write_text(
        "---\nkind: research\n---\n\n# Сидоруки в ревізії\n\nтекст\n", encoding="utf-8")
    (rep / "htr" / "RESUME.md").write_text("# прогони\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("# поза звітами\n", encoding="utf-8")
    os.utime(rep / "top.md", (1_000_000, 1_000_000))
    yield tmp_path
    W.reset()


def test_list_has_titles_kinds_and_no_htr(space: Path) -> None:
    rows = O.call("reports.list", {}).data["rows"]
    assert [(r["path"], r["title"], r["kind"]) for r in rows] == [
        ("research/sydoruk.md", "Сидоруки в ревізії", "research"),
        ("top.md", "top", "")]


def test_read_gives_the_text(space: Path) -> None:
    d = O.call("reports.read", {"path": "research/sydoruk.md"}).data
    assert d["title"] == "Сидоруки в ревізії" and "текст" in d["text"]


@pytest.mark.parametrize("bad", ["../secret.md", "htr/RESUME.md", "research/../../secret.md",
                                 "research", "nope.md"])
def test_read_refuses_outside_htr_and_missing(space: Path, bad: str) -> None:
    assert not O.call("reports.read", {"path": bad}).ok


def test_read_refuses_an_absolute_path(space: Path) -> None:
    env = O.call("reports.read", {"path": str(space / "reports" / "top.md")})
    assert not env.ok and "абсолютний" in env.error
