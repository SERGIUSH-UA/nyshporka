"""🔎 Індекс декоду: свіжість, знаменник і те, що він нічого не міняє в хітах.

🔴 Головне твердження файлу — індекс не є оптимізацією «майже без наслідків».
Він переписав шлях пошуку: раніше кандидати будувались у памʼяті при кожному
запиті, тепер читаються з диска. Якщо при цьому змінився бодай один хіт,
виграш у часі не вартий нічого: пошук по декоду — те місце, де нуль закриває
напрям дослідження.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Простір із одним прогоном на дві сторінки."""
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    run = tmp_path / "reports" / "htr" / "проба"
    run.mkdir(parents=True)
    (run / "0001.txt").write_text(
        "въ селѣ Липовенькомъ\nродился Иванъ\n", encoding="utf-8")
    (run / "0002.txt").write_text(
        "Липовень\nкомъ приходѣ\n", encoding="utf-8")
    (run / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {"0001.jpg": {"lines": 2}, "0002.jpg": {"lines": 2}},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W.reset()


def test_the_index_finds_exactly_what_the_plain_scan_finds(space) -> None:
    """🔴 Той самий набір рядків і ті самі бали — інакше виграш нічого не вартий."""
    from rapidfuzz import fuzz

    from nyshporka import htr_store as S
    from nyshporka.search import decode as D

    stem = S._norm("Липовеньке")
    assert D.ensure("проба"), "індекс не зібрався"
    got = D.sweep([stem], ["проба"], thresh=78)

    # те саме, але простим перебором по тих самих кандидатах
    plain = {}
    for page, ln, _raw, cands in S._case_index("проба"):
        best = 0.0
        for _w, norm in cands:
            if len(norm) < max(4, int(len(stem) * 0.6)):
                continue
            sc = fuzz.ratio(norm, stem)
            if len(norm) >= len(stem):
                sc = max(sc, fuzz.partial_ratio(norm, stem))
            best = max(best, sc)
        if best >= 78:
            plain[(page, ln)] = round(best)

    mine = {(h["page"], h["line_no"]): h["score"] for h in got["hits"]}
    assert mine == plain, "індекс і прямий перебір розійшлись"
    assert plain, "перевірка беззмістовна: прямий перебір нічого не знайшов"


def test_a_reread_run_rebuilds_its_own_index(space) -> None:
    """🔴 Свіжість — штампом, а не часом життя.

    Дочитану справу пошук мусить бачити одразу. Кеш «на N хвилин» показував би
    щойно прочитану сторінку як неіснуючу — тобто брехав би саме там, де людина
    щойно працювала.
    """
    from nyshporka.search import decode as D

    assert D.ensure("проба")
    first = D.index_path("проба")
    assert first.is_file()

    run = space / "reports" / "htr" / "проба"
    (run / "0003.txt").write_text("ще одна сторінка\n", encoding="utf-8")
    meta = run / "_htr_meta.json"
    meta.write_text(meta.read_text(encoding="utf-8"), encoding="utf-8")

    assert not D.is_fresh("проба"), "індекс не помітив дочитаної справи"
    assert D.ensure("проба")
    assert D.index_path("проба") != first, "штамп не змінився після дочитування"
    assert not first.is_file(), "старий індекс лишився на диску"


def test_search_names_what_stayed_outside_it(space) -> None:
    """🔴 Нуль на частковому індексі — не той самий нуль, що на повному.

    Пошук чеше лише зібране. Якщо не сказати, скільки лишилось поза ним,
    відповідь виглядає повною — а закривають за нею напрям, якого не
    перевіряли.
    """
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D

    got = D.sweep([S._norm("Липовеньке")], ["проба"], thresh=78, build_budget=0)
    assert got["scanned"] == 0
    assert got["unindexed"] == 1, "незібраний прогін не потрапив у знаменник"

    got = D.sweep([S._norm("Липовеньке")], ["проба"], thresh=78, build_budget=1)
    assert got["scanned"] == 1
    assert got["unindexed"] == 0


def test_the_index_keeps_only_normalised_forms(space) -> None:
    """⚠ У файлі немає ні самого рядка, ні показаного слова — і це навмисно.

    Саме тому індекс у рази менший за текст. Слово відновлюється зі сторінки
    вже після того, як хіт знайдено.
    """
    import gzip

    from nyshporka.search import decode as D

    assert D.ensure("проба")
    with gzip.open(D.index_path("проба"), "rt", encoding="utf-8") as fh:
        body = fh.read()
    assert "Липовенькомъ" not in body, "у індексі лежить сирий текст"
    assert "lipovenkom" in body, "нормалізованих форм у індексі немає"


def test_normalisation_did_not_change_while_getting_faster() -> None:
    """🔴 Нормалізацію переписали заради швидкості — вона мусить давати ТЕ саме.

    Вона вирішує, що вважати одним словом, тобто визначає сам набір знахідок.
    Зсув тут — не «трохи інші бали»: пари, які досі сходились на 90, розходяться
    нижче порога, і зникнення хіта нічим не супроводжується. Тому форми
    прибиті цвяхом.

    ⚠ Це еталон поведінки, а не задуму. Латинка й кирилиця тут сходяться не
    повністю (`vujcik` проти `vuicik`, `sicorski` проти `sikorskii`) — решту
    відстані добирає сам fuzzy-матчер, і саме тому поріг такий, який він є.
    Правити ці рядки можна лише разом із перезбіркою всіх індексів.
    """
    from nyshporka.utils.translit import normalize_archival as na
    from nyshporka.utils.translit import normalize_for_matching as nm

    for raw, want in [
        ("Szczurowski", "scurovski"),        # PL-диграфи: szcz→sc, w→v
        ("Щуровський", "scurovskii"),        # та сама пара з кирилиці
        ("Sicorschi", "sicorski"),           # румунський хвіст -schi→-ski
        ("Wójcik", "vujcik"),
        ("Lubkowski", "lubkovski"),
        ("Лубковскій", "lubkovskii"),
        ("Dolszczynski", "dolscinski"),
        ("  два   слова  ", "dva slova"),    # пробіли стискаються
        ("одне", "odne"),                    # а без них рядок не чіпається
    ]:
        assert nm(raw) == want, f"{raw}: {nm(raw)!r} замість {want!r}"

    # Архівний фолд поверх того самого: історичні літери й плутанини рушія.
    for raw, want in [("въ селѣ", "v sele"), ("Ѳедоръ", "fedor"),
                      ("q", "g"), ("9", "g"), ("0", "o")]:
        assert na(raw) == want, f"{raw}: {na(raw)!r} замість {want!r}"
    # 🔴 Без фолду історична літера лишається собою — це різні функції, і
    # сховище прочитаного користується саме архівною.
    assert nm("Ѳедоръ") != na("Ѳедоръ")


# ── знаменник: та сама область, що й чисельник ───────────────────────────────
def _second_voice(space: Path, name: str, case_key: str, pages: int) -> None:
    """Ще один прогін тієї самої справи іншим голосом."""
    import json as _json

    run = space / "reports" / "htr" / name
    run.mkdir(parents=True)
    for i in range(1, pages + 1):
        (run / f"{i:04d}.txt").write_text("Липовень\n", encoding="utf-8")
    (run / "_htr_meta.json").write_text(_json.dumps({
        "model": "diak_cyr_v4.mlmodel", "script": "cyrillic",
        "case_key": case_key,
        "pages": {f"{i:04d}.jpg": {"lines": 1} for i in range(1, pages + 1)},
    }), encoding="utf-8")

    from nyshporka import htr_store as S

    S._CACHE.clear()
    S._RUNS_CACHE = None


def test_two_voices_do_not_double_the_denominator(space) -> None:
    """🔴 Знаменник, більший за наявне, гірший за відсутній.

    Справу з двома письмами читають двома голосами, і кожен проходить ті самі
    аркуші. Поки знаменник був сумою `pages_done`, справа на три сторінки
    відповідала «не знайшлось у 6 сторінках» — тобто виглядала прочесаною
    удвічі ширше, ніж є, і саме за таким числом закривають напрям.
    """
    from nyshporka import htr_store as S

    _second_voice(space, "проба-дяк", "DAHMO/315/159", 2)
    rows = [r for r in S.list_cases() if r["name"] in ("проба", "проба-дяк")]
    assert len(rows) == 2
    assert sum(r["pages_done"] for r in rows) == 4, "фікстура: два голоси по дві"
    # Обидва прогони нічийні за текою, але один несе ключ — групування мусить
    # тримати їх окремо лише доти, доки справа справді різна.
    assert S.unique_pages(rows[:1]) == 2
    both = [dict(r, case_key="DAHMO/315/159") for r in rows]
    assert S.unique_pages(both) == 2, "два голоси однієї справи подвоїли знаменник"


def test_an_unbound_run_still_counts_for_itself(space) -> None:
    """⚠ Нічийні прогони не можна зливати в одну групу.

    Ключа немає в обох — але це різні справи, і взявши з них максимум, ми
    втратили б знаменник саме там, де він найкрихкіший.
    """
    from nyshporka import htr_store as S

    rows = [{"name": "а", "case_key": "", "case_dir": "", "pages_done": 3},
            {"name": "б", "case_key": "", "case_dir": "", "pages_done": 4}]
    assert S.unique_pages(rows) == 7


def test_the_scope_narrows_to_the_asked_case(space) -> None:
    """🔴 Шукали в справі — звітували обсягом усього простору.

    Чисельник звужувався під `--case`, знаменник — ні. «Не знайшлось у 1
    прогонах (320 669 сторінок)» — це нуль із чужим алібі.
    """
    from nyshporka import htr_store as S

    _second_voice(space, "проба-дяк", "DAHMO/315/159", 2)

    everything = S.runs_for_scope("")
    assert everything["kind"] == "all" and len(everything["rows"]) == 2

    one = S.runs_for_scope("проба")
    assert one["kind"] == "run" and [r["name"] for r in one["rows"]] == ["проба"]
    assert S.unique_pages(one["rows"]) == 2, "знаменник узяв чужі прогони"


def test_a_case_key_reaches_the_run_a_folder_name_never_would(space) -> None:
    """🔴 Ключ справи не резолвився в жодну теку — і пошук чесно віддавав нуль.

    Кнопка «шукати в цій справі» шле саме ключ. Доти, доки область пошуку
    приймала лише ім'я теки прогону, вона давала нуль хітів на справі, де рід
    є, — з попередженням «не знайшлось у 0 прогонах», яке читається як
    відповідь.
    """
    from nyshporka import htr_store as S

    _second_voice(space, "проба-дяк", "DAHMO/315/159", 2)

    got = S.runs_for_scope("DAHMO/315/159")
    assert got["kind"] == "case"
    assert [r["name"] for r in got["rows"]] == ["проба-дяк"]
    assert got["key"] == "DAHMO/315/159"


def test_an_unknown_scope_is_refused_by_name(space) -> None:
    """Відмова нормативна: мовчазний пошук по всьому корпусу не є відповіддю
    на питання про одну справу."""
    import pytest as _pytest

    from nyshporka import htr_store as S

    with _pytest.raises(ValueError) as exc:
        S.runs_for_scope("щось-чого-немає")
    assert "не розпізнав" in str(exc.value)


def test_the_hit_carries_the_case_not_just_the_folder(space) -> None:
    """🔴 Ім'я прогону — не адреса справи.

    Доти, доки хіт не ніс ключа, кожен споживач добудовував його сам: кнопка
    «занести в облік» слала назву теки й діставала нормативну відмову, а
    колонка «шифра» показувала ту саму назву теки.
    """
    from nyshporka import htr_store as S

    _second_voice(space, "проба-дяк", "DAHMO/315/159", 2)
    got = S.search("Липовень", name="проба-дяк", thresh=78)
    assert got["hits"], "фікстура: хіт мусить бути"
    assert got["hits"][0]["case_key"] == "DAHMO/315/159"
    assert got["pages"] == 2, "знаменник їде з тієї самої відповіді"
