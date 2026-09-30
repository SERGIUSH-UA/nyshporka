"""Що охопив пошук: простір, тека прогонів, корені справ, непрочитане.

🔴 «Прочесано N прогонів» не каже, звідки ці N. Тека поза коренями справ,
справа без жодного прогону, корінь на від'єднаному диску — поза пошуком і
поза знаменником, а відповідь «не знайшлось» виглядає так само, як якби
прочесали все (звіт користувача 29.09.2026).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.search import reach as R


@pytest.fixture
def space(tmp_path: Path):
    (tmp_path / "data" / "raw").mkdir(parents=True)
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def _reiestr(monkeypatch: pytest.MonkeyPatch, cases: int, unread: int) -> None:
    from nyshporka.cases import db

    monkeypatch.setattr(db, "read_counts", lambda *a, **kw: {"cases": cases, "unread": unread})


def test_okhopleno_nazyvaie_prostir_i_neprochytane(space: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    _reiestr(monkeypatch, 40, 12)

    got = R.reach(7)

    assert got["workspace"] == str(space) and got["runs"] == 7
    assert got["runs_root"] == str(space / "reports" / "htr")
    assert (got["cases"], got["cases_unread"]) == (40, 12)
    text = R.line(got)
    assert "прогонів у ньому 7" in text and "без жодного прогону 12" in text
    assert text.endswith("поза цим пошук не дивився")


def test_bez_reiestru_ne_nul_a_nevidomo(space: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Реєстру немає — «скільки не читано, невідомо», а не «нуль»."""
    from nyshporka.cases import db

    # Шлях реєстру заморожено на імпорті — ставимо туди, де його точно немає.
    monkeypatch.setattr(db, "DB_PATH", space / "data" / "derived" / "case_index.sqlite")
    got = R.reach(3)

    assert got["cases"] is None and got["cases_unread"] is None
    assert "невідомо" in R.line(got)


def test_nedosiazhnyi_korin_nazvano(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ye = tmp_path / "arkhiv"
    ye.mkdir()
    (tmp_path / "ws" / "data" / "raw").mkdir(parents=True)
    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test",
                      extra_case_roots=(ye, tmp_path / "vidiednanyi-dysk")))
    try:
        _reiestr(monkeypatch, 1, 0)
        got = R.reach(1)
    finally:
        W.reset()

    assert got["case_roots"] == [str(tmp_path / "ws" / "data" / "raw"), str(ye)]
    assert got["roots_gone"] == [str(tmp_path / "vidiednanyi-dysk")]
    assert "недосяжні корені" in R.line(got) and "коренів справ 2" in R.line(got)


def test_lichylnyk_reiestru(tmp_path: Path) -> None:
    import sqlite3

    from nyshporka.cases import db

    path = tmp_path / "case_index.sqlite"
    con = sqlite3.connect(path)
    con.execute("create table cases (kind text, htr_stage text)")
    con.executemany("insert into cases values (?, ?)", [
        ("case", "none"), ("case", None), ("case", "pysar"), ("unfiled", "none")])
    con.commit()
    con.close()

    assert db.read_counts(path) == {"cases": 3, "unread": 2}


def test_porozhnii_blok_bez_riadka() -> None:
    assert R.line({}) == ""
