"""Реєстр опису фонду — «що взагалі існує в архівному фонді».

Третє сховище поруч із бібліотекою («що ми маємо») і реєстром справ («що ми
зробили»). Живе як `data/raw/<slug>/f<фонд>_opys_merged.tsv`.

Реєстр можна взяти готовим (пак довідників, `nysh catalog install`) або зібрати
самому: `fonds.collect` складає джерела в `registry/<джерело>.tsv`,
`fonds.merge` зводить їх у реєстр фонду. Цей модуль — тільки читалка обох.

⚠ Збирачів у пакеті менше, ніж джерел у злитому реєстрі: воно читає файли, а
не збирачів, тож джерело без свого збирача (транскрипція Вікіджерел, OCR
опису, алфавітка архіву) просто кладеться в теку руками й підхоплюється.
Відсутній файл — порожнє джерело, а не помилка.

Модуль навмисно без `typer`/`rich`/FastAPI: його читають і CLI, і веб-консоль.
"""
from nyshporka.fonds.registry import (  # noqa: F401
    REPO_LABEL,
    REPO_SLUG,
    discover_fonds,
    expected_frames,
    facets,
    filter_rows,
    invalidate,
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
