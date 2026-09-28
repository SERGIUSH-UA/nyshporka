"""Jinja2-фільтри для рендеру звіту: дати, факти, цитати — українською."""

from __future__ import annotations

from typing import Any

from nyshporka.models import Fact, GedDate

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


def format_date(date: GedDate | None, *, decade_only: bool = False) -> str:
    """Конвертувати GedDate у читальний український рядок.

    `decade_only=True` — для приватних осіб: лишити лише десятиліття.
    """
    if date is None:
        return "—"

    if decade_only:
        year = _safe_year(date.value)
        if year is None:
            return "—"
        return _qualifier_prefix(date.qualifier) + f"{year // 10 * 10}-х"

    base = _format_value(date.value, date.precision)
    if date.range_end:
        base += " – " + _format_value(date.range_end, date.precision)
    return _qualifier_prefix(date.qualifier) + base


def _format_value(value: str, precision: str) -> str:
    parts = value.split("-")
    if precision == "day" and len(parts) == 3:
        y, m, d = parts
        try:
            return f"{int(d)} {_MONTHS_UK[int(m) - 1]} {y}"
        except (ValueError, IndexError):
            return value
    if precision == "month" and len(parts) >= 2:
        y, m = parts[0], parts[1]
        try:
            return f"{_MONTHS_UK_NOMINATIVE[int(m) - 1]} {y}"
        except (ValueError, IndexError):
            return value
    return parts[0] if parts else value


def _qualifier_prefix(qualifier: str) -> str:
    return {
        "exact": "",
        "about": "бл. ",
        "before": "до ",
        "after": "після ",
        "between": "між ",
        "estimated": "приблизно ",
        "calculated": "за обчисленням ",
    }.get(qualifier, "")


def _safe_year(value: str) -> int | None:
    head = value.split("-")[0]
    try:
        return int(head)
    except ValueError:
        return None


def fact_label(fact_type: str) -> str:
    return _FACT_LABELS.get(fact_type, fact_type.capitalize())


def fact_summary(fact: Fact, place_lookup: dict[str, str], *, decade_only: bool = False) -> str:
    """Один рядок: «**Народження:** 1 квітня 1868, [Село](../places/<ID>.md)»."""
    head = fact_label(fact.type)
    bits: list[str] = []
    if fact.date:
        bits.append(format_date(fact.date, decade_only=decade_only))
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


def register(env: Any) -> None:
    """Зареєструвати фільтри/глобали у Jinja env."""
    env.filters["format_date"] = format_date
    env.filters["fact_label"] = fact_label
    env.globals["fact_summary"] = fact_summary
    env.globals["cite_marks"] = cite_marks
