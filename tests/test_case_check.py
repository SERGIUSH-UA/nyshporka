"""🗂 `case.check`: як прочиталась шифра і де лежить тека — до «Зберегти».

Холодний прохід 07.10.2026: форма опису показувала шифру лише так, як її
набрали, а позначку «взяти теку під облік» — завжди, і вона читалась як
«завести справу».
"""
from __future__ import annotations

from pathlib import Path

import pytest

import nyshporka.cases.register as R
from nyshporka.ops_builtin import CaseCheckArgs, case_check


def test_shifra_is_read_into_archive_fond_opys_case() -> None:
    d = case_check(CaseCheckArgs(shifra="ф.315 оп.1 спр.0042", repo="ДАХмО")).data
    s = d["shifra"]
    assert (s["repo"], s["fond"], s["opys"], s["spr"]) == ("DAHMO", "315", "1", "42")
    assert s["label"] == "ДАХмО" and "Хмельницьк" in s["name"]
    assert s["text"] == "ДАХмО 315-1-42"
    assert d["shifra_error"] == ""


def test_a_shifra_without_archive_says_why() -> None:
    d = case_check(CaseCheckArgs(shifra="2-1-1741")).data
    assert d["shifra"] is None and "архіву" in d["shifra_error"]


def test_empty_fields_check_nothing() -> None:
    d = case_check(CaseCheckArgs()).data
    assert d == {"shifra": None, "shifra_error": "", "dir": None}


def test_folder_outside_the_workspace_is_named(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "reachable", lambda _d: False)
    d = case_check(CaseCheckArgs(case_dir=str(tmp_path))).data["dir"]
    assert d["exists"] is True and d["outside"] is True


def test_folder_inside_is_not_offered_adoption(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "reachable", lambda _d: True)
    d = case_check(CaseCheckArgs(case_dir=str(tmp_path))).data["dir"]
    assert d["outside"] is False


def test_a_missing_folder_is_not_called_outside(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Неіснуюча тека — не привід пропонувати «показувати там, де лежить»."""
    monkeypatch.setattr(R, "reachable", lambda _d: False)
    d = case_check(CaseCheckArgs(case_dir=str(tmp_path / "нема"))).data["dir"]
    assert d["exists"] is False and d["outside"] is False


def test_check_writes_nothing(tmp_path: Path) -> None:
    case_check(CaseCheckArgs(case_dir=str(tmp_path), shifra="ДАХмО 315-1-8433"))
    assert list(tmp_path.iterdir()) == []
