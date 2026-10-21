"""🗂 Історія як операції: журнал, «що змінилось», повернення — для консолі й CLI.

Екран «Історія» стоїть на трьох відповідях: що змінювали (журнал усього
проєкту з файлами), що саме змінив коміт у картці (поля «було → стало», а не
сирий YAML) і повернення. Рід і ID вигадані (`I9…`, «Сидорук»).
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

CARD = "data/canonical/persons/I9001.md"


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


@pytest.fixture
def space(tmp_path: Path) -> Path:
    from nyshporka.setup import wizard

    root = wizard.create(tmp_path / "ws", name="Тест")
    W.use(W._build(root, "test"))
    _source(root)
    _card(root, "I9001", "Іван Сидорук")
    V.ensure_repo(root)
    return root


def _edit(root: Path, old: str, new: str) -> None:
    card = root / CARD
    card.write_text(card.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_log_of_the_whole_project_names_changed_files(space: Path) -> None:
    _edit(space, "Іван", "Іоан")
    assert O.call("history.save", {"message": "ім'я"}).data["saved"]
    rows = O.call("history.log", {}).data["rows"]
    assert rows[0]["subject"] == "ім'я"
    assert rows[0]["files"] == [CARD]
    one = O.call("history.log", {"path": CARD}).data["rows"]
    assert one[0]["subject"] == "ім'я" and "files" not in one[0]


def test_log_files_are_from_the_project_root_not_the_git_root(space: Path) -> None:
    """🔴 Корінь git — Майстерня, корінь проєкту — `projects/<ім'я>`.

    Консоль бере файл із журналу й передає його в `history.diff`/`restore`, а
    ті читають шлях від кореня проєкту. Шлях від кореня git там не знайшовся б.
    """
    assert O.call("project.new", {"name": "sydoruk"}).ok
    proj = space / "projects" / "sydoruk"
    W.use(W._build(proj, "test"))
    _source(proj)
    _card(proj, "I9001", "Іван Сидорук")
    rev = O.call("history.save", {"message": "проєкт"}).data["rev"]
    rows = O.call("history.log", {}).data["rows"]
    assert rows[0]["files"] and all(not f.startswith("projects/") for f in rows[0]["files"])
    assert CARD in rows[0]["files"]
    d = O.call("history.diff", {"path": CARD, "rev": rev})
    assert d.ok and d.data["added"]


def test_diff_of_a_card_shows_fields_not_yaml(space: Path) -> None:
    _edit(space, "sex: M", "sex: F")
    rev = O.call("history.save", {"message": "стать"}).data["rev"]
    d = O.call("history.diff", {"path": CARD, "rev": rev}).data
    assert d["kind"] == "fields"
    assert d["fields"] == [{"field": "sex", "before": "M", "after": "F"}]
    assert not d["notes_changed"] and not d["added"] and not d["removed"]


def test_diff_of_a_new_card_has_no_before(space: Path) -> None:
    _card(space, "I9002", "Петро Сидорук")
    rev = O.call("history.save", {}).data["rev"]
    d = O.call("history.diff", {"path": "data/canonical/persons/I9002.md",
                                "rev": rev}).data
    assert d["added"] and {f["field"] for f in d["fields"]} >= {"id", "names", "sex"}
    assert all(f["before"] is None for f in d["fields"])


def test_diff_of_a_plain_file_is_text(space: Path) -> None:
    note = space / "reports" / "x.md"
    note.parent.mkdir(exist_ok=True)
    note.write_text("перший\n", encoding="utf-8")
    O.call("history.save", {})
    note.write_text("перший\nдругий\n", encoding="utf-8")
    rev = O.call("history.save", {}).data["rev"]
    d = O.call("history.diff", {"path": "reports/x.md", "rev": rev}).data
    assert d["kind"] == "text" and "+другий" in d["lines"] and not d["cut"]


def test_restore_through_the_op_and_bad_rev_refused(space: Path) -> None:
    first = _git(space, "rev-parse", "--short", "HEAD").strip()
    good = (space / CARD).read_text(encoding="utf-8")
    _edit(space, "Іван", "Іоан")
    O.call("history.save", {})
    env = O.call("history.restore", {"path": CARD, "rev": first})
    assert env.ok and env.data["rev"]
    assert (space / CARD).read_text(encoding="utf-8") == good
    for bad in ("--output=x", "HEAD", ""):
        assert not O.call("history.diff", {"path": CARD, "rev": bad}).ok
        assert not O.call("history.restore", {"path": CARD, "rev": bad}).ok


def test_auto_shows_state_and_switches(space: Path) -> None:
    d = O.call("history.auto", {}).data
    assert d == {"git": True, "repo": True, "own": False, "auto": True}
    assert O.call("history.auto", {"on": False}).data["auto"] is False
    assert not V.auto_enabled(space)


def test_outside_git_is_an_answer_not_a_crash(tmp_path: Path) -> None:
    from nyshporka.setup import wizard

    root = wizard.create(tmp_path / "bare", name="Тест")
    W.use(W._build(root, "test"))
    env = O.call("history.log", {})
    assert not env.ok and "history setup" in env.error
