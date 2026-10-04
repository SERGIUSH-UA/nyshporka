"""Основа PP-OCRv6 у половинній точності (fp16) — ЛИШЕ для заміру, не для прогонів.

🔴 На справжніх сторінках fp16 у 5.5 раза ПОВІЛЬНІШИЙ за fp32 (V100, 10 сторінок,
сегментація з кешу: розпізнавання 19.8 проти 3.6 с/стор). Рядки йдуть пачками
за шириною, і в кожній пачці ширина інша, а для кожної нової форми cuDNN
наново вибирає ядра половинної точності. Прохід по тих самих формах удруге
(окремий замір однієї пачки, бенч кількох варіантів у ОДНОМУ процесі) показує
навпаки виграш −33…−44% — і саме так цей виграш було хибно заміряно 04.10.2026.
Тому раннер вмикає це лише явно: `--pp-precision fp16`.

Що робиться:
- основа (`rec.backbone`) рахує під `torch.autocast(float16)`, шия й голова
  лишаються у fp32 — вихід основи повертається у fp32;
- 🔴 згортка `backbone.conv1.stem3` завжди у fp32. cuDNN 9.10.2 (бандл torch
  2.14 cu126) повертає NaN/inf для fp16-згорток 3×3 із 64 вихідними каналами
  на великих картах ознак — відтворено на ВИПАДКОВИХ вагах і входах, тобто це
  вада ядра, а не переповнення. Без цього обходу fp16 давав порожній вихід;
- запобіжник: якщо основа все ж дала нескінченне значення, ця пачка
  перераховується у fp32.

Якість fp16 проти fp32 на замірі XVIII ст. та сама (holdout CER 31.4% проти
31.3%), змінюється ~5% рядків. Перевірка — `pp_fp16_verify.py`.
"""
from __future__ import annotations

import torch
from torch import nn


class FP32Conv(nn.Module):
    """Згортка, що завжди рахує у fp32 (autocast вимкнено), вихід — fp32."""

    def __init__(self, conv: nn.Module) -> None:
        super().__init__()
        self.conv = conv

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        with torch.autocast(device_type=x.device.type, enabled=False):
            return self.conv(x.float())


def _guard_stem(rec: nn.Module) -> None:
    blk = getattr(rec.backbone.conv1, "stem3", None)
    if blk is not None and not isinstance(blk.conv, FP32Conv):
        blk.conv = FP32Conv(blk.conv)


def _half_forward(inner):  # type: ignore[no-untyped-def]
    def forward(x, *a, **k):  # type: ignore[no-untyped-def]
        with torch.autocast(device_type=x.device.type, dtype=torch.float16):
            y = inner(x, *a, **k)
        y = y.float()
        if not bool(torch.isfinite(y).all()):
            y = inner(x, *a, **k).float()          # запобіжник: ця пачка — у fp32
        return y
    return forward


def enable_fp16(rec: nn.Module) -> nn.Module:
    """Увімкнути fp16 для основи PP-моделі (`task.net.nn`). Ідемпотентно."""
    if getattr(rec.backbone, "_nysh_fp16", False):
        return rec
    _guard_stem(rec)
    rec.backbone.forward = _half_forward(rec.backbone.forward)
    rec.backbone._nysh_fp16 = True
    return rec
