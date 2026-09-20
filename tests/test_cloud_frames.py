"""🎞 Кадри перед дорогою: що мусить бути спіймано ДО оренди.

Усе тут безплатне, а ловить те, що після оренди найдорожче:

* обрізаний кадр рушій не валить — він читає верхню половину аркуша, і справа
  виглядає прочитаною;
* тека, яка ще качається, дає захід, що чесно рапортує «повністю» про частину;
* стискання, обірване посеред кадру, лишає в цілі рівно той обрізаний файл,
  від якого стоїть перша перевірка, — і повторний виклик пропускає його як
  готовий.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from nyshporka.cloud import frames as F

Image = pytest.importorskip("PIL.Image")


def _jpeg(path: Path, size: tuple[int, int] = (60, 90), *, age_sec: float = 3600) -> Path:
    Image.new("RGB", size, (200, 190, 170)).save(path, "JPEG", quality=90)
    _age(path, age_sec)
    return path


def _age(path: Path, age_sec: float) -> None:
    old = time.time() - age_sec
    os.utime(path, (old, old))


# ── цілість ──────────────────────────────────────────────────────────────────
def test_a_clean_folder_passes(tmp_path: Path) -> None:
    for i in range(3):
        _jpeg(tmp_path / f"{i:04d}.jpg")
    got = F.check_frames(tmp_path)
    assert (got.n, got.bad, got.still_writing_min) == (3, [], None)


def test_a_truncated_jpeg_is_caught_by_its_tail(tmp_path: Path) -> None:
    """🔴 Головний тест: `verify()` у Pillow обрізаного JPEG НЕ ловить.

    Він читає заголовок, а обрив сидить у хвості. Саме такий кадр лишає
    завантажувач, убитий посеред запису, — правильне ім'я, правильний початок.
    """
    good = _jpeg(tmp_path / "0001.jpg", (400, 600))
    cut = tmp_path / "0002.jpg"
    data = good.read_bytes()
    cut.write_bytes(data[: len(data) // 2])
    _age(cut, 3600)

    with Image.open(cut) as im:
        im.verify()         # заголовок цілий — Pillow не заперечує

    got = F.check_frames(tmp_path)
    assert len(got.bad) == 1 and "0002.jpg" in got.bad[0]
    assert "обрізаний" in got.bad[0]


def test_a_truncated_png_is_caught_too(tmp_path: Path) -> None:
    good = tmp_path / "a.png"
    Image.new("L", (80, 80), 128).save(good, "PNG")
    cut = tmp_path / "b.png"
    cut.write_bytes(good.read_bytes()[:-20])
    for p in (good, cut):
        _age(p, 3600)
    got = F.check_frames(tmp_path)
    assert [b.split(":")[0] for b in got.bad] == ["b.png"]


def test_an_empty_file_is_named(tmp_path: Path) -> None:
    _jpeg(tmp_path / "0001.jpg")
    (tmp_path / "0002.jpg").write_bytes(b"")
    _age(tmp_path / "0002.jpg", 3600)
    got = F.check_frames(tmp_path)
    assert got.bad == ["0002.jpg: 0 байт"]


def test_a_folder_still_being_written_is_flagged(tmp_path: Path) -> None:
    """🔴 Захід на недокачаній справі читає частину й рапортує «повністю»:
    знаменник він бере з тієї самої теки."""
    _jpeg(tmp_path / "0001.jpg")
    _jpeg(tmp_path / "0002.jpg", age_sec=60)
    got = F.check_frames(tmp_path)
    assert got.bad == []
    assert got.still_writing_min == pytest.approx(1.0, abs=0.2)

    settled = F.check_frames(tmp_path, now=time.time() + 600)
    assert settled.still_writing_min is None, "за десять хвилин тека вже стоїть"


def test_the_loader_sidecar_is_optional_but_believed(tmp_path: Path) -> None:
    """Сайдкар знає розмір кожного кадру: розбіжність — перезаписаний кадр,
    відсутній на диску — неповна тека. Без сайдкара перевірки просто немає."""
    a = _jpeg(tmp_path / "0001.jpg")
    assert F.check_frames(tmp_path).bad == []

    (tmp_path / F.FS_SIDECAR).write_text(json.dumps({
        "1": {"file": "0001.jpg", "size": a.stat().st_size + 7},
        "2": {"file": "0002.jpg", "size": 100}}), encoding="utf-8")
    bad = F.check_frames(tmp_path).bad
    assert any("0002.jpg" in b and "на диску немає" in b for b in bad)
    assert any("0001.jpg" in b and "перезаписаний" in b for b in bad)


# ── стискання ────────────────────────────────────────────────────────────────
def test_shrink_makes_grey_jpegs_of_working_height(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _jpeg(src / "0001.jpg", (300, 500))
    Image.new("RGB", (200, 320), (10, 20, 30)).save(src / "0002.png", "PNG")

    got = F.shrink(src, dst, target_h=100)
    assert (got.total, got.done, got.skipped) == (2, 2, 0)
    assert sorted(p.name for p in dst.iterdir()) == ["0001.jpg", "0002.jpg"]
    with Image.open(dst / "0001.jpg") as im:
        assert im.height == 100 and im.mode == "L"
    assert not list(src.glob("*.part")) and (src / "0002.png").exists(), \
        "оригінали не чіпаються"


def test_shrink_is_idempotent(tmp_path: Path) -> None:
    """Перерване стискання доганяється повторним викликом, готове не чіпається."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for i in range(3):
        _jpeg(src / f"{i:04d}.jpg", (120, 200))
    F.shrink(src, dst, target_h=100)
    stamps = {p.name: p.stat().st_mtime_ns for p in dst.iterdir()}

    (dst / "0001.jpg").unlink()             # ніби обірвало посередині
    again = F.shrink(src, dst, target_h=100)
    assert (again.done, again.skipped) == (1, 2)
    after = {p.name: p.stat().st_mtime_ns for p in dst.iterdir()}
    assert after["0000.jpg"] == stamps["0000.jpg"], "готовий кадр не переписано"
    assert not list(dst.glob("*.part")), "тимчасових файлів не лишається"


