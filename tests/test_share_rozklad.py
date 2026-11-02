"""Плівка розкладається на справи за картою сервера, на справжньому просторі."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _cherha import drop_space, make_space

from nyshporka.share.zabir import PROVENANS

DGS = "004810401"


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    yield tmp_path
    drop_space()


def _sprava(shifr: str, vid: int, do: int, **kw: Any) -> dict[str, Any]:
    return {"shifr": shifr, "vid": vid, "do": do, "kadriv": do - vid + 1, "povna": True,
            "rik_vid": "1751", "rik_do": "1752", "misce": "Київ", "nazva": "Метрика", "arkhiv": "", **kw}


def _teka(space: Path, spravy: list[dict[str, Any]], kadriv: int = 10) -> Path:
    d = space / "zabir" / "v1"
    d.mkdir(parents=True)
    for i in range(1, kadriv + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"\xff\xd8kadr" + bytes([i]))
    (d / PROVENANS).write_text(json.dumps({"vyklyk": 1, "pasport": {
        "source": "джерело", "dgs": DGS, "url": "https://x/y", "film_frames": kadriv,
        "spravy": spravy}}, ensure_ascii=False), encoding="utf-8")
    return d


def _rozklasty(d: Path, arkhiv: str = "ЦДІАК", **kw: Any) -> dict[str, Any]:
    from nyshporka.share import rozklad

    return rozklad.rozklasty(d, arkhiv, **kw)


def test_two_cases_and_a_cover_land_in_their_own_folders(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 2, 5), _sprava("224-1-62", 6, 9)])
    z = _rozklasty(d)
    assert z["stan"] == "rozkladeno", z
    assert [s["shifra"] for s in z["spravy"]] == ["ЦДІАК 224-1-61", "ЦДІАК 224-1-62"]
    teka = space / z["spravy"][0]["teka"]
    assert sorted(p.name for p in teka.glob("*.jpg")) == ["0002.jpg", "0003.jpg", "0004.jpg", "0005.jpg"]
    meta = json.loads((teka / "_source.json").read_text(encoding="utf-8"))
    assert meta["shifra"] == "ЦДІАК 224-1-61" and meta["dgs"] == DGS
    assert meta["fetched_url"] == "https://x/y" and str(meta["year_from"]) == "1751"


def test_undo_takes_it_all_back(space: Path) -> None:
    from nyshporka.cases import split as SPL

    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    z = _rozklasty(d)
    teka = space / z["spravy"][0]["teka"]
    SPL.undo(d)
    assert not list(teka.glob("*.jpg")) if teka.exists() else True
    assert len(list(d.glob("*.jpg"))) == 10


def test_relative_folder_counts_from_where_the_person_stands(
    space: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Живий прогін 02.11: `--do zb/s2` шукався від простору, і розкладка зривалась."""
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    monkeypatch.chdir(d.parent)
    from nyshporka.share import rozklad

    assert rozklad.rozklasty(Path(d.name), "ЦДІАК")["stan"] == "rozkladeno"


def test_order_on_the_film_decides_not_the_case_number(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-64", 6, 10), _sprava("224-1-65", 1, 5)])
    z = _rozklasty(d)
    assert [(s["shifra"], s["kadriv"]) for s in z["spravy"]] == [("ЦДІАК 224-1-65", 5), ("ЦДІАК 224-1-64", 5)]


@pytest.mark.parametrize(("ref", "shifr"), [
    ("246-1-122_1851", "246-1-122"), ("246-1-123_1850-1852", "246-1-123"), ("2_8_2453", "2-8-2453"),
    ("132-1- 4018", "132-1-4018"), ("5593-2-1108_1895", "5593-2-1108"), ("224-1-53", "224-1-53"),
])
def test_reference_forms_of_the_source(ref: str, shifr: str) -> None:
    from nyshporka.share import rozklad

    assert rozklad.shifr_iz_dzherela(ref) == shifr


def test_year_suffix_stays_out_of_the_reference(space: Path) -> None:
    d = _teka(space, [_sprava("246-1-122_1851", 1, 5), _sprava("246-1-123_1850-1852", 6, 10)])
    assert [s["shifra"] for s in _rozklasty(d)["spravy"]] == ["ЦДІАК 246-1-122", "ЦДІАК 246-1-123"]


def test_one_case_on_the_whole_film_describes_the_folder(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 10)])
    z = _rozklasty(d)
    assert z["stan"] == "odna" and z["spravy"][0]["shifra"] == "ЦДІАК 224-1-61"
    tsil = Path(z["spravy"][0]["teka"])
    assert tsil != d and len(list(tsil.glob("*.jpg"))) == 10
    meta = json.loads((tsil / "_source.json").read_text(encoding="utf-8"))
    assert meta["shifra"] == "ЦДІАК 224-1-61" and meta["dgs"] == DGS
    assert meta["fetched_url"] == "https://x/y"


