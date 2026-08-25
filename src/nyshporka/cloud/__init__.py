"""☁️ Прогін справи на чужій машині.

Публічне тут — контракт бекенда (`base`) і реєстр (`registry`); решта модулів
складають захід: `probe` міряє залізо, `sizing` рахує шарди й години,
`transfer` обирає канал, `plan` показує все це ДО старту, `run` веде роботу,
`verify` доводить повноту, `state` пам'ятає захід між викликами.

🔴 Порядок, який тут не обговорюється: **забрати → звірити → і лише тоді
звільнити машину**. Він виглядає як дрібниця рівно доти, доки одного разу не
буде забрано 203 сторінки з 323 і погашено машину, на якій лежали решта 120.
"""
from __future__ import annotations

from nyshporka.cloud.base import (
    AuthError,
    Box,
    BoxGone,
    BoxNotReady,
    CloudBackend,
    CloudError,
    Completed,
    Need,
    Session,
    bills,
    supports,
)
from nyshporka.cloud.registry import Registry, load

__all__ = ["AuthError", "Box", "BoxGone", "BoxNotReady", "CloudBackend",
           "CloudError", "Completed", "Need", "Registry", "Session", "bills",
           "load", "supports"]
