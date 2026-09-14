"""🖋 Intel Mac: рушії читання сюди не стануть ніколи — і сказати це треба ДО uv.

Issue #10 (12.09.2026): інсталятор на macOS 13 / x86_64 поставив uv і Python,
а тоді впав на резолвері — `torchvision>=0.20` не має колеса для
`macosx_13_0_x86_64`. PyTorch перестав збирати x86-колеса для macOS після
torch 2.2.2 / torchvision 0.17.2, а `kraken==7.0.2` (пін під патчі) вимагає
torch ≥ 2.4, тож нема версії, яка задовольнила б обох. Приймачі нижче тримають
три речі: причина називається одним рядком і до будь-якої дії; extra `htr`
пакета на такій машині порожній, а не вбивчий; інсталятор підміняє `htr` на
`cloud`, а не падає.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from nyshporka.htr import env

ROOT = Path(__file__).resolve().parents[1]
INTEL_MAC_MARKER = "platform_system != 'Darwin' or platform_machine != 'x86_64'"


def _pretend(monkeypatch: pytest.MonkeyPatch, *, platform: str, machine: str) -> None:
    import platform as _platform

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(_platform, "machine", lambda: machine)


@pytest.mark.parametrize(("platform", "machine"), [
    ("win32", "AMD64"),
    ("linux", "x86_64"),
    ("darwin", "arm64"),
])
def test_everywhere_else_engines_are_allowed(monkeypatch, platform, machine) -> None:
    _pretend(monkeypatch, platform=platform, machine=machine)
    assert env.unsupported_here() == ""


def test_intel_mac_is_named_with_the_way_out(monkeypatch) -> None:
    """Причина без виходу — це та сама відмова, лише ввічливіша."""
    _pretend(monkeypatch, platform="darwin", machine="x86_64")
    why = env.unsupported_here()
    assert "Intel" in why and "2.2.2" in why, why
    assert "nysh cloud" in why, "не сказано, як читати без рушіїв на цій машині"


def test_setup_refuses_before_touching_uv(monkeypatch, tmp_path) -> None:
    """🔴 Відмова ДО `uv venv`: порожнє середовище лишало б теку й пораду
    «nysh htr install», яка веде назад у ту саму відмову."""
    _pretend(monkeypatch, platform="darwin", machine="x86_64")

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("до uv дійшло — відмова стоїть не там")

    monkeypatch.setattr(env, "_need_tool", boom)
    monkeypatch.setattr(env, "_run", boom)
    with pytest.raises(env.EnginesUnsupported):
        env.setup(tmp_path / ".venv_htr")
    assert not (tmp_path / ".venv_htr").exists()


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


def test_unix_installer_swaps_engines_for_cloud_on_intel_mac() -> None:
    """Інсталятор дізнається про Intel Mac до `uv tool install`, а не з його
    відмови — і ставить замість рушіїв те, чим читати на іншій машині."""
    text = (ROOT / "install" / "unix.sh").read_text(encoding="utf-8")
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    joined = "\n".join(code)
    assert "uname -m" in joined and "x86_64" in joined and "Darwin" in joined, (
        "unix.sh: платформа не перевіряється — Intel Mac упаде на резолвері")
    assert "s/,htr/,cloud/" in joined, (
        "unix.sh: extra `htr` не підміняється на `cloud` — читати буде нічим")
    assert "NYSH_SOURCE" in joined.split("uname -m")[0] or \
        'NYSH_SOURCE:-' in joined.split("s/,htr/,cloud/")[0], (
        "unix.sh: явний NYSH_SOURCE мусить лишатись недоторканим")
