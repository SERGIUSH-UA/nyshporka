"""Шифра в іншій формі — та сама справа; схожа шифра — ні.

`DAHMO/315/1/8591` і `DAHMO/315/8591` — одна справа, але бібліотека знає лише
одну форму. Прогін із формою з описом випадав із ремонту теки кадрів і з
резолвера мовчки. Водночас нормалізація не має права зробити з шифри ЧУЖУ
справу: інший опис того самого фонду чи інший архів.
"""

from __future__ import annotations

import pytest

from nyshporka.cases import resolve
from nyshporka.cases.resolve import LibraryIndex, resolve_run


def _row(key: str, *, opys: str | None = None, **extra: object) -> dict:
    repo, fond, *rest = key.split("/")
    return {"key": key, "repo": repo, "fond": fond, "opys": opys, "spr": rest[-1],
            "frames": 10, "desc_source": "source_json", **extra}


def test_form_with_opys_finds_the_library_key_without_it() -> None:
    idx = LibraryIndex([_row("DAHMO/315/8591")])
    assert idx.canonical("DAHMO/315/1/8591") == "DAHMO/315/8591"


def test_form_with_opys_matches_when_the_library_knows_the_opys() -> None:
    idx = LibraryIndex([_row("DAHMO/315/8591", opys="1")])
    assert idx.canonical("DAHMO/315/1/8591") == "DAHMO/315/8591"


def test_exact_key_is_returned_as_is() -> None:
    idx = LibraryIndex([_row("DAVO/904/24/25", opys="24")])
    assert idx.canonical("DAVO/904/24/25") == "DAVO/904/24/25"


def test_another_opys_of_the_same_fond_is_not_our_case() -> None:
    """🔴 Справа 25 опису 1 — не справа 25 опису 24."""
    idx = LibraryIndex([_row("DAVO/904/25", opys="1")])
    assert idx.canonical("DAVO/904/24/25") is None


def test_another_archive_is_not_our_case() -> None:
    idx = LibraryIndex([_row("DAVO/315/8591")])
    assert idx.canonical("DAHMO/315/8591") is None


def test_leading_zeros_do_not_matter() -> None:
    idx = LibraryIndex([_row("DAHMO/315/8591")])
    assert idx.canonical("DAHMO/315/01/08591") == "DAHMO/315/8591"


@pytest.mark.parametrize("key", ["", "DAHMO", "DAHMO/315", "DAVO/904/@opys24"])
def test_nonsense_and_bundles_are_not_normalised(key: str) -> None:
    idx = LibraryIndex([_row("DAHMO/315/8591")])
    assert idx.canonical(key) is None


def test_resolver_accepts_meta_key_in_another_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolve, "_run_overrides", lambda: {})
    idx = LibraryIndex([_row("DAHMO/315/8591")])
    link = resolve_run("spr-8591", "/tmp/htrcase/pages_dl_01", idx,
                       meta_key="DAHMO/315/1/8591")
    assert link.key == "DAHMO/315/8591"
    assert link.resolved_by == "meta_key"
