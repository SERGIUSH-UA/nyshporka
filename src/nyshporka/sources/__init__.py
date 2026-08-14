"""📥 Звідки береться матеріал: архіви, дзеркала, локальна тека.

Одна форма на всіх, тому «знайшов у каталозі → завантажив → прочитав» виглядає
однаково і в браузері, і в командному рядку, і для агента. Нове джерело
додається пакетом-плагіном через entry point `nyshporka.sources`.
"""

from nyshporka.sources.base import (
    FetchResult,
    Hit,
    Manifest,
    Node,
    Sheet,
    Source,
    SourceError,
    supports,
)
from nyshporka.sources.registry import Registry, load

__all__ = ["FetchResult", "Hit", "Manifest", "Node", "Registry", "Sheet",
           "Source", "SourceError", "load", "supports"]
