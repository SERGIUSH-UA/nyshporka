"""Засіки перед 0.49.0: хмарний автомат читання опису й дочит колонки № (рев'ю 25.11.2026)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops_opysy as OO
from nyshporka.opysy import dochyt as DC
from nyshporka.opysy import hmara as H
from nyshporka.opysy import meta as M


def _etap(d: Path, tmp: Path, *, kadriv: int, txt: list[str], meta_pages: list[str] = ()) -> Path:
    """Стан етапу `storinky` з теками кадрів і результату, як їх лишає `postavyty` і наглядач."""
    teka = tmp / "teka"
    teka.mkdir(parents=True, exist_ok=True)
    for i in range(1, kadriv + 1):
        (teka / f"{i:04d}.jpg").write_bytes(b"x")
    out = tmp / "out"
    out.mkdir(parents=True, exist_ok=True)
    for s in txt:
        (out / f"{s}.txt").write_text("текст", encoding="utf-8")
    if meta_pages:
        (out / "_htr_meta.json").write_text(json.dumps({"pages": {f"{s}.jpg": {} for s in meta_pages}}),
                                            encoding="utf-8")
    d.mkdir(parents=True, exist_ok=True)
    H.zapysaty_stan(d, {"storinky": {"run_id": "run-1", "out_dir": str(out), "teka": str(teka),
                                     "kadriv": kadriv}})
    return out


def test_gotovo_rakhuie_porozhniu_storinku_z_mety(tmp_path: Path) -> None:
    """Порожня сторінка тексту не має, але рушій записав її в мету — прочитана (інакше «2 з 3» вічно)."""
    d = tmp_path / "opys"
    _etap(d, tmp_path, kadriv=3, txt=["0001", "0002"], meta_pages=["0001", "0002", "0003"])
    assert H.gotovo(d, "storinky") == (3, 3)


def test_zakinchenyi_zakhid_z_nestacheiu_beretsia_iak_ie(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Захід скінчився (наглядач записав кінець), а сторінки бракує — етап не висить «ще читає»:
    прочитане забирається, нестача названа, решту дочитує ця машина."""
    d = tmp_path / "opys"
    _etap(d, tmp_path, kadriv=3, txt=["0001", "0002"])
    a = OO.ReadOpysArgs(dir=str(d), de="hmara", language="ru")
    kudy = tmp_path / "run"
    monkeypatch.setattr(H, "skinchyvsia", lambda zap: False)
    stan, _ = OO._hmara_etap(d, "storinky", tmp_path / "teka", kudy, a)
    assert stan == "ide"
    monkeypatch.setattr(H, "skinchyvsia", lambda zap: True)
    stan, zap = OO._hmara_etap(d, "storinky", tmp_path / "teka", kudy, a)
    assert stan == "gotovo" and zap["nepovno"] == "2 з 3" and zap.get("zabrano")
    assert sorted(p.name for p in kudy.glob("*.txt")) == ["0001.txt", "0002.txt"]


def test_bytyi_stan_iak_porozhnii(tmp_path: Path) -> None:
    (tmp_path / H.FILE).write_text('{"storinky": {"run_id"', encoding="utf-8")
    assert H.stan(tmp_path) == {}


