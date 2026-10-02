"""Збірна тека: кадри кількох справ не йдуть далі під шифрою першої.

Звіт користувача (29.09.2026): тека `RGIA_592_25_926_929` несе справи 926–929,
а перелік неподіленого пропонував її як одну справу 926.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Бібліотека заморожує простір на імпорті — тож усе, що її тягне, імпортується
# у фікстурі, після оголошення тимчасового простору.
C: Any = None
R: Any = None
SP: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import legacy_key as K
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    K.reset()

    global C, R, SP
    from nyshporka import htr_store
    from nyshporka import library as lib
    from nyshporka.cases import chain, register, span
    from nyshporka.cases import db as DB
    from nyshporka.pagestore import store as S

    C, R, SP = chain, register, span
    for mod, attr, value in (
        (lib, "ROOT", tmp_path), (lib, "RAW_DIR", tmp_path / "data" / "raw"),
        (lib, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (lib, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (S, "ROOT", tmp_path), (S, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
        (htr_store, "ROOT", tmp_path), (htr_store, "HTR_ROOT", tmp_path / "reports" / "htr"),
        (htr_store, "_RUNS_CACHE", None),
    ):
        monkeypatch.setattr(mod, attr, value)
    htr_store._META_MEMO.clear()
    for fn in ("load_library", "_sidecar_case"):
        got = getattr(lib, fn, None)
        if got is not None and hasattr(got, "cache_clear"):
            got.cache_clear()
    yield tmp_path
    htr_store._META_MEMO.clear()
    K.reset()
    W.reset()


@pytest.fixture
def sp(space: Path) -> Any:
    """Розпізнавання саме по собі простору не потребує, але модуль тягне бібліотеку."""
    return SP


def _teka(space: Path, name: str, n: int = 3) -> Path:
    d = space / "data" / "raw" / "rgia_592" / name
    d.mkdir(parents=True)
    for i in range(1, n + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"x")
    return d


# ── розпізнавання ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("shifra", [
    "RGIA 592-25-926-929", "РДІА 592-25-926–929", "592-25-926_929", "RGIA 592 - 25 - 926 - 929"])
def test_diapazon_u_shyfri(sp: Any, shifra: str) -> None:
    got = sp.in_shifra(shifra)

    assert got is not None and (got.spr_from, got.spr_to, got.declared) == (926, 929, True)
    assert got.count == 4 and "926–929" in got.why


@pytest.mark.parametrize("shifra", [
    "ДАХмО 230-1-112",          # звичайна шифра
    "ДАХмО 315-1-84a",          # літера
    "ДАОО 900-5-24-1886",       # рік за номером справи
    "ANRM 211-11-27-2233036",   # номер плівки
    "RGIA 592-25-929-926",      # спадання — не діапазон
    "RGIA 592-25-926-926"])
def test_ne_diapazon_u_shyfri(sp: Any, shifra: str) -> None:
    assert sp.in_shifra(shifra) is None


def test_imia_lyshe_u_vuzkii_formi(sp: Any) -> None:
    """🔴 Чотири числа поспіль мають сотні імен прогонів, і майже всі — рік,
    плівка чи том. Діапазоном ім'я читається лише як `<архів>_ф_оп_спр_спр`."""
    got = SP.in_name("RGIA_592_25_926_929")
    assert got is not None and (got.spr_from, got.spr_to, got.declared) == (926, 929, False)
    assert SP.in_name("data/raw/x/RGIA_592_25_1549_1555") is not None

    for name in ("621-1-14_1868", "1009-1-1_1847-1849", "anrm_211_11_27_2233036",
                 "cdiak127-127-1012-1071_a", "900-5-24_1886_kairy", "442-300-3_1859",
                 "RGIA_592_25_926", "RGIA_592_25_926_929-diak_v4"):
        assert SP.in_name(name) is None, name


# ── паспорт ──────────────────────────────────────────────────────────────────

def test_pasport_ne_hubyt_khvist_diapazonu(space: Path) -> None:
    """🔴 `nysh case --shifra "…926-929"` зводив шифру до першої справи, і
    діапазон зникав без сліду."""
    d = _teka(space, "zbirka")

    out = R.describe(d, shifra="RGIA 592-25-926-929")

    assert (out["spr"], out["spr_to"]) == ("926", "929")
    got = SP.of_dir(d)
    assert got is not None and got.declared and got.label == "926–929"


def test_one_case_znimaie_poznachku(space: Path) -> None:
    d = _teka(space, "RGIA_592_25_926_929")
    assert SP.of_dir(d) is not None

    R.describe(d, shifra="RGIA 592-25-926", one_case=True)

    assert SP.of_dir(d) is None
    assert json.loads((d / "_source.json").read_text(encoding="utf-8"))["one_case"] is True


