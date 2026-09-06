"""Прогнози Писаря на кропах holdout — гість середовища рушіїв.

Один запуск = один чекпойнт × один перелік кропів. Вантажить
`htr/pysar_lines_infer.py` за шляхом (той самий код, що читає справи, тож
прогноз тут — те, що реально ляже в текст справи), і пише JSON із прогнозами в
тому ж порядку, що й вхідний перелік.

    <python рушіїв> eval_runner.py --infer <pysar_lines_infer.py> --ckpt <ваги.pt>
        --jobs <jobs.json> --out <preds.json> [--device cuda:0] [--batch 32]

`jobs.json`: {"crops": ["<шлях>", …]}; `preds.json`: {"preds": ["…", …]}.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--infer", required=True, type=Path)
    ap.add_argument("--ckpt", required=True, type=Path)
    ap.add_argument("--jobs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--batch", type=int, default=32)
    a = ap.parse_args(argv)

    import numpy as np
    import torch
    from PIL import Image

    infer = _load(a.infer, "nysh_pysar_infer")
    crops = [Path(p) for p in json.loads(a.jobs.read_text(encoding="utf-8"))["crops"]]
    device = a.device if torch.cuda.is_available() else "cpu"
    model, (h, w) = infer.load_pysar(a.ckpt, device)
    preds = []
    for i in range(0, len(crops), a.batch):
        tens = []
        for p in crops[i:i + a.batch]:
            try:
                im = Image.open(p).convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
            except Exception:  # noqa: BLE001 — битий кроп не валить замір
                im = Image.new("RGB", (w, h), "white")
            arr = (np.asarray(im, dtype="float32") / 255.0 - 0.5) / 0.5
            tens.append(torch.from_numpy(arr).permute(2, 0, 1))
        with torch.no_grad():
            probs = model(torch.stack(tens).to(device)).softmax(-1)
        txts, _ = model.tokenizer.decode(probs)
        preds.extend(infer.clean_pysar_text(t) for t in txts)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"ckpt": str(a.ckpt), "n": len(preds), "preds": preds},
                                ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "n": len(preds)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
