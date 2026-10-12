"""Номери друкованого видання з дерева тек: роки, порядок, сторінки, пропуски.

Розкладка — та, якою люди вже кладуть підшивки:
`<Назва>/<РІК>/<N (НАСКРІЗНИЙ) РРРР-ММ-ДД>/<кадри>`, здвоєні номери
`12-13 (779-780) …`. Наскрізна нумерація дає знаменник зібрання: яких номерів
у підшивці немає.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from nyshporka import vydannia
from nyshporka import vydannia_issues as V


def _issue(root: Path, year: str, name: str, pages: int) -> Path:
    d = (root / year / name) if year else (root / name)
    d.mkdir(parents=True)
    for k in range(1, pages + 1):
        Image.new("L", (20, 30), 200).save(d / f"{k:04d}.jpg", "JPEG")
    return d


@pytest.fixture
def edition(tmp_path: Path) -> Path:
    root = tmp_path / "Колективізоване село"
    _issue(root, "1936", "4 (771) 1936-01-08", 2)
    _issue(root, "1936", "3 (770) 1936-01-06", 2)
    _issue(root, "1936", "12-13 (779-780) 1936-01-22", 4)
    _issue(root, "1936", "6 (773) 1936-01-11", 0)          # тека без кадрів
    (root / "1936" / "нотатки").mkdir()                    # не номер
    _issue(root, "1937", "1 (782) 1937-01-01", 1)
    return root


def test_issues_are_parsed_in_date_order(edition: Path) -> None:
    ed = V.scan(edition)

    assert ed.title == "Колективізоване село"
    assert ed.years == [1936, 1937]
    assert [(i.no, i.no_total, i.date) for i in ed.of_year(1936)] == [
        ("3", "770", "1936-01-06"), ("4", "771", "1936-01-08"),
        ("12-13", "779-780", "1936-01-22")]
    assert ed.pages_total() == 9


def test_what_is_not_an_issue_is_reported_not_dropped(edition: Path) -> None:
    ed = V.scan(edition)

    assert [p.name for p in ed.empty] == ["6 (773) 1936-01-11"]
    assert [p.name for p in ed.unparsed] == ["нотатки"]


def test_issues_json_numbers_pages_within_the_year(edition: Path) -> None:
    rows = V.scan(edition).issues_json(1936)

    assert [(r["no"], r["first_page"], r["pages"]) for r in rows] == [
        ("3", 1, 2), ("4", 3, 2), ("12-13", 5, 4)]
    assert rows[2]["no_total"] == "779-780" and rows[0]["date"] == "1936-01-06"


def test_missing_numbers_are_the_collection_denominator(edition: Path) -> None:
    ed = V.scan(edition)

    # 773 лежить порожньою текою — для зібрання його так само немає
    assert ed.missing(1936) == ["772", "773", "774", "775", "776", "777", "778"]
    # наскрізна нумерація не рветься на межі року: 781 мав вийти наприкінці 1936-го
    assert ed.missing() == [*ed.missing(1936), "781"]


def test_a_single_year_folder_is_an_edition_too(edition: Path) -> None:
    ed = V.scan(edition / "1936")

    assert ed.title == "Колективізоване село" and ed.years == [1936]


@pytest.mark.parametrize("name, want", [
    ("3 (770) 1936-01-06", ("3", "770", "1936-01-06", False, "1936-01-06_3")),
    ("12 - 13 (779 – 780) 1936-01-22", ("12-13", "779-780", "1936-01-22", False,
                                        "1936-01-22_12-13")),
    ("4(771) 1936-01-08", ("4", "771", "1936-01-08", False, "1936-01-08_4")),
    ("5 1936-01-10", ("5", "", "1936-01-10", False, "1936-01-10_5")),
    # реальні теки партнера (Пирятин, НБУВ)
    ("2 1934-02-26", ("2", "", "1934-02-26", False, "1934-02-26_2")),
    ("1 (1918-10-24)", ("1", "", "1918-10-24", False, "1918-10-24_1")),
    ("Додаток 1935-08-12", ("", "", "1935-08-12", True, "1935-08-12_dod")),
    ("Додаток до № 111 (518) 1935-08-12", ("111", "518", "1935-08-12", True,
                                           "1935-08-12_dod-111")),
])
def test_issue_folder_names(name: str, want: tuple) -> None:
    got = V.parse_issue_name(name)
    assert got is not None
    assert (got.no, got.no_total, got.date, got.supplement, got.ident) == want


@pytest.mark.parametrize("name", [
    "нотатки", "1936", "spr-12 1934-02-12", "1934-13-40", "1 1934-02-12 1934-02-13",
    "315-1-8433", "Колективізоване село",
])
def test_what_is_not_an_issue_name(name: str) -> None:
    assert V.parse_issue_name(name) is None


def test_an_issue_and_its_supplement_of_the_same_day_are_two_issues(tmp_path: Path) -> None:
    """🔴 У партнера «111 … 1935-08-12» і «Додаток … 1935-08-12» діставали одну
    шифру `CASES/1935/8/12`. Тут вони — два номери, додаток іде після свого."""
    root = tmp_path / "Колективізоване село"
    _issue(root, "1935", "Додаток до № 111 (518) 1935-08-12", 1)
    _issue(root, "1935", "111 (518) 1935-08-12", 2)
    _issue(root, "1935", "112 (519) 1935-08-14", 2)
    ed = V.scan(root)

    assert [(i.no, i.supplement) for i in ed.issues] == [
        ("111", False), ("111", True), ("112", False)]
    assert len({i.ident for i in ed.issues}) == 3
    rows = ed.issues_json(1935)
    assert [(r["first_page"], r.get("note")) for r in rows] == [
        (1, None), (3, "додаток"), (4, None)]
    assert ed.missing(1935) == []              # додаток у знаменник не йде


def test_an_edition_without_year_folders(tmp_path: Path) -> None:
    """«Громадянин/1 (1918-10-24)/» — номери просто в теці видання."""
    root = tmp_path / "Громадянин"
    _issue(root, "", "1 (1918-10-24)", 2)
    _issue(root, "", "2 (1918-10-31)", 1)
    ed = V.scan(root)

    assert ed.title == "Громадянин" and ed.years == [1918]
    assert [i.no for i in ed.issues] == ["1", "2"] and not ed.unparsed


def test_a_city_folder_holds_several_editions(tmp_path: Path) -> None:
    """`cases/НБУВ/Пирятин/<Назва>/…` — кожна газета своє видання, і номер на
    п'ятому рівні від `cases/` знаходиться так само, як на четвертому."""
    city = tmp_path / "cases" / "НБУВ" / "Пирятин"
    _issue(city / "Громадянин", "", "1 (1918-10-24)", 1)
    _issue(city / "За ударну працю", "1934", "2 1934-02-26", 1)
    _issue(city / "Колективізоване село", "1934", "16 (443) 1934-02-12", 1)

    found = V.find_editions(tmp_path / "cases")
    assert [p.name for p in found] == ["Громадянин", "За ударну працю",
                                       "Колективізоване село"]
    assert V.find_editions(city / "За ударну працю") == [city / "За ударну працю"]
    assert [i.name for i in V.scan(found[1]).issues] == ["2 1934-02-26"]


