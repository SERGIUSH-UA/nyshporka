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
    assert d["total"] == 3 and all("searched_here" not in r for r in d["cases"])
    env = O.call("cases.list", {"searched": "not_here"})
    assert not env.ok and "оберіть проєкт" in env.error


def test_read_means_any_stage_but_none(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """`htr=read` — «прочитано хоч частково»: так Огляд проєкту рахує непрошукане."""
    _hub(tmp_path, monkeypatch, hub_only=False)
    trace.note("TEST/1/1/1", q="Сидорук", thresh=80, hits=0, pages=10,
               models=["m1"], channels=["fuzzy"])
    read = O.call("cases.list", {"htr": "read"}).data
    assert sorted(r["key"] for r in read["cases"]) == ["TEST/1/1/1", "TEST/1/1/2"]
    todo = O.call("cases.list", {"htr": "read", "searched": "not_here", "limit": 1}).data
    assert todo["total"] == 1
