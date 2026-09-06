"""Раннер трену Писаря — ВЕНДОРЕНА копія з gpurunner (584af2c).

🔴 Не редагувати руками: правки живуть у `tools/sync_train_runner.py` як
точні заміни, і `--check` там ловить дрейф від оригіналу. Гість середовища
рушіїв: жодного імпорту пакета (`tests/test_train_guest_isolated.py`).

Запуск: `<python рушіїв> parseq_train_runner.py --params <params.json>`;
`params.json` — словник `TrainParams.as_params()` плюс `input_root`,
`output_root`, `no_pip`, `progress_json`.
"""
"""PARSeq-S fine-tune на line-GT (кирилиця) — власний цикл поверх strhub.

Вхід /kaggle/input/**:
  * дані: ``*.tgz`` (розпаковуються) або готова тека з кропами + маніфестом
    ``gt.txt`` / ``gt_train.txt`` / ``gt_val.txt`` (TSV ``relpath<TAB>label``)
    або ``*.jsonl`` (``{"image": relpath, "text": label}``). Шляхи — відносно
    теки, де лежить сам маніфест.
  * базовий чекпойнт (за ``pretrained=local``): будь-який ``*.pt`` у форматі
    Hukyl {model_state, charset, config}.
Вихід /kaggle/working/ (на Modal — params["output_root"], див. _bind_roots):
  parseq_best.pt      — {model_state, charset, config} (формат Hukyl → одразу
                        їсться job'ом htr_lines_eval і нашим інференсом)
  parseq_ep<NN>.pt    — те саме, але ваги КОЖНОЇ епохи (``save_epochs``, ON).
                        Епоху обирає локальний прогін по повному holdout: val
                        малий і взятий із тих самих справ, що й train.
  parseq_last.pt      — повний стан для -p resume=true
  ptrain_summary.json — крива val (CER / exact) по епохах + charset-статистика
  ptrain.log          — повний лог трену

⚠ PL-цикл strhub НЕ використовується: ``validation_epoch_end`` викошено у
pytorch-lightning 2.x, тож Trainer мовчки не давав би val-метрик. Замість цього
викликаємо ``model.training_step`` як чисту функцію (``model.log`` заглушений)
і рахуємо валідацію самі — CER/exact на нашому домені.
⚠ БЕЗ `from __future__ import annotations` — код інжектиться після PARAMS.
"""
import json
import math
import os
import random
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path


def _utc_iso():
    # nyshporka: у gpurunner приходить із _common.py, тут — на місці.
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

KAGGLE_INPUT = Path("/kaggle/input")
KAGGLE_WORKING = Path("/kaggle/working")
EXTRACT = Path("/tmp/ptrain_input")

MIN_W, MIN_H = 32, 10  # синхронно з trocr_lines / htr_lines_eval
MANIFEST_TSV = ("gt.txt", "gt_train.txt", "gt_val.txt", "train_gt.txt", "val_gt.txt")

_LOG_LINES = []
_LOG_FH = [None]  # лениво відкритий дескриптор ptrain.log


def _log(msg):
    line = f"[ptrain] {msg}"
    _LOG_LINES.append(line)
    print(line, flush=True)
    # 🔴 Лог пишеться на диск ОДРАЗУ, а не в кінці main(). До 2026-08-02 він
    # збирався в _LOG_LINES і скидався одним write_text останнім рядком — тобто
    # будь-яке вбивство кернела (ліміт сесії, cancel, OOM) лишало нас без логу
    # взагалі, саме в тих випадках, коли він єдиний і потрібен. Kraken-гілка
    # весь цей час писала потоково; тепер поведінка однакова.
    try:
        if _LOG_FH[0] is None:
            KAGGLE_WORKING.mkdir(parents=True, exist_ok=True)
            _LOG_FH[0] = (KAGGLE_WORKING / "ptrain.log").open(
                "a", encoding="utf-8", errors="replace")
        _LOG_FH[0].write(line + "\n")
        _LOG_FH[0].flush()
    except Exception:
        pass  # лог — не привід валити трен


def _progress(params, epoch, epochs, rec):
    # nyshporka: машинний канал прогресу (`core.progress`): рядок із
    # префіксом і JSON, щоб застосунок бачив епоху, не розбираючи лог.
    if not params.get("progress_json"):
        return
    payload = {"v": 1, "phase": "train", "i": int(epoch), "n": int(epochs),
               "item": f"ep{int(epoch):02d}"}
    for k in ("val_cer", "val_exact", "train_loss", "sec"):
        if k in rec:
            payload[k] = rec[k]
    print("@@PROGRESS@@ " + json.dumps(payload, ensure_ascii=True), flush=True)


def _bind_roots(params):
    """Прив'язати корені вводу/виводу до бекенда.

    Kaggle, vast і lightning ЕМУЛЮЮТЬ ``/kaggle/{input,working}``, тож раннер
    писався під ці шляхи як під константи. Modal їх не емулює: він монтує
    вхідний том туди, де сказав ``modal_input_volumes`` (у нас ``/vol``), а
    забирає ЛИШЕ те, що лягло в ``params["output_root"]`` (``/mnt/outputs``).

    🔴 Без цієї прив'язки трен на Modal відпрацював би повністю і поклав ваги
    у ``/kaggle/working`` — теку, якої ніхто не читає. Тобто карта горить
    кілька годин, `fetch` віддає порожньо, і зовні це виглядає як «трен не
    зберіг ваги», а не як помилка шляху.
    """
    global KAGGLE_INPUT, KAGGLE_WORKING, EXTRACT
    out = params.get("output_root")
    if out:
        KAGGLE_WORKING = Path(out)
        # nyshporka: тека розпакування — під виходом, а не /tmp: на Windows
        # це C:\tmp, якого нема, а поруч із виходом вона й прибирається.
        EXTRACT = KAGGLE_WORKING / "_input"
    inp = params.get("input_root")
    if inp:
        KAGGLE_INPUT = Path(inp)
    if not KAGGLE_INPUT.is_dir():
        for cand in (Path("/vol"), Path("/mnt/input"), Path("/input")):
            if cand.is_dir():
                KAGGLE_INPUT = cand
                break
    _log(f"[roots] вхід={KAGGLE_INPUT} вихід={KAGGLE_WORKING}")


def _pip(*pkgs):
    _log(f"pip install {pkgs}…")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], check=True)


def _ensure_deps(params=None):
    # nyshporka: локально пакети ставить `nysh htr install`, і pip з-під
    # трену лише зіпсував би зібране середовище.
    if params and params.get("no_pip"):
        return
    try:
        import strhub  # noqa: F401
    except Exception:
        _pip("git+https://github.com/baudm/parseq.git", "pytorch-lightning",
             "timm", "nltk")


# ── вхідні дані ──────────────────────────────────────────────────────────────

def _extract_inputs():
    """Розпакувати всі *.tgz під /kaggle/input; повернути корені для пошуку.

    🔴 Системний `tar` замість `tarfile`. На корпусі з 86 тис. кропів Python-
    реалізація розпаковує помітно довше за C-шну, і цей час іде з того самого
    12-годинного вікна кернела, нічого не рахуючи. Fallback на `tarfile`
    лишається — бекенд може не мати `tar` у PATH.
    """
    roots = [KAGGLE_INPUT]
    tgzs = sorted(KAGGLE_INPUT.rglob("*.tgz")) + sorted(KAGGLE_INPUT.rglob("*.tar.gz"))
    if tgzs:
        EXTRACT.mkdir(parents=True, exist_ok=True)
        for t in tgzs:
            t0 = time.time()
            how = "tar"
            try:
                subprocess.run(["tar", "xzf", str(t), "-C", str(EXTRACT)], check=True)
            except Exception as exc:
                how = f"tarfile (tar не вийшов: {type(exc).__name__})"
                with tarfile.open(t) as tf:
                    tf.extractall(EXTRACT)
            _log(f"extracted {t.name} -> {EXTRACT} за {time.time() - t0:.0f}s ({how})")
        roots.insert(0, EXTRACT)
    return roots


