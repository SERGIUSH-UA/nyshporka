"""⛪ Церкви ~1772 (база Шади) і гібрид із газетиром.

Три речі, які тут тримаються тестом, а не домовленістю:

1. **Кирилиця знаходить польський запис.** «Липовеньке» → Lipoweńkie через
   спільну ASCII-форму; без цього база корисна лише тим, хто знає польське
   написання, тобто нікому з тих, для кого пакет.
2. **Зшивка з газетиром не вигадує.** Однойменне село в іншому воєводстві
   позначається, а схоже лише віддалено — не зшивається взагалі. Хибна пара
   тут гірша за відсутню: вона читається як «книги села он там».
3. **Нуль зі знаменником.** Порожня відповідь несе покриття, а відсутній пак —
   відмову, не порожній список.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

Q: Any = None
S: Any = None


def _feature(ob_id: int, name: str, *, name_v: str = "", title: str = "OpNMP",
             deanery: str = "Targowica", pal: str = "brac", lat: float, lng: float,
             denom: str = "Kościół katolicki ob. greckiego",
             source: str = "Kołbuk 1998, s. 112.", kind: str = "świątynia główna",
             parish: str | None = None) -> dict[str, Any]:
    return {"attributes": {
        "ob_id": ob_id, "pl_name": name, "pl_name_v": name_v or None,
        "pl_type": "wieś", "material": "dr", "patronage": "s", "kind": None,
        "title": title, "denom": denom, "name": None, "source": source,
        "pal_name": pal, "deanery": deanery, "adeaconry": "Kijów",
        "diocese": "Kijów-Wilno", "metropoly": "Kijów-Wilno", "parish": parish,
        "type": kind, "pkt_id": None, "comments": None},
        "geometry": {"x": lng, "y": lat}}


#: Кущ Липовенького (Торговицький деканат) + однойменні пастки.
FEATURES = {
    "unickie": [
        _feature(18162, "Lipoweńkie", name_v="Lipówka", title="WnNMP",
                 lat=48.2164, lng=30.5786,
                 source="Kołbuk 1998, s. 119; Socjografia, s. 77."),
        _feature(18015, "Kapitanka", name_v="Kapitanówka", title="OpNMP",
                 lat=48.1840, lng=30.5793),
        _feature(18533, "Szumiłów", title="Łukasz Ew", deanery="Berszada",
                 lat=48.4801, lng=29.6805),
        _feature(18209, "Mańkówka", name_v="Mańkówka, k. Olhopola",
                 title="Św. Trójca", deanery="Berszada", lat=48.4700, lng=29.7300),
        # три однойменні в трьох воєводствах — розрізняти за деканатом
        _feature(4471, "Jezierna", title="Jerzy M", deanery="Zborów", pal="rus",
                 lat=49.69, lng=25.46),
        _feature(23019, "Jezierna", title=None, deanery="Bałta", pal="brac",
                 lat=47.95, lng=29.90, source="Socjografia, s. 50."),
        _feature(19157, "Ezierna", name_v="Jezierna, Jezierno, Jezierany",
                 title="NarNMP", deanery="Białacerkiew", pal="kij",
                 lat=49.80, lng=30.10),
        # допоміжна церква з експортним сміттям у присвяті
        _feature(9001, "Rakówka", title="Mikołaj Bp                        A",
                 deanery="Teplik", lat=48.44, lng=29.72,
                 kind="świątynia pomocnicza", parish="Szumiłów"),
    ],
    "prawoslawne": [
        _feature(10501, "Mohylów", title="Jerzy M", deanery=None, pal="pod",
                 lat=48.45, lng=27.79, denom="Kościół prawosławny"),
    ],
}

#: Газетир поруч: своє село, однойменне чуже, і схоже лише віддалено.
PLACES = [
    ("lypo_001.xml", "church", "православна церква", "Липовеньке, с.", "Липовенькое, с.",
     "Брацлавського воєв., з 1797 р. Балтського пов. Подільської губ.",
     "Балтського пов. Подільської губ.", "", "Успенська"),
    ("lypi_001.xml", "church", "православна церква", "Липівка, с.", "Липовка, с.",
     "Київського воєв., з 1797 р. Київського пов. Київської губ.",
     "Київського пов. Київської губ.", "", "Покровська"),
    ("kapi_001.xml", "church", "православна церква", "Капітанівка, с.", "Капитановка, с.",
     "Київського воєв., з 1797 р. Чигиринського пов. Київської губ.",
     "Чигиринського пов. Київської губ.", "", "Михайлівська"),
    ("shum_001.xml", "church", "православна церква", "Шумилів, с.", "Шумилов, с.",
     "Брацлавського воєв., з 1797 р. Ольгопільського пов. Подільської губ.",
     "Ольгопільського пов. Подільської губ.", "", "Луківська"),
    ("raki_001.xml", "church", "православна церква", "Раківка, с.", "Раковка, с.",
     "Брацлавського воєв.", "Гайсинського пов. Подільської губ.", "", ""),
    ("raku_001.xml", "church", "православна церква", "Ракулове, с.", "Ракулово, с.",
     "Брацлавського воєв.", "Ольгопільського пов. Подільської губ.", "", ""),
]
CASES = [
    ("224", "1", "1460", 1781, 1822, "метрична книга", "Луківська", "shum_001.xml"),
    ("224", "1", "1", 1800, 1810, "метрична книга", "", "kapi_001.xml"),
    ("224", "1", "2", 1800, 1810, "метрична книга", "", "kapi_001.xml"),
    ("224", "1", "3", 1800, 1810, "метрична книга", "", "lypo_001.xml"),
    ("224", "1", "4", 1800, 1810, "метрична книга", "", "lypi_001.xml"),
]


def _write_geog(d: Path) -> tuple[Path, Path]:
    p_tsv, c_tsv = d / "places.tsv", d / "cases.tsv"
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
    return p_tsv, c_tsv


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch):
    """Каталог із паком церков і паком газетира + простір."""
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
    dump = src / "szady.json"
    dump.write_text(json.dumps(FEATURES, ensure_ascii=False), encoding="utf-8")
    _B.build_churches(dump, cat / "churches-test-2026.09.sqlite",
                      pack_id="churches-test-2026.09", taken="2026-09-11")
    p_tsv, c_tsv = _write_geog(src)
    _B.build_geog(p_tsv, c_tsv, cat / "geog-test-2026.08.sqlite",
                  pack_id="geog-test-2026.08", taken="2026-08-16")
    _S.invalidate()
    yield cat
    W.reset()
    _S.invalidate()


# ── словники кодів ───────────────────────────────────────────────────────────

def test_title_codes_expand_and_unknown_stays_raw() -> None:
    """Відомий код → присвята; невідомий — як є, не найближчий схожий."""
    from nyshporka.geog.szady import clean_title, title_uk

    assert title_uk("OpNMP") == "Покрови Пресвятої Богородиці"
    assert title_uk("Łukasz Ew") == "Євангеліста Луки"
    assert title_uk("Pkrzyża Św.") == "Воздвиження Чесного Хреста"
    # експортне сміття в хвості (два+ пробіли й знак) знімається
    assert clean_title("Mikołaj Bp                        A") == "Mikołaj Bp"
    assert title_uk("Mikołaj Bp                        A") == "Святителя Миколая"
    # кілька присвят через кому
    assert title_uk("PKrzyża Św, ZaśnNMP") == (
        "Воздвиження Чесного Хреста · Успіння Пресвятої Богородиці")
    assert title_uk("Nieznany Kod XY") == "Nieznany Kod XY"
    assert title_uk(None) == ""


def test_confession_from_denom() -> None:
    from nyshporka.geog.szady import confession_of

    assert confession_of("Kościół katolicki ob. greckiego") == "uniate"
    assert confession_of("Kościół prawosławny") == "orthodox"
    assert confession_of("Kościół katolicki ob. łacińskiego") == "latin"
    assert confession_of(None) == ""


# ── пак ──────────────────────────────────────────────────────────────────────

def test_pack_carries_scope_by_confession_and_voivodeship(catalog):
    p = S.installed("churches")[0]
    assert p.taken == "2026-09-11" and p.rows == 9
    con = sqlite3.connect(f"file:{p.path}?mode=ro", uri=True)
    scope = con.execute("SELECT dim, value, n FROM coverage_scope").fetchall()
    con.close()
    assert ("confession", "uniate", 8) in scope
    assert ("confession", "orthodox", 1) in scope
    assert ("voivodeship", "brac", 6) in scope


def test_auxiliary_church_keeps_its_parish(catalog):
    row = Q.church_card(9001).rows[0]
    assert row["role"] == "auxiliary" and row["parish_of"] == "Szumiłów"
    assert row["title_uk"] == "Святителя Миколая"


# ── пошук: кирилиця знаходить польський запис ───────────────────────────────

def test_cyrillic_query_finds_polish_record(catalog):
    """«Липовеньке» → Lipoweńkie, «Шумилів» → Szumiłów, «Капітанка» → Kapitanka."""
    for q, ob_id in (("Липовеньке", 18162), ("Шумилів", 18533),
                     ("Капітанка", 18015), ("Lipoweńkie", 18162)):
        ids = [r["ob_id"] for r in Q.find_churches(q).rows]
        assert ids and ids[0] == ob_id, (q, ids)


def test_variant_name_is_searched_and_labelled(catalog):
    """Варіант за Socjografia — інша форма, і її видно як `via=variant`."""
    rows = Q.find_churches("Jezierany").rows
    assert [r["ob_id"] for r in rows] == [19157]
    assert rows[0]["via"] == "variant"
    # -ówka ↔ -івка: регулярне чергування, форма-здогад для пошуку
    rows = Q.find_churches("Раківка").rows
    assert rows and rows[0]["ob_id"] == 9001 and rows[0]["score"] >= 90


def test_homonyms_are_all_returned_and_distinguished_by_deanery(catalog):
    rows = Q.find_churches("Jezierna").rows
    top = [r for r in rows if r["score"] >= 92]
    assert {r["ob_id"] for r in top} >= {4471, 23019, 19157}
    assert {r["deanery"] for r in top} >= {"Zborów", "Bałta", "Białacerkiew"}
    only = Q.find_churches("Jezierna", voivodeship="brac").rows
    assert [r["ob_id"] for r in only if r["score"] >= 92] == [23019]


def test_far_fetched_name_is_an_honest_zero(catalog):
    ans = Q.find_churches("Такогоселанемає")
    assert ans.rows == [] and ans.coverage
    assert ans.coverage[0].taken == "2026-09-11"


def test_missing_pack_refuses_instead_of_zero(tmp_path, monkeypatch):
    from nyshporka.catalog import query as _Q
    from nyshporka.catalog import store as _S

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path / "порожньо"))
    _S.invalidate()
    with pytest.raises(_S.CatalogMissing) as exc:
        _Q.find_churches("Липовеньке")
    assert "churches" in str(exc.value)
    _S.invalidate()


# ── коло ─────────────────────────────────────────────────────────────────────

def test_ring_is_a_circle_sorted_by_distance(catalog):
    rows = Q.churches_near(48.2164, 30.5786, km=5).rows
    assert [r["ob_id"] for r in rows] == [18162, 18015]
    assert rows[0]["km"] == 0.0 and 3.0 < rows[1]["km"] < 4.5
    assert Q.churches_near(48.2164, 30.5786, km=5, exclude=18162).rows[0]["ob_id"] == 18015
    # за межею кола — нічого, і покриття є
    far = Q.churches_near(50.45, 30.52, km=5)
    assert far.rows == [] and far.coverage


# ── гібрид: зшивка з газетиром ───────────────────────────────────────────────

def test_link_finds_own_village_and_flags_other_voivodeship(catalog):
    """Lipoweńkie → Липовеньке (своє) першим; Липівка Київського — з позначкою.

    Варіант «Lipówka» справді дорівнює Липівці за назвою, тож ховати цю пару
    не можна — але вона мусить іти ПІСЛЯ свого села й нести `region=mismatch`:
    саме так людина бачить, що зшилось однойменне з іншого воєводства.

    🪤 Kapitanka Балтського деканату зшивається з Капітанівкою Чигиринського
    повіту (своєї Капітанки в газетирі немає) — пара лишається, бо назва
    справді та сама, але несе позначку іншого воєводства й оцінку нижче.
    """
    church = Q.church_card(18162).rows[0]
    got = {p["card"]: p for p in church["places"]}
    first = church["places"][0]
    assert first["card"] == "lypo_001.xml" and first["region"] == "same"
    if "lypi_001.xml" in got:
        assert got["lypi_001.xml"]["region"] == "mismatch"
        assert got["lypi_001.xml"]["score"] < first["score"]

    kap = Q.church_card(18015).rows[0]
    assert kap["places"] and kap["places"][0]["card"] == "kapi_001.xml"
    assert kap["places"][0]["region"] == "mismatch"
    assert kap["places"][0]["score"] <= 90


def test_link_prefers_regular_alternation_over_lookalike(catalog):
    """Rakówka → Раківка першою (через -ów-/-ів-), Ракулове — після неї."""
    links, partial = Q.link_churches_to_places(Q.church_card(9001).rows)
    assert not partial
    cards = [p["card"] for p in links[9001]]
    assert cards[0] == "raki_001.xml"


def test_link_without_gazetteer_explains_instead_of_failing(catalog):
    """Церква без книг — відповідь про церкву, не відмова."""
    for p in S.installed("geog"):
        p.path.unlink()
    S.invalidate()
    ans = Q.church_card(18533)
    assert ans.rows and ans.rows[0]["places"] == []
    assert ans.partial and "газетира немає" in ans.partial[0]


def test_every_row_carries_its_origin(catalog):
    for ans in (Q.find_churches("Липовеньке"), Q.church_card(18162),
                Q.churches_near(48.2164, 30.5786, km=5)):
        for row in ans.rows:
            assert row.get("origin") in {"catalog", "own"}, row
            assert row.get("pack_id"), row


# ── операції: три обличчя одного гібрида ─────────────────────────────────────

def test_church_find_op_joins_both_sides(catalog):
    from nyshporka import ops as O

    env = O.call("church.find", {"q": "Шумилів", "limit": 5})
    assert env.ok, env.error
    churches = env.data["churches"]
    assert churches[0]["ob_id"] == 18533
    assert churches[0]["places"][0]["card"] == "shum_001.xml"
    assert churches[0]["places"][0]["n_cases"] == 1
    # зворотний бік: поселення газетира за тим самим запитом
    assert [p["card"] for p in env.data["places"]] == ["shum_001.xml"]
    sources = {c.source for c in env.coverage}
    assert {"churches-test-2026.09", "geog-test-2026.08"} <= sources
    assert any(n.op == "church.near" for n in env.next)


def test_church_near_op_resolves_center_three_ways(catalog):
    from nyshporka import ops as O

    by_id = O.call("church.near", {"at": "18533", "km": 10})
    by_pt = O.call("church.near", {"at": "48.4801, 29.6805", "km": 10})
    by_name = O.call("church.near", {"at": "Шумилів", "km": 10})
    for env in (by_id, by_pt, by_name):
        assert env.ok, env.error
        assert [r["ob_id"] for r in env.data["churches"]] == [18533, 18209, 9001]
    assert by_name.data["center"]["ob_id"] == 18533
    assert any(w.code == "center" for w in by_name.warnings), (
        "центр узято за назвою — людина мусить бачити, яку церкву взято")
    assert any(w.code == "coords" for w in by_id.warnings)
    assert by_name.data["by_deanery"] == {"Berszada": 2, "Teplik": 1}


def test_church_near_op_refuses_unknown_center(catalog):
    from nyshporka import ops as O

    env = O.call("church.near", {"at": "Такогоселанемає"})
    assert not env.ok and "широта,довгота" in env.error


def test_church_ops_stay_out_of_the_agent_budget():
    """🔴 Довідники — у браузері й командному рядку, не в агентському переліку."""
    from nyshporka import ops as O
    from nyshporka.core import sections as S_

    agent = {o.name for o in O.REGISTRY.for_agent()}
    assert not ({"church.find", "church.card", "church.near"} & agent)
    gui = {o.name for o in O.for_sections(S_.preset_sections("researcher"))}
    assert {"church.find", "church.card", "church.near"} <= gui
    for name in ("church.find", "church.card", "church.near"):
        assert S_.OP_SCREEN.get(name) == "geog", name
