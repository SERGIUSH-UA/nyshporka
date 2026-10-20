"""🧪 Скіли радять лише те, що існує, і вміщаються в один прочит.

Скіл агент виконує буквально, тож застаріла команда чи прапорець у ньому —
це зірваний запуск, а не неточність тексту. Перевірка йде проти живого
дерева CLI (`nyshporka.skills.lint`), а не проти знімка. Другий запобіжник —
межа тіла: довгий скіл агент не дочитує, і губиться саме кінець — ворота й
що записати.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from nyshporka import ops as O
from nyshporka.cli import app
from nyshporka.skills import lint as L

SKILLS = Path(__file__).resolve().parents[1] / ".claude" / "skills"
ROOT = typer.main.get_command(app)
OPS = set(O.REGISTRY.ops)


def _texts() -> list[tuple[str, str]]:
    files = [*sorted(SKILLS.glob("*/SKILL.md")), *sorted(SKILLS.glob("*/references/*.md"))]
    return [(str(p.relative_to(SKILLS)), p.read_text(encoding="utf-8")) for p in files]


def _bad(text: str) -> list[str]:
    return [p.why for p in L.check(text, "nysh", ROOT, known_ops=OPS)]


def test_skills_name_only_existing_commands_and_flags() -> None:
    problems = L.check_files(_texts(), "nysh", ROOT, OPS)
    assert not problems, "скіл радить те, чого немає:\n" + "\n".join(map(str, problems))


@pytest.mark.parametrize("card", sorted(SKILLS.glob("*/SKILL.md")), ids=lambda p: p.parent.name)
def test_skill_body_fits_one_reading(card: Path) -> None:
    n = L.body_chars(card.read_text(encoding="utf-8"))
    assert n <= L.BODY_MAX, (
        f"{card.parent.name}: {n} знаків при межі {L.BODY_MAX} — рідке винести "
        "в references/ (копія docs/agents/), перелік команд замінити картою")


def test_lint_sees_commands_in_the_skills_at_all() -> None:
    """Нуль вад нічого не важить, якщо розбір не знайшов жодної команди."""
    pieces = sum(len(L.code_lines(t)) for _, t in _texts())
    assert pieces > 500


# ── розбір: кожна гілка має свій приклад ─────────────────────────────────────
def test_invented_command_is_caught() -> None:
    assert _bad("Далі `nysh text frobnicate <справа>`.")


def test_invented_flag_is_caught() -> None:
    assert _bad("Далі `nysh text grep \"x\" --pack-dir out`.")


def test_real_command_with_flags_and_args_passes() -> None:
    assert not _bad("Далі `nysh text grep \"<регекс>\" --where all` і `nysh ops --map`.")


def test_command_wrapped_across_lines_is_joined() -> None:
    assert _bad("Спершу `nysh text\nfrobnicate` — і все.")
    assert not _bad("Спершу `nysh text\ngrep \"x\" --where all` — і все.")


def test_fenced_block_with_continuation_and_comment() -> None:
    block = "```\nnysh text grep \"x\" \\\n  --where all  # коментар --bogus\n```\n"
    assert not _bad(block)
    assert _bad("```\nnysh text grep \"x\" \\\n  --bogus\n```\n")


def test_unknown_op_is_caught() -> None:
    assert _bad("`nysh op text.nothing --describe`")
    assert not _bad("`nysh op text.find --describe`")


def test_deliberate_negative_is_allowed() -> None:
    assert not _bad("Команди `nysh cases stats` не існує — лічильник дає `nysh cases list`.")
    assert _bad("Лічильник дає `nysh cases stats`.")


def test_placeholder_in_command_position_is_not_advice() -> None:
    assert not _bad("Будь-яка `nysh <група> --help` покаже аргументи.")
