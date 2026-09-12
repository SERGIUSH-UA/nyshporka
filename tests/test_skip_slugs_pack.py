"""Теки-не-справи з паку архівів справді відсікаються обходом диска.

🔴 Пак читав `skip_slugs` і зливав їх із накладкою, але жоден обхід його не
питав: бібліотека й реєстр справ брали лише захардкоджений набір. Тека, яку
дослідник оголосив «не справою» у своїй накладці, лягала в бібліотеку «справою
без шифри» — і нічого не падало (скани описів ІР НБУВ, 12.09.2026).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.archives import pack as P


@pytest.fixture
def overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    f = tmp_path / "archives.yaml"
    f.write_text("skip_slugs:\n  - probe_opysy\n", encoding="utf-8")
    monkeypatch.setenv(P.ENV_PACK, str(f))
    P.reset()
    yield
    P.reset()


def test_overlay_slug_reaches_library(overlay) -> None:
    from nyshporka import library

    got = library.skip_slugs()
    assert "probe_opysy" in got, "slug із накладки мусить доходити до обходу"
    assert "davo_opysy" in got, "вбудований перелік не губиться"


def test_overlay_slug_is_not_parsed_as_case(overlay) -> None:
    from nyshporka import library

    assert library.parse_case_path("data/raw/probe_opysy/006/006_1.pdf") is None
