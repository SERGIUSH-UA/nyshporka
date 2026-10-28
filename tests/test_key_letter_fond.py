"""Ключ, який пакет друкує, пакет і приймає — зокрема з літерним фондом.

`cases.list` віддавав ключ радянського фонду як `DAHMO/R-100/7`, а розбір ключа
знав фонд лише як `\\d+`: той самий рядок, поданий назад у `--case`,
відмовлявся словами «не розпізнав справу» (issue #21). Тепер ключ —
`DAHMO/R-100/1/7`, а стара форма лишається читаною.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import casekey
from nyshporka.library import _mk_key

LIB = [
    {"key": "DAHMO/R-100/1/7", "repo": "DAHMO", "fond": "R-100", "opys": "1",
     "spr": "7", "shifra": "ДАХмО R-100-1-7"},
    {"key": "DAVIO/R-6129/24/5", "repo": "DAVIO", "fond": "R-6129", "opys": "24",
     "spr": "5", "shifra": "ДАВіО R-6129-24-5"},
    {"key": "DAHMO/315/1/8433", "repo": "DAHMO", "fond": "315", "opys": "1",
     "spr": "8433", "shifra": "ДАХмО 315-1-8433"},
    {"key": "ANRM/211/3/140", "repo": "ANRM", "fond": "211", "opys": "3",
     "spr": "140", "shifra": "ANRM 211-3-140"},
]


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override", W._override)   # повернути простір після тесту
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka.pagestore import store as S

    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "pages_root", lambda: tmp_path / "data" / "pages")
    monkeypatch.setattr(S, "load_library", lambda: LIB)
    return S


@pytest.mark.parametrize(("old", "want"), [
    ("DAHMO/315/7", ("DAHMO", "315", None, "7")),
    ("ANRM/211-3/140", ("ANRM", "211", "3", "140")),
    ("DAHMO/R-100/7", ("DAHMO", "R-100", None, "7")),
    ("DAVIO/R-6129-24/5", ("DAVIO", "R-6129", "24", "5")),
    ("DAVIO/Р-6129-24/5", ("DAVIO", "R-6129", "24", "5")),     # кирилична «Р»
])
def test_an_old_key_keeps_the_letter_prefix_with_the_fond(
        old: str, want: tuple[str, str, str | None, str]) -> None:
    assert casekey.parse_legacy(old) == want


@pytest.mark.parametrize("key", ["DAHMO/R-100/1/7", "DAVIO/R-6129/24/5",
                                 "DAHMO/315/1/8433", "ANRM/211/3/140"])
def test_key_printed_by_the_package_is_accepted_back(store: Any, key: str) -> None:
    assert store.resolve_case(key).key == key


@pytest.mark.parametrize(("old", "key"), [("DAHMO/R-100/7", "DAHMO/R-100/1/7"),
                                          ("DAVIO/R-6129-24/5", "DAVIO/R-6129/24/5"),
                                          ("ANRM/211-3/140", "ANRM/211/3/140")])
def test_an_old_key_leads_to_the_same_case(store: Any, old: str, key: str) -> None:
    assert store.resolve_case(old).key == key


def test_letter_fond_key_parts(store: Any) -> None:
    ref = store.resolve_case("DAHMO/R-100/1/7")
    assert (ref.repo, ref.fond, ref.opys, ref.spr) == ("DAHMO", "R-100", "1", "7")


def test_cyrillic_prefix_in_key_is_the_same_fond(store: Any) -> None:
    assert store.resolve_case("DAHMO/Р-100/1/7").key == "DAHMO/R-100/1/7"


DASO = {"key": "DASO/7720/15/133", "repo": "DASO", "fond": "7720", "opys": "15",
        "spr": "133", "shifra": "ДАСО 7720-15-133"}
DAPO = {"key": "DAPO/R-1989/1/1", "repo": "DAPO", "fond": "R-1989", "opys": "1",
        "spr": "1", "shifra": "ДАПО R-1989-1-1"}


@pytest.mark.parametrize(("shifra", "key"), [
    ("ДАСО Р-7720-15-133", "DASO/7720/15/133"),      # кирилична «Р»
    ("ДАСО P-7720-15-133", "DASO/7720/15/133"),      # латинська «P» замість «Р»
    ("ДАСО R-7720-15-133", "DASO/7720/15/133"),
    ("ДАСО 7720-15-133", "DASO/7720/15/133"),
    ("ДАПО Р-1989-1-1", "DAPO/R-1989/1/1"),
    ("ДАПО P-1989-1-1", "DAPO/R-1989/1/1"),
    ("ДАПО R-1989-1-1", "DAPO/R-1989/1/1"),
    ("ДАПО 1989-1-1", "DAPO/R-1989/1/1"),
])
def test_fond_prefix_spelling_finds_the_case_on_disk(
        store: Any, monkeypatch: pytest.MonkeyPatch, shifra: str, key: str) -> None:
    """Справа на диску дістається будь-яким написанням префікса (відгук №5 з порталу)."""
    monkeypatch.setattr(store, "load_library", lambda: [*LIB, DASO, DAPO])
    assert store.resolve_case(shifra).key == key


def test_exact_fond_wins_over_another_spelling(store: Any,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Точний збіг першим: фонд «П-» не підміняється фондом «Р-»."""
    p = {**DASO, "key": "DASO/P-7720/15/133", "fond": "P-7720", "shifra": "ДАСО П-7720-15-133"}
    monkeypatch.setattr(store, "load_library", lambda: [*LIB, DASO, p])
    assert store.resolve_case("ДАСО П-7720-15-133").key == "DASO/P-7720/15/133"
    assert store.resolve_case("ДАСО 7720-15-133").key == "DASO/7720/15/133"


