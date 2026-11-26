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


# ── ЦДІАК ф.49 оп.2 (26.11.2026): машинопис 1950-х, одиниця літерою I, сторінки текстом ──


def test_odynytsia_literoiu_I_ne_hubyt_pershoi_tsyfry() -> None:
    assert V._nomer_vl("I304") == (1304, "")
    assert V._nomer_vl("I 53") == (153, "")
    assert V._nomer_vl("136a") == (136, "а")
    assert V.num("I 53") == 153


def test_to_zhe_z_rokom_okrema_sprava(tmp_path: Path) -> None:
    d = tmp_path / "vl"
    d.mkdir()
    (d / "0001.md").write_text(
        "<table><tr><td>2871</td><td>Акты на латинском языке за 1725-29гг. часть I.</td><td>78</td></tr>"
        "<tr><td>2872</td><td>To me - &quot; - - &quot; - за 1730г.</td><td>53</td></tr>"
        "<tr><td>2873</td><td>То же за 1730-1735гг.</td><td>166</td></tr>"
        "<tr><td>2874</td><td>1736г.</td><td>45</td></tr></table>", encoding="utf-8")
    V.build(d, tmp_path / "t.tsv", "2")
    rows = _rows(tmp_path / "t.tsv")
    assert [r["no"] for r in rows] == ["2871", "2872", "2873", "2874"]
    assert rows[2]["title"].startswith("То же")


def test_storinka_tekstom_bez_tablytsi() -> None:
    md = ("208\n\n1 2 3 4 5\n\n1785\n\nПисьма Боровского Потоцким за 1712, 1714 и 1715 гг.\n\n"
          "1786\n\nПисьма Браницких Потоцким за 1716 и 1789 гг.\n\n"
          "Cnucos pereii, npousnecnmop na ceiwk.\n\n"
          "1787 То же Броповчика Потоцким за 1731 и 1839 гг. 3\n\n"
          "Проект письма неустановленного лица о продаже леса в имении Потоцких.\n\n6\n\n20\n\n3\n")
    sides, prev = V.records(md, (5, [{"no": 0}]))
    assert prev == (5, [{"no": 0}])
    r = sides[0]
    # номер сторінки й стовпчик аркушів — не справи; латиниця рукописної вставки — геть
    assert [x["no"] for x in r] == [1785, 1786, 1787, None]
    assert r[1]["title"] == ["Письма Браницких Потоцким за 1716 и 1789 гг."]
    assert r[2]["title"] == ["То же Броповчика Потоцким за 1731 и 1839 гг."] and r[2]["folios"] == ["3"]
    assert r[3].get("lost_no") and r[3]["title"][0].startswith("Проект письма")


def test_storinka_tekstom_khvist_poperednoi() -> None:
    r = V.records("ского уезда Подольской губернии.\n\n## I44\n\nДело о разделе имения Литинцы.\n")[0][0]
    assert r[0].get("cont") and r[0]["title"] == ["ского уезда Подольской губернии."]
    assert r[1]["no"] == 144 and r[1]["title"] == ["Дело о разделе имения Литинцы."]


def test_storinka_tekstom_smuhy_v_ramtsi_tekstu(tmp_path: Path) -> None:
    d = tmp_path / "vl"
    d.mkdir()
    (d / "0001.md").write_text("785\n\nПисьма Боровского Потоцким за 1712 г.\n\n786\n\n"
                               "Письма Браницких Потоцким за 1716 г.\n\n787\n\nПисьма Брукль Потоцким за 1763 г.\n",
                               encoding="utf-8")
    (d / "0001.blocks.json").write_text(json.dumps({"blocks": [
        {"label": "number", "bbox": [1386, 100, 1474, 177]},
        {"label": "content", "bbox": [69, 229, 1310, 2250]}]}), encoding="utf-8")
    res = V.build(d, tmp_path / "t.tsv", "2")
    rows = _rows(tmp_path / "t.tsv")
    assert [r["no"] for r in rows] == ["785", "786", "787"] and res["mistse_vl"] == 3
    smuhy = [tuple(map(int, r["y"].split("-"))) for r in rows]
    # кожна справа — своя смуга в рамці тексту, а не вся сторінка
    assert len(set(smuhy)) == 3 and all(229 - V.ZAPAS <= a < b <= 2250 for a, b in smuhy)


def test_storinka_tekstom_nomer_lantsiuzhkom_ne_rik(tmp_path: Path) -> None:
    d = tmp_path / "vl"
    d.mkdir()
    (d / "0001.md").write_text("1785\n\nПисьма Боровского Потоцким за 1712 г.\n\n1786\n\n"
                               "Письма Браницких Потоцким за 1716 г.\n\n1787\n\nПисьма Брукль Потоцким за 1763 г.\n",
                               encoding="utf-8")
    V.build(d, tmp_path / "t.tsv", "2")
    # перший номер сторінки без сусіда ще може бути роком над справою; наступні йдуть ланцюжком — номери
    assert [r["no"] for r in _rows(tmp_path / "t.tsv")][1:] == ["1786", "1787"]


