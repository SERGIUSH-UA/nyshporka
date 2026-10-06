"""Серія справ від пулу до пошуку: дешевий резолвер, серія, перелік, прийом.

Приймач — заміри 30.09.2026 на просторі з 3302 прогонами: будь-яка команда з
`--case` коштувала 45 с, бо резолвер справи читав бібліотеку на кожен прогін;
серія «RGIA 592-25» не бачила прийнятих із пулу прогонів (шифра в них лише в
паспорті пакета); прийом фонду з 84 справ потребував 84 викликів.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    from nyshporka import htr_store as S
    from nyshporka.cases import resolve as R

    monkeypatch.setattr(R, "OVERRIDES_PATH", tmp_path / "overrides.json")
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    S._canon_case_key.cache_clear()
    yield S
    S._canon_case_key.cache_clear()
    R.load_overrides.cache_clear()
    R._run_overrides.cache_clear()
    W.reset()


def _write_library(entries: list[dict[str, Any]]) -> None:
    from nyshporka import library as L

    L.LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    L.LIBRARY_PATH.write_text(json.dumps({"cases": entries}, ensure_ascii=False),
                              encoding="utf-8")


def _entry(spr: int) -> dict[str, Any]:
    return {"key": f"DAHMO/315/{spr}", "repo": "DAHMO", "fond": "315", "opys": "1",
            "spr": str(spr), "shifra": f"ДАХмО 315-1-{spr}"}


def test_rezolver_chytaie_biblioteku_raz_i_bachyt_perebudovu(
        space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Один розбір бібліотеки на всі виклики, доки файл той самий; новий
    файл видно одразу — і в довгоживучому процесі теж."""
    from nyshporka import library as L
    from nyshporka.pagestore import store as PS

    entries = [_entry(i) for i in range(1, 60)]
    _write_library(entries)
    real = L.read_json
    reads: list[Any] = []

    def counting(path: Any, default: Any = None) -> Any:
        reads.append(path)
        return real(path, default)

    monkeypatch.setattr(L, "read_json", counting)
    for i in range(1, 60):
        assert PS.resolve_case(f"DAHMO/315/{i}").shifra == f"ДАХмО 315-1-{i}"
    assert len(reads) == 1
    _write_library([*entries, {**_entry(60), "shifra": "ДАХмО 315-1-60 (нова)"}])
    assert PS.resolve_case("DAHMO/315/60").shifra == "ДАХмО 315-1-60 (нова)"
    assert len(reads) == 2


