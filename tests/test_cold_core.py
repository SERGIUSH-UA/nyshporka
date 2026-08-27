"""Холодне ядро: моделі, сховище, матчинг, транслітерація, морфологія.

«Холодне» — це не про важливість, а про залежності: ці модулі не тягнуть ні
FastAPI, ні torch, ні знання про конкретний архів. Саме тому вони переїхали в
публічний пакет першими.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys

import pytest

MODULES = [
    "nyshporka.ids",
    "nyshporka.utils.translit",
    "nyshporka.utils.text",
    "nyshporka.models",
    "nyshporka.storage.files",
    "nyshporka.matching.fuzzy",
    "nyshporka.core.workspace",
    "nyshporka.core.resources",
    "nyshporka.core.morph",
    "nyshporka.core.profile",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_cold_core_stays_cold():
    """🔴 Жоден із них не має тягнути важке.

    Не естетика: щойно ядро почне імпортувати torch, `nysh` стартуватиме
    секундами, а «подивитись каталог справ» вимагатиме кількох гігабайтів.

    🔴 Перевірка йде в окремому процесі, і це не педантизм. Раніше тут
    читався `sys.modules` спільного процесу pytest — тобто тест доводив не
    «ядро холодне», а «до цього моменту ніхто не імпортував важкого». Він
    зеленів, поки в наборі не з'явився тест демона, який чесно тягне FastAPI;
    після цього почав червоніти на рівному місці, нічого не знайшовши в ядрі.
    """
    code = (
        "import importlib, sys, json\n"
        f"for name in {list(MODULES)!r}:\n"
        "    importlib.import_module(name)\n"
        "heavy = [h for h in ('torch', 'fastapi', 'ultralytics', 'transformers',"
        " 'mkdocs') if h in sys.modules]\n"
        "print(json.dumps(heavy))\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    pulled = json.loads(res.stdout.strip().splitlines()[-1])
    assert not pulled, f"холодне ядро притягло {pulled}"


# ── транслітерація ───────────────────────────────────────────────────────────
def test_cyrillic_spellings_fold_to_exactly_one_word():
    """Українське, російське й дореформене написання — один рядок.

    Це головна властивість нормалізатора: у метриках той самий рід записаний
    то «Сікорський», то «Сикорский», то «Сикорскій», і без згортки пошук за
    однією формою пропускав би дві інші.
    """
    from nyshporka.utils.translit import normalize_for_matching as n

    assert n("Сікорський") == n("Сикорский") == n("Сикорскій")


def test_latin_spellings_land_within_fuzzy_reach_not_on_identity():
    """🔴 Латинка не зводиться до кирилиці дослівно — і не має.

    Заміряно: укр.↔пол. 94, укр.↔рум. 82. Нормалізація тут не робить рядки
    однаковими, вона прибирає системну відстань (діакритику, sz/cz), щоб
    решту добрав фаззі. Тест на рівність був би хибним і змусив би «полагодити»
    нормалізатор так, що він почав би зливати різні прізвища.
    """
    from rapidfuzz import fuzz

    from nyshporka.utils.translit import normalize_for_matching as n

    assert fuzz.ratio(n("Сікорський"), n("Sikorski")) >= 90
    assert fuzz.ratio(n("Сікорський"), n("Sicorschi")) >= 80
    # А ось чуже прізвище має лишатись чужим.
    assert fuzz.ratio(n("Сікорський"), n("Яворський")) < 80


def test_archival_fold_joins_historical_letters():
    from nyshporka.utils.translit import normalize_archival as n

    assert n("Ѳеодоръ") == n("Феодор")
    assert n("Сікорскій") == n("Сикорский")


def test_slugify_is_ascii_lowercase_and_stable():
    """Slug має бути передбачуваним, а не гарним: за ним лежать імена файлів."""
    from nyshporka.utils.text import slugify

    slug = slugify("Сікорський, Іван")
    assert slug == slugify("Сікорський, Іван"), "slug мусить бути детермінованим"
    assert slug.isascii() and slug == slug.lower()
    assert not slug.startswith("-") and not slug.endswith("-")
    assert "ivan" in slug
    assert slugify("  ---  ") == ""


# ── ідентифікатори ───────────────────────────────────────────────────────────
def test_ids_are_zero_padded_to_four():
    from nyshporka import ids

    assert ids.person_id(1).startswith("I") and len(ids.person_id(1)) == 5
    assert ids.family_id(42)[1:] == "0042"
    assert ids.place_id(7).startswith("PL")
    assert ids.source_id("dahmo-f315") == "dahmo-f315"


# ── морфологія ───────────────────────────────────────────────────────────────
def test_paradigm_generates_full_case_table():
    """Сім відмінків × два роди з однієї основи — те, заради чого генератор."""
    from nyshporka.core import morph

    forms = morph.paradigm("adj_skyi").forms("Сікор", "uk")
    assert forms["nom_m"] == "Сікорський"
    assert forms["gen_m"] == "Сікорського"
    assert forms["nom_f"] == "Сікорська"
    assert forms["ins_f"] == "Сікорською"
    for case in morph.CASES:
        for gender in morph.GENDERS:
            assert f"{case}_{gender}" in forms


def test_orthographies_differ_where_they_should():
    from nyshporka.core import morph

    p = morph.paradigm("adj_skyi")
    assert p.form("Сикор", "nom_m", "ru_modern") == "Сикорский"
    assert p.form("Сикор", "nom_m", "ru_prereform") == "Сикорскій"
    assert p.form("Сікор", "nom_m", "uk") == "Сікорський"
    assert p.form("Sikor", "nom_m", "pl") == "Sikorski"


def test_hyphenation_returns_all_three_pieces():
    """Голова й хвіст трапляються в декоді окремо, на різних рядках."""
    from nyshporka.core import morph

    assert morph.hyphenate("Сікорський", 4) == ("Сіко- рський", "Сіко-", "рський")


def test_target_ladder_discounts_truncated_roots():
    from nyshporka.core import morph

    got = morph.htr_targets("сікорськ")
    assert got[0] == ("сікорськ", 1.0)
    assert [w for _, w in got] == [1.0, 0.85, 0.65, 0.45]
    assert all(t for t, _ in got), "порожній таргет зробив би пошук всеїдним"


def test_the_bare_stem_paradigm_matches_the_books():
    """🔴 Золотий набір із issue #2 — саме ті написання, що заміряні в книгах.

    `Лут`/`Лутъ` 1330+92×, `Лута` 6×, `Лутова` 100× (метрики 1855-1922, прямим
    вибиранням із розібраних архівних CSV). Ключове тут — що жіноча форма
    ОКРЕМА, а не збігається з родовим чоловічим.
    """
    from nyshporka.core import morph

    f = morph.paradigm("noun_bare").forms("Лут", "ru_prereform")
    assert f["nom_m"] == "Лутъ"
    assert f["gen_m"] == "Лута"
    assert f["nom_f"] == "Лутова"
    assert f["gen_m"] != f["nom_f"], "дві різні форми злились в одну"


def test_the_ko_paradigm_declines_instead_of_standing_still():
    """🔴 Прізвища на -ко в цих книгах ВІДМІНЮЮТЬСЯ.

    Доти єдиною безпечною відповіддю на них була `indeclinable` — і вона мовчки
    не породжувала ні родового, ні жіночого. Причому саме «Шевченко» стояв у її
    підписі прикладом, тобто підпис вів рівно в цю пастку.

    ⚠ Основа тут БЕЗ «-о»: інакше родовий дав би «Чипенкоа».
    """
    from nyshporka.core import morph

    f = morph.paradigm("noun_ko").forms("Чипенк", "ru_prereform")
    assert (f["nom_m"], f["gen_m"], f["nom_f"]) == ("Чипенко", "Чипенка", "Чипенкова")
    assert morph.paradigm("noun_ko").form("Завалк", "nom_f", "ru_prereform") == "Завалкова"
    assert "Шевченко" not in morph.paradigm("indeclinable").label


def test_the_possessive_paradigm_still_cannot_do_a_bare_stem():
    """Чому знадобились нові парадигми — зафіксовано як поведінка, а не як текст.

    `noun_ov` моделює прізвище, де «-ов-» УЖЕ в основі (Иванов → Иванова). На
    голій основі вона видає родовий чоловічий і називний жіночий однаковими, а
    на основі з голосною — форму, неможливу за жодних правил.
    """
    from nyshporka.core import morph

    f = morph.paradigm("noun_ov").forms("Лут", "ru_prereform")
    assert f["gen_m"] == f["nom_f"] == "Лута", "саме цей збіг і був приводом"
    assert morph.paradigm("noun_ov").form("Чипенко", "nom_m", "ru_prereform") == "Чипенкоъ"


def test_every_paradigm_declares_a_whole_table():
    """🔴 Перебір УСІХ парадигм, а не перелічених поіменно.

    Доти приймачі називали дві з трьох, і `indeclinable` не перевіряла жодна.
    Через це нова парадигма не покривалась би нічим — а неповна таблиця дає
    тиху діру: `form()` на відсутньому коді повертає None, і написання просто
    не з'являється.
    """
    from nyshporka.core import morph

    for pid, par in morph.PARADIGMS.items():
        assert par.endings, f"{pid}: жодної орфографії"
        for orth, table in par.endings.items():
            assert orth in morph.ORTHOGRAPHIES, f"{pid}: невідома орфографія {orth}"
            for case in morph.CASES:
                for gender in morph.GENDERS:
                    code = f"{case}_{gender}"
                    assert code in table, f"{pid}/{orth}: немає {code}"


def test_unverified_paradigms_say_so():
    """⚠ Заготовки не мають виглядати як перевірені: на них ще не міряли."""
    from nyshporka.core import morph

    assert morph.paradigm("adj_skyi").verified
    assert not morph.paradigm("noun_ov").verified


# ── робочий простір ──────────────────────────────────────────────────────────
def test_no_private_default_case_roots(tmp_path):
    """🔴 Додаткові корені зі справами — це завжди чиясь конкретна машина.

    У дослідницькому репо тут стояв особистий шлях автора до архіву на іншому
    диску. У пакеті дефолт мусить бути порожній: хто тримає архів окремо,
    вписує його в маркер свого простору.
    """
    from nyshporka.core import workspace as W

    deep = tmp_path / "Нишпорка" / "Мій рід"
    (deep / "data").mkdir(parents=True)
    ws = W.resolve(deep)
    assert ws.case_roots() == [ws.raw]


def test_workspace_refuses_dangerous_roots():
    """🔴 Гард шляхів пропускає все, що під коренем простору.

    А шлях у в'ювер сторінок приходить із HTTP-запиту. Простір, що дорівнює
    диску чи домівці, перетворює цей гард на «дозволено все» — і зламаною
    виявляється не програма, а межа між нею й рештою диска.

    ⚠ Перелік залежить від платформи, і це не дрібниця: `"C:/"` на Linux — це
    не корінь диска, а звичайна відносна назва, тож перевірка там доводила б
    рівно нічого. Спіймано на CI: тест зеленів на Windows і падав на Linux.
    """
    import os
    from pathlib import Path

    from nyshporka.core import workspace as W

    bad = [str(Path.home()), os.path.abspath(os.sep)]
    bad += ["C:/", "C:\\"] if os.name == "nt" else ["/", "/home", "/usr", "/etc"]
    for path in bad:
        with pytest.raises(W.WorkspaceError):
            W.validate_root(Path(path))


def test_missing_workspace_fails_loudly_not_silently(tmp_path, monkeypatch):
    """Мовчазна робота «в нікуди» гірша за чесну відмову."""
    from nyshporka.core import workspace as W

    monkeypatch.delenv(W.ENV_WORKSPACE, raising=False)
    monkeypatch.delenv(W.ENV_LEGACY_WORKSPACE, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(W, "_PACKAGE_ANCHOR", tmp_path / "nowhere")
    monkeypatch.setattr(W, "_load_last_used", lambda: None)
    with pytest.raises(W.WorkspaceError) as exc:
        W.resolve()
    # Повідомлення мусить казати, що зробити, а не лише що зламалось.
    assert W.MARKER in str(exc.value) and "--workspace" in str(exc.value)
