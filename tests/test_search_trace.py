"""🧾 Слід свіпу: чим справу вже шукали — і чи не застарів той запис.

🔴 Головне твердження файлу — **запис прив'язаний до МОДЕЛІ**. «Обшукано»
протухає мовчки, коли бойова модель обганяє ту, якою шукали: замір приватного
конвеєра дає +8 аркушів роду на тому самому матеріалі від самої лише зміни
моделі. Запис без моделі підтверджував би роботу, якої вже немає.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def _note(key: str, q: str, models: list[str]) -> None:
    from nyshporka.search import trace as T

    T.note(key, q=q, thresh=80, hits=3, pages=100, models=models,
           channels=["surname"])


def test_a_sweep_leaves_a_trace(space) -> None:
    from nyshporka.search import trace as T

    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    got = T.of("DAHMO/315/8433")
    assert len(got) == 1
    assert got[0]["q"] == "Сікорський"


def test_the_same_query_by_the_same_models_updates_not_multiplies(space) -> None:
    from nyshporka.search import trace as T

    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    assert len(T.of("DAHMO/315/8433")) == 1


def test_a_record_by_another_model_is_flagged_stale(space) -> None:
    """🔴 Ось заради чого: старий нуль новим рушієм не підтверджується."""
    from nyshporka.search import trace as T

    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    stale = T.stale("DAHMO/315/8433", ["pysar", "diak"])
    assert [x["q"] for x in stale] == ["Сікорський"]
    assert T.stale("DAHMO/315/8433", ["pysar"]) == []


def test_different_queries_live_side_by_side(space) -> None:
    """Свіп прізвищем і свіп іменами відповідають на різні питання."""
    from nyshporka.search import trace as T

    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    _note("DAHMO/315/8433", "Ковальський", ["pysar"])
    assert {x["q"] for x in T.of("DAHMO/315/8433")} == {"Сікорський", "Ковальський"}


def test_a_case_without_a_key_writes_nothing(space) -> None:
    """Свіп по корпусу не належить жодній справі, тож і сліду не лишає."""
    from nyshporka.search import trace as T

    _note("", "Сікорський", ["pysar"])
    assert not T.path().exists()


def test_a_broken_log_does_not_kill_the_search(space) -> None:
    """Слід — зручність, а не умова роботи."""
    from nyshporka.search import trace as T

    T.path().parent.mkdir(parents=True, exist_ok=True)
    T.path().write_text("{зіпсовано", encoding="utf-8")
    assert T.of("DAHMO/315/8433") == []
    _note("DAHMO/315/8433", "Сікорський", ["pysar"])
    assert len(T.of("DAHMO/315/8433")) == 1
