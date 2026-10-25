"""🧭 Джерело без здатності відмовляє, а не падає трасуванням і не віддає нуль.

Прогін 25.10.2026: `nysh browse skanoteka` падав `AttributeError: … no attribute
'browse'`, а `nysh find "…" --source skanoteka` друкував «знайдено 0 · шукали в: —»
— нуль без жодного запиту. Обидва — наслідок однієї вади: `caps` оголошено, а
виклик іде напряму в метод.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka import ops as O
from nyshporka.sources.base import SourceError, supports
from nyshporka.sources.registry import load


def _sources() -> list[Any]:
    return list(load(None).all())


@pytest.fixture
def space(tmp_path: Path) -> Path:
    from nyshporka.core import workspace as W

    ws = tmp_path / "ws"
    (ws / "data" / "derived").mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    return ws


@pytest.mark.parametrize("cap,op", [("browse", "catalog.browse"),
                                    ("manifest", "catalog.manifest")])
def test_every_source_without_the_capability_refuses_through_the_op(
        space: Path, cap: str, op: str) -> None:
    lacking = [s for s in _sources() if not supports(s, cap)]
    assert lacking, "перевірка нічого не доводить: усі джерела вміють " + cap
    for s in lacking:
        args = {"source": s.id} if cap == "browse" else {"source": s.id, "ref": "x"}
        env = O.call(op, args)
        assert not env.ok and f"не вміє {cap}" in (env.error or ""), (s.id, env.error)
        assert s.id in (env.error or "")


def test_skanoteka_browse_is_an_honest_refusal_in_the_cli(space: Path) -> None:
    from nyshporka.cli import app

    r = CliRunner().invoke(app, ["browse", "skanoteka"])
    assert r.exit_code == 1, r.output
    assert "не вміє browse" in r.output and "Traceback" not in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_find_with_a_source_that_cannot_search_is_a_refusal_not_a_zero(space: Path) -> None:
    env = O.call("catalog.search", {"q": "Cerkowna", "source": "skanoteka"})
    assert not env.ok
    assert "не вміє пошук" in (env.error or "") and "skanoteka" in (env.error or "")
    from nyshporka.cli import app

    r = CliRunner().invoke(app, ["find", "Cerkowna", "--source", "skanoteka"])
    assert "не вміє пошук" in r.output
    assert "знайдено 0" not in r.output


def test_a_source_with_search_still_answers_with_its_zero(space: Path) -> None:
    # `reabilitovani` без мережі відмовляє сама, але питається — тобто потрапляє
    # в «питали», а не в «не вміє пошук».
    env = O.call("catalog.search", {"q": "Коваленко", "source": "reabilitovani"})
    assert "не вміє пошук" not in (env.error or "")


def test_slow_source_is_given_up_with_a_reason_not_waited_for_forever(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_builtin as B

    class Slow:
        id = "slow"
        label = "Лежачий хост"

        def search(self, q: str, *, limit: int = 30) -> list[Any]:
            time.sleep(3)
            return []

    class Fast:
        id = "fast"
        label = "Швидке"

        def search(self, q: str, *, limit: int = 30) -> list[Any]:
            return ["знахідка"]

    monkeypatch.setattr(B, "SEARCH_DEADLINE_S", 0.3)
    t0 = time.monotonic()
    out = B._ask_sources([Slow(), Fast()], "q", 5)
    assert time.monotonic() - t0 < 2.5
    assert out[1] == (["знахідка"], None)
    got = out[0]
    assert got is not None and isinstance(got[1], SourceError)
    assert "не відповіло" in str(got[1])
