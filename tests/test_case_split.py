"""Розбивка збірної теки на справи: `nysh cases split`.

Звіт користувача (29.09.2026): тека `RGIA_592_25_926_929` несе кадри чотирьох
справ, а пакет бачив у ній справу 926. Розбивка робить із неї справжні справи
— і стережеться тут те, що при цьому може подвоїтись або осиротіти: кадри в
каталозі, сторінки в пошуку, прогони у віддачі, нотатки сховища сторінок.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from _cherha import drop_space, frames, make_space

SPL: Any = None
REG: Any = None
L: Any = None
S: Any = None

OLD = "rgia_592/RGIA_592_25_926_929"
RUN = "RGIA_592_25_926_929"
VOICE = RUN + "-diak_v4"
MAP = [("926", "0001.jpg", "0003.jpg"), ("927", "0004.jpg", "0005.jpg"),
       ("928", "0006.jpg", "0007.jpg"), ("-", "0008.jpg", "0008.jpg")]


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    global SPL, REG, L, S
    from nyshporka import htr_store
    from nyshporka import library as lib
    from nyshporka.cases import register, split

    SPL, REG, L, S = split, register, lib, htr_store
    yield tmp_path
    drop_space()


def _run(space: Path, name: str, d: Path, *, key: str, voice: bool = False) -> Path:
    out = space / "reports" / "htr" / name
    out.mkdir(parents=True)
    names = sorted(p.name for p in d.glob("*.jpg"))
    for n in names:
        (out / f"{Path(n).stem}.txt").write_text(f"текст кадру {n}\n", encoding="utf-8")
        if not voice:
            (out / f"{Path(n).stem}.lines.json").write_text("{}", encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "case_dir": f"data/raw/{OLD}", "case_key": key, "frames_total": len(names),
        "model": "diak_cyr_v4.mlmodel" if voice else "pysar_cyr_v17.pt",
        "engine": "kraken" if voice else "parseq", "script": "cyrillic",
        "done": len(names) if voice else True, "stages_total": {"seg": 99.0},
        "failed": ["0005.jpg"], "pages": {n: {"lines": 1} for n in names},
    }, ensure_ascii=False), encoding="utf-8")
    return out


@pytest.fixture
def zbirka(space: Path) -> Path:
    """Тека чотирьох справ із прогоном, другим голосом і нотатками сторінок."""
    from nyshporka.cases import db
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote

    d = frames(space, OLD, 8)
    REG.describe(d, shifra="RGIA 592-25-926-929")
    _run(space, RUN, d, key="RGIA/592/25/926")
    _run(space, VOICE, d, key="RGIA/592/25/926", voice=True)
    db.rebuild(rescan=True)
    ref = PS.resolve_case("RGIA 592-25-926")
    PS.annotate_pages(ref, [
        PageNote(scan=f"{i:04d}.jpg", page_type="birth", surnames=[f"Прізвище{i}"])
        for i in (2, 4, 6, 8)])
    return d


def _keys() -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in L.load_library()}


def _runs() -> dict[str, dict[str, Any]]:
    S._RUNS_CACHE = None
    return {r["name"]: r for r in S.list_cases()}


# ── проба ────────────────────────────────────────────────────────────────────

def test_proba_pokazuie_plan_i_nichoho_ne_pyshe(space: Path, zbirka: Path) -> None:
    from nyshporka import ops as O

    env = O.call("cases.split", {
        "case_dir": str(zbirka), "dry_run": True,
        "parts": ["926=0001.jpg..0003.jpg", "927=0004.jpg..0005.jpg",
                  "928=0006.jpg..0007.jpg", "-=0008.jpg..0008.jpg"]})

    assert env.ok, env.error
    parts = env.data["parts"]
    assert [(p["spr"], p["frames"], p["from"], p["to"]) for p in parts] == [
        ("926", 3, 1, 3), ("927", 2, 4, 5), ("928", 2, 6, 7), ("-", 1, 8, 8)]
    assert parts[1]["key"] == "RGIA/592/25/927" and parts[1]["shifra"] == "РДІА 592-25-927"
    assert parts[1]["dir"] == "data/raw/rgia_592/op25-spr-927"
    assert parts[1]["runs"] == {RUN: "op25-spr-927", VOICE: "op25-spr-927-diak_v4"}
    assert [p["notes"] for p in parts] == [1, 1, 1, 0]
    assert any(w.code == "references" for w in env.warnings)
    assert not (space / "data/raw/rgia_592/op25-spr-927").exists()
    assert not (zbirka / SPL.JOURNAL).exists()
    assert "superseded" not in json.loads(
        (space / "reports/htr" / RUN / "_htr_meta.json").read_text(encoding="utf-8"))


# ── розкласти ────────────────────────────────────────────────────────────────

def test_rozkladeno_kozhna_sprava_maie_svoie(space: Path, zbirka: Path) -> None:
    from nyshporka.cases import chain as C
    from nyshporka.cases import span as SP
    from nyshporka.pagestore import store as PS
    from nyshporka.share import suggest as SG

    got = SPL.split(zbirka, MAP)

    # кадри: жорсткі посилання під тими самими іменами, стара тека ціла
    p927 = space / "data/raw/rgia_592/op25-spr-927"
    assert sorted(f.name for f in p927.glob("*.jpg")) == ["0004.jpg", "0005.jpg"]
    assert os.path.samefile(p927 / "0004.jpg", zbirka / "0004.jpg")
    assert len(list(zbirka.glob("*.jpg"))) == 8
    assert not (space / "data/raw/rgia_592/spr--").exists(), "кадр поза справами став справою"

    # паспорт частини несе шифру й походження, без діапазону
    side = json.loads((p927 / "_source.json").read_text(encoding="utf-8"))
    assert side["shifra"] == "РДІА 592-25-927" and "spr_to" not in side
    assert side["split_from"] == {"dir": f"data/raw/{OLD}", "first": "0004.jpg",
                                  "last": "0005.jpg", "frames": 2, "from": 4, "to": 5}

    # каталог: три справи зі своїми кадрами; стара тека — ні запис, ні «другий ракурс»
    keys = _keys()
    kadry = {k: keys[k]["frames"] for k in ("RGIA/592/25/926", "RGIA/592/25/927", "RGIA/592/25/928")}
    assert kadry == {"RGIA/592/25/926": 3, "RGIA/592/25/927": 2, "RGIA/592/25/928": 2}
    assert keys["RGIA/592/25/926"]["path"] == "data/raw/rgia_592/op25-spr-926"
    assert not any(OLD in " ".join([e.get("path") or "", *(e.get("extra_paths") or [])])
                   for e in keys.values())
    assert C.judge(zbirka).link == C.SPLIT and SP.of_dir(zbirka) is None
    assert C.judge(p927).link not in C.BREAKS

    # прогони: старих у переліку немає, у кожної справи — свій із голосом
    runs = _runs()
    assert RUN not in runs and VOICE not in runs
    assert {n for n in runs} == {"op25-spr-926", "op25-spr-926-diak_v4", "op25-spr-927",
                                 "op25-spr-927-diak_v4", "op25-spr-928", "op25-spr-928-diak_v4"}
    meta = json.loads((space / "reports/htr/op25-spr-927/_htr_meta.json").read_text(
        encoding="utf-8"))
    assert (meta["case_key"], meta["frames_total"], meta["done"]) == ("RGIA/592/25/927", 2, True)
    assert sorted(meta["pages"]) == ["0004.jpg", "0005.jpg"] and meta["failed"] == ["0005.jpg"]
    assert meta["case_dir"] == "data/raw/rgia_592/op25-spr-927"
    assert "stages_total" not in meta and meta["split_from"]["run"] == RUN
    assert sorted(p.name for p in (space / "reports/htr/op25-spr-927").glob("0*")) == [
        "0004.lines.json", "0004.txt", "0005.lines.json", "0005.txt"]
    voice = json.loads((space / "reports/htr/op25-spr-927-diak_v4/_htr_meta.json").read_text(
        encoding="utf-8"))
    assert voice["done"] == 2, "у теці голосу `done` — число сторінок"
    old = json.loads((space / "reports/htr" / RUN / "_htr_meta.json").read_text(
        encoding="utf-8"))
    assert old["superseded"]["by"] == ["op25-spr-926", "op25-spr-927", "op25-spr-928"]

    # віддача: три справи, жодної «збірної»
    rows = {r["case_key"]: r["status"] for r in SG.nepodileni()}
    assert set(rows) == {"RGIA/592/25/926", "RGIA/592/25/927", "RGIA/592/25/928"}
    assert SG.ZBIRNA not in rows.values()

    # сховище сторінок: нотатки — у файлах своїх справ
    def _notes(shifra: str) -> list[str]:
        cf = PS.load_case(PS.resolve_case(shifra))
        return sorted(cf.pages) if cf else []

    assert _notes("RGIA 592-25-926") == ["0002.jpg", "0008.jpg"]
    assert _notes("RGIA 592-25-927") == ["0004.jpg"]
    assert _notes("RGIA 592-25-928") == ["0006.jpg"]
    assert got["notes_moved"] == 2

    journal = json.loads((zbirka / SPL.JOURNAL).read_text(encoding="utf-8"))
    assert journal["state"] == "done"


def test_tekstovyi_stor_ne_daie_khit_dvichi(space: Path, zbirka: Path) -> None:
    from nyshporka.search import store as ST

    list(ST.ensure_all([RUN, VOICE], force=True))
    SPL.split(zbirka, MAP)

    conn = ST.connect(readonly=True)
    try:
        names = set(ST.runs_named(conn))
    finally:
        conn.close()
    assert RUN not in names and VOICE not in names
    assert {"op25-spr-926", "op25-spr-927", "op25-spr-928"} <= names


def test_druha_rozbyvka_vidmovliaie(space: Path, zbirka: Path) -> None:
    SPL.split(zbirka, MAP)

    with pytest.raises(SPL.SplitError, match="вже розкладено"):
        SPL.split(zbirka, MAP)


# ── обрив ────────────────────────────────────────────────────────────────────

def test_obirvana_rozbyvka_dorobliaietsia_tiieiu_samoiu_kartoiu(
        space: Path, zbirka: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(pl: Any) -> int:
        raise OSError("диск зник")

    real = SPL._move_notes
    monkeypatch.setattr(SPL, "_move_notes", _boom)
    with pytest.raises(OSError):
        SPL.split(zbirka, MAP)
    assert json.loads((zbirka / SPL.JOURNAL).read_text(encoding="utf-8"))["state"] == "doing"
    assert RUN in _runs(), "старий прогін знято до того, як розбивку доведено до кінця"

    insha = [("926", "0001.jpg", "0004.jpg"), ("927", "0005.jpg", "0008.jpg")]
    with pytest.raises(SPL.SplitError, match="ІНШОЮ картою"):
        SPL.split(zbirka, insha)

    monkeypatch.setattr(SPL, "_move_notes", real)
    SPL.split(zbirka, MAP)

    assert json.loads((zbirka / SPL.JOURNAL).read_text(encoding="utf-8"))["state"] == "done"
    assert RUN not in _runs() and "op25-spr-928" in _runs()


def test_obryv_pislia_poznachky_ne_hubyt_prohoniv(
        space: Path, zbirka: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Обрив після того, як старий прогін позначено заміщеним: перелік
    прогонів його вже не показує, і доробка не сміє вирішити, що прогонів не
    було, — інакше `undo` не поверне позначок."""
    def _boom(pl: Any) -> dict[str, Any]:
        raise OSError("диск зник")

    real = SPL._reindex
    monkeypatch.setattr(SPL, "_reindex", _boom)
    with pytest.raises(OSError):
        SPL.split(zbirka, MAP)
    assert RUN not in _runs()

    monkeypatch.setattr(SPL, "_reindex", real)
    SPL.split(zbirka, MAP)

    journal = json.loads((zbirka / SPL.JOURNAL).read_text(encoding="utf-8"))
    assert journal["runs"] == [RUN, VOICE]
    assert journal["parts"][1]["runs"] == {RUN: "op25-spr-927", VOICE: "op25-spr-927-diak_v4"}
    old = json.loads((space / "reports/htr" / RUN / "_htr_meta.json").read_text(
        encoding="utf-8"))
    assert old["superseded"]["by"] == ["op25-spr-926", "op25-spr-927", "op25-spr-928"]
    SPL.undo(zbirka)
    assert set(_runs()) == {RUN, VOICE}


