"""Звірка `fast_order` з оригінальним `_reading_order` kraken — до біта.

    <інтерпретатор рушіїв> -m nyshporka.htr.patches.fast_order_verify [кадрів] [тека кадрів]

Без теки — лише випадкові набори рядків (зокрема з однаковими межами, нульовою
шириною й обома напрямками письма). З текою — ще й baseline'и справжніх сторінок
із сегментації kraken: полігонний порядок читання (`polygonal_reading_order`)
рахується обома версіями, і перелік індексів мусить збігтися.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

# Гість середовища рушіїв: пакета тут немає, сусід вантажиться за шляхом.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fast_order import reading_order_fast  # noqa: E402


def _random_lines(rng: np.random.Generator, n: int, *, grid: bool) -> list:
    out = []
    for _ in range(n):
        if grid:     # таблиця: межі з сітки, тож повтори й дотики — норма
            y0, x0 = rng.integers(0, 40, 2) * 25
            h, w = rng.integers(0, 3) * 25, rng.integers(0, 6) * 25
        else:
            y0, x0 = rng.uniform(0, 3000, 2)
            h, w = rng.uniform(0, 60), rng.uniform(0, 900)
        out.append((slice(y0, y0 + h), slice(x0, x0 + w)))
    if n > 3:        # точні дублікати меж — окремий випадок `w == u`
        out[1] = (slice(out[0][0].start, out[0][0].stop),
                  slice(out[0][1].start, out[0][1].stop))
    return out


def check_random(seed: int = 7, rounds: int = 60) -> int:
    from kraken.lib.segmentation import _reading_order as orig

    orig = getattr(sys.modules["kraken.lib.segmentation"], "_reading_order_orig", orig)
    rng = np.random.default_rng(seed)
    bad = 0
    for r in range(rounds):
        n = int(rng.integers(0, 90))
        lines = _random_lines(rng, n, grid=bool(r % 2))
        for direction in ("lr", "rl"):
            a, b = orig(lines, direction), reading_order_fast(lines, direction)
            if a.shape != b.shape or not np.array_equal(a, b):
                bad += 1
                print(f"❌ випадковий набір №{r} ({n} рядків, {direction}): розбіжність")
    print(f"випадкові набори: {rounds * 2 - bad}/{rounds * 2} збіглися")
    return bad


def check_pages(folder: Path, limit: int) -> int:
    from kraken import blla
    from kraken.lib import segmentation as kseg
    from PIL import Image

    orig = getattr(kseg, "_reading_order_orig", kseg._reading_order)
    bad = 0
    for frame in sorted(folder.glob("*.jpg"))[:limit]:
        seg = blla.segment(Image.open(frame))
        lines = seg.lines
        kseg._reading_order = orig
        t = time.perf_counter()
        a = kseg.polygonal_reading_order(lines)
        t_orig = time.perf_counter() - t
        kseg._reading_order = reading_order_fast
        t = time.perf_counter()
        b = kseg.polygonal_reading_order(lines)
        t_fast = time.perf_counter() - t
        kseg._reading_order = orig
        same = list(a) == list(b)
        bad += not same
        print(f"{'✅' if same else '❌'} {frame.name}: {len(lines)} рядків · "
              f"оригінал {t_orig:.2f} с · швидкий {t_fast:.3f} с")
    return bad


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    bad = check_random()
    if len(sys.argv) > 2:
        bad += check_pages(Path(sys.argv[2]), limit)
    print("ВИХІД ТОЙ САМИЙ" if not bad else f"РОЗБІЖНОСТЕЙ: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
