"""Звірка `fast_seam.vec_lines_fast` з оригіналом Kraken на реальних сторінках.

Обгортка кличе обидві версії `blla.vec_lines` на ТИХ САМИХ аргументах (теплова
карта мережі одна, тож недетермінізм карти звірки не зачіпає) і порівнює все,
що йде далі в конвеєр: кількість і порядок рядків, тип, базову лінію й контур
до пікселя. Інші патчі сегментації (fast_geom, fast_order, sato на карті)
стоять, як у бойовому прогоні.

    <venv>/bin/python -m nyshporka.htr.patches.fast_seam_verify <тека справи> [N]

🔴 Тека справи обов'язкова: шов залежить від почерку, щільності й формуляра.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATS = {"pages": 0, "lines": 0, "same": 0, "diff": 0, "t_orig": 0.0, "t_fast": 0.0}


def _key(lines: list[dict]) -> list[tuple]:
    return [(ln["tags"]["type"][0]["type"],
             [tuple(map(int, p)) for p in ln["baseline"]],
             [tuple(map(int, p)) for p in ln["boundary"]]) for ln in lines]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    case = Path(sys.argv[1])
    if not case.is_dir():
        print(f"✗ немає теки справи: {case}", file=sys.stderr)
        return 2
    n_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    from kraken import blla
    from kraken.kraken import SEGMENTATION_DEFAULT_MODEL
    from kraken.lib import vgsl

    import fast_geom
    import fast_order
    import fast_seam
    from gpu_sato import install_gpu_sato

    fast_geom.install()
    fast_order.install()
    install_gpu_sato((1, 3), device="cuda:0")
    orig = blla.vec_lines
    blla.polygonize_page = fast_seam.polygonize_page
    blla._vec_lines_orig = orig
    diffs: list[str] = []

    def both(*a, **kw):
        t0 = time.perf_counter()
        ra = orig(*a, **kw)
        t1 = time.perf_counter()
        rb = fast_seam.vec_lines_fast(*a, **kw)
        t2 = time.perf_counter()
        STATS["t_orig"] += t1 - t0
        STATS["t_fast"] += t2 - t1
        ka, kb = _key(ra), _key(rb)
        STATS["lines"] += len(ka)
        if len(ka) != len(kb):
            diffs.append(f"рядків {len(ka)} ≠ {len(kb)}")
            STATS["diff"] += max(len(ka), len(kb))
        else:
            for i, (x, y) in enumerate(zip(ka, kb)):
                if x == y:
                    STATS["same"] += 1
                else:
                    STATS["diff"] += 1
                    diffs.append(f"рядок {i}: контур {len(x[2])} ≠ {len(y[2])} точок")
        return ra                        # у конвеєр іде оригінал

    blla.vec_lines = both
    seg_model = vgsl.TorchVGSLModel.load_model(SEGMENTATION_DEFAULT_MODEL)
    pages = sorted(p for p in case.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not pages:
        print(f"✗ у теці немає зображень: {case}", file=sys.stderr)
        return 2
    step = max(1, len(pages) // n_pages)
    for p in pages[::step][:n_pages]:
        with Image.open(p) as raw:
            im = raw.convert("RGB")
        n_diff = STATS["diff"]
        blla.segment(im, model=seg_model, device="cuda:0")
        STATS["pages"] += 1
        print(f"  {p.name}: рядків разом {STATS['lines']}, "
              f"розбіжностей на сторінці {STATS['diff'] - n_diff}", flush=True)

    s = STATS
    print(f"\nсторінок {s['pages']}, рядків {s['lines']}: збігів {s['same']}, "
          f"розбіжностей {s['diff']}, відступів на оригінал {fast_seam.FALLBACKS['vec_lines']}")
    for d in diffs[:10]:
        print("  ", d)
    print(f"vec_lines: оригінал {s['t_orig']:.1f} с → пакет {s['t_fast']:.1f} с "
          f"= ×{s['t_orig'] / max(s['t_fast'], 1e-9):.2f}")
    cv = fast_seam.CARVE
    print(f"пакетів {cv['chunks']}, доповнення {cv['padded'] / max(cv['real'], 1):.2f}× "
          "від справжніх латок")
    ok = s["diff"] == 0 and s["lines"] > 0 and not fast_seam.FALLBACKS["vec_lines"]
    print("\n" + ("✓ еквівалентно" if ok else "✗ Є розбіжності — не вмикати"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