# ── зняти ────────────────────────────────────────────────────────────────────

def test_undo_povertaie_yak_bulo(space: Path, zbirka: Path) -> None:
    from nyshporka.cases import chain as C
    from nyshporka.pagestore import store as PS

    SPL.split(zbirka, MAP)

    got = SPL.undo(zbirka)

    assert not got["kept"], got["kept"]
    assert sorted(got["runs_removed"]) == ["op25-spr-926", "op25-spr-926-diak_v4", "op25-spr-927",
                                           "op25-spr-927-diak_v4", "op25-spr-928", "op25-spr-928-diak_v4"]
    for spr in ("926", "927", "928"):
        assert not (space / f"data/raw/rgia_592/spr-{spr}").exists()
    assert len(list(zbirka.glob("*.jpg"))) == 8, "undo зачепив кадри старої теки"
    assert not (zbirka / SPL.JOURNAL).exists()
    side = json.loads((zbirka / "_source.json").read_text(encoding="utf-8"))
    assert "split_into" not in side and side["spr_to"] == "929"
    assert C.judge(zbirka).link == C.BUNDLE_FOLDER
    assert set(_runs()) == {RUN, VOICE}
    assert list(_keys()) == ["RGIA/592/25/926"]
    cf = PS.load_case(PS.resolve_case("RGIA 592-25-926"))
    assert sorted(cf.pages) == ["0002.jpg", "0004.jpg", "0006.jpg", "0008.jpg"]


