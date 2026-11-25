"""Машинописний опис: розбір розмітки рушія друку (`opysy.vl_table`) і шлях `nysh opys read` через
хмару друку. Розмітка синтетична; заміри на справжніх описах — у дослідницькому конвеєрі."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from nyshporka import ops_opysy as OO
from nyshporka.opysy import vl_table as VT


def _tablytsia(riadky: list[list[str]]) -> str:
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in riadky)
    return f"<table border=1>{tr}</table>"


SHAPKA = ["Порядковий номер", "Заголовок справи", "Дати справи", "Кількість аркушів", "Примітки"]


def _spravy(vid: int, do: int, *, shyrina: int = 5) -> list[list[str]]:
    out = []
    for n in range(vid, do + 1):
        r = [str(n), f"Метрична книга костелу села номер {n}", "1 січня 1890", "120"]
        out.append(r + [""] * (shyrina - len(r)))
    return out


def _md(teka: Path, stem: str, html: str) -> None:
    teka.mkdir(parents=True, exist_ok=True)
    (teka / f"{stem}.md").write_text(html, encoding="utf-8")
    (teka / f"{stem}.blocks.json").write_text(json.dumps({"blocks": []}), encoding="utf-8")


def test_storinka_bez_shapky_inshoi_shyryny_ne_propadaie(tmp_path: Path) -> None:
    """Сторінка без шапки, де VL загубив порожню колонку (інша ширина, ніж у попередньої): перша
    колонка — номери, тож справи сторінки не пропадають."""
    vl = tmp_path / "vl"
    _md(vl, "0001", _tablytsia([SHAPKA, *_spravy(1, 5)]))
    _md(vl, "0002", _tablytsia(_spravy(6, 10, shyrina=4)))       # без шапки, 4 колонки
    res = VT.build(vl, tmp_path / "t.tsv", opys="1")
    assert res["cases"] == 10, res


def test_nomery_z_inshoi_kolonky_lantsiuzhkom(tmp_path: Path) -> None:
    """VL прочитав «№ за старим описом» замість рукописного № з/п (14, 15, 16 там, де 72–74):
    між опорами 71 і 75 рівно три рядки — номери за порядком."""
    vl = tmp_path / "vl"
    _md(vl, "0001", _tablytsia([SHAPKA, *_spravy(66, 71)]))
    stara = [[str(n), f"Костьол містечка номер {n}", "1 січня 1881", "312", ""] for n in (14, 15, 16)]
    _md(vl, "0002", _tablytsia(stara))
    _md(vl, "0003", _tablytsia(_spravy(75, 79)))
    VT.build(vl, tmp_path / "t.tsv", opys="2")
    import csv

    rows = list(csv.DictReader((tmp_path / "t.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert [r["no"] for r in rows if r["page"] == "0002"] == ["72", "73", "74"]
    assert all(r["confirmed"] for r in rows if r["page"] == "0002")


def test_tochnyi_lantsiuzhok_ne_bere_vypadkovoho_chytannia() -> None:
    """Опора — лише де номер росте рівно на число рядків: випадкове «125» серед хибних читань не
    ламає лічбу 124 → 140."""
    reads = [(0, 122), (1, 123), (2, 124), (3, 115), (4, 116), (5, 125), (6, 194), (7, 192), (8, 140)]
    kotvy = VT._tochnyi_lantsiuzhok(reads)
    assert (2, 124) in kotvy and (5, 125) not in kotvy


# ── шлях `nysh opys read` для машинопису ──────────────────────────────────────


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.opysy import remote as R

    monkeypatch.setattr(R, "policy", lambda repo, fond, base="": {"open": True})
    monkeypatch.setattr(OO, "_orenda_ye", lambda: False)


def _pdf(tmp: Path) -> Path:
    pdf = tmp / "opys.pdf"
    Image.new("RGB", (1000, 1400), "white").save(
        pdf, save_all=True, append_images=[Image.new("RGB", (1000, 1400), "white")])
    return pdf


def test_read_mashynopys_cherez_hmaru_druku(tmp_path: Path, server: None,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Машинопис: сторінки під рушій друку, захід друку в хмару, повтор забирає розмітку → прогін
    → таблиця з `vl_table` → пачки нормалізації."""
    from nyshporka.opysy import hmara as H

    vyklyky: list[list[str]] = []

    def _go(args: list[str]) -> Any:
        vyklyky.append(args)
        out = Path(args[args.index("--out-root") + 1]) / Path(args[0]).name
        return 0, {"verdict": "detached", "run_id": "druk-1", "out_dir": str(out)}, ""

    monkeypatch.setattr(H, "_cloud_go", _go)
    d = tmp_path / "opys"
    url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Opys.pdf"
    env = OO.opysy_read(OO.ReadOpysArgs(dir=str(d), pdf=str(_pdf(tmp_path)), repo="ДАХмО", fond="17",
                                        opys="2", url=url, language="uk"))
    assert env.ok and env.data.get("meta_potribni")
    assert OO.opysy_meta(OO.MetaArgs(dir=str(d), forma="typed", kolonky="nomer,delovod,nazva,pochatok,kinets,arkushi",
                                     sprav=0)).ok
    env = OO.opysy_read(OO.ReadOpysArgs(dir=str(d), language="uk"))
    assert env.ok and env.data["hmara"]["etap"] == "druk", env
    assert "--print" in vyklyky[0] and "--not-an-edition" in vyklyky[0]
    assert Image.open(next((d / "pages_druk").glob("*.jpg"))).size[1] == VT.VYSOTA
    # повтор, поки рушій не віддав розмітки, — без нового заходу
    env = OO.opysy_read(OO.ReadOpysArgs(dir=str(d), language="uk"))
    assert env.ok and env.data["hmara"]["stan"] == "ide" and len(vyklyky) == 1
    out = Path(H.stan(d)["druk"]["out_dir"])
    _md(out, "0001", _tablytsia([SHAPKA, *_spravy(1, 4)]))
    _md(out, "0002", _tablytsia(_spravy(5, 7)))
    for s in ("0001", "0002"):
        (out / f"{s}.txt").write_text("Метрична книга костелу", encoding="utf-8")
    env = OO.opysy_read(OO.ReadOpysArgs(dir=str(d), language="uk"))
    assert env.ok, env
    assert env.data["sprav"] == 7 and env.data["pachok_normalizatsii"] >= 1
    assert (d / "run" / "0001.txt").exists() and (d / "run" / "0001.lines.json.gz").exists()


