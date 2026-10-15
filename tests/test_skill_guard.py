"""🛡 Запобіжник скілів: греп і часткове читання скілів пакета — відмова, решта — ні.

🔴 Головне — межа дії. Запобіжник, що блокує чуже (скіли людини, репозиторій
пакета, звичайний `rg` по коду), агент відчує як поломку, і людина його зніме
разом із тим, від чого він захищав. Тому тут перевіряється і «ловить», і
«пропускає».
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nyshporka import migrate as M
from nyshporka import skills as S
from nyshporka.skills import guard as G
from nyshporka.skills import hook as H


@pytest.fixture
def placed(tmp_path: Path) -> Path:
    """Тека скілів, яку наповнив пакет (з обліком), і тека чужих скілів поруч."""
    ours = tmp_path / "home" / ".claude" / "skills"
    S.install(ours, version="0.30.1")
    mine = tmp_path / "proj" / ".claude" / "skills" / "own"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("---\nname: own\ndescription: x\n---\n", encoding="utf-8")
    return ours


def _bash(cmd: str, cwd: Path) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}


def test_grep_and_partial_reads_of_package_skills_are_denied(placed: Path) -> None:
    card = placed / "read-case" / "SKILL.md"
    assert card.is_file()
    cwd = placed.parent.parent
    for cmd in (f"wc -l {card}; rg -n shard {card}",
                f'sed -n 1,60p "{card}"',
                f"head -40 {placed}/*/SKILL.md",
                f"rg cloud {placed.parent.parent.as_posix()}/.claude/skills/read-case/SKILL.md"):
        assert G.decide(_bash(cmd, cwd)), cmd
    assert G.decide({"tool_name": "PowerShell", "cwd": str(cwd),
                     "tool_input": {"command": f"Get-Content {card} -TotalCount 50"}})
    assert G.decide({"tool_name": "Grep", "cwd": str(cwd),
                     "tool_input": {"pattern": "x", "path": str(placed)}})
    assert G.decide({"tool_name": "Grep", "cwd": str(cwd),
                     "tool_input": {"pattern": "x", "path": str(card)}})
    assert G.decide({"tool_name": "Read", "cwd": str(cwd),
                     "tool_input": {"file_path": str(card), "offset": 40, "limit": 20}})


def test_whole_reads_and_foreign_skills_pass(placed: Path, tmp_path: Path) -> None:
    card = placed / "read-case" / "SKILL.md"
    own = tmp_path / "proj" / ".claude" / "skills" / "own" / "SKILL.md"
    cwd = tmp_path / "proj"
    assert G.decide({"tool_name": "Read", "cwd": str(cwd),
                     "tool_input": {"file_path": str(card)}}) is None, "ціле читання — так"
    assert G.decide(_bash(f"rg -n x {own}", cwd)) is None, "власні скіли людини не наші"
    assert G.decide({"tool_name": "Read", "cwd": str(cwd),
                     "tool_input": {"file_path": str(own), "limit": 5}}) is None
    assert G.decide(_bash("rg -n def src/", cwd)) is None
    assert G.decide(_bash(f"wc -l {card}", cwd)) is None, "лічба рядків нічого не читає"
    assert G.decide(_bash(f"git rev-parse HEAD; git add -- {card}", cwd)) is None, (
        "HEAD у git — не head")
    assert G.decide({"tool_name": "Grep", "cwd": str(cwd),
                     "tool_input": {"pattern": "x", "path": "src"}}) is None
    repo = Path(__file__).resolve().parents[1] / ".claude" / "skills"
    assert G.decide(_bash(f"rg -n x {repo}/read-case/SKILL.md", cwd)) is None, (
        "репозиторій пакета обліку не має — там скіли правлять як код")


def test_guard_runs_as_a_script_and_never_breaks_on_junk(placed: Path) -> None:
    script = Path(G.__file__)
    card = placed / "read-case" / "SKILL.md"
    # Байти UTF-8, як шле Claude Code: `text=True` кодував би вхід кодовою
    # сторінкою системи (cp1252 на Windows CI — кирилиці там немає).
    out = subprocess.run([sys.executable, str(script)], capture_output=True,
                         input=json.dumps(_bash(f"rg x {card}", placed)).encode(), timeout=60)
    assert out.returncode == 0
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    junk = subprocess.run([sys.executable, str(script)], capture_output=True,
                          input="не json".encode(), timeout=60)
    assert junk.returncode == 0 and junk.stdout == b"", "власна помилка — пропустити"


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(H, "control_path", lambda: tmp_path / "state" / H.CONTROL)
    return proj


def test_no_decision_keeps_the_migration_step_red(machine: Path) -> None:
    assert M.run_check("skill_guard", machine).state == "todo"


def test_install_keeps_foreign_settings_and_turns_the_step_green(machine: Path) -> None:
    # У проєкті — settings.local.json: settings.json кладуть у git, а наш запис
    # несе абсолютні шляхи цієї машини.
    settings = machine / ".claude" / "settings.local.json"
    assert H.settings_path(user=False) == settings
    settings.parent.mkdir()
    settings.write_text(json.dumps({"model": "x", "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "чуже"}]}]}}),
        encoding="utf-8")
    H.install(user=False)
    H.install(user=False)                          # повтор не дублює
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "x"
    pre = data["hooks"]["PreToolUse"]
    assert pre[0]["hooks"][0]["command"] == "чуже", "чужий хук лишився першим"
    assert sum(H.SCRIPT in json.dumps(e) for e in pre) == 1
    assert (machine / ".claude" / "hooks" / H.SCRIPT).is_file()
    assert M.run_check("skill_guard", machine).state == "ok"

    (machine / ".claude" / "hooks" / H.SCRIPT).unlink()
    got = M.run_check("skill_guard", machine)
    assert got.state == "todo" and "немає" in got.detail, "записане звіряється з живим"

    H.remove(user=False)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert [e["hooks"][0]["command"] for e in data["hooks"]["PreToolUse"]] == ["чуже"]


def test_a_declined_hook_closes_the_step_with_the_reason(machine: Path) -> None:
    H.record(H.settings_path(user=False), "declined", "працюю в Codex")
    got = M.run_check("skill_guard", machine)
    assert got.state == "ok" and "Codex" in got.detail


def test_unreadable_settings_are_not_overwritten(machine: Path) -> None:
    settings = H.settings_path(user=False)
    settings.parent.mkdir()
    settings.write_text("{ зламане", encoding="utf-8")
    with pytest.raises(ValueError):
        H.install(user=False)
    assert settings.read_text(encoding="utf-8") == "{ зламане"


def test_cli_decline_needs_a_reason(machine: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    runner = CliRunner()
    assert runner.invoke(app, ["skills", "hook", "--decline"]).exit_code == 1
    res = runner.invoke(app, ["skills", "hook", "--decline", "--why", "не зараз"])
    assert res.exit_code == 0
    assert M.run_check("skill_guard", machine).state == "ok"


def test_guard_reads_utf8_stdin_whatever_the_code_page(placed: Path) -> None:
    """🔴 Claude Code шле UTF-8, а Windows читає stdin кодовою сторінкою системи.

    На cp1251 шлях із кирилицею ставав кракозябрами, і запобіжник мовчки
    пропускав греп скіла — саме в тих, у кого ім'я користувача кирилицею.
    """
    import os

    home = placed.parent.parent
    cyr = home.parent / "Олена"
    home.rename(cyr)
    card = (cyr / ".claude" / "skills" / "read-case" / "SKILL.md").as_posix()
    payload = json.dumps(_bash(f"rg -n shard {card}", cyr), ensure_ascii=False).encode()
    env = dict(os.environ, PYTHONIOENCODING="cp1251")
    out = subprocess.run([sys.executable, str(Path(G.__file__))], input=payload,
                         capture_output=True, env=env, timeout=60)
    assert b"deny" in out.stdout


def test_refresh_brings_a_stale_copy_up_to_date(machine: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(S.ENV_NO_SYNC, raising=False)
    H.install(user=False)
    script = machine / ".claude" / "hooks" / H.SCRIPT
    script.write_text("# стара копія\n", encoding="utf-8")
    assert H.refresh() == [H.settings_path(user=False)]
    assert script.read_bytes() == H.GUARD.read_bytes()
    assert H.refresh() == [], "свіжа копія — нічого не робимо"

    H.remove(user=False)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# стара копія\n", encoding="utf-8")
    assert H.refresh() == [], "знятий хук не повертаємо"


def test_no_install_from_inside_the_container(machine: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(H.ENV_DOCKER, "ghcr.io/sergiush-ua/nyshporka")
    with pytest.raises(ValueError, match="контейнері"):
        H.install(user=False)
    assert not (machine / ".claude").exists()


def test_remove_also_cleans_the_0_30_2_project_place(machine: Path) -> None:
    legacy = machine / ".claude" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": H.MATCHER, "hooks": [{"type": "command",
                                          "command": f'"py" "x/{H.SCRIPT}"'}]}]},
        "model": "x"}), encoding="utf-8")
    H.remove(user=False)
    assert json.loads(legacy.read_text(encoding="utf-8")) == {"model": "x"}
