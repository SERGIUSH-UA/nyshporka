"""🗜 Геометрія рядків стиснутою: доступник і `nysh disk compact`.

Ідея №11 порталу (30.10.2026): рамки й полігони, записані текстом JSON, — найбільша
частина простору. Тут перевіряється, що стиснута й проста форми читаються однаково,
що compact не втрачає рамок за жодного обриву й що стор тексту від нього не
перечитує корпус.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from nyshporka.htr import layout as HL

GEO = {"size": [1200, 1800], "boxes": [[10, 20, 300, 40], [10, 50, 300, 70]],
       "polys": [[[10, 20], [300, 20], [300, 40], [10, 40]],
                 [[10, 50], [300, 50], [300, 70], [10, 70]]]}
OLD = time.time() - 3600


def _plain(d: Path, stem: str, geo: dict[str, Any] = GEO, age: float = OLD) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{stem}.lines.json"
    f.write_text(json.dumps(geo), encoding="utf-8")
    os.utime(f, (age, age))
    return f


# ── доступник ────────────────────────────────────────────────────────────────

def test_both_forms_read_the_same(tmp_path: Path) -> None:
    _plain(tmp_path / "a", "0001")
    (tmp_path / "b").mkdir()
    HL.write_geometry(tmp_path / "b", "0001", GEO)
    assert HL.load_geometry(tmp_path / "a", "0001") == GEO
    assert HL.load_geometry(tmp_path / "b", "0001") == GEO
    assert (tmp_path / "b" / "0001.lines.json.gz").is_file()
    assert HL.geometry_stems(tmp_path / "a") == HL.geometry_stems(tmp_path / "b") == {"0001"}


def test_writer_replaces_the_plain_copy(tmp_path: Path) -> None:
    """Перечитана сторінка старого прогону не лишає двох різних правд."""
    _plain(tmp_path, "0001", {"boxes": [[0, 0, 1, 1]]})
    HL.write_geometry(tmp_path, "0001", GEO)
    assert not (tmp_path / "0001.lines.json").exists()
    assert HL.load_geometry(tmp_path, "0001") == GEO


def test_gz_wins_when_both_lie_side_by_side(tmp_path: Path) -> None:
    _plain(tmp_path, "0001", {"boxes": [[0, 0, 1, 1]]})
    (tmp_path / "0001.lines.json.gz").write_bytes(HL.gz_blob(json.dumps(GEO).encode()))
    assert HL.geometry_path(tmp_path, "0001").name.endswith(".gz")
    assert HL.load_geometry(tmp_path, "0001") == GEO


def test_broken_gz_is_an_error_not_emptiness(tmp_path: Path) -> None:
    f = tmp_path / "0001.lines.json.gz"
    f.write_bytes(b"\x1f\x8b not really")
    with pytest.raises(ValueError):
        HL.read_geometry(f)
    assert HL.load_geometry(tmp_path, "0001") is None


def test_voice_branch_resolves_compressed_parent(tmp_path: Path) -> None:
    main, voice = tmp_path / "spr-1", tmp_path / "spr-1-diak_v4"
    for d in (main, voice):
        d.mkdir()
        (d / "0001.txt").write_text("а\nб\n", encoding="utf-8")
    HL.write_geometry(main, "0001", GEO)
    path, why = HL.resolve_geometry(voice, "0001")
    assert path == main / "0001.lines.json.gz", why
    assert HL.pages_with_geometry(voice) == ["0001"]


# ── compact ──────────────────────────────────────────────────────────────────

def test_compact_file_keeps_bytes_and_time(tmp_path: Path) -> None:
    from nyshporka.disk import compact as C

    f = _plain(tmp_path, "0001")
    raw, mtime = f.read_bytes(), f.stat().st_mtime_ns
    was, now = C.compact_file(f)
    gz = tmp_path / "0001.lines.json.gz"
    assert not f.exists() and gz.is_file()
    assert gzip.decompress(gz.read_bytes()) == raw, "вміст мусить бути той самий байт у байт"
    assert gz.stat().st_mtime_ns == mtime
    assert (was, now) == (len(raw), gz.stat().st_size) and now < was


def test_compact_finishes_an_interrupted_pair(tmp_path: Path) -> None:
    """Обрив між заміною й видаленням: повтор звіряє пару й доприбирає простий."""
    from nyshporka.disk import compact as C

    f = _plain(tmp_path, "0001")
    (tmp_path / "0001.lines.json.gz").write_bytes(HL.gz_blob(f.read_bytes()))
    C.compact_file(f)
    assert not f.exists()
    assert HL.load_geometry(tmp_path, "0001") == GEO


def test_compact_refuses_a_pair_that_disagrees(tmp_path: Path) -> None:
    from nyshporka.disk import compact as C

    f = _plain(tmp_path, "0001")
    (tmp_path / "0001.lines.json.gz").write_bytes(HL.gz_blob(b'{"boxes": []}'))
    with pytest.raises(ValueError):
        C.compact_file(f)
    assert f.is_file(), "простий файл лишається, коли пара розходиться"


def test_compact_keeps_the_plain_file_when_verification_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Стиснуте, що не розтискається в той самий вміст, не замінює оригіналу."""
    from nyshporka.disk import compact as C

    f = _plain(tmp_path, "0001")
    monkeypatch.setattr(C.HL, "gz_blob", lambda raw: gzip.compress(raw + b" "))
    with pytest.raises(ValueError):
        C.compact_file(f)
    assert f.is_file()
    assert not list(tmp_path.glob("*.gz")) and not list(tmp_path.glob("*.tmp"))


