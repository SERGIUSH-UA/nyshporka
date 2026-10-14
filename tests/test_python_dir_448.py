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

import os
import re
import shutil
import subprocess
import sys
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


# ── майстер .exe ────────────────────────────────────────────────────────────


def test_wizard_asks_for_the_python_folder_and_passes_it_on() -> None:
    """Користувач `.exe` із 448 не мав де вказати теку — лишалось запускати
    windows.ps1 руками (рішення дослідника 14.10.2026: окреме поле)."""
    iss = (ROOT / "install" / "nyshporka.iss").read_text(encoding="utf-8-sig")
    assert "CreateInputDirPage(PresetPage.ID" in iss
    assert "PythonDirFlag() +" in iss and "' -PythonDir \"'" in iss
    assert "{param:pythondir|}" in iss, "тихий режим: /PYTHONDIR="
    for lang in ("ukrainian", "english", "polish", "romanian", "french", "german", "russian"):
        for key in ("PyDirTitle", "PyDirSub", "PyDirDesc"):
            assert f"\n{lang}.{key}=" in iss, f"{lang}.{key}"


# ── збій junction мінорної версії: інтерпретатор напряму ────────────────────
# 🔴 15.10.2026: 448 повторилась і з текою `{app}\python` (AppData\Local) —
# тека тут ні до чого. uv робить junction ПІСЛЯ того, як інтерпретатор
# розпакований, тож його `python.exe` береться напряму.

LINK_FAIL = ("error: Failed to create Python minor version link directory\n"
             "  Caused by: Le chemin d'accès ne peut pas être parcouru (os error 448)\n")


def _patch_dir(root: Path, name: str, *, exe: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if exe:
        (d / "python.exe").write_bytes(b"")
    return d


def test_link_step_is_recognised_by_both_phrasings() -> None:
    assert U.link_step_failed(LINK_FAIL)
    assert U.link_step_failed("error: Missing expected target directory for Python "
                              "minor version link at C:\\x")
    assert not U.link_step_failed("error: Failed to download https://… (os error 10054)")


def test_extracted_python_takes_the_highest_real_patch(tmp_path: Path) -> None:
    _patch_dir(tmp_path, "cpython-3.12.9-windows-x86_64-none")
    best = _patch_dir(tmp_path, "cpython-3.12.15-windows-x86_64-none")
    _patch_dir(tmp_path, "cpython-3.12.20+freethreaded-windows-x86_64-none")
    _patch_dir(tmp_path, "cpython-3.12.30-windows-x86_64-none", exe=False)
    _patch_dir(tmp_path, "cpython-3.12-windows-x86_64-none")  # недоробок junction
    _patch_dir(tmp_path, "cpython-3.11.14-windows-x86_64-none")
    assert U.extracted_python(tmp_path, "3.12") == best / "python.exe"
    assert U.extracted_python(tmp_path, "3.13") is None
    assert U.extracted_python(tmp_path / "немає", "3.12") is None


def test_link_leftover_goes_but_nothing_with_content(tmp_path: Path) -> None:
    empty = _patch_dir(tmp_path, "cpython-3.12-windows-x86_64-none", exe=False)
    full = _patch_dir(tmp_path, "cpython-3.12-windows-aarch64-none")
    U._drop_link_leftover(tmp_path, "3.12")
    assert not empty.exists()
    assert (full / "python.exe").is_file()


def _fake_uv(monkeypatch: pytest.MonkeyPatch, rc: int, out: str, *, runs: bool = True) -> None:
    def run(cmd, **kw):
        if cmd[1:3] == ["python", "install"]:
            return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=out)
        return subprocess.CompletedProcess(cmd, 0, stdout="3.12\n" if runs else "", stderr="")

    monkeypatch.setattr(subprocess, "run", run)


