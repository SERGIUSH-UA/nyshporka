"""Звірка `gpu_sato` зі `skimage.filters.sato` — числова і за швидкістю.

Еквівалентність тут не самоціль: полігони рядків Kraken будуються по виходу
цього фільтра, тож будь-який зсув означає інший набір рядків і інший текст.
Тому перевіряємо не «схожість картинок», а максимальну абсолютну похибку
відносно динамічного діапазону і збіг ненульової маски.

Запуск ПІД .venv_kraken:
    .venv_kraken/Scripts/python.exe scripts/gpu_sato_verify.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gpu_sato import sato_gpu  # noqa: E402

SIGMAS = (1, 3)


def synthetic(h: int = 900, w: int = 1400, seed: int = 7) -> np.ndarray:
    """Штучна baseline-хітмапа: похилі й вигнуті смуги + шум.

    Саме такий вигляд має вихід сегментера — тонкі хребти на слабкому фоні,
    подекуди зігнуті (рукописний рядок ніколи не прямий).
    """
    rng = np.random.default_rng(seed)
    img = rng.normal(0.02, 0.01, (h, w)).astype(np.float32)
    xs = np.arange(w)
    for i, y0 in enumerate(range(40, h - 40, 55)):
        curve = y0 + 6 * np.sin(xs / 180.0 + i) + xs * (0.01 * (i % 3 - 1))
        for dy in (-1, 0, 1):
            yy = np.clip((curve + dy).astype(int), 0, h - 1)
            img[yy, xs] += 0.8 if dy == 0 else 0.35
    return np.clip(img, 0, 1)


def compare(name: str, img: np.ndarray, device: str = "cuda:0",
            mode: str = "constant") -> bool:
    """mode за замовчуванням 'constant' — саме так кличе Kraken
    (`kraken/lib/segmentation.py:346`), а не дефолтним 'reflect'."""
    from skimage.filters import sato as sato_cpu

    t0 = time.perf_counter()
    ref = sato_cpu(img, sigmas=SIGMAS, black_ridges=False, mode=mode)
    t_cpu = time.perf_counter() - t0

    sato_gpu(img[:64, :64], sigmas=SIGMAS, black_ridges=False, device=device,
             mode=mode)  # прогрів
    t0 = time.perf_counter()
    got = sato_gpu(img, sigmas=SIGMAS, black_ridges=False, device=device, mode=mode)
    t_gpu = time.perf_counter() - t0

    rng = float(ref.max() - ref.min()) or 1.0
    amax = float(np.abs(ref - got).max())
    rel = amax / rng
    # маска «фільтр щось знайшов» — саме її потім порогують і векторизують
    thr = ref.max() * 0.05
    mask_ref, mask_got = ref > thr, got > thr
    iou = float((mask_ref & mask_got).sum()) / max(1, int((mask_ref | mask_got).sum()))
    corr = float(np.corrcoef(ref.ravel(), got.ravel())[0, 1])

    ok = rel < 1e-4 and iou > 0.999
    print(f"\n{name}: {img.shape}")
    print(f"  CPU {t_cpu*1000:8.1f} мс   GPU {t_gpu*1000:8.1f} мс   "
          f"прискорення ×{t_cpu/max(t_gpu,1e-9):.1f}")
    print(f"  max|Δ| {amax:.3e} (діапазон {rng:.3e}) → відносна {rel:.2e}")
    print(f"  IoU маски@5% {iou:.6f}   кореляція {corr:.8f}   {'✓ ОК' if ok else '✗ РОЗБІЖНІСТЬ'}")
    return ok


def main() -> int:
    import torch
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"пристрій: {dev}")

    all_ok = compare("синтетична, mode=constant (як у Kraken)", synthetic(), dev)
    all_ok &= compare("дрібна (край > радіуса ядра)", synthetic(80, 120), dev)
    all_ok &= compare("синтетична, mode=reflect", synthetic(), dev, mode="reflect")

    # реальна хітмапа сегментера, якщо є збережена
    for p in sorted(Path("data/cache").rglob("bl_map*.npy"))[:1]:
        all_ok &= compare(f"реальна {p.name}", np.load(p), dev)

    print("\n" + ("✓ ЕКВІВАЛЕНТНО" if all_ok else "✗ Є РОЗБІЖНОСТІ — не вмикати"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
