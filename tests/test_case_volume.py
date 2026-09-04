"""📏 Обсяг прочитаного: скільки кадрів, скільки роботи рушіїв, скільки тексту.

До цього реєстр знав одну цифру — «декодовано сторінок» — і вона мовчки
відповідала на три різні питання. Кадр, прочитаний Писарем і Дяком, це один
кадр матеріалу, але два сторінко-декоди роботи; а сам кадр кадрові не рівня —
щільний переписний розворот дає втричі більше тексту за метричний.

Тут перевіряється те, що найлегше зламати непомітно: обсяг мусить приходити з
ТОГО САМОГО прогону, що дав `htr_pages_max`. Взявши сторінки з одного голосу, а
символи з іншого, зведення лишається правдоподібним — просто описує читання,
якого не було.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір із однією справою на диску й порожньою текою прогонів.

    🔴 Константи модулів підмінюються поіменно, а не через `workspace.use()`:
    `library`, `cases.db` і `cases.collect` заморожують шляхи в мить першого
    імпорту, тож без цього тест ганяв би збірку по СПРАВЖНЬОМУ простору
    розробника — зеленіючи від чужих даних і псуючи їх.
    """
    from nyshporka.core import workspace as W

    # 🔴 Простір повертається на місце після тесту, і саме через `monkeypatch`:
    # `use()` пише в глобальну `_override`, яку сам не відкочує. Без цього рядка
    # тимчасова тека лишалась би активним простором до кінця сесії, і падав би
    # НАСТУПНИЙ тестовий файл — спіймано на `test_frames_guard`, який після
    # цього шукав справу в чужому корені.
    monkeypatch.setattr(W, "_override", None, raising=False)
    W._cached.cache_clear()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L
    from nyshporka.cases import collect as C
    from nyshporka.cases import db as DB
    from nyshporka.cases import register as R

    for mod, attr, value in (
        (L, "ROOT", tmp_path), (L, "RAW_DIR", tmp_path / "data" / "raw"),
        (L, "LIBRARY_PATH", tmp_path / "data" / "derived" / "case_library.json"),
        (L, "VERDICTS_PATH", tmp_path / "data" / "spotter" / "case_verdicts.json"),
        (C, "ROOT", tmp_path), (C, "HTR_ROOT", tmp_path / "reports" / "htr"),
        (C, "RAW_DIR", tmp_path / "data" / "raw"),
        (C, "PAGES_ROOT", tmp_path / "data" / "pages"),
        (C, "CLAN_STATE", tmp_path / "data" / "clan_hunt" / "state.json"),
        (C, "DERIVED_DB", tmp_path / "data" / "derived" / "nyshporka.sqlite"),
        (DB, "DB_PATH", tmp_path / "data" / "derived" / "case_index.sqlite"),
    ):
        monkeypatch.setattr(mod, attr, value)

    # 🔴 Кеші чистяться ПІСЛЯ підміни констант, і чистяться ВСІ: у `library`
    # їх понад десяток (`lru_cache`), кожен тримає шляхи попереднього простору,
    # а перелічений поіменно список мовчки застаріває з появою нового кеша.
    def _clear() -> None:
        for mod in (L, C, DB):
            for name in dir(mod):
                got = getattr(mod, name, None)
                if hasattr(got, "cache_clear"):
                    got.cache_clear()

    _clear()

    case = tmp_path / "data" / "raw" / "справа"
    case.mkdir(parents=True)
    for i in (1, 2, 3):
        (case / f"000{i}.jpg").write_bytes(b"x")
    R.describe(case, shifra="ДАХмО 315-1-8433", title="Метрична книга")
    (tmp_path / "reports" / "htr").mkdir(parents=True)
    yield tmp_path
    # 🔴 І на виході теж. Тест будує опис справ (`build_library`), тож кеш
    # лишається повним НАШИМИ шляхами; `monkeypatch` відкотить константи, але
    # не вміст `lru_cache`, і наступний тестовий файл шукав би справу в теці,
    # якої вже немає. Симптом оманливий: падає чужий тест, зелений сам по собі.
    _clear()


def _run(root: Path, name: str, model: str, pages: dict[str, tuple[int, int]]) -> None:
    """Покласти прогін: `{сторінка: (символів, рядків)}`."""
    d = root / "reports" / "htr" / name
    d.mkdir(parents=True)
    (d / "_htr_meta.json").write_text(json.dumps({
        "version": 1,
        "case_dir": "data/raw/справа",
        "case_key": "DAHMO/315/8433",
        "model": model,
        "updated": "2026-09-04T10:00:00",
        "pages": {p: {"chars": c, "lines": ln} for p, (c, ln) in pages.items()},
    }, ensure_ascii=False), encoding="utf-8")


