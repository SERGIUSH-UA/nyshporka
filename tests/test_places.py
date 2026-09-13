"""🗺 Сучасні поселення з координатами: точка для села газетира.

Що тримається тестом:

1. **Зшивка картка → точка йде за назвою й ОБЛАСТЮ, район лише підказка.**
   Однойменних сіл по країні десятки; без області точка була б чужа частіше,
   ніж своя. А район у газетирі — до реформи 2020, тож шукається серед усіх
   адмінодиниць предмета, чинних і колишніх.
2. **Відстань перебиває воєводство у зшивці з церквами.** Село за 60+ км від
   церкви з тією ж назвою — інше село, і навпаки.
3. **Коло по газетиру знає свій знаменник**: село без точки в коло не входить,
   і про це сказано попередженням, а не мовчанням.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

Q: Any = None
S: Any = None

MODERN = [
    # qid, uk, ru, pl, aliases, kind, admin (усі P131, чинні й колишні), top, lat, lng
    ("Q4262721", "Липовеньке", "Липовенькое", "Lipoweńkie", "", "село",
     "Голованівський район | Голованівська селищна громада", "Кіровоградська область",
     48.2164, 30.5786),
    ("Q1", "Липівка", "Липовка", "", "", "село",
     "Макарівський район | Бучанський район", "Київська область", 50.40, 29.90),
    ("Q2", "Шумилів", "Шумилов", "Szumiłów", "Озірна", "село",
     "Бершадський район | Гайсинський район", "Вінницька область", 48.4801, 29.6805),
    ("Q3", "Маньківка", "Маньковка", "", "", "село",
     "Бершадський район | Гайсинський район", "Вінницька область", 48.47, 29.73),
    ("Q4", "Маньківка", "Маньковка", "", "", "смт",
     "Маньківський район | Уманський район", "Черкаська область", 48.96, 30.34),
    ("Q5", "Маньківка", "Маньковка", "", "", "село",
     "Гайсинський район", "Вінницька область", 48.90, 29.40),
    ("Q6", "Капітанівка", "Капитановка", "", "", "село",
     "Новомиргородський район | Новоукраїнський район", "Кіровоградська область",
     48.72, 31.86),
]

PLACES = [
    ("lypo_001.xml", "church", "православна церква", "Липовеньке, с.", "Липовенькое, с.",
     "Балтського пов. Подольської губ.", "Балтського пов. Подільської губ.",
     "Голованівського р-ну Кіровоградської обл.", "Успенська"),
    ("lypi_001.xml", "church", "православна церква", "Липівка, с.", "Липовка, с.",
     "Київського пов.", "Київського пов. Київської губ.",
     "Макарівського р-ну Київської обл.", "Покровська"),
    ("shum_001.xml", "church", "православна церква", "Шумилів, с.", "Шумилов, с.",
     "Ольгопольського пов. Подільської губ.", "Ольгопільського пов. Подільської губ.",
     "Бершадського р-ну Вінницької обл.", "Луківська"),
    # дві Маньківки однієї області — розводить лише старий район
    ("mank_001.xml", "church", "православна церква", "Маньківка, с.", "Маньковка, с.",
     "Гайсинського пов. Подільської губ.", "Гайсинського пов. Подільської губ.",
     "Бершадського р-ну Вінницької обл.", ""),
    ("mank_002.xml", "church", "православна церква", "Маньківка, с.", "Маньковка, с.",
     "Уманського пов. Київської губ.", "Уманського пов. Київської губ.",
     "Маньківського р-ну Черкаської обл.", ""),
    # без поля «нині» і з двома кандидатами — точки не буде
    ("mank_003.xml", "church", "православна церква", "Маньківка, с.", "Маньковка, с.",
     "", "", "", ""),
    # область названа, а села з такою назвою в ній немає — точки не буде
    ("kapi_001.xml", "church", "православна церква", "Капітанівка, с.", "Капитановка, с.",
     "", "Чигиринського пов. Київської губ.", "Кам'янського р-ну Черкаської обл.", ""),
]
CASES = [
    ("224", "1", "1", 1800, 1810, "метрична книга", "", "shum_001.xml"),
    ("224", "1", "2", 1800, 1810, "метрична книга", "", "mank_001.xml"),
    ("224", "1", "3", 1800, 1810, "метрична книга", "", "mank_001.xml"),
    ("224", "1", "4", 1800, 1810, "метрична книга", "", "lypo_001.xml"),
    ("224", "1", "5", 1800, 1810, "метрична книга", "", "lypi_001.xml"),
]


def _feature(ob_id: int, name: str, name_v: str, deanery: str, lat: float, lng: float
             ) -> dict[str, Any]:
    return {"attributes": {"ob_id": ob_id, "pl_name": name, "pl_name_v": name_v or None,
                           "pl_type": "wieś", "material": "dr", "patronage": "s",
                           "title": "OpNMP", "denom": "Kościół katolicki ob. greckiego",
                           "source": "Kołbuk 1998, s. 1.", "pal_name": "brac",
                           "deanery": deanery, "diocese": "Kijów-Wilno",
                           "type": "świątynia główna"},
            "geometry": {"x": lng, "y": lat}}


CHURCHES = {"unickie": [
    _feature(18162, "Lipoweńkie", "Lipówka", "Targowica", 48.2164, 30.5786),
    _feature(18533, "Szumiłów", "", "Berszada", 48.4801, 29.6805),
    _feature(18209, "Mańkówka", "Mańkówka, k. Olhopola", "Berszada", 48.47, 29.73),
]}


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
    src = tmp_path / "src"
    src.mkdir()
    dump = src / "places.json"
    dump.write_text(json.dumps([
        {"qid": q, "name_uk": uk, "name_ru": ru, "name_pl": pl, "name_en": "",
         "aliases": al, "kind": kind, "admin": adm, "top": top, "country": "UA",
         "lat": lat, "lng": lng}
        for q, uk, ru, pl, al, kind, adm, top, lat, lng in MODERN],
        ensure_ascii=False), encoding="utf-8")
    _B.build_places(dump, cat / "places-test-2026.09.sqlite",
                    pack_id="places-test-2026.09", taken="2026-09-13")
    p_tsv, c_tsv = src / "places.tsv", src / "cases.tsv"
    with p_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["card", "section", "institution", "village_uk", "village_ru",
                    "hist_place", "uezd_gub", "modern_place", "church",
                    "eparchy", "parishes", "note"])
        for r in PLACES:
            w.writerow([*r, "", "", ""])
    with c_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["fond", "opys", "spr", "year_from", "year_to", "doc_type",
                    "case_church", "card"])
        for r in CASES:
            w.writerow(list(r))
    _B.build_geog(p_tsv, c_tsv, cat / "geog-test-2026.08.sqlite",
                  pack_id="geog-test-2026.08", taken="2026-08-16")
    ch = src / "szady.json"
    ch.write_text(json.dumps(CHURCHES, ensure_ascii=False), encoding="utf-8")
    _B.build_churches(ch, cat / "churches-test-2026.09.sqlite",
                      pack_id="churches-test-2026.09", taken="2026-09-11")
    _S.invalidate()
    yield cat
    W.reset()
    _S.invalidate()


# ── зшивка картка → точка ────────────────────────────────────────────────────

def test_locate_needs_name_and_oblast_and_uses_old_raion_as_tiebreak(catalog):
    assert Q.locate("lypo_001.xml")["qid"] == "Q4262721"
    assert Q.locate("shum_001.xml")["qid"] == "Q2"
    # дві Маньківки Вінницької обл.: старий район (Бершадський, скасований)
    # лежить серед колишніх P131 і розводить їх
    loc = Q.locate("mank_001.xml")
    assert loc["qid"] == "Q3" and loc["how"] == "unique"
    assert Q.locate("mank_002.xml")["qid"] == "Q4"


def test_locate_refuses_when_oblast_has_no_such_village(catalog):
    """Капітанівка Чигиринського пов. (Черкаська обл.) ≠ Капітанівка
    Кіровоградської: назва та сама, область інша — точки немає, а не чужа."""
    assert Q.locate("kapi_001.xml") is None


def test_locate_without_modern_place_is_ambiguous_not_guessed(catalog):
    loc = Q.locate("mank_003.xml")
    assert loc is not None and loc["how"] == "ambiguous" and loc["lat"] is None
    assert len(loc["candidates"]) == 3


def test_place_card_carries_location_and_places_coverage(catalog):
    ans = Q.place_card("lypo_001.xml")
    card = ans.rows[0]
    assert card["location"]["qid"] == "Q4262721"
    assert {c.pack_id for c in ans.coverage} >= {"geog-test-2026.08", "places-test-2026.09"}


# ── відстань у зшивці з церквами ─────────────────────────────────────────────

def test_distance_beats_voivodeship_in_church_linking(catalog):
    """Lipoweńkie: Липовеньке за 0 км → near; Липівка Київської за 250 км →
    far і −10, хоч за назвою (варіант Lipówka) вона на 100."""
    links, _ = Q.link_churches_to_places(Q.church_card(18162).rows)
    by = {p["card"]: p for p in links[18162]}
    assert by["lypo_001.xml"]["region"] == "near" and by["lypo_001.xml"]["km"] < 1
    assert by["lypi_001.xml"]["region"] == "far" and by["lypi_001.xml"]["km"] > 100
    assert by["lypi_001.xml"]["score"] <= 90


def test_church_link_prefers_the_nearer_of_two_same_named_villages(catalog):
    """Mańkówka Бершадського деканату: Маньківка Бершадського р-ну (4 км) —
    попереду Маньківки Уманського пов. (60+ км), хоч оцінки за назвою рівні."""
    links, _ = Q.link_churches_to_places(Q.church_card(18209).rows)
    cards = [p["card"] for p in links[18209]]
    assert cards[0] == "mank_001.xml"
    assert {p["card"]: p["region"] for p in links[18209]}["mank_002.xml"] == "far"


# ── коло по газетиру ─────────────────────────────────────────────────────────

def test_places_near_returns_gazetteer_rows_with_cases(catalog):
    ans = Q.places_near(48.4801, 29.6805, km=10)
    assert [r["card"] for r in ans.rows] == ["shum_001.xml", "mank_001.xml"]
    assert ans.rows[1]["n_cases"] == 2 and 3 < ans.rows[1]["km"] < 6
    assert {c.domain for c in ans.coverage} == {"geog", "places"}
    # село без точки (mank_003) у коло не потрапляє ніколи
    assert "mank_003.xml" not in {r["card"] for r in Q.places_near(48.47, 29.73, km=500).rows}


def test_geog_near_op_resolves_center_by_name_card_and_point(catalog):
    from nyshporka import ops as O

    by_name = O.call("geog.near", {"at": "Шумилів", "km": 10})
    by_card = O.call("geog.near", {"at": "shum_001.xml", "km": 10})
    by_pt = O.call("geog.near", {"at": "48.4801,29.6805", "km": 10})
    for env in (by_name, by_card, by_pt):
        assert env.ok, env.error
        assert any(w.code == "geo_denominator" for w in env.warnings)
    # центр за карткою сам у коло не входить
    assert [r["card"] for r in by_card.data["places"]] == ["mank_001.xml"]
    assert [r["card"] for r in by_pt.data["places"]] == ["shum_001.xml", "mank_001.xml"]
    assert by_name.data["n_cases"] == 2


def test_geog_near_refuses_center_without_point(catalog):
    from nyshporka import ops as O

    env = O.call("geog.near", {"at": "kapi_001.xml"})
    assert not env.ok and "широта,довгота" in env.error


def test_without_places_pack_nothing_breaks(catalog):
    """Пака точок немає → картка без точки, зшивка з церквами за воєводством,
    коло по газетиру — відмова з підказкою, не порожній нуль."""
    from nyshporka import ops as O

    for p in S.installed("places"):
        p.path.unlink()
    S.invalidate()
    assert Q.place_card("lypo_001.xml").rows[0]["location"] is None
    links, _ = Q.link_churches_to_places(Q.church_card(18162).rows)
    assert all("km" not in p for p in links[18162])
    env = O.call("geog.near", {"at": "Шумилів"})
    assert not env.ok and "places" in env.error


def test_geog_near_stays_out_of_the_agent_budget_and_on_the_geog_screen():
    from nyshporka import ops as O
    from nyshporka.core import sections as S_

    assert "geog.near" not in {o.name for o in O.REGISTRY.for_agent()}
    assert S_.OP_SCREEN.get("geog.near") == "geog"
