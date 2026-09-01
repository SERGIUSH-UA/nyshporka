"""🖋 Крок, який доставляє CUDA-колесо: чим міряють карту й що кажуть людині.

🔴 Гілка `_ensure_cuda()` не була покрита нічим, і саме в ній жив issue #7:
capability питали в torch, а на Windows це щойно поставлене CPU-колесо, у якого
CUDA немає за побудовою. Тести матриці при цьому проходили — вони подавали
`"8.6"` уже готовим рядком. Тобто доведено було, що матриця правильна, і ніде —
що до матриці доїжджає число.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nyshporka.htr import env
from nyshporka.htr import manifest as M

RTX_3050 = env.gpu.Card(name="NVIDIA GeForce RTX 3050", capability="8.6", driver="581.15")


@pytest.fixture
def man() -> M.Manifest:
    return M.load()


class Fake:
    """Середовище без середовища: проби, встановлення й відповідь драйвера."""

    def __init__(self, monkeypatch, *, sees: list[str], card, fails: bool = False) -> None:
        self.cmds: list[list[str]] = []
        self.asked_driver = 0
        self._sees = list(sees)
        self._fails = fails

        def probe(_py: Path, code: str, **_kw: object) -> str:
            # Єдина проба, що лишилась у цій гілці, — «чи бачить torch карту».
            assert "cuda.is_available" in code, f"зайва проба torch: {code}"
            return self._sees.pop(0)

        def run(cmd: list[str]) -> None:
            self.cmds.append(cmd)
            if self._fails:
                raise subprocess.CalledProcessError(1, cmd)

        def detect():  # type: ignore[no-untyped-def]
            self.asked_driver += 1
            return card

        monkeypatch.setattr(env, "_probe", probe)
        monkeypatch.setattr(env, "_run", run)
        monkeypatch.setattr(env.gpu, "detect_card", detect)


def _index(cmd: list[str]) -> str:
    return cmd[cmd.index("--index-url") + 1]


def test_cpu_wheel_does_not_hide_the_card(monkeypatch, man, capsys):
    """🔴 Регресія issue #7 у чистому вигляді.

    torch зібраний під CPU і чесно каже «карти немає» — це не відповідь про
    залізо. Драйвер каже `8.6`, і колесо мусить поїхати саме за ним.
    """
    fake = Fake(monkeypatch, sees=["False", "True"], card=RTX_3050)
    env._ensure_cuda(Path("venv"), man)

    assert fake.asked_driver == 1, "карту треба питати в драйвера, а не в torch"
    assert len(fake.cmds) == 1
    assert _index(fake.cmds[0]).endswith("/cu126")
    out = capsys.readouterr().out
    assert "RTX 3050" in out and "підхопилась" in out


def test_wheel_that_installed_but_did_not_help_is_not_success(monkeypatch, man, capsys):
    """Приймач кроку — повторна проба, а не код повернення `uv`."""
    Fake(monkeypatch, sees=["False", "False"], card=RTX_3050)
    env._ensure_cuda(Path("venv"), man)
    out = capsys.readouterr().out
    assert "не бачить карту" in out and "issue" in out


def test_working_gpu_is_left_alone(monkeypatch, man, capsys):
    fake = Fake(monkeypatch, sees=["True"], card=RTX_3050)
    env._ensure_cuda(Path("venv"), man)
    assert fake.cmds == [] and fake.asked_driver == 0
    assert "уже бачить карту" in capsys.readouterr().out


def test_no_card_installs_nothing_and_says_why(monkeypatch, man, capsys):
    fake = Fake(monkeypatch, sees=["False"], card=None)
    env._ensure_cuda(Path("venv"), man)
    assert fake.cmds == []
    out = capsys.readouterr().out
    assert "nvidia-smi" in out and env.gpu.CPU_NOTE in out


def test_driver_that_does_not_report_capability_names_the_card(monkeypatch, man, capsys):
    card = env.gpu.Card(name="NVIDIA GeForce GTX 1080", capability="", driver="470.05")
    fake = Fake(monkeypatch, sees=["False"], card=card)
    env._ensure_cuda(Path("venv"), man)
    assert fake.cmds == [], "без capability колесо ставити нема з чого"
    assert "GTX 1080" in capsys.readouterr().out


def test_old_driver_is_refused_before_the_wheel(monkeypatch, man, capsys):
    """Колесо стало б мовчки й упало б аж на прогоні — «insufficient driver»."""
    card = env.gpu.Card(name="NVIDIA GeForce RTX 3050", capability="8.6", driver="460.89")
    fake = Fake(monkeypatch, sees=["False"], card=card)
    env._ensure_cuda(Path("venv"), man)
    assert fake.cmds == []
    assert "527.41" in capsys.readouterr().out


def test_failed_install_leaves_a_working_cpu_build(monkeypatch, man, capsys):
    """Індекси PyTorch зсуваються від релізу до релізу — це не привід на трасу."""
    fake = Fake(monkeypatch, sees=["False"], card=RTX_3050, fails=True)
    env._ensure_cuda(Path("venv"), man)
    assert len(fake.cmds) == 1
    out = capsys.readouterr().out
    assert "cu126" in out and "--cuda" in out


def test_manual_tag_skips_detection(monkeypatch, man, capsys):
    """Ручний обхід на випадок, коли детект однаково промахнувся."""
    fake = Fake(monkeypatch, sees=["False", "True"], card=None)
    env._ensure_cuda(Path("venv"), man, force_tag="cu128")
    assert fake.asked_driver == 0
    assert _index(fake.cmds[0]).endswith("/cu128")
    assert "вручну" in capsys.readouterr().out
