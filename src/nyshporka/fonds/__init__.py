"""Реєстр ОПИСУ фонду — «що взагалі існує в архівному фонді».

Третє сховище поруч із бібліотекою («що ми маємо») і реєстром справ («що ми
зробили»). Живе як `data/raw/<slug>/f<фонд>_opys_merged.tsv`.

⚠ Цей пакет реєстр опису **читає**, а не збирає. Зводять його з кількох джерел
(опис-OCR · Вікіджерела · дзеркала · алфавітка архіву) окремим конвеєром, і
сюди він приходить готовим — паком довідників (`nysh catalog install`) або
файлом у просторі. Тобто «реєстру немає» тут означає «не встановлено», а не
«зберіть його самі».

Модуль навмисно без `typer`/`rich`/FastAPI: його читають і CLI, і веб-консоль.
"""
from nyshporka.fonds.registry import (  # noqa: F401
    REPO_LABEL,
    REPO_SLUG,
    discover_fonds,
    facets,
    filter_rows,
    invalidate,
    expected_frames,
    live_frames,
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
