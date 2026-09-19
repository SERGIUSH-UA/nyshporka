"""Ключ, який пакет друкує, пакет і приймає — зокрема з літерним фондом.

`cases.list` віддає ключ радянського фонду як `DAHMO/R-100/7`, а трисегментний
розбір ключа знав фонд лише як `\\d+`: той самий рядок, поданий назад у
`--case`, відмовлявся словами «не розпізнав справу» (issue #21).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.library import _mk_key, split_fond_opys

LIB = [
    {"key": "DAHMO/R-100/7", "repo": "DAHMO", "fond": "R-100", "opys": "1",
     "spr": "7", "shifra": "ДАХмО R-100-1-7"},
    {"key": "DAVIO/R-6129-24/5", "repo": "DAVIO", "fond": "R-6129", "opys": "24",
     "spr": "5", "shifra": "ДАВіО R-6129-24-5"},
    {"key": "DAHMO/315/8433", "repo": "DAHMO", "fond": "315", "opys": "1",
     "spr": "8433", "shifra": "ДАХмО 315-1-8433"},
    {"key": "ANRM/211-3/140", "repo": "ANRM", "fond": "211", "opys": "3",
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


@pytest.mark.parametrize(("part", "want"), [
    ("315", ("315", None)),
    ("211-3", ("211", "3")),
    ("R-100", ("R-100", None)),
    ("R-6129-24", ("R-6129", "24")),
    ("Р-6129-24", ("R-6129", "24")),     # кирилична «Р»
])
def test_split_fond_opys_keeps_letter_prefix_with_the_fond(
        part: str, want: tuple[str, str | None]) -> None:
    assert split_fond_opys(part) == want


@pytest.mark.parametrize("key", ["DAHMO/R-100/7", "DAVIO/R-6129-24/5",
                                 "DAHMO/315/8433", "ANRM/211-3/140"])
def test_key_printed_by_the_package_is_accepted_back(store: Any, key: str) -> None:
    assert store.resolve_case(key).key == key


def test_letter_fond_key_parts(store: Any) -> None:
    ref = store.resolve_case("DAHMO/R-100/7")
    assert (ref.repo, ref.fond, ref.spr) == ("DAHMO", "R-100", "7")


def test_cyrillic_prefix_in_key_is_the_same_fond(store: Any) -> None:
    assert store.resolve_case("DAHMO/Р-100/7").key == "DAHMO/R-100/7"


def test_bundle_key_still_parses(store: Any) -> None:
    assert store.resolve_case("DAHMO/315/@fuzovka").spr == "@fuzovka"


@pytest.mark.parametrize(("repo", "fond", "spr", "opys"), [
    ("DAHMO", "R-100", "7", None),
    ("DAVIO", "R-6129", "5", "24"),
    ("ANRM", "211", "140", "3"),
])
def test_mk_key_round_trips_through_split(repo: str, fond: str, spr: str,
                                          opys: str | None) -> None:
    key = _mk_key(repo, fond, spr, opys)
    assert key
    fond_part = key.split("/")[1]
    got_fond, got_opys = split_fond_opys(fond_part)
    assert got_fond == fond
    assert got_opys == (opys if "-" in fond_part[len(fond):] else None)


def test_fond_registry_key_with_letter_fond() -> None:
    from nyshporka.fonds.registry import parse_key

    assert parse_key("DAVIO/R-6129/24/5") == ("DAVIO", "R-6129", "24", "5", "")
    assert parse_key("ДАВіО Р-6129-24-5") == ("DAVIO", "R-6129", "24", "5", "")
    assert parse_key("DAHMO/230/43") == ("DAHMO", "230", "1", "43", "")
