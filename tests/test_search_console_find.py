"""🔎 Консоль шукає тією самою командою, що й агент (`text.find`).

Дослідник 07.10.2026: «чому агенти шукають готовою уже командою, а консоль
чимось своїм?» Доти консольний «Пошук» ішов через `search.run`: той самий
двигун, але без каналів роду, без журналу знаменника, без самоперевірки й з
іншим порогом. І «з поправкою на людину»: межу пошуку підказує
`search.scopes` — лише з того, у чому є прочитане.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nyshporka.cases import db
from nyshporka.core.envelope import ALERT


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dbp = tmp_path / "reg.sqlite"
    con = sqlite3.connect(dbp)
    con.executescript(db._SCHEMA)
    rows = [
        ("DAVO/904/24/1", "ДАВіО", "904", "24", "ДАВіО 904-24-1", "Метрична книга", "pysar"),
        ("DAVO/904/24/2", "ДАВіО", "904", "24", "ДАВіО 904-24-2", "", "diak"),
        ("DAVO/1040/1/5", "ДАВіО", "1040", "1", "ДАВіО 1040-1-5", "", "pysar"),
        ("DAVO/127/1/7", "ДАВіО", "127", "1", "ДАВіО 127-1-7",
         "ДАВіО ф.127 оп.1 спр.7: Сповідні відомості", "pysar"),
        # не прочитана — у підказки межі не йде: шукати в ній нема в чому
        ("DAVO/904/24/3", "ДАВіО", "904", "24", "ДАВіО 904-24-3", "", "none"),
        # фонд із літерою: розбір серії в пошуку його не бере
        ("DAVO/R-6129/24/1", "ДАВіО", "R-6129", "24", "ДАВіО R-6129-24-1", "", "pysar"),
    ]
    for key, lab, f, o, sh, title, stage in rows:
        con.execute("INSERT INTO cases (key, kind, repo_label, fond, opys, shifra, title,"
                    " htr_stage) VALUES (?, 'case', ?, ?, ?, ?, ?, ?)",
                    (key, lab, f, o, sh, title, stage))
    con.commit()
    con.close()
    monkeypatch.setattr(db, "DB_PATH", dbp)
    return dbp


def _scopes(q: str = "") -> dict[str, Any]:
    from nyshporka.ops_text import ScopesArgs, search_scopes

    return search_scopes(ScopesArgs(q=q)).data


def test_scopes_go_from_fond_to_case_and_only_read_ones(reg: Path) -> None:
    d = _scopes()
    kinds = [x["kind"] for x in d["items"]]
    assert kinds == sorted(kinds, key=["fond", "opys", "case"].index), "від ширшого до вужчого"
    vals = {x["value"]: x for x in d["items"]}
    assert vals["ДАВіО 904"]["cases"] == 2, "непрочитана справа порахована"
    assert vals["ДАВіО 904-24"]["label"] == "ДАВіО ф.904 оп.24"
    assert "DAVO/904/24/3" not in vals, "справа без прочитаного в підказках межі"
    assert all("head" not in x for x in d["items"])


def test_scopes_offer_only_what_the_search_accepts(reg: Path) -> None:
    """🔴 Обрана підказка давала «не розпізнав справу»: справа йшла шифрою, яку
    резолвер не розбирає, а фонд із літерою — серією, якої пошук не впізнає."""
    from nyshporka import htr_store as S

    vals = {x["value"]: x for x in _scopes()["items"]}
    assert vals["DAVO/R-6129/24/1"]["label"] == "ДАВіО R-6129-24-1", "справа — ключем"
    assert "ДАВіО R-6129" not in vals and "ДАВіО R-6129-24" not in vals
    for v, x in vals.items():
        if x["kind"] != "case":
            repo, parts = S._series_head(v)
            assert repo and "-".join(parts) in v, v


def test_fonds_sort_as_numbers(reg: Path) -> None:
    fonds = [x["value"] for x in _scopes()["items"] if x["kind"] == "fond"]
    assert fonds == ["ДАВіО 127", "ДАВіО 904", "ДАВіО 1040"]


def test_scopes_filter_and_drop_the_repeated_shifra_from_titles(reg: Path) -> None:
    d = _scopes("127-1")
    labels = [x["label"] for x in d["items"]]
    assert "ДАВіО 127-1-7 — Сповідні відомості" in labels


def test_without_registry_scopes_say_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "нема.sqlite")
    assert _scopes() == {"items": [], "registry": False}


def test_console_search_is_the_agent_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """`search.find` — це `text.find`, лише роботою в черзі."""
    import nyshporka.ops_text as OT
    from nyshporka.search import textops as T

    seen: list[tuple[str, Any]] = []

    def fake_find(q: str, scope: Any = "", **kw: Any) -> dict[str, Any]:
        seen.append((q, scope))
        return {"q": q, "hits": [], "total": 0, "stopped": True,
                "ledger": {"channels": [], "runs": 1}, "anchor": {}, "record": {}}

    monkeypatch.setattr(T, "find", fake_find)
    env = OT.search_find(OT.TextFindArgs(q="Липовеньке", case="ДАВіО 904"))
    assert seen == [("Липовеньке", "ДАВіО 904")]
    assert {w.code: w.level for w in env.warnings}.get("search_stopped") == ALERT


def test_search_lives_in_core_with_its_ops() -> None:
    """Пошук у кожному пресеті — і його операції теж, інакше вкладка без відповіді."""
    from nyshporka import ops as O
    from nyshporka.core import sections as S

    assert S.SCREENS["search"] == "core"
    for name in ("search.find", "search.scopes", "text.find", "search.run", "search.state"):
        assert O.get(name).section == "core", name
    from nyshporka.daemon.workers import STOPPABLE_OPS

    assert "search.find" in STOPPABLE_OPS


# ── «Зібрати індекс»: той індекс, яким пошук справді шукає ──────────────────

def test_state_reports_the_store_when_search_uses_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Екран писав «поза пошуком 4 745 із 4 832» за старим індексом, а пошук
    ішов через стор, де свіжі 4 830 (холодний прохід 07.10.2026)."""
    from nyshporka.ops_builtin import search_state
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "stats", lambda: {"runs": 10, "indexed": 9, "stale": 1, "bytes": 1})
    monkeypatch.setattr(D, "stats", lambda: {"runs": 10, "indexed": 0, "stale": 10, "bytes": 1})
    d = search_state(None).data  # type: ignore[arg-type]
    assert d["backend"] == "store" and d["stale"] == 1


