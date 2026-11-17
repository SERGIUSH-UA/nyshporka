"""Sato через torch ставиться й без карти — на процесор.

Доти патч `gpu_sato` вмикався лише на `cuda`, і машина без NVIDIA (Mac, ноутбук,
CPU-образ Docker) рахувала найдорожчий крок сторінки повільним шляхом skimage.
Та сама математика на torch швидша й на процесорі: замір 17.11.2026 (Apple M5
Pro, кадр 1800×2800, sigmas (1,3), mode=constant) — skimage 1.79 с, torch на
одному потоці 1.06 с, на чотирьох 0.53 с, max|Δ| 1.5e-07. Вихід звіряє
`gpu_sato_verify` на тому пристрої, який йому назвати.

Перевірка тримається за структуру гілки: запустити справжній прогін тут нема на
чому — раннер живе в чужому інтерпретаторі.
"""
from __future__ import annotations

import re
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"
VERIFY = (Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "patches"
          / "gpu_sato_verify.py")


def _sato_branch() -> str:
    src = RUNNER.read_text(encoding="utf-8")
    start = src.index("install_sato_sigmas(args.sato_sigmas)")
    end = src.index("install_gpu_sato(", start)
    return src[start:end]


def test_sato_patch_is_not_gated_on_cuda() -> None:
    """🔴 Умова встановлення — лише прапорець, не тип пристрою."""
    branch = _sato_branch()
    cond = re.search(r"if args\.gpu_sato[^:]*:", branch)
    assert cond, "гілка встановлення torch-sato зникла"
    assert "cuda" not in cond.group(0), (
        "sato через torch знову прив'язаний до cuda — без карти піде повільний skimage")


def test_sato_goes_to_the_run_device() -> None:
    """Патч отримує пристрій прогону, а не зашитий `cuda:0`."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "install_gpu_sato(sigmas or (1, 3, 5, 7, 9), device=device)" in src


def test_verify_takes_the_device_to_check() -> None:
    """Рівність, доведена на CUDA, не доводить її на процесорі чи MPS: звірка
    мусить приймати пристрій, на якому патч піде в прогоні."""
    src = VERIFY.read_text(encoding="utf-8")
    assert "def main(argv: list[str] | None = None)" in src
    assert '"mps"' in src and '"cpu"' in src