def _read_manifest(path):
    """→ [(abs_image_path, label)]; шляхи відносно теки маніфесту."""
    base = path.parent
    items = []
    if path.suffix == ".jsonl":
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            rel = rec.get("image") or rec.get("path") or rec.get("file")
            txt = rec.get("text", rec.get("label", ""))
            if rel:
                items.append((base / rel, str(txt)))
        return items
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" not in raw:
            continue
        rel, _, txt = raw.partition("\t")
        rel = rel.strip()
        if rel:
            items.append((base / rel, txt.rstrip("\r\n")))
    return items


def _collect_manifests(roots):
    """{'train': [...], 'val': [...]} — val лише з явних val-маніфестів."""
    train, val = [], []
    seen = set()
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.resolve() in seen:
                continue
            name = p.name.lower()
            is_tsv = name in MANIFEST_TSV
            is_jsonl = p.suffix == ".jsonl"
            if not (is_tsv or is_jsonl):
                continue
            seen.add(p.resolve())
            items = _read_manifest(p)
            if not items:
                continue
            bucket = val if "val" in name else train
            bucket.extend(items)
            _log(f"manifest {p.name} ({p.parent.name}): {len(items)} рядків "
                 f"→ {'val' if bucket is val else 'train'}")
    return {"train": train, "val": val}


def _page_key(path):
    """Ключ сторінки для спліту — тека кропа (lines/<stem>/line_NNN.png)."""
    return path.parent.name or path.stem


def _split_by_page(items, val_frac, seed):
    """Детермінований спліт ПО СТОРІНКАХ (не по рядках — інакше витік GT)."""
    if val_frac <= 0:
        return items, []
    pages = sorted({_page_key(p) for p, _ in items})
    rng = random.Random(seed)
    rng.shuffle(pages)
    n_val = max(1, round(len(pages) * val_frac))
    val_pages = set(pages[:n_val])
    train = [(p, t) for p, t in items if _page_key(p) not in val_pages]
    val = [(p, t) for p, t in items if _page_key(p) in val_pages]
    return train, val


# ── charset ──────────────────────────────────────────────────────────────────

def _build_charset(base_charset, items, mode, extra, min_freq):
    """keep → базовий як є; extend → база ∪ extra ∪ часті символи з лейблів."""
    stats = {"base": len(base_charset), "added": "", "dropped_chars": 0}
    if mode == "keep":
        return base_charset, stats
    freq = {}
    for _, txt in items:
        for ch in txt:
            freq[ch] = freq.get(ch, 0) + 1
    have = set(base_charset)
    added = [c for c in extra if c not in have and not c.isspace()]
    have.update(added)
    for ch, n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        if ch in have or ch.isspace() or n < min_freq:
            continue
        added.append(ch)
        have.add(ch)
    charset = base_charset + "".join(added)
    stats["added"] = "".join(added)
    stats["dropped_chars"] = sum(
        n for ch, n in freq.items() if ch not in have and not ch.isspace()
    )
    return charset, stats


def _clean_label(txt, charset_set, max_len):
    """Викинути символи поза charset (tokenizer.encode інакше кидає KeyError)."""
    out = "".join(ch for ch in txt.strip() if ch in charset_set)
    return out[:max_len]


# ── модель ───────────────────────────────────────────────────────────────────

def _default_config():
    return {"img_height": 32, "img_width": 128, "max_label_length": 25,
            "patch_size": [4, 8], "embed_dim": 384, "enc_num_heads": 6,
            "enc_mlp_ratio": 4, "enc_depth": 12, "dec_num_heads": 12,
            "dec_mlp_ratio": 4, "dec_depth": 1, "decode_ar": True,
            "refine_iters": 1, "dropout": 0.1}


