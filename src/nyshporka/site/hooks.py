"""MkDocs-хук сайту роду: `[[ID]]` без сторінки стає курсивом, а не битим лінком.

Підключається генерованим `mkdocs.yml` (`hooks:`) з `event_priority=100` —
раніше за roamlinks, щоб той не шумів про невідомі посилання. `[[X]]` лишається
посиланням, лише коли в сирцях є `X.md`; інакше (особа прихована, картки ще
немає) — `*X*`, щоб не загубити сам слід.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mkdocs.plugins import event_priority

_WIKILINK = re.compile(r"\[\[([^\[\]\|#]+?)\]\]")
_KNOWN: set[str] | None = None


def _known(docs_dir: str) -> set[str]:
    return {p.stem for p in Path(docs_dir).rglob("*.md")}


@event_priority(100)  # type: ignore[untyped-decorator]  # mkdocs без типів (extra site)
def on_page_markdown(markdown: str, *, page: Any, config: Any, files: Any, **kwargs: Any) -> str:
    global _KNOWN
    if _KNOWN is None:
        _KNOWN = _known(config["docs_dir"])
    known = _KNOWN

    def replace(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        return m.group(0) if target in known else f"*{target}*"

    return _WIKILINK.sub(replace, markdown)


def on_files(files: Any, *, config: Any, **kwargs: Any) -> Any:
    """Кеш наново на кожну збірку — інакше `serve` не бачить нових сторінок."""
    global _KNOWN
    _KNOWN = _known(config["docs_dir"])
    return files
