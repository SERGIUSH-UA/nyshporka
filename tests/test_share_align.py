"""Мітка прив'язки: чотири стани, і жоден не підвищується здогадом.

🔴 Сенс тесту — не в тому, що мітка є, а в тому, що вона НЕ завищується. Збіг
імені файлу не означає той самий кадр (плоский стейджинг перенумеровує
сторінки), а збіг кількості не означає навіть цього. Кожен випадок мусить
осісти рівно там, де для нього є доказ.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka.share import align


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def frames_dir(root: Path, names: list[str], *,
               fs_meta: dict | None = None) -> Path:
    d = root / "kadry"
    d.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names, 1):
        (d / name).write_bytes(b"JPEG" + str(i).encode() * 8)
    if fs_meta is not None:
        (d / align.FS_META).write_text(json.dumps(fs_meta, ensure_ascii=False),
                                       encoding="utf-8")
    return d


def test_frames_of_numbers_in_order(tmp_path: Path) -> None:
    d = frames_dir(tmp_path, ["0002.jpg", "0001.jpg", "0003.jpg"])
    got = align.frames_of(d)
    assert [f["n"] for f in got] == [1, 2, 3]
    assert [f["name"] for f in got] == ["0001.jpg", "0002.jpg", "0003.jpg"]


def test_hash_is_not_computed_unless_asked(tmp_path: Path) -> None:
    """Хеш коштує гігабайти читання — за замовчуванням його не рахують."""
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg"])
    assert not any(f.get("sha256") for f in align.frames_of(d))
    assert all(f.get("sha256") for f in align.frames_of(d, hash_frames=True))


def test_fs_sidecar_gives_hash_and_apid_for_free(tmp_path: Path) -> None:
    d = frames_dir(tmp_path, ["0001.jpg"],
                   fs_meta={"0001": {"apid": "TH-7795-136523", "sha256": "ab" * 32}})
    got = align.frames_of(d)
    assert got[0]["apid"] == "TH-7795-136523"
    assert got[0]["sha256"] == "ab" * 32


def test_apid_match_is_exact(tmp_path: Path) -> None:
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg"],
                   fs_meta={"0001": {"apid": "A1"}, "0002": {"apid": "A2"}})
    theirs = [{"n": 1, "name": "page_1.jpg", "apid": "A1"},
              {"n": 2, "name": "page_2.jpg", "apid": "A2"}]
    got = align.grade(theirs, d)
    assert got.label == align.EXACT
    assert got.can_crop


def test_same_names_and_count_is_by_name(tmp_path: Path) -> None:
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg"])
    theirs = [{"n": 1, "name": "0001.jpg"}, {"n": 2, "name": "0002.jpg"}]
    got = align.grade(theirs, d)
    assert got.label == align.BY_NAME
    assert not got.can_crop


def test_same_count_other_names_is_by_position(tmp_path: Path) -> None:
    """Однакова кількість доводить лише кількість — і мітка це каже вголос."""
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg"])
    theirs = [{"n": 1, "name": "img_001.jpg"}, {"n": 2, "name": "img_002.jpg"}]
    got = align.grade(theirs, d)
    assert got.label == align.BY_POSITION
    assert "на віру" in got.why
    assert not got.can_crop


def test_no_frames_at_all_is_text_only(tmp_path: Path) -> None:
    theirs = [{"n": 1, "name": "0001.jpg"}]
    got = align.grade(theirs, None)
    assert got.label == align.TEXT_ONLY
    assert got.theirs == 1


def test_different_shoot_of_the_same_case_is_text_only(tmp_path: Path) -> None:
    """Різна кількість кадрів — це інша зйомка, а не привід вирівняти силою."""
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg", "0003.jpg"])
    theirs = [{"n": 1, "name": "0001.jpg"}, {"n": 2, "name": "0002.jpg"}]
    got = align.grade(theirs, d)
    assert got.label == align.TEXT_ONLY
    assert got.ours == 3
    assert got.theirs == 2
    assert "різні зйомки" in got.why


def test_summary_counts_what_is_provable(tmp_path: Path) -> None:
    d = frames_dir(tmp_path, ["0001.jpg", "0002.jpg"],
                   fs_meta={"0001": {"apid": "A1", "sha256": "cd" * 32}})
    got = align.summary(align.frames_of(d))
    assert got == {"total": 2, "listed": 2, "with_sha256": 1, "with_apid": 1}
