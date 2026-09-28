"""🧮 Консенсус вичиток, запис реєстру справ, тека фонду з чужих рук.

Аудит 29.09.2026:

  · `_merge_notes` брав статус і коментар аркуша з гілки A: коментар B
    губився, а `full` A перемагав `partial`/`unreadable` B — і аркуш, який дві
    вичитки прочитали по-різному, ставав «повним»;
  · збірка реєстру клала базу в tmp зі спільним ім'ям і замінювала без
    повтору: дві паралельні `cases build` валили одна одну;
  · `registry.merge` клав `fond_id`/`fond` у шлях як є — `..` виводив запис
    за межі `data/raw`.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.pagestore.models import PageNote
from nyshporka.records.consensus import _merge_notes


# ── консенсус аркуша ─────────────────────────────────────────────────────────
def _note(status: str, comment: str = "", **kw) -> PageNote:
    return PageNote(scan="0007.jpg", page_type="birth", status=status,
                    comment=comment, **kw)


@pytest.mark.parametrize("other", ["partial", "unreadable"])
def test_disagreeing_readings_are_not_full(other: str) -> None:
    for a, b in ((_note("full"), _note(other)), (_note(other), _note("full"))):
        (merged,) = _merge_notes([a], [b])
        assert merged.status == other


def test_both_comments_survive() -> None:
    a = _note("full", "нижній край обрізано")
    b = _note("full", "рядок 12 — прізвище під плямою")
    (merged,) = _merge_notes([a], [b])
    assert "нижній край обрізано" in merged.comment
    assert "рядок 12 — прізвище під плямою" in merged.comment
    # однаковий коментар не дублюється
    (same,) = _merge_notes([_note("full", "x")], [_note("full", "x")])
    assert same.comment == "x"


def test_agreeing_full_stays_full_and_b_fills_empty_fields() -> None:
    (merged,) = _merge_notes([_note("full")], [_note("full", sheet="31зв", agent="b")])
    assert merged.status == "full"
    assert (merged.sheet, merged.agent) == ("31зв", "b")


# ── запис реєстру справ ──────────────────────────────────────────────────────
@pytest.fixture
def quiet_build(monkeypatch):
    from nyshporka.cases import db as DB

    monkeypatch.setattr(DB, "collect_rows", lambda index, unreadable=None: ([], []))
    monkeypatch.setattr(DB, "_pulse_seq", lambda: 0)
    return DB


def test_registry_build_waits_out_a_busy_target(tmp_path: Path, quiet_build,
                                                monkeypatch) -> None:
    """Перша заміна падає (в'ювер тримає базу) — збірка все одно лягає."""
    db = tmp_path / "case_index.sqlite"
    real = os.replace
    calls = {"n": 0}

    def busy_once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "базу тримає читач", str(dst))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", busy_once)
    quiet_build.build_index(db_path=db, index=object())
    assert calls["n"] == 2
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT value FROM meta WHERE key='cases'").fetchone() == ("0",)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(sys.platform != "win32",
                    reason="відкритий файл не дає себе видалити лише на Windows")
def test_a_neighbour_build_in_progress_does_not_break_ours(tmp_path: Path,
                                                           quiet_build) -> None:
    """Сусідня збірка тримає свою проміжну базу — наша не мусить її чіпати."""
    db = tmp_path / "case_index.sqlite"
    neighbour = tmp_path / "case_index.sqlite.tmp"   # tmp зі старим спільним ім'ям
    with open(neighbour, "wb") as fh:
        fh.write(b"half-built")
        quiet_build.build_index(db_path=db, index=object())
    assert db.is_file()


# ── тека фонду ───────────────────────────────────────────────────────────────
@pytest.fixture
def space(tmp_path, monkeypatch):
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    (root / W.MARKER).write_text('[workspace]\nschema = 1\nname = "тест"\n',
                                 encoding="utf-8")
    monkeypatch.setenv(W.ENV_WORKSPACE, str(root))
    W.reset()
    yield root
    W.reset()


@pytest.mark.parametrize("args", [
    {"repo": "CDIAK", "fond": "224", "fond_id": "../../втеча"},
    {"repo": "CDIAK", "fond": "224", "fond_id": ".."},
    {"repo": "CDIAK", "fond": "../../втеча"},
])
def test_registry_merge_refuses_a_fond_dir_outside_raw(space: Path, monkeypatch,
                                                       args) -> None:
    from nyshporka.fonds.merge import run as M
    from nyshporka.ops_catalog import MergeArgs, registry_merge

    reached: list[object] = []
    monkeypatch.setattr(M, "merge_fond", lambda *a, **k: reached.append(k))
    env = registry_merge(MergeArgs(**args))
    assert not env.ok
    assert not reached, "зведення пішло з шляхом поза data/raw"
    assert not (space.parent / "втеча").exists()


def test_registry_dir_accepts_an_ordinary_fond(space: Path) -> None:
    from nyshporka.fonds.registry import fond_path, registry_dir

    assert registry_dir("cdiak_224") == space / "data" / "raw" / "cdiak_224" / "registry"
    assert fond_path("cdiak_224").name == "f224_opys_merged.tsv"
