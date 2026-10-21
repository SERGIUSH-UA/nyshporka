"""🗂 Історія простору: Нишпорка заводить локальний git і веде його сама.

Тут перевіряється не «git відпрацював», а межі: наявний репозиторій людини не
чіпається, зламаний канон не зберігається, автозбереження бере лише своє, а
без git простір однаково заводиться — з порадою.

Рід і ID вигадані (`I9…`, «Сидорук»): ворота приватних даних шукають справжні.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from nyshporka.core import vcs as V
from nyshporka.core import workspace as W
from nyshporka.models import Citation, Fact, GedDate, NameVariant, Person, Source
from nyshporka.storage.files import write_entity

pytestmark = [pytest.mark.real_paths,
              pytest.mark.skipif(shutil.which("git") is None, reason="git недоступний")]

SRC = "S_TEST_BOOK"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True).stdout.decode("utf-8")


def _card(root: Path, pid: str, name: str, **kw: object) -> Path:
    fact = Fact(type="birth", date=GedDate(value="1800"), status="confirmed",
                citations=[Citation(source_id=SRC, confidence="direct",
                                    accessed=date(2026, 1, 1))])
    person = Person(id=pid, names=[NameVariant(form=name, lang="uk", primary=True)],
                    sex="M", facts=[fact], **kw)  # type: ignore[arg-type]
    path = root / "data" / "canonical" / "persons" / f"{pid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, person)
    return path


def _source(root: Path) -> None:
    path = root / "data" / "canonical" / "sources" / f"{SRC}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, Source(id=SRC, type="book", title="Тестова книга"))


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


@pytest.fixture
def space(tmp_path: Path) -> Path:
    """Свіжий простір старого типу з однією карткою — без git."""
    from nyshporka.setup import wizard

    root = wizard.create(tmp_path / "ws", name="Тест")
    W.use(W._build(root, "test"))
    _source(root)
    _card(root, "I9001", "Іван")
    return root


def test_fresh_space_gets_a_local_repo(space: Path) -> None:
    rep = V.ensure_repo(space)
    assert rep.created and rep.gitignore and rep.commit and rep.auto
    assert (space / ".gitignore").read_text(encoding="utf-8") == V.gitignore_template()
    assert _git(space, "config", "--local", "user.name").strip() == V.AUTHOR[0]
    assert _git(space, "remote").strip() == "", "без remote — лише локально"
    tracked = _git(space, "ls-files")
    assert "data/canonical/persons/I9001.md" in tracked
    hook = Path(rep.hook).read_text(encoding="utf-8")
    assert Path(sys.executable).as_posix() in hook, "хук знає свій інтерпретатор"
    again = V.ensure_repo(space)
    assert not again.created and _git(space, "rev-list", "--count", "HEAD").strip() == "1"


def test_existing_repo_is_left_to_its_owner(space: Path) -> None:
    _git(space, "init", "-q")
    _git(space, "config", "user.email", "t")
    _git(space, "config", "user.name", "t")
    (space / ".gitignore").write_text("моє\n", encoding="utf-8")
    _git(space, "add", "-A")
    _git(space, "commit", "-qm", "моє")
    head = _git(space, "rev-parse", "HEAD")
    rep = V.ensure_repo(space)
    assert not rep.created and not rep.auto and not rep.gitignore
    assert (space / ".gitignore").read_text(encoding="utf-8") == "моє\n"
    assert _git(space, "rev-parse", "HEAD") == head, "жодного коміту за людину"
    assert V.autosave("спроба") is None
    assert _git(space, "rev-parse", "HEAD") == head, "автозбереження — не в чужому репо"


def test_space_inside_someone_elses_repo_gets_no_nested_one(tmp_path: Path) -> None:
    from nyshporka.setup import wizard

    _git(tmp_path, "init", "-q")
    root = wizard.create(tmp_path / "inner" / "ws", name="Тест")
    rep = V.ensure_repo(root)
    assert rep.inside and not (root / ".git").exists()


def test_no_git_still_makes_a_space_with_advice(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    monkeypatch.delenv(V.NO_HISTORY_ENV, raising=False)
    monkeypatch.setattr(V, "git_available", lambda: False)
    res = CliRunner().invoke(app, ["init", str(tmp_path / "ws"), "--yes"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "ws" / W.MARKER).is_file() and not (tmp_path / "ws" / ".git").exists()
    assert "git не встановлено" in res.output


def test_save_takes_only_the_project_layer(space: Path) -> None:
    V.ensure_repo(space)
    _card(space, "I9002", "Петро")
    (space / "чуже.txt").write_text("людина ще працює", encoding="utf-8")
    _git(space, "add", "чуже.txt")
    rev = V.save(W.workspace(), "картка")
    assert rev
    changed = _git(space, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == ["data/canonical/persons/I9002.md"]
    assert "чуже.txt" in _git(space, "diff", "--cached", "--name-only"), "чуже лишилось у людини"
    assert V.save(W.workspace(), "ще раз") is None, "змін немає — коміту немає"


def test_broken_canon_is_not_saved(space: Path) -> None:
    V.ensure_repo(space)
    head = _git(space, "rev-parse", "HEAD")
    _card(space, "I9003", "Зламаний", parent_family="F9404")
    with pytest.raises(V.VcsError):
        V.save(W.workspace(), "зламане")
    assert _git(space, "rev-parse", "HEAD") == head


def test_green_canon_check_saves_itself_only_where_nyshporka_keeps_history(space: Path) -> None:
    from nyshporka import ops as O

    V.ensure_repo(space)
    _card(space, "I9004", "Василь")
    env = O.call("canon.check", {})
    assert env.ok and not [w for w in env.warnings if w.code == "history"]
    assert "data/canonical/persons/I9004.md" in _git(space, "show", "--name-only", "HEAD")

    marker = space / W.MARKER
    marker.write_text(marker.read_text(encoding="utf-8").replace("auto = true", "auto = false"),
                      encoding="utf-8")
    _git(space, "commit", "-qam", "вимкнено")
    head = _git(space, "rev-parse", "HEAD")
    _card(space, "I9005", "Гнат")
    O.call("canon.check", {})
    assert _git(space, "rev-parse", "HEAD") == head


def test_restore_brings_a_card_back(space: Path) -> None:
    V.ensure_repo(space)
    card = space / "data" / "canonical" / "persons" / "I9001.md"
    good = card.read_text(encoding="utf-8")
    first = _git(space, "rev-parse", "--short", "HEAD").strip()
    card.write_text(good.replace("Іван", "Іоан"), encoding="utf-8")
    V.save(W.workspace(), "правка")
    assert [r["subject"] for r in V.log(W.workspace(), card)][:1] == ["правка"]
    assert V.restore(W.workspace(), card, first)
    assert card.read_text(encoding="utf-8") == good
    assert _git(space, "status", "--porcelain").strip() == ""


def test_template_hides_frames_and_builds_but_keeps_passports(space: Path) -> None:
    from nyshporka.setup import doctor

    V.ensure_repo(space)
    files = {
        "data/raw/справа/0001.jpg": True, "data/raw/справа/_source.json": False,
        "reports/htr/прогін/0001.txt": True, "data/derived/case_index.sqlite": True,
        "projects/rid/data/derived/graph.json": True, "projects/rid/site/index.html": True,
        "data/canonical/persons/I9009.md": False, "data/pages/DAHMO/315-1-1.json": False,
        "projects/rid/data/canonical/persons/I1.md": False,
    }
    for rel in files:
        (space / rel).parent.mkdir(parents=True, exist_ok=True)
        (space / rel).write_text("x", encoding="utf-8")
    for rel, hidden in files.items():
        res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=space)
        assert (res.returncode == 0) is hidden, rel
    assert doctor._decode_visible().level == "ok", "rg і далі бачить декоди"


def test_git_ready_has_three_states(space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import migrate as M

    assert M.CHECKS["git_ready"](space).state == "todo"
    V.ensure_repo(space)
    assert M.CHECKS["git_ready"](space).state == "ok"
    monkeypatch.setattr(V, "git_available", lambda: False)
    assert M.CHECKS["git_ready"](space).state == "n/a"


def test_new_project_is_saved_with_its_hub_instructions(tmp_path: Path) -> None:
    from nyshporka import ops as O
    from nyshporka.setup import wizard

    hub = wizard.create(tmp_path / "hub", name="Майстерня", hub=True)
    W.use(W._build(hub, "test"))
    V.ensure_repo(hub)
    env = O.call("project.new", {"name": "rid"})
    assert env.ok, env.error
    assert _git(hub, "log", "-1", "--format=%s").strip() == "Проєкт «rid» заведено"
    assert _git(hub, "status", "--porcelain").strip() == "", "усе заведене — в історії"


# ── той, хто веде git сам ────────────────────────────────────────────────────
def test_no_history_flag_and_env_leave_git_to_the_person(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    monkeypatch.delenv(V.NO_HISTORY_ENV, raising=False)
    res = CliRunner().invoke(app, ["init", str(tmp_path / "a"), "--yes", "--no-history"])
    assert res.exit_code == 0, res.output
    assert not (tmp_path / "a" / ".git").exists()
    monkeypatch.setenv(V.NO_HISTORY_ENV, "1")
    res = CliRunner().invoke(app, ["init", str(tmp_path / "b"), "--yes"])
    assert res.exit_code == 0 and not (tmp_path / "b" / ".git").exists()
    # Явна команда — завжди: змінна вимикає лише заведення «між іншим» в init.
    assert V.ensure_repo(tmp_path / "b").created


def test_auto_off_hands_commits_to_the_person_and_on_takes_them_back(space: Path) -> None:
    from nyshporka import ops as O

    V.ensure_repo(space)
    _git(space, "remote", "add", "origin", "https://example.invalid/r.git")
    V.set_auto(space, False)
    assert not V.auto_enabled(space)
    _git(space, "commit", "-qam", "вимкнено")
    head = _git(space, "rev-parse", "HEAD")
    _card(space, "I9006", "Остап")
    O.call("canon.check", {})
    assert _git(space, "rev-parse", "HEAD") == head, "автозбереження вимкнене"
    V.set_auto(space, True)
    O.call("canon.check", {})
    assert "I9006" in _git(space, "show", "--name-only", "HEAD"), "remote людини не заважає"
