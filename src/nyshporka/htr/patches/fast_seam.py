"""Шов між рядками Kraken пакетом на всю сторінку — `_calc_seam` без циклу на кожен рядок.

Контур рядка kraken будує по шву (seamcarve) над і під базовою лінією. Шов —
динамічне програмування по стовпчиках латки: на кожен стовпчик 3–4 виклики
numpy над кількома сотнями чисел, тобто накладні Python, а не арифметика.
Замір 01.10.2026 (ДАХмО ф.315 спр.8676, 4 сторінки по ~85 рядків, fast_geom і
fast_order увімкнені): цей цикл — 3.8 с із 27 с сегментації, ~150 тис. ітерацій.

Стовпчики залежать один від одного, а шви — ні. Тому шви всієї сторінки
збираються в пакет і проходять ОДИН цикл по стовпчиках, де кожна операція
працює над усіма швами разом. Операції ті самі й над тими самими числами:
`min` у float32-буфер, `argmin`, додавання float32 до float64 — отже шов той
самий до біта. Латки різних розмірів доповнюються `inf`; рядки доповнення не
змінюються (маска), стовпчики доповнення лежать праворуч від шва й на нього не
впливають.

Решта полігонізації — дослівно kraken (`calculate_polygonal_environment`,
`_extract_patch`, дві половини `_calc_seam`), лише розрізана на «до шва» і
«після шва». Звірка — `fast_seam_verify.py`: контури всіх рядків сторінки проти
оригіналу, мусять збігтися до пікселя.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

TESTED_KRAKEN = "7.0.2"
MASK_VAL = 99999

#: Скільки разів швидкий шлях поступився оригіналу через виняток.
FALLBACKS = {"vec_lines": 0}

#: Стеля елементів одного пакета з доповненням (латки float64 + argmin int8
#: ≈ 9 Б на елемент): 8 млн ≈ 72 МБ на шард. Менший пакет програє
#: накладними: 72 пакети на 4 сторінки з'їли майже весь виграш.
CHUNK_ELEMENTS = 8_000_000

#: Крок кошика за висотою й шириною латки (логарифмічний): у пакет ідуть латки,
#: що різняться не більш ніж у стільки разів по кожній осі.
BIN_RATIO = 1.3

#: Лічильник пакетів: справжні елементи латок проти доповнених (для заміру).
CARVE = {"chunks": 0, "real": 0, "padded": 0}

logger = logging.getLogger("kraken")


class _Seam:
    """Латка одного шва між підготовкою і добудовою."""

    __slots__ = ("rotated", "x_off0", "tform", "mask", "c_min", "r_min", "path", "error")

    def __init__(self) -> None:
        self.path: np.ndarray | None = None
        self.error: Exception | None = None


def _seam_prep(baseline, polygon, angle, im_feats, bias=150) -> _Seam:
    """Перша половина `kraken.lib.segmentation._calc_seam` — дослівно, до шва."""
    from kraken.lib import segmentation as kseg
    from scipy.ndimage import binary_erosion, distance_transform_cdt
    from skimage import draw

    c_min, c_max = int(polygon[:, 0].min()), int(polygon[:, 0].max())
    r_min, r_max = int(polygon[:, 1].min()), int(polygon[:, 1].max())
    patch = im_feats[r_min:r_max + 2, c_min:c_max + 2].copy()
    # bias feature matrix by distance from baseline
    mask = np.ones_like(patch)
    for line_seg in zip(baseline[:-1] - (c_min, r_min), baseline[1:] - (c_min, r_min)):
        line_locs = draw.line(line_seg[0][1],
                              line_seg[0][0],
                              line_seg[1][1],
                              line_seg[1][0])
        mask[line_locs] = 0
    dist_bias = distance_transform_cdt(mask)
    # absolute mask
    mask = np.array(kseg.make_polygonal_mask(polygon - (c_min, r_min), patch.shape[::-1])) <= 128
    # dilate mask to compensate for aliasing during rotation
    mask = binary_erosion(mask, border_value=True, iterations=2)
    # combine weights with features
    patch[mask] = MASK_VAL
    patch += (dist_bias * (np.mean(patch[patch != MASK_VAL]) / bias))
    extrema = baseline[(0, -1), :] - (c_min, r_min)
    # scale line image to max 600 pixel width
    scale = min(1.0, 600 / (c_max - c_min))
    tform, rotated_patch = kseg._rotate(patch,
                                        angle,
                                        center=extrema[0],
                                        scale=scale,
                                        cval=MASK_VAL,
                                        use_skimage_warp=True)
    # ensure to cut off padding after rotation
    x_offsets = np.sort(np.around(tform.inverse(extrema)[:, 0]).astype('int'))
    rotated_patch = rotated_patch[:, x_offsets[0]:x_offsets[1] + 1]
    # infinity pad for seamcarve
    rotated_patch = np.pad(rotated_patch, ((1, 1), (0, 0)), mode='constant',
                           constant_values=np.inf)
    s = _Seam()
    s.rotated, s.x_off0, s.tform, s.mask = rotated_patch, x_offsets[0], tform, mask
    s.c_min, s.r_min = c_min, r_min
    return s


def _seam_finish(s: _Seam) -> np.ndarray:
    """Друга половина `_calc_seam` — дослівно, від готового шва."""
    seam = s.path
    seam_mean = seam[:, 1].mean()
    seam_std = seam[:, 1].std()
    seam[:, 1] = np.clip(seam[:, 1], seam_mean - seam_std, seam_mean + seam_std)
    # rotate back
    seam = s.tform(seam).astype('int')
    # filter out seam points in masked area of original patch/in padding
    seam = seam[seam.min(axis=1) >= 0, :]
    mask = s.mask
    m = (seam < mask.shape[::-1]).T
    seam = seam[np.logical_and(m[0], m[1]), :]
    seam = seam[np.invert(mask[seam.T[1], seam.T[0]])]
    seam += (s.c_min, s.r_min)
    return seam


def _carve_chunk(seams: list[_Seam]) -> None:
    """Шви пакета одним циклом по стовпчиках. Заповнює `path` або `error`.

    Відповідність оригіналу (`P` — латка шва після доповнення `inf` згори й
    знизу, `r × c`):

        A[i] = вікна по 3 рядки стовпчика i       (c, r-2, 3)
        B[i] = P[1:-1, i+1]                        стовпчик, що оновлюється
        T    = min(A[i]) у float32;  backtrack[i] = argmin(A[i]) + j - 1
        B[i] += T

    Латки пакета лежать ОДНА ПІД ОДНОЮ в спільному масиві `PT[стовпчик, рядок]`
    (латка k — рядки `off_k … off_k + r_k - 1`), без доповнення за висотою.
    Вікно з трьох рядків, що лежить усередині латки, бачить рівно те, що
    бачило б в оригіналі: верхній і нижній рядки латки — її власне
    доповнення `inf`. Вікна на стику двох латок рахуються вхолосту; те, що
    вони дописують у межові рядки, — це `inf + T = inf`, тож межа лишається
    такою, як в оригіналі, де ці рядки не оновлюються (B = P[1:-1]). NaN, що
    зламав би цю рівність, у пакет не потрапляє (`carve`).
    Стовпчики праворуч від вужчої латки — `inf`, і її шов не читає їх.
    """
    rows = np.array([s.rotated.shape[0] for s in seams])
    cols = np.array([s.rotated.shape[1] for s in seams])
    off = np.concatenate(([0], np.cumsum(rows)[:-1]))
    Rt, C = int(rows.sum()), int(cols.max())
    PT = np.full((C, Rt), np.inf, dtype=seams[0].rotated.dtype)
    for k, s in enumerate(seams):
        PT[:cols[k], off[k]:off[k] + rows[k]] = s.rotated.T
    CARVE["chunks"] += 1
    CARVE["real"] += int((rows * cols).sum())
    CARVE["padded"] += Rt * C
    # Лише argmin трійки (0, 1, 2); зсув `j - 1` оригіналу додається у
    # зворотному проході — значення ті самі, а масив у 8 разів менший.
    W = max(Rt - 2, 0)
    arg = np.zeros((max(C - 1, 0), W), dtype='int8')
    m = np.empty(W, dtype=PT.dtype)
    bl = np.empty(W, dtype=bool)
    lt = np.empty(W, dtype=bool)
    T = np.empty(W, 'f')
    for i in range(C - 1):
        col = PT[i]
        a, b, c3 = col[:-2], col[1:-1], col[2:]
        # `argmin` по трійці = перший мінімум: строге `<` бере наступного лише
        # тоді, коли він МЕНШИЙ — рівні лишаються за першим. Без NaN (див.
        # `carve`) це та сама відповідь, що й `A.argmin(1)` оригіналу.
        np.minimum(a, b, out=m)
        np.less(b, a, out=bl)
        np.less(c3, m, out=lt)
        np.minimum(m, c3, out=m)
        out = arg[i]
        np.copyto(out, bl, casting='unsafe')
        np.copyto(out, 2, where=lt)
        # оригінал: `A[i].min(1, T)` у float32-буфер, далі `B[i] += T`
        np.copyto(T, m, casting='same_kind')
        PT[i + 1, 1:-1] += T

    for k, s in enumerate(seams):
        r, c, o = int(rows[k]), int(cols[k]), int(off[k])
        try:
            bt = arg[:max(c - 1, 0), o:o + r - 2].astype('int') + np.arange(-1, r - 3)
            s.path = _backtrack(PT[c - 1, o + 1:o + r - 1] if c else PT[:0, 0],
                                bt, c, int(s.x_off0))
        except Exception as e:           # той самий виняток, що дав би оригінал
            s.error = e


def _backtrack(last_col: np.ndarray, bt: np.ndarray, c: int, x_off0: int) -> np.ndarray:
    """Зворотний прохід оригіналу, дослівно: індексація numpy з її загортанням
    від'ємних індексів і тими самими IndexError на краях."""
    if c == 0:
        raise IndexError("index -1 is out of bounds for axis 1 with size 0")
    seam = []
    j = np.argmin(last_col)
    for i in range(c - 2, -2, -1):
        seam.append((i + x_off0 + 1, j))
        j = bt[i, j]
    return np.array(seam)[::-1]