def test_two_folders_of_one_issue_are_reported(tmp_path: Path) -> None:
    root = tmp_path / "Газета"
    _issue(root, "1934", "1 1934-02-12", 1)
    _issue(root, "1934", "1 (77) 1934-02-12", 1)
    ed = V.scan(root)

    assert len(ed.issues) == 1 and len(ed.dupes) == 1


def test_the_library_does_not_read_an_issue_date_as_a_case() -> None:
    """🔴 Дата в імені теки номера ставала фондом/описом/справою: `За ударну
    працю/1934/1 1934-02-12` і `Колективізоване село/1934/16 (443) 1934-02-12`
    обидві давали `CASES/1934/2/12`. Номер газети архівною справою не є."""
    from nyshporka.library import parse_case_path

    for rel in ("cases/НБУВ/Пирятин/За ударну працю/1934/1 1934-02-12",
                "cases/НБУВ/Пирятин/Колективізоване село/1934/16 (443) 1934-02-12",
                "cases/НБУВ/Пирятин/Колективізоване село/1935/Додаток 1935-08-12",
                "cases/НБУВ/Пирятин/Громадянин/1 (1918-10-24)"):
        assert parse_case_path(rel) is None, rel
    # архівні шифри розбираються, як і досі
    assert parse_case_path("data/raw/dahmo_315/315-1-8433") == ("DAHMO", "315", "1", "8433")


def test_suggested_code_is_a_valid_edition_code() -> None:
    code = V.suggest_code("Колективізоване село", "Пирятин")

    assert code == "KOLSELO_PYR"
    assert vydannia.is_code(code) and vydannia.key(code, 1936) == "VYD/KOLSELO_PYR/1936"
    assert vydannia.is_code(V.suggest_code("1936"))
