"""📜 Покажчики гродських книг: особа й село XVII–XVIII ст. з адресою акта.

Що тут тримається тестом:

1. **Прізвище знаходиться будь-якою мовою.** Гасло польське («Czetwertyński»), а
   питають кирилицею («Четвертинський»); основа прізвища згортається однаково, і
   варіант у дужках — теж прізвище.
2. **Село знаходиться будь-якою мовою** тим самим згортанням, що склад
   РК-парафій.
3. **Акт веде на свою сторінку.** Номер акта транскрибованої книги має адресу;
   загублена книга — адресу книги, бо актів окремо в неї немає.
4. **Без пака — відмова, а не нуль.** І особи загальним пошуком не питаються.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

#: Вигадані книги, люди й села: жодне не належить джерелу.
BOOKS = [
    {"sig": "99-1-3", "kind": "transcribed", "title": "Księga grodzka testowa 1768",
     "genre": "zapisowa", "office": "Gród testowy", "voivodeship": "województwo testowe",
     "years": "1768", "url": "https://example.org/99-1-3/index.html"},
    {"sig": "KAC 7", "kind": "lost", "title": "Testowa grodzka księga z lat 1690",
     "genre": "zapisowa", "office": "Testów – gród", "voivodeship": "kijowskie",
     "years": "1690", "year_from": 1690, "year_to": 1690,
     "url": "https://example.org/zaginione/0007/index.html"},
]
ACTS = "sygnatura\takt\turl\n99-1-3\t12\thttps://example.org/99-1-3/czesc-01.html#akt-12\n" \
       "99-1-3\t13\thttps://example.org/99-1-3/czesc-01.html#akt-13\n"
OSOBY = ("sygnatura;haslo;opis;akty\n"
         "99-1-3;Czetwertyński Jan;wielmożny, strona kontraktu (1768);12, 13\n"
         "99-1-3;Zielińska Agata (z Kowalskich [?]);wdowa;12\n"
         "KAC 7;Czetwertynski (Czetwertyński) Iwan;, łowczy;II/20\n"
         "99-1-3;Andrzej (nazwisko nieodczytane);podstoli;13\n")
MIEJSCA = ("sygnatura;haslo;opis;akty\n"
           "99-1-3;Hrabowce;(wieś Hrabowce) – wieś w powiecie testowym;12\n"
           "99-1-3;Wójtówka [?];(Woytowka) – wieś;13\n"
           "KAC 7;Zielonka (Zielona);, wieś;I/32\n")


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    from nyshporka.catalog import build as B
    from nyshporka.catalog import store as S

    src = tmp_path / "src"
    src.mkdir()
    (src / "books.json").write_text(json.dumps(BOOKS, ensure_ascii=False), encoding="utf-8")
    (src / "acts.tsv").write_text(ACTS, encoding="utf-8")
    (src / "osoby.csv").write_text("﻿" + OSOBY, encoding="utf-8")
    (src / "miejsca.csv").write_text(MIEJSCA, encoding="utf-8")
    res = B.build_courtbooks(src, cat / "courtbooks-test-2026.10.sqlite",
                             pack_id="courtbooks-test-2026.10", taken="2026-10-19",
                             source="https://example.org")
    assert (res["books"], res["acts"], res["persons"], res["places"]) == (2, 2, 4, 3)
    S.invalidate()
    yield cat
    S.invalidate()


def test_surname_key_meets_across_languages() -> None:
    from nyshporka.sources.sks import surname_key

    assert surname_key("Четвертинський") == surname_key("Четвертинский") == surname_key("Czetwertyński")
    assert surname_key("Jaroszyński") == surname_key("Ярошинський")


def test_person_forms_take_variant_not_maiden_name() -> None:
    from nyshporka.sources.sks import person_forms, surname_key

    forms, given = person_forms("Czetwertynski (Kotwicz) Iwan")
    assert forms == [surname_key("Czetwertynski"), surname_key("Kotwicz")]
    assert given
    forms, _ = person_forms("Zielińska Agata (z Kowalskich [?])")
    assert forms == [surname_key("Zielińska")]
    assert person_forms("Andrzej (nazwisko nieodczytane)")[0] == []


def test_given_name_in_parentheses_is_not_a_surname() -> None:
    """«Jabłoński Stanisław (Jan)» — у дужках ім'я: на «Ян» це не збіг 100."""
    from nyshporka.sources.sks import person_forms, surname_key

    assert person_forms("Jabłoński Stanisław (Jan)")[0] == [surname_key("Jabłoński")]
    assert person_forms("Krzętowski (Krętowski) Jan")[0] == [surname_key("Krzętowski")]


