"""🧳 `nysh workspace export / import`: простір переїжджає на іншу машину (#30).

🔴 Обіцянки:

- копія звіряється пофайлово, а паспорт `nyshporka-bundle.json` пишеться
  останнім: без нього імпорт відмовляє;
- повторний експорт докопійовує лише змінене й знімає видалене;
- venv рушіїв, замок, `.program` і дозволи агента не їдуть;
- корені справ переписуються на нові місця, а відсутній корінь не зникає мовчки;
- хук канону після імпорту знає інтерпретатор ЦІЄЇ машини.

Справжні `cases build` і `doctor` не кличуться: `runner` — заглушка.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.setup import transfer as T


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    ws = tmp_path / "old" / "Нишпорка"
    (ws / "data" / "raw" / "spr-1").mkdir(parents=True)
    (ws / "data" / "raw" / "spr-1" / "0001.jpg").write_bytes(b"x" * 100)
    (ws / "data" / "canonical" / "persons").mkdir(parents=True)
    (ws / "data" / "canonical" / "persons" / "I9001.md").write_text("Іван\n", encoding="utf-8")
    (ws / ".venv_htr" / "Scripts").mkdir(parents=True)
    (ws / ".venv_htr" / "Scripts" / "python.exe").write_bytes(b"venv")
    (ws / ".program" / "bin").mkdir(parents=True)
    (ws / ".program" / "bin" / "nysh.exe").write_bytes(b"prog")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
    (ws / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    scans = tmp_path / "old" / "Скани"
    (scans / "spr-2").mkdir(parents=True)
    (scans / "spr-2" / "0001.jpg").write_bytes(b"s" * 40)
    (ws / W.MARKER).write_text(
        f'[workspace]\nschema = 1\ncase_roots = ["{scans.as_posix()}"]\n', encoding="utf-8")

    data = tmp_path / "old-data"
    (data / "catalog").mkdir(parents=True)
    (data / "catalog" / "pack.sqlite").write_bytes(b"c" * 50)
    new_data = tmp_path / "new-data"

    W.reset()
    W.use(W._build(ws, "test"))
    monkeypatch.setattr("nyshporka.core.appdirs.data_dir", lambda: data)
    monkeypatch.setattr("nyshporka.setup.doctor.engine_venv", lambda: ws / ".venv_htr")
    remembered: dict[str, str] = {}
    monkeypatch.setattr(W, "state_set", lambda **kw: remembered.update(kw))
    yield {"ws": ws, "scans": scans, "data": data, "new_data": new_data,
           "copy": tmp_path / "disk" / "копія", "new": tmp_path / "new" / "Нишпорка",
           "tmp": tmp_path, "remembered": remembered}  # type: ignore[misc]
    W.reset()


def _export(env: dict, **kw: bool) -> dict:
    return T.run_export(T.plan_export(env["copy"], **kw), echo=lambda _s: None)


def _as_new_machine(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Старих тек на «новій машині» немає; дані програми — свої."""
    shutil.move(str(env["scans"]), str(env["tmp"] / "scans-gone"))
    monkeypatch.setattr("nyshporka.core.appdirs.data_dir", lambda: env["new_data"])


