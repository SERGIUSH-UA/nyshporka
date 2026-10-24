"""Справа на двох котушках: `nysh cases join`.

ДАЧкО 931-1-855 (17.10.2026): голова на плівці 007803765, хвіст — на
007803766. Стережеться порядок «голова → хвіст» за наскрізним номером в імені і
те, що зайвий виклик не кладе справу поверх чужих кадрів.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

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
