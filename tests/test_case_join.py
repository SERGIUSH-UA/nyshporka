"""Справа на двох котушках: `nysh cases join`.

ДАЧкО 931-1-855 (17.10.2026): голова на плівці 007803765, хвіст — на
007803766. Стережеться порядок «голова → хвіст» за наскрізним номером в імені і
те, що зайвий виклик не кладе справу поверх чужих кадрів.
"""
from __future__ import annotations

import json as _json
import os
from pathlib import Path

import pytest
from _cherha import drop_space, make_space

from nyshporka.cases import join as J


def _film(root: Path, name: str, n: int) -> Path:
    d = root / name
    d.mkdir()
    for i in range(1, n + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"\xff\xd8" + name.encode() + bytes([i]) + b"\xff\xd9")
    return d


@pytest.fixture
def films(tmp_path: Path) -> tuple[Path, Path]:
    return _film(tmp_path, "007803765_x", 12), _film(tmp_path, "007803766_x", 6)


def test_join_keeps_head_then_tail(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, tail = films
    got = J.join(tmp_path / "op1-spr-855",
                 [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    names = sorted(p.name for p in (tmp_path / "op1-spr-855").glob("*.jpg"))
    assert names == ["0001_007803765_0009.jpg", "0002_007803765_0010.jpg",
                     "0003_007803765_0011.jpg", "0004_007803765_0012.jpg",
                     "0005_007803766_0002.jpg", "0006_007803766_0003.jpg",
                     "0007_007803766_0004.jpg"]
    assert got["frames"] == 7
    a = (tmp_path / "op1-spr-855" / "0005_007803766_0002.jpg").stat()
    b = (tail / "0002.jpg").stat()
    assert os.path.samestat(a, b)          # жорстке посилання, не копія
    again = J.join(tmp_path / "op1-spr-855",
                   [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    assert again["made"] == 0               # повтор нічого не дублює


def test_join_head_dgs_greater_than_tail(tmp_path: Path) -> None:
    """DGS голови більший за DGS хвоста (007810475 → 007810474): порядок — за --part."""
    head = _film(tmp_path, "007810475_x", 12)
    tail = _film(tmp_path, "007810474_x", 6)
    dest = tmp_path / "op1-spr-889"
    got = J.join(dest, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    names = sorted(p.name for p in dest.glob("*.jpg"))
    assert [n.split("_", 1)[1] for n in names] == [
        "007810475_0009.jpg", "007810475_0010.jpg", "007810475_0011.jpg",
        "007810475_0012.jpg", "007810474_0002.jpg", "007810474_0003.jpg", "007810474_0004.jpg"]
    assert got["first"].startswith("0001_007810475") and got["last"].startswith("0007_007810474")
    # конвеєр читає теку сортуванням імен
    from nyshporka.share import align
    assert [p.name for p in align.frames_sorted(dest)] == names
    again = J.join(dest, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    assert again["made"] == 0


def test_join_legacy_folder_still_completes(films: tuple[Path, Path], tmp_path: Path) -> None:
    """Тека старого зразка `<плівка>_<кадр>` не стає «чужою»: доробляється в тому ж зразку."""
    head, tail = films
    dest = tmp_path / "old"
    dest.mkdir()
    os.link(head / "0009.jpg", dest / "007803765_0009.jpg")
    rows = J.plan(dest, [J.Piece(head, "0009.jpg", "0010.jpg"), J.Piece(tail, "0002.jpg", "0003.jpg")])
    assert [r["dst"] for r in rows] == ["007803765_0009.jpg", "007803765_0010.jpg",
                                         "007803766_0002.jpg", "007803766_0003.jpg"]


def test_join_single_piece_cuts_part_of_film(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, _ = films
    got = J.join(tmp_path / "one", [J.Piece(head, "0009.jpg", "0011.jpg")])
    assert got["frames"] == 3 and got["first"] == "0001_007803765_0009.jpg"


def test_join_refuses_alien_frames(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, tail = films
    d = tmp_path / "busy"
    d.mkdir()
    (d / "0001.jpg").write_bytes(b"\xff\xd8x\xff\xd9")
    with pytest.raises(J.JoinError, match="інші кадри"):
        J.plan(d, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])


def test_join_refuses_missing_file_and_no_pieces(films: tuple[Path, Path],
                                                    tmp_path: Path) -> None:
    head, tail = films
    with pytest.raises(J.JoinError, match="немає"):
        J.plan(tmp_path / "d", [J.Piece(head, "0009.jpg", "0099.jpg"),
                                J.Piece(tail, "0002.jpg", "0004.jpg")])
    with pytest.raises(J.JoinError, match="жодної"):
        J.plan(tmp_path / "d", [])


def test_parse_piece() -> None:
    p = J.parse_piece("data/raw/x/007803765_931=0821.jpg..0973.jpg")
    assert (p.src.name, p.first, p.last) == ("007803765_931", "0821.jpg", "0973.jpg")
    with pytest.raises(J.JoinError):
        J.parse_piece("0821.jpg..0973.jpg")


# ── прочитані плівки з кадрами в бакеті ─────────────────────────────────────
# ЦДІАК 127-1012-535 (29.10.2026): голова на плівці 007800124, хвіст — на
# 007800789; обидві прочитано трьома голосами, кадри лежать архівами R2.


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    yield tmp_path
    drop_space()


def _r2_film(space: Path, dgs: str, n: int, *, shifra: str, run: str) -> Path:
    """Плівка «лише прогнати»: у теці паспорт і маніфест, прогін і голос — у reports."""
    from nyshporka.cases import register as REG

    d = space / "data" / "raw" / "cdiak_127" / f"film-{dgs}"
    d.mkdir(parents=True)
    names = [f"{i:04d}.jpg" for i in range(1, n + 1)]
    (d / "_r2_frames.json").write_text(_json.dumps({
        "frames": [{"name": x, "size": 10, "w": 4, "h": 3, "sha256": dgs + x} for x in names],
        "parts": [{"key": f"cases/{dgs}/part-001.tar", "frames": names[:3], "bytes": 30},
                  {"key": f"cases/{dgs}/part-002.tar", "frames": names[3:], "bytes": 30}],
        "bucket": "test-bucket", "dgs": dgs}), encoding="utf-8")
    (d / "_fs_meta.json").write_text(_json.dumps({Path(x).stem: f"id-{dgs}-{x}" for x in names}),
                                     encoding="utf-8")
    REG.describe(d, shifra=shifra, dgs=dgs)
    for name, voice in ((run, False), (run + "-diak_v10", True)):
        out = space / "reports" / "htr" / name
        out.mkdir(parents=True)
        for x in names:
            (out / f"{Path(x).stem}.txt").write_text(f"{dgs} {x} {'дяк' if voice else 'писар'}\n",
                                                     encoding="utf-8")
            if not voice:
                (out / f"{Path(x).stem}.lines.json").write_text("{}", encoding="utf-8")
        (out / "_htr_meta.json").write_text(_json.dumps({
            "case_dir": str(d), "case_key": "", "frames_total": n,
            "model": "diak_cyr_v10.mlmodel" if voice else "pysar_x18_v1.pt",
            "done": n if voice else True, "stages_total": {"seg": 1.0},
            "failed": [names[-1]], "pages": {x: {"lines": 1} for x in names}}), encoding="utf-8")
    return d


@pytest.fixture
def two(space: Path) -> tuple[Path, Path]:
    from nyshporka.cases import db

    head = _r2_film(space, "007800124", 6, shifra="ЦДІАК 127-1012-529", run="film-007800124")
    tail = _r2_film(space, "007800789", 5, shifra="ЦДІАК 127-1012-538", run="film-007800789")
    db.rebuild(rescan=True)
    return head, tail


def _pieces(head: Path, tail: Path) -> list[J.Piece]:
    return [J.Piece(head, "0005.jpg", "0006.jpg"), J.Piece(tail, "0001.jpg", "0002.jpg")]


def test_r2_plivky_zvodiatsia_z_tekstom(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote

    head, tail = two
    PS.annotate_pages(PS.resolve_case("ЦДІАК 127-1012-538"),
                      [PageNote(scan="0002.jpg", page_type="birth", surnames=["Дідик"])])
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"

    got = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535")

    want = ["0001_007800124_0005.jpg", "0002_007800124_0006.jpg",
            "0003_007800789_0001.jpg", "0004_007800789_0002.jpg"]
    assert not list(dest.glob("*.jpg")), "кадрів на диску не було"
    man = _json.loads((dest / "_r2_frames.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in man["frames"]] == want and man["joined"] is True
    assert man["frames"][2]["src"] == {"film": "007800789", "name": "0001.jpg"}
    assert man["frames"][2]["sha256"] == "0078007890001.jpg"
    assert [(p["key"], p["names_in_archive"]) for p in man["parts"]] == [
        ("cases/007800124/part-002.tar", {want[0]: "0005.jpg", want[1]: "0006.jpg"}),
        ("cases/007800789/part-001.tar", {want[2]: "0001.jpg", want[3]: "0002.jpg"})]

    # прогін і голос справи — сторінки під новими іменами, мета справи
    assert got["key"] == "CDIAK/127/1012/535"
    assert got["runs"] == {"": "op1012-spr-535", "-diak_v10": "op1012-spr-535-diak_v10"}
    run = space / "reports" / "htr" / "op1012-spr-535"
    assert sorted(p.name for p in run.glob("0*")) == sorted(
        [Path(x).stem + s for x in want for s in (".txt", ".lines.json")])
    assert (run / "0003_007800789_0001.txt").read_text(encoding="utf-8") == "007800789 0001.jpg писар\n"
    meta = _json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    assert (meta["case_key"], meta["frames_total"], meta["done"]) == ("CDIAK/127/1012/535", 4, True)
    assert sorted(meta["pages"]) == want and meta["failed"] == ["0002_007800124_0006.jpg"]
    assert "stages_total" not in meta and [j["run"] for j in meta["join_from"]] == [
        "film-007800124", "film-007800789"]
    voice = _json.loads((space / "reports/htr/op1012-spr-535-diak_v10/_htr_meta.json").read_text(
        encoding="utf-8"))
    assert voice["done"] == 4, "у теці голосу `done` — число сторінок"

    # паспорт, ідентифікатори FS, нотатка сховища сторінок
    side = _json.loads((dest / "_source.json").read_text(encoding="utf-8"))
    assert side["shifra"] == "ЦДІАК 127-1012-535" and side["frames_remote"] is True
    assert side["r2_keys"] == ["cases/007800124/part-002.tar", "cases/007800789/part-001.tar"]
    assert [j["film"] for j in side["join_from"]] == ["007800124", "007800789"]
    fs = _json.loads((dest / "_fs_meta.json").read_text(encoding="utf-8"))
    assert fs["0004_007800789_0002"] == "id-007800789-0002.jpg"
    assert got["notes_moved"] == 1
    cf = PS.load_case(PS.resolve_case("ЦДІАК 127-1012-535"))
    assert list(cf.pages) == ["0004_007800789_0002.jpg"]
    assert cf.pages["0004_007800789_0002.jpg"].surnames == ["Дідик"]

    again = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535")
    assert again["made"] == 0 and again["runs"] == got["runs"]


def test_rozkladena_plivka_viddaie_tekst_z_zhurnalu(space: Path, two: tuple[Path, Path]) -> None:
    """Плівку вже розкладено, шматок справи лишився поза справами (`-`)."""
    from nyshporka.cases import split as SPL

    head, tail = two
    SPL.split(tail, [("-", "0001.jpg", "0002.jpg"), ("537", "0003.jpg", "0004.jpg"),
                     ("538", "0005.jpg", "0005.jpg")], rebuild=False)
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"

    got = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)

    run = space / "reports" / "htr" / got["runs"][""]
    assert (run / "0004_007800789_0002.txt").read_text(encoding="utf-8") == "007800789 0002.jpg писар\n"


def test_prochytane_bez_shyfry_vidmovliaie(space: Path, two: tuple[Path, Path]) -> None:
    head, tail = two
    with pytest.raises(J.JoinError, match="--shifra"):
        J.join(space / "x", _pieces(head, tail))
    assert not (space / "x").exists(), "відмова до запису"


def test_zmishani_chastyny_vidmovliaiut(space: Path, two: tuple[Path, Path], tmp_path: Path) -> None:
    head, _ = two
    disk = _film(tmp_path, "007899999_x", 3)
    with pytest.raises(J.JoinError, match="змішано"):
        J.plan(tmp_path / "y", [J.Piece(head, "0005.jpg", "0006.jpg"),
                                J.Piece(disk, "0001.jpg", "0002.jpg")])


def test_zibrana_z_bakieta_khmara_ne_perechytuie(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka.cloud import go as G

    head, tail = two
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"
    J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)

    assert G.joined_remote(dest) is True
    assert G.joined_remote(head) is False