def test_undo_ne_chipaie_zminenoho_pislia_rozbyvky(space: Path, zbirka: Path) -> None:
    SPL.split(zbirka, MAP)
    pravka = space / "reports/htr/op25-spr-927/0004.txt"
    pravka.write_text("виправлено оком\n", encoding="utf-8")
    chuzhe = space / "data/raw/rgia_592/op25-spr-928/notatka.txt"
    chuzhe.write_text("моє", encoding="utf-8")

    got = SPL.undo(zbirka)

    assert pravka.read_text(encoding="utf-8") == "виправлено оком\n"
    assert chuzhe.exists()
    assert len(got["kept"]) == 2 and "op25-spr-927" not in got["runs_removed"]


# ── відмови ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("karta", "why"), [
    ([("926", "0001.jpg", "0003.jpg"), ("927", "0003.jpg", "0008.jpg")], "у дві частини"),
    ([("926", "0001.jpg", "0003.jpg"), ("927", "0005.jpg", "0008.jpg")], "не покриває 1 кадрів"),
    ([("926", "0001.jpg", "0003.jpg"), ("927", "0004.jpg", "0009.jpg")], "у теці немає"),
    ([("926", "0005.jpg", "0003.jpg"), ("927", "0006.jpg", "0008.jpg")], "стоїть після"),
    ([("926", "0001.jpg", "0008.jpg")], "менше двох справ"),
    ([("926", "0001.jpg", "0003.jpg"), ("926", "0004.jpg", "0008.jpg")], "названо двічі"),
    ([], "карти немає"),
])
def test_vidmovy_karty(space: Path, zbirka: Path, karta: list[Any], why: str) -> None:
    with pytest.raises(SPL.SplitError, match=why):
        SPL.plan(zbirka, karta)
    assert not (zbirka / SPL.JOURNAL).exists()


