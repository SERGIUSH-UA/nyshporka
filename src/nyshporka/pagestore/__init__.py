"""Сховище знань про сторінки: data/pages/<REPO>/<fond>-<spr>.json (SoT, git).

Один раз подивився сторінку → записав тип/прізвища/географію → більше ніколи
не рендеримо даремно. Див. models.py (схема), store.py (merge/lock), query.py
(fuzzy), cli.py (nysh pages / nysh records).
"""
from nyshporka.pagestore.models import CaseFile, PageNote, Record, RecordPerson
from nyshporka.pagestore.query import grep_records, grep_surnames
from nyshporka.pagestore.store import (
    CaseRef,
    MergeReport,
    add_records,
    annotate_pages,
    case_status,
    load_case,
    resolve_case,
)

__all__ = [
    "CaseFile",
    "CaseRef",
    "MergeReport",
    "PageNote",
    "Record",
    "RecordPerson",
    "add_records",
    "annotate_pages",
    "case_status",
    "grep_records",
    "grep_surnames",
    "load_case",
    "resolve_case",
]
