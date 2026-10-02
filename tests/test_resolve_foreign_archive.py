"""Резолвер не переносить справу в чужий архів за збігом номерів.

🔴 Запасний пошук за фондом і справою писали для ОДНОГО архіву під двома
кодами (ДАВО = ДАВіО). Без обмеження архівом він брав будь-який запис із тим
самим фондом і справою: у просторі користувача (звіт 29.09.2026) запис
`repo=DAVIO` із шифрою `DAHMO 315-1-8345` перетворював явне «ДАХмО 315-1-8345»
на `DAVIO/315/8345`. Далі пул питали під чужим ключем, і вже віддана справа
знову виглядала невіддана; облік писався б у файл чужого архіву.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

SUPERECHLYVYI = {"key": "DAVIO/315/8345", "repo": "DAVIO", "fond": "315", "opys": "1",
                 "spr": "8345", "shifra": "DAHMO 315-1-8345"}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override", W._override)   # повернути простір після тесту
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka.pagestore import store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "PAGES_ROOT", tmp_path / "data" / "pages")
    return S


@pytest.mark.parametrize("vvid", ["DAHMO/315/8345", "DAHMO 315-1-8345", "ДАХмО 315-1-8345"])
def test_yavnyi_arkhiv_ne_pidminiaietsia(store: Any, monkeypatch: Any, vvid: str) -> None:
    monkeypatch.setattr(store, "load_library", lambda: [SUPERECHLYVYI])
    ref = store.resolve_case(vvid)
    assert (ref.repo, ref.key) == ("DAHMO", "DAHMO/315/1/8345")


def test_synonim_toho_samoho_arkhivu_pratsiuie(store: Any, monkeypatch: Any) -> None:
    """Заради цього запасний пошук і існує: ДАВО = ДАВіО, нотатки не розщеплюються."""
    monkeypatch.setattr(store, "load_library", lambda: [
        {"key": "DAVO/100/5", "repo": "DAVO", "fond": "100", "opys": "1", "spr": "5",
         "shifra": "ДАВО 100-1-5"}])
    ref = store.resolve_case("DAVIO/100/5")
    assert ref.key == "DAVO/100/5"


def test_superechlyvyi_zapys_vydno(store: Any, monkeypatch: Any) -> None:
    """Запис, чий архів суперечить його ж шифрі, знаходиться — щоб його виправили."""
    zdorovyi = {"key": "DAHMO/315/159", "repo": "DAHMO", "fond": "315", "opys": "1",
                "spr": "159", "shifra": "ДАХмО 315-1-159"}
    bez_shyfry = {"key": "DAVIO/1/2", "repo": "DAVIO", "fond": "1", "spr": "2", "shifra": ""}
    got = store.library_conflicts([SUPERECHLYVYI, zdorovyi, bez_shyfry])
    assert [(c["key"], c["shifra_repo"]) for c in got] == [("DAVIO/315/8345", "DAHMO")]


def test_doktor_nazyvaie_superechlyvi_zapysy(store: Any, monkeypatch: Any) -> None:
    from nyshporka.setup import doctor

    monkeypatch.setattr(store, "load_library", lambda: [SUPERECHLYVYI])
    c = doctor._library()
    assert c.level == "warn"
    assert "DAVIO/315/8345" in c.detail and "DAHMO 315-1-8345" in c.detail
    assert "cases build" in c.fix

    monkeypatch.setattr(store, "load_library", lambda: [])
    assert doctor._library().level == "ok"
