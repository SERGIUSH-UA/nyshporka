"""📏 Контракт повноти прогону: що саме доводить, що справу дочитано.

🔴 Ці три функції — весь приймач повноти, і покриття в них було нульове. Правило
проєкту каже прямо: приймач повноти — ДИСК, а не код повернення. Воно куплене
замірами. ДАХмО 241-1-886 (11.08.2026): процес помер нативно на 15-й із 18
сторінок — лог обірвався без traceback, `rc=1` без діагностики, у меті
`failed: []`, і прогін виглядав завершеним. Сусідній випадок: CUDA OOM з'їв 16
сторінок при `rc=0` і порожньому переліку збоїв.

Тобто помилка тут не падає — вона віддає книгу, оголошену прочитаною, і хибний
нуль по всій справі. Мережі й моделей тут немає: усе рахується з імен файлів.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.htr import runner as R


@pytest.fixture
def case(tmp_path: Path) -> Path:
    d = tmp_path / "case"
    d.mkdir()
    for n in range(1, 11):
        (d / f"{n:04}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (d / "опис.txt").write_text("не кадр", encoding="utf-8")
    return d


# ── розбір шарда ─────────────────────────────────────────────────────────────
def test_shard_spec_is_one_based_outside_and_zero_based_inside():
    assert R.parse_shard("1/3") == (0, 3)
    assert R.parse_shard("3/3") == (2, 3)
    assert R.parse_shard("") == (0, 1), "без шарда — один воркер із нуля"


@pytest.mark.parametrize("bad", ["0/3", "4/3", "-1/2", "2/0"])
def test_a_shard_outside_the_range_is_refused(bad):
    """🔴 Мовчазно прийнятий кривий шард — це прогін, який пропускає сторінки.

    `4/3` без перевірки дав би зріз, що не бере жодного кадру: прогін
    завершується миттєво й «успішно», а на диску нічого немає.
    """
    with pytest.raises(ValueError):
        R.parse_shard(bad)


# ── добір сторінок ───────────────────────────────────────────────────────────
def test_only_images_are_pages(case):
    got = R.select_pages(case, "", 0, 0, 1)
    assert len(got) == 10 and all(p.suffix == ".jpg" for p in got)


def test_shards_together_cover_every_page_exactly_once(case):
    """🔴 Приймач, без якого шардинг небезпечніший за його відсутність.

    Round-robin, а не блоками: сторінки нерівні за вартістю (порожня проти
    щільної), тож чергування вирівнює воркери самé по собі. Але яким би не був
    розподіл, об'єднання шардів мусить дорівнювати всій справі — інакше
    сторінка зникає без жодного сліду.
    """
    for n in (2, 3, 4, 7):
        parts = [R.select_pages(case, "", 0, k, n) for k in range(n)]
        names = [p.name for part in parts for p in part]
        assert sorted(names) == sorted(p.name for p in R.select_pages(case, "", 0, 0, 1))
        assert len(names) == len(set(names)), f"кадр потрапив у два шарди при n={n}"


def test_limit_and_pages_narrow_the_denominator(case):
    assert len(R.select_pages(case, "", 3, 0, 1)) == 3
    got = R.select_pages(case, "2-4", 0, 0, 1)
    assert [p.name for p in got] == ["0002.jpg", "0003.jpg", "0004.jpg"]


# ── головний приймач ─────────────────────────────────────────────────────────
def test_a_page_without_text_on_disk_is_missing(case, tmp_path):
    """Знаменник із ДИСКА: сторінка може загубитись без жодного винятку."""
    out = tmp_path / "out"
    out.mkdir()
    pages = R.select_pages(case, "", 0, 0, 1)
    for p in pages[:7]:
        (out / f"{p.stem}.txt").write_text("текст", encoding="utf-8")
    assert R.missing_pages(pages, out) == ["0008.jpg", "0009.jpg", "0010.jpg"]


def test_a_finished_run_reports_nothing_missing(case, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    pages = R.select_pages(case, "", 0, 0, 1)
    for p in pages:
        (out / f"{p.stem}.txt").write_text("текст", encoding="utf-8")
    assert R.missing_pages(pages, out) == []


def test_a_voice_missing_from_the_ensemble_makes_the_page_incomplete(case, tmp_path):
    """🔴 `<out>/0007.txt` без `<out>-diak/0007.txt` — недороблена сторінка, а
    не «модель промовчала».

    Ансамбль пише побічні голоси в тому самому проході. Не звіряти їх означає
    оголосити справу прочитаною двома рушіями, маючи один.
    """
    out, side = tmp_path / "out", tmp_path / "out-diak"
    out.mkdir()
    side.mkdir()
    pages = R.select_pages(case, "", 0, 0, 1)
    for p in pages:
        (out / f"{p.stem}.txt").write_text("текст", encoding="utf-8")
    for p in pages[:6]:
        (side / f"{p.stem}.txt").write_text("текст", encoding="utf-8")

    assert R.missing_pages(pages, out) == [], "головний голос повний"
    assert R.missing_pages(pages, out, (side,)) == [
        "0007.jpg", "0008.jpg", "0009.jpg", "0010.jpg"]


def test_a_page_is_counted_once_even_if_several_voices_are_missing(case, tmp_path):
    """Пропуск — це кадр, а не пара «кадр × голос»: інакше знаменник роздувається
    і «пропущено 4» на двох голосах читається як вісім різних сторінок."""
    out, a, b = tmp_path / "out", tmp_path / "va", tmp_path / "vb"
    for d in (out, a, b):
        d.mkdir()
    pages = R.select_pages(case, "", 0, 0, 1)
    for p in pages:
        (out / f"{p.stem}.txt").write_text("т", encoding="utf-8")
    got = R.missing_pages(pages, out, (a, b))
    assert got == [p.name for p in pages] and len(got) == len(set(got))
