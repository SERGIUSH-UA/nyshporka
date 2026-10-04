"""Звірка `pp_fuse`: PP-модель зі злиттям BN і без читає ті самі кропи до символу.

    <інтерпретатор рушіїв> pp_fuse_verify.py <модель .safetensors> <тека PNG-кропів> [N=200] [пристрій]

Тека — кропи рядків (наприклад `data/htr_gt/<набір>/_export`). Обидві версії
читають ті самі N кропів тим самим шляхом раннера (`pp_read_crops`, ті самі
пачки), тож різниця може бути лише від злиття. Приймач — 100% тотожних рядків;
поруч друкується час обох проходів.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))           # runner.py лежить поверхом вище


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    import runner as R
    import torch
    from PIL import Image

    model, folder = sys.argv[1], Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    dev = sys.argv[4] if len(sys.argv) > 4 else ("cuda:0" if torch.cuda.is_available() else "cpu")
    files = sorted(folder.glob("*.png"))
    step = max(1, len(files) // n)
    crops = []
    for f in files[::step][:n]:
        with Image.open(f) as im:
            crops.append(im.convert("RGB"))

    # fp16 тотожності не дає за побудовою — злиття звіряється у повній точності
    R.PP_PRECISION = "fp32"

    def read(fuse: bool) -> tuple[list[str], float]:
        R.PP_FUSE = fuse
        pp = R.load_pp(model, dev)
        R.pp_decode_crops(pp, crops[:16])          # прогрів
        if dev.startswith("cuda"):
            torch.cuda.synchronize()
        t = time.time()
        out = R.pp_decode_crops(pp, crops)
        if dev.startswith("cuda"):
            torch.cuda.synchronize()
        return out, time.time() - t

    ref, t_ref = read(False)
    got, t_got = read(True)
    same = sum(a == b for a, b in zip(ref, got, strict=True))
    print(f"рядків {len(crops)} · тотожних {same} · без злиття {1000 * t_ref / len(crops):.1f} "
          f"мс/рядок · зі злиттям {1000 * t_got / len(crops):.1f} мс/рядок")
    for a, b in zip(ref, got, strict=True):
        if a != b:
            print(f"  ✗ {a!r}\n    {b!r}")
            break
    print("✓ ТОТОЖНО" if same == len(crops) else "✗ РОЗБІЖНОСТІ")
    return 0 if same == len(crops) else 1


if __name__ == "__main__":
    sys.exit(main())
