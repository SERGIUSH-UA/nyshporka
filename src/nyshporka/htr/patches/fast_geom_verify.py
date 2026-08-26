"""Звірка `fast_geom.calc_roi_fast` з оригіналом Kraken на реальних сторінках.

Синтетика тут нічого не доводить: `_calc_roi` чутлива до взаємного розміщення
рядків (скільки сусідів зачіпає полігон, як лягають промені), а це властивість
конкретної сторінки. Тому патчимо обгорткою, яка кличе обидві версії на тих
самих аргументах, і ганяємо справжню `blla.segment`.

Порівнюються самі масиви env_up/env_bottom — не «схожість полігонів»: будь-яка
розбіжність тут означає інший кроп рядка і потенційно інший текст.

Запускається інтерпретатором середовища рушіїв (не основним):

    <venv>/bin/python -m nyshporka.htr.patches.fast_geom_verify <тека справи> [N]

🔴 Тека справи — обов'язковий аргумент, а не константа. Патч перевіряється на
тому матеріалі, з яким працюватимуть: геометрія рядків залежить від почерку,
щільності й формуляра, і «зійшлось на чужій справі» нічого не гарантує для вашої.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATS = {"calls": 0, "same": 0, "diff": 0, "t_orig": 0.0, "t_fast": 0.0,
         "max_dev": 0.0, "shape_diff": 0}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    case = Path(sys.argv[1])
    if not case.is_dir():
        print(f"✗ немає теки справи: {case}", file=sys.stderr)
        return 2
    n_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    from kraken import blla
    from kraken.lib import segmentation as kseg
    from kraken.lib import vgsl
    from kraken.kraken import SEGMENTATION_DEFAULT_MODEL

    from fast_geom import calc_roi_fast
    from gpu_sato import install_gpu_sato

    install_gpu_sato((1, 3), device="cuda:0")   # як у бойовому прогоні
    orig = kseg._calc_roi

    def both(line, bounds, baselines, suppl_obj, p_dir):
        t0 = time.perf_counter()
        a_up, a_bt = orig(line, bounds, baselines, suppl_obj, p_dir)
        t1 = time.perf_counter()
        b_up, b_bt = calc_roi_fast(line, bounds, baselines, suppl_obj, p_dir)
        t2 = time.perf_counter()
        STATS["t_orig"] += t1 - t0
        STATS["t_fast"] += t2 - t1
        STATS["calls"] += 1
        if a_up.shape != b_up.shape or a_bt.shape != b_bt.shape:
            STATS["shape_diff"] += 1
            STATS["diff"] += 1
        else:
            d = max(float(np.abs(a_up.astype(np.int64) - b_up.astype(np.int64)).max()
                          if a_up.size else 0),
                    float(np.abs(a_bt.astype(np.int64) - b_bt.astype(np.int64)).max()
                          if a_bt.size else 0))
            STATS["max_dev"] = max(STATS["max_dev"], d)
            STATS["same" if d == 0 else "diff"] += 1
        return a_up, a_bt          # у конвеєр іде оригінальний результат

    # підміняємо саме в модулі-власнику: виклик усередині
    # calculate_polygonal_environment резолвить глобальне ім'я на кожен виклик
    kseg._calc_roi = both

    from fast_geom import boundary_tracing_fast
    bt_orig = kseg.boundary_tracing
    BT = {"calls": 0, "same": 0, "diff": 0, "t_orig": 0.0, "t_fast": 0.0}

    def both_bt(region):
        t0 = time.perf_counter()
        a = bt_orig(region)
        t1 = time.perf_counter()
        b = boundary_tracing_fast(region)
        t2 = time.perf_counter()
        BT["t_orig"] += t1 - t0
        BT["t_fast"] += t2 - t1
        BT["calls"] += 1
        BT["same" if (a.shape == b.shape and np.array_equal(a, b)) else "diff"] += 1
        return a

    kseg.boundary_tracing = both_bt
    STATS["_bt"] = BT

    from fast_geom import rotate_fast
    rot_orig = kseg._rotate
    kseg._rotate_orig = rot_orig
    RT = {"calls": 0, "same": 0, "diff": 0, "skip": 0, "t_orig": 0.0, "t_fast": 0.0}

    def both_rot(image, angle, center, scale, cval=0, order=0,
                 use_skimage_warp=False):
        t0 = time.perf_counter()
        ta, a = rot_orig(image, angle, center, scale, cval, order, use_skimage_warp)
        t1 = time.perf_counter()
        tb, b = rotate_fast(image, angle, center, scale, cval, order, use_skimage_warp)
        t2 = time.perf_counter()
        RT["calls"] += 1
        if hasattr(image, "size") and not hasattr(image, "shape"):
            RT["skip"] += 1                      # PIL-гілка йде в оригінал
        else:
            RT["t_orig"] += t1 - t0
            RT["t_fast"] += t2 - t1
            same = (np.asarray(a).shape == np.asarray(b).shape
                    and np.array_equal(np.asarray(a), np.asarray(b)))
            RT["same" if same else "diff"] += 1
        return ta, a

    kseg._rotate = both_rot
    STATS["_rt"] = RT

    seg_model = vgsl.TorchVGSLModel.load_model(SEGMENTATION_DEFAULT_MODEL)
    pages = sorted(p for p in case.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:n_pages]
    if not pages:
        print(f"✗ у теці немає зображень: {case}", file=sys.stderr)
        return 2
    for p in pages:
        with Image.open(p) as raw:
            im = raw.convert("RGB")
        t0 = time.perf_counter()
        seg = blla.segment(im, model=seg_model, device="cuda:0")
        print(f"  {p.name}: {len(seg.lines)} рядків за {time.perf_counter()-t0:.1f} с "
              f"(виклики _calc_roi: {STATS['calls']})", flush=True)

    s = STATS
    print(f"\nвикликів _calc_roi: {s['calls']}")
    print(f"  збігів: {s['same']}   розбіжностей: {s['diff']} "
          f"(з них інша форма масиву: {s['shape_diff']})")
    print(f"  макс. відхилення координати: {s['max_dev']:.0f} px")
    print(f"  час: оригінал {s['t_orig']:.1f} с → швидка {s['t_fast']:.1f} с "
          f"= ×{s['t_orig']/max(s['t_fast'],1e-9):.2f}")
    bt = s.get("_bt") or {"calls": 0, "same": 0, "diff": 0, "t_orig": 0, "t_fast": 0}
    print(f"\nвикликів boundary_tracing: {bt['calls']}")
    print(f"  збігів: {bt['same']}   розбіжностей: {bt['diff']}")
    if bt["calls"]:
        print(f"  час: оригінал {bt['t_orig']:.1f} с → швидка {bt['t_fast']:.1f} с "
              f"= ×{bt['t_orig']/max(bt['t_fast'],1e-9):.2f}")
    rt = s.get("_rt") or {"calls": 0, "same": 0, "diff": 0, "skip": 0,
                          "t_orig": 0, "t_fast": 0}
    print(f"\nвикликів _rotate: {rt['calls']} (PIL-гілка в оригінал: {rt['skip']})")
    print(f"  збігів: {rt['same']}   розбіжностей: {rt['diff']}")
    if rt["t_fast"]:
        print(f"  час: skimage {rt['t_orig']:.1f} с → свій {rt['t_fast']:.1f} с "
              f"= ×{rt['t_orig']/max(rt['t_fast'],1e-9):.2f}")
    ok = (s["diff"] == 0 and s["calls"] > 0 and bt["diff"] == 0
          and rt["diff"] == 0)
    print("\n" + ("✓ еквівалентно" if ok else "✗ Є розбіжності — не вмикати"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
