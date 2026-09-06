"""⏱ Скільки триватиме трен і скільки коштуватиме — до того, як платити.

Брат `cloud/sizing.py`, а не імпорт: там осі — сторінки × ядра (читання
рахує процесор), тут — рядки × епохи × клас карти (трен рахує карту).

🔴 Точки відліку ВИМІРЯНІ, а не виведені. Перша таблиця в дослідницькому
конвеєрі була вдвічі песимістична — число з коментаря помножили на
прискорення, яке в ньому вже сиділо, — і від цього залежав і вибір карти, і
відповідь «чи влізе в стелю часу». Тут для T4 і A100 стоїть замір
(`ptrain_summary.json`: 101 169 рядків, 17.4 хв/епоха на 2×T4, тобто ~33 хв
на одній), решта карт — оцінка з позначкою, а перший власний прогін
перекриває таблицю калібруванням (`calib.json`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Хвилин на епоху зі 100 тис. рядків, ОДНА карта, parseq-s, batch 64, amp.
#: (хвилини, чи виміряно, ~$/год оренди для порядку величини)
_CARDS: dict[str, tuple[float, bool, float]] = {
    "T4": (33.0, True, 1.0),
    "L4": (22.5, False, 1.25),
    "A10G": (20.5, False, 1.6),
    "3090": (18.0, False, 0.3),
    "4090": (12.0, False, 0.45),
    "A100": (12.0, True, 2.7),
    "H100": (8.5, False, 4.7),
    "V100": (26.0, False, 0.5),
    #: Побутова 4-гігабайтна карта: батч 64 не влазить, темп ~T4/2.5 — оцінка.
    "1650": (85.0, False, 0.0),
}
#: Холодний старт: розпакування корпусу, збірка алфавіту, базова валідація.
STARTUP_MIN = 8.0
#: Що беремо для невідомої карти — найповільніше з відомих, свідомо.
UNKNOWN_CARD = "T4"

_CLASS_RE = re.compile(r"(H100|A100|A10G|A10|L4|T4|V100|4090|3090|1650)", re.IGNORECASE)


def gpu_class(name: str) -> str:
    """`NVIDIA GeForce RTX 3090` → `3090`; невідома → `T4` (песимістично)."""
    m = _CLASS_RE.search(name or "")
    if not m:
        return UNKNOWN_CARD
    got = m.group(1).upper()
    return "A10G" if got == "A10" else got


@dataclass
class Estimate:
    gpu: str
    rows: int
    epochs: int
    min_per_epoch: float
    hours: float
    usd: float
    measured: bool
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"gpu": self.gpu, "rows": self.rows, "epochs": self.epochs,
                "min_per_epoch": round(self.min_per_epoch, 1), "hours": round(self.hours, 2),
                "usd": round(self.usd, 2), "measured": self.measured, "notes": self.notes}


def predict(rows: int, epochs: int, gpu: str, *, calib: dict[str, Any] | None = None,
            usd_per_hour: float | None = None) -> Estimate:
    """Години й ціна для `rows` рядків × `epochs` епох на карті `gpu`.

    `calib` — `{клас: {"rows_per_sec": …}}` з власних прогонів; він перекриває
    таблицю: власний замір на власній машині точніший за чужий.
    """
    cls = gpu_class(gpu)
    minutes, measured, price = _CARDS.get(cls, _CARDS[UNKNOWN_CARD])
    notes: list[str] = []
    if cls == UNKNOWN_CARD and not _CLASS_RE.search(gpu or ""):
        notes.append(f"карта «{gpu or '—'}» невідома таблиці — рахую як {UNKNOWN_CARD}")
    own = (calib or {}).get(cls) or {}
    rps = float(own.get("rows_per_sec") or 0)
    if rps > 0:
        minutes = 100_000 / rps / 60.0
        measured = True
        notes.append(f"за власним заміром: {rps:.0f} рядків/с")
    elif not measured:
        notes.append(f"для {cls} час оцінений, не виміряний; перший прогін відкалібрує")
    per_epoch = minutes * rows / 100_000.0
    hours = (STARTUP_MIN + per_epoch * epochs) / 60.0
    rate = usd_per_hour if usd_per_hour is not None else price
    return Estimate(gpu=cls, rows=rows, epochs=epochs, min_per_epoch=per_epoch,
                    hours=hours, usd=hours * rate, measured=measured, notes=notes)


def fits_wall(est: Estimate, wall_limit_h: float) -> tuple[bool, int]:
    """Чи влізе трен у стелю; якщо ні — на якій епосі раннер сам зупиниться."""
    if wall_limit_h <= 0 or est.hours <= wall_limit_h:
        return True, est.epochs
    if est.min_per_epoch <= 0:
        return False, 0
    fits = int((wall_limit_h * 60.0 - STARTUP_MIN) / est.min_per_epoch)
    return False, max(0, fits)


def calibration_from_summary(summary: dict[str, Any], gpu: str) -> dict[str, Any] | None:
    """`rows_per_sec` і пік пам'яті з `ptrain_summary.json` — для `calib.json`."""
    hist = [r for r in (summary.get("history") or []) if isinstance(r, dict)]
    rps = [float(r["rows_per_sec"]) for r in hist if r.get("rows_per_sec")]
    peak = [float(r["gpu_peak_gib"]) for r in hist if r.get("gpu_peak_gib")]
    if not rps:
        return None
    return {"gpu": gpu_class(gpu), "rows_per_sec": round(sum(rps) / len(rps), 1),
            "gpu_peak_gib": round(max(peak), 2) if peak else None,
            "n_train": int(summary.get("n_train") or 0),
            "world_size": int(summary.get("world_size") or 1)}
