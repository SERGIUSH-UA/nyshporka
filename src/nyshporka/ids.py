"""Стабільні внутрішні ID: GEDCOM-XREF (`@I1@`) → літера-префікс + 4 цифри.

Префікси: `I` особа, `F` родина, `PL` місце. Джерела нумерації не мають —
у них читабельний slug.

⚠ Повні приклади ідентифікаторів тут навмисно не наводяться: у робочому
просторі це посилання на конкретних людей, і ворота проти приватних даних
(`tools/scan_private.py`) шукають саме такий вигляд.
"""

from __future__ import annotations


def person_id(index: int) -> str:
    """Послідовний ID особи (1-based)."""
    return f"I{index:04d}"


def family_id(index: int) -> str:
    return f"F{index:04d}"


def place_id(index: int) -> str:
    return f"PL{index:04d}"


def source_id(slug: str) -> str:
    """ID джерела — slug, бо їх мало і вони мають читатись."""
    return slug
