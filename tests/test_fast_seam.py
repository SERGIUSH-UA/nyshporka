"""Шов пакетом (`fast_seam.carve`) проти оригінального циклу kraken, без kraken.

Звірка на справжніх сторінках — `fast_seam_verify.py` (середовище рушіїв). Тут
те, чого живі сторінки майже не дають: нічиї в трійці (цілі числа), `inf`
посеред латки, NaN, латки висотою 2, шириною 0 і 1, пакети з латок різної
висоти й ширини. Відповідь — той самий шов або той самий тип винятку.
"""
from __future__ import annotations

import numpy as np
import pytest

from nyshporka.htr.patches import fast_seam


def _orig(rotated_patch: np.ndarray, x_off0: int) -> np.ndarray:
    """Цикл і зворотний прохід `kraken.lib.segmentation._calc_seam` 7.0.2, дослівно."""
    r, c = rotated_patch.shape
    A = np.lib.stride_tricks.as_strided(rotated_patch,
                                        (c, r - 2, 3),
                                        (rotated_patch.strides[1],
                                         rotated_patch.strides[0],
                                         rotated_patch.strides[0]))
    B = rotated_patch[1:-1, 1:].swapaxes(0, 1)
    backtrack = np.zeros_like(B, dtype='int')
    T = np.empty((B.shape[1]), 'f')
    R = np.arange(-1, len(T) - 1)
    for i in np.arange(c - 1):
        A[i].min(1, T)
        backtrack[i] = A[i].argmin(1) + R
        B[i] += T
    seam = []
    j = np.argmin(rotated_patch[1:-1, -1])
    for i in range(c - 2, -2, -1):
        seam.append((i + x_off0 + 1, j))
        j = backtrack[i, j]
    return np.array(seam)[::-1]


def _seam(patch: np.ndarray, x_off0: int) -> fast_seam._Seam:
    s = fast_seam._Seam()
    s.rotated = np.pad(patch, ((1, 1), (0, 0)), mode='constant', constant_values=np.inf)
    s.x_off0 = x_off0
    return s


def _patches(rng: np.random.Generator) -> list[np.ndarray]:
    out = []
    for _ in range(60):
        h, w = int(rng.integers(0, 40)), int(rng.integers(0, 50))
        kind = rng.integers(0, 3)
        if kind == 0:                    # нічиї: мало різних значень
            p = rng.integers(0, 3, (h, w)).astype(float)
        elif kind == 1:
            p = rng.random((h, w)) * 100
        else:                            # маска kraken посеред латки
            p = rng.random((h, w))
            p[rng.random((h, w)) < 0.3] = fast_seam.MASK_VAL
        if h and w and rng.random() < 0.15:
            p[rng.random((h, w)) < 0.2] = np.inf
        out.append(p)
    return out


@pytest.mark.parametrize("seed", range(5))
def test_paket_daie_toi_samyi_shov(seed: int) -> None:
    rng = np.random.default_rng(seed)
    patches = _patches(rng)
    want = []
    for k, p in enumerate(patches):
        try:
            want.append(_orig(np.pad(p, ((1, 1), (0, 0)), mode='constant',
                                     constant_values=np.inf), k))
        except Exception as e:
            want.append(type(e))
    seams = [_seam(p, k) for k, p in enumerate(patches)]
    fast_seam.carve(seams)
    for k, (w, s) in enumerate(zip(want, seams, strict=True)):
        if isinstance(w, type):
            assert s.error is not None and type(s.error) is w, k
        else:
            assert s.error is None, (k, s.error)
            assert s.path.dtype == w.dtype and np.array_equal(s.path, w), k


def test_nan_ide_oryhinalnym_tsyklom() -> None:
    p = np.arange(30, dtype=float).reshape(5, 6) % 4
    p[2, 3] = np.nan
    want = _orig(np.pad(p, ((1, 1), (0, 0)), mode='constant', constant_values=np.inf), 3)
    s = _seam(p, 3)
    fast_seam.carve([s, _seam(np.ones((4, 6)), 0)])
    assert np.array_equal(s.path, want)


def test_malyi_paket_ne_zminiuie_vidpovid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Межі пакета (стеля елементів, крок ширини) на відповідь не впливають."""
    rng = np.random.default_rng(7)
    patches = [p for p in _patches(rng) if p.size]
    big = [_seam(p.copy(), 0) for p in patches]
    fast_seam.carve(big)
    monkeypatch.setattr(fast_seam, "CHUNK_ELEMENTS", 50)
    small = [_seam(p.copy(), 0) for p in patches]
    fast_seam.carve(small)
    for a, b in zip(big, small, strict=True):
        assert (a.error is None) == (b.error is None)
        if a.error is None:
            assert np.array_equal(a.path, b.path)