def test_shrink_refuses_two_frames_that_would_become_one(tmp_path: Path) -> None:
    """🔴 Усе стає `<ім'я>.jpg`: `0001.png` і `0001.jpg` злились би в один кадр,
    і захід прочитав би на сторінку менше без жодної помилки."""
    src = tmp_path / "src"
    src.mkdir()
    _jpeg(src / "0001.jpg")
    Image.new("L", (60, 90), 128).save(src / "0001.png", "PNG")
    with pytest.raises(F.FramesError, match="одним іменем"):
        F.shrink(src, tmp_path / "dst")


def test_shrink_refuses_a_target_that_holds_another_case(tmp_path: Path) -> None:
    """Тека з таким іменем могла лишитись від іншої справи — чужого не зносимо."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _jpeg(src / "0001.jpg")
    _jpeg(dst / "9999.jpg")
    with pytest.raises(F.FramesError, match="іншої теки"):
        F.shrink(src, dst)


def test_landscape_frames_are_counted_and_never_rotated_silently(tmp_path: Path) -> None:
    """🔴 Кадр на боці й кадр-розворот виглядають однаково — ширина більша за
    висоту, — а лікуються протилежно. Тому без прапорця не крутиться нічого,
    а число таких кадрів повертається: вибір не мовчазний у жодному напрямку."""
    src = tmp_path / "src"
    src.mkdir()
    _jpeg(src / "0001.jpg", (300, 200))
    _jpeg(src / "0002.jpg", (200, 300))

    plain = F.shrink(src, tmp_path / "plain", target_h=100)
    assert (plain.landscape, plain.rotated) == (1, 0)
    with Image.open(tmp_path / "plain" / "0001.jpg") as im:
        assert im.width > im.height, "без прапорця кадр лишився як був"

    turned = F.shrink(src, tmp_path / "turned", target_h=100, rotate_landscape=True)
    assert turned.rotated == 1
    with Image.open(tmp_path / "turned" / "0001.jpg") as im:
        assert im.height > im.width


def test_the_shrunk_copy_keeps_the_name_of_the_case(tmp_path: Path, monkeypatch) -> None:
    """🔴 Ім'я теки = ім'я справи: з нього беруться ім'я прогону й тека виходу."""
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    assert F.shrink_dir_for(tmp_path / "raw" / "sprava-7").name == "sprava-7"
    assert F.shrink_dir_for(tmp_path / "raw" / "sprava-7" / "pages").name == "sprava-7"


# ── щільність ────────────────────────────────────────────────────────────────
def test_density_is_unknown_until_there_is_enough_to_measure(tmp_path: Path) -> None:
    """Медіана з трьох аркушів описує три аркуші, а не книгу: доти — `None`."""
    assert F.lines_per_page(tmp_path / "нема") is None
    for i in range(F.DENSITY_MIN_PAGES - 1):
        (tmp_path / f"{i:04d}.txt").write_text("рядок\n" * 40, encoding="utf-8")
    assert F.lines_per_page(tmp_path) is None
    (tmp_path / "9999.txt").write_text("рядок\n\n" * 40, encoding="utf-8")
    assert F.lines_per_page(tmp_path) == 40.0


# ── формат, якого машина не бере ─────────────────────────────────────────────
def test_tiff_is_named_and_converted_before_the_road(tmp_path: Path) -> None:
    """🔴 TIFF локальне читання розуміє, а хмарний захід пакує лише JPEG і PNG.

    Такий кадр мовчки випав би зі знаменника — половина справи виглядала б
    прочитаною повністю. Тому він і названий у звірці, і переведений у JPEG
    разом зі стисканням, хоч би яка була медіана розміру.
    """
    case = tmp_path / "sprava"
    case.mkdir()
    Image.new("L", (40, 60), 200).save(case / "0001.jpg", "JPEG")
    Image.new("L", (40, 60), 200).save(case / "0002.tif", "TIFF")

    rep = F.check_frames(case)
    assert rep.alien == ["0002.tif"], "кадр чужого формату мусить бути названий"
    assert rep.heavy, "дрібний TIFF однаково треба перевести, а не везти як є"

    out = F.shrink(case, tmp_path / "ready", target_h=50)
    assert out.done == 2
    assert sorted(p.name for p in (tmp_path / "ready").iterdir()) == \
        ["0001.jpg", "0002.jpg"], "на машину їде лише те, що вона читає"