def _row(root: Path) -> Any:
    """Зібрати реєстр і повернути єдину справу простору.

    🔴 Опис справ будується заново перед кожним збором. `collect_rows()` читає
    `case_library.json`, а не диск: без цього кроку справа з сайдкаром лягає в
    реєстр як `unfiled` («без шифри»), прогони до неї не прив'язуються, і тест
    зеленів би на порожньому місці — рівно та помилка, від якої застерігає
    `rebuild()` у самому пакеті.
    """
    from nyshporka.cases.collect import collect_rows
    from nyshporka.library import build_library, write_library

    write_library(build_library())
    rows, _ = collect_rows()
    assert len(rows) == 1, "у просторі одна справа — решта тут зайва"
    return rows[0]


def test_volume_comes_from_the_run_that_set_pages_max(space: Path) -> None:
    """Сторінки й символи — з одного прогону, а не з різних голосів.

    Дяк тут прочитав менше сторінок, але кожну — щедріше. Якщо взяти максимум
    окремо по кожному полю, справа отримає 3 сторінки і 900 символів, тобто
    обсяг читання, якого не робив жоден рушій.
    """
    _run(space, "spr-8433", "pysar_cyr_v17.pt",
         {"0001.jpg": (100, 10), "0002.jpg": (100, 10), "0003.jpg": (100, 10)})
    _run(space, "spr-8433-diak_v4", "diak_cyr_v9.mlmodel",
         {"0001.jpg": (300, 30), "0002.jpg": (300, 30)})

    row = _row(space)
    assert row.htr_pages_max == 3
    assert row.htr_chars_max == 300, "символи мусять бути Писаревими, а не Дяковими"
    assert row.htr_lines_max == 30


def test_work_of_engines_counts_every_voice(space: Path) -> None:
    """Робота рушіїв — сума прогонів; матеріал — кожен кадр один раз."""
    _run(space, "spr-8433", "pysar_cyr_v17.pt",
         {"0001.jpg": (100, 10), "0002.jpg": (100, 10)})
    _run(space, "spr-8433-diak_v4", "pysar_cyr_v17.pt+diak_v4",
         {"0001.jpg": (150, 12), "0002.jpg": (150, 12)})

    row = _row(space)
    assert row.htr_pages_max == 2, "кадрів прочитано два, скільки б голосів не було"
    assert row.htr_pages_all == 4, "а роботи рушіїв — чотири сторінко-декоди"
    assert row.htr_chars_all == 500
    assert row.htr_chars_max == 300


def test_ensemble_credits_both_voices(space: Path) -> None:
    """Ансамбль записується обом голосам: питання «що рушій бачив», не «чий текст».

    Саме тому сума по голосах законно перевищує число кадрів, і читати її як
    подвійний облік не можна.
    """
    _run(space, "spr-8433", "pysar_cyr_v17.pt+diak_v4",
         {"0001.jpg": (100, 10), "0002.jpg": (100, 10)})

    row = _row(space)
    assert row.htr_pysar and row.htr_diak
    assert row.htr_pysar_pages == row.htr_diak_pages == 2
    assert row.htr_pysar_chars == row.htr_diak_chars == 200
    assert not row.htr_skryba


def test_blank_pages_are_exactly_the_ones_with_no_characters(space: Path) -> None:
    """Порожня — це `chars == 0`, а не «мало символів».

    Сторінка з самим колонтитулом прочитана; оголосивши її порожньою, зведення
    почало б звітувати про сліпоту рушія там, де насправді порожній аркуш.
    """
    _run(space, "spr-8433", "pysar_cyr_v17.pt",
         {"0001.jpg": (0, 0), "0002.jpg": (7, 1), "0003.jpg": (500, 40)})

    row = _row(space)
    assert row.htr_pages_blank == 1


def test_stats_keeps_material_and_work_apart(space: Path) -> None:
    """Зведення подає обидва числа, і вони не сходяться між собою — так і треба."""
    from nyshporka.cases import db as DB

    _run(space, "spr-8433", "pysar_cyr_v17.pt",
         {"0001.jpg": (100, 10), "0002.jpg": (100, 10)})
    _run(space, "spr-8433-diak_v4", "diak_cyr_v9.mlmodel",
         {"0001.jpg": (100, 10), "0002.jpg": (100, 10)})
    # 🔴 `rebuild()`, а не `build_index()`: другий збирає зріз на бібліотеці,
    # якої ще немає, і дає не порожній результат, а НЕПРАВИЛЬНИЙ — справа без
    # шифри, прогони нічиї. Саме про це попереджає докстрока `rebuild`.
    DB.rebuild()

    s = DB.stats()
    assert s["htr_pages"] == 2
    assert s["htr_pages_all"] == 4
    assert s["htr_chars"] == 200
    assert s["htr_chars_all"] == 400
    mix = {int(r["voices"]): r["n"] for r in s["voice_mix"]}
    assert mix == {2: 1}, "справа прочитана двома голосами"
    voices = {v["voice"]: v for v in s["voices"]}
    assert voices["pysar"]["cases"] == voices["diak"]["cases"] == 1
    assert voices["skryba"]["cases"] == 0
