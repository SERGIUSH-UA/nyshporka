"""Спільний байткод шаблонів сайту (`render._MemoryBytecode`) чесний, доки
мовні фільтри не стоять на константі.

Jinja згортає фільтр із константним аргументом ще при компіляції: `"birth"|fact_label`
дав би переклад першої мови збірки всім сімом — а байткод тепер один на процес
(рецензія 20.10.2026).
"""
from __future__ import annotations

import re
from pathlib import Path

from nyshporka.site import filters as F
from nyshporka.site.render import TEMPLATES

#: Фільтри, що залежать від мови збірки (`filters.register`).
LANG_FILTERS = ("fact_label", "format_date")

_LITERAL = re.compile(r"""(?:"[^"]*"|'[^']*'|\b\d+)\s*\|\s*(""" + "|".join(LANG_FILTERS)
                      + r")\b")


def test_language_filters_are_the_ones_registered_per_language() -> None:
    from types import SimpleNamespace

    uk = SimpleNamespace(filters={}, globals={})
    en = SimpleNamespace(filters={}, globals={})
    F.register(uk, "uk")
    F.register(en, "en")
    for name in LANG_FILTERS:
        assert name in uk.filters and name in en.filters


def test_the_guard_sees_a_literal() -> None:
    assert _LITERAL.search('{{ "birth"|fact_label }}')
    assert _LITERAL.search("{{ 'x' | format_date }}")
    assert not _LITERAL.search("{{ fact.type|fact_label }}")


def test_no_language_filter_on_a_literal() -> None:
    bad = [f"{p.relative_to(TEMPLATES)}:{n}: {line.strip()}"
           for p in sorted(Path(TEMPLATES).rglob("*.j2"))
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if _LITERAL.search(line)]
    assert not bad, "мовний фільтр на константі — Jinja згорне його в першу мову:\n" + "\n".join(bad)
