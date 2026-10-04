"""Звірка `pp_fp16`: основа PP-моделі у fp16 читає ті самі кропи практично так само.

    <інтерпретатор рушіїв> pp_fp16_verify.py <модель .safetensors> <тека PNG-кропів> [N=200] [пристрій]

На відміну від `pp_fuse` тут тотожності не буде: половинна точність зсуває
рядки на краю рішення (як і інший склад пачки у fp32). Приймач інший:
- жоден рядок, що у fp32 має текст, не стає порожнім у fp16 — саме так
  проявлялась вада cuDNN у `stem3` (порожній вихід на всю пачку);
- розбіжність fp16 проти fp32 — не більше 1% символів (V100 04.10.2026: 0.2%).
Поруч друкується час обох проходів і частка тотожних рядків. Лише CUDA.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))           # runner.py лежить поверхом вище

MAX_DIFF = 0.01


def _dist(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    import runner as R
    import torch
    from PIL import Image

    if not torch.cuda.is_available():
        print("⚠ карти немає — fp16 для PP вмикається лише на CUDA")
        return 2
    model, folder = sys.argv[1], Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    dev = sys.argv[4] if len(sys.argv) > 4 else "cuda:0"
    files = sorted(folder.glob("*.png"))
    step = max(1, len(files) // n)
    crops = []
    for f in files[::step][:n]:
        with Image.open(f) as im:
            crops.append(im.convert("RGB"))

    def read(precision: str) -> tuple[list[str], float]:
        R.PP_PRECISION = precision
        pp = R.load_pp(model, dev)
        R.pp_decode_crops(pp, crops[:16])          # прогрів
        torch.cuda.synchronize()
        t = time.time()
        out = R.pp_decode_crops(pp, crops)
        torch.cuda.synchronize()
        return out, time.time() - t

    ref, t_ref = read("fp32")
    got, t_got = read("fp16")
    same = sum(a == b for a, b in zip(ref, got, strict=True))
    emptied = [i for i, (a, b) in enumerate(zip(ref, got, strict=True)) if a and not b]
    diff = sum(_dist(a, b) for a, b in zip(ref, got, strict=True)) / max(
        1, sum(len(a) for a in ref))
    print(f"рядків {len(crops)} · тотожних {same} · розбіжність {100 * diff:.2f}% символів · "
          f"спорожніло {len(emptied)} · fp32 {1000 * t_ref / len(crops):.1f} мс/рядок · "
          f"fp16 {1000 * t_got / len(crops):.1f} мс/рядок")
    ok = not emptied and diff <= MAX_DIFF
    print("✓ ПРИЙНЯТО" if ok else "✗ НЕ ПРИЙНЯТО")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
