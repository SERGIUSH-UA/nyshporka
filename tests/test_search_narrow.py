"""🔎 Рік і архів поруч із `--case` (ідея №8 порталу).

🔴 Головне, що тут стережеться: справа без року в описі ЛИШАЄТЬСЯ в пошуку.
Невідомий рік — не доказ іншого вікна, і фільтр, що її викидав, мовчки ховав би
справи, яких просто не описали.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.search import narrow as NR

LIB = {
    "DAHMO/315/1/1": {"year_from": 1795, "year_to": 1800},
    "DAHMO/315/1/2": {"year_from": 1860, "year_to": 1870},
    "DAHMO/315/1/3": {},                                   # рік не описано
    "DAHMO/315/1/4": {"year_from": 1858},                  # лише одна межа
    "CDIAK/224/1/5": {"year_from": 1830, "year_to": 1840},
}


# ── розбір ───────────────────────────────────────────────────────────────────

def test_years_parse_point_window_and_refuse_garbage() -> None:
    assert NR.parse_years("") is None
    assert NR.parse_years("1858") == (1858, 1858)
    assert NR.parse_years("1795..1858") == (1795, 1858)
    assert NR.parse_years(" 1795 – 1858 ") == (1795, 1858)
    with pytest.raises(ValueError, match="перевернуте"):
        NR.parse_years("1858..1795")
    with pytest.raises(ValueError, match="1795..1858"):
        NR.parse_years("XIX ст.")


def test_archive_label_and_code_are_one_archive() -> None:
    assert NR.parse_archive("ДАХмО") == NR.parse_archive("DAHMO") == \
        NR.parse_archive("dahmo") == "DAHMO"
    with pytest.raises(ValueError, match="не впізнано"):
        NR.parse_archive("Архів-якого-нема")


def test_no_filter_means_no_narrowing() -> None:
    assert NR.parse("", "") is None


# ── відбір справи ────────────────────────────────────────────────────────────

def test_year_window_keeps_overlap_and_unknown() -> None:
    nar = NR.Narrow(years=(1795, 1858))
    assert nar.keep_key("DAHMO/315/1/1", LIB) is True
    assert nar.keep_key("DAHMO/315/1/2", LIB) is False
    assert nar.keep_key("DAHMO/315/1/3", LIB) is None, "без року — лишається"
    assert nar.keep_key("DAHMO/315/1/4", LIB) is True, "одна межа — точка"
    assert nar.keep_key("", LIB) is None, "прогін без справи за роком — невідомо"


def test_archive_drops_other_archives_and_runs_without_case() -> None:
    nar = NR.Narrow(repo="DAHMO")
    assert nar.keep_key("DAHMO/315/1/2", LIB) is True
    assert nar.keep_key("CDIAK/224/1/5", LIB) is False
    assert nar.keep_key("", LIB) is False


def _rows(*keys: str) -> list[dict[str, Any]]:
    return [{"name": f"run-{i}", "case_canon": k} for i, k in enumerate(keys)]


@pytest.fixture
def lib(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store as S

    monkeypatch.setattr(NR, "_library", lambda: LIB)
    monkeypatch.setattr(S, "_bound_of_listing", lambda: {})


def test_apply_turns_the_scope_into_cases_with_a_denominator(lib: None) -> None:
    sc = {"rows": _rows(*LIB, ""), "kind": "all", "key": "", "shifra": ""}
    got = NR.apply(sc, NR.Narrow(years=(1795, 1858), repo="DAHMO", archive_asked="ДАХмО"))
    assert got["kind"] == "cases"
    assert got["keys"] == ["DAHMO/315/1/1", "DAHMO/315/1/3", "DAHMO/315/1/4"]
    st = got["narrow"]
    assert st["cases_listed"] == 5 and st["cases_kept"] == 3
    assert st["year_unknown"] == 1 and st["year_unknown_cases"] == ["DAHMO/315/1/3"]
    assert st["no_case_skipped"] == 1
    codes = [c for c, _ in NR.notes(st)]
    assert codes == ["narrowed", "year_unknown", "no_case_skipped"]


def test_year_alone_keeps_runs_without_case(lib: None) -> None:
    sc = {"rows": _rows("DAHMO/315/1/2", ""), "kind": "all", "key": "", "shifra": ""}
    got = NR.apply(sc, NR.Narrow(years=(1795, 1858)))
    assert [r["name"] for r in got["rows"]] == ["run-1"]
    assert got["narrow"]["no_case_kept"] == 1


def test_empty_selection_refuses_with_the_denominator(lib: None) -> None:
    sc = {"rows": _rows("DAHMO/315/1/1", "DAHMO/315/1/2"), "kind": "all",
          "key": "", "shifra": ""}
    with pytest.raises(ValueError, match="справ 2, з них в архіві ЦДІАК — 0"):
        NR.apply(sc, NR.Narrow(repo="CDIAK", archive_asked="ЦДІАК"))


# ── text.find: відбір іде справами, як серія ─────────────────────────────────

def test_find_searches_only_the_selected_cases(lib: None,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import textops as T

    asked_scope: list[Any] = []
    asked: list[str] = []

    def scope(s: Any) -> dict[str, Any]:
        asked_scope.append(s)
        return {"rows": _rows(*LIB), "kind": "cases", "key": "", "shifra": "серія",
                "keys": sorted(LIB)}

    def one(q: str, k: str, **_: Any) -> dict[str, Any]:
        asked.append(k)
        return {"case_key": k, "hits": [], "total": 0, "matches": {}, "anchor": {},
                "record": {}, "notebook": {},
                "ledger": {"channels": [], "runs": 1, "pages_scoped": 1,
                           "frames": 1, "decoded": 1}}

    monkeypatch.setattr(S, "runs_for_scope", scope)
    monkeypatch.setattr(T, "_find_one", one)
    got = T.find("Ковальський", "315-1", narrow=NR.Narrow(years=(1850, 1865)))
    assert asked_scope == ["315-1"], "фільтр — перетин із --case, а не заміна"
    assert sorted(asked) == ["DAHMO/315/1/2", "DAHMO/315/1/3", "DAHMO/315/1/4"]
    assert got["ledger"]["narrow"]["year_unknown"] == 1


# ── виписане й розібране: та сама множина справ ──────────────────────────────

RECORDS = [{"rtype": "birth", "date": "1858-03-14", "scans": ["0106.jpg"],
            "persons": [{"role": "father", "name": "Іоаннъ Ковальскій",
                         "surname": "Ковальскій"}]}]


@pytest.fixture
def space(tmp_path: Path) -> Path:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "data" / "raw" / "dahmo_315" / "spr-8433"
    d.mkdir(parents=True)
    (d / "0106.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    return tmp_path


def _cli(*args: str, stdin: str | None = None) -> Any:
    from nyshporka.cli import app
    from nyshporka.pagestore import query

    query._CACHE.clear()
    return CliRunner().invoke(app, list(args), input=stdin)


def test_records_branch_honours_archive_and_keeps_undated_case(space: Path) -> None:
    r = _cli("records", "add", "DAHMO/315/8433", "--json",
             stdin=json.dumps(RECORDS, ensure_ascii=False))
    assert r.exit_code == 0, r.output

    def find(*extra: str) -> dict[str, Any]:
        res = _cli("search", "Ковальський", "--where", "records", "--json", *extra)
        got = json.loads(res.stdout)
        return got

    other = find("--archive", "ЦДІАК")
    assert other["data"]["hits"] == [] and other["data"]["coverage"]["cases"] == 0
    mine = find("--archive", "ДАХмО", "--year", "1700..1710")
    # Справа без року в описі: у вікно «не доведено поза», тож лишається.
    assert len(mine["data"]["hits"]) == 1, mine
    assert mine["data"]["coverage"]["narrow"]["year_unknown"] == 1
    assert any(w.get("code") == "year_unknown" for w in mine.get("warnings") or []), mine


def test_big_selection_is_one_pass_not_case_by_case(lib: None,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 4844 справи по одній — 45 хв. Понад `SERIES_MAX` — один прохід, і журнал
    каже, що канали в межах справи не ганялись."""
    from nyshporka import htr_store as S
    from nyshporka.search import textops as T

    calls: list[dict[str, Any]] = []

    def one(q: str, k: str = "", **kw: Any) -> dict[str, Any]:
        calls.append({"scope": k, **kw})
        return {"case_key": "", "hits": [], "total": 0, "matches": {}, "anchor": {},
                "record": {}, "notebook": {},
                "ledger": {"channels": [], "runs": 3, "pages_scoped": 3,
                           "frames": None, "decoded": None}}

    monkeypatch.setattr(S, "runs_for_scope",
                        lambda s: {"rows": _rows(*LIB), "kind": "all", "key": "",
                                   "shifra": ""})
    monkeypatch.setattr(T, "_find_one", one)
    monkeypatch.setattr(NR, "SERIES_MAX", 2)
    got = T.find("Ковальський", "", narrow=NR.Narrow(repo="DAHMO"))
    assert len(calls) == 1 and calls[0]["narrow"] == NR.Narrow(repo="DAHMO")
    st = got["ledger"]["narrow"]
    assert st["one_pass"] is True and st["cases_kept"] == 4
    assert "narrow_one_pass" in [c for c, _ in NR.notes(st)]
