"""🧬 Написання профілю в пошуку: людина набирає одне, рід пишеться десятьма.

🔴 Профіль знав 10-13 написань від першого дня, і жодне з них у пошук не
потрапляло: форма показувала їх чипсами, кожен чип летів окремим запитом — тож
замість одного знаменника виходив десяток окремих нулів.

⚠ Приймач узято з рахунку, а не навмання. Рушій з'їдає ПОЧАТОК слова частіше,
ніж кінець, і саме такий уламок лишається поза порогом:

    «корскаго» проти основи  58.8   ← нижче порога 80, не знайдеться ніколи
    «корскаго» проти форм    85.7   ← знаходиться

На цілому написанні («Сикорскаго» 87.5 → 100.0) тест не доводив би нічого: воно
проходить поріг і без форм.
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
"""


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "research_profile.yaml").write_text(
        PROFILE, encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reset()

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    # Уламок із з'їденим початком — те, заради чого форми й потрібні.
    # ⚠ Стоїть САМ у рядку навмисно: пошук ще й клеїть сусідні токени, і на
    # «сынъ корскаго» склейка сама витягує 82 бали — тобто сторінка знайшлась
    # би й без профілю, а тест доводив би не те.
    (run / "0001.txt").write_text("корскаго\nвъ томъ же дворѣ\n",
                                  encoding="utf-8")
    # Ціле написання: знаходиться і без форм, тож служить контролем.
    (run / "0002.txt").write_text("восприемникъ Сикорскій Петръ\nсело Кривое\n",
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
    yield tmp_path
    P.reset()
    W.reset()


def _pages(res: dict) -> set[str]:
    return {h["page"] for h in res["hits"]}


def test_a_chewed_off_beginning_is_found_only_with_the_forms(space) -> None:
    """🔴 Заради чого все: уламок нижче порога стає знахідкою."""
    from nyshporka import htr_store as S

    assert "0001.jpg" in _pages(S.search("Сікорський", thresh=80))


def test_without_the_profile_that_page_stays_invisible(space) -> None:
    """Приймач самого тесту: без форм сторінки немає, інакше він порожній."""
    from nyshporka import htr_store as S

    got = S.search("Сікорський", thresh=80, profile=False)
    assert "0001.jpg" not in _pages(got)
    assert "0002.jpg" in _pages(got), "ціле написання мусить знаходитись завжди"


def test_the_answer_says_whose_forms_were_added(space) -> None:
    """Мовчазне розширення — та сама вада, що мовчазний фільтр, лише навпаки."""
    from nyshporka import htr_store as S

    res = S.search("Сікорський", thresh=80)
    assert res["profile_of"] == "Сікорський"
    assert res["stems_added"], "додані написання мусять бути названі"


def test_what_was_typed_still_comes_first(space) -> None:
    from nyshporka import htr_store as S

    res = S.search("Сікорський", thresh=80)
    assert res["stems"][0] == res["stems_asked"][0]


def test_a_foreign_query_does_not_drag_the_clan_in(space) -> None:
    """🔴 Пошук по назві села не сміє тягнути за собою форми роду.

    Інакше знаменник бреше в обидва боки: людина питала про одне, а шукали
    ще й інше, і нуль по її питанню читається як нуль по обох.
    """
    from nyshporka import htr_store as S

    res = S.search("Городківка", thresh=80)
    assert res["profile_of"] == ""
    assert not res["stems_added"]


def test_no_profile_is_not_a_failure(tmp_path, monkeypatch) -> None:
    """На чужому просторі профілю може не бути — пошук працює як раніше."""
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reset()
    try:
        assert P.forms_for_query("Сікорський") == ([], "")
    finally:
        P.reset()
        W.reset()
