"""Холодне ядро: моделі, сховище, матчинг, транслітерація, морфологія.

«Холодне» — це не про важливість, а про залежності: ці модулі не тягнуть ні
FastAPI, ні torch, ні знання про конкретний архів. Саме тому вони переїхали в
публічний пакет першими.
"""
from __future__ import annotations

import importlib
import sys

import pytest

MODULES = [
    "nyshporka.ids",
    "nyshporka.utils.translit",
    "nyshporka.utils.text",
    "nyshporka.models",
    "nyshporka.storage.files",
    "nyshporka.matching.fuzzy",
    "nyshporka.core.workspace",
    "nyshporka.core.resources",
    "nyshporka.core.morph",
    "nyshporka.core.profile",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_cold_core_stays_cold():
    """🔴 Жоден із них не має тягнути важке.

    Не естетика: щойно ядро почне імпортувати torch, `nysh` стартуватиме
    секундами, а «подивитись каталог справ» вимагатиме кількох гігабайтів.
    """
    for name in MODULES:
        importlib.import_module(name)
    for heavy in ("torch", "fastapi", "ultralytics", "transformers", "mkdocs"):
        assert heavy not in sys.modules, f"холодне ядро притягло {heavy}"


# ── транслітерація ───────────────────────────────────────────────────────────
def test_cyrillic_spellings_fold_to_exactly_one_word():
    """Українське, російське й дореформене написання — ОДИН рядок.

    Це головна властивість нормалізатора: у метриках той самий рід записаний
    то «Сікорський», то «Сикорский», то «Сикорскій», і без згортки пошук за
    однією формою пропускав би дві інші.
    """
    from nyshporka.utils.translit import normalize_for_matching as n

    assert n("Сікорський") == n("Сикорский") == n("Сикорскій")


def test_latin_spellings_land_within_fuzzy_reach_not_on_identity():
    """🔴 Латинка НЕ зводиться до кирилиці дослівно — і не має.

    Заміряно: укр.↔пол. 94, укр.↔рум. 82. Нормалізація тут не робить рядки
    однаковими, вона прибирає системну відстань (діакритику, sz/cz), щоб
    решту добрав фаззі. Тест на рівність був би хибним і змусив би «полагодити»
    нормалізатор так, що він почав би зливати різні прізвища.
    """
    from rapidfuzz import fuzz

    from nyshporka.utils.translit import normalize_for_matching as n

    assert fuzz.ratio(n("Сікорський"), n("Sikorski")) >= 90
    assert fuzz.ratio(n("Сікорський"), n("Sicorschi")) >= 80
    # А ось чуже прізвище має лишатись чужим.
    assert fuzz.ratio(n("Сікорський"), n("Яворський")) < 80


def test_archival_fold_joins_historical_letters():
    from nyshporka.utils.translit import normalize_archival as n

    assert n("Ѳеодоръ") == n("Феодор")
    assert n("Сікорскій") == n("Сикорский")


def test_slugify_is_ascii_lowercase_and_stable():
    """Slug має бути передбачуваним, а не гарним: за ним лежать імена файлів."""
    from nyshporka.utils.text import slugify

    slug = slugify("Сікорський, Іван")
    assert slug == slugify("Сікорський, Іван"), "slug мусить бути детермінованим"
    assert slug.isascii() and slug == slug.lower()
    assert not slug.startswith("-") and not slug.endswith("-")
    assert "ivan" in slug
    assert slugify("  ---  ") == ""


# ── ідентифікатори ───────────────────────────────────────────────────────────
def test_ids_are_zero_padded_to_four():
    from nyshporka import ids

    assert ids.person_id(1).startswith("I") and len(ids.person_id(1)) == 5
    assert ids.family_id(42)[1:] == "0042"
    assert ids.place_id(7).startswith("PL")
    assert ids.source_id("dahmo-f315") == "dahmo-f315"


# ── морфологія ───────────────────────────────────────────────────────────────
def test_paradigm_generates_full_case_table():
    """Сім відмінків × два роди з однієї основи — те, заради чого генератор."""
    from nyshporka.core import morph

    forms = morph.paradigm("adj_skyi").forms("Сікор", "uk")
    assert forms["nom_m"] == "Сікорський"
    assert forms["gen_m"] == "Сікорського"
    assert forms["nom_f"] == "Сікорська"
    assert forms["ins_f"] == "Сікорською"
    for case in morph.CASES:
        for gender in morph.GENDERS:
            assert f"{case}_{gender}" in forms


def test_orthographies_differ_where_they_should():
    from nyshporka.core import morph

    p = morph.paradigm("adj_skyi")
    assert p.form("Сикор", "nom_m", "ru_modern") == "Сикорский"
    assert p.form("Сикор", "nom_m", "ru_prereform") == "Сикорскій"
    assert p.form("Сікор", "nom_m", "uk") == "Сікорський"
    assert p.form("Sikor", "nom_m", "pl") == "Sikorski"


def test_hyphenation_returns_all_three_pieces():
    """Голова й хвіст трапляються в декоді ОКРЕМО, на різних рядках."""
    from nyshporka.core import morph

    assert morph.hyphenate("Сікорський", 4) == ("Сіко- рський", "Сіко-", "рський")


def test_target_ladder_discounts_truncated_roots():
    from nyshporka.core import morph

    got = morph.htr_targets("сікорськ")
    assert got[0] == ("сікорськ", 1.0)
    assert [w for _, w in got] == [1.0, 0.85, 0.65, 0.45]
    assert all(t for t, _ in got), "порожній таргет зробив би пошук всеїдним"


def test_unverified_paradigms_say_so():
    """⚠ Заготовки не мають виглядати як перевірені: на них ще не міряли."""
    from nyshporka.core import morph

    assert morph.paradigm("adj_skyi").verified
    assert not morph.paradigm("noun_ov").verified


# ── робочий простір ──────────────────────────────────────────────────────────
def test_no_private_default_case_roots(tmp_path):
    """🔴 Додаткові корені зі справами — це завжди чиясь конкретна машина.

    У дослідницькому репо тут стояв особистий шлях автора до архіву на іншому
    диску. У пакеті дефолт мусить бути порожній: хто тримає архів окремо,
    вписує його в маркер СВОГО простору.
    """
    from nyshporka.core import workspace as W

    deep = tmp_path / "Нишпорка" / "Мій рід"
    (deep / "data").mkdir(parents=True)
    ws = W.resolve(deep)
    assert ws.case_roots() == [ws.raw]


def test_workspace_refuses_dangerous_roots():
    from pathlib import Path

    from nyshporka.core import workspace as W

    for bad in ("C:/", str(Path.home()), "/"):
        with pytest.raises(W.WorkspaceError):
            W.validate_root(Path(bad))


def test_missing_workspace_fails_loudly_not_silently(tmp_path, monkeypatch):
    """Мовчазна робота «в нікуди» гірша за чесну відмову."""
    from nyshporka.core import workspace as W

    monkeypatch.delenv(W.ENV_WORKSPACE, raising=False)
    monkeypatch.delenv(W.ENV_LEGACY_WORKSPACE, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(W, "_PACKAGE_ANCHOR", tmp_path / "nowhere")
    monkeypatch.setattr(W, "_load_last_used", lambda: None)
    with pytest.raises(W.WorkspaceError) as exc:
        W.resolve()
    # Повідомлення мусить казати, ЩО зробити, а не лише що зламалось.
    assert W.MARKER in str(exc.value) and "--workspace" in str(exc.value)