def _carve_one(s: _Seam) -> None:
    """Шов оригінальним циклом, дослівно — для латок із NaN."""
    try:
        rotated_patch = s.rotated
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
        s.path = _backtrack(rotated_patch[1:-1, -1] if c else rotated_patch[1:-1, :0],
                            backtrack, c, int(s.x_off0))
    except Exception as e:
        s.error = e


def carve(seams: list[_Seam]) -> None:
    """Усі шви сторінки: пакети однакового dtype і близької ширини.

    Ширина латки — це довжина циклу, тож пакет із вузьких і широких латок
    ганяв би вузькі по стовпчиках доповнення. Латка з NaN іде оригінальним
    циклом: на NaN `argmin` бере перший NaN, а порівняння — ні.
    """
    by_dtype: dict[Any, list[_Seam]] = {}
    for s in seams:
        if s.rotated.size and np.isnan(s.rotated).any():
            _carve_one(s)
        else:
            by_dtype.setdefault(s.rotated.dtype, []).append(s)
    for group in by_dtype.values():
        group.sort(key=lambda s: s.rotated.shape[1])
        chunk: list[_Seam] = []
        rows = 0
        for s in group:
            r, c = s.rotated.shape
            if chunk and ((rows + r) * c > CHUNK_ELEMENTS
                          or c > BIN_RATIO * chunk[0].rotated.shape[1] + 8):
                _carve_chunk(chunk)
                chunk, rows = [], 0
            chunk.append(s)
            rows += r
        if chunk:
            _carve_chunk(chunk)


