"""⚓ Канал імен: рід знаходиться там, де прізвища в тексті вже немає.

🔴 Заради чого канал існує: рушій калічить довге прізвище сильніше, ніж коротке
формулярне слово. У приватному конвеєрі обидва золоті рятунки мали по прізвищу
бал НУЛЬ — мовна модель підставила чуже слово, — а по батькові той самий рушій
прочитав дослівно. Тобто прізвищний канал там не «трохи не дотягнув»: його не
було зовсім.

🔴 Друге, що тут стережеться: **пара обов'язкова**. Одиночне по батькові стоїть
у метриці на кожному аркуші й ознакою не є. Канал, який приймає одинака,
знаходить усе — тобто не знаходить нічого.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROFILE = """\
fallback: rid

profiles:
  rid:
    surname:
      display: Сікорський
      paradigm: adj_skyi
      stems:
        uk: Сікор
{kin}
"""

KIN = """\
    kin:
      - given: Ѳеодоръ
        patronymic: Ѳеодоровъ
        born: 1762
        died: 1830
"""


def _space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kin: str = KIN) -> Path:
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "research_profile.yaml").write_text(
        PROFILE.format(kin=kin), encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reset()

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    # Прізвище скалічене до невпізнання, імена цілі — типовий вихід рушія.
    (run / "0001.txt").write_text(
        "у Ѳеодоръ Ѳеодоровъ Cкрсхнй родился сынъ\nтого же двора\n",
        encoding="utf-8")
    # Одиночне по батькові: на кожному аркуші метрики, ознакою не є.
    (run / "0002.txt").write_text("восприемникъ Ѳеодоровъ Петръ\nсело Кривое\n",
                                  encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    return tmp_path


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    yield _space(tmp_path, monkeypatch)
    P.reset()
    W.reset()


def test_the_surname_channel_sees_nothing_there(space) -> None:
    """Приймач самого тесту: прізвище скалічене так, що його вже немає."""
    from nyshporka import htr_store as S

    got = S.search("Сікорський", name="проба", thresh=80)
    assert not got["hits"], "прізвище знайшлось — тест доводив би не те"


def test_the_names_channel_finds_the_page(space) -> None:
    """🔴 Заради чого все: сторінка приходить іменами, коли прізвища немає."""
    from nyshporka import htr_store as S

    got = S.search("Сікорський", name="проба", thresh=80, anchors=True)
    assert [h["page"] for h in got["anchor"]["hits"]] == ["0001.jpg"]


def test_a_lone_patronymic_is_not_enough(space) -> None:
    """🔴 «Ѳеодоровъ» стоїть на кожному аркуші метрики — сам він не ознака."""
    from nyshporka import htr_store as S

    got = S.search("Сікорський", name="проба", thresh=80, anchors=True)
    assert "0002.jpg" not in [h["page"] for h in got["anchor"]["hits"]]


def test_the_channel_keeps_its_own_count(space) -> None:
    """🔴 Прізвищний нуль мусить лишитись прізвищним нулем.

    «Прізвища немає, зате поруч стоять наші імена» — це дві різні відповіді, і
    злиття їх в одну втрачає обидві.
    """
    from nyshporka import htr_store as S

    got = S.search("Сікорський", name="проба", thresh=80, anchors=True)
    assert got["hits"] == []
    assert got["anchor"]["total"] == 1
    assert got["anchor"]["hits"][0]["channel"] == "anchor"


def test_without_kin_the_channel_is_silent_not_broken(tmp_path, monkeypatch) -> None:
    """Канал без даних мовчить — як і рятувальний прохід у раннері."""
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    _space(tmp_path, monkeypatch, kin="")
    try:
        from nyshporka import htr_store as S

        got = S.search("Сікорський", name="проба", thresh=80, anchors=True)
        assert got["anchor"]["total"] == 0 or "total" not in got["anchor"]
        assert got["anchor"]["on"] is True
    finally:
        P.reset()
        W.reset()


def test_a_name_is_useful_while_the_person_lives(space) -> None:
    from nyshporka.search import anchors as A

    assert A.keys(1800, 1810).given, "за життя ім'я мусить бути в якорі"
    assert not A.keys(1900, 1910).given, "через 70 років по смерті — вже ні"


def test_a_patronymic_outlives_its_bearer(space) -> None:
    """🔴 По батькові переживає носія на покоління — воно живе, поки живі діти.

    Саме тому воно й ловить рядки, де прізвище скалічене в нуль: діти
    трапляються в актах довго після смерті батька.
    """
    from nyshporka.search import anchors as A

    late = A.keys(1855, 1860)
    assert not late.given, "сам він помер 1830 — імені у вікні бути не може"
    assert late.patronymic, "а по батькові (нар+18…нар+100) ще чинне"


def test_a_person_without_dates_does_not_widen_the_anchor(tmp_path,
                                                          monkeypatch) -> None:
    """🔴 Без дат особа вікно не звужує, і за замовчуванням у якір не йде.

    Без прив'язки до років якір вироджувався до чверті рядків книги — тобто
    вимикав сам себе. Але й мовчки такі особи не зникають: їх лічать окремо.
    """
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W
    from nyshporka.search import anchors as A

    _space(tmp_path, monkeypatch,
           "    kin:\n      - given: Іосифъ\n        patronymic: Іосифовъ\n")
    try:
        k = A.keys(1800, 1810)
        assert k.undated == 1
        assert not k.given
        assert A.keys(1800, 1810, any_date=True).given, "явно попросили — беремо"
    finally:
        P.reset()
        W.reset()


def test_the_channel_refuses_outside_a_case(space) -> None:
    """🔴 Вікно якорів береться з РОКІВ СПРАВИ, тож поза справою його немає."""
    from nyshporka.ops_builtin import SearchArgs, search_run

    env = search_run(SearchArgs(q="Сікорський", anchors=True))
    assert not env.ok
    assert "case" in (env.error or "").lower() or "справ" in (env.error or "")



def test_people_with_the_same_given_name_stay_apart() -> None:
    """🔴 Імена в роді повторюються через покоління: ключ — пара, не ім'я."""
    from nyshporka.search import anchors as A

    class Prof:
        kin = ({"given": "Іван", "patronymic": "Федорович", "born": 1800},
               {"given": "Іван", "patronymic": "Петрович", "born": 1850},
               {"given": "Федір", "patronymic": "Іванович", "born": 1825})

    got = A.people(Prof())
    assert sorted(p.patronymic for p in got) == ["Іванович", "Петрович", "Федорович"]


def test_scan_many_agrees_with_scan_line_by_line(space) -> None:
    from nyshporka.search import anchors as A

    k = A.keys(1800, 1830)
    lines = ["у Ѳеодоръ Ѳеодоровъ Cкрсхнй родился сынъ", "того же двора",
             "Ѳеодоръ Ѳеодоръ Ѳеодоровъ", "Феодора Феодорова дочь", "просто рядок без імен",
             "Ѳеодоровъ Ѳеодоръ"]
    want = [(i, *A.scan(ln, k)) for i, ln in enumerate(lines) if A.scan(ln, k)]
    assert A.scan_many(lines, k) == want and want, want