def test_compact_run_skips_a_folder_still_being_written(tmp_path: Path) -> None:
    from nyshporka.disk import compact as C

    _plain(tmp_path, "0001")
    _plain(tmp_path, "0002", age=time.time())
    res = C.compact_run(tmp_path, apply=True)
    assert res.skipped and res.done == 0
    assert (tmp_path / "0001.lines.json").is_file()


def test_compact_run_restores_folder_time(tmp_path: Path) -> None:
    from nyshporka.disk import compact as C

    run = tmp_path / "run"
    _plain(run, "0001")
    _plain(run, "0002")
    os.utime(run, (OLD, OLD))
    before = run.stat().st_mtime_ns
    res = C.compact_run(run, apply=True)
    assert res.done == 2 and not res.errors
    assert run.stat().st_mtime_ns == before


# ── простір: стор не перечитує, живі прогони не чіпаються ─────────────────────

@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka import disk as D
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W
    from nyshporka.htr import runs as R

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    for i, stem in enumerate(("0001", "0002")):
        (run / f"{stem}.txt").write_text("перший рядок\nдругий рядок\n", encoding="utf-8")
        _plain(run, stem, {**GEO, "boxes": [[0, 10 * i, 100, 10 * i + 9], [0, 50, 100, 59]]})
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic", "case_key": "DAHMO/1/1/1",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2}}}), encoding="utf-8")
    for f in run.iterdir():
        os.utime(f, (OLD, OLD))
    os.utime(run, (OLD, OLD))
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    monkeypatch.setattr(D, "_live_runs", lambda: [])
    monkeypatch.setattr(R, "alive", lambda: [])
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield run
    W.reset()


def test_compact_does_not_make_the_store_reread(space: Path) -> None:
    """🔴 5,3 млн сторінок у сторі Майстерні: compact не має їх перечитувати."""
    from nyshporka.disk import compact as C
    from nyshporka.search import store as ST

    assert list(ST.ensure_all(["проба"])) == ["проба"]
    rep = C.compact(apply=True).as_json()
    assert rep["done"] == 2 and not rep["errors"], rep
    assert not list(space.glob("*.lines.json"))
    conn = ST.connect()
    try:
        assert ST.index_run_if_stale(conn, "проба") is None, "стор перечитав прогін"
    finally:
        conn.close()


