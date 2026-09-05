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


# ── клейми: динамічний розподіл ──────────────────────────────────────────────
# Хвіст статичного зрізу на std160 05.09.2026: шарди фінішують у вікні 110–125 с
# = 12% роботи на 20 стор/шард, на довгих справах ~20%. Динаміка мусить зберегти
# інваріант «рівно раз», але вже не за формулою, а за файлом-клеймом (O_EXCL).


def test_select_pages_with_claim_returns_the_whole_list_for_every_shard(case):
    for k in range(4):
        got = R.select_pages(case, "", 0, k, 4, claim=True)
        assert [p.name for p in got] == [p.name for p in R.select_pages(case, "", 0, 0, 1)]
    # без прапорця — старий зріз, для відкату й звірок
    assert len(R.select_pages(case, "", 0, 0, 4)) < 10


def test_racing_claimants_take_every_page_exactly_once(case, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    pages = R.select_pages(case, "", 0, 0, 1)
    taken: dict[int, list[str]] = {k: [] for k in range(4)}
    for p in pages:
        for k in range(4):
            if R.claim_page(out, p.stem, f"{k + 1}/4"):
                taken[k].append(p.name)
    names = [n for part in taken.values() for n in part]
    assert sorted(names) == sorted(p.name for p in pages)
    assert len(names) == len(set(names)), "кадр потрапив у два шарди"
    # повторний обхід тих самих чотирьох не бере нічого
    assert not any(R.claim_page(out, p.stem) for p in pages)
    assert (out / R.CLAIMS_DIR / "0001.claim").read_text(encoding="utf-8").split()[0] == str(
        __import__("os").getpid())


def test_a_dead_owner_s_claim_is_released_a_live_one_is_not(case, tmp_path: Path):
    """Мертвий шард лишає клейм без txt — сторінку візьме живий; свій і чужий
    живий клейми не чіпаються; клейм зі зробленим txt — не сирота."""
    out = tmp_path / "out"
    (out / R.CLAIMS_DIR).mkdir(parents=True)
    (out / R.CLAIMS_DIR / "0001.claim").write_text("2147483647 1/2 t\n", encoding="utf-8")
    (out / R.CLAIMS_DIR / "0002.claim").write_text(f"{__import__('os').getpid()} 2/2 t\n",
                                                   encoding="utf-8")
    (out / R.CLAIMS_DIR / "0003.claim").write_text("2147483647 1/2 t\n", encoding="utf-8")
    (out / "0003.txt").write_text("готово\n", encoding="utf-8")
    assert R.orphan_claims(out) == ["0001"]
    assert R.release_orphan_claims(out) == 1
    assert not (out / R.CLAIMS_DIR / "0001.claim").exists()
    assert (out / R.CLAIMS_DIR / "0002.claim").exists()
    assert (out / R.CLAIMS_DIR / "0003.claim").exists()
    assert R.claim_page(out, "0001")


def test_claimable_missing_ignores_pages_held_by_a_live_stranger(case, tmp_path: Path,
                                                                  monkeypatch):
    """Інакше кожен шард бачив би чужі недочитані сторінки як свої пропуски."""
    out = tmp_path / "out"
    (out / R.CLAIMS_DIR).mkdir(parents=True)
    pages = R.select_pages(case, "", 0, 0, 1)
    (out / "0001.txt").write_text("є\n", encoding="utf-8")
    (out / R.CLAIMS_DIR / "0002.claim").write_text("424242 1/2 t\n", encoding="utf-8")
    monkeypatch.setattr(R, "_pid_alive", lambda pid: pid == 424242)
    gone = R.claimable_missing(pages, out)
    assert "0001.jpg" not in gone and "0002.jpg" not in gone
    assert "0003.jpg" in gone and len(gone) == 8
    # а для статичного зрізу чужий клейм — не аргумент
    assert "0002.jpg" in R.missing_pages(pages, out)


def test_quarantine_writes_survive_two_writers(tmp_path: Path):
    """З клеймами сторінка-вбивця може дістатись двом шардам по черзі — два
    наглядачі пишуть карантин одночасно, і без лока один запис губився."""
    import threading

    out = tmp_path / "out"
    out.mkdir()

    def writer(prefix: str):
        for i in range(30):
            R.add_quarantine(out, f"{prefix}{i:03d}.jpg", "тест")

    threads = [threading.Thread(target=writer, args=(p,)) for p in ("a", "b", "c")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(R.load_quarantine(out)) == 90
