"""Тека керованих інтерпретаторів — одна для інсталятора й для кожного виклику uv.

🔴 14.10.2026, французька Windows: `uv python install` падав з os error 448
(ERROR_UNTRUSTED_MOUNT_POINT). uv кладе Python у ромінговий
`%APPDATA%\\uv\\python` і робить там junction на мінорну версію, а Windows з
перенаправленим AppData / OneDrive відмовляється його проходити
(astral-sh/uv#19622, #19616). Недовірений junction на CI не змоделювати, тож
тут стережеться інше: кожен виклик uv отримує ту саму теку
(`UV_PYTHON_INSTALL_DIR`), а відмова з «os error 448» у виводі дає ту саму
пораду і в інсталятора, і в `nysh htr install`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from nyshporka.setup import update as U

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "install" / "windows.ps1"
FOLDER = r"D:\Ім'я дослідника\Nyshporka\python"


def _ps1() -> str:
    return PS1.read_text(encoding="utf-8-sig")


@pytest.fixture
def info(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    got = {"uv": r"C:\Nysh\uv\uv.exe", "python_dir": FOLDER, "preset": "researcher"}
    monkeypatch.setattr(U, "install_info", lambda: dict(got))
    return got


# ── інсталятор ──────────────────────────────────────────────────────────────


def test_installer_sets_the_folder_before_the_first_python_install() -> None:
    text = _ps1()
    assert "[string]$PythonDir" in text
    assert "if (-not $PythonDir) { $PythonDir = Join-Path $Home_ 'python' }" in text
    set_at = text.index("$env:UV_PYTHON_INSTALL_DIR = $PythonDir")
    assert set_at < text.index("Invoke-Logged $uv python install 3.12")
    assert set_at < text.index("Invoke-Logged $uv tool install"), \
        "і `uv tool install`, і `nysh htr install` далі успадковують змінну процесу"
    assert "SetEnvironmentVariable('UV_PYTHON" not in text, \
        "не постійна змінна користувача: вона зачепила б чужі uv"


def test_installer_records_the_folder_for_nyshporka() -> None:
    assert '"python_dir=$PythonDir"' in _ps1()


def test_installer_and_package_give_the_same_448_advice() -> None:
    text = _ps1()
    m = re.search(r"^\$Untrusted448 = '((?:[^']|'')*)'", text, re.M)
    assert m, "текст відмови 448 в інсталяторі"
    assert m.group(1).replace("''", "'") == U.UNTRUSTED_MOUNT_HINT
    # обидва виклики uv, що можуть качати Python, кажуть про 448 одне
    assert text.count("-match 'os error 448') { throw $Untrusted448 }") == 2


# ── Нишпорка ────────────────────────────────────────────────────────────────


def test_every_uv_call_gets_the_installer_folder(info) -> None:
    env = U.uv_python_env()
    assert env["UV_PYTHON_INSTALL_DIR"] == FOLDER
    assert env["UV_PYTHON_INSTALL_BIN"] == "0" and env["UV_PYTHON_INSTALL_REGISTRY"] == "0"
    assert U.command_env()["UV_PYTHON_INSTALL_DIR"] == FOLDER


def test_without_a_recorded_folder_uv_keeps_its_default(monkeypatch) -> None:
    """unix.sh і старі установки теки не пишуть — тоді й Нишпорка її не задає."""
    monkeypatch.setattr(U, "install_info", lambda: {"uv": "uv"})
    assert "UV_PYTHON_INSTALL_DIR" not in U.uv_python_env()


def test_engine_env_install_uses_the_same_folder(info, monkeypatch) -> None:
    from nyshporka.htr import env as E

    seen: list[dict[str, str]] = []

    def fake_run(cmd, **kw):
        seen.append(kw["env"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(E.subprocess, "run", fake_run)
    E._run(["uv", "pip", "install", "x"])
    E._run_watching_448(["uv", "venv", "v", "--python", "3.11"])
    assert [e["UV_PYTHON_INSTALL_DIR"] for e in seen] == [FOLDER, FOLDER]


def test_engine_env_448_gives_the_installer_advice(info, monkeypatch) -> None:
    from nyshporka.htr import env as E

    monkeypatch.setattr(E.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 2, stdout="", stderr="error: Failed to create Python minor version link "
                                  "directory\n  Caused by: ... (os error 448)\n"))
    with pytest.raises(E.UntrustedMount) as exc:
        E._run_watching_448(["uv", "venv", "v", "--python", "3.11"])
    assert str(exc.value) == U.UNTRUSTED_MOUNT_HINT


def test_other_uv_failures_stay_ordinary(info, monkeypatch) -> None:
    from nyshporka.htr import env as E

    monkeypatch.setattr(E.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 2, stdout="", stderr="error: No interpreter found"))
    with pytest.raises(subprocess.CalledProcessError):
        E._run_watching_448(["uv", "venv", "v", "--python", "3.11"])


def test_htr_install_shows_the_advice_not_a_traceback(info, monkeypatch) -> None:
    from typer.testing import CliRunner

    from nyshporka import cli
    from nyshporka.htr import env as E

    monkeypatch.setattr(cli, "_need", lambda *a, **k: None)
    monkeypatch.setattr(E, "setup", lambda *a, **k: (_ for _ in ()).throw(
        E.UntrustedMount(U.UNTRUSTED_MOUNT_HINT)))
    res = CliRunner().invoke(cli.app, ["htr", "install"])
    assert res.exit_code == 2, res.output
    assert "os error 448" in res.output and "-PythonDir" in res.output


def test_update_line_carries_the_folder(info, monkeypatch) -> None:
    monkeypatch.setattr(U, "tool_env", lambda: True)
    monkeypatch.setattr(U.sys, "platform", "win32")
    line = U.how_to_update("researcher")
    assert line.startswith("$env:UV_PYTHON_INSTALL_DIR='D:\\Ім''я дослідника")
    assert "tool install" in line


# ── видалення ───────────────────────────────────────────────────────────────


def _plan(monkeypatch, tmp_path: Path, *, engines_venv: bool, engines: bool):
    from nyshporka.setup import uninstall as UN

    pydir = tmp_path / "python"
    pydir.mkdir()
    (pydir / "cpython-3.12.11-windows-x86_64-none").mkdir()
    monkeypatch.setattr(U, "install_info", lambda: {"python_dir": str(pydir)})
    monkeypatch.setattr(U, "install_home", lambda: tmp_path / "home")
    venv = tmp_path / "engines"
    if engines_venv:
        venv.mkdir()
    monkeypatch.setattr(UN, "_engine_venv", lambda: venv if engines_venv else None)
    return UN.plan(engines=engines), pydir


def test_uninstall_takes_the_python_folder(monkeypatch, tmp_path: Path) -> None:
    p, pydir = _plan(monkeypatch, tmp_path, engines_venv=False, engines=False)
    assert pydir in [i.path for i in p.items]
    assert not any("uv python uninstall" in k for k in p.kept)


def test_uninstall_keeps_the_python_under_kept_engines(monkeypatch, tmp_path: Path) -> None:
    """Рушії свідомо лишено — їхній інтерпретатор лежить саме в цій теці."""
    p, pydir = _plan(monkeypatch, tmp_path, engines_venv=True, engines=False)
    assert pydir not in [i.path for i in p.items]
    assert any(str(pydir) in k and "--engines" in k for k in p.kept)

    p, pydir2 = _plan_again(monkeypatch, tmp_path)
    assert pydir2 in [i.path for i in p.items]


def _plan_again(monkeypatch, tmp_path: Path):
    from nyshporka.setup import uninstall as UN

    return UN.plan(engines=True), Path(U.install_info()["python_dir"])


# ── doctor ──────────────────────────────────────────────────────────────────


def test_doctor_names_where_python_comes_from(info, monkeypatch) -> None:
    from nyshporka.setup import doctor

    monkeypatch.setattr(doctor, "_roaming_uv_pythons", lambda: [])   # не ця машина
    check = doctor._python()
    assert check.level == "ok"
    assert str(Path(__import__("sys").base_prefix)) in check.detail


def test_doctor_reports_roaming_leftovers_without_deleting(info, monkeypatch,
                                                           tmp_path: Path) -> None:
    from nyshporka.setup import doctor

    left = tmp_path / "uv" / "python" / "cpython-3.12.11-windows-x86_64-none"
    left.mkdir(parents=True)
    monkeypatch.setattr(doctor, "_roaming_uv_pythons", lambda: [left])
    check = doctor._python()
    assert check.level == "warn"
    assert "448" in check.detail and "не видаляю" in check.fix
    assert left.is_dir()


def test_roaming_scan_reads_appdata(monkeypatch, tmp_path: Path) -> None:
    from nyshporka.setup import doctor

    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "uv" / "python" / "cpython-3.12.11-windows-x86_64-none").mkdir(parents=True)
    (tmp_path / "uv" / "python" / ".lock").write_text("", encoding="utf-8")
    assert [p.name for p in doctor._roaming_uv_pythons()] == [
        "cpython-3.12.11-windows-x86_64-none"]
