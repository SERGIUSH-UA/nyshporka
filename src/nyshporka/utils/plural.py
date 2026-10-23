"""Українська множина після числа: «1 справа · 2 справи · 5 справ»."""
from __future__ import annotations


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова під число. Число тут бачать щоразу, і «1 справ» муляє."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def cases(n: int) -> str:
    """«{n} справа / справи / справ»."""
    return f"{n} {plural(n, 'справа', 'справи', 'справ')}"
