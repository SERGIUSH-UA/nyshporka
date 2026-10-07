"""📥 Нові теки: групи «звідки», «Не справа» і повернення.

Екран звався «Приймальня», і навіщо він, не розумів навіть дослідник, що
працює із застосунком від початку (07.10.2026). Поруч із неописаними теками
там стояли збірки (уже описане), випуски однієї газети йшли сотнею рядків, а
книгу, якій шифри не буде, не було як прибрати.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nyshporka import library as L
from nyshporka.cases import db
from nyshporka.cases import resolve as R
from nyshporka.ops_builtin import IntakeAsideArgs, intake_aside, intake_list

FOLDERS = ["data/raw/gazeta/1854/n1", "data/raw/gazeta/1855/n2", "data/raw/kn",
           "data/raw/book_olds", "data/raw/bookXolds/t1"]


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ws"
    for p in [*FOLDERS, "data/raw/a"]:
        (root / p).mkdir(parents=True)
    dbp = tmp_path / "reg.sqlite"
    con = sqlite3.connect(dbp)
    con.executescript(db._SCHEMA)

    def row(key: str, kind: str, path: str, shifra: str = "", title: str = "") -> None:
        con.execute("INSERT INTO cases (key, kind, path, frames, shifra, title, why)"
                    " VALUES (?, ?, ?, 3, ?, ?, '')", (key, kind, path, shifra, title))

    for p in FOLDERS:
        row(f"@disk/{p}", "unfiled", p,
            shifra="плівка 77" if p.endswith("/kn") else f"без шифри · {p.rsplit('/', 1)[-1]}",
            title="КНИГА" if p.endswith("/kn") else "")
    row("A/1/1/1", "case", "data/raw/a", shifra="А 1-1-1")
    row("A/1/@zbirka", "bundle", "data/raw/a", shifra="збірка")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setattr(L, "ROOT", root)
    monkeypatch.setattr(R, "OVERRIDES_PATH", tmp_path / "overrides.json")
    R.load_overrides.cache_clear()
    yield root
    R.load_overrides.cache_clear()


def _kinds() -> dict[str, str]:
    con = sqlite3.connect(db.DB_PATH)
    try:
        return {p: k for p, k in con.execute("SELECT path, kind FROM cases WHERE key LIKE '@disk/%'")}
    finally:
        con.close()


def _by_label(groups: list[dict]) -> dict[str, dict]:
    return {g["label"]: g for g in groups}


def test_folders_are_grouped_by_their_source_folder(reg: Path) -> None:
    d = intake_list(None).data  # type: ignore[arg-type]
    g = _by_label(d["waiting"])
    assert set(g) == {"gazeta", "kn", "book_olds", "bookXolds"}
    assert len(g["gazeta"]["folders"]) == 2, "випуски різних років — одна газета"
    assert g["gazeta"]["aside_key"] == "data/raw/gazeta"
    kn = g["kn"]["folders"][0]
    assert kn["note"] == "плівка 77" and kn["title"] == "КНИГА"
    assert g["book_olds"]["folders"][0]["note"] == "", "«без шифри · ім'я» нічого не додає"
    assert d["counts"] == {"waiting": 5, "waiting_frames": 15, "aside": 0, "described": 1}


def test_bundles_and_cases_are_not_new_folders(reg: Path) -> None:
    d = intake_list(None).data  # type: ignore[arg-type]
    paths = {f["path"] for g in d["waiting"] for f in g["folders"]}
    assert "data/raw/a" not in paths


def test_set_aside_moves_the_group_and_is_written_as_a_decision(reg: Path,
                                                                tmp_path: Path) -> None:
    env = intake_aside(IntakeAsideArgs(paths=["data/raw/gazeta"], why="газета чи журнал"))
    assert env.ok and env.data["folders"] == 2
    d = intake_list(None).data  # type: ignore[arg-type]
    assert "gazeta" not in _by_label(d["waiting"])
    put = _by_label(d["aside"])["gazeta"]
    assert put["why"] == "газета чи журнал" and len(put["folders"]) == 2
    assert d["counts"]["aside"] == 2
    saved = json.loads((tmp_path / "overrides.json").read_text(encoding="utf-8"))
    assert saved["set_aside"]["data/raw/gazeta"]["why"] == "газета чи журнал"
    assert _kinds()["data/raw/gazeta/1854/n1"] == "material", "реєстр не виправлено одразу"


def test_bring_back_undoes_it(reg: Path, tmp_path: Path) -> None:
    intake_aside(IntakeAsideArgs(paths=["data/raw/gazeta"], why="газета"))
    env = intake_aside(IntakeAsideArgs(paths=["data/raw/gazeta"], undo=True))
    assert env.ok
    d = intake_list(None).data  # type: ignore[arg-type]
    assert "gazeta" in _by_label(d["waiting"]) and not d["aside"]
    saved = json.loads((tmp_path / "overrides.json").read_text(encoding="utf-8"))
    assert "set_aside" not in saved
    assert _kinds()["data/raw/gazeta/1855/n2"] == "unfiled"


def test_underscore_in_a_folder_name_does_not_catch_a_neighbour(reg: Path) -> None:
    """🔴 `LIKE 'book_olds/%'` зачепив би й `bookXolds`: `_` там — будь-який символ."""
    intake_aside(IntakeAsideArgs(paths=["data/raw/book_olds"], why="книга"))
    k = _kinds()
    assert k["data/raw/book_olds"] == "material"
    assert k["data/raw/bookXolds/t1"] == "unfiled"


def test_a_decision_made_after_the_registry_was_built_still_counts(reg: Path) -> None:
    """Рішення накладається й на зріз, зібраний раніше за нього."""
    R.put_aside(["data/raw/kn"], "книга")          # реєстр не чіпаємо
    d = intake_list(None).data  # type: ignore[arg-type]
    assert "kn" not in _by_label(d["waiting"])
    assert "data/raw/kn" in _by_label(d["aside"])["kn"]["aside_key"]


@pytest.mark.parametrize("bad", ["data/raw", "../x", "C:/Users", "/etc", "data/raw/нема", ""])
def test_refuses_what_is_not_a_folder_inside(reg: Path, bad: str) -> None:
    assert not intake_aside(IntakeAsideArgs(paths=[bad], why="x")).ok


def test_aside_for_matches_the_folder_and_below_only() -> None:
    aside = {"data/raw/gazeta": {"why": "газета"}}
    assert R.aside_for("data/raw/gazeta", aside) == ("data/raw/gazeta", "газета")
    assert R.aside_for("data/raw/gazeta/1854/n1", aside) == ("data/raw/gazeta", "газета")
    assert R.aside_for("data/raw/gazeta2", aside) is None
