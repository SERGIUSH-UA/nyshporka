"""Клітинки друкованого бланка за його лініями — для читання поклітинно.

Радянські акти цивільного стану 1940-х — друкований бланк-таблиця, заповнений
від руки. Сегментація kraken (`blla`), натренована на книгах, на такій сторінці
пропускає більшість рукописних значень, рве слова навпіл і обрізає великі літери.
Зате лінії бланка видно без жодної моделі: їх знаходить морфологія, а клітинка —
це прямокутник між сусідніми лініями. Кожну клітинку читає основна модель як ОДИН
рядок (`cells_read.py`).

🔴 Модуль чистий: лише numpy і PIL, без scipy й без імпортів `nyshporka`. Він
їде під інтерпретатором середовища рушіїв (як `pysar_lines_infer.py`), а в тестах
пакета scipy немає. Тому «відкриття» (morphological opening) по горизонталі й
вертикалі зроблено прямо: піксель лишається, якщо лежить у відрізку чорнила
завдовжки ≥ L. Для лінійного структурного елемента це те саме, що
`scipy.ndimage.binary_opening`, і так само детерміновано.

Параметри підібрано на 15 актах із перевіреними оком прізвищами, іменами й
по батькові (прототип; заміряно на 93 словах): робота на зменшенні до 1600 px
завширшки, локальний поріг «темніше за околицю на 11», горизонталь — відрізок
від 5% ширини, вертикаль — 3.5% висоти й 60% висоти смуги, клітинки вищі за 12%
сторінки чи вужчі за 3% відкидаються, кроп бере запас угору 45% і вниз 15% висоти
рядка — рукопис налазить на лінію над собою.

⚠ Нахил сторінки не виправляється: горизонталь, що ухилилась більше ніж на
піксель на 5% ширини (≈ 0.7°), розсипається, і сторінка вийде без клітинок.
Це чесна відмова, а не сміття: «сітки не знайдено» рахується окремо.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

Box = tuple[int, int, int, int]

#: Ширина робочого зменшення.
WORK_WIDTH = 1600
#: Околиця локального порогу (піксель) і запас «темніше за околицю».
LOCAL_WINDOW = 51
LOCAL_DELTA = 11
#: Горизонтальна лінія: довжина відрізка й мінімальне заповнення рядка — частки ширини.
H_RUN = 0.05
H_FILL = 0.05
#: Вертикальна лінія: довжина відрізка — частка висоти, заповнення — частка висоти смуги.
V_RUN = 0.035
V_FILL = 0.60
#: Рядок таблиці нижчий за стільки робочих пікселів не береться; вужча клітинка теж.
MIN_ROW_PX = 18
MIN_CELL_PX = 25
#: Клітинки вищі за частку висоти сторінки чи вужчі за частку ширини — не поля, а тло.
MAX_CELL_H = 0.12
MIN_CELL_W = 0.03
#: Запас кропа: угору й униз — частка висоти клітинки, вбік — пікселі.
PAD_UP = 0.45
PAD_DOWN = 0.15
PAD_SIDE = 4
#: Сторінка без хоча б цього числа горизонталей чи клітинок — не таблиця. Книжкова
#: сторінка з випадковою рискою не мусить дати «сітку».
MIN_H_LINES = 3
MIN_CELLS = 4


@dataclass(frozen=True)
class Grid:
    """Що знайдено на сторінці. `crops` порожній, коли сітки немає."""

    cells: list[Box] = field(default_factory=list)
    crops: list[Box] = field(default_factory=list)
    h_lines: int = 0

    @property
    def found(self) -> bool:
        return bool(self.crops)


def _local_mean(a: np.ndarray, size: int) -> np.ndarray:
    """Середнє у вікні size×size (краї — продовженням крайового значення)."""
    r = size // 2
    p = np.pad(a, ((r + 1, r), (r + 1, r)), mode="edge").astype(np.float64)
    s = p.cumsum(0).cumsum(1)
    h, w = a.shape
    tot = (s[size:size + h, size:size + w] - s[0:h, size:size + w]
           - s[size:size + h, 0:w] + s[0:h, 0:w])
    return tot / float(size * size)


def _open_runs(ink: np.ndarray, length: int, axis: int) -> np.ndarray:
    """Піксель чорнила, що лежить у суцільному відрізку завдовжки ≥ `length` вздовж `axis`."""
    a = np.moveaxis(ink.astype(np.int32), axis, 1)
    n = a.shape[1]
    if length <= 1:
        return ink.copy()
    if n < length:
        return np.zeros_like(ink)
    s = np.concatenate([np.zeros((a.shape[0], 1), np.int32), a.cumsum(1)], axis=1)
    starts = (s[:, length:] - s[:, :-length]) == length          # (rows, n-length+1)
    e = np.concatenate([np.zeros((a.shape[0], 1), np.int32),
                        starts.astype(np.int32).cumsum(1)], axis=1)
    x = np.arange(n)
    hi = np.minimum(x, n - length) + 1
    lo = np.maximum(x - length + 1, 0)
    covered = (e[:, hi] - e[:, lo]) > 0
    out = covered & (a > 0)
    return np.moveaxis(out, 1, axis)


def _ink(gray: np.ndarray) -> np.ndarray:
    return gray < _local_mean(gray, LOCAL_WINDOW) - LOCAL_DELTA


def _positions(mask: np.ndarray, axis: int, min_fill: float) -> list[int]:
    """Середини смуг, де проекція маски перевищує `min_fill` (суміжні зливаються)."""
    prof = mask.sum(axis=axis)
    idx = np.where(prof > min_fill)[0]
    out: list[int] = []
    start = prev = None
    for i in idx:
        i = int(i)
        if start is None or i - prev > 3:
            if start is not None:
                out.append((start + prev) // 2)
            start = i
        prev = i
    if start is not None:
        out.append((start + prev) // 2)
    return out


def raw_cells(img: Image.Image) -> tuple[list[Box], int]:
    """Усі клітинки між лініями в координатах кадру + число знайдених горизонталей."""
    gray = img.convert("L")
    w0, h0 = gray.size
    if w0 < 8 or h0 < 8:
        return [], 0
    s = WORK_WIDTH / w0
    sw, sh = WORK_WIDTH, max(8, int(h0 * s))
    small = np.asarray(gray.resize((sw, sh), Image.Resampling.BILINEAR), dtype=np.float32)
    ink = _ink(small)
    hm = _open_runs(ink, max(2, int(sw * H_RUN)), axis=1)
    ys = _positions(hm, 1, sw * H_FILL)
    if len(ys) < 2:
        return [], len(ys)
    vm = _open_runs(ink, max(2, int(sh * V_RUN)), axis=0)
    out: list[Box] = []
    for y0, y1 in zip(ys, ys[1:], strict=False):
        if y1 - y0 < MIN_ROW_PX:
            continue
        band = vm[y0 + 3:y1 - 3]
        xs = sorted({0, *_positions(band, 0, (y1 - y0 - 6) * V_FILL), sw})
        for x0, x1 in zip(xs, xs[1:], strict=False):
            if x1 - x0 < MIN_CELL_PX:
                continue
            out.append((round(x0 / s), round(y0 / s), round(x1 / s), round(y1 / s)))
    return out, len(ys)


def crop_boxes(cells: list[Box], size: tuple[int, int]) -> list[Box]:
    """Клітинки → рамки кропів: відкинути завеликі/завузькі, додати запас угору."""
    width, height = size
    keep: list[Box] = []
    for x0, y0, x1, y1 in cells:
        h = y1 - y0
        if h > height * MAX_CELL_H or (x1 - x0) < width * MIN_CELL_W:
            continue
        side = min(PAD_SIDE, max(0, (x1 - x0) // 8))
        box = (max(0, x0 + side), max(0, int(y0 - h * PAD_UP)),
               min(width, x1 - side), min(height, int(y1 + h * PAD_DOWN)))
        if box[2] > box[0] and box[3] > box[1]:
            keep.append(box)
    return keep


def find_grid(img: Image.Image) -> Grid:
    """Сітка бланка на сторінці. Таблиці немає — `Grid.found` хибне, рамок нема."""
    cells, n_lines = raw_cells(img)
    if n_lines < MIN_H_LINES:
        return Grid(h_lines=n_lines)
    crops = crop_boxes(cells, img.size)
    if len(crops) < MIN_CELLS:
        return Grid(cells=cells, h_lines=n_lines)
    return Grid(cells=cells, crops=crops, h_lines=n_lines)