def test_state_falls_back_to_the_old_index_without_a_store(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.ops_builtin import search_state
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "exists", lambda: False)
    monkeypatch.setattr(D, "stats", lambda: {"runs": 10, "indexed": 4, "stale": 6, "bytes": 1})
    d = search_state(None).data  # type: ignore[arg-type]
    assert d["backend"] == "decode" and d["stale"] == 6


def test_index_button_builds_only_the_missing_store_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Лише відсутні прогони — без перебудови правил усього корпусу (години)."""
    from nyshporka import htr_store as S
    from nyshporka.ops_builtin import IndexArgs, search_index
    from nyshporka.search import store as ST

    seen: dict[str, Any] = {}

    def fake_ensure(runs: list[str], **kw: Any) -> Any:
        seen.update(kw, runs=runs)
        return iter(["r2"])

    monkeypatch.setattr(S, "list_cases", lambda: [{"name": "r1"}, {"name": "r2"}])
    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "ensure_all", fake_ensure)
    monkeypatch.setattr(ST, "stats", lambda: {"runs": 2, "indexed": 2, "stale": 0, "bytes": 1})
    env = search_index(IndexArgs())
    assert env.ok and env.data["built"] == 1 and env.data["backend"] == "store"
    assert seen["runs"] == ["r1", "r2"] and not seen.get("force") and "reset_rules" not in seen


@pytest.mark.parametrize("where", ["pages", "records"])
def test_written_out_search_over_a_series_says_why_not(monkeypatch: pytest.MonkeyPatch,
                                                       where: str) -> None:
    """Межа «фонд/опис» із «виписаним» радила прив'язати прогін (`cases bind`) —
    дію, яка тут нічого не змінює."""
    from nyshporka import htr_store as S
    from nyshporka.ops_builtin import SearchArgs, search_run

    monkeypatch.setattr(S, "runs_for_scope", lambda _s: {
        "rows": [{"name": "r1"}], "kind": "cases", "key": "", "shifra": "ДАХмО 315-1",
        "keys": ["DAHMO/315/1/1"]})
    env = search_run(SearchArgs(q="Ярошинський", where=where, case="ДАХмО 315-1"))
    assert not env.ok
    assert "фонд чи опис" in str(env.error) and "bind" not in str(env.error)


def test_home_counts_the_index_the_search_uses(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Огляд» рахував старий погонний індекс (87 / 4860), а пошук і кнопка
    «Зібрати індекс» — текстовий стор (4844 / 4860)."""
    from nyshporka.ops_builtin import _pulse_search
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "stale_count", lambda runs, *_a: 1)
    monkeypatch.setattr(D, "stats", lambda *_a: {"runs": 3, "indexed": 0, "stale": 3})
    got = _pulse_search(["a", "b", "c"])
    assert (got["runs"], got["indexed"], got["stale"], got["backend"]) == (3, 2, 1, "store")
