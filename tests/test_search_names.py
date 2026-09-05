"""🗣 Довідник імен у пошуку: чи знаходиться те, чого fuzzy не бере.

🔴 Головне твердження файлу — розширення запиту НЕ СМІЄ зсунути наявні хіти.
Пошук по прізвищу відповідає на питання, яким закривають напрям дослідження;
якщо разом із новою здатністю поїхали старі відповіді, здатність не варта
нічого. Тому тут два роди перевірок поруч: що нове знаходиться і що старе
лишилось точно таким, як було.

⚠ Пара для перевірки взята не будь-яка. «Ганна» проти «Анна» дає на живому
rapidfuzz 88.9 — тобто fuzzy бере її й БЕЗ довідника, і тест на ній проходив би
однаково до правки й після, нічого не доводячи. «Явдоха» проти «Євдокія» дає
61.5 при порозі 80: без довідника ця пара не знаходиться ніколи.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Простір із одним прогоном: хрестильне ім'я, побутове й прізвище."""
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    # Сторінка 1 — хрестильна форма, якою запис зроблено в книзі.
    (run / "0001.txt").write_text(
        "восприемница Евдокія Сикорская\nтого же села крестьянка\n",
        encoding="utf-8")
    # Сторінка 2 — та сама людина побутовим іменем, як її записали далі.
    (run / "0002.txt").write_text(
        "жена Явдоха Сикорская\nдвора хозяйка\n", encoding="utf-8")
    # Сторінка 3 — побутове ім'я з ІНШОГО шару: Васса проти Анни.
    (run / "0003.txt").write_text(
        "родилась Васса Ковалева\nмѣщанка\n", encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2},
                  "0003.jpg": {"lines": 2}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S
    from nyshporka.records import names as N

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    # ⚠ Кеш побутових пар живе на процес, а накладку читає з ПРОСТОРУ. Без
    # скидання порядок тестів вирішував би, що саме бачить довідник.
    N._folk_pairs = None
    yield tmp_path
    N._folk_pairs = None
    W.reset()


def _pages(res: dict) -> set[str]:
    return {h["page"] for h in res["hits"]}


def test_the_pair_under_test_is_out_of_reach_for_plain_fuzzy() -> None:
    """⚠ Приймач самого тесту: без довідника ця пара НЕ знаходиться.

    Без цієї перевірки решта файлу могла б проходити на парі, яку fuzzy бере
    сам, — і мовчки доводити не те.
    """
    from rapidfuzz import fuzz

    from nyshporka.utils.translit import normalize_archival as N

    assert fuzz.ratio(N("Явдоха"), N("Евдокія")) < 78
    assert fuzz.ratio(N("Васса"), N("Анна")) < 78
    # А ось контрприклад, на якому тест був би беззмістовним:
    assert fuzz.ratio(N("Ганна"), N("Анна")) > 85


def test_a_folk_spelling_finds_the_church_form(space) -> None:
    """🔴 Заради чого все: «Явдоха» мусить знайти сторінку з «Евдокія»."""
    from nyshporka import htr_store as S

    res = S.search("Явдоха", thresh=80)
    assert "0001.jpg" in _pages(res), "хрестильна форма не знайшлась"
    assert "0002.jpg" in _pages(res), "набране людиною теж мусить знаходитись"


def test_the_dictionary_can_be_switched_off(space) -> None:
    """Вимикач мусить справді вимикати — інакше порівняти нема з чим."""
    from nyshporka import htr_store as S

    res = S.search("Явдоха", thresh=80, given=False)
    assert "0001.jpg" not in _pages(res)
    assert not res["stems_added"]


def test_each_hit_says_which_spelling_found_it(space) -> None:
    """🔴 Хіт по двійнику з довідника не сміє читатись як хіт по набраному."""
    from nyshporka import htr_store as S
    from nyshporka.records import names as N

    res = S.search("Явдоха", thresh=80)
    origin = {h["page"]: h["stem_origin"] for h in res["hits"]}
    assert origin["0002.jpg"] == N.ORIGIN_QUERY
    assert origin["0001.jpg"] == N.ORIGIN_GIVEN


def test_what_was_typed_stays_a_separate_number(space) -> None:
    """Знаменник: «шукали Явдоху» після розширення вже неправда."""
    from nyshporka import htr_store as S

    res = S.search("Явдоха", thresh=80)
    assert res["stems_asked"] == ["avdoha"]
    assert "evdokia" in res["stems_added"]
    assert res["stems_asked"][0] == res["stems"][0], "набране мусить іти першим"


def test_surname_hits_do_not_move(space) -> None:
    """🔴 Найважливіше: старі відповіді лишились точно такими, як були."""
    from nyshporka import htr_store as S

    plain = S.search("Сикорская", thresh=80, given=False)
    wide = S.search("Сикорская", thresh=80, given=True)
    key = [(h["page"], h["line_no"], h["score"]) for h in plain["hits"]]
    assert key, "перевірка беззмістовна: прізвище не знайшлось узагалі"
    assert [(h["page"], h["line_no"], h["score"]) for h in wide["hits"]] == key


def test_folk_layer_is_off_until_asked(space) -> None:
    """🔴 Васса й Анна — різні святі; глобально їх зводити не можна."""
    from nyshporka import htr_store as S

    assert "0003.jpg" not in _pages(S.search("Анна", thresh=80))
    got = S.search("Анна", thresh=80, folk=True)
    assert "0003.jpg" in _pages(got)
    assert got["folk"] is True


def test_folk_hits_are_marked_apart(space) -> None:
    """Побутовий двійник мусить бути видним у відповіді, а не мовчазним."""
    from nyshporka import htr_store as S
    from nyshporka.records import names as N

    got = S.search("Анна", thresh=80, folk=True)
    marks = {h["page"]: h["stem_origin"] for h in got["hits"]}
    assert marks["0003.jpg"] == N.ORIGIN_FOLK


def test_the_pair_works_from_both_sides() -> None:
    """🔴 Симетрія: інакше відповідь залежала б від того, з якого документа почали."""
    from nyshporka.records import names as N

    assert "anna" in N.expand_folk("Васса")
    assert "vassa" in N.expand_folk("Анна")


def test_a_space_can_add_its_own_pairs(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Накладка простору — тим самим механізмом, що й пак архівів."""
    from nyshporka.core import workspace as W
    from nyshporka.records import names as N

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / N.WORKSPACE_FOLK).write_text(
        "Мотрона: [Матрёна, Мотря]\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    try:
        pairs = N.folk_pairs(refresh=True)
        assert "motra" in pairs.get("motrona", ())
        # вбудоване не зникає від того, що з'явилась накладка
        assert "anna" in pairs.get("vassa", ())
    finally:
        N._folk_pairs = None
        W.reset()
