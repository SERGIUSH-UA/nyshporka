"""MkDocs-хук сайту роду: `[[ID]]` без сторінки стає курсивом, а не битим лінком.

Підключається генерованим `mkdocs.yml` (`hooks:`) з `event_priority=100` —
раніше за roamlinks, щоб той не шумів про невідомі посилання. `[[X]]` лишається
посиланням, лише коли в сирцях є `X.md`; інакше (особа прихована, картки ще
немає) — `*X*`, щоб не загубити сам слід. Посилання на особу підписується її
іменем (`[[X|Ім'я]]` для roamlinks): голий `I9123` у тексті читач не розбере.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mkdocs.plugins import event_priority

_WIKILINK = re.compile(r"\[\[([^\[\]\|#]+?)\]\]")
_KNOWN: set[str] | None = None
_NAMES: dict[str, str] = {}


def _known(docs_dir: str) -> set[str]:
    return {p.stem for p in Path(docs_dir).rglob("*.md")}


def _names(docs_dir: str) -> dict[str, str]:
    """Імена осіб зі сторінкою — з пошукового покажчика сайту."""
    path = Path(docs_dir) / "assets" / "search.json"
    try:
        return {e["id"]: e["n"] for e in json.loads(path.read_text(encoding="utf-8"))
                if e.get("id") and e.get("n")}
    except (OSError, ValueError, TypeError):
        return {}


# Без extra `site` mkdocs нетипізований (декоратор `Any`), з ним — типізований:
# `unused-ignore` тримає перевірку зеленою в обох середовищах.
@event_priority(100)  # type: ignore[untyped-decorator, unused-ignore]
def on_page_markdown(markdown: str, *, page: Any, config: Any, files: Any, **kwargs: Any) -> str:
    global _KNOWN, _NAMES
    if _KNOWN is None:
        _KNOWN = _known(config["docs_dir"])
        _NAMES = _names(config["docs_dir"])
    known = _KNOWN

    def replace(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        if target not in known:
            return f"*{target}*"
        name = _NAMES.get(target)
        # Аліас roamlinks не може починатися з цифри й містити `|` чи `]`.
        if name and not name[:1].isdigit() and not set(name) & set("|]["):
            return f"[[{target}|{name}]]"
        return m.group(0)

    return _WIKILINK.sub(replace, markdown)


def on_files(files: Any, *, config: Any, **kwargs: Any) -> Any:
    """Кеш наново на кожну збірку — інакше `serve` не бачить нових сторінок."""
    global _KNOWN, _NAMES
    _KNOWN = _known(config["docs_dir"])
    _NAMES = _names(config["docs_dir"])
    return files
