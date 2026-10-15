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
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         input=json.dumps(_bash(f"rg x {card}", placed)), timeout=60)
    assert out.returncode == 0
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    junk = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          input="не json", timeout=60)
    assert junk.returncode == 0 and junk.stdout == "", "власна помилка — пропустити"


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
    settings = machine / ".claude" / "settings.json"
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
    settings = machine / ".claude" / "settings.json"
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
