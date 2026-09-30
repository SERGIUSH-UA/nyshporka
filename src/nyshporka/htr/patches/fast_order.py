"""Порядок читання Kraken без кубічного циклу Python — `_reading_order` на numpy.

Профіль 30.09.2026, ДАКрО ф.60 спр.32 (щільні таблиці, медіана 463 рядки на
сторінку, до 800 зі знятою стелею сегментації): сторінка на 800 рядків ішла
~370 с, з яких мережа сегментації — 1 с, контури рядків — 22 с, розпізнавання —
12–16 с, а **~340 с — решта сегментації**. На машині в цей час простоювали 75%
ядер і 70% карти: кожен шард молотив однопотоковий Python.

Винен `kraken.lib.segmentation._reading_order`. Для кожної пари рядків, що не
перекриваються по горизонталі, він перебирає ВСІ рядки сторінки в пошуках
розділювача — списковим виразом, тобто без зупинки на першому знайденому:
n² пар × n кандидатів. На 100 рядках це ~700 тис. викликів `_separates` на
сторінку (профіль spr-8676), на 800 — до ~500 млн.

Тут та сама логіка, але перебір кандидатів іде матрицею numpy на кожен рядок.
Нічого не «спрощується»: умови `_separates` перенесено дослівно, зокрема
виключення кандидата, чиї межі ДОРІВНЮЮТЬ межам одного з пари (у kraken це
`w == u` на кортежах зрізів — рівність значень, а не тотожність). Звірка —
`nyshporka.htr.patches.fast_order_verify`: стара й нова версії на випадкових і
реальних наборах рядків, матриця порядку мусить збігтися до біта.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

TESTED_KRAKEN = "7.0.2"

#: Скільки разів швидкий шлях поступився оригіналу через виняток.
FALLBACKS = {"reading_order": 0}


def _bounds(lines: Sequence[tuple[slice, slice]]) -> np.ndarray:
    """(y0, y1, x0, x1) кожного рядка — межі зрізів, як їх порівнює kraken."""
    return np.array([[u[0].start, u[0].stop, u[1].start, u[1].stop] for u in lines],
                    dtype=np.float64).reshape(-1, 4)


def reading_order_fast(lines: Sequence[tuple[slice, slice]],
                       text_direction: str = "lr") -> np.ndarray:
    """Те саме, що `kraken.lib.segmentation._reading_order`, без циклу по кандидатах.

    `order[i, j] = 1` — рядок i йде перед рядком j.
    """
    n = len(lines)
    order = np.zeros((n, n), "B")
    if n == 0:
        return order
    b = _bounds(lines)
    y0, y1, x0, x1 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    # same[w, u]: кандидат w має ті самі межі, що й u (`w == u` у kraken).
    # Діагональ — завжди «той самий»: у kraken це той самий об'єкт, і рівність
    # кортежу спрацьовує на тотожності навіть для NaN.
    same = np.all(b[:, None, :] == b[None, :, :], axis=2)
    np.fill_diagonal(same, True)

    x_overlaps = (x0[:, None] < x1[None, :]) & (x1[:, None] > x0[None, :])
    above = y0[:, None] < y0[None, :]
    order[x_overlaps & above] = 1

    left_of = x1[:, None] < x0[None, :]
    horizontal = ~left_of if text_direction == "rl" else left_of
    # Розділювач потрібен лише там, де без нього стояла б одиниця.
    need = ~x_overlaps & horizontal
    for i in np.nonzero(need.any(axis=1))[0]:
        js = np.nonzero(need[i])[0]
        # `_separates(w, u, v)`, u = рядок i, v = кожен із js:
        #   w не дорівнює ні u, ні v;
        #   w.y1 >= min(u.y0, v.y0) і w.y0 <= max(u.y1, v.y1);
        #   w.x0 < u.x1 і w.x1 > v.x0.
        ws = np.nonzero((x0 < x1[i]) & ~same[:, i])[0]
        if ws.size == 0:
            order[i, js] = 1
            continue
        lo = np.minimum(y0[i], y0[js])[:, None]
        hi = np.maximum(y1[i], y1[js])[:, None]
        separated = ((y1[ws][None, :] >= lo) & (y0[ws][None, :] <= hi)
                     & (x1[ws][None, :] > x0[js][:, None])
                     & ~same[np.ix_(ws, js)].T).any(axis=1)
        order[i, js[~separated]] = 1
    return order


def _with_fallback(fast: Any, orig: Any) -> Any:
    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fast(*args, **kwargs)
        except Exception:
            FALLBACKS["reading_order"] += 1
            return orig(*args, **kwargs)

    call.__name__ = getattr(fast, "__name__", "reading_order")
    return call


def install(verbose: bool = False) -> bool:
    """Підмінити `_reading_order` у модулі kraken.

    `polygonal_reading_order` і `reading_order` резолвлять глобальне ім'я модуля
    на кожен виклик, тож підміни досить.
    """
    from kraken.lib import segmentation as kseg

    if getattr(kseg, "_fast_order_installed", False):
        return True
    if not hasattr(kseg, "_reading_order"):
        raise RuntimeError(
            "fast_order: у kraken.lib.segmentation немає `_reading_order` — версія "
            f"пакета розійшлася з патчем (звірено на {TESTED_KRAKEN})")
    kseg._reading_order_orig = kseg._reading_order
    kseg._reading_order = _with_fallback(reading_order_fast, kseg._reading_order_orig)
    kseg._fast_order_installed = True
    if verbose:
        print("[fast-order] порядок читання kraken — матрицею numpy "
              "(та сама логіка, без кубічного циклу Python)", flush=True)
    return True