def test_oblast_spravy_ne_rezolvyt_kozhen_progin(
        space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Рядок переліку несе канонічний ключ — його й звіряти, а не рахувати
    ключ вдруге на кожен із тисяч прогонів."""
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.store import CaseRef

    S = space
    rows = [{"name": f"r{i}", "case_key": f"ДАХмО 315-1-{i}",
             "case_canon": f"DAHMO/315/{i}", "case_dir": ""} for i in range(500)]
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in rows])
    calls: list[str] = []

    def resolve(v: str) -> CaseRef:
        calls.append(v)
        return CaseRef(key="DAHMO/315/7", repo="DAHMO", fond="315", spr="7")

    monkeypatch.setattr(PS, "resolve_case", resolve)
    got = S.runs_for_scope("DAHMO/315/7")
    assert [r["name"] for r in got["rows"]] == ["r7"]
    assert calls == ["DAHMO/315/7"]


def _pool_rows() -> list[dict[str, Any]]:
    return [
        # прийнятий із пулу: справи в бібліотеці нема, шифра — з паспорта пакета
        {"name": "RGIA_592_25_1562", "case_key": "RGIA/592/1562",
         "case_canon": "RGIA/592/1562", "shifra": "RGIA 592-25-1562", "case_dir": ""},
        {"name": "RGIA_592_39_532", "case_key": "RGIA/592/532",
         "case_canon": "RGIA/592/532", "shifra": "RGIA 592-39-532", "case_dir": ""},
        # свій, без шифри взагалі: серія — лише за ключем
        {"name": "dahmo_230_1_130", "case_key": "DAHMO/230-1/130",
         "case_canon": "DAHMO/230-1/130", "shifra": "", "case_dir": ""},
    ]


def _names(sc: dict[str, Any]) -> set[str]:
    return {r["name"] for r in sc["rows"]}


def test_seriia_bachyt_pryiniati_z_pulu(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    S = space
    monkeypatch.setattr(S, "list_cases", _pool_rows)
    got = S.runs_for_scope("RGIA 592-25")
    assert _names(got) == {"RGIA_592_25_1562"}
    assert got["kind"] == "cases" and got["keys"] == ["RGIA/592/1562"]
    assert _names(S.runs_for_scope("RGIA 592")) == {"RGIA_592_25_1562", "RGIA_592_39_532"}
    assert _names(S.runs_for_scope("ДАХмО 230-1")) == {"dahmo_230_1_130"}


def test_perelik_sprav_obiednuietsia_i_nazyvaie_nevpiznanu(
        space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    S = space
    monkeypatch.setattr(S, "list_cases", _pool_rows)
    got = S.runs_for_scope(["RGIA 592-25", "ДАХмО 230-1", "RGIA 592-25"])
    assert _names(got) == {"RGIA_592_25_1562", "dahmo_230_1_130"}
    assert got["kind"] == "cases" and len(got["parts"]) == 2
    assert S.runs_for_scope(["RGIA 592-25"])["kind"] == "cases"
    with pytest.raises(ValueError, match="нісенітниця"):
        S.runs_for_scope(["RGIA 592-25", "нісенітниця"])


def _one(key: str, total: int, anchor: int = 0) -> dict[str, Any]:
    return {"q": "q", "case_key": key, "shifra": "",
            "hits": [{"name": key, "page": "p", "line_no": 1, "score": 80 + total}],
            "total": total, "anchor": {"total": anchor, "hits": []},
            "ledger": {"frames": None, "decoded": None, "runs": 1, "in_store": 1,
                       "pages_scoped": 10, "channels": [
                           {"id": "surname", "ran": True, "hits": total},
                           {"id": "anchor", "ran": True, "hits": anchor}]}}


def test_find_po_serii_shukaie_kozhnu_spravu(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Серія розкладається на справи: якорі й самоперевірка є лише в
    пошуку однієї справи, а знаменник називається по кожній."""
    from nyshporka.search import textops as T

    S = space
    monkeypatch.setattr(S, "list_cases", _pool_rows)
    asked: list[str] = []

    def one(q: str, scope: str = "", **kw: Any) -> dict[str, Any]:
        asked.append(scope)
        return _one(scope, total=2 if scope.endswith("1562") else 0, anchor=1)

    monkeypatch.setattr(T, "_find_one", one)
    got = T.find("Коваленко", "RGIA 592")
    assert sorted(asked) == ["RGIA/592/1562", "RGIA/592/532"]
    assert got["scope"] == "cases" and got["total"] == 2
    assert got["anchor"]["total"] == 2
    cases = {c["key"]: c for c in got["ledger"]["cases"]}
    assert cases["RGIA/592/1562"]["shifra"] == "RGIA 592-25-1562"
    assert got["hits"][0]["shifra"] == "RGIA 592-25-1562"
    assert got["ledger"]["pages_scoped"] == 20


def test_pull_serii_bere_kozhnu_spravu_raz(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_share
    from nyshporka.share import accept as A
    from nyshporka.share import catalog as C

    def row(shifra: str, url: str) -> C.Row:
        repo, rest = shifra.split()
        fond, opys, spr = rest.split("-")
        return C.Row(shifra=shifra, repo=repo, fond=fond, opys=opys, spr=spr,
                     url=url, sha256=url, pages="10", years="1900")

    rows = [row("RGIA 592-25-1", "u1new"), row("RGIA 592-25-1", "u1old"),
            row("RGIA 592-25-2", "u2bad"), row("RGIA 592-39-5", "u5"),
            row("DAHMO 592-1-9", "other_repo"), row("RGIA 5920-25-1", "other_fond")]
    monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                        (rows[offset:offset + limit], len(rows), 99))
    taken: list[str] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        if url == "u2bad":
            raise A.GatesRefused("ворота", detail="нема моделі")
        taken.append(url)
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    monkeypatch.setattr(A, "accept", accept)
    indexed: list[list[str]] = []
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: indexed.append(runs))

    env = ops_share.share_pull(ops_share.SharePullArgs(repo="РДІА", fond="592"))
    assert env.ok, env
    assert [(g["repo"], g["opys"], g["cases"]) for g in env.data["series"]] == [
        ("RGIA", "25", 2), ("RGIA", "39", 1)]
    assert taken == []

    env = ops_share.share_pull(ops_share.SharePullArgs(
        repo="RGIA", fond="592", opys="25", take=True))
    assert env.ok, env
    assert taken == ["u1new"]
    assert [t["label"] for t in env.data["imported"]] == ["RGIA 592-25-1"]
    assert any(w.code == "gate_refusal" for w in env.warnings)
    assert indexed == [["run_u1new"]]


def test_pull_bez_zapytu_ohliad_a_ne_pomylka(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_share
    from nyshporka.share import catalog as C

    rows = [C.Row(shifra="RGIA 592-25-1", repo="RGIA", fond="592", opys="25", spr="1")]
    monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                        (rows[offset:offset + limit], len(rows), 1))
    env = ops_share.share_pull(ops_share.SharePullArgs())
    assert env.ok and env.data["series"][0]["cases"] == 1
    assert not ops_share.share_pull(ops_share.SharePullArgs(take=True)).ok
    assert not ops_share.share_pull(ops_share.SharePullArgs(query="x", fond="592")).ok