def test_two_possible_fonds_are_refused_with_both_named(
        store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    r = {**DASO, "key": "DASO/R-7720/15/133", "fond": "R-7720", "shifra": "ДАСО R-7720-15-133"}
    monkeypatch.setattr(store, "load_library", lambda: [*LIB, DASO, r])
    with pytest.raises(ValueError, match="кілька"):
        store.resolve_case("ДАСО P-7720-15-133")


def test_bundle_key_still_parses(store: Any) -> None:
    assert store.resolve_case("DAHMO/315/@fuzovka").spr == "@fuzovka"


@pytest.mark.parametrize(("repo", "fond", "spr", "opys"), [
    ("DAHMO", "R-100", "7", None),
    ("DAVIO", "R-6129", "5", "24"),
    ("ANRM", "211", "140", "3"),
])
def test_mk_key_round_trips_through_parse(repo: str, fond: str, spr: str,
                                          opys: str | None) -> None:
    key = _mk_key(repo, fond, spr, opys)
    ck = casekey.parse(key)
    assert ck is not None
    assert (ck.repo, ck.fond, ck.opys, ck.spr) == (repo, fond, opys or casekey.UNKNOWN, spr)


def test_fond_registry_key_with_letter_fond() -> None:
    from nyshporka.fonds.registry import parse_key

    assert parse_key("DAVIO/R-6129/24/5") == ("DAVIO", "R-6129", "24", "5", "")
    assert parse_key("ДАВіО Р-6129-24-5") == ("DAVIO", "R-6129", "24", "5", "")
    # опису не названо — опис за замовчуванням фонду з паку; немає й його — порожньо
    assert parse_key("DAHMO/230/43") == ("DAHMO", "230", "1", "43", "")
    assert parse_key("CDIAK/2/43") == ("CDIAK", "2", "", "43", "")


@pytest.mark.parametrize("ref, spr, want", [
    ("ЦДІАК, Фонд 127, Опис 1076, Справа 199-А, 507 арк.", "199", "199a"),
    ("ДАХмО, Опис 1, Справа 84а", "84", "84a"),
    ("ДАХмО, Опис 1, Справа 8433", "8433", "8433"),
    ("Справа 199-А", "200", "200"),
    ("Опис 1, Справа 12, 30 арк.", "12", "12"),
    ("", "7", "7"),
])
def test_litera_spravy_z_repository_ref(ref: str, spr: str, want: str) -> None:
    """id канону губить літеру (номер без літери при «Справа 199-А» в описі)."""
    from nyshporka.library import _spr_from_ref

    assert _spr_from_ref(ref, spr) == want
