"""🗂 Реєстр збирачів — дзеркало реєстру джерел, і навмисно до останнього правила.

🔴 Заборона затінити вбудований збирач тут навіть гостріша, ніж для джерел:
збирач пише в реєстр опису, а за реєстром людина вирішує, що замовляти в архіві.
Підмінений збирач — це не «інша відповідь», це чужий перелік документів, який
виглядає як наш.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nyshporka.fonds.collect.base import Collector

#: Точка розширення для чужих збирачів.
ENTRY_POINT_GROUP = "nyshporka.collectors"


@dataclass
class Registry:
    collectors: dict[str, Collector] = field(default_factory=dict)
    broken: list[tuple[str, str]] = field(default_factory=list)

    def get(self, collector_id: str) -> Collector | None:
        return self.collectors.get(collector_id)

    def all(self) -> list[Collector]:
        return [self.collectors[k] for k in sorted(self.collectors)]

    def with_cap(self, cap: str) -> list[Collector]:
        return [c for c in self.all() if cap in c.caps]


def _builtin(workspace: Path | None = None) -> list[Collector]:
    """Вбудовані збирачі. Ліниві імпорти: кожен тягне свої extras.

    Простір передається, а не резолвиться всередині — з тієї ж причини, що й у
    джерел: збирач, який шукає простір сам, стає другим резолвером поруч із
    головним, і вони розходяться тихо (склали в один корінь, читаємо з іншого).
    """
    out: list[Collector] = []
    return out


def _from_entry_points() -> tuple[list[Collector], list[tuple[str, str]]]:
    from importlib.metadata import entry_points

    found: list[Collector] = []
    broken: list[tuple[str, str]] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
            got = obj() if callable(obj) else obj
            if not getattr(got, "id", ""):
                raise ValueError("збирач не має `id`")
            found.append(got)
        except Exception as exc:   # чужий код падає як хоче — це не наша поломка
            broken.append((ep.name, f"{type(exc).__name__}: {exc}"))
    return found, broken


def load(workspace: Path | None = None) -> Registry:
    reg = Registry()
    for c in _builtin(workspace):
        reg.collectors[c.id] = c
    plugins, broken = _from_entry_points()
    reg.broken = broken
    for c in plugins:
        if c.id in reg.collectors:
            reg.broken.append((c.id, "збігається з іменем вбудованого збирача"))
            continue
        reg.collectors[c.id] = c
    return reg