def _build_model(charset, cfg, lr, warmup_pct, weight_decay, batch):
    from strhub.models.parseq.system import PARSeq
    ps = cfg.get("patch_size", [4, 8])
    if isinstance(ps, int):
        ps = [ps, ps]
    model = PARSeq(
        charset_train=charset, charset_test=charset,
        max_label_length=int(cfg.get("max_label_length", 25)),
        batch_size=batch, lr=lr, warmup_pct=warmup_pct, weight_decay=weight_decay,
        img_size=[int(cfg.get("img_height", 32)), int(cfg.get("img_width", 128))],
        patch_size=list(ps),
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
    return model


def _strip_prefix(sd, model_keys):
    """Чекпойнти бувають з/без префікса 'model.' — беремо варіант із більшим перетином."""
    variants = (
        sd,
        {"model." + k: v for k, v in sd.items()},
        {k[len("model."):]: v for k, v in sd.items() if k.startswith("model.")},
    )
    return max(variants, key=lambda v: len(set(v) & model_keys))


def _find_key(keys, suffix):
    """Ключі чекпойнта бувають з префіксом ('model.head.weight') — шукаємо суфіксом."""
    for k in keys:
        if k == suffix or k.endswith("." + suffix):
            return k
    return None


def _remap_charset_weights(sd, old_charset, new_charset, model_sd):
    """Перенести head/text_embed по СИМВОЛАХ при розширенні charset.

    strhub Tokenizer: itos = ([EOS],) + charset + ([BOS], [PAD]).
      head      : out_features = len(tokenizer) - 2 = 1 + len(charset)
      text_embed: rows        = len(tokenizer)     = 3 + len(charset)
    Нові символи лишаються з ініціалізації нової моделі.
    """
    import torch
    stats = {"remapped": 0, "fresh": 0, "dropped": []}
    idx_old = {c: i for i, c in enumerate(old_charset)}
    stats["remapped"] = sum(1 for c in new_charset if c in idx_old)
    stats["fresh"] = len(new_charset) - stats["remapped"]

    def _rows(suffix, n_specials_tail):
        old_key = _find_key(sd.keys(), suffix)
        new_key = _find_key(model_sd.keys(), suffix)
        if old_key is None or new_key is None:
            return
        old_w, new_w = sd[old_key], model_sd[new_key]
        if old_w.shape == new_w.shape and old_charset == new_charset:
            return
        out = new_w.clone()
        out[0] = old_w[0]  # [EOS] — перший рядок в обох
        for i, ch in enumerate(new_charset):
            j = idx_old.get(ch)
            if j is not None and 1 + j < old_w.shape[0]:
                out[1 + i] = old_w[1 + j]
        for k in range(n_specials_tail):  # ([BOS],[PAD]) — з кінця
            if k < old_w.shape[0] and k < new_w.shape[0]:
                out[new_w.shape[0] - 1 - k] = old_w[old_w.shape[0] - 1 - k]
        sd[old_key] = out

    with torch.no_grad():
        _rows("head.weight", 0)  # [EOS] + charset, хвостових спецтокенів нема
        _rows("head.bias", 0)
        _rows("text_embed.embedding.weight", 2)  # + [BOS] + [PAD]
        # запобіжник: усе, що після ремапу не збігається формою, вчиться з нуля
        # (strict=False НЕ рятує від size mismatch — це RuntimeError, не missing)
        for k in list(sd.keys()):
            ref = model_sd.get(k)
            if ref is not None and tuple(ref.shape) != tuple(sd[k].shape):
                stats["dropped"].append(k)
                sd.pop(k)
    return sd, stats


RESUME_NAME = "parseq_last.pt"


def _fingerprint(params, charset, cfg, n_train):
    """Що мусить збігтись, щоб продовження трену було тим самим треном.

    Усе тут впливає або на форму ваг, або на розклад OneCycleLR: підмінити
    непомітно не можна нічого. Розбіжність — це помилка, а не привід «якось
    продовжити»: мовчазний рестарт lr-циклу посеред трену виглядав би як
    раптове погіршення моделі без жодного сліду в лозі.
    """
    return {
        "charset": charset,
        "img": [int(cfg["img_height"]), int(cfg["img_width"])],
        "max_label_length": int(cfg["max_label_length"]),
        "batch": int(params["batch"]),
        "epochs": int(params["epochs"]),
        "lr": float(params["lr"]),
        "warmup_pct": float(params["warmup_pct"]),
        "weight_decay": float(params["weight_decay"]),
        "lr_scale": str(params.get("lr_scale", "sqrt")),
        "n_train": int(n_train),
    }


def _find_resume(roots):
    """parseq_last.pt із входу (його треба залити окремим датасетом)."""
    hits = [p for r in roots for p in sorted(r.rglob(RESUME_NAME))]
    return hits[0] if hits else None


def _load_resume(params, roots):
    """→ payload повного стану або None."""
    import torch
    if not params.get("resume"):
        return None
    path = _find_resume(roots)
    if path is None:
        raise RuntimeError(
            f"resume=true, але {RESUME_NAME} не знайдено під {roots}. "
            f"Залий вихід попереднього прогону окремим датасетом "
            f"(-p resume_dataset=<slug>)")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    _log(f"resume <- {path} (епох пройдено {payload.get('epoch')}, "
         f"best_val_cer={payload.get('best_cer')})")
    return payload


def _load_pretrained(params, roots):
    """→ (state_dict|None, charset|None, config)."""
    import torch
    spec = params["pretrained"]
    if spec == "scratch":
        _log("pretrained=scratch — з нуля")
        return None, None, _default_config()
    if spec == "local":
        pts = [p for r in roots for p in sorted(r.rglob("*.pt"))]
        if not pts:
            raise RuntimeError(f"pretrained=local, але *.pt не знайдено під {roots}")
        ckpt = pts[0]
        _log(f"pretrained <- local {ckpt}")
    else:
        from huggingface_hub import hf_hub_download
        ckpt = Path(hf_hub_download(spec, "best.pt"))
        _log(f"pretrained <- hub {spec}")
    payload = torch.load(ckpt, map_location="cpu", weights_only=True)
    cfg = dict(_default_config())
    cfg.update(payload.get("config", {}) or {})
    return payload["model_state"], payload.get("charset"), cfg


# ── датасет ──────────────────────────────────────────────────────────────────

class LineDataset:
    """Кроп рядка → (tensor CHW, label). Аугментації — легкі, без imgaug."""

    def __init__(self, items, img_h, img_w, augment):
        self.items = items
        self.h = img_h
        self.w = img_w
        self.augment = augment

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        import numpy as np
        import torch
        from PIL import Image, ImageEnhance, ImageFilter
        path, label = self.items[i]
        im = Image.open(path).convert("RGB")
        if self.augment:
            # 🔴 МОДУЛЬНИЙ random, не Random(seed, i). Раніше генератор сідувався
            # індексом зразка — тобто кожна епоха давала для того самого кропа
            # ТУ САМУ аугментацію, і 20 епох бачили один варіант замість двадцяти.
            # Аугментація формально працювала, а як регуляризатор була вимкнена.
            # Відтворюваність від -p seed при цьому не втрачається: DataLoader
            # сідує `random` у кожному воркері як base_seed+worker_id, а base_seed
            # бере з глобального torch-RNG (його ми сідуємо в main); при
            # num_workers=0 стан просто тече далі між епохами.
            # ⚠ Атрибут self.epoch тут НЕ спрацював би: при persistent_workers
            # воркери тримають свою копію датасету і присвоєння в головному
            # процесі до них не доїжджає.
            rng = random
            if rng.random() < 0.5:
                im = im.rotate(rng.uniform(-2.0, 2.0), resample=Image.BILINEAR,
                               expand=False, fillcolor=(255, 255, 255))
            if rng.random() < 0.4:
                sc = rng.uniform(0.9, 1.1)
                im = im.resize((max(8, int(im.width * sc)),
                                max(8, int(im.height * sc))), Image.BILINEAR)
            if rng.random() < 0.4:
                im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.8, 1.2))
            if rng.random() < 0.4:
                im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.8, 1.25))
            if rng.random() < 0.25:
                im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.8)))
        im = im.resize((self.w, self.h), Image.LANCZOS)
        arr = (np.asarray(im, dtype="float32") / 255.0 - 0.5) / 0.5
        return torch.from_numpy(arr).permute(2, 0, 1), label


def _collate(batch):
    import torch
    imgs = torch.stack([b[0] for b in batch])
    labels = [b[1] for b in batch]
    return imgs, labels


# ── метрики ──────────────────────────────────────────────────────────────────

