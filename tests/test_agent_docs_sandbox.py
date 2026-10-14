"""Що агент читає про скіли й довгу роботу — правда для КОЖНОГО агента.

🔴 14.10.2026: агент Codex пропустив однорядкову згадку про свою теку скілів
(вона стояла після абзацу про довгі команди, під командою з коментарем
`# ~/.claude/skills`), не мав скілів і запустив `cloud go` з пісочниці. Скіл
при цьому обіцяв, що після `detached` «можна вимкнути машину», хоча наглядач
живе саме на ній.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    import re

    # Переноси рядків і розмітку жирного вирівнюємо: правило лишається правилом.
    text = (ROOT / rel).read_text(encoding="utf-8").replace("**", "")
    return re.sub(r"\s*\n\s*", " ", text)


def test_agents_md_shows_each_agent_its_skill_folder() -> None:
    text = _read("AGENTS.md")
    assert "| Claude Code | `~/.claude/skills`" in text
    assert "| Codex | `~/.agents/skills`" in text
    assert "--agent codex" in text
    assert "# ~/.claude/skills" not in text, "команда з коментарем лише про Claude"


def test_agents_md_and_the_skill_keep_cloud_go_out_of_the_sandbox() -> None:
    for rel in ("AGENTS.md", ".claude/skills/run-case-remote/SKILL.md"):
        text = _read(rel)
        assert "поза пісочницею" in text, rel
        assert "nysh cloud state" in text, rel
        assert "конкретний PID" in text, rel


def test_the_skill_no_longer_says_the_machine_can_be_switched_off() -> None:
    text = _read(".claude/skills/run-case-remote/SKILL.md")
    assert "навіть вимкнути машину" not in text
    assert "наглядач живе саме на ній" in text


def test_readme_does_not_hardcode_the_skill_count() -> None:
    """Числа з документації застарівають: «11 скілів» стояло при 17."""
    import re

    assert not re.search(r"\b\d+\s+скіл", _read("README.md"))
