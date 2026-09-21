"""💾 Готова сегментація: коли їй можна вірити, а коли вона тихо збреше.

Перечитування справи другою моделлю коштує вдвічі дешевше, якщо не сегментувати
її вдруге (18.4 → 9.1 с/стор). Але кеш не знає зображення — лише параметри
нарізки, — тож єдине, що стоїть між економією й купою правдоподібного сміття,
це перевірки з цього файлу.

Усе тут на диску: справжні gzip-и, справжні `.lines.json`, справжні кадри. Ні
мережі, ні рушія — і саме тому ці перевірки не можна «пропустити заради
швидкості».
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from nyshporka.htr import seg as S

Image = pytest.importorskip("PIL.Image")


def _frame(path: Path, size: tuple[int, int] = (1200, 1800)) -> Path:
    Image.new("RGB", size, (210, 200, 180)).save(path, "JPEG", quality=85)
    return path


def _cache(d: Path, stems: list[str], *, key: dict | None = None) -> Path:
    """Тека кешу з правдоподібними `*.seg.json.gz`, як їх пише раннер."""
    d.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        blob = {"key": key or dict(S.EXPECTED_KEY), "lines": [[0, 0, 100, 40]]}
        with gzip.open(d / f"{stem}.c400.seg.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(blob, fh)
    return d


def _lines_json(out: Path, stem: str, size: tuple[int, int]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.lines.json").write_text(
        json.dumps({"size": list(size), "lines": []}), encoding="utf-8")


# ── де кеш шукається ─────────────────────────────────────────────────────────
def test_the_local_cache_is_found_at_the_address_htr_run_gives(tmp_path: Path) -> None:
    """🔴 Формула адреси одна на простір. Другий екземпляр розійшовся б із нею
    мовчки, і кеш «не знаходився б» — тобто справу сегментували б удруге за
    гроші, не дізнавшись про це."""
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-1"
    case.mkdir()
    frames = [_frame(case / f"{i:04d}.jpg") for i in range(3)]
    derived = tmp_path / "derived"
    _cache(seg_cache_dir(case, derived), [f.stem for f in frames])

    got = S.inspect(case, frames, base_out=tmp_path / "out", derived=derived)
    assert got.usable and got.covered == 3
    assert got.path == seg_cache_dir(case, derived)


def test_the_fuller_cache_wins(tmp_path: Path) -> None:
    """Кеш із хмари й локальний можуть співіснувати: у теці прогону лежить те,
    що привезли, у просторі — те, що рахували вдома. Береться повніший."""
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-2"
    case.mkdir()
    frames = [_frame(case / f"{i:04d}.jpg") for i in range(3)]
    out = tmp_path / "out"
    _cache(out / "data" / "derived" / "htr_seg" / "привезене", [frames[0].stem])
    derived = tmp_path / "derived"
    local = _cache(seg_cache_dir(case, derived), [f.stem for f in frames])

    got = S.inspect(case, frames, base_out=out, derived=derived)
    assert got.path == local and got.covered == 3


def test_no_cache_is_an_answer_not_a_failure(tmp_path: Path) -> None:
    case = tmp_path / "spr-3"
    case.mkdir()
    frames = [_frame(case / "0001.jpg")]
    got = S.inspect(case, frames, base_out=tmp_path / "out", derived=tmp_path / "derived")
    assert not got.usable and got.path is None
    assert "сегментуватиметься наново" in got.why


# ── коли кешу вірити НЕ можна ────────────────────────────────────────────────
def test_a_cache_from_other_geometry_is_refused(tmp_path: Path) -> None:
    """🔴🔴 Головний запобіжник усього модуля.

    Перший прогін читав ОРИГІНАЛИ, а на машину їде стиснута до 3100 px копія
    (`cloud.frames.shrink`). Засіяний у такий прогін кеш дає полігони в чужій
    системі координат — рядки вийдуть не ті, текст вийде не той, і жоден
    лічильник цього не покаже: сторінки чесно рахуватимуться як прочитані.
    """
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-4"
    case.mkdir()
    # кадри, які ПОЇДУТЬ читатись, — стиснуті
    frames = [_frame(case / f"{i:04d}.jpg", (600, 900)) for i in range(3)]
    derived = tmp_path / "derived"
    _cache(seg_cache_dir(case, derived), [f.stem for f in frames])
    out = tmp_path / "out"
    for f in frames:                       # перший прогін бачив оригінали
        _lines_json(out, f.stem, (1200, 1800))

    got = S.inspect(case, frames, base_out=out, derived=derived)
    assert not got.usable
    assert "іншого розміру" in got.why and "600×900" in got.why
    assert got.covered == 3, "кеш знайдено — відмовлено саме за геометрією"


def test_a_cache_with_other_slicing_params_is_refused(tmp_path: Path) -> None:
    """Раннер на такому кеші мовчки сегментує наново: ми заплатили б за те,
    чого думали, що не робимо."""
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-5"
    case.mkdir()
    frames = [_frame(case / f"{i:04d}.jpg") for i in range(3)]
    derived = tmp_path / "derived"
    _cache(seg_cache_dir(case, derived), [f.stem for f in frames],
           key={**S.EXPECTED_KEY, "sato": "1,5"})

    got = S.inspect(case, frames, base_out=tmp_path / "out", derived=derived)
    assert not got.usable and "sato" in got.why


def test_a_broken_cache_file_is_refused_by_name(tmp_path: Path) -> None:
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-6"
    case.mkdir()
    frames = [_frame(case / "0001.jpg")]
    derived = tmp_path / "derived"
    d = seg_cache_dir(case, derived)
    d.mkdir(parents=True)
    (d / "0001.c400.seg.json.gz").write_bytes("не gzip".encode())

    got = S.inspect(case, frames, base_out=tmp_path / "out", derived=derived)
    assert not got.usable and "не читається" in got.why


# ── покриття ─────────────────────────────────────────────────────────────────
def test_coverage_counts_only_the_frames_we_will_read(tmp_path: Path) -> None:
    """Кеш може бути ширший за справу (перечитуємо частину) або вужчий
    (обірваний прогін). Рахується перетин — саме від нього залежить, чи класти
    щільніший флот."""
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-7"
    case.mkdir()
    frames = [_frame(case / f"{i:04d}.jpg") for i in range(10)]
    derived = tmp_path / "derived"
    _cache(seg_cache_dir(case, derived),
           [f.stem for f in frames[:8]] + ["чужий-кадр"])

    got = S.inspect(case, frames, base_out=tmp_path / "out", derived=derived)
    assert (got.covered, got.frames) == (8, 10)
    assert got.coverage == pytest.approx(0.8)
    assert got.coverage < S.DENSE_FLEET_COVERAGE, (
        "щільніший флот на такому покритті ставити не можна: дві сторінки з "
        "десяти сегментуватимуться, і шардам забракне ядер")


def test_a_missing_lines_json_is_not_a_geometry_problem(tmp_path: Path) -> None:
    """Першого прогону могло не бути взагалі (кеш привезли, тексти ні). Це не
    привід відкидати кеш — привід лише розбіжність, яку ВИДНО."""
    from nyshporka.htr.run import seg_cache_dir

    case = tmp_path / "spr-8"
    case.mkdir()
    frames = [_frame(case / f"{i:04d}.jpg") for i in range(3)]
    derived = tmp_path / "derived"
    _cache(seg_cache_dir(case, derived), [f.stem for f in frames])

    got = S.inspect(case, frames, base_out=tmp_path / "порожньо", derived=derived)
    assert got.usable and got.covered == 3