def test_person_found_in_cyrillic_with_act_links(catalog: Path) -> None:
    from nyshporka.catalog.query import find_court_persons

    rows = find_court_persons("Четвертинський").rows
    sigs = {r["sig"] for r in rows}
    assert sigs == {"99-1-3", "KAC 7"}
    jan = next(r for r in rows if r["sig"] == "99-1-3")
    assert [x["url"] for x in jan["act_links"]] == [
        "https://example.org/99-1-3/czesc-01.html#akt-12",
        "https://example.org/99-1-3/czesc-01.html#akt-13"]
    lost = next(r for r in rows if r["sig"] == "KAC 7")
    assert lost["book_kind"] == "lost"
    assert lost["act_links"] == [{"akt": "II/20", "url": ""}]
    assert lost["book_url"].endswith("/zaginione/0007/index.html")


def test_given_name_ranks_but_does_not_filter(catalog: Path) -> None:
    from nyshporka.catalog.query import find_court_persons

    rows = find_court_persons("Четвертинський Іван").rows
    assert rows[0]["sig"] == "KAC 7"          # Iwan ↔ Іван піднімає
    assert len(rows) == 2                     # Jan не відсіяно
    assert all(r["score"] <= 100 for r in rows)   # ім'я — у порядку, не в балі


def test_place_found_in_ukrainian_and_russian(catalog: Path) -> None:
    from nyshporka.catalog.query import find_court_places

    for q in ("Грабівці", "Грабовцы", "Hrabowce"):
        rows = find_court_places(q).rows
        assert [(r["name"], r["score"]) for r in rows] == [("Hrabowce", 100)], q
    assert find_court_places("Війтівка").rows[0]["name"] == "Wójtówka [?]"
    assert find_court_places("Zielona").rows[0]["sig"] == "KAC 7"   # варіант у дужках


def test_sources_hits_and_explicit_only(catalog: Path) -> None:
    from nyshporka.sources.sks import SksPersonsSource, SksPlacesSource

    persons = SksPersonsSource()
    assert getattr(persons, "explicit_only", False) is True
    assert not getattr(SksPlacesSource(), "explicit_only", False)
    hits = persons.search("Czetwertynski")
    one = next(h for h in hits if h.shifra == "ЦДІАК 99-1-3")
    assert one.repo == "CDIAK" and one.fond == "99"
    assert "Kowal" in one.note
    lost = next(h for h in hits if h.shifra == "KAC 7")
    assert lost.url.endswith("/zaginione/0007/index.html")   # актів окремо немає — книга
    kind, info = persons.catalog_source()
    assert kind == "bundled" and info["rows"] == 7


def test_without_pack_refuses_instead_of_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.catalog import store as S
    from nyshporka.sources.base import SourceError
    from nyshporka.sources.sks import SksPlacesSource

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path))
    S.invalidate()
    try:
        assert SksPlacesSource().catalog_source()[0] == "none"
        with pytest.raises(SourceError):
            SksPlacesSource().search("Hrabowce")
    finally:
        S.invalidate()


def test_missing_pack_hint_is_an_action_that_exists(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Порада у відмові мусить давати пак, якщо виконати її буквально."""
    from nyshporka.catalog import store as S

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path))
    S.invalidate()
    try:
        with pytest.raises(S.CatalogMissing) as exc:
            S.require("courtbooks")
    finally:
        S.invalidate()
    msg = str(exc.value)
    assert "nysh catalog update" in msg and "catalog install --from" in msg
    assert S.RELEASES_URL in msg and "--domain" not in msg
    # порада веде на команду, яка є
    from nyshporka.catalog.cli import app

    assert "update" in {c.name for c in app.registered_commands}


def test_migration_check_names_missing_catalog_domains(catalog: Path) -> None:
    """Каталог із самими гродськими книгами — міграція називає, чого бракує."""
    from nyshporka.migrate import run_check

    res = run_check("catalog_current", catalog)
    assert res.state == "todo"
    assert "churches" in res.detail and "courtbooks" not in res.detail.split("—")[0]
    assert "catalog install --from" in res.detail
