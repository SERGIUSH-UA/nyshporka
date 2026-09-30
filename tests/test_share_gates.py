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


def _no_refs_text(m) -> str:
    return next(t for code, t in gates.check(m).warnings if code == "no_refs")


def test_no_refs_does_not_advise_the_link_already_given() -> None:
    """🔴 Порада мусить бути виконуваною: `--link` уже в пакеті — не радити його знову.

    Звіт користувача 29.09.2026: 24 пакети з посиланням на ARCHIUM у `links`
    і порожнім `refs` отримували «додайте --link», а виконана порада
    попередження не прибирала. Людина, що бачить вічне хибне попередження,
    перестає читати й справжні.
    """
    m = good()
    m.refs = []
    m.links = [{"label": "Скани", "url": "https://example.org/scans/1"}]
    text = _no_refs_text(m)
    assert "--link" not in text
    assert "example.org" in text, "назвати, яке саме посилання не розпізнано"

    m.links = [{"label": "Скани ARCHIUM",
                "url": "https://archium.cdiak.archives.gov.ua/file-viewer/35112/"}]
    text = _no_refs_text(m)
    assert "ARCHIUM" in text or "archium" in text
    assert "pack" in text, "відомий хост стає джерелом при перепакуванні"

    m.links = []
    assert "--link" in _no_refs_text(m), "без посилань порада лишається"


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


# ── коди відмов і номер політики ──────────────────────────────────────────────

def test_vidmova_nese_kod_pravyla_i_pole() -> None:
    """🔴 Агент і сценарій черги розрізняють відмови кодом, а не текстом.

    Звіт користувача 29.09.2026: пул відповідав 400, і що саме виправляти —
    `--partial` чи щось інше — можна було зрозуміти лише з українського речення.
    """
    m = good()
    m.frames["total"] = 300
    v = gates.check(m)

    assert [(d["rule"], d["field"]) for d in v.refusal_details] == [
        ("partial_unexplained", "extra.partial")]
    assert v.refusal_details[0]["text"] == v.refusals[0]


def test_kozhna_vidmova_maie_kod() -> None:
    """Скільки відмов рядками — стільки ж із кодом: жодна не лишилась безіменною."""
    m = good()
    m.decode["voices"] = [{**VOICE, "model": ""}]
    m.case["shifra"] = ""
    m.license = {}
    m.case["note"] = "робоча нотатка"
    v = gates.check(m)

    assert len(v.refusals) >= 4
    assert [d["text"] for d in v.refusal_details] == v.refusals
    assert {d["rule"] for d in v.refusal_details} >= {
        "model_unnamed", "no_shifra", "no_license", "private_keys"}
    assert all(d["rule"] for d in v.refusal_details)


def test_as_json_nese_polityku_i_staryi_perelik() -> None:
    """`refusals` лишається списком рядків — його читають старі клієнти пулу."""
    m = good()
    m.frames["total"] = 300
    got = gates.check(m).as_json()

    assert got["policy"] == gates.POLICY
    assert all(isinstance(r, str) for r in got["refusals"])
    assert got["refusal_details"][0]["rule"] == "partial_unexplained"


def test_extend_perenosyt_kody() -> None:
    """Вердикт приймача складається з двох — коди не губляться дорогою."""
    m = good()
    m.frames["total"] = 300
    v = gates.Verdict()
    v.refuse("вада пакета: x", rule="bundle_defect")
    v.extend(gates.check(m))

    assert [d["rule"] for d in v.refusal_details] == ["bundle_defect", "partial_unexplained"]
    assert len(v.refusals) == 2
