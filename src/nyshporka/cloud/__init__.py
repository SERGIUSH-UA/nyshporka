"""☁️ Прогін справи на чужій машині.

Публічне тут — контракт бекенда (`base`) і реєстр (`registry`); решта модулів
складають захід: `probe` міряє залізо, `sizing` рахує шарди й години,
`transfer` обирає канал, `plan` показує все це до старту, `run` веде роботу,
`verify` доводить повноту, `state` пам'ятає захід між викликами. Поверх них —
оренда одним заходом: `frames` звіряє й стискає кадри до дороги, `money` рахує
вилку кошторису й вирішує, чи пускати без людини, `go` веде все від справи до
погашеної машини.

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
    ChannelDropped,
    CloudBackend,
    CloudError,
    Completed,
    Need,
    Session,
    bills,
    supports,
)
from nyshporka.cloud.registry import Registry, load

__all__ = ["AuthError", "Box", "BoxGone", "BoxNotReady", "ChannelDropped",
           "CloudBackend", "CloudError", "Completed", "Need", "Registry",
           "Session", "bills", "load", "supports"]
