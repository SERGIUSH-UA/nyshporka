"""🔎 Пошук по сховищу: роль, тип акту й вісь місця.

🔴 Фільтри жили в шарі даних із самого початку (`grep_records` приймає `role`,
`rtype`, `place`), а поверхня передавала лише `q/thresh/case/limit` — тобто
питання «хто був БАТЬКОМ із цим прізвищем» не відрізнялось від «хто був
восприємником». Саме заради цієї різниці записи й розбирають структурою, а не
прозою, і саме її обіцяє докстрінг `nysh records add`.

Друге, що тут стережеться, — щоб несумісний фільтр ВІДМОВЛЯВСЯ, а не мовчки
ігнорувався. Проігнорований `role` віддає ширшу вибірку, ніж просили, і читач
бере її за звужену: «серед батьків не знайшлось» замість «не знайшлось
узагалі». Нуль такої форми закриває напрям, якого не перевіряли.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()

#: Одне прізвище у трьох ролях і двох типах акту — менше не розрізнить
#: «звузив» від «випадково знайшов одне».
RECORDS = [
    {"rtype": "birth", "date": "1858-03-14", "scans": ["0106.jpg"], "row": "14",
     "places": ["Мястковка"],
     "persons": [
         {"role": "child", "name": "Анна"},
         {"role": "father", "name": "Іоаннъ Ковальскій",
          "surname": "Ковальскій"},
         {"role": "godfather", "name": "Феодоръ Ковальскій",
          "surname": "Ковальскій"}]},
    {"rtype": "death", "date": "1859-01-02", "scans": ["0107.jpg"],
     "persons": [
         {"role": "deceased", "name": "Стефанъ Ковальскій",
          "surname": "Ковальскій", "place": "Городківка"}]},
]

CASE = "DAHMO/315/8433"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    for n in (106, 107, 108):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    return tmp_path


def _run(*args, stdin: str | None = None):
    # ⚠ Кеш індексу тримається на mtime файла, а тест пише й читає той самий
    # файл у межах однієї секунди. Без скидання друга перевірка бачила б стан
    # до запису — і зелений тест доводив би не те.
    from nyshporka.pagestore import query
    query._CACHE.clear()
    return runner.invoke(app, list(args), input=stdin)


def _data(res) -> dict:
    got = json.loads(res.stdout)
    return got.get("data", got) if isinstance(got, dict) else got


def _seed(records=RECORDS) -> None:
    r = _run("records", "add", CASE, "--json",
             stdin=json.dumps(records, ensure_ascii=False))
    assert r.exit_code == 0, r.output


# ── роль і тип акту ──────────────────────────────────────────────────────────
def test_role_narrows_the_search_to_the_asked_role(case):
    """🔴 «Хто був батьком» — інше питання, ніж «хто був восприємником»."""
    _seed()
    all_hits = _data(_run("records", "grep", "Ковальський", "--json"))["hits"]
    assert len(all_hits) == 3, all_hits

    only = _data(_run("records", "grep", "Ковальський",
                      "--role", "father", "--json"))["hits"]
    assert len(only) == 1
    assert only[0]["role"] == "father"
    assert only[0]["name"] == "Іоаннъ Ковальскій"


def test_rtype_narrows_the_search_to_the_asked_act(case):
    _seed()
    got = _data(_run("records", "grep", "Ковальський",
                     "--rtype", "death", "--json"))["hits"]
    assert len(got) == 1
    assert got[0]["rtype"] == "death" and got[0]["role"] == "deceased"


# ── вісь місця ───────────────────────────────────────────────────────────────
def test_place_axis_finds_what_the_name_axis_cannot(case):
    """Місце учасника — інша вісь, а не бідніший різновид прізвищевої."""
    _seed()
    by_name = _data(_run("records", "grep", "Городківка", "--json"))["hits"]
    assert by_name == []

    by_place = _data(_run("records", "grep", "Городківка",
                          "--axis", "place", "--json"))["hits"]
    assert len(by_place) == 1
    assert by_place[0]["place"] == "Городківка"


def test_place_axis_also_sees_the_place_of_the_act_itself(case):
    """У записі місце тримається двічі: де подія і звідки людина."""
    _seed()
    got = _data(_run("records", "grep", "Мястковка",
                     "--axis", "place", "--json"))["hits"]
    assert got and got[0]["rtype"] == "birth"


def test_pages_place_axis_reads_places_not_surnames(case):
    """Приймач на переплутані імена: `places=` для сторінок, `place=` для записів."""
    r = _run("pages", "note", CASE, "0108.jpg", "--type", "birth",
             "--surnames", "Ковальський", "--places", "Мурафа", "--json")
    assert r.exit_code == 0, r.output

    got = _data(_run("pages", "grep", "Мурафа", "--axis", "place", "--json"))
    assert got["hits"], "вісь місця не побачила виписаного місця сторінки"
    assert _data(_run("pages", "grep", "Мурафа", "--json"))["hits"] == []


# ── несумісний фільтр ────────────────────────────────────────────────────────
def test_an_incompatible_filter_is_refused_not_ignored(case):
    """🔴 Головний тест: тихо ширша вибірка гірша за відмову.

    Проігнорований `role` дав би відповідь на інше питання, і вона виглядала б
    як відповідь на поставлене.
    """
    r = _run("pages", "grep", "Ковальський", "--where", "pages",
             "--role", "father", "--json")
    assert r.exit_code == 1
    env = json.loads(r.stdout)
    assert env["ok"] is False
    assert "where=records" in env["error"], env["error"]


def test_the_place_axis_is_refused_on_decode(case):
    r = _run("pages", "grep", "Мястковка", "--where", "decode",
             "--axis", "place", "--json")
    assert r.exit_code == 1
    assert "where=pages" in json.loads(r.stdout)["error"]


def test_the_zero_names_the_filter_it_applied(case):
    """Нуль без назви звуження читається як нуль по всьому."""
    _seed()
    env = json.loads(_run("records", "grep", "Ковальський",
                          "--role", "priest", "--json").stdout)
    assert env["data"]["hits"] == []
    assert env["data"]["coverage"]["role"] == "priest"
    said = " ".join(w["text"] for w in env["warnings"])
    assert "priest" in said, said


# ── прокинуте в командний рядок ──────────────────────────────────────────────
def test_status_of_named_scans_does_not_crash_the_human_output(case):
    """Дві форми відповіді — дві гілки друку; одна на обидві падала KeyError."""
    r = _run("pages", "status", CASE, "--scans", "0106.jpg,9999.jpg")
    assert r.exit_code == 0, r.output
    assert "0106.jpg" in r.output and "9999.jpg" in r.output


def test_the_agent_who_noted_the_page_is_visible_afterwards(case):
    """Поле, якого не видно нізвідки, — те саме, що поля немає."""
    r = _run("pages", "note", CASE, "0106.jpg", "--type", "confession",
             "--surnames", "Ковальскій", "--agent", "сеанс-7", "--json")
    assert r.exit_code == 0, r.output
    got = _data(_run("pages", "show", CASE, "0106.jpg", "--json"))
    assert got["page"]["agent"] == "сеанс-7"


def test_show_by_rid_names_the_existing_ones_when_it_misses(case):
    _seed()
    rid = _data(_run("records", "grep", "Ковальський", "--json"))["hits"][0]["rid"]
    got = _data(_run("records", "show", CASE, rid, "--json"))
    assert got["record"]["rid"] == rid

    r = _run("records", "show", CASE, "нема-такого", "--json")
    assert r.exit_code == 1
    assert rid in json.loads(r.stdout)["error"]


# ── заміна записів ───────────────────────────────────────────────────────────
def test_replace_refuses_until_it_is_told_how_much_it_may_erase(case):
    """🔴 Підтвердження числом: щоб його підставити, відмову треба прочитати."""
    _seed()
    r = _run("records", "add", CASE, "--replace", "--json",
             stdin=json.dumps(RECORDS[:1], ensure_ascii=False))
    assert r.exit_code == 1
    assert "confirm=2" in json.loads(r.stdout)["error"]


def test_replace_says_how_much_it_erased(case):
    _seed()
    r = _run("records", "add", CASE, "--replace", "--confirm", "2", "--json",
             stdin=json.dumps(RECORDS[:1], ensure_ascii=False))
    assert r.exit_code == 0, r.output
    env = json.loads(r.stdout)
    assert env["data"]["erased"] == 2
    said = " ".join(w["text"] for w in env["warnings"])
    assert "стерто 2" in said, said
    assert len(_data(_run("records", "grep", "Ковальський", "--json"))["hits"]) == 2


def test_a_wrong_confirmation_does_not_erase(case):
    _seed()
    r = _run("records", "add", CASE, "--replace", "--confirm", "1", "--json",
             stdin=json.dumps(RECORDS[:1], ensure_ascii=False))
    assert r.exit_code == 1
    assert len(_data(_run("records", "grep", "Ковальський", "--json"))["hits"]) == 3


# ── переліки не роз'їжджаються з моделями ────────────────────────────────────
def test_the_search_literals_match_the_models() -> None:
    """🔴 Перелік ролей живе тричі: модель, схема пошуку, довідка CLI.

    Розбіжність тут не падає: `--role` просто не матчить нічого, і фільтр
    віддає нуль — тобто найдорожчу з можливих відповідей.
    """
    from typing import get_args

    from nyshporka import cli
    from nyshporka.ops_builtin import SearchArgs
    from nyshporka.pagestore.models import RecordType, Role

    roles = set(get_args(Role))
    rtypes = set(get_args(RecordType))

    assert set(get_args(SearchArgs.model_fields["role"].annotation)) == roles | {""}
    assert set(get_args(SearchArgs.model_fields["rtype"].annotation)) == rtypes | {""}
    assert roles <= set(cli._ROLES_HELP.replace("|", " ").split())
    assert rtypes <= set(cli._RTYPES_HELP.replace("|", " ").split())
