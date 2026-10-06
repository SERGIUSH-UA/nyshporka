"""📏 Перелік скілів Claude Code: чи вміщаються описи скілів Нишпорки.

Claude Code відкидає описи найрідше вживаних скілів, коли перелік більший за
бюджет (1% вікна, без відомого вікна — 8 000 символів). Щойно оновлені скіли
Нишпорки — саме найрідше вживані, тож нова фіча випускалась, а агент не
бачив, коли її кликати (07.10.2026: 54 скіли, ~35 тис. символів).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.skills import listing as L


def _skill(root: Path, name: str, desc: str, *, dirname: str = "") -> None:
    d = root / (dirname or name)
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "{desc}"\n---\n\nТіло.\n',
                                encoding="utf-8")


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from nyshporka import skills as S

    home, project = tmp_path / "home", tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    (project / ".claude").mkdir(parents=True)
    monkeypatch.delenv("SLASH_COMMAND_TOOL_CHAR_BUDGET", raising=False)
    monkeypatch.setattr(S, "available",
                        lambda: [S.Skill(name="read-case", root=tmp_path / "x")])
    return home, project


def test_overrides_hide_and_collapse(machine: tuple[Path, Path]) -> None:
    home, project = machine
    skills = home / ".claude" / "skills"
    _skill(skills, "read-case", "р" * 900)
    _skill(skills, "meshy", "m" * 900)
    _skill(skills, "wrangler", "w" * 900)
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"skillOverrides": {"meshy": "off", "wrangler": "name-only"}}), encoding="utf-8")

    lst = L.measure(home, project)

    by = {e.name: e for e in lst.entries}
    assert "meshy" not in by and lst.hidden == ["meshy"]
    assert by["wrangler"].mode == "name-only" and by["wrangler"].chars < 50
    assert by["read-case"].ours and by["read-case"].chars > 900


def test_description_is_capped_per_entry(machine: tuple[Path, Path]) -> None:
    home, project = machine
    _skill(home / ".claude" / "skills", "huge", "x" * 5000)
    (e,) = L.measure(home, project).entries
    assert e.chars <= L.MAX_DESC + len("huge") + L.ENTRY_OVERHEAD


def test_synced_skills_are_one_level_deeper(machine: tuple[Path, Path]) -> None:
    home, project = machine
    _skill(home / ".claude" / "skills" / "synced" / "acc-1", "docx", "d" * 300)
    names = {e.name: e.where for e in L.measure(home, project).entries}
    assert names == {"docx": "synced"}
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"syncClaudeAiSkills": False}), encoding="utf-8")
    assert L.measure(home, project).entries == []


def test_project_skill_shadows_and_is_never_a_candidate(machine: tuple[Path, Path]) -> None:
    """Скіли проєкту поклав той, хто його веде: вимикати їх — не порада."""
    home, project = machine
    _skill(project / ".claude" / "skills", "duck", "к" * 1200)
    _skill(home / ".claude" / "skills", "cloudflare", "c" * 400)
    top = [e.name for e in L.measure(home, project).foreign_top()]
    assert top == ["cloudflare"]


def test_fixed_budget_from_env(machine: tuple[Path, Path],
                               monkeypatch: pytest.MonkeyPatch) -> None:
    home, project = machine
    monkeypatch.setenv("SLASH_COMMAND_TOOL_CHAR_BUDGET", "5000")
    assert L.measure(home, project).budgets() == {0: 5000}


def test_doctor_warns_when_listing_overflows(machine: tuple[Path, Path],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import doctor as D

    home, project = machine
    skills = home / ".claude" / "skills"
    _skill(skills, "read-case", "р" * 900)
    for i in range(10):
        _skill(skills, f"cf-{i}", "c" * 1000)
    lst = L.measure(home, project)
    monkeypatch.setattr(L, "measure", lambda *a, **k: lst)
    c = D._skill_listing()
    assert c.level == "warn" and "відкидає описи" in c.detail
    assert "cf-" in c.fix, "назвати сторонні скіли, які варто згорнути"


def test_doctor_names_our_own_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Самі скіли Нишпорки більші за бюджет — вимикати сторонні не порада."""
    from nyshporka.setup import doctor as D

    lst = L.Listing(entries=[L.Entry("read-case", "user", 9000, True),
                             L.Entry("cloudflare", "user", 400, False)])
    monkeypatch.setattr(L, "measure", lambda *a, **k: lst)
    c = D._skill_listing()
    assert c.level == "warn" and "самі скіли Нишпорки" in c.detail
    assert "skillListingBudgetFraction" in c.fix and "cloudflare" not in c.fix


def test_doctor_ok_when_it_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.setup import doctor as D

    lst = L.Listing(entries=[L.Entry("read-case", "user", 600, True)])
    monkeypatch.setattr(L, "measure", lambda *a, **k: lst)
    assert D._skill_listing().level == "ok"


def test_our_skill_descriptions_fit_the_per_entry_cap() -> None:
    """Опис кожного скіла Нишпорки мусить влазити в стелю переліку цілим."""
    from nyshporka import skills as S

    long = []
    for s in S.available():
        meta = L._front(s.card)
        text = " ".join(str(meta.get(k) or "") for k in ("description", "when_to_use"))
        if len(text.strip()) > L.MAX_DESC:
            long.append(f"{s.name}: {len(text.strip())}")
    assert not long, long
