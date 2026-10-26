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

Бланк буває книжковим: галицька метрика, сповідний розпис — друковані графи на
розвороті двох сторінок, межі записів друковані або рукописні, у графі кілька
рядків руки. Тому:
- розворот ділиться по корінцю: горизонталі бланка на корінці обриваються, а в
  бланка на всю ширину кадру — ні;
- кожна сторінка вирівнюється: кут — за довгими горизонталями (запасний — за
  вертикалями), вибір кута — той, за якого проєкція ліній найгостріша; без цього
  нахил понад ≈ 0.7° розсипає лінії, і сітки немає;
- висока клітинка (графа з кількома рядками руки) поклітинно НЕ читається:
  замір на галицькій метриці (31 сторінка, 429 звірених слів) — рядки, вирізані
  з графи проєкцією чорнила, дали 38 % слів проти 81 % звичайної сегментації
  kraken тієї ж сторінки, а разом лише +1.4 пункту. Сегментація навчена саме на
  книжкових рядках; клітинки виграють там, де в клітинці одне значення (акт
  РАЦС: 47 → 67 %). Графу книжкового бланка дає адреса (`cells`), а текст —
  звичайне читання.

Кожен кроп має адресу `(сторінка розвороту, рядок таблиці, колонка)`:
вона йде в `lines.json` голосу, щоб пізніше дати клітинці назву поля шаблону.
Рамки в `crops` — у координатах кадру (прямокутник навколо повернутого кропа);
самі зображення для читання бере `Grid.images` з вирівняної сторінки.