def test_mezhu_kadru_ne_zsuvaie(space: Path, zbirka: Path) -> None:
    """«Від..до» включно: останній названий кадр — ще цієї справи."""
    pl = SPL.plan(zbirka, MAP)

    assert pl.parts[0].names == ["0001.jpg", "0002.jpg", "0003.jpg"]
    assert pl.parts[1].names[0] == "0004.jpg"


def test_chuzhu_teku_ne_zaimaie(space: Path, zbirka: Path) -> None:
    frames(space, "rgia_592/spr-927", 2)

    with pytest.raises(SPL.SplitError, match="уже існує й містить інше"):
        SPL.plan(zbirka, MAP)


def test_nomer_bez_shyfry_pasporta_vidmovliaie(space: Path) -> None:
    d = frames(space, "rgia_592/RGIA_592_25_10_11", 4)

    with pytest.raises(SPL.SplitError, match="Назвіть шифру повністю"):
        SPL.plan(d, [("10", "0001.jpg", "0002.jpg"), ("11", "0003.jpg", "0004.jpg")])
    pl = SPL.plan(d, [("РДІА 592-25-10", "0001.jpg", "0002.jpg"),
                      ("РДІА 592-25-11", "0003.jpg", "0004.jpg")])
    assert [p.key for p in pl.parts] == ["RGIA/592/25/10", "RGIA/592/25/11"]


def test_inshyi_tom_bez_copy_vidmovliaie(space: Path, zbirka: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_link(src: Any, dst: Any) -> None:
        raise OSError(17, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", _no_link)

    with pytest.raises(SPL.SplitError, match="--copy"):
        SPL.split(zbirka, MAP)
    SPL.undo(zbirka)

    SPL.split(zbirka, MAP, copy=True)
    kopiia = space / "data/raw/rgia_592/op25-spr-927/0004.jpg"
    assert kopiia.read_bytes() == (zbirka / "0004.jpg").read_bytes()
    assert not os.path.samefile(kopiia, zbirka / "0004.jpg")


def test_karta_z_faila(space: Path, zbirka: Path) -> None:
    f = space / "karta.json"
    f.write_text(json.dumps([{"spr": w, "first": a, "last": b} for w, a, b in MAP]),
                 encoding="utf-8")

    assert SPL.load_map(f) == MAP
    assert SPL.parse_part("926 = 0001.jpg .. 0003.jpg") == MAP[0]
    with pytest.raises(SPL.SplitError, match="чекаю"):
        SPL.parse_part("926:0001-0003")