def test_case_split_between_films_is_not_mixed(space: Path) -> None:
    from nyshporka.share import rozklad

    d = _teka(space, [_sprava("224-1-61", 1, 10)])
    assert _rozklasty(d)["stan"] == "odna"
    druha = space / "zabir" / "v2"
    druha.mkdir()
    (druha / "0081.jpg").write_bytes(b"\xff\xd8druha")
    (druha / PROVENANS).write_text(json.dumps({"pasport": {"dgs": "2", "spravy": [
        _sprava("224-1-61", 81, 81)]}}, ensure_ascii=False), encoding="utf-8")
    z = rozklad.rozklasty(druha, "ЦДІАК")
    assert z["stan"] == "odna" and "nysh cases join" in z["prychyna"]
    assert Path(z["spravy"][0]["teka"]) == druha.resolve()


def test_one_case_inside_the_workspace_stays_where_it_is(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 10)])
    u_prostori = space / "data" / "raw" / "zabrane"
    u_prostori.parent.mkdir(parents=True, exist_ok=True)
    d.rename(u_prostori)
    z = _rozklasty(u_prostori)
    assert Path(z["spravy"][0]["teka"]) == u_prostori.resolve()


def test_archive_is_not_guessed(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    z = _rozklasty(d, "")
    assert z["stan"] == "potriben_arkhiv" and z["shyfry"] == ["224-1-61", "224-1-62"]
    assert len(list(d.glob("*.jpg"))) == 10 and not (d / "_source.json").exists()


def test_archive_from_the_source_is_taken_when_the_pack_knows_it(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5, arkhiv="ЦДІАК"), _sprava("224-1-62", 6, 10, arkhiv="ЦДІАК")])
    assert _rozklasty(d, "")["stan"] == "rozkladeno"


@pytest.mark.parametrize("ref", ["Volume 211-2/381 (cont", "f 132-1- 4018 Cyvil Records", "Book 3"])
def test_description_instead_of_a_reference_is_not_parsed(space: Path, ref: str) -> None:
    d = _teka(space, [_sprava(ref, 1, 10)])
    z = _rozklasty(d)
    assert z["stan"] == "ne_mozhna" and "не шифр" in z["prychyna"]
    assert not (d / "_source.json").exists()


def test_unknown_archive_word_is_refused(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    assert _rozklasty(d, "Марсіанський")["stan"] == "ne_mozhna"


def test_missing_frames_keep_the_folder_whole(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    (d / "0007.jpg").unlink()
    z = _rozklasty(d)
    assert z["stan"] == "ne_mozhna" and "0007.jpg" in z["prychyna"]


def test_part_of_a_case_is_not_cut(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5, povna=False), _sprava("224-1-62", 6, 10)])
    assert _rozklasty(d)["stan"] == "ne_mozhna"


def test_no_map_means_nothing_to_do(space: Path) -> None:
    d = _teka(space, [])
    assert _rozklasty(d)["stan"] == "nemaie"
    assert not (d / "_source.json").exists()


def test_second_run_is_quiet(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    assert _rozklasty(d)["stan"] == "rozkladeno"
    assert _rozklasty(d)["stan"] == "vzhe"


def test_odd_server_answer_does_not_raise(space: Path) -> None:
    d = _teka(space, [{"shifr": "224-1-61", "povna": True}, _sprava("224-1-62", 6, 10)])
    assert _rozklasty(d)["stan"] == "ne_mozhna"
    assert len(list(d.glob("*.jpg"))) == 10


def test_dry_run_changes_nothing(space: Path) -> None:
    d = _teka(space, [_sprava("224-1-61", 1, 5), _sprava("224-1-62", 6, 10)])
    z = _rozklasty(d, dry_run=True)
    assert z["stan"] == "plan" and z["spravy"] == ["ЦДІАК 224-1-61", "ЦДІАК 224-1-62"]
    assert not (d / "_source.json").exists()
