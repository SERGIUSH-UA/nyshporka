"""🧾 Збирачі реєстру опису: «що взагалі існує у фонді».

Пакет донедавна реєстр опису лише ЧИТАВ — складав його зовнішній конвеєр. Тобто
на питання «які справи є у фонді» застосунок відповідав рівно доти, доки хтось
приніс готовий файл, а зібрати його самому не міг.
"""
from nyshporka.fonds.collect.base import (
    Blind,
    CollectError,
    Collector,
    CollectResult,
    Plan,
    Target,
)
from nyshporka.fonds.collect.registry import Registry, load

__all__ = ["Blind", "CollectError", "CollectResult", "Collector", "Plan",
           "Registry", "Target", "load"]
