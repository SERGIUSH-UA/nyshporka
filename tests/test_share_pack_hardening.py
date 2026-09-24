"""Що їде в пакет: лише прочитання справи, без нотаток дослідження.

Вади, знайдені рев'ю 24.09.2026 на справжніх пакетах живого простору: у
пакет їхали вимірювальні й пробні прогони з нотатками з мети, а назва справи
несла робочі позначки паспорта. Плюс картка, яку задає людина чи агент.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from _share import make_run

from nyshporka.share import bundle, opys


@pytest.fixture
def space(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield tmp_path / "ws"
    W.reset()


def _root(space: Path) -> Path:
    d = space / "reports" / "htr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta(d: Path, **extra: Any) -> None:
    p = d / bundle.META_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    m.update(extra)
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


def _keep_only(d: Path, names: list[str]) -> None:
    for f in d.glob("*.txt"):
        if f.name not in names:
            f.unlink()


# ── A2: які прогони — голоси пакета ─────────────────────────────────────────

def test_zamir_ne_ide(space: Path) -> None:
    from nyshporka.share.publish import choose_voices

    root = _root(space)
    main = make_run(root, "230-1-130", pages=5)
    zamir = make_run(root, "230-1-130-skryba_v6", pages=5, model="skryba_f792_v6.mlmodel")
    _meta(zamir, control_run=True, control_why="Прогін зроблено ЯК ВИМІР")
    got, skipped = choose_voices([main, zamir], "DAHMO/315/8433")
    assert got == [main]
    assert skipped[0]["run"] == zamir.name and "вимір" in skipped[0]["why"]


def test_proba_tiieyi_zh_modeli_ne_ide_a_chastyny_idut(space: Path) -> None:
    from nyshporka.share.publish import choose_voices

    root = _root(space)
    full = make_run(root, "a-full", pages=10, model="skryba.mlmodel")
    proba = make_run(root, "a-probe", pages=10, model="skryba.mlmodel")
    _keep_only(proba, ["0002.txt", "0003.txt"])
    part_b = make_run(root, "b-part", pages=10, model="pysar.pt")
    part_a = make_run(root, "a-part", pages=10, model="pysar.pt")
    _keep_only(part_a, [f"{i:04d}.txt" for i in range(1, 6)])
    _keep_only(part_b, [f"{i:04d}.txt" for i in range(6, 11)])

    got, skipped = choose_voices([full, proba, part_a, part_b], "DAHMO/315/8433")
    assert set(got) == {full, part_a, part_b}
    assert [s["run"] for s in skipped] == ["a-probe"]


def test_prohin_inshoi_spravy_i_chuzhyi_ne_idut(space: Path) -> None:
    from nyshporka.share.publish import choose_voices

    root = _root(space)
    main = make_run(root, "010241")
    other = make_run(root, "010241-01-00886", case_key="DAHMO/315/886")
    shared = make_run(root, "010241-diak")
    _meta(shared, shared={"from": "oksana"})
    got, skipped = choose_voices([main, other, shared], "DAHMO/315/8433")
    assert got == [main]
    assert {s["run"] for s in skipped} == {other.name, shared.name}


def test_skip_run_vid_liudyny(space: Path) -> None:
    from nyshporka.share.publish import choose_voices

    root = _root(space)
    a = make_run(root, "r1")
    b = make_run(root, "r2", model="diak.mlmodel")
    got, skipped = choose_voices([a, b], "", skip=["r2"])
    assert got == [a] and skipped[0]["run"] == "r2"


def test_meta_bilym_spyskom() -> None:
    raw = {"model": "m", "engine": "kraken", "case_dir_note": "з боксу", "_note": "x",
           "control_why": "вимір", "merged_from": ["a"], "rescued": {"1": "догін"},
           "orphan_note": "y", "case_key_note": "z",
           "pages": {"0001.jpg": {"lines": 2, "conf": 0.9, "rss_mb": 1677,
                                  "vram_peak_mb": 2376}}}
    got = bundle.clean_meta(raw)
    assert set(got) == {"model", "engine", "pages"}
    assert got["pages"]["0001.jpg"] == {"lines": 2, "conf": 0.9}


def test_znamennyk_chastyn_i_dvokh_modelei() -> None:
    """Частини однієї моделі — сумою сторінок, дві моделі — не подвоюються."""
    pa = {f"{i:04d}.txt": "рядок\n" for i in range(1, 6)}
    pb = {f"{i:04d}.txt": "рядок\n" for i in range(6, 11)}
    full = {f"{i:04d}.txt": "рядок\n" for i in range(1, 11)}
    got = bundle.tally({"a": pa, "b": pb, "d": full},
                       {"a": "pysar", "b": "pysar", "d": "diak"})
    assert got["pages"] == 10


def test_pakuvannia_nese_vidkynuti_prohony(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import publish as PUB

    root = _root(space)
    make_run(root, "spr-8433", pages=3)
    zamir = make_run(root, "spr-8433-skryba", pages=3, model="skryba.mlmodel")
    _meta(zamir, control_run=True)
    monkeypatch.setattr("nyshporka.htr_store.runs_for_scope", lambda scope: {
        "rows": [{"name": "spr-8433"}], "kind": "case", "key": "DAHMO/315/8433",
        "shifra": "ДАХмО 315-1-8433"})
    monkeypatch.setattr("nyshporka.cloud.verify.voice_dirs", lambda d: [zamir])

    got = PUB.pack("DAHMO/315/8433", geometry=False)
    assert got["runs"] == ["spr-8433"]
    assert got["skipped_runs"][0]["run"] == "spr-8433-skryba"
    with tarfile.open(got["path"]) as tar:
        assert not [n for n in tar.getnames() if "skryba" in n]
        meta = json.loads(tar.extractfile(f"runs/spr-8433/{bundle.META_NAME}").read())  # type: ignore[union-attr]
    assert "case_dir" not in meta


# ── A3: назва й жанр без нотаток ────────────────────────────────────────────

@pytest.mark.parametrize("raw, want", [
    ("Метрична книга Н+Ш+С (титулка звірена 2026-07-09)", "Метрична книга Н+Ш+С"),
    ("Метрична книга с. Вербівка, 1890-1891. FS-тег: Religious Death Records, verbivka.",
     "Метрична книга с. Вербівка, 1890-1891"),
    ("Судова справа, 1895-1896; FS-місце: Verbivka, Podolia.",
     "Судова справа, 1895-1896"),
    ("Позов про 120 руб. (звірено по сканах 2026-07-20)", "Позов про 120 руб."),
    ("Купча, на десяти півлистах. ⚠ У справі є документ від 1864 р.",
     "Купча, на десяти півлистах"),
    ("Справа **Петренка А.** про борг", "Справа Петренка А. про борг"),
    ("Переселення: наряд 1-ї черги 1929 р. по Вербівці",
     "Переселення: наряд 1-ї черги 1929 р. по Вербівці"),
])
def test_nazva_bez_notatok(raw: str, want: str) -> None:
    assert opys.title(raw, None) == want


def test_zhanr_pasporta_chystytsia() -> None:
    got = opys.sidecar_extras({"record_type": "Метрична книга Н+Ш+С (титулка звірена "
                                              "2026-07-09) — м. Слобідка"})
    assert "звірена" not in got["record_type"]


# ── H: картка від людини чи агента ──────────────────────────────────────────

def test_kartka_z_pakuvannia_zapamiatovuietsia(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import card as K
    from nyshporka.share import publish as PUB

    run = make_run(_root(space), "spr-8433")
    monkeypatch.setattr(PUB, "resolve_runs", lambda scope, **kw: (
        [run], {"key": "DAHMO/315/8433", "shifra": "ДАХмО 315-1-8433"}))
    fields = K.normalize(title="Сповідні розписи Слобідки", years="1795-1797",
                         places=["Слобідка"], doc_type="confession")

    got = PUB.pack("DAHMO/315/8433", geometry=False, card_fields=fields)
    case = got["manifest"]["case"]
    assert case["title"] == "Сповідні розписи Слобідки"
    assert case["years"] == [1795, 1797] and case["doc_type"] == "confession"

    again = PUB.pack("DAHMO/315/8433", geometry=False)
    assert again["manifest"]["case"]["title"] == "Сповідні розписи Слобідки", \
        "наступне пакування мусить узяти ту саму картку"


def test_kartka_dry_run_ne_pyshe(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import card as K
    from nyshporka.share import publish as PUB

    run = make_run(_root(space), "spr-8433")
    monkeypatch.setattr(PUB, "resolve_runs", lambda scope, **kw: (
        [run], {"key": "DAHMO/315/8433", "shifra": "ДАХмО 315-1-8433"}))
    PUB.pack("DAHMO/315/8433", dry_run=True, card_fields={"title": "Проба"})
    assert K.get("DAHMO/315/8433") == {}


@pytest.mark.parametrize("kw, match", [
    ({"years": "сімнадцяте"}, "роки"), ({"years": "1200"}, "межами"),
    ({"title": "x" * 400}, "довша"), ({"title": "Справа [[Осип]]"}, "дерева"),
    ({"doc_type": "невідоме"}, "невідомий"),
])
def test_kartka_perevirka(kw: dict[str, Any], match: str) -> None:
    from nyshporka.share import card as K

    with pytest.raises(K.CardError, match=match):
        K.normalize(**kw)


def test_zhanr_pidpysom_a_ne_kodom() -> None:
    from nyshporka.share import card as K

    if not K.genres():
        pytest.skip("довідника жанрів немає")
    assert K.normalize(doc_type="сповідні")["doc_type"] == "confession"


def test_kartka_operatsiieiu(space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("share.card", {"case": "DAHMO/315/8433", "title": "Назва",
                                "place": ["Слобідка", "Вербівка"]})
    assert env.ok, env.error
    assert env.data["card"]["places"] == ["Слобідка", "Вербівка"]
    env = O.call("share.card", {"case": "DAHMO/315/8433", "title": ""})
    assert "title" not in env.data["card"]
    env = O.call("share.card", {"case": "DAHMO/315/8433", "clear": True})
    assert env.data["card"] == {}


# ── C14: застарілий geom-файл ────────────────────────────────────────────────

def test_bez_heometrii_staryi_geom_prybyraietsia(space: Path, monkeypatch: Any) -> None:
    from nyshporka.share import publish as PUB

    run = make_run(_root(space), "spr-8433", geometry=True)
    monkeypatch.setattr(PUB, "resolve_runs", lambda scope, **kw: (
        [run], {"key": "", "shifra": "ДАХмО 315-1-8433"}))
    z = PUB.pack("ДАХмО 315-1-8433", geometry=True)
    geom = Path(z["geom"]["path"])
    assert geom.is_file()
    PUB.pack("ДАХмО 315-1-8433", geometry=False)
    assert not geom.exists(), "рамки старого пакування поїхали б до нового тексту"


def test_geom_inshoho_tekstu_ne_zalyvaietsia(space: Path, tmp_path: Path) -> None:
    from _share import manifest_for

    from nyshporka.share import upload

    run = make_run(_root(space), "spr-8433", geometry=True)
    text = tmp_path / "p.nyshtext"
    m = manifest_for([bundle.voice_of(run)])
    m.decode["content_sha256"] = "a" * 64
    bundle.write(text, m, [run])
    m.decode["content_sha256"] = "b" * 64
    bundle.write(bundle.geom_path(text), m, [run], patterns=bundle.PACKED_GEOM)
    assert not upload._geom_fresh(text, bundle.geom_path(text))