def test_dzherelo_teka_kadriv(tmp_path: Path) -> None:
    """Архів публікує опис кадрами (тека на своєму файлообміннику): тека — джерело так само, як PDF.
    Сторінки — самі кадри під висоту читання; відбиток — з імен і вмісту кадрів; адреса не мусить
    вести на файл."""
    from nyshporka.opysy import pages as PG
    from nyshporka.opysy import workdir as W

    teka = tmp_path / "010792"
    teka.mkdir()
    for i in range(3):
        Image.new("RGB", (1728, 2592), "white").save(teka / f"0000{i + 1}.JPG")
    d = tmp_path / "opys"
    pas = W.init(d, teka, repo="ДАОО", fond="445", opys="9",
                 url="https://archive.example/d/s/600562020850376707/z56")
    assert pas["pages"] == 3 and len(pas["source"]["sha256"]) == 64
    res = PG.render(teka, d / "pages", target_h=2400)
    assert res["pages"] == 3 and Image.open(d / "pages" / "0001.jpg").size[1] == 2400
    # інший кадр — інший відбиток
    Image.new("RGB", (1728, 2592), "black").save(teka / "00003.JPG")
    assert W.init(tmp_path / "opys2", teka, repo="ДАОО", fond="445", opys="9",
                  url="https://archive.example/d/s/1")["source"]["sha256"] != pas["source"]["sha256"]


def test_zaholovok_roku_ne_sprava(tmp_path: Path) -> None:
    """Машинопис ставить рік окремим рядком між справами («1799») — це не справа й не номер."""
    vl = tmp_path / "vl"
    riadky = [SHAPKA, *_spravy(1, 3), ["1799", "", "", "", ""], *_spravy(4, 6)]
    _md(vl, "0001", _tablytsia(riadky))
    res = VT.build(vl, tmp_path / "t.tsv", opys="1")
    assert res["cases"] == 6, res


def test_perestavleni_arkushi_ne_psuiut_nomeriv(tmp_path: Path) -> None:
    """Архів виклав два аркуші переставленими (кадри: 1–5, 11–15, 6–10, 16–20): номери, прочитані
    правильно, лишаються, а не «виправляються» за порядком файлів."""
    import csv

    vl = tmp_path / "vl"
    _md(vl, "0001", _tablytsia([SHAPKA, *_spravy(1, 5)]))
    _md(vl, "0002", _tablytsia(_spravy(11, 15)))
    _md(vl, "0003", _tablytsia(_spravy(6, 10)))
    _md(vl, "0004", _tablytsia(_spravy(16, 20)))
    VT.build(vl, tmp_path / "t.tsv", opys="1")
    rows = list(csv.DictReader((tmp_path / "t.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert [r["no"] for r in rows if r["page"] == "0002"] == ["11", "12", "13", "14", "15"]
    assert [r["no"] for r in rows if r["page"] == "0003"] == ["6", "7", "8", "9", "10"]


def test_druhyi_riadok_daty_ne_sprava(tmp_path: Path) -> None:
    """Друга частина дати окремим рядком («805 | | 30 декаб 1805»): уривок року — не номер, рядок — не
    справа; назва, яку VL поклав у дати, — назва справи."""
    import csv

    vl = tmp_path / "vl"
    riadky = [SHAPKA, *_spravy(1, 3), ["805", "", "30 декаб 1805", "", ""], *_spravy(4, 5),
              ["6", "", "Книга записи доверенностей 1806 г.", "", ""], *_spravy(7, 8)]
    _md(vl, "0001", _tablytsia(riadky))
    res = VT.build(vl, tmp_path / "t.tsv", opys="1")
    rows = list(csv.DictReader((tmp_path / "t.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert res["cases"] == 8, res
    assert [r["no"] for r in rows] == [str(n) for n in range(1, 9)]
    assert "доверенностей" in rows[5]["title"]
