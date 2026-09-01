"""🖋 Карта за словами драйвера, а не за словами torch.

Тест існує через issue #7: на Windows дефолтне колесо torch — `+cpu`, тож
питання «яка тут карта» до torch не має відповіді за побудовою, і робоча RTX
3050 читалась як «карти не видно». Тому тут перевіряється рівно те, що доїжджає
до матриці колес: розбір виводу `nvidia-smi` і межа між «карти немає» та «карта
є, але драйвер про неї не каже».
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from nyshporka.htr import gpu


def _smi(monkeypatch, answers: dict[str, tuple[int, str]]) -> list[str]:
    """Підмінити `nvidia-smi`: запит (поля) → (код повернення, вивід).

    Повертається список зроблених запитів — послідовність тут значуща: другий
    запит робиться лише тоді, коли перший не відповів.
    """
    asked: list[str] = []

    def fake_run(cmd, **kw):  # type: ignore[no-untyped-def]
        fields = next(a for a in cmd if a.startswith("--query-gpu="))[len("--query-gpu="):]
        asked.append(fields)
        rc, out = answers.get(fields, (2, ""))
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(gpu.shutil, "which", lambda _n: "nvidia-smi")
    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    return asked


FULL = "name,compute_cap,driver_version"
SHORT = "name,driver_version"


def test_card_comes_from_the_driver(monkeypatch):
    """Той самий стан, що в репорті: карта є, torch про неї не знає."""
    _smi(monkeypatch, {FULL: (0, "NVIDIA GeForce RTX 3050, 8.6, 581.15\n")})
    card = gpu.detect_card()
    assert card == gpu.Card(name="NVIDIA GeForce RTX 3050", capability="8.6", driver="581.15")
    assert "RTX 3050" in card.label() and "8.6" in card.label()


def test_old_driver_names_the_card_without_capability(monkeypatch):
    """🔴 «Карта є, але яка — не сказано» і «карти немає» — різні відповіді.

    Драйвери до R510 поля `compute_cap` не знають, і запит падає ЦІЛИМ. Якщо не
    перепитати коротшим набором, машина з робочою картою потрапляє в ту саму
    гілку, що машина без карти взагалі, — і людина читає, що карти немає.
    """
    asked = _smi(monkeypatch, {FULL: (6, "Field \"compute_cap\" is not a valid field\n"),
                               SHORT: (0, "NVIDIA GeForce GTX 1080, 470.05\n")})
    card = gpu.detect_card()
    assert card == gpu.Card(name="NVIDIA GeForce GTX 1080", capability="", driver="470.05")
    assert asked == [FULL, SHORT]


def test_no_smi_means_no_card(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _n: None)
    monkeypatch.setattr(gpu, "_smi_path", lambda: None)
    assert gpu.detect_card() is None


def test_smi_that_answers_nothing_is_not_a_card(monkeypatch):
    asked = _smi(monkeypatch, {FULL: (0, "\n"), SHORT: (0, "")})
    assert gpu.detect_card() is None
    assert asked == [FULL, SHORT]


def test_placeholders_are_not_values(monkeypatch):
    """`[N/A]` — це «поля немає», і воно не сміє доїхати до матриці колес."""
    _smi(monkeypatch, {FULL: (0, "NVIDIA GeForce MX150, [N/A], [Not Supported]\n")})
    card = gpu.detect_card()
    assert card is not None
    assert card.capability == "" and card.driver == ""


def test_capability_must_look_like_a_number(monkeypatch):
    _smi(monkeypatch, {FULL: (0, "NVIDIA T400, not supported, 550.90\n")})
    card = gpu.detect_card()
    assert card is not None and card.capability == "" and card.driver == "550.90"


def test_first_row_is_the_card_torch_will_use(monkeypatch):
    """Дві карти → береться перша: саме її torch бачить як `cuda:0`."""
    _smi(monkeypatch, {FULL: (0, "NVIDIA RTX A4000, 8.6, 550.90\n"
                                 "NVIDIA GeForce GT 1030, 6.1, 550.90\n")})
    card = gpu.detect_card()
    assert card is not None and card.name == "NVIDIA RTX A4000"


def test_broken_smi_does_not_raise(monkeypatch):
    def boom(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=1)

    monkeypatch.setattr(gpu.shutil, "which", lambda _n: "nvidia-smi")
    monkeypatch.setattr(gpu.subprocess, "run", boom)
    assert gpu.detect_card() is None


# ── пояснення для людини ─────────────────────────────────────────────────────
@pytest.mark.parametrize("card, reason, must_have", [
    (None, "no_card", "nvidia-smi"),
    (gpu.Card("NVIDIA GeForce GTX 1080", "", "470.05"), "no_capability", "драйвер"),
    (gpu.Card("NVIDIA GeForce GT 730", "3.5", "391.35"), "out_of_range", "GT 730"),
    (gpu.Card("NVIDIA GeForce RTX 3050", "8.6", "460.89"), "driver_old:527.41", "527.41"),
])
def test_every_refusal_names_its_own_cause(card, reason, must_have):
    """🔴 Один текст на три стани й був частиною вади.

    «Карти не видно або вона поза відомими межами» людина з робочою RTX читає
    як «моя карта не підтримується» — і йде шукати іншу машину замість того, щоб
    оновити драйвер.
    """
    text = gpu.explain(card, reason)
    assert must_have in text
    assert gpu.CPU_NOTE in text, "людина має знати, що читання все одно працює"
    if card is not None:
        assert card.name in text
