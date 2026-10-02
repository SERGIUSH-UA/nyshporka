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

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "PAGES_ROOT", tmp_path / "data" / "pages")
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