class _Line:
    """Рядок між підготовкою швів і добудовою полігона."""

    __slots__ = ("end_points", "offset", "roi_polygon", "upper", "bottom")


def _line_prep(baseline, suppl_obj, im_feats, topline) -> _Line:
    """`calculate_polygonal_environment` на один рядок (так її кличе `vec_lines`)
    і `_extract_patch` до швів — дослівно."""
    import shapely.geometry as geom
    from kraken.lib import segmentation as kseg
    from shapely.ops import unary_union

    bounds = np.array(im_feats.shape[::-1], dtype=float) - 1
    end_points = (baseline[0], baseline[-1])
    line = geom.LineString(baseline)
    offset = 8 if topline is not None else 0
    offset_line = line.parallel_offset(offset, side='left' if topline else 'right')
    line = np.array(line.coords, dtype=float)
    offset_line = np.array(offset_line.coords, dtype=float)

    # calculate magnitude-weighted average direction vector
    lengths = np.linalg.norm(np.diff(line.T), axis=0)
    p_dir = np.mean(np.diff(line.T) * lengths / lengths.sum(), axis=1)
    p_dir = (p_dir.T / np.sqrt(np.sum(p_dir**2, axis=-1)))
    env_up, env_bottom = kseg._calc_roi(line, bounds, [], suppl_obj, p_dir)

    # ── _extract_patch до швів ──
    baseline_i = line.astype('int')
    offset_baseline = offset_line.astype('int')
    dir_vec = p_dir
    upper_polygon = np.concatenate((baseline_i, env_up[::-1]))
    bottom_polygon = np.concatenate((baseline_i, env_bottom[::-1]))
    upper_offset_polygon = np.concatenate((offset_baseline, env_up[::-1]))
    bottom_offset_polygon = np.concatenate((offset_baseline, env_bottom[::-1]))

    angle = np.arctan2(dir_vec[1], dir_vec[0])
    roi_polygon = unary_union([geom.Polygon(upper_polygon), geom.Polygon(bottom_polygon)])

    ln = _Line()
    if topline:
        ln.upper = _seam_prep(baseline_i, upper_polygon, angle, im_feats)
        ln.bottom = _seam_prep(offset_baseline, bottom_offset_polygon, angle, im_feats)
    else:
        ln.upper = _seam_prep(offset_baseline, upper_offset_polygon, angle, im_feats)
        ln.bottom = _seam_prep(baseline_i, bottom_polygon, angle, im_feats)
    ln.end_points, ln.offset, ln.roi_polygon = end_points, offset, roi_polygon
    return ln


