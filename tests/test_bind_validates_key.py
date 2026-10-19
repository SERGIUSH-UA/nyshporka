"""`cases bind` записує лише ключ справи, а побита прив'язка не перебиває мету.

12.10.2026 користувач прив'язав прогін командою `nysh cases bind <прогін>
"ДАХО 31-141-139"`. Рядок ліг у `overrides.json` як є; як рішення людини він
стояв першим у резолвері, перекрив правильний `case_key` з `_htr_meta.json`, і
після перебудови прочитана справа значилась непрочитаною — без жодного слова.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

KEY = "DAHO/31/141/139"
LIB = [{"key": KEY, "repo": "DAHO", "fond": "31", "opys": "141", "spr": "139",
        "path": "data/raw/daho_31/141-139"}]


@pytest.fixture
def R(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.cases import resolve as R

    real = R.LibraryIndex
    monkeypatch.setattr(R, "overrides_path", lambda: tmp_path / "overrides.json")
    # Бібліотека тесту — одна справа; резолвер і `bind_run` будують індекс самі.
    monkeypatch.setattr(R, "LibraryIndex",
                        lambda rows=None: real(LIB if rows is None else rows))
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    yield R
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()


def _stored(R: Any) -> dict[str, Any]:
    return json.loads(Path(R.overrides_path()).read_text(encoding="utf-8"))["runs"]


def _write(R: Any, runs: dict[str, Any]) -> None:
    Path(R.overrides_path()).write_text(json.dumps({"runs": runs}, ensure_ascii=False),
                                      encoding="utf-8")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()


# ── розбір ключа ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("asked, want", [
    ("ДАХО 31-141-139", KEY),
    ("DAHO/31/141/139", KEY),
    ("daho/31/141/139", KEY),
    ("ДАХмО ф.315 оп.1 спр.8433", "DAHMO/315/1/8433"),
    ("VYD/PEV/1880", "VYD/PEV/1880"),
])
def test_key_in_any_human_form_becomes_the_case_key(R: Any, asked: str, want: str) -> None:
    assert R.normalize_key(asked) == (want, "")


@pytest.mark.parametrize("asked, why", [
    ("31-141-139", "архів не названо"),
    ("ДАХО 31-141", "не є ключем справи"),
    ("Хлам", "не є ключем справи"),
    ("", "порожній"),
])
def test_what_is_not_a_case_key_is_refused_with_a_reason(R: Any, asked: str,
                                                          why: str) -> None:
    got, reason = R.normalize_key(asked)
    assert got is None and why in reason


# ── сама прив'язка ───────────────────────────────────────────────────────────
def test_bind_writes_the_canonical_key_and_says_so(R: Any) -> None:
    got = R.bind_run("daho-run", "ДАХО 31-141-139", "мета з боксу")

    assert _stored(R)["daho-run"]["key"] == KEY
    assert got["normalized"] and got["asked"] == "ДАХО 31-141-139"
    assert got["in_library"]


def test_bind_refuses_garbage_and_leaves_the_file_alone(R: Any) -> None:
    _write(R, {"старий": {"key": KEY}})

    with pytest.raises(ValueError, match="не є ключем справи"):
        R.bind_run("daho-run", "ДАХО 31-141", "описка")

    assert set(_stored(R)) == {"старий"}


def test_bind_refuses_a_case_missing_from_the_library(R: Any) -> None:
    with pytest.raises(ValueError, match="у бібліотеці немає"):
        R.bind_run("daho-run", "DAHO/31/141/140", "описка в номері")
    assert not Path(R.overrides_path()).exists()


def test_force_binds_a_case_not_yet_in_the_library(R: Any) -> None:
    got = R.bind_run("daho-run", "DAHO/31/141/140", "справу ще не заведено", force=True)

    assert _stored(R)["daho-run"]["key"] == "DAHO/31/141/140"
    assert got["in_library"] is False


# ── побита прив'язка, записана раніше ────────────────────────────────────────
def test_broken_bind_does_not_override_the_meta_key(R: Any) -> None:
    _write(R, {"daho-run": {"key": "ДАХО 31-141-139", "why": "ручна"}})

    link = R.resolve_run("daho-run", "", R.LibraryIndex(), meta_key=KEY)

    assert link.key == KEY and link.resolved_by == "meta_key"
    assert "негодяща" in link.note


def test_good_bind_still_beats_the_meta_key(R: Any) -> None:
    _write(R, {"daho-run": {"key": "DAHO/31/141/140", "why": "інша книга"}})

    link = R.resolve_run("daho-run", "", R.LibraryIndex(), meta_key=KEY)

    assert (link.key, link.resolved_by) == ("DAHO/31/141/140", "override")


def test_deliberately_unbound_run_stays_unbound(R: Any) -> None:
    _write(R, {"daho-run": {"key": None}})

    link = R.resolve_run("daho-run", "", R.LibraryIndex(), meta_key=KEY)

    assert link.key is None and link.resolved_by == "override"


def test_build_warns_about_a_broken_bind_with_the_fix(R: Any) -> None:
    _write(R, {"daho-run": {"key": "ДАХО 31-141-139"}, "ok-run": {"key": KEY}})

    lines = R.broken_binds_report()

    assert len(lines) == 1
    assert "daho-run" in lines[0] and f"nysh cases bind daho-run {KEY}" in lines[0]


def test_search_scope_skips_a_broken_bind(R: Any, tmp_path: Path) -> None:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    try:
        from nyshporka import htr_store as S

        _write(R, {"daho-run": {"key": "ДАХО 31-141-139"}, "ok-run": {"key": KEY},
                   "nobody": {"key": None}})
        assert S._bound_runs() == {"ok-run": KEY, "nobody": None}
    finally:
        W.reset()
