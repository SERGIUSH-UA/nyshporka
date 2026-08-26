"""Прогін писаря (PARSeq, формат Hukyl) по готових кропах рядків.

Локальний двійник GPU-джоби ``htr_lines_eval`` (engine=parseq) — щоб не гнати
кропи в хмару заради десятка сторінок. Вхід і вихід ті самі, що в
``kraken_lines_infer.py``, тож результат лягає у спільний протокол
``htr_phrase_recall.py`` і в консенсус:

    вхід   <lines>/lines/<page>/line_NNN.png
    вихід  <out>/<page>.txt   (рядок на seg-індекс, діри = порожні рядки)

Навіщо окремо від Скриби: Скриба — kraken/CTC, тренована на латинці ф.792, і
кириличний рукопис їй не по зубах. Писар — PARSeq, тюнений на RUKOPYS, вантажиться
strhub'ом, не kraken'ом (memory ``parseq-train-job-and-cyrillic-consensus``).

⚠ Запускати під середовищем рушіїв (py3.11 + torch + strhub/timm/nltk), не тим
інтерпретатором, у якому стоїть пакет — тому тут немає імпортів `nyshporka`:

    <python середовища рушіїв> pysar_lines_infer.py \\
        --model <ваги Писаря>.pt \\
        --lines <тека з вирізками рядків> \\
        --out reports/htr/<назва прогону>
"""
from __future__ import annotations

import argparse
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

# 🔴 Символи, яких у рукописі XIX ст. не буває фізично, — службові маркери
# конфлікту з LLM-злиття (`‹26|20›`). Одного разу вони протекли у трен-корпус
# (16 рядків із 724 псевдо-міток, Писар v5b) і осіли в алфавіті моделі, тож
# вона їх відтворює в декоді: «гранямъ родственникъ ‹1|›», «го в 8052›».
# Зрізаємо саме символи, а не парну форму ‹A|B›: модель ліпить маркер зламаним,
# і регулярка на пару його не бачить. У фаззі-пошуку по прізвищах це шум.
_JUNK = re.compile(r"[‹›|]")


def clean_pysar_text(s: str) -> str:
    """Прибрати службове сміття з декоду й звести пробіли."""
    return " ".join(_JUNK.sub(" ", s).split())