def test_ponad_stelyu_v_auto_zupyniaietsia_a_ne_chytaie_tut(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """`auto`: відмова лише за стелею — це не «хмари немає», а питання до людини (`--confirm`)."""
    monkeypatch.setattr(H, "_cloud_go", lambda args: (10, {"verdict": "needs_confirm",
                                                          "launch": "needs_confirm", "fork_high": 7.5}, ""))
    monkeypatch.setattr(H, "slug", lambda d: "opys-test")
    kadry = tmp_path / "kadry"
    kadry.mkdir()
    (kadry / "0001.jpg").write_bytes(b"x")
    with pytest.raises(H.HmaraError) as e:
        H.postavyty(tmp_path, "storinky", kadry, script="cyrillic")
    assert e.value.zghoda and "--confirm" in str(e.value)


def test_bez_pysma_khmara_ne_vhaduie(tmp_path: Path) -> None:
    d = tmp_path / "opys"
    d.mkdir()
    (d / "opys.json").write_text(json.dumps({"repo": "DAOO", "fond": "445", "opys": "4"}), encoding="utf-8")
    a = OO.ReadOpysArgs(dir=str(d), de="hmara")
    with pytest.raises(H.HmaraError, match="--language"):
        OO._hmara_etap(d, "storinky", tmp_path, tmp_path / "run", a)


def test_podaty_skladaie_teku_nanovo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Перерізаний кроп під тим самим іменем їде новим вмістом, зайвий старий — не їде."""
    monkeypatch.setattr(H, "slug", lambda d: "opys-test")
    kadry = tmp_path / "kropy"
    kadry.mkdir()
    (kadry / "0005__p000.jpg").write_bytes(b"stare")
    (kadry / "0005__p001.jpg").write_bytes(b"zaive")
    H._podaty(tmp_path, "kropy", kadry, "aaaa")
    (kadry / "0005__p000.jpg").unlink()
    (kadry / "0005__p000.jpg").write_bytes(b"nove")
    (kadry / "0005__p001.jpg").unlink()
    teka = H._podaty(tmp_path, "kropy", kadry, "aaaa")
    assert sorted(p.name for p in teka.iterdir()) == ["0005__p000.jpg"]
    assert (teka / "0005__p000.jpg").read_bytes() == b"nove"
    assert H._podaty(tmp_path, "kropy", kadry, "bbbb").name.endswith("-kropy-bbbb")


def test_vidbytok_dochytu_bez_mitky_chasu() -> None:
    """`opys meta` щоразу пише нову мітку часу — дочит від неї не скидається; від сторінок — так."""
    a = M.Meta(forma="hand_ruled", kolonky=["nomer", "nazva"], sprav=10, storinky=(2, 9),
               zapovniv="агент", koly="2026-11-25T10:00:00+00:00")
    b = M.Meta(forma="hand_ruled", kolonky=["nomer", "nazva"], sprav=10, storinky=(2, 9),
               zapovniv="людина", koly="2026-11-25T11:00:00+00:00")
    c = M.Meta(forma="hand_ruled", kolonky=["nomer", "nazva"], sprav=10, storinky=(3, 9))
    assert M.vidbytok_dochytu(a) == M.vidbytok_dochytu(b) != M.vidbytok_dochytu(c)


def _riadky_bez_kolonky_nomera() -> list[tuple[int, int, int, int, str]]:
    """Права сторінка розвороту з порожньою лівою: рушій не побачив колонки № зовсім — ліві рядки
    вже в колонці назв, серед них короткі «тоже»."""
    out = []
    for k in range(8):
        y = 600 + 150 * k
        out.append((2740, y, 3400, y + 100, "Книга решений суда по уголовным делам" if k % 2 == 0 else "тоже"))
        out.append((3900, y, 4050, y + 100, "1806"))
    return out


def test_nomerni_ne_berut_kolonky_nazv() -> None:
    assert DC.nomerni(_riadky_bez_kolonky_nomera(), 4432, 3100) == []


def test_nomerni_berut_nomer_livishe_nazvy() -> None:
    riadky = [*_riadky_bez_kolonky_nomera(), (2460, 600, 2530, 700, "21."), (2470, 900, 2520, 1000, "аз")]
    got = [ln[4] for _i, _p, ln in DC.nomerni(riadky, 4432, 3100)]
    assert got == ["21.", "аз"]


def test_liva_nazv_ne_vid_riadka_z_nomerom() -> None:
    """Рядок «21. Книга…» стоїть у колонці №: лівий край назв — за рядками без числа на початку."""
    riadky: list[Any] = [(2460, 600 + 150 * k, 3400, 700 + 150 * k, f"{21 + k}. Книга решений суда") for k in range(5)]
    riadky += [(2740, 1500 + 150 * k, 3400, 1600 + 150 * k, "Книга регистрации торговых сделок") for k in range(5)]
    assert DC.liva_nazv(riadky) == 2740
