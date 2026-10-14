"""Скіли для кожного агента: Claude Code читає `.claude/skills`, Codex — `.agents/skills`.

🔴 14.10.2026: `nysh skills install` клав лише в теки Claude, `doctor` дивився
лише туди й казав «все гаразд», а агент Codex не бачив жодного скіла — і
запустив `cloud go` з пісочниці, яка вбила наглядача разом із собою. Бокси
горіли без нагляду.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka import skills as S
from nyshporka.cli import app

CARD = """---
name: probe
description: Зразок для перевірки постачання.
---

# Проба
"""


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pack"
    (root / "probe").mkdir(parents=True)
    (root / "probe" / "SKILL.md").write_text(CARD, encoding="utf-8")
    monkeypatch.setattr(S, "_roots", lambda: [root])
    return root


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: proj))
    # Своя домашня на кожен тест: спільна на сесію (conftest) несла б скіли сусідів.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(proj)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return proj


def _install(*args: str) -> str:
    res = CliRunner().invoke(app, ["skills", "install", *args])
    assert res.exit_code == 0, res.output
    return res.output


def test_install_puts_skills_where_both_agents_read_them(pack, project) -> None:
    _install()
    for rel in (".claude/skills", ".agents/skills"):
        dest = project / rel
        assert (dest / "probe" / "SKILL.md").is_file(), rel
        assert json.loads((dest / S.LEDGER).read_text(encoding="utf-8"))["files"], \
            "облік кожна тека веде свій"


def test_user_install_goes_to_both_home_dirs(pack, project) -> None:
    _install("--user")
    for rel in (".claude/skills", ".agents/skills"):
        assert (Path.home() / rel / "probe" / "SKILL.md").is_file(), rel
    assert not (project / ".claude").exists(), "--user не чіпає проєкт"


@pytest.mark.parametrize(("agent", "there", "not_there"), [
    ("codex", ".agents/skills", ".claude/skills"),
    ("claude", ".claude/skills", ".agents/skills"),
])
def test_agent_flag_picks_one(pack, project, agent, there, not_there) -> None:
    _install("--agent", agent)
    assert (project / there / "probe" / "SKILL.md").is_file()
    assert not (project / not_there).exists()


def test_target_stays_a_single_folder(pack, project, tmp_path: Path) -> None:
    out = tmp_path / "elsewhere"
    _install("--target", str(out))
    assert (out / "probe" / "SKILL.md").is_file()
    assert not (project / ".agents").exists() and not (project / ".claude").exists()
    res = CliRunner().invoke(app, ["skills", "install", "--target", str(out),
                                   "--agent", "codex"])
    assert res.exit_code == 1


def test_unknown_agent_is_refused(pack, project) -> None:
    res = CliRunner().invoke(app, ["skills", "install", "--agent", "cursor"])
    assert res.exit_code == 1
    assert "невідомий агент" in res.output


def test_installed_and_sync_see_the_codex_folders(pack, project,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    S.install(project / ".agents" / "skills", version="0.0.1")
    S.install(Path.home() / ".agents" / "skills", version="0.0.1")
    got = {str(d) for d, _ in S.installed()}
    assert str(project / ".agents" / "skills") in got
    assert str(Path.home() / ".agents" / "skills") in got

    monkeypatch.delenv(S.ENV_NO_SYNC, raising=False)
    synced = {str(d) for d, _ in S.sync("9.9.9")}
    assert str(project / ".agents" / "skills") in synced, "оновлення пакета доганяє й Codex"


# ── doctor ────────────────────────────────────────────────────────────────


def _codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))


def test_doctor_warns_when_codex_is_here_but_its_folder_is_empty(
        pack, project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import __version__
    from nyshporka.setup import doctor

    S.install(Path.home() / ".claude" / "skills", version=__version__)
    assert doctor._skills().level == "ok", "без Codex теки Claude досить"

    _codex_home(tmp_path, monkeypatch)
    check = doctor._skills()
    assert check.level == "warn"
    assert "Codex" in check.detail
    assert "nysh skills install --user --agent codex" in check.fix


def test_doctor_warns_about_stale_codex_skills(
        pack, project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import doctor

    _codex_home(tmp_path, monkeypatch)
    S.install(Path.home() / ".agents" / "skills", version="0.0.1")
    check = doctor._skills()
    assert check.level == "warn" and ".agents" in check.detail


def test_doctor_is_quiet_when_codex_has_current_skills(
        pack, project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import __version__
    from nyshporka.setup import doctor

    _codex_home(tmp_path, monkeypatch)
    S.install(Path.home() / ".agents" / "skills", version=__version__)
    assert doctor._skills().level == "ok"


def test_doctor_with_nothing_installed_and_codex_present_warns(
        pack, project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import doctor

    _codex_home(tmp_path, monkeypatch)
    assert doctor._skills().level == "warn"


def test_codex_presence_follows_codex_home(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    assert S.codex_present() is False
    (tmp_path / "nope").mkdir()
    assert S.codex_present() is True


# ── uninstall ─────────────────────────────────────────────────────────────


def test_uninstall_takes_skills_from_every_folder_it_put_them(pack, project) -> None:
    from nyshporka.setup import uninstall as U

    _install("--user")
    _install()
    dirs = {str(d) for d, _ in U._skill_dirs()}
    assert len(dirs) == 4
    for d, _ in U._skill_dirs():
        U._drop_skills(d, dry=False)
    for base in (project, Path.home()):
        for rel in (".claude/skills", ".agents/skills"):
            assert not (base / rel / "probe").exists(), f"{base}/{rel}"


def test_uninstall_leaves_foreign_empty_folders_in_the_shared_codex_dir(pack, project) -> None:
    """`~/.agents/skills` спільна для всіх скілів Codex: чужа порожня тека — не наша."""
    from nyshporka.setup import uninstall as U

    shared = Path.home() / ".agents" / "skills"
    _install("--user", "--agent", "codex")
    (shared / "someone-elses-skill").mkdir()
    U._drop_skills(shared, dry=False)
    assert not (shared / "probe").exists()
    assert (shared / "someone-elses-skill").is_dir()
