"""Машинописний опис з виходу рушія друку (`nyshporka.opysy.vl_table`): сітка таблиці, справи за
вмістом клітинок, номери (підтвердження, літерна справа, новий розділ), смуга справи в рамці."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from nyshporka.opysy import vl_table as V

_MD = """<table><tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td></tr>
<tr><td>{a}</td><td>Дело о межевании земли помещика Иванова</td><td>04 січня 1881р.</td><td>12 березня 1882р.</td><td>12</td></tr>
<tr><td>{b}</td><td>Дело о краже у мещанина Кондратюка в Балте</td><td>02 лютого 1883р.</td><td>30 травня 1884р.</td><td>7</td></tr>
<tr><td>{c}</td><td>Список однодворцев селения Липовеньки</td><td>01 липня 1885р.</td><td>19 серпня 1885р.</td><td>3</td></tr>
</table>"""


def _opys(tmp: Path, nomery: list[tuple[str, str, str]]) -> Path:
    d = tmp / "vl"
    d.mkdir()
    for i, (a, b, c) in enumerate(nomery, start=1):
        (d / f"{i:04d}.md").write_text(_MD.format(a=a, b=b, c=c), encoding="utf-8")
        (d / f"{i:04d}.blocks.json").write_text(json.dumps(
            {"width": 1700, "blocks": [{"label": "table", "bbox": [100, 300, 1600, 2100]}]}),
            encoding="utf-8")
    return d


def _rows(p: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(p.open(encoding="utf-8"), delimiter="\t"))


def test_spravy_nomery_i_smuhy(tmp_path: Path) -> None:
    d = _opys(tmp_path, [("10", "11", "12"), ("13", "13", "14")])
    res = V.build(d, tmp_path / "t.tsv", "1")
    rows = _rows(tmp_path / "t.tsv")
    assert res["cases"] == 6 and res["mistse_vl"] == 6
    # шапка з самих номерів колонок — не справа; номери підтверджені сусідами
    assert [r["no"] for r in rows] == ["10", "11", "12", "13", "13а", "14"]
    assert [bool(r["confirmed"]) for r in rows] == [True, True, True, True, False, True]
    assert rows[0]["title"].startswith("Дело о межевании") and rows[0]["year_from"] == "1881"
    assert rows[0]["folios"] == "12"
    # смуги — у рамці таблиці, по порядку, не перекриваються (крім запасу вгору)
    smuhy = [tuple(map(int, r["y"].split("-"))) for r in rows if r["page"] == "0001"]
    assert all(300 - V.ZAPAS <= a < b <= 2100 for a, b in smuhy)
    assert all(smuhy[i][1] <= smuhy[i + 1][0] + V.ZAPAS for i in range(len(smuhy) - 1))


def test_novyi_rozdil_z_odynytsi(tmp_path: Path) -> None:
    d = _opys(tmp_path, [("10", "11", "12"), ("1", "2", "3")])
    V.build(d, tmp_path / "t.tsv", "1")
    rows = _rows(tmp_path / "t.tsv")
    assert [r["no"] for r in rows] == ["10", "11", "12", "1", "2", "3"]
    assert all(r["confirmed"] == "neighbors" for r in rows)


def test_bez_ramky_tablytsi_vsia_storinka(tmp_path: Path) -> None:
    d = _opys(tmp_path, [("10", "11", "12")])
    (d / "0001.blocks.json").write_text(json.dumps({"blocks": []}), encoding="utf-8")
    res = V.build(d, tmp_path / "t.tsv", "1")
    assert res["bez_ramky"] == 3
    assert {r["y"] for r in _rows(tmp_path / "t.tsv")} == {f"0-{V.VYSOTA}"}
