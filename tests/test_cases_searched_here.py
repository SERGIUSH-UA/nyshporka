"""🧾 «Прошукано тут»: реєстр справ спільний, а слід пошуку — проєктний.

Бібліотека в консолі показує, які справи цей рід уже шукав, і вміє дати
«прочитані, але не прошукані тут». Фільтр іде в SQL, тому знаменник (`total`)
— про відфільтроване, а не про всю сторінку. Справи вигадані (`TEST/…`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka import ops as O
from nyshporka.cases import db
from nyshporka.cases.model import CaseRow
from nyshporka.core import workspace as W
from nyshporka.search import trace

ROWS = [CaseRow(key="TEST/1/1/1", repo="TEST", fond="1", opys="1", spr="1",
                htr_stage="pysar"),
        CaseRow(key="TEST/1/1/4", repo="TEST", fond="1", opys="1", spr="4",
                htr_stage="partial"),
        CaseRow(key="TEST/1/1/2", repo="TEST", fond="1", opys="1", spr="2",
                htr_stage="pysar"),
        CaseRow(key="TEST/1/1/3", repo="TEST", fond="1", opys="1", spr="3")]


def _hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, hub_only: bool) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
    flag = "hub_only = true\n" if hub_only else ""
    (hub / W.MARKER).write_text(f'[workspace]\nname = "М"\nkeys = 2\n{flag}',
                                encoding="utf-8")
    W.reset()
    W.use(W._build(hub, "test"))
    monkeypatch.setattr(db, "collect_rows", lambda index=None, unreadable=None: (ROWS, []))
    db.build_index()
    return hub


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def test_rows_carry_the_date_and_filters_count_honestly(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    _hub(tmp_path, monkeypatch, hub_only=False)
    trace.note("TEST/1/1/1", q="Сидорук", thresh=80, hits=2, pages=10,
               models=["m1"], channels=["fuzzy"])
    d = O.call("cases.list", {}).data
    marks = {r["key"]: r["searched_here"] for r in d["cases"]}
    assert marks["TEST/1/1/1"] and marks["TEST/1/1/2"] is None
    here = O.call("cases.list", {"searched": "here"}).data
    assert [r["key"] for r in here["cases"]] == ["TEST/1/1/1"] and here["total"] == 1
    todo = O.call("cases.list", {"searched": "not_here", "htr": "pysar"}).data
    assert [r["key"] for r in todo["cases"]] == ["TEST/1/1/2"] and todo["total"] == 1


def test_pure_hub_has_no_project_trace(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _hub(tmp_path, monkeypatch, hub_only=True)
    d = O.call("cases.list", {}).data
    assert d["total"] == 4 and all("searched_here" not in r for r in d["cases"])
    env = O.call("cases.list", {"searched": "not_here"})
    assert not env.ok and "оберіть проєкт" in env.error
    # Свіжість реєстру з кореня Майстерні не чіпає шар проєкту (пошук роду, канон).
    assert db.staleness()["stale"] in (True, False)


def test_read_means_any_stage_but_none(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """`htr=read` — «прочитано хоч частково»: так Огляд проєкту рахує непрошукане."""
    _hub(tmp_path, monkeypatch, hub_only=False)
    trace.note("TEST/1/1/1", q="Сидорук", thresh=80, hits=0, pages=10,
               models=["m1"], channels=["fuzzy"])
    read = O.call("cases.list", {"htr": "read"}).data
    assert sorted(r["key"] for r in read["cases"]) == ["TEST/1/1/1", "TEST/1/1/2", "TEST/1/1/4"]
    # Дві залишкові при ліміті 1: `total` рахується до ліміту, а не по показаному.
    todo = O.call("cases.list", {"htr": "read", "searched": "not_here", "limit": 1}).data
    assert todo["total"] == 2 and len(todo["cases"]) == 1



def _project(hub: Path, pid: str) -> Path:
    root = hub / W.PROJECTS_DIR / pid
    root.mkdir(parents=True)
    (root / W.MARKER).write_text(f'[project]\nname = "Рід {pid}"\nkind = "family"\n',
                                 encoding="utf-8")
    return root


def _swept(root: Path, key: str) -> None:
    """Свіп від імені проєкту `root`: слід пишеться в його власний файл."""
    W.reset()
    W.use(W._build(root, "test"))
    trace.note(key, q="Сидорук", thresh=80, hits=0, pages=10,
               models=["m1"], channels=["fuzzy"])


def test_searched_by_shows_every_project(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Справи спільні, «прошукано» — проєктне: зріз бачить слід кожного роду."""
    hub = _hub(tmp_path, monkeypatch, hub_only=True)
    syd, kov = _project(hub, "sydoruk"), _project(hub, "kovalchuk")
    _swept(syd, "TEST/1/1/1")
    _swept(kov, "TEST/1/1/1")
    _swept(kov, "TEST/1/1/2")

    W.reset()
    W.use(W._build(hub, "test"))
    by = {r["key"]: r["searched_by"] for r in O.call("cases.list", {}).data["cases"]}
    assert sorted(by["TEST/1/1/1"]) == ["kovalchuk", "sydoruk"]
    assert list(by["TEST/1/1/2"]) == ["kovalchuk"] and by["TEST/1/1/3"] == {}

    W.reset()
    W.use(W._build(syd, "test"))
    rows = {r["key"]: r for r in O.call("cases.list", {}).data["cases"]}
    assert rows["TEST/1/1/2"]["searched_here"] is None
    assert list(rows["TEST/1/1/2"]["searched_by"]) == ["kovalchuk"]


def test_library_carries_searched_by_and_filters(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    hub = _hub(tmp_path, monkeypatch, hub_only=True)
    syd, kov = _project(hub, "sydoruk"), _project(hub, "kovalchuk")
    _swept(syd, "TEST/1/1/1")
    _swept(kov, "TEST/1/1/2")
    lib = tmp_path / "lib.json"
    lib.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(L, "library_path", lambda: lib)
    monkeypatch.setattr(LY, "has_layers", lambda: False)
    monkeypatch.setattr(LY, "entries", lambda: [
        {"key": k, "htr_stage": "pysar", "verdict": ""}
        for k in ("TEST/1/1/1", "TEST/1/1/2", "TEST/1/1/3")])

    W.reset()
    W.use(W._build(syd, "test"))
    d = O.call("library.list", {}).data
    by = {r["key"]: r["searched_by"] for r in d["cases"]}
    assert list(by["TEST/1/1/1"]) == ["sydoruk"] and list(by["TEST/1/1/2"]) == ["kovalchuk"]
    todo = O.call("library.list", {"searched": "not_here"}).data
    assert [r["key"] for r in todo["cases"]] == ["TEST/1/1/2", "TEST/1/1/3"]
    assert todo["total"] == 2
    here = O.call("library.list", {"searched": "here"}).data
    assert [r["key"] for r in here["cases"]] == ["TEST/1/1/1"]

    W.reset()
    W.use(W._build(hub, "test"))
    env = O.call("library.list", {"searched": "not_here"})
    assert not env.ok and "оберіть проєкт" in env.error