def _line_finish(ln: _Line) -> np.ndarray:
    """Решта `_extract_patch` — дослівно."""
    import shapely.geometry as geom
    from shapely.validation import explain_validity

    for s in (ln.upper, ln.bottom):
        if s.error is not None:
            raise s.error
    upper_seam = _seam_finish(ln.upper)
    bottom_seam = _seam_finish(ln.bottom)
    offset, end_points = ln.offset, ln.end_points

    upper_seam = geom.LineString(upper_seam).simplify(5)
    bottom_seam = geom.LineString(bottom_seam).simplify(5)

    # ugly workaround against GEOM parallel_offset bug creating a
    # MultiLineString out of offset LineString
    if upper_seam.parallel_offset(offset // 2, side='right').geom_type == 'MultiLineString' or offset == 0:
        upper_seam = np.array(upper_seam.coords, dtype=int)
    else:
        upper_seam = np.array(upper_seam.parallel_offset(offset // 2, side='right').coords, dtype=int)[::-1]
    if bottom_seam.parallel_offset(offset // 2, side='left').geom_type == 'MultiLineString' or offset == 0:
        bottom_seam = np.array(bottom_seam.coords, dtype=int)
    else:
        bottom_seam = np.array(bottom_seam.parallel_offset(offset // 2, side='left').coords, dtype=int)

    # offsetting might produce bounds outside the image. Clip it to the image bounds.
    polygon = np.concatenate(([end_points[0]], upper_seam, [end_points[-1]], bottom_seam[::-1]))
    polygon = geom.Polygon(polygon)
    if not polygon.is_valid:
        polygon = np.concatenate(([end_points[-1]], upper_seam, [end_points[0]], bottom_seam))
        polygon = geom.Polygon(polygon)
    if not polygon.is_valid:
        raise Exception(f'Invalid bounding polygon computed: {explain_validity(polygon)}')
    return np.array(ln.roi_polygon.intersection(polygon).boundary.coords, dtype=int)


def polygonize_page(jobs: list[tuple[Any, list]], im_feats: np.ndarray,
                    topline: bool | None) -> list[Any]:
    """Полігони всіх рядків сторінки; `None` там, де оригінал дав би `None`.

    `jobs` — (базова лінія, suppl_obj) у порядку `vec_lines`. Помилка рядка
    логується тим самим повідомленням, що й у `calculate_polygonal_environment`
    (індекс там завжди 0: `vec_lines` кличе її по одному рядку).
    """
    lines: list[_Line | Exception] = []
    for bl, suppl_obj in jobs:
        try:
            lines.append(_line_prep(bl, suppl_obj, im_feats, topline))
        except Exception as e:
            lines.append(e)
    carve([s for ln in lines if isinstance(ln, _Line) for s in (ln.upper, ln.bottom)])
    out: list[Any] = []
    for ln in lines:
        try:
            if isinstance(ln, Exception):
                raise ln
            out.append(_line_finish(ln))
        except Exception as e:
            logger.warning(f'Polygonizer failed on line 0: {e}')
            out.append(None)
    return out


def vec_lines_fast(heatmap, cls_map, scale, text_direction='horizontal-lr',
                   regions=None, scal_im=None, suppl_obj=None, topline=False,
                   raise_on_error=False, **kwargs):
    """`kraken.blla.vec_lines` із пакетною полігонізацією. Решта — дослівно."""
    import shapely.geometry as geom
    from kraken import blla
    from scipy.ndimage import gaussian_filter
    from skimage.filters import sobel

    if raise_on_error:
        # оригінал зупиняється на ПЕРШОМУ битому рядку; пакет рахує всі —
        # семантику винятку тримає лише оригінал
        return blla._vec_lines_orig(heatmap, cls_map, scale, text_direction, regions,
                                    scal_im, suppl_obj, topline, raise_on_error, **kwargs)

    st_sep = cls_map['aux']['_start_separator']
    end_sep = cls_map['aux']['_end_separator']

    blla.logger.info('Vectorizing baselines')
    baselines = []
    for bl_type, idx in cls_map['baselines'].items():
        blla.logger.debug(f'Vectorizing lines of type {bl_type}')
        baselines.extend([(bl_type, x) for x in blla.vectorize_lines(
            heatmap[(st_sep, end_sep, idx), :, :], text_direction=text_direction[:-3])])
    blla.logger.debug('Polygonizing lines')

    im_feats = gaussian_filter(sobel(scal_im), 0.5)

    reg_pols = [geom.Polygon(x) for x in regions]
    jobs = []
    for bl_idx in range(len(baselines)):
        bl = baselines[bl_idx]
        bl_ls = geom.LineString(bl[1])
        suppl = [x[1] for x in baselines[:bl_idx] + baselines[bl_idx + 1:]]
        for reg_idx, reg_pol in enumerate(reg_pols):
            if blla.is_in_region(bl_ls, reg_pol):
                suppl.append(regions[reg_idx])
        jobs.append((bl[1], suppl))
    # через атрибут модуля — щоб таймер етапу `polygon` бачив цей виклик
    pols = blla.polygonize_page(jobs, im_feats, topline)
    lines = [(bl[0], bl[1], pol) for bl, pol in zip(baselines, pols) if pol is not None]

    blla.logger.debug('Scaling vectorized lines')
    sc = blla.scale_polygonal_lines([x[1:] for x in lines], scale)

    lines = list(zip([x[0] for x in lines], [x[0] for x in sc], [x[1] for x in sc]))
    return [{'tags': {'type': [{'type': bl_type}]}, 'baseline': bl, 'boundary': pl}
            for bl_type, bl, pl in lines]


def _with_fallback(fast: Any, orig: Any) -> Any:
    def call(*a: Any, **kw: Any) -> Any:
        try:
            return fast(*a, **kw)
        except Exception:
            FALLBACKS["vec_lines"] += 1
            return orig(*a, **kw)
    return call


def install(verbose: bool = False) -> bool:
    """Підмінити `blla.vec_lines`. Ідемпотентно; False — kraken іншої версії."""
    import importlib.metadata as md

    from kraken import blla

    if getattr(blla, "_fast_seam_installed", False):
        return True
    try:
        ver = md.version("kraken")
    except md.PackageNotFoundError:
        ver = "?"
    # 🔴 Тут не попередження, як у fast_geom, а відмова: патч несе дослівні
    # копії `vec_lines`, `_extract_patch` і `_calc_seam`, і на іншій версії
    # kraken він тихо повернув би стару поведінку поверх нової.
    if ver != TESTED_KRAKEN:
        print(f"[fast-seam] ⚠ kraken {ver} ≠ перевіреного {TESTED_KRAKEN} — "
              "шов лишається оригінальним", flush=True)
        return False
    blla._vec_lines_orig = blla.vec_lines
    blla.polygonize_page = polygonize_page
    blla.vec_lines = _with_fallback(vec_lines_fast, blla._vec_lines_orig)
    blla._fast_seam_installed = True
    if verbose:
        print("[fast-seam] шви рядків пакетом на сторінку", flush=True)
    return True
