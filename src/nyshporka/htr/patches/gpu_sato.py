"""GPU-версія `skimage.filters.sato` — найдорожчого кроку сегментації Kraken.

Профіль py-spy живого HTR-прогону: **43% часу сторінки** сидить у
`skimage.filters.sato` (→ `scipy.ndimage.correlate1d`), який `kraken.lib.
segmentation.vectorize_lines` кличе по baseline-хітмапі. Хітмапа щойно вийшла
з мережі, тобто вже була на карті — і одразу стягується на CPU заради згорток,
для яких GPU і створений.

Тут та сама математика на torch. Це не «схожий фільтр»: 1D-ядра беруться з
самого scipy (`_gaussian_kernel1d`), послідовність застосування повторює
`_hessian_matrix_with_gaussian`, тож вихід збігається з точністю до float32.
Перевірка — `nyshporka.htr.patches.gpu_sato_verify`.

Що саме рахується (для 2D формула коротка):
    H = гаусові похідні 2-го порядку (два послідовні проходи 1-го порядку)
    λmax = більше власне значення H (closed-form для симетричної 2×2)
    vals = sigma² · max(λmax, 0);  результат = максимум по всіх sigma

Вмикається підміною `skimage.filters.sato` — тією самою діркою, куди вже
патчиться звуження sigmas у `htr_case_run.install_sato_sigmas`.
"""
from __future__ import annotations

import math

import numpy as np

_KERNEL_CACHE: dict[tuple[float, int, int], "torch.Tensor"] = {}

#: Версії, на яких доведено еквівалентність (max|Δ| 1.2e-07 при діапазоні 0.31,
#: IoU маски 1.000000, текст 18/18 сторінок ідентичний)
TESTED_SKIMAGE = "0.25.2"
TESTED_SCIPY = "1.15.3"


def _kernel1d(sigma: float, order: int, radius: int, device, dtype):
    """1D-ядро рівно те, яке застосував би scipy (вже перевернуте під кореляцію).

    `gaussian_filter1d` робить `correlate1d(input, weights[::-1])`, а torch
    `conv2d` — теж кореляція, тож у нього йде той самий перевернутий масив.
    Знак важливий: ядра непарного порядку антисиметричні.
    """
    import torch
    from scipy.ndimage._filters import _gaussian_kernel1d

    key = (round(sigma, 9), order, radius)
    cached = _KERNEL_CACHE.get(key)
    if cached is None or cached.device != device or cached.dtype != dtype:
        w = _gaussian_kernel1d(sigma, order, radius)[::-1].copy()
        cached = torch.as_tensor(w, dtype=dtype, device=device)
        _KERNEL_CACHE[key] = cached
    return cached


def _pad_axis(x, r: int, dim: int, mode: str, cval: float):
    """Крайові умови точно за scipy.

    ⚠ Kraken кличе `sato(bl_map, black_ridges=False, mode='constant')` —
    саме 'constant', не дефолтний 'reflect' (`kraken/lib/segmentation.py:346`).
    Режими різні по суті, тож підтримуємо обидва:
    - 'constant': доповнення `cval` (у torch — прямий аналог);
    - 'reflect' scipy = (d c b a | a b c d | d c b a), край повторюється.
      У torch такого немає: `F.pad(mode='reflect')` — це scipy 'mirror'
      (край не повторюється), і на ядрі радіусом 71 різниця видна. Тому
      дзеркалимо зрізами вручну, циклом — на випадок радіуса більшого за
      саму сторону (дрібні хітмапи).
    """
    import torch
    import torch.nn.functional as F

    if r <= 0:
        return x
    if mode == "constant":
        pad = (0, 0, r, r) if dim == 2 else (r, r, 0, 0)
        return F.pad(x, pad, mode="constant", value=float(cval))
    while r > 0:
        n = x.shape[dim]
        step = min(r, n)
        if dim == 2:
            left = x[:, :, :step].flip(2)
            right = x[:, :, n - step:].flip(2)
        else:
            left = x[:, :, :, :step].flip(3)
            right = x[:, :, :, n - step:].flip(3)
        x = torch.cat([left, x, right], dim=dim)
        r -= step
    return x


def _sep_filter(x, sigma_scaled: float, radius: int, orders: tuple[int, int],
                mode: str, cval: float):
    """Один прохід `ndi.gaussian_filter` з покомпонентним order (спершу вісь 0)."""
    import torch.nn.functional as F

    for dim, order in ((2, orders[0]), (3, orders[1])):
        k = _kernel1d(sigma_scaled, order, radius, x.device, x.dtype)
        x = _pad_axis(x, radius, dim, mode, cval)
        w = k.view(1, 1, -1, 1) if dim == 2 else k.view(1, 1, 1, -1)
        x = F.conv2d(x, w)
    return x


