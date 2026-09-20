"""Ворота пакета: кожна відмова мусить називати СВОЮ причину.

🔴 Спільне «пакет не пройшов перевірку» змушує вгадувати, що виправляти, і
найчастіше закінчується тим, що людина здається — а декод у неї насправді
добрий. Тому тест перевіряє не факт відмови, а її текст.

Головні ворота — знаменник. Декод на три сторінки, розданий як прочитана
справа на три тисячі, виробляє хибні нулі оптом: людина грепне його, не
знайде прізвища й закриє напрям, зробивши все правильно.
"""
from __future__ import annotations

import pytest
from _share import manifest_for

from nyshporka.share import gates

VOICE = {"run": "spr-8433", "model": "pysar_cyr_v17.pt", "engine": "parseq",
         "pages": 3, "lines": 6, "chars": 120}


def good():
    m = manifest_for([], pages=3, frames=3, lines=6, chars=120)
    m.decode["voices"] = [dict(VOICE)]
    m.refs = [{"source": "commons", "ref": "file:Test.djvu"}]
    return m


def test_a_healthy_bundle_passes() -> None:
    v = gates.check(good())
    assert v.passed, v.refusals
    assert not v.warnings


def test_scrap_of_a_case_is_refused_by_the_denominator() -> None:
    m = good()
    m.frames["total"] = 300
    m.decode["pages"] = 3
    v = gates.check(m)
    assert not v.passed
    assert any("уривок" in r for r in v.refusals)
    assert any("--partial" in r for r in v.refusals)


def test_explained_scrap_passes_but_stays_marked() -> None:
    """Уривок із поясненням їде — але отримувач бачить, що це уривок."""
    m = good()
    m.frames["total"] = 300
    v = gates.check(m, partial_why="прочитано лише аркуші з нашим селом")
    assert v.passed
    assert any(code == "partial" for code, _ in v.warnings)
    assert any("нашим селом" in text for _, text in v.warnings)


def test_unnamed_model_is_refused() -> None:
    m = good()
    m.decode["voices"] = [{**VOICE, "model": ""}]
    v = gates.check(m)
    assert not v.passed
    assert any("модел" in r.lower() for r in v.refusals)


def test_shredded_lines_are_refused() -> None:
    """Рядок у півтора символа — це сміття сегментації, не текст."""
    m = good()
    m.decode["lines"] = 600
    m.decode["chars"] = 900
    v = gates.check(m)
    assert not v.passed
    assert any("сміття сегментації" in r for r in v.refusals)


def test_mostly_blank_case_is_refused() -> None:
    m = good()
    m.decode["pages"] = 100
    m.decode["blank_pages"] = 95
    m.frames["total"] = 100
    v = gates.check(m)
    assert not v.passed
    assert any("не взяв письмо" in r for r in v.refusals)


def test_no_shifra_is_refused() -> None:
    m = good()
    m.case["shifra"] = ""
    v = gates.check(m)
    assert not v.passed
    assert any("шифр" in r for r in v.refusals)


def test_missing_license_is_refused() -> None:
    m = good()
    m.license = {}
    v = gates.check(m)
    assert not v.passed
    assert any("ліценз" in r for r in v.refusals)


def test_no_refs_warns_but_does_not_block() -> None:
    """Джерело сканів бажане, але його відсутність не робить текст марним."""
    m = good()
    m.refs = []
    v = gates.check(m)
    assert v.passed
    assert any(code == "no_refs" for code, _ in v.warnings)


def test_unknown_frame_count_warns_about_the_denominator() -> None:
    m = good()
    m.frames["total"] = 0
    v = gates.check(m)
    assert v.passed
    assert any(code == "frames_unknown" for code, _ in v.warnings)


@pytest.mark.parametrize("field", ["pages", "lines"])
def test_empty_decode_is_refused(field: str) -> None:
    m = good()
    m.decode[field] = 0
    v = gates.check(m)
    assert not v.passed


def test_describe_lists_every_reason_separately() -> None:
    m = good()
    m.decode["voices"] = [{**VOICE, "model": ""}]
    m.license = {}
    text = gates.describe(gates.check(m))
    assert text.count("✗") >= 2
