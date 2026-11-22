"""Описи-внески: схема, звірка власних назв, ворота (nyshporka.opysy)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from nyshporka.opysy import gates as G
from nyshporka.opysy import names as N
from nyshporka.opysy.schema import (
    SCHEMA,
    Manifest,
    Page,
    Quality,
    Region,
    Row,
    Source,
    row_key,
)

SHA = "a" * 64


def _src(**kw) -> Source:
    base = dict(kind="archive_site", url="https://archive.example/0445_01.djvu", sha256=SHA,
                pages=3, label="0445_01.djvu")
    base.update(kw)
    return Source(**base)


def _manifest(**kw) -> Manifest:
    base = dict(repo="DAOO", fond="445", opys="1", language="ru", sources=[_src()],
                engines=["pysar_v31"],
                quality=Quality(klass="mid", form="hand_ruled"), license="CC-BY-4.0")
    base.update(kw)
    return Manifest(**base)


def _pages(n: int = 3, src: int = 0) -> list[Page]:
    return [Page(src=src, page=i, voices={"pysar": f"текст сторінки {i}"}) for i in range(1, n + 1)]


def _row(no: int, page: int = 1, y: float = 0.1, **kw) -> Row:
    base = dict(regions=[Region(page=page, y0=y, y1=y + 0.05)], no_raw=str(no), no=no,
                no_status="chain", title_raw=f"Дело о крестьянине {no}")
    base.update(kw)
    return Row(**base)


def _rules(v: G.Verdict) -> set[str]:
    return {d["rule"] for d in v.refusal_details}


# ── схема ────────────────────────────────────────────────────────────────


def test_manifest_roundtrip_keeps_schema_alias() -> None:
    m = _manifest()
    dumped = m.model_dump(by_alias=True)
    assert dumped["schema"] == SCHEMA
    assert Manifest.model_validate(dumped) == m


def test_source_requires_web_url_unless_private() -> None:
    with pytest.raises(ValidationError):
        _src(url="")
    with pytest.raises(ValidationError):
        _src(url="E:/scans/opys.pdf")
    assert _src(kind="private", url="").kind == "private"


def test_source_frames_identity_and_links() -> None:
    s = Source(kind="fs", url="https://www.familysearch.org/search/film/004123456",
               page_link="https://www.familysearch.org/search/film/004123456?i={i}",
               frames=["f1", "f2"], pages=2)
    assert s.link(2).endswith("?i=1")
    assert s.ident(1) == "f:f1"
    with pytest.raises(ValidationError):
        Source(kind="fs", url="https://x.example", frames=["f1"], pages=2)
    with pytest.raises(ValidationError):
        _src(page_link="https://archive.example/p")  # без підстановки


def test_strict_schema_refuses_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Row(title_raw="x", note="приватна нотатка")


def test_row_key_positional_not_by_number() -> None:
    m = _manifest()
    a = _row(5, page=2, y=0.3)
    b = _row(6, page=2, y=0.3)  # інший номер, те саме місце
    assert row_key(m.sources, a) == row_key(m.sources, b) != ""
    assert row_key(m.sources, Row(title_raw="x")) == ""


# ── власні назви ─────────────────────────────────────────────────────────


def test_marks_and_unmark() -> None:
    t = "По жалобе ⟨?Ібанов⟩ на ⟨?Г. Ско- тиняи⟩"
    assert N.marks(t) == ["Ібанов", "Г. Ско- тиняи"]
    assert N.unmark(t) == "По жалобе Ібанов на Г. Ско- тиняи"


def test_invented_catches_new_surname() -> None:
    raw = "Поденентой претензій Арона Шварушана мѣщику карлу Прогомара цкому"
    norm = "По денежной претензии Арона Шварцмана к помещику Карлу Прогомарецкому"
    assert N.invented(raw, norm) == ["Шварцмана"]


def test_invented_tolerates_endings_and_old_letters() -> None:
    raw = "По жаловѣ приста Злотопольской Нико ласьской церкви на по мѣщика Лопухина"
    norm = "По жалобе пристава Златопольской Николаевской церкви на помещика Лопухина"
    assert N.invented(raw, norm) == []


def test_invented_short_word_compared_whole() -> None:
    assert N.invented("о высылке его въ Сабирь", "о высылке его в Сибирь") == []


def test_invented_ignores_capitalised_offices() -> None:
    raw = "По отношенію Мини тра Внута Дѣлъ"
    norm = "По отношению Министра Внутренних Дел"
    assert N.invented(raw, norm) == []


def test_invented_checks_marked_words_one_by_one() -> None:
    raw = "о найденном близъ Г. Ско- уда тиняи"
    assert N.invented(raw, "о найденном близ ⟨?Г. Ско- тиняи⟩") == []
    assert N.invented(raw, "о найденном близ ⟨?Скотиняи⟩ ⟨?Бердичевом⟩") == ["Бердичевом"]


def test_glued_name_inside_longer_raw_word() -> None:
    assert N.invented("на помещикаЛопухина за долг", "на помещика Лопухина за долг") == []


def test_lexicon_ships_and_matches_policy() -> None:
    stems = N.common_stems()
    assert len(stems) == N.LEXICON_STEMS, "словник змінився — підніми gates.POLICY і LEXICON_STEMS"
    assert N.stem("Министра") in stems


# ── ворота ───────────────────────────────────────────────────────────────


def test_clean_pack_passes() -> None:
    m = _manifest()
    rows = [_row(1, page=1, y=0.1), _row(2, page=1, y=0.2), _row(3, page=2, y=0.1)]
    v = G.check(m, _pages(), rows)
    assert v.passed, v.refusals


def test_excluded_fond_refused_any_spelling() -> None:
    assert G.excluded("ЦДІАК", "442")
    assert G.excluded("cdiak", " 442 ")
    assert not G.excluded("DAOO", "445")
    v = G.check(_manifest(repo="ЦДІАК", fond="442"), _pages(), [_row(1)])
    assert "excluded_fond" in _rules(v)


def test_repo_key_one_code_for_any_spelling() -> None:
    """Той самий фонд не розходиться на два ключі через кирилицю в назві архіву."""
    for repo in ("ДАОО", "DAOO", "daoo"):
        assert G.repo_fond(repo, "0445") == ("DAOO", "445")
    assert G.repo_fond("ДАВО", "904") == G.repo_fond("ДАВіО", "904") == ("DAVIO", "904")


def test_row_without_binding_refused() -> None:
    v = G.check(_manifest(), _pages(), [Row(title_raw="без місця")])
    assert "row_unbound" in _rules(v)


def test_row_on_missing_page_refused() -> None:
    v = G.check(_manifest(), _pages(), [_row(1, page=9)])
    assert "row_bad_page" in _rules(v)


def test_half_on_non_spread_refused() -> None:
    r = Row(regions=[Region(page=1, half=0, y0=0.1, y1=0.2)], title_raw="x")
    assert "row_bad_half" in _rules(G.check(_manifest(), _pages(), [r]))


def test_foreign_key_and_duplicate_place_refused() -> None:
    a = _row(1, y=0.1)
    b = _row(2, y=0.1)
    v = G.check(_manifest(), _pages(), [a, b])
    assert "row_dup" in _rules(v)
    c = _row(3, y=0.5, rk="deadbeef")
    assert "row_bad_key" in _rules(G.check(_manifest(), _pages(), [c]))


def test_coverage_needs_every_source_page() -> None:
    v = G.check(_manifest(), _pages(2), [_row(1)])
    assert "coverage" in _rules(v)
    m = _manifest(partial={"why": "третя сторінка — інший опис"})
    v2 = G.check(m, _pages(2), [_row(1)])
    assert "coverage" not in _rules(v2)
    assert any(c == "partial" for c, _ in v2.warnings)


def test_spread_needs_both_halves_or_whole() -> None:
    m = _manifest(sources=[_src(pages=1, spread=True)])
    half = [Page(page=1, half=0, voices={"p": "ліва"})]
    assert "coverage" in _rules(G.check(m, half, []))
    both = [*half, Page(page=1, half=1, voices={"p": "права"})]
    assert G.check(m, both, []).passed
    whole = [Page(page=1, voices={"vl": "цілий розворот"})]
    assert G.check(m, whole, []).passed


def test_spread_blank_right_halves_are_not_blank_pages() -> None:
    """Розворот навпіл, права половина чиста: сторінка з текстом, а не порожня."""
    m = _manifest(sources=[_src(pages=3, spread=True)])
    pages = []
    for i in (1, 2, 3):
        pages += [Page(page=i, half=0, voices={"p": f"ліва {i}"}), Page(page=i, half=1, blank=True)]
    v = G.check(m, pages, [])
    assert v.passed, v.refusals
    assert G.summary(m, pages, [])["pages_blank"] == 0


def test_summary_and_gate_share_one_unit() -> None:
    m = _manifest(sources=[_src(pages=2, spread=True)])
    pages = [Page(page=1, half=0, voices={"p": "ліва"})] + [
        Page(page=2, half=h, voices={"p": "x"}) for h in (0, 1)]
    assert G.summary(m, pages, [])["pages_read"] == 1  # стор. 1 — лише половина
    assert "coverage" in _rules(G.check(m, pages, []))


def test_quality_form_required() -> None:
    with pytest.raises(ValidationError):
        Quality(klass="mid")


def test_blank_page_counts_but_empty_unmarked_does_not() -> None:
    pages = [*_pages(2), Page(page=3, blank=True)]
    assert G.check(_manifest(), pages, [_row(1)]).passed
    pages2 = [*_pages(2), Page(page=3)]
    assert "page_empty" in _rules(G.check(_manifest(), pages2, [_row(1)]))


def test_low_quality_needs_normalization() -> None:
    m = _manifest(quality=Quality(klass="low", form="hand_form"))
    v = G.check(m, _pages(), [_row(1)])
    assert "norm_missing" in _rules(v)


def test_normalized_without_naming_refused() -> None:
    v = G.check(_manifest(), _pages(), [_row(1, title_norm="Дело о крестьянине")])
    assert "norm_unnamed" in _rules(v)


def test_hand_form_cannot_be_high() -> None:
    m = _manifest(quality=Quality(klass="high", form="hand_form"))
    assert "quality_hand_high" in _rules(G.check(m, _pages(), [_row(1)]))


def _norm_rows(n: int, bad: int) -> list[Row]:
    rows = []
    for i in range(1, n + 1):
        raw = "По прошению крестьянина Ивана Петренка о земле"
        norm = ("По прошению крестьянина Ивана Шварцмана о земле" if i <= bad
                else "По прошению крестьянина Ивана Петренка о земле")
        rows.append(_row(i, page=1 + (i % 3), y=0.01 * i, title_raw=raw, title_norm=norm))
    return rows


def test_invented_names_refused_over_share_and_floor() -> None:
    m = _manifest(normalization={"prompt": "norm_prompt", "version": "1", "model": "sonnet"})
    v = G.check(m, _pages(), _norm_rows(40, 8))  # 20 % > 12 %, 8 ≥ 5
    assert "norm_invents" in _rules(v)
    v2 = G.check(m, _pages(), _norm_rows(40, 3))  # нижче порога — лише позначка
    assert "norm_invents" not in _rules(v2)
    assert any(c == "invented_names" for c, _ in v2.warnings)
    v3 = G.check(m, _pages(), _norm_rows(20, 4))  # 20 %, але < 5 рядків — шум вибірки
    assert "norm_invents" not in _rules(v3)


def test_language_without_lexicon_only_marks() -> None:
    m = _manifest(language="uk",
                  normalization={"prompt": "norm_prompt", "version": "1", "model": "sonnet"})
    v = G.check(m, _pages(), _norm_rows(40, 8))
    assert "norm_invents" not in _rules(v)
    codes = {c for c, _ in v.warnings}
    assert {"invented_names", "invented_names_no_lexicon"} <= codes


def test_manifest_requires_language() -> None:
    raw = _manifest().model_dump(by_alias=True)
    raw.pop("language")
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)


def test_no_span_validated_and_marked() -> None:
    with pytest.raises(ValidationError):
        _row(1, no_span="будь-що")
    r = _row(14, no_span="14–19")
    assert r.no_span == "14–19"
    assert _row(2, y=0.3, no_span="2а-5").no_span == "2а-5"
    v = G.check(_manifest(), _pages(), [r, _row(20, y=0.4)])
    assert v.passed and any(c == "no_span" for c, _ in v.warnings)


def test_schema_1_pack_still_accepted() -> None:
    """Старий клієнт (схема 1, без no_span) приймається новим боком."""
    raw = _manifest().model_dump(by_alias=True)
    raw["schema"] = 1
    m, _, rows, v = G.parse(raw, [], [{"title_raw": "x", "regions": [
        {"page": 1, "y0": 0.1, "y1": 0.2}]}])
    assert m is not None and v.passed and rows[0].no_span == ""


def test_number_warnings_not_refusals() -> None:
    rows = [_row(5, y=0.1), _row(5, y=0.2, no_status="unconfirmed"), _row(3, y=0.3)]
    v = G.check(_manifest(), _pages(), rows)
    assert v.passed
    codes = {c for c, _ in v.warnings}
    assert {"no_unconfirmed", "no_dup", "no_back"} <= codes


def test_machine_path_in_free_text_refused() -> None:
    m = _manifest(title="C:\\Users\\me\\opys")
    assert "machine_path" in _rules(G.check(m, _pages(), [_row(1)]))


def test_parse_names_newer_schema_and_bad_line() -> None:
    raw = _manifest().model_dump(by_alias=True)
    newer = dict(raw, schema=SCHEMA + 1)
    _, _, _, v = G.parse(newer, [], [])
    assert "schema_newer" in _rules(v)
    m, pages, rows, v2 = G.parse(raw, [{"page": 1, "voices": {"p": "t"}}],
                                 [{"title_raw": "x"}, {"title_raw": "y", "private": 1}])
    assert m is not None and len(pages) == 1 and len(rows) == 1
    assert any("rows.jsonl, рядок 2" in r for r in v2.refusals)


def test_private_source_is_a_mark() -> None:
    m = _manifest(sources=[_src(kind="private", url="")])
    v = G.check(m, _pages(), [_row(1)])
    assert v.passed
    assert any(c == "private_source" for c, _ in v.warnings)


def test_verdict_carries_opysy_policy() -> None:
    out = G.check(_manifest(), _pages(), [_row(1)]).as_json()
    assert out["policy"] == G.POLICY and out["kind"] == "opys"
