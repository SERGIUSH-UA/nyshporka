"""🖋 Письмо справи: висновок мусить їхати разом із тим, на чому він стоїть.

Помилка тут не дає збою. Кириличний рушій на латинській книзі чесно видає
текст, впевненість не просідає, і виглядає це як погана якість сканів — тобто
людина шукає проблему не там, де вона є, а потім списує ненайдене прізвище на
модель.

Тому перевіряються дві речі, а не одна: що письмо визначено правильно і що
поруч стоїть РІВЕНЬ ДОВІРИ. «Кирилиця» з опису справи й «кирилиця» з імені
теки — різні відповіді, і плутати їх коштує ночі прогону.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.htr import pick


# ── порядок довіри ───────────────────────────────────────────────────────────
def test_fixed_description_beats_every_heuristic() -> None:
    """🔴 Записане в опису б'є жанр і роки — і саме там, де вони безсилі.

    Тримовна книга (російська рамка, латинські обляти, польські контракти) не
    має «свого» письма взагалі. Жанр і роки про це не скажуть; сказати може
    лише той, хто книгу бачив.
    """
    got = pick.guess_script({"script": "mixed", "langs": ["pl", "ru"],
                             "title": "Метрична книга", "year_from": 1850})
    assert got.script == "mixed", "опис справи програв евристиці"
    assert got.trust == "fixed"
    assert not got.is_guess, "зафіксоване письмо не є здогадом"
    assert "pl" in got.why, "мови з опису не доїхали в пояснення"


def test_genre_in_the_title_decides_before_the_years() -> None:
    """Жанр сильніший за епоху: нотаріат 1850-х лишається латинкою."""
    lat = pick.guess_script({"title": "Актова книга облят", "year_from": 1855})
    assert lat.script == "latin" and lat.trust == "genre"
    cyr = pick.guess_script({"title": "Сповідні розписи", "year_from": 1800})
    assert cyr.script == "cyrillic" and cyr.trust == "genre"


def test_both_genres_in_one_title_mean_two_scripts() -> None:
    """Латинський і кириличний жанр разом — це не «не знаю», а книга з двома."""
    got = pick.guess_script({"title": "Метрична книга костелу"})
    assert got.script == "mixed", (
        "книгу з двома жанрами зведено до одного письма — половина лишиться "
        "непрочитаною")


def test_epoch_answers_only_when_the_genre_is_silent() -> None:
    assert pick.guess_script({"year_to": 1810}).script == "latin"
    assert pick.guess_script({"year_from": 1870}).script == "cyrillic"
    assert pick.guess_script({"year_to": 1810}).trust == "epoch"


# ── головне: нуль лишається нулем ────────────────────────────────────────────
def test_silence_stays_silence_and_never_becomes_cyrillic() -> None:
    """🔴🔴 Не сказати нічого — повноцінна відповідь.

    Мовчазне «нехай буде кирилиця» коштує ночі прогону й теки правдоподібного
    сміття. Чесне «жанр і роки не дають відповіді» коштує одного погляду на
    скан. Саме цей дефолт стояв у попередній редакції й був її найслабшою
    ланкою.
    """
    got = pick.guess_script({"title": "Справа № 90"})
    assert got.script == "unknown", (
        "порожній опис дав упевнене письмо — це і є тиха помилка, від якої "
        "весь модуль")
    assert got.trust == "unknown"
    assert "оком" in got.why, "людині не сказано, що робити далі"


def test_folder_name_is_the_last_resort_and_admits_it(tmp_path: Path) -> None:
    """З імені теки видно мало, і це має бути написано в самій відповіді."""
    d = tmp_path / "spr-90"
    d.mkdir()
    got = pick.guess_script_for_dir(d)
    assert got.script == "unknown" and got.trust == "unknown"

    d2 = tmp_path / "f792_notarialne"
    d2.mkdir()
    got2 = pick.guess_script_for_dir(d2)
    assert got2.script == "latin"
    assert got2.trust == "folder"
    assert "здогад" in got2.why, "здогад не названо здогадом"


def test_a_human_hint_outranks_everything(tmp_path: Path) -> None:
    d = tmp_path / "f792_notarialne"
    d.mkdir()
    got = pick.guess_script_for_dir(d, "cyrillic")
    assert got.script == "cyrillic" and got.trust == "fixed"


# ── покриття рушіями ─────────────────────────────────────────────────────────
def test_covered_keeps_the_fullest_run_per_engine() -> None:
    """Із двох прогонів одним рушієм лишається той, що прочитав більше."""
    runs = [
        {"name": "a", "engine_id": "pysar", "pages_done": 10, "done": False},
        {"name": "b", "engine_id": "pysar", "pages_done": 400, "done": True},
        {"name": "c", "engine_id": "diak", "pages_done": 400, "done": True},
    ]
    got = pick.covered(runs)
    assert set(got) == {"pysar", "diak"}
    assert got["pysar"]["run"] == "b", "перелік узяв менш повний прогін"


def test_gaps_speak_three_different_sentences() -> None:
    """🔴 «Прогін є» мовчки читається як «справу прочитано».

    Саме так половина книги з двома письмами лишається непрочитаною. Тому
    «бракує рушія» і «рушій не той» мусять бути РІЗНИМИ відповідями, а не
    спільним «щось не так».
    """
    engines = {e["id"] for e in pick.engines_for("cyrillic")}
    if not engines:
        pytest.skip("маніфест рушіїв недоступний")

    empty = pick.gaps("cyrillic", {})
    assert empty and all(g["kind"] == "missing" for g in empty), (
        "непрочитана справа не сказала, яких саме рушіїв бракує")

    wrong = pick.gaps("cyrillic", {"skryba": {"run": "x", "pages_done": 5}})
    kinds = {g["kind"] for g in wrong}
    assert "mismatch" in kinds, (
        "прогін чужим письмом не позначено — його текст може бути тихим "
        "сміттям, а в переліку він виглядає як прочитана справа")
    mism = next(g for g in wrong if g["kind"] == "mismatch")
    assert "сміт" in mism["why"], "ціна невідповідності не названа"


def test_mixed_script_asks_for_both_engines() -> None:
    """Книга з двома письмами вимагає ДВОХ прогонів, і це видно з переліку."""
    got = {e["script"] for e in pick.engines_for("mixed")}
    if not got:
        pytest.skip("маніфест рушіїв недоступний")
    assert got == {"latin", "cyrillic"}, (
        f"для мішаного письма запропоновано лише {got}")
