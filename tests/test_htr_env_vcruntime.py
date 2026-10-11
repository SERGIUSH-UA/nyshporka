"""🧩 torch, що стоїть, але не вантажиться, — і Visual C++ Redistributable.

Чиста Windows Sandbox, 11.10.2026: `nysh htr install` поставив усе, `doctor`
писав «✅ Рушії читання kraken 7.1.1 · CPU», а `import torch` падав «Error
loading c10.dll» — у системі не було Microsoft Visual C++ Redistributable.
Огляд питав лише метадані пакетів, тож зламаний torch виглядав готовим, і
читання не запускалось без жодного червоного рядка.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nyshporka.htr import env
from nyshporka.setup import doctor

_C10 = ('OSError: [WinError 126] The specified module could not be found. Error loading '
        '"…\\torch\\lib\\c10.dll" or one of its dependencies.\n'
        "Microsoft Visual C++ Redistributable is not installed, this may lead to the DLL load failure.")


def _torch_installed_not_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 err: str) -> Path:
    """Середовище, де метадані torch є, а `import torch` падає з `err`."""
    py = env.venv_python(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")

    def probe(_py: Path, code: str, timeout: int = 120) -> str | None:
        if "version('kraken')" in code:
            return "7.1.1"
        if code.startswith("import importlib.metadata"):
            return "2.14.0"                   # пакет стоїть — і torch теж
        if code.startswith("import strhub"):
            return ""
        return None                           # будь-який `import torch` падає

    monkeypatch.setattr(env, "_probe", probe)
    monkeypatch.setattr(env, "_import_failure", lambda _py, module, timeout=120: err)
    return tmp_path


def test_torch_that_does_not_load_is_not_ready(tmp_path, monkeypatch):
    """🔴 Приймач самої вади: зламаний torch — не «рушії готові»."""
    monkeypatch.setattr(env, "vc_runtime_missing", lambda: ("msvcp140.dll", "vcruntime140.dll"))
    venv = _torch_installed_not_loading(tmp_path, monkeypatch, _C10)

    rep = env.inspect(venv)

    assert not rep.ok, "огляд знову назвав середовище готовим"
    assert "Visual C++" in rep.torch_broken and "msvcp140.dll" in rep.torch_broken
    # Не лише діагноз — у тому самому рядку ліки.
    assert any("nysh htr install" in p for p in rep.problems), rep.problems


def test_other_load_failures_are_named_not_swallowed(tmp_path, monkeypatch):
    """Не кожна відмова — Visual C++; тоді в рядку стоїть сама причина."""
    monkeypatch.setattr(env, "vc_runtime_missing", lambda: ())
    err = "Traceback (most recent call last):\nImportError: DLL load failed while importing _C"
    venv = _torch_installed_not_loading(tmp_path, monkeypatch, err)

    rep = env.inspect(venv)

    assert not rep.ok
    assert "DLL load failed" in rep.torch_broken and "Visual C++" not in rep.torch_broken


def test_absent_torch_is_still_missing_not_broken(tmp_path, monkeypatch):
    """Немає torch зовсім — це «не зібрано», а не «не вантажиться»."""
    py = env.venv_python(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(env, "_probe", lambda _py, code, timeout=120: None)
    called: list[str] = []
    monkeypatch.setattr(env, "_import_failure",
                        lambda _py, module, timeout=120: called.append(module) or "")

    rep = env.inspect(tmp_path)

    assert not rep.torch_broken and not called


# ── доктор ───────────────────────────────────────────────────────────────────
def _report(monkeypatch, **kw) -> None:
    monkeypatch.setattr(doctor, "_engine_report",
                        lambda: env.EnvReport(ok=False, python=Path("py"), **kw))
    monkeypatch.setattr(doctor, "engine_venv", lambda: Path("venv"))


def test_doctor_sends_to_vc_redist_not_to_a_2_5_gb_download(monkeypatch):
    msg = "torch стоїть, але не вантажиться: бракує Microsoft Visual C++ Redistributable"
    _report(monkeypatch, kraken="7.1.1", torch_broken=msg, problems=(msg,))
    monkeypatch.setattr(env, "vc_runtime_missing", lambda: ("msvcp140.dll",))

    eng = doctor._engines()

    assert eng.level != "ok"
    assert "Visual C++" in eng.fix and "2.5" not in eng.fix, eng.fix


def test_gpu_line_does_not_say_torch_is_absent_when_it_only_fails_to_load(monkeypatch):
    msg = "torch стоїть, але не вантажиться: …"
    _report(monkeypatch, torch_broken=msg, problems=(msg,))

    gpu = doctor._torch()

    assert "не вантажиться" in gpu.detail and "немає" not in gpu.detail


# ── доставка Visual C++ ──────────────────────────────────────────────────────
def _vc_states(monkeypatch, *states: tuple[str, ...]) -> None:
    seq = list(states)
    monkeypatch.setattr(env, "vc_runtime_missing", lambda: seq.pop(0) if len(seq) > 1 else seq[0])


def test_vc_redist_is_installed_from_microsoft_and_checked_by_files(monkeypatch, capsys):
    _vc_states(monkeypatch, ("msvcp140.dll",), ())
    got: dict[str, object] = {}
    monkeypatch.setattr(env, "_download", lambda url, target: got.update(url=url))
    monkeypatch.setattr(env, "_run_signed_elevated",
                        lambda exe, args: got.update(args=args) or 0)

    env._ensure_vc_runtime()

    assert str(got["url"]).startswith("https://aka.ms/vs/17/release/vc_redist.")
    assert "/install" in got["args"] and "/norestart" in got["args"]
    assert "✓ Visual C++" in capsys.readouterr().out


def test_declined_or_failed_vc_install_does_not_break_setup(monkeypatch, capsys):
    """Відмова у вікні Windows — не трасування: рядок із ручним шляхом."""
    _vc_states(monkeypatch, ("msvcp140.dll",))
    monkeypatch.setattr(env, "_download", lambda url, target: None)

    def refuse(exe, args):
        raise RuntimeError("The operation was canceled by the user.")

    monkeypatch.setattr(env, "_run_signed_elevated", refuse)

    env._ensure_vc_runtime()

    out = capsys.readouterr().out
    assert "не поставився" in out and "aka.ms" in out and "canceled" in out


def test_present_vc_runtime_downloads_nothing(monkeypatch):
    _vc_states(monkeypatch, ())
    monkeypatch.setattr(env, "_download",
                        lambda *a: pytest.fail("качав інсталятор, хоча все на місці"))
    env._ensure_vc_runtime()


@pytest.mark.skipif(os.name != "nt", reason="бібліотеки Visual C++ є лише у Windows")
def test_vc_runtime_is_looked_up_in_system32(tmp_path, monkeypatch):
    sys32 = tmp_path / "System32"
    sys32.mkdir()
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    assert "msvcp140.dll" in env.vc_runtime_missing()
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        (sys32 / name).write_bytes(b"")
    assert env.vc_runtime_missing() == ()


def test_vc_runtime_is_a_windows_only_question(monkeypatch):
    monkeypatch.setattr(env.os, "name", "posix")
    assert env.vc_runtime_missing() == ()
