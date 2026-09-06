"""Кропи рядків сторінки — ТІ САМІ, що бачив рушій під час прогону.

Гість середовища рушіїв: запускається інтерпретатором `.venv` рушіїв, де є
kraken і PIL, і не імпортує пакет. Раннер прогону вантажиться за шляхом як
модуль — щоб вирізка йшла тим самим `extract_polygons` (з випрямленням
рядка), що й на інференсі. Кроп для трену, вирізаний інакше, ніж кроп на
читанні, — це модель, яку вчать на одному, а питають про інше.

Приймач — не ключ кешу, а збіг РАМОК: кеш сегментації читається без звірки
параметрів, зате рамки, які він дає після фільтра ширини, мусять збігтися з
`<стор>.lines.json` прогону поштучно. Збіглись — кропи доведено ті самі, що
дали текст; не збіглись — гість каже про це, і пакет ріже полігоном сам.

    <python рушіїв> cut_runner.py --runner <htr/runner.py> --image <скан>
        --orient 0 --seg <stem>.o0.seg.json.gz [--seg …] --lines-json <stem>.lines.json
        --out <тека сторінки>

Друкує один рядок JSON: {"ok": true, "n": 41, "source": "seg_cache", "seg": "<файл>"}
або {"ok": false, "why": "…"}.
"""
import argparse
import gzip
import importlib.util
import json
import sys
from pathlib import Path


def _load_runner(path):
    spec = importlib.util.spec_from_file_location("nysh_htr_runner", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nysh_htr_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _boxes_equal(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x is None or y is None:
            if x is not y:
                return False
            continue
        if [int(v) for v in x[:4]] != [int(v) for v in y[:4]]:
            return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runner", required=True, type=Path)
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--orient", type=int, default=0)
    ap.add_argument("--seg", action="append", default=[], type=Path,
                    help="кандидати кешу сегментації, у порядку спроб")
    ap.add_argument("--lines-json", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    from PIL import Image

    R = _load_runner(args.runner)
    want = json.loads(args.lines_json.read_text(encoding="utf-8"))
    want_boxes = want.get("boxes") or []
    if not want_boxes:
        print(json.dumps({"ok": False, "why": "у .lines.json немає рамок"}))
        return 2

    with Image.open(args.image) as raw:
        im = raw.convert("RGB")
    im = R.rotated(im, args.orient)
    size = [im.width, im.height]
    if want.get("size") and [int(v) for v in want["size"]] != size:
        print(json.dumps({"ok": False,
                          "why": f"розмір зображення {size} не збігається з "
                                 f"розміром у прогоні {want['size']}"}))
        return 2

    tried = []
    for f in args.seg:
        if not f.is_file():
            continue
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                blob = json.load(fh)
            seg = R._seg_from_blob(blob["seg"])
        except Exception as exc:  # noqa: BLE001 — кандидат, не вирок
            tried.append(f"{f.name}: {type(exc).__name__}")
            continue
        crops = R._line_crops(im, seg)
        boxes = list(getattr(R._line_crops, "boxes", []) or [])
        if not _boxes_equal(boxes, want_boxes):
            tried.append(f"{f.name}: рамок {len(boxes)} проти {len(want_boxes)} "
                         f"у прогоні, або не ті")
            continue
        args.out.mkdir(parents=True, exist_ok=True)
        n = 0
        for i, crop in enumerate(crops):
            crop.save(args.out / f"line_{i:03d}.png")
            n += 1
        print(json.dumps({"ok": True, "n": n, "source": "seg_cache",
                          "seg": str(f), "size": size}, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "why": "жоден кеш сегментації не дав тих самих "
                                          "рамок: " + ("; ".join(tried) or "кешу немає")},
                     ensure_ascii=False))
    return 3


if __name__ == "__main__":
    sys.exit(main())