«Сітки не знайдено» лишається чесною відмовою й рахується окремо.
"""
from __future__ import annotations

import math
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
#: Нахил: пошук кута в ±SKEW_MAX з кроком SKEW_STEP; менший за SKEW_MIN не повертаємо.
SKEW_MAX = 4.0
SKEW_STEP = 0.1
SKEW_MIN = 0.15
#: Вертикальний відрізок для оцінки кута — коротший, ніж для сітки: на нахиленій
#: сторінці довгий відрізок рветься.
SKEW_V_RUN = 0.02
#: Розворот: кадр ширший за висоту в стільки разів — кандидат; корінець шукається в
#: середній смузі ширини, і горизонталі там мусять майже зникати.
SPREAD_ASPECT = 1.15
SPREAD_BAND = (0.35, 0.65)
SPREAD_GAP = 0.25
#: Лінія бланка тонка: смуга «чорнила», товща за стільки робочих пікселів поперек,
#: — це тло сканера за краєм аркуша чи тінь корінця, а не лінія.
MAX_LINE_PX = 12
#: Тло, яким заповнюються кути після повороту.
BG = 235


#: Адреса кропа: (сторінка розвороту, рядок таблиці, колонка в рядку).
Addr = tuple[int, int, int]


@dataclass(frozen=True)
class Part:
    """Сторінка кадру: межі по x у кадрі й кут, на який її вирівняно (градуси)."""

    x0: int
    x1: int
    angle: float = 0.0


@dataclass(frozen=True)
class Grid:
    """Що знайдено на кадрі. `crops` порожній, коли сітки немає."""

    #: Сирі клітинки між лініями — у координатах кадру.
    cells: list[Box] = field(default_factory=list)
    #: Рамки кропів у координатах кадру; `addr` і `src` — паралельні списки.
    crops: list[Box] = field(default_factory=list)
    h_lines: int = 0
    addr: list[Addr] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    #: (номер сторінки в `parts`, рамка у вирівняній сторінці) — звідки різати кроп.
    src: list[tuple[int, Box]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.crops)

    def images(self, img: Image.Image) -> list[Image.Image]:
        """Кропи для читання — з вирівняних сторінок, у порядку `crops`."""
        pages = [_level(img.crop((p.x0, 0, p.x1, img.height)), p.angle) for p in self.parts]
        return [pages[i].crop(b) for i, b in self.src]


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


def _thin(mask: np.ndarray, axis: int) -> np.ndarray:
    """Лише тонкі лінії маски: прибрати те, що товще за MAX_LINE_PX поперек лінії
    (axis — напрям ЛІНІЇ: 1 — горизонталі, 0 — вертикалі)."""
    return mask & ~_open_runs(mask, MAX_LINE_PX + 1, axis=1 - axis)


def _hlines(ink: np.ndarray) -> np.ndarray:
    return _thin(_open_runs(ink, max(2, int(ink.shape[1] * H_RUN)), axis=1), 1)


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


def _work(img: Image.Image) -> tuple[np.ndarray, float]:
    """Сіре зменшення до робочої ширини і масштаб (робочі / кадрові пікселі)."""
    gray = img.convert("L")
    w0, h0 = gray.size
    s = WORK_WIDTH / w0
    small = np.asarray(gray.resize((WORK_WIDTH, max(8, int(h0 * s))),
                                   Image.Resampling.BILINEAR), dtype=np.float32)
    return small, s


def raw_cells(img: Image.Image) -> tuple[list[Box], int]:
    """Усі клітинки між лініями в координатах кадру + число знайдених горизонталей."""
    w0, h0 = img.size
    if w0 < 8 or h0 < 8:
        return [], 0
    small, s = _work(img)
    sh, sw = small.shape
    ink = _ink(small)
    hm = _hlines(ink)
    ys = _positions(hm, 1, sw * H_FILL)
    if len(ys) < 2:
        return [], len(ys)
    vm = _thin(_open_runs(ink, max(2, int(sh * V_RUN)), axis=0), 0)
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


def _crop_one(cell: Box, size: tuple[int, int]) -> Box | None:
    """Одна невисока клітинка → рамка кропа із запасом угору (як `crop_boxes`)."""
    got = crop_boxes([cell], size)
    return got[0] if got else None


def _skew(mask: np.ndarray, axis: int) -> tuple[float, float]:
    """Кут (градуси), за якого лінії маски стають строго вертикальні (axis=0) чи
    горизонтальні (1), і гострота проєкції за цього кута.

    Перебір кутів зсувом координат пікселів маски: за правильного кута пікселі
    однієї лінії падають в одну колонку (рядок) проєкції, і сума квадратів
    гістограми найбільша.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return 0.0, 0.0
    ys = ys.astype(np.float64)
    xs = xs.astype(np.float64)
    off = int(max(mask.shape) * 1.2)
    best_sc, best_a = -1.0, 0.0
    for a in np.arange(-SKEW_MAX, SKEW_MAX + 1e-9, SKEW_STEP):
        t = math.tan(math.radians(float(a)))
        c = (xs - t * ys) if axis == 0 else (ys + t * xs)
        h = np.bincount(np.clip(np.round(c).astype(np.int64) + off, 0, 3 * off))
        sc = float((h.astype(np.float64) ** 2).sum())
        if sc > best_sc:
            best_sc, best_a = sc, float(a)
    return round(best_a, 2), best_sc


def page_angle(img: Image.Image) -> float:
    """Кут вирівнювання сторінки: за горизонталями бланка, без них — за вертикалями."""
    if img.width < 8 or img.height < 8:
        return 0.0
    small, _s = _work(img)
    sh, sw = small.shape
    ink = _ink(small)
    hm = _hlines(ink)
    if hm.sum() >= sw:                       # хоч одна горизонталь на всю ширину
        a, _ = _skew(hm, 1)
    else:
        a, _ = _skew(_thin(_open_runs(ink, max(2, int(sh * SKEW_V_RUN)), axis=0), 0), 0)
    return a if abs(a) >= SKEW_MIN else 0.0


def _level(img: Image.Image, angle: float) -> Image.Image:
    """Сторінка, повернута так, що лінії бланка стали прямі (тло — сірим)."""
    if not angle:
        return img
    fill: int | tuple[int, int, int] = BG if img.mode == "L" else (BG, BG, BG)
    return img.rotate(-angle, resample=Image.Resampling.BILINEAR, fillcolor=fill)