def test_storinka_tekstom_zasvidchennia_ne_sprava() -> None:
    # лише засвідчувальний напис розділу (ДАХмО ф.17 оп.2, стор. 23) — справ немає
    md = ("В даний розділ опису внесено 20 (двадцять ) справ\n\n3 № по № 71 у тому числі:\n\n"
          "Заступник начальника Славутського міськарайонного управління юстиції\n\nСХВАЛЕНО\n")
    assert V.records(md)[0] == []
    # напис після справ закінчує сторінку
    md = ("1785\n\nПисьма Боровского Потоцким за 1712 г.\n\n1786\n\nПисьма Браницких Потоцким за 1716 г.\n\n"
          "Внесено на підставі акту 152 від 02.06.98 р. 116 справ.\n\nЗав. відділом Сухих\n")
    r = V.records(md)[0][0]
    assert [x["no"] for x in r] == [1785, 1786] and r[-1]["title"] == ["Письма Браницких Потоцким за 1716 г."]
    # підпис ЕК з числом над «СХВАЛЕНО» (ДАХмО ф.17 оп.2, стор. 41) — не справа
    assert V.records("Літерні номери - немає\n\nОпис склав :\n\n3\n\nСХВАЛЕНО\n\nПротокол ЕК\n")[0] == []


# ── ДАВіО ф.5 оп.3 (26.11.2026): форма № 4, перші колонки порожні, шапка з номерів колонок з вадами ──


def _td(*cells: str) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _forma4(shapka: list[str], start: int, n: int = 3) -> str:
    """Сторінка форми № 4: дві порожні колонки, номер справи в третій, назва, дата, аркуші."""
    rows = [_td(*shapka)]
    for k in range(start, start + n):
        rows.append(_td("", "", str(k), f"То же, Ивана Петровича Маньковского {k}", "", "2"))
    return "<table>" + "".join(rows) + "</table>"


def test_shapka_nomeriv_kolonok_z_vadamy_ne_hubyt_storinku() -> None:
    # VL склеїв дві клітинки, загубив номер порожньої колонки, домішав сусіднє число
    for shapka in (["1", "2", "3", "2\n4", "5", "6"], ["2", "3", "", "", "6", ""],
                   ["2", "3", "24", "", "6", ""], ["2", "3", "", "", "", ""]):
        sides, _ = V.records(_forma4(shapka, 12))
        assert [r["no"] for s in sides for r in s if r["no"] is not None] == [12, 13, 14], shapka


def test_shapka_z_troiky_pravyi_bik_rozvorotu_ne_tablytsia_z_nomeramy() -> None:
    # «3 4 5 6» — права сторінка розвороту без колонки №: назви не мають прилипнути до чужої справи
    md = "<table>" + _td("3", "4", "5", "6") + _td("Грамота митрополита о работе крестьян", "1805г.", "1", "") + "</table>"
    p = V._Tables()
    p.feed(md)
    assert V._nomery_kolonok(V.grid(p.tables[0])) is None


def test_persha_neporozhnia_klitynka_i_rowspan() -> None:
    # номер справи — у третій колонці; другий рядок назви наслідує номер через rowspan і не рахується
    md = ("<table>" + _td("", "", "769", "Геодезическое описание земли с. Лю-", "", "6")
          + _td("", "", "", "пинец, находящейся в пользовании", "", "")
          + _td("", "", "770", "То же, Аполинария Людвиговича Орловского", "", "")
          + "</table>")
    p = V._Tables()
    p.feed(md)
    assert V._persha_chysla(V.grid(p.tables[0]))
    md2 = ('<table><tr><td rowspan="2">197</td><td>Метрична книга</td></tr>'
           "<tr><td>Чорноострівської церкви</td></tr>"
           '<tr><td rowspan="2">198</td><td>Метрична книга</td></tr>'
           "<tr><td>Фельштинської церкви</td></tr></table>")
    p2 = V._Tables()
    p2.feed(md2)
    assert V._persha_chysla(V.grid(p2.tables[0]))


def test_storinka_insha_shyryna_bez_shapky_ne_hubytsia(tmp_path: Path) -> None:
    # стор. 2 — 7 колонок із шапкою, стор. 3 — 6 колонок без шапки: розкладка попередньої не підходить,
    # але номери стоять першими в рядках — сторінка лишається (ДАВіО ф.5 оп.3, стор. 56→57)
    d = tmp_path / "vl"
    d.mkdir()
    (d / "0001.md").write_text(_forma4(["1", "2", "3", "4", "5", "6", "7"], 1), encoding="utf-8")
    rows = "".join(_td("", "", str(k), f"То же, Карла Ивановича Яблонского {k}", "") for k in (4, 5, 6))
    (d / "0002.md").write_text("<table>" + rows + "</table>", encoding="utf-8")
    V.build(d, tmp_path / "t.tsv", "3")
    assert [r["no"] for r in _rows(tmp_path / "t.tsv")] == ["1", "2", "3", "4", "5", "6"]