def test_round_trip_moves_research_and_rewrites_roots(env: dict,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _export(env, with_roots=True, with_data=True)
    copy = env["copy"]
    assert (copy / T.BUNDLE).is_file()
    assert (copy / "workspace" / "data" / "canonical" / "persons" / "I9001.md").is_file()
    for gone in (".venv_htr", ".program", ".claude/settings.local.json"):
        assert not (copy / "workspace" / gone).exists(), f"{gone} не мав їхати"
    assert (copy / "workspace" / ".claude" / "settings.json").is_file()
    assert bundle["engines"] and bundle["data"]
    assert [r["dir"] for r in bundle["roots"]] == ["roots/01-Скани"]

    _as_new_machine(env, monkeypatch)
    calls: list[list[str]] = []
    p = T.plan_import(copy, env["new"])
    assert p.problems == []
    todo = T.run_import(p, runner=lambda c: calls.append(c) or 0, echo=lambda _s: None)

    new = env["new"]
    assert (new / "data" / "raw" / "spr-1" / "0001.jpg").read_bytes() == b"x" * 100
    moved = env["tmp"] / "new" / "Нишпорка-скани" / "01-Скани"
    assert (moved / "spr-2" / "0001.jpg").is_file()
    W.reset()
    built = W._build(new, "test")
    assert list(built.extra_case_roots) == [moved]
    assert (env["new_data"] / "catalog" / "pack.sqlite").is_file()
    assert env["remembered"]["workspace"] == str(new)
    assert all(c[c.index("--workspace") + 1] == str(new) for c in calls)
    assert [c[c.index("--workspace") + 2:] for c in calls] == [["cases", "build"], ["doctor"]]
    assert any("htr install" in t for t in todo) and any("share login" in t for t in todo)


def test_second_export_copies_only_the_change_and_drops_the_deleted(env: dict) -> None:
    _export(env)
    again = T.sync_tree(env["ws"], env["copy"] / "workspace", T.WS_SKIP_TOP, T.WS_SKIP_REL)
    assert again.copied == 0 and again.removed == 0, "без змін — нічого не копіюється"

    card = env["ws"] / "data" / "canonical" / "persons" / "I9001.md"
    card.write_text("Іван Петрович\n", encoding="utf-8")
    (env["ws"] / "data" / "raw" / "spr-1" / "0001.jpg").unlink()
    _export(env)
    copied = env["copy"] / "workspace"
    assert (copied / "data" / "canonical" / "persons" / "I9001.md").read_text(
        encoding="utf-8") == "Іван Петрович\n"
    assert not (copied / "data" / "raw" / "spr-1" / "0001.jpg").exists(), \
        "видалене в просторі не має воскреснути після імпорту"


def test_mtime_within_two_seconds_counts_as_unchanged(env: dict) -> None:
    """FAT/exFAT зберігає час із кроком 2 с — це не зміна файла."""
    _export(env)
    f = env["copy"] / "workspace" / "data" / "raw" / "spr-1" / "0001.jpg"
    st = f.stat()
    os.utime(f, (st.st_atime, st.st_mtime - 1.5))
    rep = T.sync_tree(env["ws"], env["copy"] / "workspace", T.WS_SKIP_TOP, T.WS_SKIP_REL)
    assert rep.copied == 0


def test_without_bundle_the_copy_is_incomplete(env: dict) -> None:
    _export(env)
    (env["copy"] / T.BUNDLE).unlink()
    with pytest.raises(T.TransferError, match="неповна"):
        T.plan_import(env["copy"], env["new"])


def test_copy_that_differs_from_its_list_is_refused(env: dict) -> None:
    _export(env)
    (env["copy"] / "workspace" / "data" / "canonical" / "persons" / "I9001.md").write_text(
        "інше", encoding="utf-8")
    p = T.plan_import(env["copy"], env["new"])
    assert any("не сходиться" in x and "I9001.md" in x for x in p.problems)


def test_copy_made_by_a_newer_version_asks_for_update(env: dict) -> None:
    _export(env)
    path = env["copy"] / T.BUNDLE
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["nyshporka"] = "99.0.0"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    p = T.plan_import(env["copy"], env["new"])
    assert any("nysh update" in x for x in p.problems)


def test_root_not_taken_is_named_not_hidden(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Без `--with-roots` корінь лишається в маркері й у переліку «доробити»."""
    bundle = _export(env)
    assert bundle["roots"][0]["dir"] is None
    _as_new_machine(env, monkeypatch)
    p = T.plan_import(env["copy"], env["new"])
    assert [m.action for m in p.roots] == ["missing"]
    todo = T.run_import(p, runner=lambda c: 0, echo=lambda _s: None)
    assert any("roots remove" in t and env["scans"].as_posix() in t for t in todo)
    marker = (env["new"] / W.MARKER).read_text(encoding="utf-8")
    assert env["scans"].as_posix() in marker, "корінь не зникає мовчки"


def test_root_that_exists_here_stays_in_place(env: dict) -> None:
    _export(env, with_roots=True)
    p = T.plan_import(env["copy"], env["new"])
    assert [(m.action, m.new) for m in p.roots] == [("keep", env["scans"])]


def test_import_refuses_a_non_empty_destination(env: dict) -> None:
    _export(env)
    env["new"].mkdir(parents=True)
    (env["new"] / "щось.txt").write_text("x", encoding="utf-8")
    p = T.plan_import(env["copy"], env["new"])
    assert any("не порожня" in x for x in p.problems)


def test_export_refuses_a_foreign_non_empty_folder(env: dict) -> None:
    env["copy"].mkdir(parents=True)
    (env["copy"] / "фото.jpg").write_bytes(b"x")
    p = T.plan_export(env["copy"])
    assert any("не є копією простору" in x for x in p.problems)


@pytest.mark.skipif(shutil.which("git") is None, reason="git недоступний")
def test_hook_gets_this_machines_interpreter(env: dict,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.canon import hook as H

    ws = env["ws"]
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    hook = H.install(ws)
    hook.write_text(hook.read_text(encoding="utf-8").replace(
        Path(sys.executable).as_posix(), "/інша-машина/python"), encoding="utf-8", newline="\n")
    _export(env)
    _as_new_machine(env, monkeypatch)
    T.run_import(T.plan_import(env["copy"], env["new"]), runner=lambda c: 0,
                 echo=lambda _s: None)
    text = (env["new"] / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert Path(sys.executable).as_posix() in text and "/інша-машина/" not in text


def test_names_match_across_unicode_normal_forms(tmp_path: Path) -> None:
    """macOS пише імена в NFD, Windows — у NFC: звірка не має їх розрізняти."""
    nfd = unicodedata.normalize("NFD", "Йосип.md")
    (tmp_path / nfd).write_text("x", encoding="utf-8")
    assert list(T._walk(tmp_path)) == [unicodedata.normalize("NFC", "Йосип.md")]


def test_cli_dry_runs_change_nothing(env: dict) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    res = CliRunner().invoke(app, ["workspace", "export", str(env["copy"]), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert not env["copy"].exists()
    _export(env)
    res = CliRunner().invoke(app, ["workspace", "import", str(env["copy"]), str(env["new"]),
                                   "--dry-run"])
    assert res.exit_code == 0, res.output
    assert not env["new"].exists()
