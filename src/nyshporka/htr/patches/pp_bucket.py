"""Кошики форм для PP-OCRv6: вхід мережі доповнюється до фіксованої сітки форм.

Навіщо. fp16 основи PP-моделі на справжніх сторінках повільніший за fp32, бо
кожна нова форма пачки (рядків × ширина) змушує cuDNN наново добирати ядра;
на повторних формах той самий fp16 дав −33…−44 % (`pp_fp16.py`). Тут кожна
пачка доповнюється до ширини, кратної `step`, і до кількості рядків, що є
степенем двійки. Форм стає кілька десятків, і після розгону всі повторні.

Що змінюється в тексті. Порожні рядки пачки ні на що не впливають: основа зі
злитим BN рядки між собою не змішує (на 210 рядках — 0 відмінностей). Доповнення
ширини — впливає: шия мережі маскує його за `seq_lens`, але блоки SE основи
усереднюють ознаки по всій ширині разом із нулями. Тому PP-текст і без кошиків
залежить від складу пачки, а кошики міняють його ще на ~7 % символів — не в бік
гіршого (заміри нижче).

Вмикає раннер разом із fp16 (`--pp-precision auto|fp16`, крок `--pp-bucket`, дефолт
64). Замір 18.11.2026 (V100, 240 сторінок, три голоси): розпізнавання +59 % з кроком 64,
+47 % з 256; PP-текст змінюється на ~7 % символів (з 256 — на 14 %). Якість не гірша:
«індекс FS» 178 рук (Дяк v16) прізвища 59.0 → 60.8 %, мірило назв Регента пошуком
95.7 → 95.9 %, сліпий тест 6 пар × 2 порядки — 8 : 1 на користь fp16 з кошиками.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


def _pow2(n: int) -> int:
    p = 1
    while p < n:
        p *= 2
    return p


def enable_bucket(rec: nn.Module, step: int = 256) -> nn.Module:
    """Обгорнути `forward` мережі (`task.net.nn`) доповненням до сітки форм."""
    if getattr(rec, "_nysh_bucket", False):
        return rec
    inner = rec.forward

    def forward(x, seq_lens=None, *a, **k):  # type: ignore[no-untyped-def]
        n, _c, _h, w = x.shape
        wb = ((w + step - 1) // step) * step
        nb = _pow2(n)
        if wb == w and nb == n:
            return inner(x, seq_lens, *a, **k)
        if seq_lens is None:
            seq_lens = torch.full((n,), w, dtype=torch.long, device=x.device)
        xp = F.pad(x, (0, wb - w, 0, 0, 0, 0, 0, nb - n))
        lp = torch.cat([seq_lens.to(x.device),
                        torch.full((nb - n,), w, dtype=seq_lens.dtype, device=x.device)])
        logits, out_lens = inner(xp, lp, *a, **k)
        logits = logits[:n]
        if out_lens is not None:
            out_lens = out_lens[:n]
            # обрізати хвіст доповнення: вихід мусить мати ту саму ширину, що без кошика
            w_out = int(logits.shape[-1] * w / wb)
            if w_out >= int(out_lens.max()):
                logits = logits[..., :w_out]
        return logits, out_lens

    rec.forward = forward
    rec._nysh_bucket = True
    return rec
