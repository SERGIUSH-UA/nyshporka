"""Читання бланка поклітинно: ще один голос справи (`nysh read --form-cells`).

Береться вже прочитана справа, чиї кадри лежать на диску. Для кожного кадра
`form_cells.find_grid` знаходить клітинки друкованого бланка, кожну клітинку
основна модель читає як ОДИН рядок, і результат лягає в сестринську теку
`<прогін>-cells` за тією ж конвенцією, що й голоси `--with`:

    <стор>.txt          рядок на клітинку (порожні клітинки — порожні рядки)
    <стор>.lines.json   `size` (розмір повернутого кадру), `boxes` (рамки кропів),
                        `cells` (адреса кожного кропа: сторінка розвороту, рядок
                        таблиці, колонка, підрядок) і `parts` (межі сторінок і кут)
    _htr_meta.json      case_key, case_dir, model (`<ваги>+cells`), engine, voice

🔴 Рамки лежать у координатах кадру, повернутого на `orient` з мети основного
прогону, — так само, як у раннера; `nysh text crop` повертає кадр тим самим кутом.
Сторінки без сітки (книжкові) не дають ні `.txt`, ні `.lines.json`: порожній
файл читався б як «прочитано, тексту немає». Скільки сторінок із сіткою і без —
друкується підсумком і лягає в мету (`form_cells`).

⚠ Запускати під середовищем рушіїв (як `runner.py`): тут немає імпортів
`nyshporka`, потрібні torch і ваги.

    <python рушіїв> cells_read.py --case-dir <кадри> --out-dir <прогін>-cells \\
        --model <ваги>.pt --base-run <прогін>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import form_cells as FC  # noqa: E402
from PIL import Image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
#: Суфікс теки голосу й мітка в `model` мети (`<ваги>+cells`), як `+diak_v4` у голосів.
VOICE_TAG = "cells"


def parse_ranges(spec: str, n: int) -> set[int]:
    """«1-50,60» → порядкові номери кадрів (з 1); порожньо — усі."""
    if not spec.strip():
        return set(range(1, n + 1))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.update(range(lo, hi + 1))
    return out


def rotated(im: Image.Image, orient: int) -> Image.Image:
    """Поворот проти годинникової, як `runner.rotated` (дзеркало: тут без раннера)."""
    return {90: lambda: im.transpose(Image.Transpose.ROTATE_90),
            180: lambda: im.transpose(Image.Transpose.ROTATE_180),
            270: lambda: im.transpose(Image.Transpose.ROTATE_270)}.get(orient, lambda: im)()


def base_orient(base_run: Path | None) -> dict[str, int]:
    """Кут повороту кожного кадра з мети основного прогону (немає — 0°)."""
    if base_run is None:
        return {}
    try:
        meta = json.loads((base_run / "_htr_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pages = meta.get("pages") if isinstance(meta, dict) else None
    out: dict[str, int] = {}
    for name, info in (pages or {}).items():
        if isinstance(info, dict):
            out[Path(name).stem] = int(info.get("orient") or 0)
    return out


def build_meta(*, case_dir: Path, case_key: str, model: str, engine: str, script: str,
               device: str, base_run: str, started: str, pages: dict[str, Any],
               with_grid: int, without_grid: int,
               no_grid: list[str] | None = None) -> dict[str, Any]:
    return {
        "version": 1, "case_dir": str(case_dir).replace("\\", "/"),
        "case_key": case_key, "model": f"{model}+{VOICE_TAG}", "engine": engine,
        "script": script, "device": device,
        "voice": VOICE_TAG, "cells_of": base_run,
        # Сторінки без сітки txt не мають: повноту голосу рахувати за цим переліком.
        "form_cells": {"pages_with_grid": with_grid, "pages_without_grid": without_grid,
                       "no_grid": sorted(no_grid or [])},
        "started": started, "updated": datetime.now().isoformat(timespec="seconds"),
        "pages": pages, "done": len(pages), "failed": []}


def _decode(rec: Any, engine: str, crops: list[Any], device: str, batch: int,
            runner: Any) -> list[str]:
    """Тексти кропів у порядку `crops`: рушій — за вагами, як у раннері."""
    if engine == "kraken":
        return list(runner.kraken_decode_crops(rec, crops, runner.VOICE_BATCH))
    if engine == "ppocr":
        return list(runner.pp_decode_crops(rec, crops))
    import numpy as np
    import torch
    from pysar_lines_infer import clean_pysar_text

    model, (h, w) = rec
    tensors = []
    for c in crops:
        arr = np.asarray(c.convert("RGB").resize((w, h), Image.Resampling.LANCZOS),
                         dtype="float32") / 255.0
        tensors.append(torch.from_numpy((arr - 0.5) / 0.5).permute(2, 0, 1))
    got = runner._parseq_decode(model, tensors, device, batch)
    return [clean_pysar_text(str(t or "")) for t, _ in got]


#: Позначка «на цій сторінці сітки немає»: сторінка голосом опрацьована, тексту
#: в неї немає. Окремий файл на сторінку, а не список у меті: шарди пишуть
#: сторінки паралельно, і спільний список у меті вони б затирали одне одному.
NOGRID = ".nogrid"
#: Позначка «клітинки сторінки не прочитались» (виняток рушія): сторінка не
#: зупиняє справу, а причина лишається на диску й у меті голосу.
FAILED = ".cellsfail"


def read_page(im: Image.Image, decode: Any) -> tuple[list[str], dict[str, Any]] | None:
    """Сторінка (уже повернута на `orient`) → тексти кропів і геометрія.
    `None` — сітки немає."""
    grid = FC.find_grid(im)
    if not grid.found:
        return None
    texts = [unicodedata.normalize("NFC", (t or "").replace("\n", " ").strip())
             for t in decode(grid.images(im))]
    if len(texts) != len(grid.crops):
        raise RuntimeError(f"рушій віддав {len(texts)} текстів на {len(grid.crops)} клітинок")
    geo = {"size": [im.width, im.height],
           "boxes": [list(b) for b in grid.crops],
           "cells": [list(a) for a in grid.addr],
           "parts": [[p.x0, p.x1, p.angle] for p in grid.parts]}
    return texts, geo


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_page(out_dir: Path, stem: str, got: tuple[list[str], dict[str, Any]] | None,
               *, orient: int = 0) -> int:
    """Записати сторінку голосу: текст і рамки, або позначку «сітки немає».
    Повертає число клітинок."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mark = out_dir / f"{stem}{NOGRID}"
    if got is None:
        for f in (out_dir / f"{stem}.txt", out_dir / f"{stem}.lines.json"):
            f.unlink(missing_ok=True)
        _write(mark, "")
        return 0
    texts, geo = got
    _write(out_dir / f"{stem}.lines.json", json.dumps({**geo, "orient": orient}))
    _write(out_dir / f"{stem}.txt", "\n".join(texts) + "\n")
    mark.unlink(missing_ok=True)
    return len(texts)