def test_compacted_files_keep_text_unchanged_when_the_stamp_moves(space: Path) -> None:
    """Друга лінія: штамп таки змінився (мету переписали) — стор бачить «текст той
    самий» за часом файлів, бо `.gz` несе час оригіналу."""
    from nyshporka.disk import compact as C
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    assert C.compact(apply=True).as_json()["done"] == 2
    meta = space / "_htr_meta.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["project"] = "інший"
    meta.write_text(json.dumps(data), encoding="utf-8")
    os.utime(meta, (OLD, OLD))
    conn = ST.connect()
    try:
        assert ST.index_run_if_stale(conn, "проба") is None, "стор перечитав прогін"
    finally:
        conn.close()


def test_compact_dry_run_touches_nothing(space: Path) -> None:
    from nyshporka.disk import compact as C

    rep = C.compact().as_json()
    assert rep["files"] == 2 and rep["done"] == 0 and rep["ratio"]
    assert rep["after"] < rep["before"]
    assert len(list(space.glob("*.lines.json"))) == 2


def test_compact_skips_a_case_read_right_now(space: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.disk import compact as C
    from nyshporka.htr import runs as R

    monkeypatch.setattr(R, "alive", lambda: [R.Live(pid=1, created=0.0, case="",
                                                    case_key="DAHMO/1/1/1", shard="",
                                                    since=0.0)])
    rep = C.compact(apply=True).as_json()
    assert rep["done"] == 0 and rep["skipped"], rep
    assert len(list(space.glob("*.lines.json"))) == 2


def test_compact_refuses_when_cloud_state_is_unknown(space: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import disk as D
    from nyshporka.disk import compact as C

    monkeypatch.setattr(D, "_live_runs", lambda: None)
    with pytest.raises(C.CompactError):
        C.compact(apply=True)
    assert len(list(space.glob("*.lines.json"))) == 2


def test_compact_in_processes_matches_one_by_one(space: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """`workers` розводить теки по процесах: той самий підсумок, живу теку не чіпає,
    стор не перечитує, звіт у порядку переліку."""
    import shutil

    from nyshporka import htr_store as S
    from nyshporka.disk import compact as C
    from nyshporka.htr import runs as R
    from nyshporka.search import store as ST

    for n in ("проба2", "проба3", "жива"):
        dst = space.parent / n
        shutil.copytree(space, dst)
        if n == "жива":
            meta = dst / "_htr_meta.json"
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["case_key"] = "DAHMO/2/2/2"
            meta.write_text(json.dumps(data), encoding="utf-8")
        for f in dst.iterdir():
            os.utime(f, (OLD, OLD))
        os.utime(dst, (OLD, OLD))
    S._CACHE.clear()
    S._RUNS_CACHE = None
    monkeypatch.setattr(R, "alive", lambda: [R.Live(pid=1, created=0.0, case="",
                                                    case_key="DAHMO/2/2/2", shard="",
                                                    since=0.0)])
    list(ST.ensure_all(["проба", "проба2", "проба3"]))
    rep = C.compact(apply=True, workers=2).as_json()
    assert rep["done"] == 6 and not rep["errors"], rep
    assert [s["run"] for s in rep["skipped"]] == ["жива"]
    assert len(list((space.parent / "жива").glob("*.lines.json"))) == 2
    for n in ("проба", "проба2", "проба3"):
        assert not list((space.parent / n).glob("*.lines.json"))
        assert len(list((space.parent / n).glob("*.lines.json.gz"))) == 2
    conn = ST.connect()
    try:
        for n in ("проба", "проба2", "проба3"):
            assert ST.index_run_if_stale(conn, n) is None, f"стор перечитав {n}"
    finally:
        conn.close()
