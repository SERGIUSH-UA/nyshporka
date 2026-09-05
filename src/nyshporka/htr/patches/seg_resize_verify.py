"""Звірка `seg_resize` зі стоковим `compute_segmentation_map` на реальних кадрах.

Доказ тут двошаровий, і обидва шари потрібні:

1. **Побайтно** — `scal_im` (numpy) і тензор мережі (`torch.equal`) від голови
   ланцюга, застосованої один раз, проти стокового шляху «голова + весь ланцюг».
   Це і є твердження патча: обидва проходи детерміновані, тож вхід у мережу той
   самий до біта.
2. **Наскрізно** — `blla.segment` стоком і з патчем на тому самому кадрі дає ті
   самі baseline і полігони рядків. Форвард на карті може бути недетермінованим
   на рівні float (cudnn), тому хітмапу звіряємо `allclose`, а геометрію — точно.

Запускається інтерпретатором середовища рушіїв (не основним):

    <venv>/bin/python -m nyshporka.htr.patches.seg_resize_verify <тека справи> [N]

🔴 Тека справи — обов'язковий аргумент. Патч має сенс саме на важких кадрах
(розвороти 16 Мпікс), і саме на них його й треба звіряти.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _lines_key(seg) -> list[tuple]:
    return [(tuple(map(tuple, ln.baseline)), tuple(map(tuple, ln.boundary)))
            for ln in seg.lines]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    case = Path(sys.argv[1])
    if not case.is_dir():
        print(f"✗ немає теки справи: {case}", file=sys.stderr)
        return 2
    n_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    device = "cuda:0"

    import torch
    from kraken import blla
    from kraken.kraken import SEGMENTATION_DEFAULT_MODEL
    from kraken.lib import dataset, vgsl

    import seg_resize
    from gpu_sato import install_gpu_sato

    install_gpu_sato((1, 3), device=device)   # як у бойовому прогоні
    model = vgsl.TorchVGSLModel.load_model(SEGMENTATION_DEFAULT_MODEL)
    model.eval()
    batch, channels, height, width = model.input
    hp = model.user_metadata["hyper_params"]
    padding = hp["padding"] if "padding" in hp else (0, 0)
    transforms = dataset.ImageInputTransforms(batch, height, width, channels,
                                              padding, valid_norm=False)
    head, tail = seg_resize.split_transforms(transforms)

    pages = sorted(p for p in case.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[:n_pages]
    if not pages:
        print(f"✗ у теці немає зображень: {case}", file=sys.stderr)
        return 2

    stats = {"pages": 0, "scal_same": 0, "tensor_same": 0, "heat_close": 0,
             "lines_same": 0, "t_orig": 0.0, "t_once": 0.0, "max_heat_dev": 0.0}
    orig = blla.compute_segmentation_map
    for p in pages:
        with Image.open(p) as raw:
            im = raw.convert("RGB")
        stats["pages"] += 1
        # ── шар 1: побайтно ──
        t0 = time.perf_counter()
        scal_a = np.array(head(im).convert("L"))
        tensor_a = transforms(im)
        t1 = time.perf_counter()
        scaled = head(im)
        scal_b = np.array(scaled.convert("L"))
        tensor_b = tail(scaled)
        t2 = time.perf_counter()
        stats["t_orig"] += t1 - t0
        stats["t_once"] += t2 - t1
        scal_same = scal_a.shape == scal_b.shape and np.array_equal(scal_a, scal_b)
        tensor_same = tensor_a.shape == tensor_b.shape and torch.equal(tensor_a, tensor_b)
        stats["scal_same"] += int(scal_same)
        stats["tensor_same"] += int(tensor_same)
        # ── шар 2: наскрізно ──
        blla.compute_segmentation_map = orig
        ra = orig(im, model=model, device=device)
        seg_a = blla.segment(im, model=model, device=device)
        blla.compute_segmentation_map = seg_resize.compute_segmentation_map_once
        rb = seg_resize.compute_segmentation_map_once(im, model=model, device=device)
        seg_b = blla.segment(im, model=model, device=device)
        blla.compute_segmentation_map = orig
        dev = float(np.abs(ra["heatmap"] - rb["heatmap"]).max()) \
            if ra["heatmap"].shape == rb["heatmap"].shape else float("inf")
        stats["max_heat_dev"] = max(stats["max_heat_dev"], dev)
        heat_close = dev <= 1e-5 and np.array_equal(ra["scal_im"], rb["scal_im"])
        lines_same = _lines_key(seg_a) == _lines_key(seg_b)
        stats["heat_close"] += int(heat_close)
        stats["lines_same"] += int(lines_same)
        print(f"  {p.name}: {im.size[0]}×{im.size[1]} · scal_im {'=' if scal_same else '≠'} "
              f"· тензор {'=' if tensor_same else '≠'} · хітмапа Δ{dev:.1e} "
              f"· рядків {len(seg_a.lines)}/{len(seg_b.lines)} "
              f"{'=' if lines_same else '≠'} · підготовка {t1-t0:.2f} → {t2-t1:.2f} с",
              flush=True)

    s = stats
    n = s["pages"]
    print(f"\nкадрів: {n}")
    print(f"  scal_im побайтно: {s['scal_same']}/{n}   тензор побайтно: {s['tensor_same']}/{n}")
    print(f"  хітмапа allclose: {s['heat_close']}/{n} (макс. Δ {s['max_heat_dev']:.1e})"
          f"   рядки тотожні: {s['lines_same']}/{n}")
    print(f"  підготовка кадру: сток {s['t_orig']:.2f} с → патч {s['t_once']:.2f} с "
          f"= ×{s['t_orig']/max(s['t_once'],1e-9):.2f} "
          f"(економія {(s['t_orig']-s['t_once'])/max(n,1):.2f} с/кадр)")
    ok = (n > 0 and s["scal_same"] == n and s["tensor_same"] == n
          and s["lines_same"] == n)
    print("\n" + ("✓ еквівалентно" if ok else "✗ Є розбіжності — не вмикати"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
