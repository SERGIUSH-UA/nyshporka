"""Прив'язку, поставлену людиною (`cases.bind`), пошук бачить так само, як реєстр.

Після переїзду теки справи мета прогону несе мертвий `case_dir` і порожній
`case_key`. `cases.bind` пише рішення в `overrides.json`; реєстр його читав
(«нерозв'язаних 0»), а область пошуку будувалась лише з мети — і `search --case`
на тій самій справі казав «жодного прогону» (issue #20).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nyshporka.pagestore.store import CaseRef

KEY = "DAHMO/R-100/7"
RUNS = [
    # переїхала тека: ключа в меті немає, шлях мертвий
    {"name": "проба-фонд-Р", "case_key": "", "case_dir": "D:/gone/R-100-1-7",
     "pages_done": 12},
    # чужа справа, але мета помилково вказує на нашу теку
    {"name": "чужий", "case_key": "", "case_dir": "data/raw/dahmo_R-100/spr-7",
     "pages_done": 5},
    # ключ у меті правильний — працювало й доти
    {"name": "свій", "case_key": KEY, "case_dir": "", "pages_done": 3},
]


@pytest.fixture
def scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka import htr_store as S
    from nyshporka.cases import resolve as R
    from nyshporka.pagestore import store as PS

    monkeypatch.setattr(R, "OVERRIDES_PATH", tmp_path / "overrides.json")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in RUNS])
    monkeypatch.setattr(S, "find_runs_for_case", lambda p: [
        dict(r) for r in RUNS if r["case_dir"] == p])
    monkeypatch.setattr(PS, "resolve_case", lambda v: CaseRef(
        key=KEY, repo="DAHMO", fond="R-100", spr="7", opys="1",
        shifra="ДАХмО R-100-1-7", path="data/raw/dahmo_R-100/spr-7"))
    yield S, R
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()


def _names(sc: dict[str, Any]) -> set[str]:
    return {r["name"] for r in sc["rows"]}


def test_bound_run_is_in_the_case_scope(scope: Any) -> None:
    S, R = scope
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == {"свій"}
    R.bind_run("проба-фонд-Р", KEY, "теку перенесено")
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == {"свій", "проба-фонд-Р"}


def test_run_scope_reports_the_bound_key(scope: Any) -> None:
    S, R = scope
    R.bind_run("проба-фонд-Р", KEY, "теку перенесено")
    assert S.runs_for_scope("проба-фонд-Р")["key"] == KEY


def test_override_elsewhere_beats_meta_key(scope: Any) -> None:
    """Рішення людини сильніше за ключ мети — як у `resolve_run`."""
    S, R = scope
    R.bind_run("свій", "DAHMO/315/8433", "насправді інша книга")
    assert "свій" not in _names(S.runs_for_scope("ДАХмО R-100-1-7"))


def test_unbound_run_is_not_taken_by_case_dir(scope: Any, tmp_path: Path) -> None:
    """`key: null` — прогін свідомо нічий, хоч мета й вказує на теку справи."""
    S, R = scope
    (tmp_path / "overrides.json").write_text(
        '{"runs": {"свій": {"key": "DAHMO/315/8433"}, "чужий": {"key": null}}}',
        encoding="utf-8")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    # без збігу за ключем пошук іде в резерв за текою — і там «чужий» відсікається
    assert _names(S.runs_for_scope("ДАХмО R-100-1-7")) == set()


def test_shyfra_v_case_key_tezh_svoia(scope: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Старий прогін несе в `case_key` шифру, а не ключ — і лишається своїм.

    Інакше справа, прочитана повністю, для пошуку й пакувальника «без прогонів».
    """
    S, _ = scope
    S._canon_case_key.cache_clear()
    rows = [*RUNS, {"name": "старий", "case_key": "ДАХмО R-100-1-7",
                    "case_dir": "E:/elsewhere/spr-7", "pages_done": 26}]
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in rows])
    try:
        assert "старий" in _names(S.runs_for_scope("ДАХмО R-100-1-7"))
    finally:
        S._canon_case_key.cache_clear()
