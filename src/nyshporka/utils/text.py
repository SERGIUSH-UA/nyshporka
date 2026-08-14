"""Текстові утиліти: slug, нормалізатори."""

from __future__ import annotations

import re

from unidecode import unidecode


def slugify(s: str) -> str:
    """Канонічний URL-friendly slug: ASCII lowercase з тире.

    Кирилиця транслітерується через `unidecode` (Сікорський → Sikorskyi).
    Усе, що не [a-z0-9] — заміняється тире, послідовності тире зливаються.
    """
    ascii_text = unidecode(s).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug
