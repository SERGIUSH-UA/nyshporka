"""📶 Дзеркало каналу прогресу: раннер пише — ядро читає.

🔴 Дублювання тут обов'язкове, а не лінь. Раннер їде під інтерпретатором
середовища рушіїв (`kraken==7.0.2`, свій torch), де пакета немає й не буде;
імпортувати `core.progress` він не може. Отже, опис протоколу існує двічі.

І саме тому потрібен цей тест. Розходження двох описів ламається **тихо й
дорого**: читач відкидає подію з чужою версією схеми (і правильно робить —
поле, що змінило сенс, гірше за відсутнє), прогрес завмирає на нулі, а вотчдог
за десять хвилин тиші вбиває живий прогін. Зовні це «завис».

Спіймано саме так: раннер не слав `"v"` взагалі, тож `parse()` відкидав кожну
його подію. Знайшлось не тестом і не в лозі — а тим, що подію прогнали крізь
читача руками.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from nyshporka.core import progress as P

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("_runner_progress", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def test_prefix_and_schema_match(runner) -> None:
    """Два описи протоколу мусять називати те саме."""
    assert runner.PROGRESS_PREFIX.strip() == P.PREFIX
    assert runner.PROGRESS_SCHEMA == P.SCHEMA


def test_what_the_runner_emits_is_what_the_core_parses(runner, capsys) -> None:
    """🔴 Головна перевірка: подія раннера проходить крізь читача.

    Не «формат схожий», а буквально: беремо те, що раннер надрукував, і
    згодовуємо `parse()`. Саме цей крок і показав, що жодна подія не доїжджала.
    """
    runner.emit(True, "page", i=3, n=20, item="0003.jpg")
    line = capsys.readouterr().out.strip()
    ev = P.parse(line)
    assert ev is not None, (
        f"читач відкинув подію раннера: {line!r}\n"
        f"Це та сама тиша, через яку вотчдог убиває живий прогін.")
    assert ev.phase == "page"
    assert (ev.i, ev.n) == (3, 20)
    assert ev.item == "0003.jpg"


def test_disabled_emit_is_silent(runner, capsys) -> None:
    """Вимкнений канал не має засмічувати вивід для людини."""
    runner.emit(False, "page", i=1, n=2)
    assert capsys.readouterr().out == ""


def test_extra_fields_survive_the_trip(runner, capsys) -> None:
    """Поля, яких читач не знає, доїжджають в `extra`, а не зникають.

    Раннер додає свої (`spp`, `contrast`), і втрачати їх не можна: саме вони
    відповідають на «чому так повільно».
    """
    runner.emit(True, "done", i=20, n=20, spp=18.4)
    ev = P.parse(capsys.readouterr().out.strip())
    assert ev is not None
    assert ev.extra.get("spp") == 18.4


def test_a_human_line_is_not_mistaken_for_progress() -> None:
    """У потоці змішані людські рядки й машинні; переплутати їх не можна."""
    assert P.parse("[htr-run] ✓ готово: 20 розпізнано") is None
    assert P.parse("") is None


def test_foreign_schema_is_refused_not_guessed() -> None:
    """Чужа версія — відмова, а не «прочитаємо, що зрозуміло».

    Показник, який бреше, гірший за відсутній: поле могло змінити сенс.
    """
    line = f'{P.PREFIX} {json.dumps({"v": P.SCHEMA + 1, "phase": "page", "i": 5})}'
    assert P.parse(line) is None
