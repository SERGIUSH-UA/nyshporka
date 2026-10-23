"""Рамка одного виклику операції: те, що не змінюється за час відповіді, рахується раз.

🔴 Відбитки джерел (бібліотека, пак архівів, зріз пулу, карта переїзду ключів)
перевіряються перед кожним читанням кешу — і це правильно для довгоживучого
демона. Але операція, що обходить тисячі справ, питала той самий відбиток
тисячі разів: «Віддати» витрачало на `stat` понад половину своїх 5–8 с
(замір 23.10.2026). У межах однієї відповіді диск один, тож і відбиток один.

⚠ Лише для операцій, що НЕ пишуть (`Op.mutates=False`): та, що пише, між своїми
кроками справді змінює джерела, і застиглий відбиток збрехав би саме там.
Рамку відкриває `Registry.call`; поза нею `once()` просто рахує щоразу.
Той самий підхід уже мав перелік прогонів (`htr_store.one_listing`).
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Hashable, Iterator
from contextvars import ContextVar
from typing import Any, TypeVar

T = TypeVar("T")

_SCOPE: ContextVar[dict[Hashable, Any] | None] = ContextVar("nysh_read_scope", default=None)


@contextlib.contextmanager
def read_scope() -> Iterator[None]:
    """Відкрити рамку; вкладена рамка користується зовнішньою."""
    if _SCOPE.get() is not None:
        yield
        return
    tok = _SCOPE.set({})
    try:
        yield
    finally:
        _SCOPE.reset(tok)


def once(key: Hashable, fn: Callable[[], T]) -> T:
    """`fn()` раз на рамку за ключем; поза рамкою — щоразу."""
    box = _SCOPE.get()
    if box is None:
        return fn()
    if key not in box:
        box[key] = fn()
    return box[key]  # type: ignore[no-any-return]