def load_pysar(ckpt: Path, device: str) -> Any:
    """best.pt (model_state+charset+config) + код baudm/parseq (strhub).

    Гіперпараметри архітектури беруться з чекпойнта, а не з дефолтів PARSeq —
    інакше матриці не зійдуться і `load_state_dict` тихо лишить половину ваг
    випадковими.
    """
    import torch
    from strhub.models.parseq.system import PARSeq

    payload = torch.load(str(ckpt), map_location="cpu", weights_only=True)
    cfg, charset = payload["config"], payload["charset"]
    kwargs = dict(
        charset_train=charset, charset_test=charset,
        max_label_length=int(cfg.get("max_label_length", 100)),
        batch_size=1, lr=1e-4, warmup_pct=0.1, weight_decay=0.0,
        img_size=[int(cfg.get("img_height", 48)), int(cfg.get("img_width", 512))],
        patch_size=cfg.get("patch_size", [8, 8]),
        embed_dim=int(cfg.get("embed_dim", 384)),
        enc_num_heads=int(cfg.get("enc_num_heads", 6)),
        enc_mlp_ratio=int(cfg.get("enc_mlp_ratio", 4)),
        enc_depth=int(cfg.get("enc_depth", 12)),
        dec_num_heads=int(cfg.get("dec_num_heads", 12)),
        dec_mlp_ratio=int(cfg.get("dec_mlp_ratio", 4)),
        dec_depth=int(cfg.get("dec_depth", 1)),
        perm_num=6, perm_forward=True, perm_mirrored=True,
        decode_ar=bool(cfg.get("decode_ar", True)),
        refine_iters=int(cfg.get("refine_iters", 1)),
        dropout=float(cfg.get("dropout", 0.1)),
    )
    if isinstance(kwargs["patch_size"], int):
        kwargs["patch_size"] = [kwargs["patch_size"]] * 2

    model = PARSeq(**kwargs)
    sd = payload["model_state"]
    keys = set(model.state_dict())
    variants = (sd,
                {"model." + k: v for k, v in sd.items()},
                {k[len("model."):]: v for k, v in sd.items() if k.startswith("model.")})
    sd = max(variants, key=lambda v: len(set(v) & keys))
    missing, unexpected = model.load_state_dict(sd, strict=False)
    print(f"[pysar] ваг збіглося={len(set(sd) & keys)} "
          f"missing={len(missing)} unexpected={len(unexpected)} "
          f"charset={len(charset)} симв.", flush=True)
    if len(missing) > len(keys) // 2:
        raise SystemExit(f"[pysar] state_dict не той: {missing[:5]}")
    return model.to(device).eval(), tuple(kwargs["img_size"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--lines", required=True, type=Path,
                    help="тека прогону kraken_lines_cut (усередині має бути lines/)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pages", default="", help="кома-список сторінок (порожньо = всі)")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--case-dir", default="",
                    help="тека сканів справи — лягає в _htr_meta.json, звідти "
                         "library/pagestore впізнають, до якої справи прогін")
    args = ap.parse_args()

    import numpy as np
    import torch
    from PIL import Image

    root = args.lines / "lines" if (args.lines / "lines").is_dir() else args.lines
    want = {p.strip() for p in args.pages.split(",") if p.strip()}
    pages = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))
    if want:
        pages = [p for p in pages if p.name in want]
    if not pages:
        raise SystemExit(f"[pysar] нема сторінок під {root}")

    device = args.device if torch.cuda.is_available() else "cpu"
    model, (h, w) = load_pysar(args.model, device)
    args.out.mkdir(parents=True, exist_ok=True)

    t0, total = time.time(), 0
    for i, page in enumerate(pages, 1):
        crops = sorted(page.glob("line_*.png"))
        if not crops:
            continue
        tensors = []
        for c in crops:
            im = Image.open(c).convert("RGB").resize((w, h), Image.Resampling.LANCZOS)
            arr = (np.asarray(im, dtype="float32") / 255.0 - 0.5) / 0.5
            tensors.append(torch.from_numpy(arr).permute(2, 0, 1))

        texts: list[str] = []
        for j in range(0, len(tensors), args.batch):
            x = torch.stack(tensors[j:j + args.batch]).to(device)
            with torch.no_grad():
                probs = model(x).softmax(-1)
            preds, _ = model.tokenizer.decode(probs)
            texts.extend(clean_pysar_text(t) for t in preds)

        # 🔴 Рядок кладеться за номером З імені кропа, а не за позицією в списку.
        # Нарізка лишає діри (забракований сегмент не зберігається, але номер
        # з'їдається): у 00049 нема line_022, і позиційний запис зсував увесь
        # хвіст сторінки на +1 — декод діставався сусідньому рядку, а GT,
        # зібраний по номерах кропів, зіставлявся з чужим текстом.
        by_idx = {int(c.stem.split("_")[-1]): t
                  for c, t in zip(crops, texts, strict=True)}
        # NFC — щоб combining-діакритика не ламала fuzzy-пошук (як у Скриби)
        body = "\n".join(unicodedata.normalize("NFC", by_idx.get(i, ""))
                         for i in range(max(by_idx) + 1))
        (args.out / f"{page.name}.txt").write_text(body, encoding="utf-8")
        total += len(crops)
        print(f"[pysar] {i}/{len(pages)} {page.name}: {len(crops)} рядків", flush=True)

    # `_htr_meta.json` — без неї htr_store.list_cases() прогону не бачить, і будь-який
    # пошук (Нишпорка, htr_sweep, htr_store.search) мовчки віддає нуль хітів,
    # хоча тексти на диску є. Витрачено 20 хв на діагностику — тому пишемо завжди.
    import json
    from datetime import datetime
    meta_pages = {}
    for f in sorted(args.out.glob("*.txt")):
        body = f.read_text(encoding="utf-8").splitlines()
        meta_pages[f.stem + ".jpg"] = {
            "orient": 0, "detector": "n/a", "retried": False, "guarded": False,
            "lines": len(body), "chars": sum(len(x) for x in body),
            "conf": None, "sec": None}
    now = datetime.now().isoformat(timespec="seconds")
    (args.out / "_htr_meta.json").write_text(json.dumps({
        "version": 1, "case_dir": str(args.case_dir or "").replace("\\", "/"),
        "model": args.model.name, "device": device,
        "started": now, "updated": now,
        "pages": meta_pages, "done": len(meta_pages), "failed": [],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[pysar] готово: {total} кропів / {len(pages)} стор. "
          f"за {time.time() - t0:.0f} с → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