def _unlevel(box: Box, angle: float, size: tuple[int, int]) -> Box:
    """Рамка у вирівняній сторінці → прямокутник навколо неї у сторінці до повороту."""
    if not angle:
        return box
    w, h = size
    cx, cy = w / 2, h / 2
    t = math.radians(angle)
    c, sn = math.cos(t), math.sin(t)
    xs, ys = [], []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])):
        dx, dy = x - cx, y - cy
        xs.append(cx + dx * c + dy * sn)
        ys.append(cy - dx * sn + dy * c)
    return (max(0, int(min(xs))), max(0, int(min(ys))),
            min(w, math.ceil(max(xs))), min(h, math.ceil(max(ys))))


def split_spread(img: Image.Image) -> list[tuple[int, int]]:
    """Межі сторінок кадру по x. Розворот ділиться по корінцю, решта — один шматок.

    Корінець — колонка середньої смуги, де горизонталі бланка майже зникають: на
    розвороті кожна сторінка має свої лінії, що обриваються на корінці, а бланк на
    всю ширину кадру (альбомний акт) перетинає середину суцільно.
    """
    w, h = img.size
    if w < 8 or h < 8 or w / h < SPREAD_ASPECT:
        return [(0, w)]
    small, s = _work(img)
    sh, sw = small.shape
    hm = _hlines(_ink(small))
    cover = np.convolve(hm.sum(0).astype(np.float64), np.ones(9) / 9, mode="same")
    lo, hi = int(sw * SPREAD_BAND[0]), int(sw * SPREAD_BAND[1])
    ref = float(np.median(cover[int(sw * 0.1):int(sw * 0.9)]))
    if ref <= 0:
        return [(0, w)]
    # Корінець — середина найдовшого проміжку без горизонталей у середній смузі:
    # перша «порожня» колонка лягла б упритул до краю лівої таблиці.
    gap = cover[lo:hi] <= ref * SPREAD_GAP
    best: tuple[int, int] = (0, -1)
    x = 0
    while x < len(gap):
        if gap[x]:
            a = x
            while x < len(gap) and gap[x]:
                x += 1
            if x - a > best[1] - best[0]:
                best = (a, x)
        x += 1
    if best[1] < 0:
        return [(0, w)]
    X = round((lo + (best[0] + best[1]) / 2) / s)
    return [(0, X), (X, w)]


def find_grid(img: Image.Image) -> Grid:
    """Сітка бланка на кадрі. Таблиці немає — `Grid.found` хибне, рамок нема."""
    parts: list[Part] = []
    cells_all: list[Box] = []
    crops: list[Box] = []
    addr: list[Addr] = []
    src: list[tuple[int, Box]] = []
    n_lines = 0
    for x0, x1 in split_spread(img):
        page = img.crop((x0, 0, x1, img.height)) if (x0, x1) != (0, img.width) else img
        angle = page_angle(page)
        level = _level(page, angle)
        cells, n = raw_cells(level)
        pi = len(parts)
        parts.append(Part(x0, x1, angle))
        n_lines += n
        if n < MIN_H_LINES:
            continue
        rows = sorted({(c[1], c[3]) for c in cells})
        row_of = {r: i for i, r in enumerate(rows)}
        col_in_row: dict[tuple[int, int], int] = {}
        for c in sorted(cells, key=lambda b: (b[1], b[0])):
            r = (c[1], c[3])
            col = col_in_row.get(r, 0)
            col_in_row[r] = col + 1
            cells_all.append(_shift(_unlevel(c, angle, level.size), x0))
            if c[3] - c[1] > level.height * MAX_CELL_H:
                continue                     # графа книжкового бланка — див. угорі
            b = _crop_one(c, level.size)
            if b is None:
                continue
            crops.append(_shift(_unlevel(b, angle, level.size), x0))
            addr.append((pi, row_of[r], col))
            src.append((pi, b))
    if n_lines < MIN_H_LINES or len(crops) < MIN_CELLS:
        return Grid(cells=cells_all, h_lines=n_lines, parts=parts)
    return Grid(cells=cells_all, crops=crops, h_lines=n_lines, addr=addr, parts=parts, src=src)


def _shift(box: Box, dx: int) -> Box:
    return (box[0] + dx, box[1], box[2] + dx, box[3])
