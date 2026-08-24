"""⚙️ Доступ до реєстру операцій.

Окремий модуль від `core.ops` навмисно: там МЕХАНІЗМ, тут — гарантія, що
вбудовані операції зареєстровані. Інакше споживач, який імпортував лише
механізм, отримував би порожній реєстр і вважав, що операцій немає.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Імпорт наповнює реєстр (декоратори виконуються при завантаженні модуля).
from nyshporka import ops_builtin as _builtin  # noqa: F401  (потрібен саме побічний ефект)
from nyshporka import ops_catalog as _catalog  # noqa: F401  (те саме: реєстрація)
from nyshporka import ops_library as _library  # noqa: F401  (те саме: реєстрація)
from nyshporka.core.envelope import Envelope
from nyshporka.core.ops import REGISTRY, Op, Registry

__all__ = ["REGISTRY", "Op", "Registry", "all_ops", "call", "for_agent",
           "for_sections", "get", "sections_in_use"]


def call(name: str, payload: dict[str, Any] | None = None) -> Envelope:
    return REGISTRY.call(name, payload)


def get(name: str) -> Op | None:
    return REGISTRY.get(name)


def all_ops() -> list[Op]:
    return REGISTRY.all()


def for_agent() -> list[Op]:
    return REGISTRY.for_agent()


def for_sections(active: Iterable[str]) -> list[Op]:
    return REGISTRY.for_sections(active)


def sections_in_use() -> frozenset[str]:
    return REGISTRY.sections_in_use()
