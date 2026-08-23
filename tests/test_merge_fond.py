"""Злиття джерел опису в реєстр фонду — на синтетичному фонді.

🔴 Фонд ЦДІАК 999 вигаданий, і це навмисно: справжні реєстри лежать у
дослідницькому репозиторії, тож тест на них був би зеленим лише в того, у кого
той репозиторій під рукою. Кожна справа тут стоїть заради одних воріт і
названа в коментарі — прибрати «зайву» не можна, не прибравши перевірки.

Головний приймач — ПОБАЙТОВА рівність трьох файлів золоту. Логічні тести нижче
пояснюють, ЩО саме в тих байтах: коли золото зміниться, вони скажуть чому.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from nyshporka.fonds.collect.base import Target
from nyshporka.fonds.merge.run import MergeError, merge_fond
from nyshporka.fonds.merge.sources import COLUMNS, SOURCES, TEXT_ORDER, TITLE_RANK
from nyshporka.fonds.merge.titles import _fuse_fields
from nyshporka.fonds.registry import FIELDS

DATA = Path(__file__).parent / "data" / "merge_fond"
GOLD = DATA / "golden"


@pytest.fixture
def run(tmp_path: Path):
    """Злити фікстуру у свіжій копії. Повертає (результат, тека джерел, реєстр).

    🔴 Копія обов'язкова: `conflicts.tsv` водночас вхід і вихід, тож прогін «на
    місці» спожив би вердикти фікстури, і наступний тест побачив би вже інший
    вхід.
    """
    def _go(fond: str = "999", *, library: bool = True, dest: Path | None = None):
        d = dest or (tmp_path / "registry")
        if not d.exists():
            shutil.copytree(DATA / "registry", d)
        out = d.parent / f"f{fond}_opys_merged.tsv"
        lib = DATA / "case_library.json" if library else None
        res = merge_fond(Target(repo="CDIAK", fond=fond), dest=d, out=out, library=lib)
        return res, d, out
    return _go


def _rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {f"{r['opys']}-{r['spr_int']}{r['spr_letter']}": r
                for r in csv.DictReader(fh, delimiter="\t")}


# ── головний приймач ────────────────────────────────────────────────────────

def test_golden_bytes(run) -> None:
    """Три файли ПОБАЙТОВО ті самі."""
    res, d, out = run()
    assert out.read_bytes() == (GOLD / "f999_opys_merged.tsv").read_bytes()
    for name in ("conflicts.tsv", "coverage.json", "unresolved_scans.tsv"):
        assert (d / name).read_bytes() == (GOLD / name).read_bytes(), name
    assert res.rows == 18


def test_idempotent(run, tmp_path: Path) -> None:
    """Друге злиття тих самих джерел дає той самий реєстр.

    ⚠ Не тавтологія: між прогонами `conflicts.tsv` переписується, а наступний
    прогін його ЧИТАЄ — саме тут ламається перенос вердиктів.
    """
    d = tmp_path / "registry"
    run(dest=d)
    first = (d.parent / "f999_opys_merged.tsv").read_bytes()
    res2, _, out2 = run(dest=d)
    assert out2.read_bytes() == first
    assert res2.verdicts_kept == 1, "вердикт людини мусить пережити перезбірку"


# ── зшивачі: те, що розходиться МОВЧКИ ──────────────────────────────────────

def test_columns_known_to_reader() -> None:
    """Кожна колонка реєстру відома читалці.

    🔴 Ворота проти вади, яку двічі знаходили постфактум: злиття додає колонку,
    читалка про неї не знає й мовчки відкидає — на диску дані є, у застосунку
    їх немає.
    """
    assert set(COLUMNS) <= set(FIELDS), set(COLUMNS) - set(FIELDS)


def test_rank_matches_sources() -> None:
    """Перелік рангів дорівнює переліку рангових джерел."""
    assert set(TITLE_RANK) == {s.name for s in SOURCES if s.rank is not None}
    assert set(TEXT_ORDER) == set(TITLE_RANK)


def test_processing_order_is_not_the_rank_order() -> None:
    """Порядок обробки зафіксовано ДОСЛІВНО — він несе байти.

    🔴 І він НЕ дорівнює порядку рангів: каталог (58) обробляється раніше за
    транскрипції (50, 55), бо ранг вирішує, чий ЗАГОЛОВОК виграє, а порядок —
    лише чиї роки й аркуші стануть «першим непорожнім» і в якій послідовності
    ляже черга розбіжностей. Звести їх «для порядку» означає переписати обидва
    файли-виходи.
    """
    assert TEXT_ORDER == ("fs", "ocr", "duck", "catalog", "ukrfamily",
                          "legacy", "wikisource", "archium", "manual")


def test_golden_columns_are_the_declared_order() -> None:
    with (GOLD / "f999_opys_merged.tsv").open(encoding="utf-8", newline="") as fh:
        head = next(csv.reader(fh, delimiter="\t"))
    assert tuple(head) == COLUMNS


# ── ранг заголовка ──────────────────────────────────────────────────────────

def test_eye_beats_archive_listing(run) -> None:
    """Опис, прочитаний оком, переважує опис на сайті архіву (спр.12)."""
    r = _rows(run()[2])["1-12"]
    assert r["title_src"] == "manual"
    assert "приписних" in r["title"]


def test_weaker_title_survives_in_alt(run) -> None:
    """Слабший заголовок лишається слідом, а не зникає (спр.1)."""
    r = _rows(run()[2])["1-1"]
    assert r["title_src"] == "archium"
    assert "wikisource:Ревізька казка" in r["title_alt"]


def test_registry_only_source_still_names_the_case(run) -> None:
    """Справа, про яку знає ЛИШЕ покажчик, доходить із заголовком (спр.2)."""
    r = _rows(run()[2])["1-2"]
    assert r["title_src"] == "duck"
    assert r["duck_url"]


def test_years_src_names_both_sources() -> None:
    """Коли роки прийшли з РІЗНИХ джерел, поле називає обидва.

    ⚠ Наявні джерела дають діапазон цілком (47 020 рядків із 47 020), тож на
    сьогоднішніх даних ця гілка мовчить — вона тут, щоб перший же однорічний
    рядок не збрехав про походження другого року.
    """
    from nyshporka.fonds.merge.sources import blank_row

    r = blank_row(("1", "1", ""))
    _fuse_fields(r, {"year_from": "1801"}, "wikisource")
    assert r["years_src"] == "wikisource"
    _fuse_fields(r, {"year_to": "1810"}, "archium")
    assert r["years_src"] == "wikisource+archium"
    assert (r["year_from"], r["year_to"]) == ("1801", "1810")


def test_years_src_stays_single_when_one_source_gave_both() -> None:
    from nyshporka.fonds.merge.sources import blank_row

    r = blank_row(("1", "1", ""))
    _fuse_fields(r, {"year_from": "1801", "year_to": "1810"}, "wikisource")
    _fuse_fields(r, {"year_from": "1799", "year_to": "1802"}, "archium")
    assert r["years_src"] == "wikisource", "сильніше джерело років НЕ перебиває"


def test_ukrainian_letter_index_is_a_letter() -> None:
    """«1280і» — літерна справа, а не сміття.

    🔴 Діапазон «а-я» не містить «і ї є ґ», тож такий номер не розбирався
    ЗОВСІМ: рядок мовчки випадав, і в черзі завантаження на його місці не було
    нічого. Описи ДАХмО й ДАВіО набирали українською.
    ⚠ Замір 2026-08-23: на 27 839 наявних значеннях правка не міняє нічого —
    вона чекає на дані, а не лагодить сьогоднішні.
    """
    from nyshporka.fonds.merge.text import key_of

    assert key_of({"opys": "1", "spr": "1280і"}) == ("1", "1280", "і")
    assert key_of({"opys": "1", "spr": "84є"}) == ("1", "84", "є")
    assert key_of({"opys": "1", "spr": "24a"}) == ("1", "24", "а"), "латинка → шифр"
    assert key_of({"opys": "1", "spr": "без номера"}) is None


# ── черга розбіжностей ──────────────────────────────────────────────────────

def test_conflict_queue_is_about_a_different_village(run) -> None:
    """У чергу йде РІЗНЕ СЕЛО, а не різні слова про те саме.

    🔴 Спр.16 має два несхожі описи однієї церкви («Свято-Покровська» проти
    «Покрови Пресвятої Богородиці») — і в черзі її бути НЕ МУСИТЬ: саме така
    пара дала 572 хибні позиції на ф.224, у яких тонули справжні.
    """
    res, d, _ = run()
    with (d / "conflicts.tsv").open(encoding="utf-8", newline="") as fh:
        q = list(csv.DictReader(fh, delimiter="\t"))
    assert res.conflicts == 1
    assert q[0]["spr"] == "1"
    assert not [r for r in q if r["spr"] == "16"]


def test_verdict_kept_note_without_verdict_dropped(run) -> None:
    """Вердикт людини переживає перезбірку — а сама нотатка ні.

    ⚠ Другий бік названо навмисно: без нього «полагодять» так, що переживати
    почне будь-який рядок, і черга ніколи не зменшиться.
    """
    _, d, _ = run()
    with (d / "conflicts.tsv").open(encoding="utf-8", newline="") as fh:
        q = list(csv.DictReader(fh, delimiter="\t"))
    kept = [r for r in q if r["verdict"]]
    assert len(kept) == 1 and kept[0]["note"] == "звірено зі сканом опису"
    assert not [r for r in q if r["spr"] == "3"], "нотатка без вердикту не переживає"


# ── скани ───────────────────────────────────────────────────────────────────

def test_volumes_add_up_variants_do_not(run) -> None:
    """Томи складаються, витяг однієї парафії — ні (спр.3 і спр.4).

    🔴 Складати варіанти означало б рахувати ті самі аркуші вдруге.
    """
    reg = _rows(run()[2])
    assert reg["1-3"]["commons_kind"] == "volumes"
    assert reg["1-3"]["commons_pages"] == "2300"          # 1200 + 1100
    assert reg["1-4"]["commons_kind"] == "variants"
    assert reg["1-4"]["commons_pages"] == "1500"          # НЕ 1530


def test_truncated_mirror_flagged(run) -> None:
    """Дзеркало, що віддає менше за найбільший файл, позначене (спр.5)."""
    assert _rows(run()[2])["1-5"]["truncated_mirror"] == "1"


def test_scan_without_shifra_goes_to_its_own_file(run) -> None:
    """Скан, шифри якого немає в назві, не зникає мовчки."""
    res, d, _ = run()
    txt = (d / "unresolved_scans.tsv").read_text(encoding="utf-8")
    assert "Опис фонду без шифри.pdf" in txt
    assert any(b.kind == "no_shifra" for b in res.blind)


def test_cover_only_case_survives(run) -> None:
    """Справа, відома ЛИШЕ з обкладинки, доходить до реєстру (спр.6).

    🔴 Регресія: поля `truncated_mirror`/`on_disk` створювались у циклі
    дзеркала, тож джерела, що додають справи ПІСЛЯ нього, лишали рядок без них
    — і підсумки падали на фонді, де така справа є.
    """
    r = _rows(run()[2])["1-6"]
    assert r["cover_place"] == "Соснівка"
    assert r["on_disk"] == "" and r["truncated_mirror"] == ""


# ── диск і канали ───────────────────────────────────────────────────────────

def test_disk_does_not_leak_from_another_fond(run) -> None:
    """Бібліотека містить спр.9 ДВОХ фондів — узятись має лише свій."""
    reg = _rows(run()[2])
    assert reg["1-9"]["on_disk"] == "data/raw/cdiak_999/999-1-9"


def test_channels_are_mutually_exclusive(run) -> None:
    """Справа з чотирма каналами рахується в черзі рівно раз (спр.7)."""
    res, _, _ = run()
    ch = res.channels
    assert ch["disk"] + ch["free"] + ch["order"] == res.rows
    assert ch["archium"] + ch["commons"] + ch["mirror"] + ch["film"] == ch["free"]


def test_no_library_is_a_named_blindness(run) -> None:
    """Без бібліотеки «на диску» порожнє у ВСЬОМУ фонді — і це сказано вголос.

    🔴 Нуль без знаменника читається як «нічого не завантажено».
    """
    res, _, _ = run(library=False)
    assert any(b.kind == "no_library" for b in res.blind)


# ── покриття ────────────────────────────────────────────────────────────────

def test_no_bounds_no_coverage(run) -> None:
    """Меж описів ф.999 у паку немає — покриття не рахується, і це названо."""
    res, d, _ = run()
    assert res.denominator == ""
    assert any(b.kind == "no_denominator" for b in res.blind)
    cov = json.loads((d / "coverage.json").read_text(encoding="utf-8"))
    assert set(cov) == {"_total"}, "жодного опису без знаменника"


def test_bounds_from_pack_are_used(run) -> None:
    """Той самий вхід під фондом із відомими межами дає знаменник із паку.

    ⚠ Числа тут навмисно НЕ золоті: вони живуть у `archives.yaml`, і прив'язка
    тесту до них зробила б кожне уточнення межі червоним.
    """
    res, _, _ = run("224")
    assert res.denominator == "pack:CDIAK/224"
    assert res.coverage["1"]["last_number"] > 0
    # 17 рядків в оп.1, але літерна серед них рахується ОКРЕМО: номер 8а не
    # займає позиції 8 у знаменнику опису.
    assert res.coverage["1"]["present"] == 16
    assert res.coverage["1"]["letter_rows"] == 1        # спр.8а
    assert any(b.kind == "lower_estimate" for b in res.blind)


def test_opys_subset_is_refused(run, tmp_path: Path) -> None:
    """Злиття одного опису — помилка з поясненням, а не тиха згода."""
    d = tmp_path / "registry"
    shutil.copytree(DATA / "registry", d)
    with pytest.raises(MergeError, match="по ФОНДУ"):
        merge_fond(Target(repo="CDIAK", fond="999", opys=("1",)),
                   dest=d, out=d.parent / "x.tsv")


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    d = tmp_path / "registry"
    shutil.copytree(DATA / "registry", d)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    res = merge_fond(Target(repo="CDIAK", fond="999"), dest=d,
                     out=d.parent / "f999_opys_merged.tsv", dry_run=True)
    assert res.rows == 18
    assert not (d.parent / "f999_opys_merged.tsv").exists()
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before


def test_empty_source_is_still_named(run) -> None:
    """Джерело, якого в теці немає, лишається в переліку з нулем.

    🔴 «Джерела не було» і «джерело дало нуль» — різні відповіді про фонд.
    """
    res, _, _ = run()
    names = dict(res.sources)
    assert set(names) == {s.name for s in SOURCES}
    assert names["covers"] == 1
