"""Основа PP-OCRv6 у половинній точності (fp16) — там, де карта від цього швидша.

Що робиться:
- основа (`rec.backbone`) рахує під `torch.autocast(float16)`, шия й голова
  лишаються у fp32 — вихід основи повертається у fp32;
- 🔴 згортка `backbone.conv1.stem3` завжди у fp32. cuDNN 9.10.2 (бандл torch
  2.14 cu126) повертає NaN/inf для fp16-згорток 3×3 із 64 вихідними каналами
  на великих картах ознак — відтворено на ВИПАДКОВИХ вагах і входах, тобто це
  вада ядра, а не переповнення. У мережі така згортка одна — `stem3`
  (128 → 64, 3×3, крок 2). Без цього обходу fp16 давав порожній вихід;
- запобіжник: якщо основа все ж дала нескінченне значення, ця пачка
  перераховується у fp32. Текст тоді той самий, що без fp16, лише повільніше.

Заміри (04.10.2026, Дяк-Літописець, 1277 рядків 224-1-1112, мс/рядок; разом зі
злиттям `pp_fuse`):
- V100: fp32 12.4 → fp16 6.9 (−44%); 94% рядків тотожні fp32, CER між ними 0.2%;
  Скриба-PP на holdout ф.792 — CER 13.40% проти 13.42% у fp32;
- GTX 1650 (без тензорних ядер): fp16 утричі ПОВІЛЬНІШИЙ — тому `calibrate`.

Розбіжність у ~6% рядків — того самого роду, що від складу пачки (інша пачка в
fp32 змінює 26% рядків): дрібні зсуви на краю рішення, а не вада.

Перевірка — `pp_fp16_verify.py`: fp32 проти fp16 на тих самих кропах.
"""
from __future__ import annotations

import time

import torch
from torch import nn

#: Скільки має виграти fp16 на калібруванні, щоб його ввімкнути: з запасом,
#: аби межовий випадок не перемикав точність від прогону до прогону.
GAIN_MIN = 0.8


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


def calibrate(rec: nn.Module, device: str, *, channels: int = 3, height: int = 96,
              width: int = 512, batch: int = 4, reps: int = 2) -> tuple[float, float]:
    """Час проходу основи fp32 і fp16 на цій карті, мс: `(fp32, fp16)`.

    Вхід — синтетичний, форми робочої пачки; міряється найкращий із `reps`
    після прогріву (перший виклик платить за вибір алгоритмів cuDNN).
    """
    bb = rec.backbone
    inner = bb.forward
    _guard_stem(rec)
    half = _half_forward(inner)
    x = torch.rand(batch, channels, height, width, device=device) * 2 - 1

    def best(fn) -> float:  # type: ignore[no-untyped-def]
        fn(x)
        torch.cuda.synchronize(device)
        out = float("inf")
        for _ in range(reps):
            t = time.perf_counter()
            fn(x)
            torch.cuda.synchronize(device)
            out = min(out, time.perf_counter() - t)
        return 1000 * out

    with torch.inference_mode():
        return best(inner), best(half)


def worth_it(ms32: float, ms16: float) -> bool:
    return ms16 <= GAIN_MIN * ms32
