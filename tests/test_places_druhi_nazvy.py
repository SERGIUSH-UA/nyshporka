"""Пак `places`: другі назви — румунська, GeoNames і варіант без «ґ».

Замір 19.10.2026 на 8203 книгах Супряги: більшість «сіл, яких немає в паку»
насправді в паку були, але під іншою назвою — «Мінжир» лише як «Мінджир»
(румунське Mingir стояло тільки в `name_en`), «Дзигівка» як «Дзиґівка»,
бессарабські Doluchioi чи Tasbunar — лише в GeoNames.
"""
import json
import sqlite3
from pathlib import Path

from nyshporka.catalog.build import build_places

RYADKY = [
    {"qid": "Q1", "name_uk": "Дзиґівка", "name_ru": "Дзыговка", "aliases": "",
     "kind": "село", "admin": "Ямпільський район", "top": "Вінницька область",
     "country": "UA", "lat": 48.3, "lng": 28.2},
    {"qid": "Q2", "name_uk": "Мінджир", "name_ru": "Минжир", "name_en": "Mingir",
     "name_ro": "Mingir", "aliases": "", "kind": "село", "admin": "Хинчештський район",
     "top": "Молдова", "country": "MD", "lat": 46.6, "lng": 28.3},
    {"qid": "Q3", "name_uk": "Багате", "name_ru": "Богатое", "aliases": "",
     "aliases_extra": "Doluchioi | Багате", "kind": "село", "admin": "Ізмаїльський район",
     "top": "Одеська область", "country": "UA", "lat": 45.4, "lng": 28.6},
]


def _pak(tmp_path: Path, ryadky: list[dict]) -> sqlite3.Connection:
    dump = tmp_path / "places.json"
    dump.write_text(json.dumps(ryadky, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "places-test-2026.10.sqlite"
    res = build_places(dump, out, pack_id="places-test-2026.10", taken="2026-10-19")
    assert res["places"] == len(ryadky)
    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    return con


def _riadok(con: sqlite3.Connection, qid: str) -> sqlite3.Row:
    return con.execute("SELECT * FROM modern WHERE qid = ?", (qid,)).fetchone()


def test_variant_bez_g_u_psevdonimakh_a_ne_v_normi(tmp_path: Path) -> None:
    r = _riadok(_pak(tmp_path, RYADKY), "Q1")
    # норма назви та сама, що й раніше: на ній стоять уже роздані паки
    assert r["norm_uk"] == "дзиґівка"
    assert "дзигівка" in r["norm_alias"].split(" | ")
    # показові псевдоніми службовим варіантом не засмічуються
    assert r["aliases"] == ""


def test_rumunska_nazva_shukaietsia_latynkoiu(tmp_path: Path) -> None:
    r = _riadok(_pak(tmp_path, RYADKY), "Q2")
    assert "Mingir" in r["aliases"].split(" | ")
    assert "mingir" in r["translit"].split()


def test_druhi_nazvy_geonames_bez_dubliv_osnovnoi(tmp_path: Path) -> None:
    con = _pak(tmp_path, RYADKY)
    r = _riadok(con, "Q3")
    assert r["aliases"] == "Doluchioi"
    assert "doluchioi" in r["norm_alias"].split(" | ")
    note = con.execute("SELECT v FROM meta WHERE k = 'note'").fetchone()[0]
    assert "GeoNames" in note


def test_staryi_damp_bez_novykh_poliv_zbyraietsia_iak_buv(tmp_path: Path) -> None:
    staryi = [{k: v for k, v in r.items() if k not in ("name_ro", "aliases_extra")}
              for r in RYADKY]
    con = _pak(tmp_path, staryi)
    assert _riadok(con, "Q3")["aliases"] == ""
    note = con.execute("SELECT v FROM meta WHERE k = 'note'").fetchone()[0]
    assert "GeoNames" not in note
