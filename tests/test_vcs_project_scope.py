"""🔒 Історія проєкту не показує інші проєкти тієї ж Майстерні.

Репозиторій один на Майстерню, а облік сторінок, реєстр справ і маніфест доказів
лежать у спільних теках хаба. Коміт проєкту Б, що зачепив спільний файл, не мав
потрапляти в журнал проєкту А. Проєкти, прізвища й ID вигадані.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_vcs import _card, _git, _source

from nyshporka import ops as O
from nyshporka.core import vcs as V
from nyshporka.core import workspace as W

pytestmark = [pytest.mark.real_paths,
              pytest.mark.skipif(shutil.which("git") is None, reason="git недоступний")]

SUBJ_A = "Рід А: картка Сидорука"
SUBJ_B = "Рід Б: картка Мельника"
SUBJ_B_HUB = "Рід Б: лише облік сторінок"
SUBJ_B_MIX = "Рід Б: доказ у маніфесті"
SUBJ_A_HUB = "Рід А: лише спільний облік"
CARD = "data/canonical/persons/I9001.md"
PAGE = "data/pages/TEST/1-1-1.json"
MANIFEST = "data/source/citations/MANIFEST_citations.json"


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def _commit(top: Path, subject: str, *paths: str) -> None:
    _git(top, "add", "-A", "--", *paths)
    _git(top, "commit", "-q", "-m", subject)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _open(root: Path) -> None:
    W.reset()
    W.use(W._build(root, "test"))


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """Майстерня з двома проєктами й спільними файлами; історія розвинена по черзі."""
    from nyshporka.setup import wizard

    top = wizard.create(tmp_path / "ws", name="Тест")
    W.use(W._build(top, "test"))
    assert O.call("project.new", {"name": "rid-a"}).ok
    assert O.call("project.new", {"name": "rid-b"}).ok
    V.ensure_repo(top)
    a, b = top / "projects" / "rid-a", top / "projects" / "rid-b"
    for proj, pid, name in ((a, "I9001", "Іван Сидорук"), (b, "I9001", "Петро Мельник")):
        _source(proj)
        _card(proj, pid, name)
    _commit(top, SUBJ_A, "projects/rid-a")
    _commit(top, SUBJ_B, "projects/rid-b")
    _write(top / PAGE, '{"pages": {"1": {"b": 1}}}')
    _commit(top, SUBJ_B_HUB, PAGE)
    _write(top / PAGE, '{"pages": {"1": {"b": 2}}}')
    _write(top / MANIFEST, '{"x": {"cited_by": ["rid-b:I9001"]}}')
    _write(b / "reports" / "note.md", "нотатка Б\n")
    _commit(top, SUBJ_B_MIX, PAGE, MANIFEST, "projects/rid-b/reports")
    _write(top / MANIFEST, '{"x": {"cited_by": ["rid-b:I9001"]}, "y": {}}')
    _commit(top, SUBJ_A_HUB, MANIFEST)
    return top


def _subjects(rows: list[dict[str, object]]) -> list[str]:
    return [str(r["subject"]) for r in rows]


def test_project_log_has_only_own_commits(shop: Path) -> None:
    _open(shop / "projects" / "rid-a")
    rows = V.log(W.workspace())
    subjects = _subjects(rows)
    assert SUBJ_A in subjects
    for foreign in (SUBJ_B, SUBJ_B_HUB, SUBJ_B_MIX, SUBJ_A_HUB):
        assert foreign not in subjects
    blob = repr(rows)
    assert "rid-b" not in blob and "TEST/1-1-1" not in blob and "Мельник" not in blob
    assert all(not f.startswith("projects/") for r in rows for f in r["files"])
    via_op = O.call("history.log", {}).data["rows"]
    assert _subjects(via_op) == subjects


def test_other_project_sees_its_own_commits_only(shop: Path) -> None:
    _open(shop / "projects" / "rid-b")
    subjects = _subjects(V.log(W.workspace()))
    assert SUBJ_B in subjects and SUBJ_B_MIX in subjects
    assert SUBJ_A not in subjects and SUBJ_A_HUB not in subjects and SUBJ_B_HUB not in subjects


def test_hub_file_log_from_a_project_keeps_only_commits_touching_it(shop: Path) -> None:
    _open(shop / "projects" / "rid-b")
    subjects = _subjects(V.log(W.workspace(), shop / PAGE))
    assert subjects == [SUBJ_B_MIX], subjects
    _open(shop / "projects" / "rid-a")
    assert V.log(W.workspace(), shop / PAGE) == []
    assert V.log(W.workspace(), shop / MANIFEST) == []


def test_foreign_project_file_is_refused(shop: Path) -> None:
    _open(shop / "projects" / "rid-a")
    foreign = shop / "projects" / "rid-b" / CARD
    env = O.call("history.log", {"path": str(foreign)})
    assert not env.ok
    rev = _git(shop, "rev-parse", "--short", "HEAD~3").strip()
    assert not O.call("history.diff", {"path": str(foreign), "rev": rev}).ok
    assert not O.call("history.restore", {"path": str(foreign), "rev": rev}).ok


def test_hub_file_diff_and_restore_are_refused_in_a_project(shop: Path) -> None:
    _open(shop / "projects" / "rid-a")
    before = (shop / PAGE).read_text(encoding="utf-8")
    rev = _git(shop, "rev-parse", "--short", "HEAD~2").strip()
    assert not O.call("history.diff", {"path": str(shop / PAGE), "rev": rev}).ok
    assert not O.call("history.restore", {"path": str(shop / PAGE), "rev": rev}).ok
    assert (shop / PAGE).read_text(encoding="utf-8") == before


def test_own_files_still_work_in_a_project(shop: Path) -> None:
    _open(shop / "projects" / "rid-a")
    own = shop / "projects" / "rid-a" / CARD
    assert _subjects(V.log(W.workspace(), own)) == [SUBJ_A]
    rev = V.log(W.workspace(), own)[0]["rev"]
    assert O.call("history.diff", {"path": CARD, "rev": rev}).ok


def test_workshop_root_log_is_unchanged(shop: Path) -> None:
    _open(shop)
    subjects = _subjects(V.log(W.workspace(), limit=50))
    assert SUBJ_B_HUB in subjects and SUBJ_A_HUB in subjects
    assert SUBJ_B_MIX in subjects
    assert _subjects(V.log(W.workspace(), shop / PAGE)) == [SUBJ_B_MIX, SUBJ_B_HUB]
