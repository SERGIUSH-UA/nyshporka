"""🏠 `--with`: ознаки запису від людини, там де домінує одне прізвище.

🔴 Заради чого: у селі, де одне прізвище стоїть майже на кожній сторінці книги
народжень, пошук за ним не виокремлює жодного запису. Канал запису вмикається
від двох ознак, а прізвище саме — одна; ні `kin`, ні канону в простору може не
бути. `--with` дає людині спосіб додати ознаку, не ведучи профіль: ім'я з
довідника (збіг через гніздо — латинське «Georgius» знаходиться за «Юрко») чи
прізвище поруч.

Родина тут вигадана.
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

W = 2000


def _band(y: int, *rows: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    return [(t, (600, y + i * 70, 1500, y + i * 70 + 60)) for i, t in enumerate(rows)]


def _write_run(root: Path, run: str, pages: dict[str, list]) -> None:
    d = root / "reports" / "htr" / run
    d.mkdir(parents=True)
    meta: dict[str, dict] = {}
    for stem, lines in pages.items():
        (d / f"{stem}.txt").write_text("\n".join(t for t, _b in lines) + "\n", encoding="utf-8")
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
    # Прізвище Мирончук — на кожній сторінці; «Іван» — теж на кожній (часте ім'я),
    # а латинський «Georgius» — на одній-єдиній.
    pages: dict[str, list] = {}
    for n in range(1, 31):
        pages[f"{n:04d}"] = (_band(100, "Pater Joannes", "Мирончукъ Іоаннъ Петровъ", "Parochus loci")
                             + _band(1500, "Мирончукъ Степанъ", "Maria uxor"))
    pages["0031"] = (_band(100, "Pater Georgius", "Мирончукъ Георгій Іоанновъ", "Parochus loci")
                     + _band(1500, "Мирончукъ Степанъ", "Maria uxor"))
    _write_run(tmp_path, "метрика", pages)

    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    list(ST.ensure_all(["метрика"]))
    yield tmp_path
    P.reset()
    WS.reset()


def test_the_surname_alone_keeps_the_channel_off(space: Path) -> None:
    """Приймач: без `--with` у простору немає другої ознаки — канал мовчить."""
    from nyshporka import htr_store as S

    got = S.search("Мирончук", name="метрика", thresh=80, record=True)
    assert not got["record"]["on"] and not got["record"]["hits"]


def test_with_turns_the_record_channel_on_without_kin(space: Path) -> None:
    from nyshporka import htr_store as S

    got = S.search("Мирончук", name="метрика", thresh=80, record=True, with_terms=["Юрко"])
    rec = got["record"]
    assert rec["terms"] and rec["hits"], rec
    assert {t["source"] for t in rec["terms"]} == {"запит", "--with"}


def test_a_latin_form_is_found_through_the_name_nest(space: Path) -> None:
    """🔴 «Georgius» у тексті — це «Юрко» у запиті: гніздо імен, а не fuzzy на словах."""
    from nyshporka import htr_store as S

    got = S.search("Мирончук", name="метрика", thresh=80, record=True, with_terms=["Юрко"])
    top = got["record"]["hits"][0]
    assert top["page"] == "0031.jpg"
    tokens = {m["term"]: m["token"] for m in top["marks"]}
    assert tokens["Юрко"] == "Georgius"


def test_a_rare_with_sign_outranks_a_common_one(space: Path) -> None:
    """🔴 Смуга з прізвищем і рідкісним словом стоїть вище за смуги з прізвищем і
    частим: вага — неймовірність випадкового збігу в самій смузі."""
    from nyshporka import htr_store as S

    got = S.search("Мирончук", name="метрика", thresh=80, record=True,
                   with_terms=["Юрко", "Іван"], limit=100)
    hits = got["record"]["hits"]
    assert hits[0]["page"] == "0031.jpg"
    rare = hits[0]["score"]
    assert all(h["score"] < rare for h in hits[1:]), [h["score"] for h in hits[:4]]


def test_a_foreign_active_profile_kin_is_not_borrowed(space: Path) -> None:
    """Запит про прізвище, якого немає в профілях, kin активного профілю не бере."""
    from nyshporka.search import record as R

    ts = R.terms(None, "Мирончук", None, None, with_terms=["Юрко", "Степан"])
    assert [t.source for t in ts.terms] == ["запит", "--with", "--with"]
    assert [t.kind for t in ts.terms] == ["surname", "given", "given"]


def test_a_word_that_is_not_a_given_name_is_a_surname_sign(space: Path) -> None:
    from nyshporka.search import record as R

    ts = R.terms(None, "Мирончук", None, None, with_terms=["Дзвінка", "Ян"])
    assert [t.kind for t in ts.terms] == ["surname", "surname"]
    assert ts.ignored == ("Ян",), "коротке слово не порівнюється, але про нього сказано"


def test_find_names_where_the_signs_came_from(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Мирончук", "метрика", with_terms=["Юрко"])
    ch = {c["id"]: c for c in got["ledger"]["channels"]}
    assert ch["record"]["ran"] and ch["record"]["hits"] >= 1
    srcs = {x["source"]: x["terms"] for x in ch["record"]["sources"]}
    assert srcs["--with"] == ["Юрко"]
    assert got["record"]["hits"][0]["page"] == "0031.jpg"


def test_with_still_needs_a_case(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Мирончук", "", with_terms=["Юрко"])
    ch = {c["id"]: c for c in got["ledger"]["channels"]}
    assert not ch["record"]["ran"] and "однієї справи" in ch["record"]["why"]


def test_find_without_with_stays_as_before(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Мирончук", "метрика")
    ch = {c["id"]: c for c in got["ledger"]["channels"]}
    assert not ch["record"]["ran"] and "--family" in ch["record"]["fix"]
    assert got["total"] > 30


def test_truncated_output_is_a_warning_in_the_envelope(space: Path) -> None:
    from nyshporka.ops_text import TextFindArgs, text_find

    env = text_find(TextFindArgs(q="Мирончук", case="метрика", limit=5, with_terms=["Юрко"]))
    assert env.ok, env.error
    cut = [w for w in env.warnings if w.code == "shown_truncated"]
    assert len(cut) == 1
    assert "показано 5 із" in cut[0].text and "--limit" in cut[0].text
    assert "запис" in cut[0].text or "прізвище" in cut[0].text
    full = text_find(TextFindArgs(q="Мирончук", case="метрика", limit=5000,
                                  with_terms=["Юрко"]))
    assert not [w for w in full.warnings if w.code == "shown_truncated"]


def test_search_run_takes_with_and_warns_on_truncation(space: Path) -> None:
    from nyshporka.ops_builtin import SearchArgs, search_run

    env = search_run(SearchArgs(q="Мирончук", case="метрика", limit=5, with_terms=["Юрко"]))
    assert env.ok, env.error
    assert env.data["coverage"]["record"]["hits"]
    assert [w for w in env.warnings if w.code == "shown_truncated"]
    bad = search_run(SearchArgs(q="Мирончук", with_terms=["Юрко"]))
    assert not bad.ok and "справи" in bad.error


def test_the_cli_prints_the_record_block_for_with(space: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    res = CliRunner().invoke(app, ["text", "find", "Мирончук", "--case", "метрика",
                                   "--with", "Юрко", "--limit", "3"])
    assert res.exit_code == 0, res.output
    assert "🏠" in res.output and "Georgius" in res.output
    assert "--with: Юрко" in res.output


# ── канон ────────────────────────────────────────────────────────────────────
def _canon(root: Path) -> None:
    from nyshporka.models.common import GedDate, NameVariant
    from nyshporka.models.fact import Fact
    from nyshporka.models.person import Person
    from nyshporka.storage.files import write_person

    persons = root / "data" / "canonical" / "persons"
    persons.mkdir(parents=True)
    write_person(persons / "P1.md", Person(
        id="P1", sex="M",
        names=[NameVariant(form="Юрій Мирончук", lang="uk", primary=True,
                           given="Юрій", surname="Мирончук"),
               NameVariant(form="Georgius Mironczuk", lang="pl", given="Georgius",
                           surname="Mironczuk")],
        facts=[Fact(type="baptism", date=GedDate(value="1851-03-02")),
               Fact(type="burial", date=GedDate(value="1919"))]))
    write_person(persons / "P2.md", Person(
        id="P2", sex="F",
        names=[NameVariant(form="Параскевія Дзвінська", lang="uk", primary=True,
                           given="Параскевія", surname="Дзвінська"),
               NameVariant(form="Parascevia Mironczuk", lang="pl", given="Parascevia",
                           surname="Mironczuk")],
        facts=[Fact(type="birth", date=GedDate(value="1855"))]))
    write_person(persons / "P4.md", Person(
        id="P4", sex="M",
        names=[NameVariant(form="Мирон Мирончук", lang="uk", primary=True,
                           given="Мирон", surname="Мирончук"),
               NameVariant(form="Hieronim Mironczuk", lang="pl", given="Hieronim",
                           surname="Mironczuk")],
        facts=[Fact(type="birth", date=GedDate(value="1860"))]))
    write_person(persons / "P3.md", Person(
        id="P3", sex="M",
        names=[NameVariant(form="Степан Стороженко", lang="uk", primary=True)],
        facts=[Fact(type="birth", date=GedDate(value="1850"))]))


def test_canon_uses_every_name_variant_and_the_maiden_surname(space: Path) -> None:
    from nyshporka.core import profile as P
    from nyshporka.search import anchors as A

    _canon(space)
    prof = P.resolve("rid")
    got = {p.given: p for p in A._from_canon(prof, surnames=("mironcuk",))}
    man = got["Юрій"]
    # «Georgius» — те саме гніздо, що «Юрій»: окремою формою не стає
    assert man.alt_given == ()
    assert man.surname == "", "чоловікові чуже прізвище не дівоче"
    # Форма поза гніздом лишається ключем тієї самої людини, а не новою особою
    assert got["Мирон"].alt_given == ("Hieronim",)
    # хрещення й поховання рахуються датами життя
    assert (man.born, man.died) == (1851, 1919)
    wife = got["Параскевія"]
    assert wife.surname == "Дзвінська", "дівоче прізвище, а не прізвище роду"


def test_canon_of_the_queried_surname_feeds_the_channel_without_a_profile(space: Path) -> None:
    from nyshporka.search import record as R

    _canon(space)
    ts = R.terms(None, "Мирончук", 1860, 1900, with_terms=["Юрко"])
    labels = {t.label: t for t in ts.terms}
    # Юрій несе прізвище запиту: його ім'я — ознака з гніздом форм, джерело — канон
    assert labels["Юрій"].source == "канон"
    assert any(k.startswith("georg") for k in labels["Юрій"].keys)
    assert labels["Дзвінська"].kind == "surname"
    # Степан Стороженко — чужа картка: ні його ім'я, ні прізвище в ознаки не йдуть
    assert "Степан" not in labels and "Стороженко" not in labels


def test_canon_of_a_non_home_profile_is_limited_to_its_surname(space: Path) -> None:
    from nyshporka.search import anchors as A

    _canon(space)
    cfg = space / "config" / "research_profile.yaml"
    cfg.write_text(PROFILE + """\
  myronchuk:
    surname:
      display: Мирончук
      paradigm: noun_bare
      stems:
        uk: Мирончук
""", encoding="utf-8")
    from nyshporka.core import profile as P

    P.reset()
    got = {p.given for p in A.people(P.resolve("myronchuk"))}
    assert {"Юрій", "Параскевія"} <= got and "Степан" not in got
    assert {p.given for p in A.people(P.resolve("rid"))} >= {"Юрій", "Степан"}


def test_a_real_patronymic_survives_the_cleaning(space: Path) -> None:
    from nyshporka.models.common import NameVariant
    from nyshporka.models.person import Person
    from nyshporka.search import anchors as A

    p = A._canon_person(Person(id="P9", names=[NameVariant(form="Іван Петрович Мирончук")]),
                        subs=("mironcuk",), fam=())
    assert (p.given, p.patronymic) == ("Іван", "Петрович")
