"""Ключ справи збирає тільки `_mk_key` — f-рядок повз нього заборонений.

Підстава — інцидент 2026-08-25. Фонд перевели на ключ-з-описом
(`_OPYS_IN_KEY`), і збірка реєстру відв'язала від справи канон: картка
показала «фактів 0» там, де канон цитує аркуш дослівно. Причина була не в
міграції, а в тому, що `cases/collect.py` у трьох місцях складав ключ як
`f"{repo}/{fond}/{spr}"` — тобто опис у ньому не з'являвся ніколи, хоч би що
казав `_OPYS_IN_KEY`.

Помилка мовчазна за побудовою: рядок збирається успішно, просто не влучає в
жоден запис реєстру. Тому приймач тут не на поведінку, а на форму коду.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# 🔴 `nyshporka.library` НЕ імпортується в шапці, і це не стиль. Модуль бере
# `ROOT = workspace().root` на рівні модуля, тобто заморожує простір у мить
# першого імпорту, — а pytest імпортує ВСІ тестові модулі на збиранні, коли
# ізолювальна фікстура ще не діяла. Одна імпортна стрічка тут прив'язує
# бібліотеку до простору розробника, і сусідній тест, який підставив тимчасову
# теку, мовчки бачить справжні справи. Спіймано 2026-08-26: `test_case_roots`
# окремо проходив, у повному прогоні падав.
#
# ⚠ Перенести імпорт усередину тесту НЕ досить: простір тоді знаходять і без
# змінної середовища — через файл «останній використаний», що лежить у профілі
# ОС, — тож бібліотека все одно замерзає на чужому. Тому фікстура спершу
# ОГОЛОШУЄ тимчасовий простір і лише потім імпортує; той самий порядок, що в
# `test_register_and_notes.space`.


@pytest.fixture
def lib(tmp_path: Path):
    """Бібліотека, заморожена на ТИМЧАСОВОМУ просторі.

    Констант простору цей файл не читає — лише таблиці фондів і збирачі
    ключів, — але імпортувати модуль інакше не можна, не лишивши слід сусідам.
    """
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka import library as L

    return L

PKG = Path(__file__).resolve().parents[1] / "src" / "nyshporka"

#: `f"{repo}/{fond}/{spr}"` і подібне: три поля через слеш усередині f-рядка.
HAND_BUILT = re.compile(r'f"\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}/\{[a-z_]+(?:\[\d\])?\}"')


def test_no_hand_built_case_keys() -> None:
    """У пакеті `cases` ключ не збирається f-рядком із трьох полів."""
    findings: list[str] = []
    for path in sorted((PKG / "cases").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HAND_BUILT.search(line):
                findings.append(f"{path.name}:{n}: {line.strip()}")
    assert not findings, (
        "ключ справи зібрано f-рядком повз `_mk_key` — у фондах із `_OPYS_IN_KEY` "
        "такий ключ не несе опису й не влучає в реєстр:\n" + "\n".join(findings))


def test_opys_fond_keys_carry_opys(lib) -> None:
    """Для фонду з `_OPYS_IN_KEY` ключ без опису й ключ З описом — різні.

    ⚠ Цикл, а не `parametrize`: перелік фондів довелось би прочитати на
    збиранні, тобто імпортувати `library` у шапці — рівно те, що прив'язує
    бібліотеку до чужого простору (див. шапку файла).
    """
    _OPYS_IN_KEY, _mk_key = lib._OPYS_IN_KEY, lib._mk_key

    assert _OPYS_IN_KEY, "перелік фондів із описом у ключі порожній — тест сліпий"
    for repo, fond in sorted(_OPYS_IN_KEY):
        with_opys = _mk_key(repo, fond, "13", "3")
        without = _mk_key(repo, fond, "13")
        assert with_opys != without, f"{repo} ф.{fond}"
        assert with_opys == f"{repo}/{fond}-3/13"


def test_candidate_keys_offers_default_opys(lib) -> None:
    """Форма без опису мусить лишатись знаходжуваною через опис за замовчуванням.

    ID джерела канону (`S_<архів>_F<фонд>_D<справа>`) опису не несе — і без
    цього кандидата канон відв'язується від справи щойно фонд переходить на
    ключ-з-описом.
    """
    from nyshporka.library import _DEFAULT_OPYS, _OPYS_IN_KEY, candidate_keys

    for (repo, fond), default in _DEFAULT_OPYS.items():
        if (repo, fond) not in _OPYS_IN_KEY:
            continue
        keys = candidate_keys((repo, fond, None, "13"))
        assert f"{repo}/{fond}-{default}/13" in keys, (
            f"{repo} ф.{fond}: серед кандидатів немає форми з описом за "
            f"замовчуванням — канон і сховище сторінок відв'яжуться")
