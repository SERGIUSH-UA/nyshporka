"""🏠 Канал запису й будь-яка родина з файла профілів.

🔴 Заради чого: метрика — таблиця. Ім'я дитини в одній колонці, батьки в
другій, кума в третій, і рушій читає їх окремими рядками. Коли прізвище батька
скалічене («Цально»), рядковий пошук запису не бачить, а ознаки з сусідніх
колонок того самого запису — бачать (Р-740-2-63, кадр 119).

🔴 Друге: ознаки зводяться в межах ЗАПИСУ, а не сторінки. На сторінці чотири-
вісім записів, і зведене по сторінці з'єднує чужих людей.

🔴 Третє: рід — будь-який профіль файла, а не лише активний; канон простору
чужій родині якорів не дає.
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
  tsynko:
    surname:
      display: Цинько
      paradigm: noun_ko
      stems:
        uk: Циньк
        ru_prereform: Цыньк
    kin:
      - {given: Галактіон, patronymic: Іванов, born: 1822, died: 1895}
      - {given: Прокопій, patronymic: Галактіонов, born: 1847, died: 1923}
      - {given: Васса, patronymic: Антонова, born: 1851}
      - {given: Северіан, patronymic: Прокопієв, born: 1870}
"""

W = 2000
# (текст, рамка). Розворот: ім'я дитини, батьки, кума — три колонки одного
# запису на висоті 100–260; нижче, на 1500+, — інший запис.
PAGE_1 = [
    ("Северіанъ", (300, 100, 500, 160)),
    ("Крестьянинъ Прошеній Гамастіановъ Цально", (600, 100, 1100, 160)),
    ("и законная жена его Васса Антонова", (600, 170, 1100, 230)),
    ("Стефанида Ѳеодорова Цинькова", (1150, 190, 1600, 250)),
    ("Священникъ Стефанъ Доброчинскій", (1650, 120, 1990, 180)),
    ("Іоаннъ Петровъ Ковальчукъ", (600, 1500, 1100, 1560)),
    ("Марія Даниловна", (600, 1570, 1100, 1630)),
]
# Ті самі дві ознаки, але в різних записах: далеко одна від одної.
PAGE_2 = [
    ("Северіанъ", (300, 100, 500, 160)),
    ("Крестьянинъ Іоаннъ Петровъ", (600, 100, 1100, 160)),
    ("Священникъ Стефанъ Доброчинскій", (1650, 120, 1990, 180)),
    ("Васса", (300, 1800, 500, 1860)),
    ("Крестьянинъ Андрей Ѳомичъ", (600, 1800, 1100, 1860)),
]
# Одне слово, схоже і на ім'я Галактіон, і на по батькові Галактіонов.
PAGE_3 = [
    ("Крестьянинъ Галактіоновъ", (600, 100, 1100, 160)),
    ("Священникъ Стефанъ Доброчинскій", (1650, 120, 1990, 180)),
]


def _write_run(root: Path, run: str, pages: dict[str, list[tuple[str, tuple]]],
               geo: bool) -> None:
    d = root / "reports" / "htr" / run
    d.mkdir(parents=True)
    meta: dict[str, dict] = {}
    for stem, lines in pages.items():
        (d / f"{stem}.txt").write_text("\n".join(t for t, _b in lines) + "\n", encoding="utf-8")
        if geo:
            (d / f"{stem}.lines.json").write_text(json.dumps(
                {"size": [W, 2600], "boxes": [list(b) for _t, b in lines]}), encoding="utf-8")
        meta[f"{stem}.jpg"] = {"lines": len(lines), "orient": 0}
    (d / "_htr_meta.json").write_text(json.dumps(
        {"model": "pysar_cyr_v19.pt", "script": "cyrillic", "pages": meta}), encoding="utf-8")


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import profile as P
    from nyshporka.core import workspace as WS

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "research_profile.yaml").write_text(PROFILE, encoding="utf-8")
    WS.reset()
    WS.use(WS.Workspace(root=tmp_path, name="тест", origin="test"))
    P.reset()
    # решта книги: записи чужих родин — щоб вага ознаки мала з чого рахуватись
    filler = {f"{n:04d}": [("Крестьянинъ Іоаннъ Петровъ Ковальчукъ", (600, 100, 1100, 160)),
                           ("и законная жена его Марія Даниловна", (600, 170, 1100, 230)),
                           ("Священникъ Стефанъ Доброчинскій", (1650, 120, 1990, 180))]
              for n in range(10, 22)}
    _write_run(tmp_path, "метрика",
               {"0001": PAGE_1, "0002": PAGE_2, "0003": PAGE_3, **filler}, geo=True)
    # Голос без геометрії: та сама сторінка 0001, дві ознаки; і сторінка, де три.
    _write_run(tmp_path, "голий", {
        "0001": [("Северіанъ Ковальчукъ", None), ("Васса Петрова", None)],
        "0005": [("Северіанъ", None), ("Васса Антонова", None), ("Прокопій", None)],
        **{n: [(t, None) for t, _b in lines] for n, lines in filler.items()},
    }, geo=False)

    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(["метрика", "голий"]))
    yield tmp_path
    P.reset()
    WS.reset()


