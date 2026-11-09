"""🗺 Газетири старих карт: пак, пошук за назвою карти й сучасною, коло, нуль.

Що тут тримається тестом:

1. **Кирилиця знаходить підпис карти.** Запит «Кам'яний Брід» знаходить
   «Kamienny brod» — через сучасну назву ототожненого поселення, з позначкою
   `via=modern`, тобто нижче за збіг з тим, що написав картограф.
2. **Однойменні підписи не зливаються.** На карті три Kamienny brod — пошук
   віддає три різні підписи з трьома точками.
3. **Нуль зі знаменником.** Порожня відповідь несе покриття (які карти є), а
   відсутній пак — відмову, не порожній список.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

Q: Any = None
S: Any = None

ROWS = [
    # key, name, kind, x, y, lat, lng, reading, readings, qid, modern, admin, km, score, ident, ob, church
    ("0001", "Kamienny brod", "village", 5740, 2485, 49.2958, 30.784, "agree", "",
     "Q1", "Кам'яний Брід", "Звенигородський район", 1.2, 0.93, "confirmed", 18001,
     "Kamienny Bród"),
    ("0002", "Kamiennybrod", "village", 4158, 5056, 48.2164, 30.0947, "dict", "",
     "Q2", "Кам'яний Брід", "Голованівський район", 2.0, 0.93, "confirmed", "", ""),
    ("0003", "Kamienny brod", "village", 1896, 4487, 48.3408, 28.7199, "agree", "",
     "", "", "", "", "", "none", "", ""),
    ("0004", "Winnica", "town", 2160, 1050, 49.2331, 28.4682, "dict", "",
     "Q3", "Вінниця", "Вінницький район", 3.0, 1.0, "confirmed", "", ""),
    ("0005", "Rakówka", "village", 3000, 3000, 48.44, 29.72, "arbiters",
     "Rakowka | Rabówka", "Q4", "Раківка", "Гайсинський район", 1.0, 0.9,
     "confirmed", "", ""),
    ("0006", "Satowijowka", "village", 2200, 1400, 49.15, 28.50, "disputed",
     "Sołowijowka", "", "", "", "", "", "none", "", ""),
]


def _write_map(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / "map.json").write_text(json.dumps({
        "map_id": "braclaw1790", "title": "Mappa geograficzna województwa bracławskiego",
        "year": 1790, "region": "Брацлавське воєводство", "holder": "BN, ZZK 2 014",
        "width": 10000, "height": 6990,
        "georef": {"anchors": 33, "median_km": 3.9, "p90_km": 7.4}}, ensure_ascii=False),
        encoding="utf-8")
    from nyshporka.catalog.build import MAP_COLS

    with (d / "gazetteer.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(MAP_COLS)
        for r in ROWS:
            w.writerow(r)
    return d


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch):
    global Q, S
    from nyshporka.core import workspace as W

    ws = tmp_path / "ws"
    (ws / "data" / "derived").mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))

    from nyshporka.catalog import build as _B
    from nyshporka.catalog import query as _Q
    from nyshporka.catalog import store as _S

    Q, S = _Q, _S
    d = _write_map(tmp_path / "src" / "braclaw1790")
    _B.build_maps([d], cat / "maps-test-2026.11.sqlite",
                  pack_id="maps-test-2026.11", taken="2026-11-09")
    _S.invalidate()
    yield cat
    W.reset()
    _S.invalidate()


def test_pack_scope_by_map_and_ident(catalog):
    import sqlite3

    p = S.installed("maps")[0]
    assert p.rows == len(ROWS) and p.taken == "2026-11-09"
    con = sqlite3.connect(f"file:{p.path}?mode=ro", uri=True)
    scope = con.execute("SELECT dim, value, n FROM coverage_scope").fetchall()
    con.close()
    assert ("map", "braclaw1790", 6) in scope
    assert ("ident", "confirmed", 4) in scope and ("ident", "none", 2) in scope


def test_map_spelling_finds_all_homonyms(catalog):
    rows = Q.find_map_places("Kamienny brod").rows
    keys = sorted(r["key"] for r in rows if r["score"] >= 84)
    assert keys == ["0001", "0002", "0003"]   # три підписи — не злиті
    assert {r["via"] for r in rows if r["key"] in ("0001", "0003")} == {"name"}


def test_cyrillic_query_hits_through_modern_name(catalog):
    rows = Q.find_map_places("Кам'яний Брід").rows
    top = [r for r in rows if r["via"] == "modern"]
    assert {r["key"] for r in top} >= {"0001", "0002"}
    # без ототожнення (0003) сучасною назвою не знаходиться — і не вдає
    assert all(r["key"] != "0003" or r["via"] == "name" for r in rows)


def test_joined_cyrillic_form_finds_map_spelling(catalog):
    """Живий запит 09.11.2026: «Кам'янобрід» давав нуль — звичайна нормалізація
    не зводить brod/брід і Kamienny/Кам'яний (70–82 при порозі 84)."""
    rows = Q.find_map_places("Кам'янобрід").rows
    assert {"0001", "0002", "0003"} <= {r["key"] for r in rows}


def test_unrelated_name_stays_zero(catalog):
    assert Q.find_map_places("Тульчин").rows == []


def test_ow_alternation(catalog):
    rows = Q.find_map_places("Rakiwka").rows
    assert rows and rows[0]["key"] == "0005" and rows[0]["score"] == 100


def test_near_orders_by_distance_and_keeps_reading_flags(catalog):
    rows = Q.map_places_near(49.2331, 28.4682, km=15).rows
    assert [r["key"] for r in rows][:2] == ["0004", "0006"]
    assert rows[1]["reading"] == "disputed" and "Sołowijowka" in rows[1]["readings"]


def test_ops_zero_carries_coverage_and_note(catalog):
    from nyshporka import ops as O

    env = O.call("map.find", {"q": "Zzzyx"})
    assert env.ok and env.data["places"] == []
    codes = {w.code for w in env.warnings}
    assert "nothing_found" in codes and "map_note" in codes
    assert env.coverage


def test_ops_near_by_name_and_list(catalog):
    from nyshporka import ops as O

    env = O.call("map.near", {"at": "Winnica", "km": 15})
    assert env.ok and env.data["places"][0]["key"] == "0004"
    lst = O.call("map.list", {})
    m = lst.data["maps"][0]
    assert m["map_id"] == "braclaw1790" and m["n"] == 6 and m["georef"]["anchors"] == 33


def test_missing_pack_is_refusal_not_zero(tmp_path, monkeypatch):
    from nyshporka import ops as O
    from nyshporka.catalog import store as _S

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    _S.invalidate()
    env = O.call("map.find", {"q": "Winnica"})
    _S.invalidate()
    assert not env.ok
