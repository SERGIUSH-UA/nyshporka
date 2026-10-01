"""CLAHE для вицвілих сторінок з інтерполяцією на карті — той самий результат до біта.

`enhance_image` (раннер) піднімає контраст блідої сторінки через
`skimage.exposure.equalize_adapthist`. На блідих справах це майже кожна
сторінка: клірові ф.315 спр.11858 — 406 із 608. Профіль шарда на боксі
(01.10.2026): CLAHE — 15 % часу сторінки, ~1 с на кожну; удома 1.6 с із 2.1 с
`enhance_image` — це `equalize_adapthist`, і найдорожче в ньому — інтерполяція
відображень між сусідніми вікнами: чотири проходи «вибірка з таблиці ×
коефіцієнт → float32 → сума» по всіх пікселях кадру.

Тут — дослівна копія `equalize_adapthist` / `_clahe` зі skimage 0.25.2, у якій
лише цей цикл іде тензорами на карті. Операції поелементні й ті самі (ціле
відображення → float64, множення на float64-коефіцієнт, округлення до
float32, додавання у float32 в тому самому порядку країв), кожна — окремим
ядром, тож злиття множення з додаванням (FMA), яке змінило б округлення, не
трапляється. Гістограми, відсікання, відображення, перцентилі — на процесорі,
як в оригіналі. Звірка — `fast_clahe_verify.py`: результат мусить збігтися до
біта на справжніх сторінках.

Без карти або на іншій версії skimage — оригінальна функція.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

TESTED_SKIMAGE = "0.25.2"
STATE: dict[str, Any] = {"device": None, "calls": 0, "fallbacks": 0}


def equalize_adapthist_fast(image: np.ndarray, kernel_size: Any = None,
                            clip_limit: float = 0.01, nbins: int = 256) -> np.ndarray:
    """`skimage.exposure.equalize_adapthist` для 2-D сірого — те саме значення."""
    from skimage.exposure import equalize_adapthist

    dev = STATE["device"]
    if dev is None or image.ndim != 2:
        return equalize_adapthist(image, kernel_size=kernel_size,
                                  clip_limit=clip_limit, nbins=nbins)
    try:
        out = _equalize(image, kernel_size, clip_limit, nbins, dev)
        STATE["calls"] += 1
        return out
    except Exception:
        STATE["fallbacks"] += 1
        return equalize_adapthist(image, kernel_size=kernel_size,
                                  clip_limit=clip_limit, nbins=nbins)


def _equalize(image, kernel_size, clip_limit, nbins, dev):
    import numbers

    from skimage._shared.utils import _supported_float_type
    from skimage.exposure import rescale_intensity
    from skimage.exposure._adapthist import NR_OF_GRAY
    from skimage.util import img_as_uint

    float_dtype = _supported_float_type(image.dtype)
    image = img_as_uint(image)
    image = np.round(rescale_intensity(image, out_range=(0, NR_OF_GRAY - 1))).astype(
        np.min_scalar_type(NR_OF_GRAY)
    )

    if kernel_size is None:
        kernel_size = tuple([max(s // 8, 1) for s in image.shape])
    elif isinstance(kernel_size, numbers.Number):
        kernel_size = (kernel_size,) * image.ndim
    elif len(kernel_size) != image.ndim:
        raise ValueError(f'Incorrect value of `kernel_size`: {kernel_size}')

    kernel_size = [int(k) for k in kernel_size]

    image = _clahe(image, kernel_size, clip_limit, nbins, dev)
    image = image.astype(float_dtype, copy=False)
    return rescale_intensity(image)


def _clahe(image, kernel_size, clip_limit, nbins, dev):
    import torch
    from skimage.exposure._adapthist import NR_OF_GRAY, clip_histogram, map_histogram

    ndim = image.ndim
    dtype = image.dtype

    pad_start_per_dim = [k // 2 for k in kernel_size]

    pad_end_per_dim = [
        (k - s % k) % k + int(np.ceil(k / 2.0))
        for k, s in zip(kernel_size, image.shape)
    ]

    image = np.pad(
        image,
        [[p_i, p_f] for p_i, p_f in zip(pad_start_per_dim, pad_end_per_dim)],
        mode='reflect',
    )

    bin_size = 1 + NR_OF_GRAY // nbins
    lut = np.arange(NR_OF_GRAY, dtype=np.min_scalar_type(NR_OF_GRAY))
    lut //= bin_size

    image = lut[image]

    ns_hist = [int(s / k) - 1 for s, k in zip(image.shape, kernel_size)]
    hist_blocks_shape = np.array([ns_hist, kernel_size]).T.flatten()
    hist_blocks_axis_order = np.array(
        [np.arange(0, ndim * 2, 2), np.arange(1, ndim * 2, 2)]
    ).flatten()
    hist_slices = [slice(k // 2, k // 2 + n * k) for k, n in zip(kernel_size, ns_hist)]
    hist_blocks = image[tuple(hist_slices)].reshape(hist_blocks_shape)
    hist_blocks = np.transpose(hist_blocks, axes=hist_blocks_axis_order)
    hist_block_assembled_shape = hist_blocks.shape
    hist_blocks = hist_blocks.reshape((math.prod(ns_hist), -1))

    kernel_elements = math.prod(kernel_size)
    if clip_limit > 0.0:
        clim = int(np.clip(clip_limit * kernel_elements, 1, None))
    else:
        clim = kernel_elements

    hist = np.apply_along_axis(np.bincount, -1, hist_blocks, minlength=nbins)
    hist = np.apply_along_axis(clip_histogram, -1, hist, clip_limit=clim)
    hist = map_histogram(hist, 0, NR_OF_GRAY - 1, kernel_elements)
    hist = hist.reshape(hist_block_assembled_shape[:ndim] + (-1,))

    map_array = np.pad(hist, [[1, 1] for _ in range(ndim)] + [[0, 0]], mode='edge')

    ns_proc = [int(s / k) for s, k in zip(image.shape, kernel_size)]
    blocks_shape = np.array([ns_proc, kernel_size]).T.flatten()
    blocks_axis_order = np.array(
        [np.arange(0, ndim * 2, 2), np.arange(1, ndim * 2, 2)]
    ).flatten()
    blocks = image.reshape(blocks_shape)
    blocks = np.transpose(blocks, axes=blocks_axis_order)
    blocks_flattened_shape = blocks.shape
    blocks = np.reshape(blocks, (math.prod(ns_proc), math.prod(blocks.shape[ndim:])))

    coeffs = np.meshgrid(
        *tuple([np.arange(k) / k for k in kernel_size[::-1]]), indexing='ij'
    )
    coeffs = [np.transpose(c).flatten() for c in coeffs]
    inv_coeffs = [1 - c for dim, c in enumerate(coeffs)]

    # ── єдина відмінність від skimage: цикл нижче — тензорами на карті ──────
    idx = torch.from_numpy(np.ascontiguousarray(blocks)).to(dev).long()
    result_t = torch.zeros(blocks.shape, dtype=torch.float32, device=dev)
    for iedge, edge in enumerate(np.ndindex(*([2] * ndim))):
        edge_maps = map_array[tuple([slice(e, e + n) for e, n in zip(edge, ns_proc)])]
        edge_maps = edge_maps.reshape((math.prod(ns_proc), -1))

        # apply map: ціле відображення (int64), як `np.take_along_axis`
        edge_mapped = torch.gather(torch.from_numpy(np.ascontiguousarray(edge_maps)).to(dev),
                                   1, idx)

        edge_coeffs = np.prod(
            [[inv_coeffs, coeffs][e][d] for d, e in enumerate(edge[::-1])], 0
        )
        coeff_t = torch.from_numpy(np.ascontiguousarray(edge_coeffs)).to(dev)
        # int64 × float64 → float64 (numpy-просування), потім float32 і сума
        prod = edge_mapped.to(torch.float64) * coeff_t
        result_t += prod.to(torch.float32)
    result = result_t.cpu().numpy()
    del idx, result_t
    # ── далі — дослівно ──────────────────────────────────────────────────────

    result = result.astype(dtype)

    result = result.reshape(blocks_flattened_shape)
    blocks_axis_rebuild_order = np.array(
        [np.arange(0, ndim), np.arange(ndim, ndim * 2)]
    ).T.flatten()
    result = np.transpose(result, axes=blocks_axis_rebuild_order)
    result = result.reshape(image.shape)

    unpad_slices = tuple(
        [
            slice(p_i, s - p_f)
            for p_i, p_f, s in zip(pad_start_per_dim, pad_end_per_dim, image.shape)
        ]
    )
    result = result[unpad_slices]

    return result


def install(device: str, verbose: bool = False) -> bool:
    """Увімкнути CLAHE на карті для `enhance_image`. False — лишається skimage."""
    import importlib.metadata as md

    try:
        ver = md.version("scikit-image")
    except md.PackageNotFoundError:
        ver = "?"
    if not device.startswith("cuda") or ver != TESTED_SKIMAGE:
        if verbose:
            print(f"[fast-clahe] лишається skimage (пристрій {device}, scikit-image "
                  f"{ver}; звірено на {TESTED_SKIMAGE})", flush=True)
        return False
    STATE["device"] = device
    if verbose:
        print(f"[fast-clahe] CLAHE: інтерполяція на {device}", flush=True)
    return True