def test_nova_shyfra_bez_diapazonu_stiraie_khvist(space: Path) -> None:
    d = _teka(space, "zbirka")
    R.describe(d, shifra="RGIA 592-25-926-929")

    out = R.describe(d, shifra="RGIA 592-25-926")

    assert "spr_to" not in out and SP.of_dir(d) is None


def test_case_register_poperedzhaie(space: Path) -> None:
    from nyshporka import ops as O

    d = _teka(space, "zbirka")
    env = O.call("case.register", {"case_dir": str(d), "shifra": "RGIA 592-25-926-929",
                                   "reindex": False})

    assert env.ok, env.error
    assert any(w.code == "span" for w in env.warnings)
    assert env.data["span"] == {"from": 926, "to": 929, "declared": True,
                                "source": "РДІА 592-25-926–929"}


# ── ланцюг справи ────────────────────────────────────────────────────────────

def test_lantsiuh_zbirna_teka_tse_obryv(space: Path) -> None:
    d = _teka(space, "zbirka")
    R.describe(d, shifra="RGIA 592-25-926-929")

    got = C.judge(d, frames=3)

    assert got.link == C.BUNDLE_FOLDER and got.broken
    assert "926–929" in got.why and "--one-case" in got.fix


def test_lantsiuh_za_imenem_bez_pasporta(space: Path) -> None:
    d = _teka(space, "RGIA_592_25_926_929")

    assert C.judge(d).link == C.BUNDLE_FOLDER


def test_lantsiuh_zvychaina_sprava_ne_zbirna(space: Path) -> None:
    d = _teka(space, "spr-926")
    R.describe(d, shifra="RGIA 592-25-926")

    assert C.judge(d).link != C.BUNDLE_FOLDER


# ── перелік неподіленого й пакування ─────────────────────────────────────────

def _prohin(space: Path, name: str, case_dir: Path, key: str) -> Path:
    run = space / "reports" / "htr" / name
    run.mkdir(parents=True)
    pages = {}
    for p in sorted(case_dir.glob("*.jpg")):
        (run / f"{p.stem}.txt").write_text("Іванъ Петровъ сынъ\n" * 3, encoding="utf-8")
        pages[p.name] = {"lines": 3}
    (run / "_htr_meta.json").write_text(json.dumps({
        "case_dir": str(case_dir.relative_to(space)).replace("\\", "/"),
        "case_key": key, "frames_total": len(pages), "model": "pysar_cyr_v17.pt",
        "engine": "parseq", "script": "cyrillic", "done": True, "pages": pages,
    }, ensure_ascii=False), encoding="utf-8")
    return run


def test_suggest_ne_proponuie_zbirnu_yak_hotovu(space: Path) -> None:
    from nyshporka.share import suggest as SG

    d = _teka(space, "RGIA_592_25_926_929")
    R.describe(d, shifra="RGIA 592-25-926-929")
    _prohin(space, "RGIA_592_25_926_929", d, "RGIA/592/926")
    e = _teka(space, "spr-1000")
    R.describe(e, shifra="RGIA 592-25-1000")
    _prohin(space, "rgia_592-spr-1000", e, "RGIA/592/1000")

    rows = {r["case_key"]: r for r in SG.nepodileni()}

    assert rows["RGIA/592/926"]["status"] == SG.ZBIRNA
    assert rows["RGIA/592/926"]["span"]["to"] == 929
    assert rows["RGIA/592/1000"]["status"] != SG.ZBIRNA
    assert "span" not in rows["RGIA/592/1000"]
    assert SG.pidsumok(list(rows.values()))[SG.ZBIRNA] == 1


def test_pack_vidmovliaie_zbirnii_tetsi(space: Path) -> None:
    from nyshporka.share import publish as PUB

    d = _teka(space, "RGIA_592_25_926_929")
    R.describe(d, shifra="RGIA 592-25-926-929")
    run = _prohin(space, "RGIA_592_25_926_929", d, "RGIA/592/926")

    assert "збірна тека" in PUB._zbirna_teka("RGIA/592/926", [run])
    out = PUB.pack("RGIA/592/926", dry_run=True)
    assert any("збірна тека" in x for x in out["pack_refusals"])
    with pytest.raises(PUB.PublishError, match="збірна тека"):
        PUB.pack("RGIA/592/926", space / "out", geometry=False, card_fields={"frames": 3})
    e = _teka(space, "spr-1000")
    R.describe(e, shifra="RGIA 592-25-1000")
    assert PUB._zbirna_teka("RGIA/592/1000", [_prohin(space, "r1000", e, "RGIA/592/1000")]) == ""