def write_failed(out_dir: Path, stem: str, reason: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / f"{stem}{FAILED}", reason + "\n")


def page_done(out_dir: Path, stem: str) -> bool:
    """Чи опрацьована сторінка голосом клітинок (є текст або позначка).
    🔴 Дзеркало — `runner.CELLS_DONE`: раннер цього модуля для повноти не імпортує."""
    return any((out_dir / f"{stem}{suf}").exists() for suf in (".txt", NOGRID, FAILED))


def finish(out_dir: Path, *, names: dict[str, str] | None = None, started: str = "",
           **meta_args: Any) -> dict[str, Any]:
    """Мета голосу — з диска: сторінки з текстом і сторінки без сітки.

    `names` — stem → ім'я кадру (з розширенням), як у меті основного прогону.
    """
    names = names or {}
    pages: dict[str, dict[str, Any]] = {}
    for f in sorted(out_dir.glob("*.txt")):
        body = f.read_text(encoding="utf-8").splitlines()
        try:
            geo = json.loads((out_dir / f"{f.stem}.lines.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            geo = {}
        pages[names.get(f.stem, f"{f.stem}.jpg")] = {
            "orient": int(geo.get("orient") or 0), "detector": "form-cells",
            "retried": False, "guarded": False, "lines": len(body),
            "skew": [p[2] for p in geo.get("parts") or []],
            "chars": sum(len(t) for t in body), "conf": None, "sec": None}
    def listed(suffix: str) -> list[str]:
        return sorted(names.get(m.name[:-len(suffix)], m.name[:-len(suffix)] + ".jpg")
                      for m in out_dir.glob(f"*{suffix}"))

    no_grid = listed(NOGRID)
    meta = build_meta(started=started or datetime.now().isoformat(timespec="seconds"),
                      pages=pages, with_grid=len(pages), without_grid=len(no_grid),
                      no_grid=no_grid, **meta_args)
    failed = listed(FAILED)
    if failed:
        meta["form_cells"]["failed"] = failed
    _write(out_dir / "_htr_meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def process(frames: list[Path], out_dir: Path, decode: Any, *, orient_of: dict[str, int],
            want: set[int], meta_args: dict[str, Any], say: Any = print) -> dict[str, Any]:
    """Кадри → клітинки → тексти → файли голосу. `decode(crops) -> [текст]`.

    Без torch і ваг: розпізнавач приходить викликом, тож усе, крім нього, можна
    довести тестом на вигаданому бланку.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    n_cells = 0
    t0 = time.time()
    for i, src in enumerate(frames, 1):
        if i not in want:
            continue
        orient = orient_of.get(src.stem, 0)
        with Image.open(src) as raw:
            im = rotated(raw.convert("RGB"), orient)
        got = read_page(im, decode)
        k = write_page(out_dir, src.stem, got, orient=orient)
        n_cells += k
        say(f"[cells] {i}/{len(frames)} {src.name}: "
            + (f"{k} клітинок" if got else "сітки немає"))
    meta = finish(out_dir, names={f.stem: f.name for f in frames}, started=started,
                  **meta_args)
    fc = meta["form_cells"]
    say(f"[cells] готово: сторінок із сіткою {fc['pages_with_grid']}, без сітки "
        f"{fc['pages_without_grid']}, клітинок {n_cells} за {time.time() - t0:.0f} с → {out_dir}")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--base-run", type=Path, default=None,
                    help="тека основного прогону: звідти кути повороту кадрів")
    ap.add_argument("--case-key", default="")
    ap.add_argument("--script", default="")
    ap.add_argument("--pages", default="", help="порядкові номери кадрів: 1-50,60")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    import runner as R
    import torch

    frames = sorted(p for p in args.case_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in IMG_EXT)
    if not frames:
        raise SystemExit(f"[cells] у {args.case_dir} немає кадрів")
    device = args.device if torch.cuda.is_available() else "cpu"
    engine = R.detect_engine(str(args.model))
    rec = R.load_recognizer(str(args.model), engine, device)
    process(
        frames, args.out_dir,
        lambda crops: _decode(rec, engine, crops, device, args.batch, R),
        orient_of=base_orient(args.base_run), want=parse_ranges(args.pages, len(frames)),
        meta_args=dict(
            case_dir=args.case_dir, case_key=args.case_key, model=args.model.name,
            engine=engine, script=args.script or R.model_script(str(args.model), engine),
            device=device, base_run=args.base_run.name if args.base_run else ""),
        say=lambda line: print(line, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
