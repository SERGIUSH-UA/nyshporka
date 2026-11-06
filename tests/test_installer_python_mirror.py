"""Архів Python повз мережевий стек uv — друга спроба інсталятора Windows.

🔴 06.11.2026: у людини `uv python install` чотири рази поспіль обривав архів
інтерпретатора на тому самому місці (~16,7 із 21 МБ) — «error reading a body
from connection: message buffer full», відмова TLS-бібліотеки uv (rustls).
Повтори uv її не лікують, тож інсталятор качає той самий архів засобами
Windows і дає uv теку як дзеркало `file://`; хеш uv звіряє сам.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "install" / "windows.ps1"


def _ps1() -> str:
    return PS1.read_text(encoding="utf-8-sig")


def _function(name: str) -> str:
    fn = re.search(rf"^function {name}\b.*?^}}\r?$", _ps1(), re.S | re.M)
    assert fn, f"{name} у windows.ps1"
    return fn.group(0)


def _python_step() -> str:
    text = _ps1()
    start = text.index("$rc = Invoke-Logged $uv python install $PyReq")
    return text[start:text.index("# ── 3. застосунок", start)]


def test_download_failure_gets_a_second_try_before_the_error() -> None:
    step = _python_step()
    junction = step.index("Resolve-ExtractedPython $tail $PythonDir '3.12'")
    retry = step.index("Save-PythonMirror $uv $PyReq $mirror")
    assert junction < retry < step.index("throw (M 'err.python' $rc)"), \
        "обхід junction — першим, обхід завантаження — перед відмовою"
    assert "$tail -notmatch 'os error 448'" in step[:retry], \
        "448 — не завантаження: порада про теку, а не друга спроба"
    # друга спроба — той самий запит, з тим самим обходом junction після неї
    assert step.count("Invoke-Logged $uv python install $PyReq") == 2
    assert step.count("Resolve-ExtractedPython $tail $PythonDir '3.12'") == 2


def test_the_mirror_variable_lives_only_for_that_call() -> None:
    step = _python_step()
    assert "$hadMirror = $env:UV_PYTHON_INSTALL_MIRROR" in step
    fin = step[step.index("} finally {"):]
    assert "$env:UV_PYTHON_INSTALL_MIRROR = $hadMirror" in fin, "змінну повернуто як була"
    assert "Remove-Item -LiteralPath $mirror -Recurse" in fin, "тека архіву не лишається"
    assert "SetEnvironmentVariable" not in step, "не постійна змінна користувача"


def test_the_archive_is_named_by_uv_not_by_the_installer() -> None:
    """Версія Python — справа uv: чужий uv новішої збірки хоче інший архів."""
    fn = _function("Save-PythonMirror")
    assert "python list $Request --only-downloads --output-format json" in fn
    assert "cpython-3.12." not in fn, "ім'я архіву не вписане руками"
    assert "Invoke-WebRequest" in fn
    # тека як у дзеркала: <реліз>/<файл>, ім'я — розкодоване (`%2B` → `+`)
    assert "Join-Path $Mirror $parts[-2]" in fn
    assert "[Uri]::UnescapeDataString($file)" in fn


# ── живий uv у Windows PowerShell 5.1 ───────────────────────────────────────
# Качає Python (~21 МБ), тож іде лише на CI або з `NYSH_TEST_UV=1`.

live_uv = pytest.mark.skipif(
    sys.platform != "win32" or not shutil.which("uv")
    or not (os.environ.get("CI") or os.environ.get("NYSH_TEST_UV")),
    reason="живий uv на Windows: CI або NYSH_TEST_UV=1")


@live_uv
@pytest.mark.timeout(900)
def test_live_python_installs_from_the_windows_download(tmp_path: Path) -> None:
    """Функція з windows.ps1 у 5.1, як у майстра `.exe`; тека — з кирилицею й пробілом."""
    uv = shutil.which("uv") or "uv"
    home = tmp_path / "Тека дослідника"
    folder = home / "python"
    mirror = home / "_python-mirror"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("UV_PYTHON") and k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    env.update(UV_PYTHON_INSTALL_DIR=str(folder), UV_PYTHON_INSTALL_BIN="0",
               UV_PYTHON_INSTALL_REGISTRY="0", UV_PYTHON_PREFERENCE="only-managed",
               UV_NO_CONFIG="1")
    script = tmp_path / "probe.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        + _function("Save-PythonMirror") + "\n"
        f"$why = Save-PythonMirror '{uv}' 'cpython-3.12-windows-x86_64-none' '{mirror}'\n"
        "if ($why) { throw \"не скачано: $why\" }\n"
        f"$env:UV_PYTHON_INSTALL_MIRROR = ([Uri]'{mirror}').AbsoluteUri\n"
        # мережі uv не потрібно: архів уже в теці
        "$env:UV_OFFLINE = '1'\n"
        "$ErrorActionPreference = 'Continue'\n"
        f"& '{uv}' python install cpython-3.12-windows-x86_64-none 2>&1 | ForEach-Object {{ \"$_\" }}\n"
        "exit $LASTEXITCODE\n", encoding="utf-8-sig")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script)], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    archives = list(mirror.glob("*/cpython-3.12.*+*-x86_64-pc-windows-msvc-*.tar.gz"))
    assert len(archives) == 1, f"розкладка дзеркала: {list(mirror.rglob('*'))}"
    exes = list(folder.glob("cpython-3.12.*-windows-x86_64-none/python.exe"))
    assert exes, r.stdout + r.stderr
    out = subprocess.run([str(exes[0]), "-c", "import ssl, sys; print(sys.version_info[:2])"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "(3, 12)"
