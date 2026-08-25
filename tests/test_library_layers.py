"""📚 Шари роботи над справою: «не знаємо» ніколи не стає нулем.

Бібліотека зводить три сховища: опис справи, реєстр роботи над нею й вердикт
людини. Кожне з них може бути відсутнім, і кожна відсутність має свій вигляд.

🔴🔴 Найдорожча помилка тут — видати «зрізу не збирали» за «нічого не
зроблено». «1331 справа без декоду» виглядає як факт про роботу, на підставі
якого вирішують, що гнати наступним; насправді ж це означає, що реєстру просто
немає. Тому шари без реєстру віддаються як `None`, а не `0`, і зведення про
них мовчить.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір із бібліотекою на дві справи й БЕЗ реєстру роботи."""
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    (derived / "case_library.json").write_text(json.dumps({"cases": [
        {"key": "DAHMO/315/1", "shifra": "ДАХмО 315-1-1", "repo": "DAHMO",
         "title": "Метрична книга", "place": "М'ястківка", "uezd": "Ольгопільський",
         "on_disk": True, "frames": 100, "record_types": ["birth"],
         "doc_type": "метрична книга", "path": "data/raw/a"},
        {"key": "DAVO/904/2", "shifra": "ДАВіО 904-2", "repo": "DAVO",
         "title": "Сповідні розписи", "place": "Ротмистрівка",
         "on_disk": False, "frames": 0, "record_types": ["confession"],
         "doc_type": "сповідні розписи"},
    ]}), encoding="utf-8")

    monkeypatch.setattr(L, "LIBRARY_PATH", derived / "case_library.json")
    monkeypatch.setattr(L, "VERDICTS_PATH", tmp_path / "verdicts.json")
    # 🔴 Шлях реєстру теж, і це не формальність. `cases.db.DB_PATH` рахується
    # ПРИ ІМПОРТІ від того простору, який трапився першим, і далі не змінюється
    # ніколи. Без цієї підміни тест читав би реєстр ЧУЖОГО простору — того, що
    # лишився від попереднього тесту, — і «шарів немає» перетворювалось би на
    # «шари є», причому лише в повній збірці й лише за певного порядку.
    from nyshporka.cases import db as DB

    monkeypatch.setattr(DB, "DB_PATH", derived / "case_index.sqlite")
    LY.reset()
    yield tmp_path
    LY.reset()


def _call(args=None):
    from nyshporka import ops as O

    return O.call("library.list", args or {})


# ── 🔴 головне правило ───────────────────────────────────────────────────────
def test_without_the_registry_layers_are_unknown_not_zero(space) -> None:
    """🔴🔴 Немає реєстру → колонки `None`, зведення мовчить, застереження є."""
    env = _call()
    assert env.ok, env.error
    d = env.data
    assert d["total"] == 2, "бібліотека не прочиталась"

    for row in d["cases"]:
        assert row["htr_stage"] is None, (
            "шар читання прийшов нулем замість «невідомо» — на екрані це "
            "стане «справу не читали», хоч означає «зрізу не збирали»")
        assert row["fuzzy_stage"] is None
        assert row["pages_noted"] is None

    s = d["summary"]
    assert s["has_layers"] is False
    assert s["no_htr"] is None, (
        "«0 без декоду» читається як досягнення, а означає протилежне")
    assert s["no_fuzzy"] is None
    # Опис бібліотеки при цьому цілком відомий — його рахувати можна.
    assert s["all"] == 2 and s["on_disk"] == 1

    codes = {w.code for w in env.warnings}
    assert "no_layers" in codes, "відсутність зрізу пройшла мовчки"


def test_the_unbuilt_library_is_not_an_empty_one(tmp_path: Path, monkeypatch) -> None:
    """🔴 «Зведення не збирали» і «справ немає» — різні відповіді.

    Побачивши «0 справ», людина вирішує, що шукати нема де, — і закриває
    напрям, якого ніхто не відкривав.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    monkeypatch.setattr(L, "LIBRARY_PATH", tmp_path / "nema.json")
    LY.reset()
    env = _call()
    assert env.data["shown"] is None, "нуль замість «невідомо»"
    assert env.data["built"] is False
    assert {w.code for w in env.warnings} >= {"no_library_yet"}
    assert env.next, "не сказано, чим це лікується"
    LY.reset()


# ── фасети й знаменник ───────────────────────────────────────────────────────
def test_facets_are_built_from_the_whole_library_not_from_the_result(space) -> None:
    """🔴 Фасет із відфільтрованого схлопується після першого ж вибору.

    Решта архівів зникає зі списку, повернутись до них нема чим — і екран
    починає брехати про діючий фільтр.
    """
    env = _call({"repo": "DAHMO"})
    assert env.data["total"] == 1, "фільтр не спрацював"
    repos = {x["code"] for x in env.data["facets"]["repos"]}
    assert repos == {"DAHMO", "DAVO"}, (
        f"перелік архівів зібрано з видачі, а не з бібліотеки: {repos}")


def test_zero_comes_with_its_denominator(space) -> None:
    """«Нічого не знайшлось» означає різне при двох справах і при тисячі."""
    env = _call({"q": "такогонемає"})
    assert env.data["total"] == 0
    warn = next((w for w in env.warnings if w.code == "empty_filter"), None)
    assert warn, "порожня видача без знаменника"
    assert "2" in warn.text, f"у знаменнику немає числа справ: {warn.text}"


# ── 🔎 приблизний пошук ──────────────────────────────────────────────────────
def test_search_finds_a_village_written_in_another_form(space) -> None:
    """🔴 Підрядка мало, і це не зручність.

    Назва села в описі буває латинкою, в іншому відмінку або з апострофом,
    якого людина не набирає. Підрядком такі форми не збігаються НІКОЛИ — і
    справа, яка є, чесно відповідає «немає».
    """
    exact = _call({"q": "М'ястківка"})
    assert exact.data["total"] == 1, "точний збіг не спрацював"

    # Без апострофа — так набирає більшість.
    loose = _call({"q": "Мястківка"})
    assert loose.data["total"] == 1, (
        "справа не знайшлась без апострофа — а саме так її й шукатимуть")

    # Латинкою: те саме село в іншій графіці.
    latin = _call({"q": "Miastkivka"})
    assert latin.data["total"] == 1, (
        "латинська форма не знайшла кириличний опис — пошук мовчки дав нуль")


def test_uezd_filter_survives_the_adjective_ending(space) -> None:
    """Повіт пишуть і як «Ольгопіль», і як «Ольгопільського»."""
    assert _call({"uezd": "Ольгопіль"}).data["total"] == 1
    assert _call({"uezd": "Ольгопільського"}).data["total"] == 1


# ── посторінкова видача ──────────────────────────────────────────────────────
def test_pagination_keeps_the_full_total(space) -> None:
    """Сторінка не має ховати знаменник: інакше «1 з 1» замість «1 з 2»."""
    env = _call({"page_size": 10, "page": 0})
    assert env.data["shown"] == 2 and env.data["total"] == 2
    assert env.data["pages"] == 1

    env2 = _call({"page_size": 10, "page": 5})
    assert env2.data["shown"] == 0
    assert env2.data["total"] == 2, "загальне число загубилось на порожній сторінці"
    assert {w.code for w in env2.warnings} >= {"page_past_end"}
