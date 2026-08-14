"""Реєстр ОПИСУ фонду — «що взагалі існує в архівному фонді».

Третє сховище поруч із бібліотекою («що ми маємо») і реєстром справ («що ми
зробили»). Живе як `data/raw/<slug>/f<фонд>_opys_merged.tsv`, збирається
`scripts/fond_registry_merge.py` із п'яти джерел (опис-OCR · Вікіджерела ·
ukrfamily · Commons · дзеркало) плюс алфавітка архіву.

Модуль навмисно без `typer`/`rich`/FastAPI: його читають і CLI, і веб-консоль.
"""
from nyshporka.fonds.registry import (  # noqa: F401
    REPO_LABEL,
    REPO_SLUG,
    discover_fonds,
    facets,
    filter_rows,
    invalidate,
    live_on_disk,
    load_alfavitka,
    load_conflicts,
    load_coverage,
    load_rows,
    parse_key,
    registry_row,
    row_status,
    summarize,
)
