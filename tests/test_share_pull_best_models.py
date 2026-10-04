"""Пакет із Супряги: найновіші бойові моделі, без них — попередні.

Та сама справа буває в пулі кількома пакетами. Доти серія брала найсвіжіший
за датою, а одна справа взагалі не приймалась («збігів 2»): прочитання
Писарем v17, викладене пізніше, витісняло прочитання v19.
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka.share import catalog as C


def _row(shifra: str, url: str, models: str) -> C.Row:
    repo, rest = shifra.split()
    fond, opys, spr = rest.split("-")
    return C.Row(shifra=shifra, repo=repo, fond=fond, opys=opys, spr=spr,
                 url=url, sha256=url, pages="10", years="1900", models=models)


NEW = "pysar_cyr_v19.pt, diak_cyr_v6.safetensors"
OLD = "pysar_cyr_v17.pt, diak_cyr_v4.mlmodel"


def test_rang_za_pokolinniam_z_pakiv_vag() -> None:
    assert C.model_rank(_row("RGIA 1-1-1", "u", NEW)) == (2, 0)
    assert C.model_rank(_row("RGIA 1-1-1", "u", OLD)) == (0, 2)
    assert C.model_rank(_row("RGIA 1-1-1", "u", "pysar_cyr_v19.pt, diak_cyr_v4.mlmodel")) == (1, 1)
    # власна модель поза переліком паків не важить нічого
    assert C.model_rank(_row("RGIA 1-1-1", "u", "moia_model.pt")) == (0, 0)
    # шлях і регістр не заважають упізнати модель
    assert C.model_rank(_row("RGIA 1-1-1", "u", r"C:\m\PYSAR_CYR_V19.pt")) == (1, 0)


def test_najnovishi_boiovi_a_bez_nykh_poperedni() -> None:
    rows = [_row("RGIA 1-1-1", "old_fresh", OLD),        # свіжіший, але старі ваги
            _row("RGIA 1-1-1", "new", NEW),
            _row("RGIA 1-1-2", "junk", "moia_model.pt"),
            _row("RGIA 1-1-2", "prev", OLD),
            _row("RGIA 1-1-3", "a_fresh", NEW),           # рівні — лишається свіжіший
            _row("RGIA 1-1-3", "b_older", NEW)]
    assert sorted(r.url for r in C.best_per_case(rows)) == ["a_fresh", "new", "prev"]


@pytest.fixture
def pull(monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka import ops_share
    from nyshporka.share import accept as A

    taken: list[str] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        taken.append(url)
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    monkeypatch.setattr(A, "accept", accept)
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: None)
    monkeypatch.setattr(ops_share, "_after_import", lambda env, got: env)

    def run(rows: list[C.Row], **kw: Any) -> tuple[Any, list[str]]:
        monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                            (rows[offset:offset + limit], len(rows), 99))
        taken.clear()
        return ops_share.share_pull(ops_share.SharePullArgs(take=True, **kw)), taken

    return run


def test_odna_sprava_kilkoma_paketamy_bere_novishi_modeli(pull: Any) -> None:
    env, taken = pull([_row("RGIA 592-25-1", "old_fresh", OLD),
                       _row("RGIA 592-25-1", "new", NEW)], query="592-25-1")
    assert env.ok, env
    assert taken == ["new"]
    assert any("2 пакетами" in str(w) for w in env.warnings)


def test_rizni_spravy_lyshaiutsia_dvoznachnistiu(pull: Any) -> None:
    env, taken = pull([_row("RGIA 592-25-1", "a", NEW),
                       _row("RGIA 592-25-2", "b", NEW)], query="592-25")
    assert taken == []
    assert any("різних справ" in str(w) for w in env.warnings)


def test_seriia_bere_novishi_modeli_na_kozhnu_spravu(pull: Any) -> None:
    env, taken = pull([_row("RGIA 592-25-1", "old_fresh", OLD),
                       _row("RGIA 592-25-1", "new", NEW),
                       _row("RGIA 592-25-2", "only_old", OLD)],
                      repo="RGIA", fond="592")
    assert env.ok, env
    assert sorted(taken) == ["new", "only_old"]
