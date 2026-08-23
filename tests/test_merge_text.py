"""🔤 Чисті згортки злиття: пороги, ключі, зведення файлів.

Числа в назвах тестів — заміри на живих фондах. Вони тут не для історії: без них
наступний «оптимізує» поріг і дістане тисячі хибних розбіжностей у черзі ока.
"""
from __future__ import annotations

import json

import pytest

from nyshporka.fonds.merge import scans as S
from nyshporka.fonds.merge import text as T


# ── схожість заголовків ──────────────────────────────────────────────────────
def test_abbreviations_stop_a_pair_from_looking_like_a_conflict() -> None:
    """Розкриття скорочень ДОДАЄ спільних токенів. На ф.224 без нього пара
    «опис архіву ↔ транскрипція» давала 642 хибні розбіжності з 642."""
    a = "Метрична книга ц. Різдва с. Вербка Ольгопільського пов."
    b = "Метрична книга церкви Різдва села Вербка Ольгопільського повіту"
    assert T.token_set_ratio(a, b) >= 0.45


def test_the_ratio_is_symmetric_and_empty_means_zero() -> None:
    a, b = "Метрична книга", "Сповідний розпис"
    assert T.token_set_ratio(a, b) == T.token_set_ratio(b, a)
    assert T.token_set_ratio("", "будь-що") == 0.0


def test_ocr_confusions_do_not_split_the_same_title() -> None:
    """Класи плутанини відкалібровані під машинопис цих описів: «щ»↔«ш»,
    тверді знаки, «о»↔«0»."""
    assert T.norm_title("Общiй списокъ") == T.norm_title("Обшiй список")


# ── села ─────────────────────────────────────────────────────────────────────
def test_a_village_is_read_from_the_title() -> None:
    assert T.village_of("Метрична книга с. Вербка Ольгопільського повіту") == "вербка"
    assert T.village_of("Родовідна книга дворян") == ""


@pytest.mark.parametrize("village,text,same", [
    # каталог пише повну форму, назва файлу — коротку
    ("Вербка-Волоська", "ДАХмО 230-1-5. с. Вербка", True),
    # різна орфографія кореня: о/а
    ("Стара Гарячківка", "ЦДІАК 224-1-9. с. Горячківка", True),
    # різні села
    ("Вільшанка", "ЦДІАК 224-1-9. с. М'ястківка", False),
])
def test_villages_are_compared_word_by_word(village: str, text: str, same: bool) -> None:
    assert T.village_matches(village, text) is same


def test_nothing_to_compare_means_silence_not_accusation() -> None:
    """🔴 Самі короткі слова («Нова», «Мала») відкидаються, бо є в десятках
    назв. Коли після відсіву не лишилось нічого, ми МОВЧИМО, а не звинувачуємо:
    інакше черга ока наповнилась би там, де порівняти було нічим."""
    assert T.village_matches("Нова", "с. Мала") is True


# ── ключі справ ──────────────────────────────────────────────────────────────
def test_a_latin_letter_index_is_the_same_case_as_the_cyrillic_one() -> None:
    """🔴 Заміряно на ф.230 спр.24а: в описі літера кирилична, а в назві файлу
    на Вікісховищі — латинська, бо так набрав заливач. Реєстр роздвоював справу:
    рядок із заголовком без скана і рядок зі сканом без заголовка — і обидва
    йшли в чергу завантаження як окремі позиції."""
    assert T.key_of({"opys": "1", "spr_int": "24", "spr_letter": "a"}) == ("1", "24", "а")
    assert T.key_of({"opys": "1", "spr_int": "24", "spr_letter": "а"}) == ("1", "24", "а")


def test_a_solid_number_field_is_understood() -> None:
    """Алфавітка й індекс плівок пишуть номер суцільно: «1280а»."""
    assert T.key_of({"opys": "1", "spr": "1280а"}) == ("1", "1280", "а")


def test_a_row_that_is_not_a_case_gives_no_key() -> None:
    assert T.key_of({"opys": "", "spr_int": "5"}) is None
    assert T.key_of({"opys": "1", "spr": "вільний номер"}) is None


def test_a_non_numeric_inventory_does_not_break_sorting() -> None:
    """⚠ Описи бувають «Л2», «ОРП41» — на `int()` це клало всю перезбірку, тобто
    одна дивна позиція гасила решту фонду."""
    got = sorted(["Л2", "2", "10", "ОРП41", "1"], key=T.opys_sort)
    assert got == ["1", "2", "10", "Л2", "ОРП41"]


# ── зведення файлів Commons ──────────────────────────────────────────────────
@pytest.mark.parametrize("name,volume", [
    ("ДАХмО 315-1-7864. Частина 2.pdf", True),
    ("ДАХмО 315-1-8534 Т1.pdf", True),
    ("ДАХмО 315-1-7345. Сповідний розпис села Побірка.pdf", False),
])
def test_only_an_explicit_marker_means_a_volume(name: str, volume: bool) -> None:
    assert S.is_volume(name) is volume


def test_volumes_are_summed_variants_are_not() -> None:
    """🔴 Заміряно: спр.7864 це 1217+1313+1242 = 3772 стор. (томи), а спр.7345 —
    3291, бо витяг парафії на 30 стор. показує ті самі аркуші вдруге."""
    vols = S.aggregate_commons([
        {"file": "спр.7864 Частина 1.pdf", "size": "100", "pagecount": "1217"},
        {"file": "спр.7864 Частина 2.pdf", "size": "90", "pagecount": "1313"},
        {"file": "спр.7864 Частина 3.pdf", "size": "80", "pagecount": "1242"}])
    assert vols["commons_kind"] == "volumes"
    assert vols["commons_pages"] == "3772"

    vars_ = S.aggregate_commons([
        {"file": "спр.7345.pdf", "size": "900", "pagecount": "3291"},
        {"file": "спр.7345 Сповідний розпис села Побірка.pdf",
         "size": "10", "pagecount": "30"}])
    assert vars_["commons_kind"] == "variants"
    assert vars_["commons_pages"] == "3291", "витяг парафії додався до тому"


def test_the_biggest_file_names_the_case() -> None:
    """Витяг парафії назвав би справу СЕЛОМ ВИТЯГУ — тому назва береться з
    найбільшого файлу, а не з першого за абеткою."""
    out = S.aggregate_commons([
        {"file": "А. витяг села Побірка.pdf", "size": "10", "pagecount": "30"},
        {"file": "Я. повний том.pdf", "size": "900", "pagecount": "3291"}])
    assert out["commons_title"] == "Я. повний том.pdf"


def test_one_file_case_stays_plain() -> None:
    out = S.aggregate_commons([{"file": "спр.6664.pdf", "size": "5", "pagecount": "12"}])
    assert out["commons_kind"] == "" and out["commons_parts"] == ""
    assert out["commons_pages"] == "12"


def test_parts_say_which_of_them_were_counted() -> None:
    out = S.aggregate_commons([
        {"file": "том.pdf", "size": "900", "pagecount": "3291"},
        {"file": "витяг.pdf", "size": "10", "pagecount": "30"}])
    parts = json.loads(out["commons_parts"])
    assert [p["sum"] for p in parts] == [True, False]
