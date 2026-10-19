"""Майстерня й проєкт: кожна властивість шляху знає, чия вона.

Поки `hub_root` не задано, обидва корені збігаються — старий простір працює як
є. Коли задано, хабові шляхи (кадри, прочитане, реєстр) мусять іти в Майстерню,
а проєктні (канон, база роду, вердикти) — лишатися в проєкті. Помилка тут не
падає: вердикт одного проєкту мовчки ліг би в канон іншого роду.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.core import workspace as W

HUB_PROPS = ("raw", "derived", "pages", "spotter", "share", "cases", "citations",
             "htr_reports")
PROJECT_PROPS = ("canonical", "project_derived", "candidates", "clan_hunt", "reports",
                 "config", "marker", "data")


def _split(tmp_path: Path) -> W.Workspace:
    return W.Workspace(root=tmp_path / "projects" / "rid", hub_root=tmp_path / "hub",
                       origin="test")


def test_one_root_means_both_layers_in_it(tmp_path: Path) -> None:
    ws = W.Workspace(root=tmp_path, origin="test")
    assert ws.hub == tmp_path
    for name in HUB_PROPS + PROJECT_PROPS:
        assert getattr(ws, name).is_relative_to(tmp_path), name


@pytest.mark.parametrize("name", HUB_PROPS)
def test_hub_paths_go_to_the_hub(tmp_path: Path, name: str) -> None:
    ws = _split(tmp_path)
    assert getattr(ws, name).is_relative_to(tmp_path / "hub"), name


@pytest.mark.parametrize("name", PROJECT_PROPS)
def test_project_paths_stay_in_the_project(tmp_path: Path, name: str) -> None:
    ws = _split(tmp_path)
    assert getattr(ws, name).is_relative_to(tmp_path / "projects" / "rid"), name


def test_case_roots_start_in_the_hub(tmp_path: Path) -> None:
    assert _split(tmp_path).case_roots()[0] == tmp_path / "hub" / "data" / "raw"


@pytest.mark.real_paths
def test_module_paths_follow_the_active_space(tmp_path: Path) -> None:
    """Функції шляхів доменних модулів читають активний простір у мить виклику —
    тож перемикання простору їх зачіпає, і кожна йде у свій шар."""
    from nyshporka import decode_hits, htr_store, library
    from nyshporka.cases import collect, db, resolve
    from nyshporka.pagestore import store

    hub, proj = tmp_path / "hub", tmp_path / "projects" / "rid"
    W.use(_split(tmp_path))
    try:
        for p in (library.library_path(), library.raw_dir(), library.scan_targets_path(),
                  library.case_base(), htr_store.htr_root(), store.pages_root(),
                  db.index_path(), resolve.overrides_path(), collect.htr_root()):
            assert p.is_relative_to(hub), p
        for p in (library.verdicts_path(), library.sources_dir(), decode_hits.hits_path(),
                  collect.clan_state(), collect.derived_db()):
            assert p.is_relative_to(proj), p
        W.use(W.Workspace(root=tmp_path / "other", origin="test"))
        assert library.library_path().is_relative_to(tmp_path / "other")
    finally:
        W.reset()
