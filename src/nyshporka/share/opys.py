"""🗂 Опис справи для картки каталогу: паспорт, реєстр опису, сховище сторінок.

Картка книги в пулі має кілька полів (назва, жанр, роки, місця, прізвища), і
без опису її заповнює агент модерації з вибірки тексту. Тут те саме
збирається з того, що дослідник уже встановив: паспорт теки справи, рядок
реєстру опису фонду, аркуші, вичитані оком.

🔴 Лише БІЛИМ СПИСКОМ полів. Паспорт і сховище сторінок — робочі файли
дослідження: у `note`, `clan_relevance`, `comment` лежать нотатки про рід,
посилання на осіб дерева й міркування, які не призначались нікому. Прибрати
з пакета «відомо приватне» означало б пропустити наступне приватне поле,
яке хтось допише в паспорт через місяць.

Мовчить у будь-якій халепі, як і `publish._links_from_registry`: немає
реєстру чи сховища — немає й відповідного ключа, пакування не падає.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

#: Поля паспорта, які їдуть у `case` як є. Решта паспорта не їде НІКОЛИ.
SIDECAR_FIELDS = ("repository", "collection", "sheets", "langs", "script")

#: Поля рядка реєстру опису, які їдуть у `case.details.registry`.
REGISTRY_FIELDS = ("title", "title_src", "folios", "num_src", "year_from", "year_to")

MAX_SURNAMES = 300
MAX_PLACES = 40

_YEAR_MIN, _YEAR_MAX = 1400, 2100
#: Слово-прізвище: перше слово запису до пробілу, коми чи дужки.
_FIRST_WORD = re.compile(r"^[^\s,;()\[\]]+")


def genre(side: dict[str, Any], title: str = "") -> tuple[str, list[str]]:
    """Код жанру для картки й повний перелік типів записів.

    Картка тримає ОДИН код зі словника жанрів пакета (`record_type_labels`),
    а метрична книга дає три — народження, шлюби, смерті. Вибрати з них
    один означало б записати зведену метрику як «народження», тож код
    ставиться лише тоді, коли тип однозначний; перелік їде окремо.
    """
    from nyshporka.library import _infer_record_types

    raw = str(side.get("doc_type") or side.get("record_type") or "")
    types = [str(t) for t in _infer_record_types(raw, str(side.get("title") or ""), title)]
    return (types[0] if len(types) == 1 else ""), types


def sidecar_extras(side: dict[str, Any]) -> dict[str, Any]:
    """Опис справи з паспорта — лише поля з білого списку."""
    out: dict[str, Any] = {}
    for key in SIDECAR_FIELDS:
        val = side.get(key)
        if val not in (None, "", [], {}):
            out[key] = val
    raw_type = str(side.get("record_type") or "").strip()
    if raw_type:
        out["record_type"] = raw_type
    dates = [str(side.get(k) or "").strip() for k in ("date_started", "date_ended")]
    if any(dates):
        out["dates"] = dates
    return out


def registry_row(shifra: str) -> dict[str, Any] | None:
    """Рядок реєстру опису для шифри — з пробою літери обома письмами."""
    if not shifra.strip():
        return None
    try:
        from nyshporka.fonds.registry import registry_row as _row
        from nyshporka.pagestore import resolve_case
        from nyshporka.share.publish import _letter_variants

        ref = resolve_case(shifra)
        spr = str(ref.spr or "")
        i = len(spr)
        while i and not spr[i - 1].isdigit():
            i -= 1
        number, letter = spr[:i], spr[i:]
        for variant in _letter_variants(letter):
            row, _ = _row(ref.repo, ref.fond, ref.opys or "", number, variant)
            if row:
                return row
    except Exception:
        # Широко й навмисно: реєстр не обов'язковий, а падінь у нього багато
        # різних — немає простору, немає фонду, битий TSV.
        return None
    return None


def from_registry(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return {k: row[k] for k in REGISTRY_FIELDS if row.get(k) not in (None, "")}


def _surname(entry: str) -> str:
    """Прізвище з запису сховища: «Ковальський Іван (дяк, 40)» → «Ковальський».

    Записи зі знаком сумніву не беруться: картка показує встановлене, а не
    здогад, який дослідник сам позначив як непевний.
    """
    entry = entry.strip()
    if not entry or "?" in entry or "…" in entry:
        return ""
    m = _FIRST_WORD.match(entry)
    word = m.group(0).strip(".:-") if m else ""
    if len(word) < 3 or not word[0].isupper():
        return ""
    return word


def from_pagestore(shifra: str, frames_total: int = 0) -> dict[str, Any]:
    """Що вичитано оком: типи аркушів, прізвища, місця, роки — зі знаменником.

    🔴 Прізвища, місця й роки — лише з аркушів `status=full`. `partial`
    означає «дивились під іншим кутом», і перелік там неповний за
    визначенням; у картці він читався б як повний.
    """
    try:
        from nyshporka.pagestore import load_case, resolve_case

        cf = load_case(resolve_case(shifra))
    except Exception:
        return {}
    if cf is None or not cf.pages:
        return {}
    notes = list(cf.pages.values())
    full = [n for n in notes if n.status == "full"]
    surnames = list(dict.fromkeys(
        s for n in full for s in (_surname(x) for x in n.surnames) if s))
    places = list(dict.fromkeys(
        p.strip() for n in full for p in n.places if p.strip() and "?" not in p))
    years = sorted({y for n in full for y in n.years if _YEAR_MIN <= y <= _YEAR_MAX})
    out: dict[str, Any] = {
        "pages_noted": len(notes),
        "pages_full": len(full),
        "page_types": dict(Counter(str(n.page_type) for n in notes).most_common()),
    }
    if frames_total:
        out["frames_total"] = int(frames_total)
    if surnames:
        out["surnames"] = surnames[:MAX_SURNAMES]
    if places:
        out["places"] = places[:MAX_PLACES]
    if years:
        out["years"] = [years[0], years[-1]]
    return out


def build(shifra: str, *, row: dict[str, Any] | None, frames_total: int,
          geometry_pages: int, text_pages: int) -> dict[str, Any]:
    """Блок `case.details`. Порожні частини не пишуться.

    ⚠ Не `case.opys`: там уже лежить номер опису фонду.
    """
    out: dict[str, Any] = {}
    reg = from_registry(row)
    if reg:
        out["registry"] = reg
    pages = from_pagestore(shifra, frames_total)
    if pages:
        out["pagestore"] = pages
    if text_pages:
        out["geometry"] = {"pages": int(geometry_pages), "of": int(text_pages)}
    return out