# ── рід ──────────────────────────────────────────────────────────────────────
def test_the_query_finds_its_family_among_all_profiles(space: Path) -> None:
    """🔴 Доти пошук знав лише `fallback` — родина другим профілем шукалась голим словом."""
    from nyshporka.core import profile as P

    assert P.family_for_query("Цинько").name == "tsynko"
    assert P.family_for_query("Цынька").name == "tsynko"
    assert P.family_for_query("Сікорський").name == "rid"
    assert P.family_for_query("Ковальчук") is None
    forms, whose = P.forms_for_query("Цинько")
    assert whose == "Цинько" and "cinkova" in forms


def test_the_home_canon_is_not_kin_of_another_family(space: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Люди канону — рід простору. Чужій родині вони не якорі."""
    from nyshporka.core import profile as P
    from nyshporka.search import anchors as A

    monkeypatch.setattr(A, "_from_canon",
                        lambda prof=None: [A.Person(given="Ѳеодоръ", patronymic="Ѳеодоровъ",
                                                    born=1762)])
    home = {p.given for p in A.people(P.resolve("rid"))}
    other = {p.given for p in A.people(P.resolve("tsynko"))}
    assert "Ѳеодоръ" in home
    assert "Ѳеодоръ" not in other and "Северіан" in other


# ── запис ────────────────────────────────────────────────────────────────────
def test_the_surname_channel_misses_the_record(space: Path) -> None:
    """Приймач фікстури: прізвище батька скалічене, рядком запис не знаходиться."""
    from nyshporka import htr_store as S

    got = S.search("Цинько", name="метрика", thresh=80, profile=False)
    assert not any(h["page"] == "0001.jpg" and "Цально" in h["line"] for h in got["hits"])


def test_the_record_comes_from_the_columns_of_one_record(space: Path) -> None:
    """🔴 Заради чого канал: ім'я дитини, мати й кума з трьох колонок одного запису."""
    from nyshporka import htr_store as S

    got = S.search("Цинько", name="метрика", thresh=80, family="tsynko", record=True)
    rec = got["record"]
    assert rec["on"] and rec["hits"], rec
    top = rec["hits"][0]
    assert top["page"] == "0001.jpg" and top["by_geometry"] is True
    terms = {m["term"] for m in top["marks"]}
    assert {"Северіан", "Васса", "Антонова"} <= terms
    # смуга — висота запису, а не вся сторінка: запис нижче туди не входить
    assert top["band"][1] < 1500
    assert got["family"] == {"name": "tsynko", "display": "Цинько"}


def test_signs_of_different_records_are_not_joined(space: Path) -> None:
    """🔴 Северіан угорі сторінки й Васса в іншому записі внизу — не родина."""
    from nyshporka import htr_store as S

    got = S.search("Цинько", name="метрика", family="tsynko", record=True)
    assert not [h for h in got["record"]["hits"] if h["page"] == "0002.jpg"]


def test_a_bare_name_is_not_a_patronymic(space: Path) -> None:
    """«Іоаннъ» — це Іван, але ім'я, а не «Ивановъ»: по батькові Галактіона
    Івановича воно не ознака, хоч стоїть у кожному записі книги."""
    from nyshporka.core import profile as P
    from nyshporka.search import record as R

    ts = R.terms(P.resolve("tsynko"), "Цинько")
    memo: dict = {}
    from rapidfuzz import fuzz

    kinds = {ts.terms[i].kind for i, _s in R.match(fuzz, "Іоаннъ", ts, memo)}
    assert "patronymic" not in kinds
    kinds = {ts.terms[i].label for i, _s in R.match(fuzz, "Ивановъ", ts, memo)}
    assert "Іванов" in kinds


def test_one_word_is_one_sign(space: Path) -> None:
    """«Галактіоновъ» схожий і на ім'я, і на по батькові — але це одне слово."""
    from nyshporka import htr_store as S

    got = S.search("Цинько", name="метрика", family="tsynko", record=True)
    assert not [h for h in got["record"]["hits"] if h["page"] == "0003.jpg"]


def test_without_geometry_the_page_needs_one_sign_more(space: Path) -> None:
    """Без рамок межі запису немає: двох ознак на сторінці мало, трьох — досить,
    і запис позначено як зведений по сторінці."""
    from nyshporka import htr_store as S

    got = S.search("Цинько", name="голий", family="tsynko", record=True)
    pages = {h["page"]: h for h in got["record"]["hits"]}
    assert "0001.jpg" not in pages
    assert "0005.jpg" in pages and pages["0005.jpg"]["by_geometry"] is False


def test_the_signs_of_a_family(space: Path) -> None:
    """Ознаки — прізвище роду й люди з `kin`; без роду їх немає."""
    from nyshporka.search import record as R

    ts = R.terms(None, "", None, None)
    assert ts.empty
    from nyshporka.core import profile as P

    ts = R.terms(P.resolve("tsynko"), "Цинько")
    labels = [t.label for t in ts.terms]
    assert labels[0] == "Цинько" and "Северіан" in labels and "Галактіонов" in labels
    assert "Галактіон" in labels  # ім'я живе, поки людина жива: років справи немає


def test_years_narrow_the_signs(space: Path) -> None:
    """Ім'я — поки людина жива; по батькові — поки живі її діти."""
    from nyshporka.core import profile as P
    from nyshporka.search import record as R

    ts = R.terms(P.resolve("tsynko"), "Цинько", 1922, 1929)
    labels = {t.label for t in ts.terms}
    assert "Галактіон" not in labels          # помер 1895
    assert "Галактіонов" in labels            # його діти ще живі
    assert "Северіан" in labels


# ── пошук цілком ─────────────────────────────────────────────────────────────
def test_find_names_the_family_and_the_record_channel(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Цинько", "метрика", family="tsynko")
    assert not got.get("error"), got
    ids = {ch["id"]: ch for ch in got["ledger"]["channels"]}
    assert ids["record"]["ran"] and ids["record"]["hits"] >= 1
    assert got["record"]["hits"][0]["page"] == "0001.jpg"
    assert got["family"]["name"] == "tsynko"

    whole = T.find("Цинько", "", family="tsynko")
    ids = {ch["id"]: ch for ch in whole["ledger"]["channels"]}
    # поза справою ознаки людей нема чим звузити — канал мовчить і каже чому
    assert not ids["record"]["ran"] and "--case" in ids["record"]["why"]


def test_find_off_family_says_how_to_name_one(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Ковальчук", "метрика")
    ids = {ch["id"]: ch for ch in got["ledger"]["channels"]}
    assert not ids["record"]["ran"] and "--family" in ids["record"]["why"]


def test_unknown_family_is_refused(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Цинько", "метрика", family="немає")
    assert "немає профілю" in got.get("error", "")


def test_search_run_refuses_record_without_a_case(space: Path) -> None:
    from nyshporka.ops_builtin import SearchArgs, search_run

    env = search_run(SearchArgs(q="Цинько", record=True))
    assert not env.ok and "справи" in env.error
    env = search_run(SearchArgs(q="Цинько", where="all", record=True))
    assert not env.ok and "record" in env.error


def test_a_sign_weighs_less_in_a_longer_band() -> None:
    """🔴 Вага — неймовірність збігу в самій смузі: «Марія» в щільному списку
    (сотня слів) важить майже нуль, у короткому записі метрики — ні."""
    from nyshporka.search.record import Weigh

    w = Weigh({0: 0.002, 1: 0.0002})
    assert w(0, 10) > w(0, 100) > w(0, 1000)
    assert w(1, 100) > w(0, 100)          # рідша ознака важить більше
    assert w(0, 100_000) < 0.01           # у дуже довгій смузі — майже нуль
