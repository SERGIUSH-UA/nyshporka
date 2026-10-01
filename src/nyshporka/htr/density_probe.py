"""Щільність справи наперед: рядків на сторінку з вибірки кадрів — лише сегментація.

Гість середовища рушіїв (як `runner.py`): пакета `nyshporka` тут немає, відповідь
— останній рядок stdout у JSON.

Навіщо. Темп читання (і отже вибір машини, стеля часу, ціна тисячі сторінок)
рахується від рядків на сторінку: час сторінки ≈ стала + рядки, і більше від
матеріалу майже нічого не залежить (заміри 01.10.2026: 6 справ, 4 типи
документів). Перший захід справи щільності не знав і брав припущені 60 рядків,
а реальна буває від 18 (сповідки) до 250 (щільні формуляри) — помилка вдвічі-
втричі в обидва боки. Вибірка з 40 кадрів дає ±4–7 % на рівномірних книгах і
±30 % на збірних, де щільні блоки йдуть підряд; ~1 хв на карті.

Як. Лише мережа сегментації й векторизація базових ліній: контури (найдорожча
частина сегментації) для лічби рядків не потрібні. Ті самі патчі, що в
раннері. Кадри-смуги (етикетка плівки, корінець; ш/в > 2.5) не сторінки — не
рахуються. Перші й останні три кадри — обкладинки — теж.

    <інтерпретатор рушіїв> density_probe.py <тека кадрів> [--sample 40] [--device cuda:0]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

FRAME_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
#: Ширше за висоту більше ніж стільки — не сторінка (етикетка, смуга).
MAX_ASPECT = 2.5
#: Скільки кадрів брати без карти: сегментація на процесорі в рази повільніша.
CPU_SAMPLE = 12
#: Стеля кінців скелета — як у перепуску раннера: густа сторінка рахується
#: повністю, а не обрізаною на 200 рядках.
MAX_ENDPOINTS = 1600


def sample_frames(case_dir: Path, n: int) -> list[Path]:
    """Рівномірна вибірка без обкладинок, у порядку справи."""
    files = sorted(p for p in case_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in FRAME_EXT)
    body = files[3:-3] if len(files) > 20 else files
    if len(body) <= n:
        return body
    step = len(body) / n
    return [body[int(i * step)] for i in range(n)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("case_dir")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--device", default="")
    a = ap.parse_args()
    t0 = time.perf_counter()
    try:
        from importlib import resources

        import torch
        from kraken import blla
        from kraken.lib import segmentation as kseg
        from kraken.lib import vgsl
        from PIL import Image

        sys.path.insert(0, str(Path(__file__).resolve().parent / "patches"))
        import fast_geom
        import seg_resize

        fast_geom.install()
        seg_resize.install()
        cuda = torch.cuda.is_available()
        device = a.device or ("cuda:0" if cuda else "cpu")
        if device.startswith("cuda"):
            from gpu_sato import install_gpu_sato
            install_gpu_sato((1, 3), device=device)
        n = a.sample if device.startswith("cuda") else min(a.sample, CPU_SAMPLE)
        model = vgsl.TorchVGSLModel.load_model(resources.files("kraken").joinpath("blla.mlmodel"))
        counts: list[int] = []
        for f in sample_frames(Path(a.case_dir), n):
            with Image.open(f) as raw:
                w, h = raw.size
                if not h or w / h > MAX_ASPECT:
                    continue
                im = raw.convert("RGB")
            rets = blla.compute_segmentation_map(im, None, model, device)
            cls = rets["cls_map"]
            st_sep = cls["aux"]["_start_separator"]
            end_sep = cls["aux"]["_end_separator"]
            counts.append(sum(
                len(kseg.vectorize_lines(rets["heatmap"][(st_sep, end_sep, idx), :, :],
                                         text_direction="horizontal",
                                         max_endpoints=MAX_ENDPOINTS))
                for idx in cls["baselines"].values()))
    except Exception as exc:  # відповідь мусить бути завжди — хост чекає JSON
        print(json.dumps({"ok": False, "why": f"{type(exc).__name__}: {exc}"[:300]}))
        return 1
    if not counts:
        print(json.dumps({"ok": False, "why": "у вибірці немає сторінок"}))
        return 1
    print(json.dumps({"ok": True, "n": len(counts),
                      "lines_mean": round(statistics.mean(counts), 1),
                      "lines_median": float(statistics.median(counts)),
                      "device": device, "sec": round(time.perf_counter() - t0, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
