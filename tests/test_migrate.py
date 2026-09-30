"""🧭 Міграція агента: непройдене видно, застаріле знаходиться, цитата — не теза,
новий простір мігрувати не мусить, перевірки кроків живі."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka import migrate as M
from nyshporka import ops as O
from nyshporka.core import workspace as W


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "простір"
    root.mkdir()
    (root / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=root, name="t", origin="test"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(root)
    return root


def test_every_shipped_migration_parses_and_checks_exist() -> None:
    migs = M.load_all()
    assert migs, "жодної міграції в пакеті"
    for m in migs:
        assert m.title and m.body and m.stale and m.steps, m.version
        for s in m.steps:
            assert not s.check or s.check in M.CHECKS, f"{m.version}/{s.id}: {s.check}"


def test_an_old_workspace_has_the_migration_pending_until_done(space: Path) -> None:
    assert [m.version for m in M.pending(space, "0.19.0")] == ["0.19"]
    assert [m.version for m in M.pending(space, "0.20.0")] == ["0.19", "0.20"]
    assert M.pending(space, "0.18.14") == [], "новіша за пакет міграція не показується"
    env = O.call("workspace.info", {})
    assert any(w.code == "agent_migration" for w in env.warnings)
    done = O.call("migrate.done", {})
    assert done.ok and done.data["marked"] == ["0.19", "0.20"]
    assert M.pending(space, "0.19.0") == [] and M.pending(space, "0.20.0") == []
    assert not any(w.code == "agent_migration" for w in O.call("workspace.info", {}).warnings)


def test_a_new_workspace_is_stamped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import __version__
    from nyshporka.setup import wizard

    monkeypatch.setattr(W, "remember", lambda ws: None)
    root = wizard.create(tmp_path / "новий", name="н")
    assert M.pending(root, __version__) == []
    assert M.record(root)["history"][0]["how"] == "new-workspace"


def test_the_record_lives_on_the_machine_not_in_the_workspace(space: Path, tmp_path: Path) -> None:
    """🔴 Копія простору на новій машині мусить нагадати знову: кроки про конфіг
    агента, скіли й пам'ять — про машину, а не про теку."""
    O.call("migrate.done", {})
    assert not list(space.rglob("*migrat*.json")), "запис не має жити в теці простору"
    import shutil

    copy = tmp_path / "копія"
    shutil.copytree(space, copy)
    assert [m.version for m in M.pending(copy, "0.19.0")] == ["0.19"]


def test_scan_finds_a_stale_thesis_but_not_a_quoted_one(tmp_path: Path) -> None:
    note = tmp_path / "memory" / "note.md"
    note.parent.mkdir()
    note.write_text(
        "Канону в пакеті немає, родовід веде людина.\n"
        "Не повторювати тезу «канону в пакеті немає».\n"
        "Агент кличе nysh_search_run.\n"
        "Запусти `nysh mcp serve` на старті.\n"
        "Змінна NYSH_NO_CATALOG=1 вимикає каталог.\n"
        "Без --status аркуш лягає partial за замовчуванням, а не full.\n"
        "Канону немає в пакеті.\n", encoding="utf-8")
    hits = M.scan([tmp_path / "memory"], M.load_all())
    assert [(h.line, h.stale) for h in hits] == [
        (1, "no-canon"), (3, "mcp"), (4, "mcp"), (7, "no-canon")], (
        "цитата в «» — не теза; команда в бектиках — теза; змінна оточення й нова "
        "правда про partial — не тези")
    assert all(h.now for h in hits)


def test_default_scan_reads_only_this_projects_memory(space: Path) -> None:
    import re

    projects = Path.home() / ".claude" / "projects"
    mine = projects / re.sub(r"[^A-Za-z0-9]", "-", str(space.resolve())) / "memory"
    other = projects / "E--Projects-Other" / "memory"
    for d in (mine, other):
        d.mkdir(parents=True)
        (d / "n.md").write_text("кличе nysh mcp serve\n", encoding="utf-8")
    paths = M.default_scan_paths(space)
    assert mine in paths and other not in paths


def test_status_runs_live_checks(space: Path) -> None:
    (space / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"nyshporka": {"command": "nysh", "args": ["mcp", "serve"]}}}),
        encoding="utf-8")
    env = O.call("migrate.status", {})
    steps = {s["id"]: s for s in env.data["pending"][0]["steps"]}
    assert steps["mcp-config"]["state"] == "todo" and ".mcp.json" in steps["mcp-config"]["detail"]
    assert steps["canon"]["state"] == "todo" and steps["canon"]["human"]
    assert steps["hook"]["state"] == "n/a"
    (space / ".mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    steps = {s["id"]: s for s in O.call("migrate.status", {}).data["pending"][0]["steps"]}
    assert steps["mcp-config"]["state"] == "ok"


def test_hand_edited_skills_are_scanned_and_package_ones_are_not(space: Path) -> None:
    from nyshporka import skills as S

    dest = Path.home() / ".claude" / "skills"
    S.install(dest, version="0.18")
    ours = next(dest.rglob("SKILL.md"))
    assert ours not in M.default_scan_paths(space)
    ours.write_text(ours.read_text(encoding="utf-8") + "\nкличе nysh mcp serve\n", encoding="utf-8")
    assert ours in M.default_scan_paths(space)


def test_cli_show_and_scan(space: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    runner = CliRunner()
    res = runner.invoke(app, ["migrate", "--show", "0.19"])
    assert res.exit_code == 0 and "Канон роду — твоя робота" in res.stdout
    res = runner.invoke(app, ["migrate", "--show", "9.9"])
    assert res.exit_code == 1
    res = runner.invoke(app, ["migrate", "--scan", str(space)])
    assert res.exit_code == 0
