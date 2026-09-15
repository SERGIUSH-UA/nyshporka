"""🧭 Пак довідника каже, де його межі, — і нуль поза ними це називає.

Таблицю `coverage_scope` збирач писав від першої схеми, а не читав її ніхто.
Наслідок видно на запиті про донецьке село: пак церков ~1772 накриває
воєводства Речі Посполитої, газетир — фонди свого архіву, і обидва відповідали
звичайним `nothing_found`, який читається як «такого села немає».
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest


def _church(ob_id: int, name: str, pal: str, lat: float, lng: float) -> dict[str, Any]:
    return {"attributes": {
        "ob_id": ob_id, "pl_name": name, "pl_name_v": None, "pl_type": "wieś",
        "material": "dr", "patronage": "s", "kind": None, "title": "OpNMP",
        "denom": "Kościół katolicki ob. greckiego", "name": None,
        "source": "Kołbuk 1998, s. 112.", "pal_name": pal, "deanery": "Targowica",
        "adeaconry": "Kijów", "diocese": "Kijów-Wilno", "metropoly": "Kijów-Wilno",
        "parish": None, "type": "świątynia główna", "pkt_id": None, "comments": None},
        "geometry": {"x": lng, "y": lat}}


CHURCHES = {"unickie": [_church(18162, "Lipoweńkie", "brac", 48.2164, 30.5786),
                        _church(4471, "Jezierna", "rus", 49.69, 25.46)]}

PLACES = [
    ("c1", "church", "православна церква", "М'ястківка", "Мястковка",
     "Ольгопольський пов.", "Подільська губ.", "Городківка", "Благовіщенська"),
    ("c2", "rabbinate", "рабинат", "М'ястківка", "Мястковка",
     "Ольгопольський пов.", "Подільська губ.", "Городківка", ""),
]
CASES = [("224", "1", "864", 1752, 1777, "метрична книга", "Благовіщенська", "c1")]


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
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.catalog import build as B
    from nyshporka.catalog import store as S
    from nyshporka.core import workspace as W

    ws = tmp_path / "ws"
    (ws / "data" / "derived").mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    src = tmp_path / "src"
    src.mkdir()
    dump = src / "szady.json"
    dump.write_text(json.dumps(CHURCHES, ensure_ascii=False), encoding="utf-8")
    B.build_churches(dump, cat / "churches-test-2026.09.sqlite",
                     pack_id="churches-test-2026.09", taken="2026-09-11")
    p_tsv, c_tsv = _write_geog(src)
    B.build_geog(p_tsv, c_tsv, cat / "geog-test-2026.08.sqlite",
                 pack_id="geog-test-2026.08", taken="2026-08-16")
    S.invalidate()
    yield cat
    W.reset()
    S.invalidate()


def _codes(env: Any) -> list[str]:
    return [w.code for w in env.warnings]


def test_scope_values_read_what_the_builder_wrote(catalog: Path) -> None:
    from nyshporka.catalog import store as S

    assert set(S.scope_values("churches", "voivodeship") or []) == {"brac", "rus"}
    assert S.scope_values("churches", "confession") == ["uniate"]
    assert set(S.scope_values("geog", "section") or []) == {"church", "rabbinate"}
    assert S.scope_values("geog", "region") is None, (
        "вимір, якого пак не декларує, — «не назване», а не «порожньо»")


def test_church_zero_names_the_voivodeships_the_pack_covers(catalog: Path) -> None:
    from nyshporka.ops_catalog import ChurchFindArgs, church_find

    env = church_find(ChurchFindArgs(q="Бахмут"))
    text = " ".join(w.text for w in env.warnings if w.code == "nothing_found")
    assert "brac" in text and "rus" in text, (
        "нуль бази церков мусить назвати межу пака — інакше село поза Річчю "
        "Посполитою виглядає як «церкви не було»")


def test_church_filter_outside_the_pack_is_called_so(catalog: Path) -> None:
    from nyshporka.ops_catalog import ChurchFindArgs, church_find

    env = church_find(ChurchFindArgs(q="Lipoweńkie", voivodeship="xyz"))
    assert "outside_pack_scope" in _codes(env)


def test_geog_section_outside_the_pack_is_called_so(catalog: Path) -> None:
    from nyshporka.ops_catalog import GeogFindArgs, geog_find

    env = geog_find(GeogFindArgs(q="М'ястківка", section="nope"))
    assert "outside_pack_scope" in _codes(env)


def test_geog_unknown_uezd_is_a_limit_of_the_gazetteer(catalog: Path) -> None:
    from nyshporka.ops_catalog import GeogFindArgs, geog_find

    env = geog_find(GeogFindArgs(q="Олексіївка", uezd="Бахмутськ"))
    assert "outside_pack_scope" in _codes(env)


def test_geog_known_uezd_without_match_is_a_plain_zero(catalog: Path) -> None:
    from nyshporka.ops_catalog import GeogFindArgs, geog_find

    env = geog_find(GeogFindArgs(q="Такогоселанемає", uezd="Ольгопольськ"))
    assert _codes(env) == ["nothing_found"]


def test_catalog_list_json_carries_scope_and_note(catalog: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.catalog.cli import app

    res = CliRunner().invoke(app, ["list", "--json"])
    assert res.exit_code == 0, res.stdout
    packs = {p["pack_id"]: p for p in json.loads(res.stdout)}
    church = packs["churches-test-2026.09"]
    assert church["note"]
    assert {(r["dim"], r["value"]) for r in church["scope"]} >= {
        ("voivodeship", "brac"), ("voivodeship", "rus"), ("confession", "uniate")}
