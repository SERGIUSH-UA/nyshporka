"""🖋 Intel Mac: torch з PyPI не стане ніколи — середовище рушіїв іде з conda-forge.

Issue #10 (12.09.2026): інсталятор на macOS 13 / x86_64 поставив uv і Python,
а тоді впав на резолвері — `torchvision>=0.20` не має колеса для
`macosx_13_0_x86_64`. PyTorch перестав збирати x86-колеса для macOS після
torch 2.2.2 / torchvision 0.17.2, а `kraken==7.0.2` (пін під патчі) вимагає
torch ≥ 2.4 — з PyPI цю пару не скласти. conda-forge збирає pytorch для osx-64
далі, тож там середовище створює micromamba, а не `uv venv`.

Приймачі нижче тримають чотири речі: платформа впізнається по інтерпретатору;
на ній `setup()` кличе conda-інструмент, а не `uv venv`, і кличе його ДО pip;
extra `htr` пакета на такій машині порожній, а не вбивчий; інсталятор каже про
окремий крок заздалегідь.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from nyshporka.htr import env
from nyshporka.htr import manifest as M

ROOT = Path(__file__).resolve().parents[1]
INTEL_MAC_MARKER = "platform_system != 'Darwin' or platform_machine != 'x86_64'"


def _pretend(monkeypatch: pytest.MonkeyPatch, *, platform: str, machine: str) -> None:
    import platform as _platform

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(_platform, "machine", lambda: machine)


@pytest.mark.parametrize(("platform", "machine", "expect"), [
    ("win32", "AMD64", False),
    ("linux", "x86_64", False),
    ("darwin", "arm64", False),
    ("darwin", "x86_64", True),
])
def test_intel_mac_is_the_interpreter_not_the_metal(monkeypatch, platform, machine, expect) -> None:
    _pretend(monkeypatch, platform=platform, machine=machine)
    assert env.intel_mac() is expect


def test_manifest_carries_a_conda_recipe_that_fits_kraken() -> None:
    """🔴 Без блоку conda Intel Mac лишається без torch; стеля 2.10 — межа kraken 7.0.2."""
    man = M.load()
    assert man.conda_channel == "conda-forge"
    torch_spec = next((p for p in man.conda_packages if p.startswith("pytorch")), "")
    assert torch_spec, "у conda-рецепті немає pytorch"
    assert ">=2.4" in torch_spec and "<=2.10" in torch_spec, torch_spec
    assert any(p.startswith("torchvision") for p in man.conda_packages)


def test_setup_on_intel_mac_builds_the_env_from_conda_forge(monkeypatch, tmp_path) -> None:
    """🔴 `uv venv` + pip на Intel Mac дали б відмову резолвера на torch — ПІСЛЯ
    того, як усе інше стало. Тому середовище створює conda-інструмент, з
    рецептом маніфесту, і лише потім pip докладає решту."""
    _pretend(monkeypatch, platform="darwin", machine="x86_64")
    venv = tmp_path / ".venv_htr"
    calls: list[list[str]] = []

    def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
        calls.append(cmd)
        if cmd[1:2] == ["create"]:
            assert env and env.get("MAMBA_ROOT_PREFIX"), "кеш micromamba поїхав би в ~/micromamba"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_text("", encoding="utf-8")

    monkeypatch.setattr(env, "_run", run)
    monkeypatch.setattr(env, "_need_tool", lambda *a, **k: None)
    monkeypatch.setattr(env, "_resolve_tool", lambda name: name)
    monkeypatch.setattr(env, "_conda_tool", lambda: "/tools/micromamba")
    # ⚠ Не справжня тека застосунку: під фальшивим darwin її читач тягне
    # `urllib.request`, а той на «macOS» шукає `_scproxy`, якого тут немає.
    monkeypatch.setattr(env, "_micromamba_home", lambda: tmp_path / "micromamba")
    monkeypatch.setattr(env, "inspect", lambda v, m=None: env.EnvReport(ok=True, python=v))

    env.setup(venv, with_cuda=False)

    assert calls, "нічого не запущено"
    create = calls[0]
    assert create[0] == "/tools/micromamba" and create[1] == "create", create
    assert "-c" in create and create[create.index("-c") + 1] == "conda-forge"
    assert "--override-channels" in create
    assert f"python={M.load().python}" in create
    assert any(a.startswith("pytorch") for a in create), create
    assert not any(c[:2] == ["uv", "venv"] for c in calls), "uv venv на Intel Mac — назад у відмову"


def test_conda_tool_prefers_what_is_already_on_the_machine(monkeypatch) -> None:
    """Свій micromamba — лише коли на машині немає ні його, ні mamba, ні conda."""
    monkeypatch.setattr(env, "_resolve_tool",
                        lambda name: "/opt/conda/bin/conda" if name == "conda" else "")
    monkeypatch.setattr(env, "_fetch_micromamba",
                        lambda target: pytest.fail("завантажив попри наявний conda"))
    assert env._conda_tool() == "/opt/conda/bin/conda"


def test_macos_skips_the_cuda_step(monkeypatch, tmp_path, capsys) -> None:
    """CUDA на macOS немає за побудовою — питати nvidia-smi там означає друкувати
    «карти не видно» на кожному Mac."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(env, "_probe", lambda *a, **k: pytest.fail("проба torch на macOS зайва"))
    env._ensure_cuda(tmp_path, M.load())
    assert "CPU" in capsys.readouterr().out


def test_htr_extra_is_empty_on_intel_mac_instead_of_fatal() -> None:
    """🔴 Extra `htr` без маркера валив `pip install 'nyshporka[app,archives,htr]'`
    і `nysh update` ЦІЛКОМ — разом із консоллю й архівами, яким torch не
    потрібен. Рушії живуть в окремому середовищі, тож у самому пакеті torch на
    такій машині нема за що триматись."""
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    htr = meta["project"]["optional-dependencies"]["htr"]
    assert htr, "extra `htr` спорожнів зовсім — інсталятор ставитиме невідомо що"
    for spec in htr:
        assert INTEL_MAC_MARKER in spec, (
            f"{spec}: без маркера платформи ця вимога валить установку на Intel Mac")


def test_unix_installer_warns_intel_mac_about_the_separate_step() -> None:
    """Інсталятор дізнається про Intel Mac до `uv tool install`, а не з його
    відмови, і каже, що рушії збираються окремо — інакше «HTR: немає» у
    `nysh info` читається як поломка."""
    text = (ROOT / "install" / "unix.sh").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "uname -m" in code and "x86_64" in code and "Darwin" in code, (
        "unix.sh: платформа не перевіряється")
    assert "conda-forge" in code and "nysh htr install" in code, (
        "unix.sh: не сказано, звідки візьмуться рушії на Intel Mac")
    assert "s/,htr/,cloud/" not in code, "extra htr більше не підміняється — установка проходить"
