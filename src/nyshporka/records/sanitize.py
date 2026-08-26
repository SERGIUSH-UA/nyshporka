"""М'яке приведення виводу агента до схеми — щоб дрібниця не коштувала акту.

Схема сховища навмисно сувора (`extra="forbid"`): вона ловить одруківки, які
інакше тихо осідали б у канонічній базі. Але на масовому прогоні виявилось, що
за цю суворість платить не одруківка, а цілий вичитаний акт: агент пише
`page_type: "summary"` замість `"other"`, `rtype: "reception_orthodoxy"` замість
`"conversion"`, додає власне поле `clergy_change` — і запис із десятком імен
гине через один ключ.

Тому перед валідацією payload проходить тут. Головне правило: **нічого не
викидаємо мовчки**. Синоніми зводяться до словника схеми, а невідомі поля
переїжджають у `comment` — так інформація, яку агент вважав вартою запису,
лишається читабельною для людини, навіть якщо структура її не передбачила.
"""
from __future__ import annotations

import json
from typing import Any

from nyshporka.pagestore.models import PageNote, Record, RecordPerson

# синоніми, які агенти вигадують для наявних типів
_RTYPE_ALIASES = {
    "reception_orthodoxy": "conversion", "reception": "conversion",
    "joining": "conversion", "присоединение": "conversion",
    "приєднання": "conversion", "convert": "conversion",
    "birth_record": "birth", "marriage_record": "marriage",
    "death_record": "death", "burial": "death",
    "summary": "tally", "total": "tally", "підсумок": "tally",
}
_PAGETYPE_ALIASES = {
    "summary": "other", "annual_summary": "other", "register": "other",
    "flyleaf_back": "flyleaf", "endpaper": "flyleaf",
    "titlepage": "title", "title_page": "title", "empty": "blank",
    "unreadable": "illegible", "contents": "index",
    # роздільник секції («Часть вторая. О бракосочетавшихся») — це титул
    # наступної частини книги, і саме він датує межу секцій
    "divider": "title", "separator": "title", "section": "title",
}
_ROLE_ALIASES = {
    "newborn": "child", "infant": "child", "baby": "child",
    "husband": "spouse", "wife": "spouse",
    "guarantor": "witness", "porucitel": "witness", "поручитель": "witness",
    "recipient": "godfather", "vospriemnik": "godfather",
    "receiver": "godmother", "vospriemnica": "godmother",
    "clergy": "priest", "deacon": "priest", "sexton": "priest",
}
_SEX = {"m": "m", "f": "f", "м": "m", "ч": "m", "ж": "f",
        "male": "m", "female": "f", "мужеска": "m", "женска": "f"}

_PERSON_FIELDS = set(RecordPerson.model_fields)
_RECORD_FIELDS = set(Record.model_fields)
_PAGE_FIELDS = set(PageNote.model_fields)


def _stash(extra: dict[str, Any]) -> str:
    """Невідомі поля — у людський рядок для `comment`, а не в небуття."""
    parts = []
    for k, v in extra.items():
        if v in (None, "", [], {}):
            continue
        val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        parts.append(f"{k}: {val}")
    return "; ".join(parts)


def _split(payload: dict[str, Any], known: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    item = {k: v for k, v in payload.items() if k in known}
    extra = {k: v for k, v in payload.items() if k not in known}
    return item, extra


def _merge_comment(item: dict[str, Any], extra_text: str) -> None:
    if not extra_text:
        return
    old = (item.get("comment") or "").strip()
    item["comment"] = f"{old} ⟂ {extra_text}"[:600] if old else extra_text[:600]


def clean_person(raw: dict[str, Any]) -> dict[str, Any]:
    person, extra = _split(raw, _PERSON_FIELDS)
    role = str(person.get("role") or "other").strip().lower()
    person["role"] = _ROLE_ALIASES.get(role, role)
    sex = person.get("sex")
    if sex is not None:
        person["sex"] = _SEX.get(str(sex).strip().lower())
    if extra:
        note = (person.get("note") or "").strip()
        text = _stash(extra)
        person["note"] = f"{note}; {text}"[:400] if note else text[:400]
    return person


def clean_record(raw: dict[str, Any]) -> dict[str, Any]:
    rec, extra = _split(raw, _RECORD_FIELDS)
    rtype = str(rec.get("rtype") or "other").strip().lower()
    rec["rtype"] = _RTYPE_ALIASES.get(rtype, rtype)
    rec["persons"] = [clean_person(p) for p in (rec.get("persons") or [])
                      if isinstance(p, dict)]
    # скани без розширення трапляються постійно; сховище ключується саме ними
    scans = [str(s) for s in (rec.get("scans") or []) if s]
    rec["scans"] = [s if "." in s else f"{s}.JPG" for s in scans]
    _merge_comment(rec, _stash(extra))
    return rec


def clean_page(raw: dict[str, Any]) -> dict[str, Any]:
    page, extra = _split(raw, _PAGE_FIELDS)
    pt = str(page.get("page_type") or "other").strip().lower()
    page["page_type"] = _PAGETYPE_ALIASES.get(pt, pt)
    scan = str(page.get("scan") or "").strip()
    if scan and "." not in scan:
        scan = f"{scan}.JPG"
    page["scan"] = scan
    _merge_comment(page, _stash(extra))
    return page


def clean_payload(payload: Any) -> dict[str, Any]:
    """Вивід агента → payload, готовий до валідації."""
    if isinstance(payload, list):
        payload = {"records": payload}
    if not isinstance(payload, dict):
        return {"pages": [], "records": []}
    return {
        "pages": [clean_page(p) for p in (payload.get("pages") or [])
                  if isinstance(p, dict)],
        "records": [clean_record(r) for r in (payload.get("records") or [])
                    if isinstance(r, dict)],
    }