def _edit_distance(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _validate(model, loader, device, adtype, ddp=False):
    """Валідація. При ddp кожен ранг рахує СВІЙ зріз, лічильники сумуються.

    🔴 Раніше валідував лише rank 0, а решта тим часом заходила в наступну епоху
    і ставала на allreduce першого ж кроку. Валідація autoregressive: при
    val_limit=0 (дефолт) на 8.5k рядків це десятки хвилин, тобто набагато більше
    за таймаут NCCL — watchdog убивав трен, і в лозі це виглядало як мережевий
    збій. Тепер очікування ≈ 0, а сама валідація ще й ділиться на карти.
    """
    import torch
    model.eval()
    n = n_exact = 0
    dist = chars = 0
    samples = []
    with torch.no_grad():
        for imgs, labels in loader:
            imgs = imgs.to(device, non_blocking=True)
            if adtype is not None and device.type == "cuda":
                with torch.autocast("cuda", dtype=adtype):
                    probs = model(imgs).softmax(-1)
            else:
                probs = model(imgs).softmax(-1)
            preds, _ = model.tokenizer.decode(probs.float())
            for pred, gt in zip(preds, labels):
                n += 1
                n_exact += int(pred == gt)
                dist += _edit_distance(pred, gt)
                chars += max(1, len(gt))
                if len(samples) < 8:
                    samples.append({"gt": gt, "pred": pred})
    model.train()
    if ddp:
        acc = torch.tensor([n, n_exact, dist, chars], dtype=torch.int64,
                           device=device)
        torch.distributed.all_reduce(acc)
        n, n_exact, dist, chars = (int(x) for x in acc.tolist())
    return {"n": n, "exact": n_exact / max(1, n), "cer": dist / max(1, chars),
            "samples": samples}


# ── адаптація під залізо ─────────────────────────────────────────────────────
# 🔴 Той самий job їздить на Kaggle (2×T4, 4 CPU), Lightning (1×T4),
# Modal і Vast (A10G/3090/4090, десятки CPU). Жорстко зашиті `workers=2`,
# `fp16` і «одна карта» означали б, що на потужнішому залізі простоює саме те,
# заради чого туди йшли. Тому все, що залежить від заліза, визначається на
# місці, а параметр лишається способом ПЕРЕБИТИ автовизначення, не задати його.

def _cpu_count():
    try:
        return len(os.sched_getaffinity(0))
    except Exception:
        return os.cpu_count() or 2


def _auto_workers(explicit, world):
    """Воркери НА ПРОЦЕС. При DDP CPU ділиться між процесами, інакше вони
    б'ються за ті самі ядра і dataloader стає повільнішим, ніж на одній карті.

    ⚠ 0 = визначити самому, **−1 = справді без воркерів** (завантаження в
    головному процесі). Без цього розрізнення «нуль» став би недосяжним, а він
    потрібен для налагодження і для Windows, де немає fork.
    """
    explicit = int(explicit)
    if explicit < 0:
        return 0
    if explicit:
        return explicit
    per = max(1, (_cpu_count() - 1) // max(1, world))
    return min(8, per)


def _amp_dtype(params, torch, device):
    """None = fp32. bf16 на Ampere+ (стабільніший, без GradScaler), fp16 на T4."""
    if not params.get("amp", True) or device.type != "cuda":
        return None
    want = str(params.get("amp_dtype", "auto")).lower()
    if want == "fp32":
        return None
    if want == "auto":
        major = torch.cuda.get_device_capability(device)[0]
        want = "bf16" if major >= 8 else "fp16"
    if want == "bf16" and not torch.cuda.is_bf16_supported():
        want = "fp16"
    return torch.bfloat16 if want == "bf16" else torch.float16


def _tune_backend(torch):
    """TF32 і cudnn.benchmark. Вхід у нас ФІКСОВАНОГО розміру (48×512), тож
    benchmark підбирає алгоритми один раз і далі лише виграє."""
    try:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
    except Exception:
        pass


def _visible_gpus():
    """Скільки карт видно — БЕЗ звертання до torch.cuda.

    🔴 Це не педантизм, а причина падіння живого прогону 2026-08-01:
    `torch.cuda.is_available()` виконує lazy-init драйвера в БАТЬКІВСЬКОМУ
    процесі, після чого fork-нащадок не може ініціалізувати CUDA («Cannot
    re-initialize CUDA in forked subprocess») і мовчки гине. Rank 0 при цьому
    чесно чекав на нього 20 хвилин і впав із «1/2 clients joined» — тобто
    діагноз у лозі вказував на мережу, а винний був один рядок вище.
    """
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cvd is not None:
        return len([x for x in cvd.split(",") if x.strip() != ""])
    try:
        out = subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                             text=True, timeout=30)
        return sum(1 for ln in out.stdout.splitlines() if ln.startswith("GPU "))
    except Exception:
        return 0


def _world_size(params):
    """Скільки карт задіяти. `ddp=off` — одна, `auto` — усі видимі."""
    mode = str(params.get("ddp", "auto")).lower()
    if os.name == "nt":
        return 1  # nyshporka: DDP через fork на Windows немає
    n = _visible_gpus()
    if n < 1 or mode == "off":
        return 1
    if mode not in ("auto", "on"):
        try:
            n = min(n, int(mode))
        except ValueError:
            pass
    return max(1, n)


class _StepWrap:
    """Обгортка, чий forward = training_step.

    🔴 Без неї DDP не працює взагалі: градієнти синхронізуються хуком на
    forward САМОГО DDP-модуля, а `ddp.module.training_step(...)` його обходить —
    трен би йшов, allreduce не було б, і дві карти тихо вчили б дві різні
    моделі, з яких зберігається одна. Помилки при цьому не буває.
    """

    def __new__(cls, core):
        import torch

        class _W(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.core = m

            def forward(self, imgs, labels):
                return self.core.training_step((imgs, labels), 0)

        return _W(core)


# ── main ─────────────────────────────────────────────────────────────────────

def main(params):
    # ПЕРЕД _ensure_deps(): той пише в лог, а лог відкривається у KAGGLE_WORKING.
    _bind_roots(params)
    _ensure_deps(params)
    import torch

    t_start = time.time()
    seed = int(params["seed"])
    random.seed(seed)
    torch.manual_seed(seed)

    roots = _extract_inputs()
    manifests = _collect_manifests(roots)
    if not manifests["train"]:
        raise RuntimeError(
            f"не знайдено жодного маніфесту (gt*.txt / *.jsonl) під {roots}"
        )

    # відсів биті/дрібні кропи
    def _usable(items):
        from PIL import Image
        out, skipped = [], 0
        for path, txt in items:
            if not path.is_file():
                skipped += 1
                continue
            try:
                with Image.open(path) as im:
                    if im.width < MIN_W or im.height < MIN_H:
                        skipped += 1
                        continue
            except Exception:
                skipped += 1
                continue
            out.append((path, txt))
        return out, skipped

    train_items, sk_t = _usable(manifests["train"])
    val_items, sk_v = _usable(manifests["val"])
    _log(f"кропів: train={len(train_items)} val={len(val_items)} "
         f"(відсіяно {sk_t + sk_v})")
    if params["limit"]:
        train_items = train_items[: params["limit"]]
        _log(f"limit={params['limit']} → train={len(train_items)}")
    if not val_items:
        train_items, val_items = _split_by_page(
            train_items, params["val_frac"], seed)
        _log(f"спліт по сторінках val_frac={params['val_frac']}: "
             f"train={len(train_items)} val={len(val_items)}")
    if params.get("val_limit") and len(val_items) > params["val_limit"]:
        # валідація autoregressive і йде КОЖНУ епоху — не палити GPU на повний val
        val_items = val_items[: params["val_limit"]]
        _log(f"val_limit={params['val_limit']} → val={len(val_items)}")

    resume = _load_resume(params, roots)
    if resume is not None:
        # 🔴 При продовженні charset і config беруться З ЧЕКПОЙНТА, а не
        # перебудовуються: інакше та сама вибірка, порахована після іншого
        # відсіву, дала б charset на символ довший — і голова моделі просто не
        # зійшлася б формою з вагами, які ми відновлюємо.
        state, cfg = resume["model_state"], dict(resume["config"])
        base_charset = charset = resume["charset"]
        cs_stats = {"base": len(charset), "added": "", "dropped_chars": 0}
    else:
        state, base_charset, cfg = _load_pretrained(params, roots)
        if params["img_h"]:
            cfg["img_height"] = params["img_h"]
        if params["img_w"]:
            cfg["img_width"] = params["img_w"]
        if params["max_label_length"]:
            cfg["max_label_length"] = params["max_label_length"]

        if base_charset is None:
            base_charset = ""
            params = dict(params, charset_mode="extend", charset_min_freq=1)
        # Частоти рахуємо ЛИШЕ по train: інакше рідкісний символ, що є тільки у
        # val, потрапляв би в charset через валідаційні мітки — витік, хай і слабкий.
        charset, cs_stats = _build_charset(
            base_charset, train_items, params["charset_mode"],
            params["charset_extra"], params["charset_min_freq"])
    _log(f"charset: {len(base_charset)} → {len(charset)} "
         f"(+{cs_stats['added']!r}; викинуто {cs_stats['dropped_chars']} рідких симв.)")

    charset_set = set(charset)
    max_len = int(cfg["max_label_length"])

    def _prep(items):
        out, empties = [], 0
        for path, txt in items:
            lab = _clean_label(txt, charset_set, max_len)
            if lab:
                out.append((path, lab))
            else:
                empties += 1
        return out, empties

    train_items, e_t = _prep(train_items)
    val_items, e_v = _prep(val_items)
    # val окремо від train: charset будується лише з train, тож саме у val
    # осідають рядки з символами, яких модель не вміє — це видно тільки нарізно
    _log(f"після чистки лейблів: train={len(train_items)} val={len(val_items)} "
         f"(порожніх train={e_t} val={e_v})")
    if not train_items:
        raise RuntimeError("порожній train після чистки лейблів")

    # ── запуск: одна карта чи всі видимі ─────────────────────────────────
    # 🔴 CUDA у батьківському процесі НЕ чіпаємо до розгалуження: ініціалізований
    # у батьку контекст робить fork-нащадка непрацездатним («Cannot re-initialize
    # CUDA in forked subprocess»). Тому вся підготовка вище — суто CPU: списки
    # шляхів, charset, чекпойнт на map_location="cpu".
    fingerprint = _fingerprint(params, charset, cfg, len(train_items))
    if resume is not None:
        old = resume.get("fingerprint") or {}
        diff = {k: (old.get(k), v) for k, v in fingerprint.items() if old.get(k) != v}
        if diff:
            raise RuntimeError(
                "resume: параметри розійшлися з чекпойнтом — продовжити цей самий "
                "трен не можна (було → стало): "
                + "; ".join(f"{k}: {a!r} → {b!r}" for k, (a, b) in sorted(diff.items()))
                + ". Постав ті самі значення або запусти з нуля без resume=true.")
    ctx = {"params": params, "train_items": train_items, "val_items": val_items,
           "charset": charset, "base_charset": base_charset, "cfg": cfg,
           "state": state, "cs_stats": cs_stats, "t_start": t_start,
           "resume": resume, "fingerprint": fingerprint}
    world = _world_size(params)
    if world <= 1:
        _log(f"[env] CPU={_cpu_count()} · карт видно {_visible_gpus()} → тренуємо на 1")
        _train_entry(0, 1, ctx)
        return

    import multiprocessing as _mp
    os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
    # Порт беремо вільний, а не зашитий: на Vast/Lightning (і локально) у тій
    # самій машині може вже крутитись інший наш прогін, і фіксований 29517
    # означав би «Address already in use» на рівному місці.
    if not os.environ.get("MASTER_PORT"):
        try:
            import socket as _socket
            with _socket.socket() as _s:
                _s.bind(("", 0))
                os.environ["MASTER_PORT"] = str(_s.getsockname()[1])
        except Exception:
            os.environ["MASTER_PORT"] = "29517"
    _log(f"[env] CPU={_cpu_count()} · DDP на {world} картах "
         f"(ефективний batch {params['batch'] * world})")
    procs = []
    for rank in range(1, world):
        p = _mp.get_context("fork").Process(target=_child_entry,
                                            args=(rank, world, ctx), daemon=False)
        p.start()
        procs.append(p)
    err = None
    try:
        _train_entry(0, world, ctx)          # rank 0 працює у цьому ж процесі
    except Exception as exc:
        err = exc
    for p in procs:
        if p.is_alive():
            p.terminate()
        p.join()
    dead = [p.exitcode for p in procs if p.exitcode]
    # Причину смерті нащадок пише у ФАЙЛ: його stdout у kaggle-ноутбуці
    # перехоплює ipykernel, і traceback просто зникає — саме через це перша
    # спроба DDP виглядала як «мережевий таймаут» замість справжньої помилки.
    for rank in range(1, world):
        f = KAGGLE_WORKING / f"ddp_rank{rank}.log"
        if f.is_file():
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]:
                _log(f"  [rank{rank}] {ln}")
    if err is not None:
        # 🔴 ФОЛБЕК. DDP — прискорення, а не умова роботи: якщо він не піднявся,
        # правильна поведінка — втратити швидкість, а не сесію з корпусом,
        # який уже 20 хвилин розпаковувався.
        _log(f"⚠ DDP не спрацював ({type(err).__name__}: {str(err)[:200]}) — "
             f"перезапускаюсь на ОДНІЙ карті")
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        _train_entry(0, 1, ctx)
        return
    if dead:
        # Ваги вже записані rank'ом 0, тож це попередження, а не падіння —
        # але мовчати не можна: половина градієнтів могла не доїхати.
        _log(f"⚠ DDP: воркери завершились із кодами {dead} — результат сумнівний")


def _child_entry(rank, world, ctx):
    """Нащадок DDP: те саме, що rank 0, але з траплянням помилки у файл."""
    try:
        _train_entry(rank, world, ctx)
    except BaseException as exc:
        import traceback
        try:
            KAGGLE_WORKING.mkdir(parents=True, exist_ok=True)
            (KAGGLE_WORKING / f"ddp_rank{rank}.log").write_text(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8")
        except Exception:
            pass
        raise


def _train_entry(rank, world, ctx):
    """Один процес трену. rank 0 логує, валідує і зберігає; решта — рахує."""
    import torch
    from torch.utils.data import DataLoader

    params = ctx["params"]
    charset, cfg, state = ctx["charset"], ctx["cfg"], ctx["state"]
    train_items, val_items = ctx["train_items"], ctx["val_items"]
    t_start = ctx["t_start"]
    lead = rank == 0
    log = _log if lead else (lambda *a, **kw: None)

    ddp = world > 1
    if ddp:
        from datetime import timedelta as _td
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        if torch.cuda.is_available():
            torch.cuda.set_device(rank)
        # ⚠ Таймаут коштує РЕАЛЬНОГО часу сесії: при невдалому рукостисканні
        # rank 0 просто стоїть. 20 хв з'їли пів проби, 5 достатньо (процеси
        # стартують секунди) і лишає запас на найдовшу колективну операцію —
        # broadcast після валідації rank 0.
        torch.distributed.init_process_group(
            backend, rank=rank, world_size=world,
            timeout=_td(minutes=float(params.get("ddp_timeout_min", 5))))
    device = torch.device(f"cuda:{rank}" if torch.cuda.is_available() else "cpu")
    _tune_backend(torch)
    adtype = _amp_dtype(params, torch, device)

    # 🔴 Більший ефективний batch без правки lr — це ІНШИЙ трен, а не швидший.
    # sqrt-масштабування (дефолт) — компроміс: linear на fine-tune з OneCycle
    # часто розхитує, none недовикористовує більший батч.
    lr = float(params["lr"])
    mode = str(params.get("lr_scale", "sqrt")).lower()
    if ddp and mode != "none":
        lr *= (world ** 0.5) if mode == "sqrt" else world
        log(f"[env] lr {params['lr']:.2e} → {lr:.2e} ({mode} × {world} карт)")

    model = _build_model(charset, cfg, lr, params["warmup_pct"],
                         params["weight_decay"], params["batch"])
    model.log = lambda *a, **kw: None  # strhub self.log поза Trainer — заглушка
    remap = {"remapped": 0, "fresh": 0, "dropped": []}
    if state is not None:
        model_sd = model.state_dict()
        st = _strip_prefix(dict(state), set(model_sd.keys()))
        st, remap = _remap_charset_weights(st, ctx["base_charset"], charset, model_sd)
        missing, unexpected = model.load_state_dict(st, strict=False)
        log(f"ваги: matched={len(set(st) & set(model_sd))} "
            f"missing={len(missing)} unexpected={len(unexpected)}; "
            f"charset-перенесено {remap['remapped']}, нових {remap['fresh']}"
            + (f"; скинуто по формі {remap['dropped']}" if remap["dropped"] else ""))
        if len(missing) > len(model_sd) // 2:
            raise RuntimeError(f"state_dict mismatch: {missing[:5]}")
    model = model.to(device)
    model.train()
    core = model
    if ddp:
        from torch.nn.parallel import DistributedDataParallel as DDP
        # find_unused_parameters=False (перевірено на живому трені 2026-08-01).
        # Спершу стояло True «про всяк випадок»: PARSeq рахує кілька перестановок
        # за крок, і склад задіяних параметрів теоретично міг плавати. Але сам
        # PyTorch на 752 кроках епохи не знайшов жодного невикористаного
        # параметра і попередив, що прапорець додає зайвий обхід графа КОЖНУ
        # ітерацію. Тобто обережність тут коштувала швидкості й нічого не
        # страхувала. ⚠ Якщо колись зависне на allreduce посеред епохи —
        # `-p ddp_find_unused=true` повертає стару поведінку.
        gpu = torch.cuda.is_available()
        model = DDP(_StepWrap(core),
                    device_ids=[rank] if gpu else None,
                    output_device=rank if gpu else None,
                    find_unused_parameters=bool(params.get("ddp_find_unused", False)))

    h, w = int(cfg["img_height"]), int(cfg["img_width"])
    seed = int(params["seed"])
    workers = _auto_workers(params.get("workers", 0), world)
    train_ds = LineDataset(train_items, h, w, params["augment"] == "basic")
    # Зріз [rank::world], а не DistributedSampler: семплер доповнює вибірку до
    # кратності world, тобто частина рядків порахувалась би двічі й перекосила
    # CER. Зріз ділить рівно, сума лічильників = повний val-сет.
    my_val = val_items[rank::world] if world > 1 else val_items
    val_ds = LineDataset(my_val, h, w, False)
    sampler = None
    if ddp:
        from torch.utils.data.distributed import DistributedSampler
        sampler = DistributedSampler(train_ds, num_replicas=world, rank=rank,
                                     shuffle=True, seed=seed)
    train_loader = DataLoader(
        train_ds, batch_size=params["batch"], shuffle=(sampler is None),
        sampler=sampler, num_workers=workers, collate_fn=_collate,
        pin_memory=(device.type == "cuda"), drop_last=False,
        persistent_workers=bool(workers),
        **({"prefetch_factor": 4} if workers else {}))
    # Валідують УСІ ранги, кожен свій зріз; лічильники зводить all_reduce
    # у _validate. Логує і зберігає ваги все одно тільки rank 0.
    val_loader = DataLoader(
        val_ds, batch_size=max(8, params["batch"]), shuffle=False,
        num_workers=workers, collate_fn=_collate,
        pin_memory=(device.type == "cuda"),
        persistent_workers=bool(workers)) if val_items else None

    steps_per_epoch = max(1, math.ceil(len(train_ds) / max(1, world) / params["batch"]))
    total_steps = steps_per_epoch * params["epochs"]
    opt = torch.optim.AdamW(core.parameters(), lr=lr,
                            weight_decay=params["weight_decay"])
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=total_steps,
        pct_start=params["warmup_pct"], cycle_momentum=False)
    use_scaler = adtype is torch.float16
    try:  # torch>=2.4 — torch.cuda.amp.GradScaler задепрекейчено
        scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)
    except (AttributeError, TypeError):
        scaler = torch.cuda.amp.GradScaler(enabled=use_scaler)
    dtype_name = {None: "fp32", torch.float16: "fp16",
                  torch.bfloat16: "bf16"}.get(adtype, str(adtype))

    # ── продовження перерваного трену ────────────────────────────────────────
    # 🔴 Відновлюємо не лише ваги, а й optimizer/scheduler/scaler. Ваги без
    # моментів AdamW і без позиції в циклі OneCycle — це не «продовжити», а
    # «почати наново з теплого старту»: lr стрибнув би на початок циклу, і крива
    # просіла б рівно там, де трен нібито продовжився.
    resume = ctx.get("resume")
    start_epoch = 1
    resumed_history = []
    if resume is not None:
        opt.load_state_dict(resume["optimizer"])
        sched.load_state_dict(resume["scheduler"])
        if resume.get("scaler") is not None and use_scaler:
            try:
                scaler.load_state_dict(resume["scaler"])
            except Exception as exc:      # інший amp-режим між прогонами
                log(f"[resume] scaler не відновлено ({type(exc).__name__}) — з нуля")
        start_epoch = int(resume["epoch"]) + 1
        resumed_history = list(resume.get("history") or [])
        log(f"[resume] продовжую з епохи {start_epoch}/{params['epochs']}; "
            f"lr={sched.get_last_lr()[0]:.2e}, best_val_cer={resume.get('best_cer')}")
        if start_epoch > params["epochs"]:
            log("[resume] усі епохи вже пройдено — нема чого доучувати")

    log(f"старт: {len(train_ds)} рядків × {params['epochs']} епох "
        f"({steps_per_epoch} кроків/епоха на процес), img={h}x{w}, "
        f"dev={device}, amp={dtype_name}")
    if lead:
        try:
            names = ", ".join(torch.cuda.get_device_name(i)
                              for i in range(torch.cuda.device_count())) or "—"
            _log(f"[env] CPU={_cpu_count()} workers/процес={workers} "
                 f"batch={params['batch']}×{world}={params['batch'] * world} "
                 f"| GPU: {names}")
        except Exception as exc:
            _log(f"[env] діагностику пропущено: {type(exc).__name__}: {exc}")

    if params.get("compile"):
        # ⚠ Не дефолт: inductor на sm75 (T4) виграє мало, а перекомпіляція під
        # мінливі форми може з'їсти більше, ніж дасть. Вмикати свідомо.
        try:
            core_c = torch.compile(core)
            log("[env] torch.compile увімкнено")
            if not ddp:
                model = core_c
        except Exception as exc:
            log(f"[env] torch.compile не вийшов ({type(exc).__name__}) — без нього")

    # Крива тягнеться крізь перезапуски: інакше summary другої сесії показував
    # би трен, що «почався» з 12-ї епохи і не мав би з чим порівнюватись.
    history = list(resumed_history)
    best_cer = float(resume["best_cer"]) if resume is not None else float("inf")
    # 🔴 ДВА лічильники, а не один — це і є «помилка 11-ї». До 2026-08-04 умова
    # була одна: `if cer < best_cer - min_delta`. Тобто епоха, що покращила
    # результат МЕНШЕ за min_delta, вважалась провальною ДВІЧІ: і ваги не
    # зберігались, і лічильник терпіння тікав. На v11 (`b83741e8`) ep7 дав
    # 0.1237 проти 0.1246 — покращення на 0.0009 при порозі 0.002 — трен
    # зупинився, а `parseq_best.pt` лишився з ГІРШИМИ вагами ep6. Модель, що
    # монотонно повзе вниз дрібними кроками, так не доїжджає ніколи.
    #   best_cer — «найкраще бачене», рухається від БУДЬ-ЯКОГО покращення
    #              і вирішує, коли писати ваги;
    #   ref_cer  — точка відліку терпіння, рухається лише від ЗНАЧУЩОГО
    #              покращення (≥ min_delta) і вирішує, коли зупинятись.
    # Обидва зберігаються у parseq_last.pt; для старих чекпойнтів ref = best.
    ref_cer = float(resume.get("ref_cer", best_cer)) if resume is not None else float("inf")
    stale_start = int(resume.get("stale", 0)) if resume is not None else 0
    baseline = None
    if val_loader is not None and resume is None:
        # точка відліку ДО тюну: без неї крива val_cer ні з чим не порівнюється
        # (а базова модель може вже читати цей домен — тоді трен марний).
        # При resume не рахуємо: базова точка вже є в history попередньої сесії,
        # а зайвий повний прохід по val — це десятки хвилин GPU ні за що.
        baseline = _validate(core, val_loader, device, adtype, ddp)
        log(f"baseline (до трену): val_cer={baseline['cer']:.4f} "
            f"val_exact={baseline['exact']:.4f} на {baseline['n']} рядках")
    elif resume is not None:
        baseline = resume.get("baseline")
    best_path = KAGGLE_WORKING / "parseq_best.pt"
    last_path = KAGGLE_WORKING / RESUME_NAME
    if lead:
        KAGGLE_WORKING.mkdir(parents=True, exist_ok=True)
    out_cfg = {"img_height": h, "img_width": w,
               "max_label_length": int(cfg["max_label_length"]),
               "patch_size": list(cfg.get("patch_size", [4, 8])),
               "embed_dim": int(cfg.get("embed_dim", 384)),
               "enc_num_heads": int(cfg.get("enc_num_heads", 6)),
               "enc_mlp_ratio": int(cfg.get("enc_mlp_ratio", 4)),
               "enc_depth": int(cfg.get("enc_depth", 12)),
               "dec_num_heads": int(cfg.get("dec_num_heads", 12)),
               "dec_mlp_ratio": int(cfg.get("dec_mlp_ratio", 4)),
               "dec_depth": int(cfg.get("dec_depth", 1)),
               "decode_ar": bool(cfg.get("decode_ar", True)),
               "refine_iters": int(cfg.get("refine_iters", 1)),
               "dropout": float(cfg.get("dropout", 0.1))}
    stale = stale_start

    # ── профіль data vs compute ────────────────────────────────────────────
    # Навіщо: T4 на Kaggle тримала ~1% утилізації, а епоха йшла 33 хв — тобто
    # тренувався dataloader, не модель. Без розділення «скільки чекали батч»
    # проти «скільки рахували» це неможливо ані довести, ані спростувати, і
    # оптимізація зводиться до вгадування (додати GPU? збільшити batch?).
    # `torch.cuda.synchronize()` обов'язковий: без нього CUDA-виклики
    # асинхронні, і час compute «перетече» у наступний замір data.
    prof = bool(params.get("profile", True)) and lead
    # 🔴 Самозупинка за годинником. Перевіряється НА МЕЖІ ЕПОХИ і з прогнозом:
    # якщо наступна епоха (за середнім часом попередніх) не встигне до ліміту —
    # виходимо зараз. Інакше при 45-хвилинних епохах можна перескочити ліміт на
    # півгодини й отримати те саме вбивство посеред роботи, від якого рятуємось.
    # ⚠ `t_start` — від початку main(), НЕ від початку епох: розпакування
    # корпусу з'їдає 15-25 хв того самого 12-годинного вікна.
    wall_limit = float(params.get("wall_limit_h", 0)) * 3600
    if wall_limit and lead:
        log(f"[wall] ліміт {wall_limit / 3600:.1f} год від старту кернела "
            f"(вже минуло {(time.time() - t_start) / 60:.0f} хв) — "
            f"зупинюсь сам, щоб гарантовано записати ваги й summary")

    for epoch in range(start_epoch, params["epochs"] + 1):
        if sampler is not None:
            sampler.set_epoch(epoch)      # інакше всі епохи мають той самий поділ
        t_ep = time.time()
        run_loss, n_batch = 0.0, 0
        t_data = t_fwd = t_bwd = 0.0
        t_mark = time.time()
        for bi, (imgs, labels) in enumerate(train_loader):
            if prof:
                t_data += time.time() - t_mark          # чекали на батч
                t_mark = time.time()
            imgs = imgs.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            if adtype is not None:
                with torch.autocast("cuda", dtype=adtype):
                    loss = model(imgs, labels) if ddp else \
                        core.training_step((imgs, labels), bi)
                if prof:
                    torch.cuda.synchronize(); t_fwd += time.time() - t_mark
                    t_mark = time.time()
                if use_scaler:
                    scaler.scale(loss).backward()
                    scaler.unscale_(opt)
                    torch.nn.utils.clip_grad_norm_(core.parameters(), 5.0)
                    scaler.step(opt)
                    scaler.update()
                else:                      # bf16 не потребує масштабування втрат
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(core.parameters(), 5.0)
                    opt.step()
            else:
                loss = model(imgs, labels) if ddp else \
                    core.training_step((imgs, labels), bi)
                if prof:
                    torch.cuda.synchronize(); t_fwd += time.time() - t_mark
                    t_mark = time.time()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(core.parameters(), 5.0)
                opt.step()
            sched.step()
            if prof:
                torch.cuda.synchronize(); t_bwd += time.time() - t_mark
                t_mark = time.time()
            run_loss += float(loss.detach())
            n_batch += 1
            if params.get("max_steps") and n_batch >= params["max_steps"]:
                log(f"[prof] max_steps={params['max_steps']} — епоху обрізано")
                break
            if bi % 50 == 0:
                extra = ""
                if prof and bi:
                    tot = max(1e-9, t_data + t_fwd + t_bwd)
                    extra = (f" | data={t_data / tot * 100:.0f}% "
                             f"fwd={t_fwd / tot * 100:.0f}% bwd={t_bwd / tot * 100:.0f}%")
                log(f"ep{epoch} {bi}/{steps_per_epoch} loss={run_loss / max(1, n_batch):.4f} "
                    f"lr={sched.get_last_lr()[0]:.2e}{extra}")
        train_loss = run_loss / max(1, n_batch)
        rec = {"epoch": epoch, "train_loss": round(train_loss, 4),
               "sec": round(time.time() - t_ep, 1)}
        if prof:
            tot = max(1e-9, t_data + t_fwd + t_bwd)
            rows_s = n_batch * params["batch"] * world / max(1e-9, tot)
            rec.update({"t_data": round(t_data, 1), "t_fwd": round(t_fwd, 1),
                        "t_bwd": round(t_bwd, 1),
                        "data_pct": round(t_data / tot * 100, 1),
                        "rows_per_sec": round(rows_s, 1)})
            log(f"[prof] ep{epoch}: data={t_data:.0f}s ({rec['data_pct']:.0f}%) "
                f"fwd={t_fwd:.0f}s bwd={t_bwd:.0f}s → {rec['rows_per_sec']:.0f} рядків/с"
                + (" 🔴 DATALOADER-BOUND: піднімай workers"
                   if rec["data_pct"] > 40 else ""))
            if torch.cuda.is_available():
                # 🔴 ПІК, а не поточне. `memory_allocated()` міряється між
                # епохами, коли активації вже звільнені, і показував 0.4 GiB із
                # 14.6 — з чого випливав хибний висновок «пам'ять вільна, можна
                # батч більший». Рішення про batch приймається за піком.
                peak = torch.cuda.max_memory_allocated() / 2**30
                total = torch.cuda.get_device_properties(device).total_memory / 2**30
                rec["gpu_peak_gib"] = round(peak, 2)
                log(f"[prof] GPU: пік {peak:.1f} GiB / {total:.1f} GiB "
                    f"({peak / total * 100:.0f}%)"
                    + ("  → batch можна піднімати" if peak / total < 0.5 else ""))
                torch.cuda.reset_peak_memory_stats()
        stop = False
        if val_loader is not None:
            v = _validate(core, val_loader, device, adtype, ddp)
            rec.update({"val_cer": round(v["cer"], 4),
                        "val_exact": round(v["exact"], 4), "val_n": v["n"]})
            log(f"ep{epoch}: loss={train_loss:.4f} val_cer={v['cer']:.4f} "
                f"val_exact={v['exact']:.4f} ({rec['sec']}s)")
            for s in v["samples"][:3]:
                log(f"   GT: {s['gt']!r}\n   PR: {s['pred']!r}")
            # 🔴 Поріг значущості керує ТЕРПІННЯМ, а не збереженням ваг —
            # див. пояснення про два лічильники біля ініціалізації ref_cer.
            # min_delta 0.002 = 0.2 пп; було зашито 1e-4 (покращення на 3
            # символи з 4500 скидало лічильник, і трен їхав по плато далі).
            md = float(params.get("min_delta", 0.002))
            if v["cer"] < best_cer:
                best_cer = v["cer"]
                # Метрики після all_reduce однакові на всіх рангах, тож рішення
                # «це best» теж однакове — але ПИШЕ файл лише rank 0, інакше
                # кілька процесів товклися б в один шлях.
                if lead:
                    torch.save({"model_state": core.state_dict(),
                                "charset": charset, "config": out_cfg,
                                "val_cer": best_cer, "epoch": epoch}, best_path)
                    log(f"ep{epoch}: ★ новий best (cer={best_cer:.4f}) → {best_path.name}")
            if v["cer"] < ref_cer - md:
                ref_cer = v["cer"]
                stale = 0
            else:
                stale += 1
                if v["cer"] < ref_cer:
                    # Покращення є, але дрібне. Кажемо це вголос: інакше в лозі
                    # видно лише «early stop», і зупинка на моделі, що ще їхала
                    # вниз, виглядає як плато.
                    log(f"ep{epoch}: покращення {ref_cer - v['cer']:.4f} < "
                        f"min_delta {md} → терпіння {stale}/{params['patience']} "
                        f"(ваги збережено, зупинка рахується)")
        elif lead:
            torch.save({"model_state": core.state_dict(), "charset": charset,
                        "config": out_cfg, "epoch": epoch}, best_path)
            log(f"ep{epoch}: loss={train_loss:.4f} (без val) ({rec['sec']}s)")
        history.append(rec)
        if lead:
            _progress(params, epoch, params["epochs"], rec)
        if lead and params.get("save_epochs", True) and val_loader is not None:
            # 🔴 ВАГИ КОЖНОЇ ЕПОХИ окремим тонким файлом (формат Hukyl, ~95 МБ).
            # Навіщо, коли є parseq_best.pt: `best` обирається за val_cer, а
            # val у нашого збірника — це 155 рядків / 4.7 тис. символів за
            # фіксованою квотою на джерело. Він добре зважений (57% наш домен,
            # 43% peter) і дедуплікований проти train, але:
            #   * менший за БУДЬ-ЯКИЙ наш holdout — а «малий holdout бреше»
            #     перевертав висновок двічі за три доби (29 рядків казки,
            #     48 рядків суду);
            #   * узятий із ТИХ САМИХ справ, що й train (holdout зі збірника
            #     виключений), тобто нової руки й нового фонду не бачить;
            #   * міряє CER, а наш критерій — recall власних назв, і вони
            #     розходяться (v11f мала ГІРШИЙ CER і знаходила на 10 назв
            #     більше — memory htr-search-recall-not-cer).
            # Тому епоху обирає локальний прогін по всьому holdout, а для цього
            # ваги кожної епохи мусять пережити контейнер.
            ep_path = KAGGLE_WORKING / f"parseq_ep{epoch:02d}.pt"
            try:
                torch.save({"model_state": core.state_dict(), "charset": charset,
                            "config": out_cfg, "val_cer": v["cer"],
                            "epoch": epoch}, ep_path)
            except Exception as exc:   # диск міг скінчитись — трен важливіший
                log(f"[epochs] не збережено {ep_path.name}: "
                    f"{type(exc).__name__}: {exc}")
        if lead:
            # 🔴 Повний стан ЩОЕПОХИ, окремим файлом. parseq_best.pt лишається
            # тонким і Hukyl-сумісним (його читає htr_lines_eval), а сюди йде
            # все, без чого продовження — фікція: моменти AdamW, позиція в циклі
            # OneCycle, лічильники ранньої зупинки й крива.
            try:
                torch.save({
                    "model_state": core.state_dict(),
                    "optimizer": opt.state_dict(),
                    "scheduler": sched.state_dict(),
                    "scaler": scaler.state_dict() if use_scaler else None,
                    "epoch": epoch,
                    "best_cer": best_cer,
                    "ref_cer": ref_cer,
                    "stale": stale,
                    "charset": charset,
                    "config": out_cfg,
                    "history": history,
                    "baseline": baseline,
                    "fingerprint": ctx["fingerprint"],
                }, last_path)
            except Exception as exc:   # диск міг скінчитись — але трен живий
                log(f"[resume] не збережено {last_path.name}: {type(exc).__name__}: {exc}")
        if params["patience"] and stale >= params["patience"]:
            # 🔴 Підлога: до min_epochs рання зупинка не діє. Терпіння судить за
            # val_cer (8% від трен-корпусу), а придатність моделі міряється
            # потім, локально, по всіх збережених епохах — і на кривій v11
            # найкращий val прийшов на ep9 ПІСЛЯ провалу на ep8. Зупинившись
            # раніше, ми б не мали чого міряти.
            floor = int(params.get("min_epochs", 0))
            if epoch < floor:
                log(f"ep{epoch}: терпіння вичерпано ({stale}), але підлога "
                    f"min_epochs={floor} — їдемо далі")
            else:
                log(f"early stop: {stale} епох без покращення")
                stop = True
        if wall_limit and not stop:
            spent = time.time() - t_start
            # середнє по ЕПОХАХ, не по всьому часу — інакше розпакування
            # роздуває прогноз і трен зупиняється передчасно
            avg_ep = sum(r["sec"] for r in history) / max(1, len(history))
            if spent + avg_ep > wall_limit:
                log(f"[wall] ⏱ {spent / 3600:.1f} год з {wall_limit / 3600:.1f}; "
                    f"наступна епоха (~{avg_ep / 60:.0f} хв) не встигне — "
                    f"зупиняюсь на ep{epoch}, ваги збережено")
                stop = True
        if ddp:
            # 🔴 Рішення «зупинитись» приймає ЛИШЕ rank 0 (тільки він валідує), і
            # його треба РОЗІСЛАТИ. Інакше нульовий процес вийде з циклу, решта
            # стане на allreduce наступної епохи й повисне до таймауту NCCL.
            flag = torch.tensor([1 if stop else 0], device=device)
            torch.distributed.broadcast(flag, src=0)
            stop = bool(flag.item())
        if stop:
            break

    if ddp:
        torch.distributed.barrier()
        torch.distributed.destroy_process_group()
    if not lead:
        return
    if not best_path.exists():
        torch.save({"model_state": core.state_dict(), "charset": charset,
                    "config": out_cfg}, best_path)

    summary = {
        "pretrained": params["pretrained"],
        "baseline_val_cer": None if baseline is None else round(baseline["cer"], 4),
        "baseline_val_exact": None if baseline is None else round(baseline["exact"], 4),
        "charset_len": len(charset),
        "charset_added": ctx["cs_stats"]["added"],
        "charset_remapped": remap,
        "n_train": len(train_items),
        "n_val": len(val_items),
        "img_size": [h, w],
        "world_size": world,
        "effective_batch": params["batch"] * world,
        "lr_effective": lr,
        "amp_dtype": dtype_name,
        "workers_per_proc": workers,
        "params": {k: params[k] for k in sorted(params)},
        "history": history,
        "best_val_cer": None if best_cer == float("inf") else round(best_cer, 4),
        "best_epoch": min((r for r in history if r.get("val_cer") is not None),
                          key=lambda r: r["val_cer"], default={}).get("epoch"),
        # 🔴 Ваги епох лежать поруч і чекають на ЛОКАЛЬНИЙ відбір по holdout:
        # best_epoch тут — це best ЗА VAL, тобто за ~155 рядками з тих самих
        # справ, що й train. Остаточну епоху обирає локальний відбір по holdout (`nysh train eval`).
        "epoch_ckpts": sorted(p.name for p in KAGGLE_WORKING.glob("parseq_ep*.pt")),
        "wall_sec": round(time.time() - t_start, 1),
        "finished": _utc_iso(),
    }
    (KAGGLE_WORKING / "ptrain_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    # ptrain.log більше НЕ переписується тут: _log пише його потоково з першого
    # рядка, і фінальний write_text затер би все, що встигло накопичитись.
    _log(f"done: best_cer={summary['best_val_cer']} "
         f"epochs={len(history)} wall={summary['wall_sec']}s")
    # Обгортка Modal кладе повернуте у _summary.json поруч із вагами й віддає
    # його в `gpurunner status`. На Kaggle значення нікому не потрібне (там
    # читається ptrain_summary.json із виходу), тож повернення нічого не ламає.
    return summary


# ⚠ __main__-блоку тут навмисно немає. Раніше він тримав «смоук» із жорстко
# виписаним набором params, який відстав від validate_params на десяток ключів
# і читався як документація формату — брехлива. Єдине правдиве джерело набору
# параметрів — ParseqTrainJob.validate_params; локально ранер не запускається
# однаково (потрібні /kaggle/input і GPU).


if __name__ == "__main__":
    # nyshporka: локальний запуск файлом — параметри з JSON, а не з інжекції.
    import argparse as _ap

    _p = _ap.ArgumentParser()
    _p.add_argument("--params", required=True)
    _a = _p.parse_args()
    _params = json.loads(Path(_a.params).read_text(encoding="utf-8"))
    main(_params)
