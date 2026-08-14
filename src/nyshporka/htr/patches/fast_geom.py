"""Прискорення CPU-геометрії Kraken — `_calc_roi` без Python-циклів по shapely.

Профіль живого прогону ПІСЛЯ перенесення sato на GPU (2026-07-26, 16 771 семпл):
**73.8% часу сторінки — CPU-геометрія `blla`**, а власне розпізнавання (LSTM) —
17.4%. Найдорожче в геометрії — `_calc_roi` (~25% сторінки), і не тому, що
рахує щось складне, а через дві структурні речі:

1. **O(рядків²)**: на КОЖЕН рядок перебираються ВСІ baselines сторінки з
   `upper_polygon.intersects(adj_line)`. На 46-70 рядків — 2-5 тис. викликів.
   Лікується просторовим індексом `STRtree`: bbox-фільтр консервативний
   (не може відкинути справжнє перетинання), тож множина збігів та сама.
2. **Python-цикл на кожну точку** інтерпольованої базової лінії (кожні 10 px,
   тобто сотні точок на рядок): `LineString(...).intersection(...)` і
   `min(geoms, key=spt.distance)`. shapely 2.x усе це вміє векторизовано, на C.

⚠ Це патч ЧУЖОЇ бібліотеки, і від геометрії залежать полігони рядків, тобто
текст. Тому нічого не «спрощується»: порядок додавання ліній, вибір при рівних
відстанях (перший мінімум) і типи виходу збережені навмисне. Перевірка —
`scripts/fast_geom_verify.py`, який ганяє стару і нову версії пліч-о-пліч на
реальних сторінках і звіряє масиви.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely import geometry as geom
from shapely.ops import nearest_points, unary_union

# Кеш STRtree на сторінку. Ключ — САМІ об'єкти-списки (звірка через `is`), а не
# id(): id звільненого списку може дістатись новому, і дерево тихо стало б чужим.
# Тримаючи посилання, ми це унеможливлюємо; живе рівно один запис.
_TREE_CACHE: dict = {"baselines": None, "suppl": None, "lines": None, "tree": None}


def _adj_lines_tree(baselines, suppl_obj):
    c = _TREE_CACHE
    if (c["baselines"] is baselines and c["suppl"] is suppl_obj
            and c["lines"] is not None):
        return c["lines"], c["tree"]
    adj = list(baselines) + list(suppl_obj)
    lines = np.array([geom.LineString(a) for a in adj], dtype=object)
    tree = shapely.STRtree(lines) if len(lines) else None
    c.update(baselines=baselines, suppl=suppl_obj, lines=lines, tree=tree)
    return lines, tree


def _closest_coord(pt, inter):
    """Координата найближчої до `pt` точки перетину — еквівалент `_find_closest_point`.

    Оригінал повертає геометрію, з якої далі беруть `.coords[0]`, тож віддаємо
    одразу координату. `min(..., key=distance)` бере ПЕРШИЙ мінімум — `argmin`
    теж; порядок `geoms` збігається з порядком `get_coordinates` для MultiPoint.
    Порівняння за квадратом відстані не змінює індексу мінімуму.
    """
    if inter.is_empty:
        raise Exception('No intersection with boundaries. Shapely intersection '
                        f'object: {inter.wkt}')
    gt = inter.geom_type
    if gt == 'Point':
        return inter.coords[0]
    if gt == 'MultiPoint':
        xy = shapely.get_coordinates(inter)
        d = ((xy - np.asarray(pt, dtype=float)) ** 2).sum(axis=1)
        return tuple(xy[int(np.argmin(d))])
    if gt == 'GeometryCollection' and len(inter.geoms) > 0:
        # рідкісна гілка — лишаємо оригінальну логіку разом з її дивиною
        # (`if t == 'Point'` порівнює геометрію з рядком і ніколи не істинне)
        spt = geom.Point(pt)
        t = min(list(inter.geoms), key=lambda x: spt.distance(x))
        return nearest_points(spt, t)[1].coords[0]
    raise Exception('No intersection with boundaries. Shapely intersection '
                    f'object: {inter.wkt}')


def calc_roi_fast(line, bounds, baselines, suppl_obj, p_dir):
    """Заміна `kraken.lib.segmentation._calc_roi` з тим самим виходом."""
    from kraken.lib.segmentation import _ray_intersect_boundaries

    # ── 1. інтерполяція базової лінії кожні 10 px ────────────────────────────
    ls = geom.LineString(line)
    # оригінал: `dist = 10; while dist < line.length: ...; dist += 10`.
    # `arange` рахує start + i*step (стабільніше за накопичення), але його
    # верхня межа обчислюється через ceil((stop-start)/step) у плавучій арифметиці
    # — на довжині, кратній 10, це може ЛИШИТИ точку, рівну length, якої цикл
    # `while dist < length` не дав би. Зайва точка = зайвий промінь = інший
    # полігон рядка, тобто інший текст. Фільтр робить нерівність суворою.
    dists = np.arange(10.0, ls.length, 10.0)
    if len(dists) and dists[-1] >= ls.length:
        dists = dists[dists < ls.length]
    if len(dists):
        mid = shapely.get_coordinates(shapely.line_interpolate_point(ls, dists))
        ip_line = np.vstack([np.asarray(line[0], dtype=float)[None], mid,
                             np.asarray(line[-1], dtype=float)[None]])
    else:
        ip_line = np.array([line[0], line[-1]], dtype=float)

    up_dir = (p_dir * (-1, 1))[::-1]
    bt_dir = (p_dir * (1, -1))[::-1]
    b1 = bounds + 1
    upper_bounds_intersects = [_ray_intersect_boundaries(p, up_dir, b1).astype('int')
                               for p in ip_line]
    bottom_bounds_intersects = [_ray_intersect_boundaries(p, bt_dir, b1).astype('int')
                                for p in ip_line]

    upper_polygon = geom.Polygon(ip_line.tolist() + upper_bounds_intersects)
    bottom_polygon = geom.Polygon(ip_line.tolist() + bottom_bounds_intersects)

    # ── 2. добір суміжних ліній: STRtree замість перебору всіх ───────────────
    side_a = [geom.LineString(upper_bounds_intersects)]
    side_b = [geom.LineString(bottom_bounds_intersects)]
    lines, tree = _adj_lines_tree(baselines, suppl_obj)
    if tree is not None:
        # кандидати за bbox для обох полігонів, далі — точна перевірка В ТОМУ Ж
        # ПОРЯДКУ, що й оригінальний цикл: порядок міняє результат unary_union
        cand = np.union1d(tree.query(upper_polygon), tree.query(bottom_polygon))
        for idx in np.sort(cand):
            adj_line = lines[int(idx)]
            if upper_polygon.intersects(adj_line):
                side_a.append(adj_line)
            elif bottom_polygon.intersects(adj_line):
                side_b.append(adj_line)
    side_a = unary_union(side_a).buffer(1).boundary
    side_b = unary_union(side_b).buffer(1).boundary

    # ── 3. перетини променів з межами — векторизовано ───────────────────────
    up_arr = np.asarray(upper_bounds_intersects, dtype=float)
    bt_arr = np.asarray(bottom_bounds_intersects, dtype=float)
    up_seg = shapely.linestrings(np.stack([ip_line, up_arr], axis=1))
    bt_seg = shapely.linestrings(np.stack([ip_line, bt_arr], axis=1))
    inter_a = shapely.intersection(up_seg, side_a)
    inter_b = shapely.intersection(bt_seg, side_b)

    env_up = [_closest_coord(p, ia) for p, ia in zip(ip_line, inter_a)]
    env_bottom = [_closest_coord(p, ib) for p, ib in zip(ip_line, inter_b)]
    return (np.array(env_up, dtype='uint'), np.array(env_bottom, dtype='uint'))


# ── обхід контуру (Moore) ────────────────────────────────────────────────────
# Порядок ЗАФІКСОВАНИЙ оригіналом і не є довільним: сусіди обходяться проти
# годинникової від backtrack, і від цього залежить, який саме піксель стане
# наступним на контурі.
_OPS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))
_OFF2IDX = {op: i for i, op in enumerate(_OPS)}


def boundary_tracing_fast(region):
    """Заміна `kraken.lib.segmentation.boundary_tracing` без numpy в циклі.

    Оригінал на КОЖЕН піксель контуру будує масив 8×2 (`moore_neighborhood`),
    шукає в ньому backtrack Python-циклом і робить fancy-indexing на 8 елементів.
    Разом це 13.8% часу сторінки — не через обчислення, а через накладні витрати
    numpy на мікромасивах. Тут та сама логіка на скалярах і плоскому списку.

    Дві тонкощі оригіналу відтворені навмисне:
    - `np.argmax` на суцільних нулях повертає 0 (а не «не знайдено»);
    - `neighbors[idx - 1]` при idx == 0 бере ОСТАННІЙ сусід (від'ємний індекс).
    """
    coords = region.coords
    mins = np.amin(coords, axis=0)
    maxs = np.amax(coords, axis=0)
    h, w = int(maxs[0] - mins[0] + 3), int(maxs[1] - mins[1] + 3)
    binary = np.zeros((h, w), dtype=np.uint8)
    ys = coords[:, 0] - mins[0] + 1
    xs = coords[:, 1] - mins[1] + 1
    binary[ys, xs] = 1
    flat = binary.ravel().tolist()          # Python-список: доступ дешевший за .item()

    idx_start = 0
    while True:                              # стартова точка не має бути ізольованою
        sy, sx = int(ys[idx_start]), int(xs[idx_start])
        if binary[sy - 1:sy + 2, sx - 1:sx + 2].sum() > 1:
            break
        idx_start += 1

    if flat[(sy + 1) * w + sx] == 0 and flat[(sy + 1) * w + sx - 1] == 0:
        by, bx = sy + 1, sx
    else:
        by, bx = sy, sx - 1

    bs_y, bs_x = by, bx
    cy, cx = sy, sx
    boundary: list[tuple[int, int]] = []
    while True:
        k = _OFF2IDX.get((by - cy, bx - cx))
        if k is None:                        # оригінал тут повернув би 0 і впав
            raise ValueError("boundary_tracing: backtrack не є сусідом current")
        found = 0                            # ← поведінка argmax на всіх нулях
        for t in range(8):
            dy, dx = _OPS[(k + t) & 7]
            if flat[(cy + dy) * w + cx + dx]:
                found = t
                break
        boundary.append((cy, cx))
        bdy, bdx = _OPS[(k + found - 1) & 7]
        ndy, ndx = _OPS[(k + found) & 7]
        by, bx = cy + bdy, cx + bdx
        cy, cx = cy + ndy, cx + ndx
        if cy == sy and cx == sx and by == bs_y and bx == bs_x:
            break

    return np.array(boundary) + [int(mins[0]) - 1, int(mins[1]) - 1]


# ── поворот патча для seam-carving ───────────────────────────────────────────
def warp_nearest(image, matrix, output_shape, cval):
    """`skimage.transform.warp(..., order=0, mode='constant')` прямим рахунком.

    skimage на цьому виклику йде повільним шляхом — `np.indices` → `_apply_mat`
    → `scipy.map_coordinates` (7% часу сторінки), хоча при order=0 інтерполяції
    немає взагалі: досить порахувати координати й вибрати пікселі.

    Семантика відтворена пробою, а не з документації, і вона НЕ така, як у
    `scipy.map_coordinates`, викликаного напряму:
    - округлення `floor(x + 0.5)` — round-half-UP, а НЕ `np.round`
      (той банкірський: 0.5→0, 2.5→2, і давав би інші пікселі);
    - межі перевіряються ПІСЛЯ округлення, тому координата -0.4 чи (n-1)+0.3
      законно дає крайовий піксель, а не cval. Перша версія перевіряла до
      округлення (як робить map_coordinates з mode='constant') і розходилась
      на 2.6% пікселів — усі рівно по краю патча.
    """
    rows, cols = image.shape[:2]
    orr, occ = int(output_shape[0]), int(output_shape[1])
    cc = np.arange(occ, dtype=np.float64)
    rr = np.arange(orr, dtype=np.float64)[:, None]
    x = matrix[0, 0] * cc + matrix[0, 1] * rr + matrix[0, 2]
    y = matrix[1, 0] * cc + matrix[1, 1] * rr + matrix[1, 2]
    xi = np.floor(x + 0.5).astype(np.intp)
    yi = np.floor(y + 0.5).astype(np.intp)
    valid = (xi >= 0) & (xi <= cols - 1) & (yi >= 0) & (yi <= rows - 1)
    np.clip(xi, 0, cols - 1, out=xi)
    np.clip(yi, 0, rows - 1, out=yi)
    out = np.full((orr, occ), cval, dtype=image.dtype)
    out[valid] = image[yi[valid], xi[valid]]
    return out


def rotate_fast(image, angle, center, scale, cval=0, order=0,
                use_skimage_warp=False):
    """Заміна `_rotate` для numpy-гілки з order=0 (єдина, яку кличе `_calc_seam`).

    Решта випадків (PIL-вхід, order>0) віддаються оригіналу — вони або вже
    швидкі (PIL), або вимагають справжньої інтерполяції.
    """
    from PIL import Image as _Image
    from skimage.transform import AffineTransform

    if isinstance(image, _Image.Image) or order != 0 or image.ndim != 2:
        # ⚠ саме `_rotate_orig`, а не імпорт `_rotate`: після install() друге ім'я
        # вказує вже на цю ж функцію, і фолбек пішов би в нескінченну рекурсію
        from kraken.lib import segmentation as kseg
        return kseg._rotate_orig(image, angle, center, scale, cval, order,
                                 use_skimage_warp)
    rows, cols = image.shape[:2]
    tform = AffineTransform(rotation=angle, scale=(1 / scale, 1))
    corners = tform.inverse(np.array([[0, 0], [0, rows - 1],
                                      [cols - 1, rows - 1], [cols - 1, 0]]))
    minc, minr = corners[:, 0].min(), corners[:, 1].min()
    maxc, maxr = corners[:, 0].max(), corners[:, 1].max()
    output_shape = tuple(int(o) for o in np.around((maxr - minr + 1,
                                                    maxc - minc + 1)))
    translation = tform([[minc, minr]])
    tform = AffineTransform(rotation=angle, scale=(1 / scale, 1),
                            translation=[f for f in translation.flatten()])
    return tform, warp_nearest(image, tform.params, output_shape, cval)


#: Версії, на яких патчі звірені з оригіналом (fast_geom_verify: 82/82 _calc_roi,
#: 98/98 boundary_tracing, 164/164 _rotate, 6/6 сторінок ідентичний текст).
#: Це патч ЧУЖОГО коду: інша версія kraken може змінити семантику підмінених
#: функцій, і розбіжність буде ТИХОЮ — той самий скан дасть інші полігони рядків,
#: тобто інший текст, без жодної помилки в лозі. Тому — гучне попередження.
TESTED_KRAKEN = "7.0.2"
TESTED_SHAPELY = "2.1.2"


def _warn_version_drift() -> None:
    import importlib.metadata as md

    for pkg, tested in (("kraken", TESTED_KRAKEN), ("shapely", TESTED_SHAPELY)):
        try:
            have = md.version(pkg)
        except Exception:
            continue
        if have != tested:
            print(f"[fast-geom] ⚠ {pkg} {have}, а патчі звірені на {tested}. "
                  f"Перезвір: .venv_kraken/Scripts/python.exe "
                  f"scripts/fast_geom_verify.py 5", flush=True)


def install(verbose: bool = False) -> bool:
    """Підмінити гарячі функції в модулі kraken.

    Виклики всередині `calculate_polygonal_environment` / `vectorize_lines`
    резолвлять глобальні імена модуля на кожен виклик, тому підміни досить.
    """
    from kraken.lib import segmentation as kseg

    if getattr(kseg, "_fast_geom_installed", False):
        return True
    _warn_version_drift()
    # ловимо перейменування в чужій бібліотеці ЯВНО, а не через AttributeError
    # десь у надрах сегментації посеред нічного прогону
    missing = [n for n in ("_calc_roi", "boundary_tracing", "_rotate")
               if not hasattr(kseg, n)]
    if missing:
        raise RuntimeError(
            f"fast_geom: у kraken.lib.segmentation немає {missing} — "
            f"версія пакета розійшлася з патчем (звірено на {TESTED_KRAKEN})")
    kseg._calc_roi_orig = kseg._calc_roi
    kseg._calc_roi = calc_roi_fast
    kseg._boundary_tracing_orig = kseg.boundary_tracing
    kseg.boundary_tracing = boundary_tracing_fast
    kseg._rotate_orig = kseg._rotate
    kseg._rotate = rotate_fast
    kseg._fast_geom_installed = True
    if verbose:
        print("[fast-geom] _calc_roi (STRtree+векторний shapely) + "
              "boundary_tracing (скалярний обхід) + _rotate (nearest без skimage)",
              flush=True)
    return True
