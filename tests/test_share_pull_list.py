"""Список шифр із різних фондів — одним процесом (`share pull --z-fayla`).

Доти такий список брався циклом `share pull "<шифра>" --take`: кожна справа
платила новий процес ~11 с (імпорти, обхід прочитаного, запит до каталогу),
208 книг ≈ 40 хв лише накладних (замір 21.11.2026).
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka.share import catalog as C

NEW = "pysar_cyr_v31.pt, diak_cyr_v16.safetensors"


def _row(shifra: str, url: str, models: str = NEW, segment: str = "") -> C.Row:
    repo, rest = shifra.split()
    fond, opys, spr = rest.split("-")
    return C.Row(shifra=shifra, repo=repo, fond=fond, opys=opys, spr=spr,
                 url=url, sha256=url, pages="10", years="1900", models=models,
                 segment=segment)


#: Каталог: пошук повнотекстовий, тож «127-1012-8» зачіпає й 127-1012-80.
CATALOG = [
    _row("CDIAK 127-1012-8", "s8"),
    _row("CDIAK 127-1012-80", "s80"),
    _row("CDIAK 127-1012-81", "s81"),
    _row("CDIAK 127-1015-11", "own11"),
    _row("CDIAK 57-1-436", "s436"),
]


@pytest.fixture
def pull(monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka import htr_store as S
    from nyshporka import ops_share
    from nyshporka.share import accept as A

    taken: list[str] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        taken.append(url)
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    def search(q: str, base: str = "", *, limit: int = 50, offset: int = 0):
        tail = q.split()[-1]
        hits = [r for r in CATALOG if tail in f"{r.fond}-{r.opys}-{r.spr}"]
        return hits[offset:offset + limit], len(hits), len(CATALOG)

    monkeypatch.setattr(A, "accept", accept)
    monkeypatch.setattr(C, "search", search)
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: None)
    monkeypatch.setattr(ops_share, "_library_knows", lambda env, keys: None)
    # своє прочитання на цій машині: 127-1015-11
    monkeypatch.setattr(S, "local_reads",
                        lambda: {"CDIAK/127/1015/11": {"own": ["op1015-spr-11"], "taken": []}})

    def run(shyfry: list[str], take: bool = True) -> tuple[Any, list[str]]:
        taken.clear()
        env = ops_share.share_pull(ops_share.SharePullArgs(take=take, shyfry=shyfry))
        return env, list(taken)

    return run


def test_bere_tochnu_spravu_a_ne_povnotekstovyi_zbig(pull: Any) -> None:
    env, taken = pull(["ЦДІАК 127-1012-8"])
    assert env.ok, env
    assert taken == ["s8"]


def test_svoie_ne_beretsia_vidsutnie_poiasneno(pull: Any) -> None:
    env, taken = pull(["ЦДІАК 127-1015-11", "ЦДІАК 999-9-9", "ЦДІАК 57-1-436"])
    assert env.ok, env
    assert taken == ["s436"]
    d = env.data or {}
    assert d["list"] == 3 and d["found"] == 2
    assert [m["shifra"] for m in d["missing"]] == ["ЦДІАК 999-9-9"]
    assert [s["label"] for s in d["skipped_local"]] == ["ЦДІАК 127-1015-11"]


def test_dubli_v_spysku_zvodiatsia(pull: Any) -> None:
    env, taken = pull(["ЦДІАК 57-1-436", " ЦДІАК 57-1-436 ", ""])
    assert env.ok, env
    assert taken == ["s436"]
    assert (env.data or {})["list"] == 1


def test_bez_take_lyshe_poshuk(pull: Any) -> None:
    env, taken = pull(["ЦДІАК 127-1012-8", "ЦДІАК 57-1-436"], take=False)
    assert env.ok, env
    assert taken == []
    assert (env.data or {})["found"] == 2


def test_spysok_i_seriia_ne_razom() -> None:
    from nyshporka import ops_share

    env = ops_share.share_pull(ops_share.SharePullArgs(shyfry=["ЦДІАК 57-1-436"],
                                                       repo="CDIAK", fond="57"))
    assert not env.ok


def test_riadok_seriia_rozghortaietsia(pull: Any) -> None:
    """«ЦДІАК 127-1012» у списку — уся серія; справа, названа й окремо, — один раз."""
    env, taken = pull(["ЦДІАК 127-1012", "ЦДІАК 127-1012-8", "ЦДІАК 57-1-436"])
    assert env.ok, env
    assert sorted(taken) == ["s436", "s8", "s80", "s81"]
    assert (env.data or {})["series_cases"] == {"ЦДІАК 127-1012": 3}


def test_riadok_fond_bez_opysu(pull: Any) -> None:
    env, taken = pull(["ЦДІАК 57"])
    assert env.ok, env
    assert taken == ["s436"]


def test_kesh_local_reads_za_shtampom(monkeypatch: pytest.MonkeyPatch,
                                      tmp_path: Any) -> None:
    """Той самий штамп — мапа з диска без перебудови; новий штамп — перебудова."""
    from nyshporka import htr_store as S

    built: list[int] = []
    stamp = {"v": "a"}
    monkeypatch.setattr(S, "_local_reads_cache_path", lambda: tmp_path / "lr.json")
    monkeypatch.setattr(S, "_bound_runs", lambda: {})
    monkeypatch.setattr(S, "_local_reads_stamp", lambda bound: stamp["v"])

    def now(bound: Any) -> dict[str, Any]:
        built.append(1)
        return {"K/1/1/1": {"own": [f"run{len(built)}"], "taken": []}}

    monkeypatch.setattr(S, "_local_reads_now", now)
    first = S.local_reads()
    second = S.local_reads()
    assert len(built) == 1 and first == second
    stamp["v"] = "b"
    third = S.local_reads()
    assert len(built) == 2 and third["K/1/1/1"]["own"] == ["run2"]