def test_ensure_python_falls_back_to_the_extracted_interpreter(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(U.sys, "platform", "win32")
    exe = _patch_dir(tmp_path, "cpython-3.12.15-windows-x86_64-none") / "python.exe"
    _fake_uv(monkeypatch, 2, LINK_FAIL)
    assert U.ensure_python("uv", "3.12", {"UV_PYTHON_INSTALL_DIR": str(tmp_path)}) == str(exe)


def test_ensure_python_keeps_the_version_when_uv_succeeds(monkeypatch, tmp_path) -> None:
    _fake_uv(monkeypatch, 0, "")
    assert U.ensure_python("uv", "3.11", {"UV_PYTHON_INSTALL_DIR": str(tmp_path)}) == "3.11"


def test_ensure_python_refuses_an_interpreter_that_does_not_run(monkeypatch, tmp_path) -> None:
    """Розпакований, але не запускається (інша версія, обірвана розпаковка) —
    тоді це справжня відмова з порадою, а не тихий перехід на зламаний Python."""
    monkeypatch.setattr(U.sys, "platform", "win32")
    _patch_dir(tmp_path, "cpython-3.12.15-windows-x86_64-none")
    _fake_uv(monkeypatch, 2, LINK_FAIL, runs=False)
    with pytest.raises(U.PythonInstallFailed) as exc:
        U.ensure_python("uv", "3.12", {"UV_PYTHON_INSTALL_DIR": str(tmp_path)})
    assert str(exc.value) == U.UNTRUSTED_MOUNT_HINT


def test_engine_venv_is_built_on_the_interpreter_ensure_python_gave(info, monkeypatch,
                                                                    tmp_path) -> None:
    """`uv venv --python 3.11` сам качав би 3.11 і падав на тому самому junction."""
    from nyshporka.htr import env as E

    seen: list[list[str]] = []
    given = r"C:\py\cpython-3.11.14-windows-x86_64-none\python.exe"
    monkeypatch.setattr(E, "intel_mac", lambda: False)
    monkeypatch.setattr(E, "_need_tool", lambda *a, **k: None)
    monkeypatch.setattr(E, "_resolve_tool", lambda uv: uv)
    monkeypatch.setattr(U, "ensure_python", lambda uv, v, env: given)
    monkeypatch.setattr(E, "_run_watching_448", lambda cmd: seen.append(cmd))
    class Built(Exception):
        """venv створено — далі не йдемо."""

    def stop(*a, **k):
        raise Built

    monkeypatch.setattr(E, "inspect", stop)
    with pytest.raises(Built):
        E.setup(tmp_path / "venv", with_cuda=False)
    assert seen and seen[0][1] == "venv"
    assert seen[0][-2:] == ["--python", given]


def test_installer_hands_the_extracted_interpreter_to_tool_install() -> None:
    text = _ps1()
    assert "function Resolve-ExtractedPython" in text
    at = text.index("Invoke-Logged $uv python install 3.12")
    assert text.index("Resolve-ExtractedPython $tail $PythonDir '3.12'", at) > at
    assert "Invoke-Logged $uv tool install --python $PythonArg --force $Source" in text
    for phrase in U.LINK_STEP_FAILURES:
        assert phrase in text, "інсталятор і пакет упізнають той самий крок"


# ── живий uv на Windows ─────────────────────────────────────────────────────
# Справжню 448 на CI не змоделювати, але в uv це та сама гілка: файл на місці
# junction (`cpython-3.12-windows-…-none`) дає ту саму відмову «Failed to
# create Python minor version link directory» після розпаковки. Тест качає
# Python (~21 МБ), тож іде лише на CI або з `NYSH_TEST_UV=1`.

live_uv = pytest.mark.skipif(
    sys.platform != "win32" or not shutil.which("uv")
    or not (os.environ.get("CI") or os.environ.get("NYSH_TEST_UV")),
    reason="живий uv на Windows: CI або NYSH_TEST_UV=1")


def _trapped_folder(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    import platform

    arch = {"AMD64": "x86_64", "ARM64": "aarch64"}.get(platform.machine(), platform.machine())
    folder = tmp_path / "python"
    folder.mkdir()
    (folder / f"cpython-3.12-windows-{arch}-none").write_text("пастка", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("UV_PYTHON") and k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    env.update(UV_PYTHON_INSTALL_DIR=str(folder), UV_PYTHON_INSTALL_BIN="0",
               UV_PYTHON_INSTALL_REGISTRY="0", UV_NO_CONFIG="1")
    return folder, env


@live_uv
@pytest.mark.timeout(900)
def test_live_uv_link_failure_still_gives_a_working_venv(tmp_path, capsys) -> None:
    uv = shutil.which("uv") or "uv"
    folder, env = _trapped_folder(tmp_path)
    python = U.ensure_python(uv, "3.12", env)
    assert "Failed to create Python minor version link directory" in capsys.readouterr().err, \
        "пастка не спрацювала — uv змінив крок junction, тест треба переглянути"
    assert Path(python).parent.parent == folder and python.endswith("python.exe")
    venv = tmp_path / "venv"
    subprocess.run([uv, "venv", str(venv), "--python", python], env=env, check=True,
                   cwd=tmp_path)
    out = subprocess.run([str(venv / "Scripts" / "python.exe"), "-c",
                          "import sqlite3, ssl, sys; print(sys.version_info[:2])"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "(3, 12)"


@live_uv
@pytest.mark.timeout(900)
def test_live_installer_function_finds_the_interpreter(tmp_path) -> None:
    """Сама функція з windows.ps1 — у Windows PowerShell 5.1, як у майстра .exe."""
    uv = shutil.which("uv") or "uv"
    folder, env = _trapped_folder(tmp_path)
    fn = re.search(r"^function Resolve-ExtractedPython.*?^}\r?$", _ps1(), re.S | re.M)
    assert fn, "функція в windows.ps1"
    script = tmp_path / "probe.ps1"
    script.write_text(
        # 'Continue': у 5.1 рядок stderr рідної команди під 'Stop' — термінальна помилка
        "$ErrorActionPreference = 'Continue'\n"
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        + fn.group(0) + "\n"
        f"$tail = (& '{uv}' python install 3.12 2>&1 | ForEach-Object {{ \"$_\" }}) -join \"`n\"\n"
        "if ($LASTEXITCODE -eq 0) { throw 'пастка не спрацювала' }\n"
        f"$exe = Resolve-ExtractedPython $tail '{folder}' '3.12'\n"
        "if (-not $exe) { throw \"не знайшов: $tail\" }\n"
        "Write-Output $exe\n", encoding="utf-8-sig")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script)], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    exe = Path(r.stdout.strip().splitlines()[-1])
    assert exe.parent.parent == folder and exe.is_file()
