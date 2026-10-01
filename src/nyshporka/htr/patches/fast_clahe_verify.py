"""Звірка `fast_clahe.equalize_adapthist_fast` з skimage на справжніх кадрах — до біта.

    <інтерпретатор рушіїв> fast_clahe_verify.py <тека справи> [N] [--all]

Береться N кадрів (рівномірно); без `--all` — лише ті, які раннер справді
підсилює (контраст нижче порогу `auto`). Кадр зводиться до висоти 3100, як
перед хмарою. Порівнюється сам `equalize_adapthist` (float) і весь
`enhance_image('clahesmooth')` (uint8, те, що йде в сегментацію).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    case = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 20
    every = "--all" in sys.argv
    from skimage.exposure import equalize_adapthist

    import fast_clahe
    import runner as R

    if not fast_clahe.install("cuda:0", verbose=True):
        print("✗ fast_clahe не встановився — немає карти чи інша версія skimage")
        return 2
    files = sorted(p for p in case.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    step = max(1, len(files) // (n * (1 if every else 3)))
    same = diff = 0
    t_o = t_f = 0.0
    seen = 0
    for f in files[::step]:
        if seen >= n:
            break
        with Image.open(f) as raw:
            im = raw.convert("RGB")
        if im.height > 3100:
            im = im.resize((round(im.width * 3100 / im.height), 3100), Image.LANCZOS)
        if not every and R.page_contrast(im) >= R.AUTO_CONTRAST_THRESHOLD:
            continue
        seen += 1
        g = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
        ks = (g.shape[0] // 8, g.shape[1] // 8)
        t = time.perf_counter()
        a = equalize_adapthist(g, kernel_size=ks, clip_limit=0.02)
        t_o += time.perf_counter() - t
        t = time.perf_counter()
        b = fast_clahe.equalize_adapthist_fast(g, kernel_size=ks, clip_limit=0.02)
        t_f += time.perf_counter() - t
        ok = a.dtype == b.dtype and a.shape == b.shape and np.array_equal(a, b)
        # і весь шлях раннера: з патчем і без
        fast_clahe.STATE["device"] = None
        e1 = np.asarray(R.enhance_image(im, "clahesmooth"))
        fast_clahe.STATE["device"] = "cuda:0"
        e2 = np.asarray(R.enhance_image(im, "clahesmooth"))
        ok = ok and np.array_equal(e1, e2)
        same += ok
        diff += not ok
        print(f"  {f.name}: {'=' if ok else '≠'}  max|Δ| {float(np.abs(a - b).max()):.3g}", flush=True)
    print(f"\nкадрів {same + diff}: збігів {same}, розбіжностей {diff} · "
          f"equalize_adapthist: skimage {t_o:.1f} с → карта {t_f:.1f} с "
          f"= ×{t_o / max(t_f, 1e-9):.2f} · відступів {fast_clahe.STATE['fallbacks']}")
    ok = diff == 0 and same > 0 and not fast_clahe.STATE["fallbacks"]
    print("✓ еквівалентно" if ok else "✗ Є розбіжності — не вмикати")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