def sato_gpu(image, sigmas=(1, 3), black_ridges: bool = True, device=None,
             mode: str = "reflect", cval: float = 0):
    """Заміна `skimage.filters.sato` для 2D. Приймає й повертає numpy-масив."""
    import torch

    if mode not in ("reflect", "constant"):
        raise ValueError(f"gpu_sato підтримує 'reflect'/'constant', дано {mode!r}")
    arr = np.asarray(image)
    if arr.ndim != 2:
        raise ValueError(f"gpu_sato — лише 2D, дано {arr.ndim}D")

    dev = torch.device(device or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    x = torch.as_tensor(np.ascontiguousarray(arr, dtype=np.float32),
                        device=dev).view(1, 1, *arr.shape)
    if not black_ridges:          # нормалізація до чорних хребтів, як у skimage
        x = -x

    out = torch.zeros_like(x)
    for sigma in sigmas:
        s = float(sigma)
        # truncate береться від оригінальної sigma, а фільтрується масштабованою:
        # для малих sigma scipy навмисне бере величезний радіус проти аліасингу
        truncate = 8.0 if s > 1 else 100.0
        ss = s / math.sqrt(2.0)
        radius = int(truncate * ss + 0.5)

        gr0 = _sep_filter(x, ss, radius, (1, 0), mode, cval)
        gr1 = _sep_filter(x, ss, radius, (0, 1), mode, cval)
        m00 = _sep_filter(gr0, ss, radius, (1, 0), mode, cval)
        m01 = _sep_filter(gr0, ss, radius, (0, 1), mode, cval)
        m11 = _sep_filter(gr1, ss, radius, (0, 1), mode, cval)

        half = (m00 + m11) / 2
        hsqrtdet = torch.sqrt(m01 * m01 + ((m00 - m11) / 2) ** 2)
        lam_max = half + hsqrtdet            # eigvals[0] — більше з двох
        # для 2D добуток «усіх, крім найменшого» = саме λmax, корінь 1-го степеня
        vals = (s ** 2) * lam_max.clamp(min=0)
        out = torch.maximum(out, vals)

    return out.view(*arr.shape).cpu().numpy()


def install_gpu_sato(sigmas=(1, 3), device=None) -> tuple:
    """Підмінити `skimage.filters.sato` на GPU-версію із зафіксованими sigmas.

    Kraken кличе `filters.sato(bl_map, black_ridges=False)` без sigmas, тож
    підміна дефолту і є весь патч — так само, як у `install_sato_sigmas`.

    Оригінал зберігається у `skf._sato_orig` (як `fast_geom.install` робить із
    трьома своїми функціями): патч глобальний на процес, і без збереженого
    імені жоден інший код у цьому ж процесі вже не дістав би справжній
    `skimage.filters.sato` — тихо отримував би GPU-версію. Повторний виклик
    ідемпотентний і не загортає патч сам у себе.
    """
    import importlib.metadata as md

    from skimage import filters as skf

    # 1D-ядра беруться з приватного `scipy.ndimage._filters._gaussian_kernel1d`,
    # а еквівалентність доведена проти конкретного skimage. Зміна будь-якого з
    # двох може розійтися тихо (інші полігони рядків = інший текст), тому версії
    # звіряються вголос. Звірка: `nyshporka.htr.patches.gpu_sato_verify`
    for pkg, tested in (("scikit-image", TESTED_SKIMAGE), ("scipy", TESTED_SCIPY)):
        try:
            have = md.version(pkg)
        except Exception:
            continue
        if have != tested:
            print(f"[gpu-sato] ⚠ {pkg} {have}, а патч звірений на {tested}. "
                  f"Перезвір: <інтерпретатор рушіїв> -m "
                  f"nyshporka.htr.patches.gpu_sato_verify", flush=True)

    sig = tuple(sigmas)
    if not hasattr(skf, "_sato_orig"):
        skf._sato_orig = skf.sato

    def patched(image, sigmas=sig, black_ridges=True, mode=None, cval=0):
        return sato_gpu(image, sigmas=sigmas, black_ridges=black_ridges,
                        device=device, mode=mode or "reflect", cval=cval)

    skf.sato = patched
    return sig


def uninstall_gpu_sato() -> bool:
    """Повернути справжній `skimage.filters.sato`. True — якщо було що вертати."""
    from skimage import filters as skf

    orig = getattr(skf, "_sato_orig", None)
    if orig is None:
        return False
    skf.sato = orig
    del skf._sato_orig
    return True