def test_pull_serii_ne_bere_prochytane_tut(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Звірка за КЛЮЧЕМ справи до завантаження: своє прочитання під іншим
    іменем прогону не береться ніколи, навіть із --force; прийняте раніше —
    лише з --force; решта береться."""
    from nyshporka import htr_store as S
    from nyshporka import ops_share
    from nyshporka.share import accept as A
    from nyshporka.share import catalog as C

    def row(spr: str) -> C.Row:
        return C.Row(shifra=f"DAHMO 315-1-{spr}", repo="DAHMO", fond="315", opys="1",
                     spr=spr, url=f"u{spr}", sha256=f"u{spr}", pages="10", years="1900")

    rows = [row("1"), row("2"), row("3"), row("10")]
    monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                        (rows[offset:offset + limit], len(rows), 4))
    k1, k2 = ops_share._row_key(rows[0]), ops_share._row_key(rows[1])
    # прогін без ключа справи: шифра лише в імені теки — «можливо прочитано»;
    # «315-1-1» у ньому не має зачепити справу 1, а «315-1-10» — так
    monkeypatch.setattr(S, "local_reads", lambda: {
        k1: {"own": ["spr-1"], "taken": []}, k2: {"own": [], "taken": ["DAHMO_315-1-2"]},
        "": {"own": ["kostel-315-1-10-1847"], "taken": []}})
    taken: list[str] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        taken.append(url)
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    monkeypatch.setattr(A, "accept", accept)
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: None)

    env = ops_share.share_pull(ops_share.SharePullArgs(repo="DAHMO", fond="315"))
    assert env.data["local"] == {"have": 2, "maybe": 1, "missing": 1}
    assert taken == []

    env = ops_share.share_pull(ops_share.SharePullArgs(repo="DAHMO", fond="315", take=True))
    assert taken == ["u3"]
    assert {s["case_key"] for s in env.data["skipped_local"]} == {k1, k2}
    assert [m["runs"] for m in env.data["skipped_maybe"]] == [["kostel-315-1-10-1847"]]
    assert {w.code for w in env.warnings} >= {"skipped_local", "skipped_maybe"}

    taken.clear()
    ops_share.share_pull(ops_share.SharePullArgs(repo="DAHMO", fond="315", take=True,
                                                 force=True))
    assert sorted(taken) == ["u2", "u3"]


def test_pull_odniiei_spravy_zviriaie_z_prochytanym_tut(
        space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 `share pull "<шифра>" --take` звіряє з прочитаним так само, як серія,
    але відмовою з назвами прогонів: своє — ніколи, навіть із --force;
    прийняте раніше — лише з --force; безключовий прогін — «можливо прочитано»."""
    from nyshporka import htr_store as S
    from nyshporka import ops_share
    from nyshporka.share import accept as A
    from nyshporka.share import catalog as C

    def row(spr: str) -> C.Row:
        return C.Row(shifra=f"DAHMO 315-1-{spr}", repo="DAHMO", fond="315", opys="1",
                     spr=spr, url=f"u{spr}", sha256=f"u{spr}", pages="10", years="1900")

    k1, k2 = ops_share._row_key(row("1")), ops_share._row_key(row("2"))
    monkeypatch.setattr(S, "local_reads", lambda: {
        k1: {"own": ["spr-1"], "taken": []}, k2: {"own": [], "taken": ["DAHMO_315-1-2"]},
        "": {"own": ["kostel-315-1-10-1847"], "taken": []}})
    taken: list[tuple[str, bool]] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        taken.append((url, replace))
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    monkeypatch.setattr(A, "accept", accept)
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: None)

    def pull(spr: str, force: bool = False) -> Any:
        one = [row(spr)]
        monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                            (one, 1, 4))
        return ops_share.share_pull(ops_share.SharePullArgs(
            query=f"315-1-{spr}", take=True, force=force))

    for force in (False, True):
        env = pull("1", force=force)
        assert not env.ok and "spr-1" in str(env.error), env
    env = pull("2")
    assert not env.ok and "DAHMO_315-1-2" in str(env.error) and "--force" in str(env.error)
    env = pull("10")
    assert not env.ok and "kostel-315-1-10-1847" in str(env.error)
    assert "share import u10" in str(env.error)
    assert taken == []

    assert pull("2", force=True).ok
    assert pull("3").ok
    assert taken == [("u2", True), ("u3", False)]


def test_local_reads_bere_kliuch_pryiniatoho_z_shyfry(
        space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Прийняте старшою версією лежить без ключа в меті — справу впізнає шифра
    паспорта пакета, інакше серія з пулу брала б її вдруге."""
    S = space
    _write_library([_entry(7)])
    rows = [{"name": "op-7", "case_key": "", "case_canon": "", "shared": "Comme il faut",
             "shifra": "ДАХмО 315-1-7", "case_dir": ""},
            {"name": "own-8", "case_key": "", "case_canon": "", "shared": "",
             "shifra": "ДАХмО 315-1-8", "case_dir": ""}]
    monkeypatch.setattr(S, "list_cases", lambda: [dict(r) for r in rows])
    got = S.local_reads()
    key = S._canon_case_key("ДАХмО 315-1-7")
    assert key and got[key] == {"own": [], "taken": ["op-7"]}
    assert got[""] == {"own": ["own-8"], "taken": []}
