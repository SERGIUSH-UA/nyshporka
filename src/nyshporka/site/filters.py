"""Jinja2-фільтри для рендеру сайту: дати, факти, цитати — мовою збірки (`site.i18n`)."""

from __future__ import annotations

import json
import re
from typing import Any

from nyshporka.models import Fact, GedDate
from nyshporka.site import i18n as I18N

_MONTHS_UK = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)

_MONTHS_UK_NOMINATIVE = (
    "січень",
    "лютий",
    "березень",
    "квітень",
    "травень",
    "червень",
    "липень",
    "серпень",
    "вересень",
    "жовтень",
    "листопад",
    "грудень",
)

_FACT_LABELS = {
    "birth": "Народження",
    "death": "Смерть",
    "marriage": "Шлюб",
    "divorce": "Розлучення",
    "residence": "Місце проживання",
    "occupation": "Професія",
    "baptism": "Хрещення",
    "burial": "Поховання",
    "emigration": "Еміграція",
    "religion": "Віросповідання",
    "nationality": "Національність",
    "military": "Військова служба",
    "other": "Подія",
}


def format_date(date: GedDate | None, *, decade_only: bool = False, lang: str = "uk") -> str:
    """Конвертувати GedDate у читальний рядок мовою `lang`.

    `decade_only=True` — для приватних осіб: лишити лише десятиліття.
    """
    if date is None:
        return "—"

    if decade_only:
        year = _safe_year(date.value)
        if year is None:
            return "—"
        return _qualifier_prefix(date.qualifier, lang) + I18N.t(lang, "decade", y=year // 10 * 10)

    base = _format_value(date.value, date.precision, lang)
    if date.range_end:
        base += " – " + _format_value(date.range_end, date.precision, lang)
    return _qualifier_prefix(date.qualifier, lang) + base


def _months(lang: str, form: str) -> list[str]:
    return I18N.t(lang, f"months.{form}").split("|")


def _format_value(value: str, precision: str, lang: str = "uk") -> str:
    parts = value.split("-")
    if precision == "day" and len(parts) == 3:
        y, m, d = parts
        try:
            month = _months(lang, "gen")[int(m) - 1]
        except (ValueError, IndexError):
            return value
        # Англійська й німецька пишуть місяць перед днем чи з крапкою —
        # «12 March 1868» читається всюди, тож формат один, лише назва місяця
        # мовою збірки.
        return f"{int(d)} {month} {y}" if lang != "de" else f"{int(d)}. {month} {y}"
    if precision == "month" and len(parts) >= 2:
        y, m = parts[0], parts[1]
        try:
            return f"{_months(lang, 'nom')[int(m) - 1]} {y}"
        except (ValueError, IndexError):
            return value
    return parts[0] if parts else value


_QUALIFIERS = ("about", "before", "after", "between", "estimated", "calculated")


def _qualifier_prefix(qualifier: str, lang: str = "uk") -> str:
    return I18N.t(lang, f"q.{qualifier}") if qualifier in _QUALIFIERS else ""


def _safe_year(value: str) -> int | None:
    head = value.split("-")[0]
    try:
        return int(head)
    except ValueError:
        return None


def fact_label(fact_type: str, lang: str = "uk") -> str:
    key = f"f.{fact_type}"
    if key in I18N.S[I18N.DEFAULT]:
        return I18N.t(lang, key)
    return _FACT_LABELS.get(fact_type, fact_type.capitalize())


def fact_summary(fact: Fact, place_lookup: dict[str, str], *, decade_only: bool = False,
                 lang: str = "uk") -> str:
    """Один рядок: «**Народження:** 1 квітня 1868, [Село](../places/<ID>.md)»."""
    head = fact_label(fact.type, lang)
    bits: list[str] = []
    if fact.date:
        bits.append(format_date(fact.date, decade_only=decade_only, lang=lang))
    if fact.place_id:
        place_name = place_lookup.get(fact.place_id, fact.place_id)
        bits.append(f"[{place_name}](../places/{fact.place_id}.md)")
    if fact.value:
        bits.append(fact.value)
    body = ", ".join(bits) if bits else "—"
    cite = cite_marks(fact)
    return f"**{head}:** {body}{cite}"


def cite_marks(fact: Fact) -> str:
    """Footnote-маркери для всіх джерел факту: `[^S_X][^S_Y]`."""
    if not fact.citations:
        return ""
    seen: list[str] = []
    for c in fact.citations:
        if c.source_id not in seen:
            seen.append(c.source_id)
    return "".join(f"[^{sid}]" for sid in seen)


_WIKI = re.compile(r"\s*\[\[[^\]]+\]\]")
_EMPHASIS = re.compile(r"\*\*|__|(?<!\w)[*_](?!\s)|(?<!\s)[*_](?!\w)|`")


def plain(text: str | None) -> str:
    """Текст для підпису посилання: без `[[ID]]`, наголосів markdown і переносів.

    Квадратні дужки стають круглими: у підписі `[…](…)` вони закривали б його
    передчасно."""
    out = " ".join(_EMPHASIS.sub("", _WIKI.sub("", text or "")).split())
    return out.replace("[", "(").replace("]", ")")


#: Стани гіпотези в порядку показу: від того, що чекає рішення людини.
HYPOTHESIS_ORDER = ("awaiting", "open", "closed")


def hypothesis_status(lang: str = "uk") -> dict[str, str]:
    """Стан гіпотези → підпис мовою збірки."""
    return {st: I18N.t(lang, f"hyp.st.{st}") for st in HYPOTHESIS_ORDER}


#: Українські підписи станів — для тих, хто бере їх як дані (без мови збірки).
HYPOTHESIS_STATUS = hypothesis_status("uk")


def register(env: Any, lang: str = "uk") -> None:
    """Зареєструвати фільтри/глобали у Jinja env — мовою `lang`."""
    def _date(date: GedDate | None, *, decade_only: bool = False) -> str:
        return format_date(date, decade_only=decade_only, lang=lang)

    def _summary(fact: Fact, place_lookup: dict[str, str], *, decade_only: bool = False) -> str:
        return fact_summary(fact, place_lookup, decade_only=decade_only, lang=lang)

    env.filters["format_date"] = _date
    env.filters["fact_label"] = lambda ft: fact_label(ft, lang)
    env.filters["plain"] = plain
    # Рядок у лапках без екранування кирилиці: `tojson` пише \uXXXX, і
    # заголовок врізки Markdown показав би саме його.
    env.filters["q"] = lambda v: json.dumps(str(v), ensure_ascii=False)
    env.globals["hyp_status"] = hypothesis_status(lang)
    env.globals["fact_summary"] = _summary
    env.globals["cite_marks"] = cite_marks
    env.globals["lang"] = lang
    env.globals["t"] = lambda key, **kw: I18N.t(lang, key, **kw)
