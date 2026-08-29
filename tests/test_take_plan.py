"""📥 Куди лягає взята справа і чому саме таким каналом.

🔴 Модуль мав НУЛЬ покриття, і ціна цього не теоретична: він рахує теку
призначення й читає реєстр опису. Помилка тут — це або дубль зйомки в другому
дереві поруч із наявним, або тека-сирота, або «опису не зібрано» при наявному
файлі. Жодне з трьох не падає гучно: людина бачить порожній план і йде
замовляти в архіві те, що вже лежить на диску.

Мережі тут немає взагалі — `plan()` існує рівно для того, щоб відповідь «каналу
немає» коштувала нуль секунд.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.cases import take as T
from nyshporka.core import workspace as W


@pytest.fixture
def space(tmp_path: Path) -> Path:
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    return tmp_path


# ── тека призначення ─────────────────────────────────────────────────────────
def test_the_folder_is_computed_from_the_reference_not_the_address(space):
    """Тека з шифри, а не з посилання: другу знаходить бібліотека, першу — лише
    той, хто пам'ятає, звідки качав."""
    got = T.case_dir_for("DAHMO", "315", "8433", "")
    assert got == space / "data" / "raw" / "dahmo_315" / "spr-8433"


def test_a_letter_in_the_case_number_stays_in_the_folder_name(space):
    """«2а» і «2» — різні справи, і теки в них мусять бути різні."""
    a = T.case_dir_for("DAHMO", "230", "2", "а")
    b = T.case_dir_for("DAHMO", "230", "2", "")
    assert a != b and a.name == "spr-2а" and b.name == "spr-2"


def test_both_codes_of_one_archive_land_in_the_same_folder(space):
    """🔴 Канонічний код архіву змінився, а тека на диску лишилась.

    Якби `DAVIO` дав власний slug, узята справа поїхала б у НОВЕ дерево поруч
    із наявним `davo_904`: ті самі кадри двічі, і жодного слова про це.
    """
    assert T.case_dir_for("DAVIO", "904", "131", "") == \
           T.case_dir_for("DAVO", "904", "131", "")


def test_an_unknown_archive_still_gets_a_folder(space):
    """Код, якого немає в переліку slug'ів, не має ламати взяття."""
    got = T.case_dir_for("AGAD", "1", "2", "")
    assert got.parent.name == "agad_1"


# ── вибір каналу ─────────────────────────────────────────────────────────────
def _row(**kw):
    base = {"title": "Метрична книга", "year_from": "1858"}
    return {**base, **kw}


def test_the_viewer_wins_over_commons(space):
    """🔴 Канал обирається за ШВИДКІСТЮ, а не за порядком перевірок у коді.

    Переглядач архіву віддає посторінкові JPG, Commons — один файл на сотні
    мегабайтів. Доки перевірявся лише Commons, ЦДІАК ф.224 виглядав фондом
    майже без сканів: 42 справи з 2950, а понад тисяча стояла в черзі
    «замовлення в архіві», лежачи при цьому онлайн.
    """
    p = T._plan_from("CDIAK", "224", "1", "864", "",
                     _row(archium_url="https://a/1", commons_title="File:X.pdf"))
    assert p["channel"] == "archium"
    assert p["ref"] == "https://a/1"


def test_commons_is_taken_when_the_viewer_has_nothing(space):
    p = T._plan_from("CDIAK", "224", "1", "864", "", _row(commons_title="File:X.pdf"))
    assert p["channel"] == "commons" and p["ref"] == "File:X.pdf"


def test_no_channel_says_what_to_do_instead(space):
    """«Нічого не вийшло» — не відповідь. Кожен глухий випадок називає причину."""
    plain = T._plan_from("DAHMO", "315", "1", "1", "", _row())
    assert plain["channel"] == "" and "замовляють в архіві" in plain["why"]

    film = T._plan_from("DAHMO", "315", "1", "1", "", _row(fs_dgs="7654321"))
    assert film["channel"] == "" and "7654321" in film["why"]
    assert "плівк" in film["why"], "плівку треба назвати саме плівкою"

    mirror = T._plan_from("DAHMO", "315", "1", "1", "", _row(mirror_url="https://m/1"))
    assert mirror["channel"] == "" and "обрізає" in mirror["why"], (
        "дзеркало мусить попередити, що ріже великі справи")


def test_an_interpolated_number_travels_with_the_plan(space):
    """🔴 Узяти можна, вірити шифрі — ні, доки її не звірили оком.

    Номер справи, відновлений інтерполяцією, мусить їхати разом із планом:
    інакше він мовчки стане ключем, під яким лягне облік прочитаного.
    """
    p = T._plan_from("DAHMO", "230", "3", "13", "",
                     _row(archium_url="https://a/1", num_src="interp"))
    assert p["shifra_needs_eye"] is True
    assert T._plan_from("DAHMO", "230", "3", "13", "",
                        _row(archium_url="https://a/1"))["shifra_needs_eye"] is False


def test_a_case_missing_from_the_registry_names_the_file_it_looked_in(space):
    """Відмова мусить казати, ДЕ шукали: «опису не зібрано» без імені файла
    неможливо ні перевірити, ні полагодити."""
    with pytest.raises(T.TakeError) as e:
        T.plan("DAHMO/315/8433")
    msg = str(e.value)
    assert "не зібраний" in msg and "dahmo_315" in msg, msg


def test_a_broken_key_is_refused_with_examples(space):
    with pytest.raises(T.TakeError) as e:
        T.plan("щось не те")
    assert "не розумію ключ" in str(e.value)
