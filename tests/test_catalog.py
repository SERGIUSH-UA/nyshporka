"""🗂 Каталог: нуль щось означає, і кожен рядок має автора.

Два інваріанти, і обидва тут не про зручність:

1. **Порожня відповідь дозволена ТІЛЬКИ разом із покриттям.** «Нічого не
   знайдено» і «ніде не шукали» — різні відповіді, і в генеалогії ціна плутанини
   між ними максимальна: «немає» закриває напрям назавжди.
2. **Кожен рядок несе `origin` і `pack_id`.** Різниця між «так каже офіційний
   покажчик архіву» і «так я сам прочитав з обкладинки» — це різниця між доказом
   і гіпотезою.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

import pytest

Q: Any = None
S: Any = None
B: Any = None


PLACES = [
    # card, section, institution, village_uk, village_ru, hist, uezd, modern, church
    ("c1", "church", "православна церква", "М'ястківка", "Мястковка",
     "Ольгопольський пов.", "Подільська губ.", "Городківка", "Благовіщенська"),
    ("c2", "church", "православна церква", "М'яколовичі", "Мяколовичи",
     "Ольгопольський пов.", "Подільська губ.", "", "Миколаївська"),
    ("c3", "rabbinate", "рабинат", "М'ястківка", "Мястковка",
     "Ольгопольський пов.", "Подільська губ.", "Городківка", ""),
    ("c4", "church", "православна церква", "Устя", "Устье",
     "Ямпільський пов.", "Подільська губ.", "", "Покровська"),
]
CASES = [
    ("224", "1", "864", 1752, 1777, "метрична книга", "Благовіщенська", "c1"),
    ("224", "1", "865", 1778, 1791, "метрична книга", "Благовіщенська", "c1"),
    ("224", "1", "12а", 1800, 1810, "метрична книга", "Миколаївська", "c2"),
    ("1", "1", "500", 1850, 1860, "метрична книга", "", "c3"),
]


def _write_sources(d: Path) -> tuple[Path, Path]:
    p_tsv, c_tsv = d / "places.tsv", d / "cases.tsv"
    with p_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["card", "section", "institution", "village_uk", "village_ru",
                    "hist_place", "uezd_gub", "modern_place", "church",
                    "eparchy", "parishes", "note"])
        for r in PLACES:
            w.writerow([*r, "", "", ""])
    with c_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["fond", "opys", "spr", "year_from", "year_to", "doc_type",
                    "case_church", "card"])
        for r in CASES:
            w.writerow(list(r))
    return p_tsv, c_tsv


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch):
    """Каталог із одним паком газетира + простір (для `own.sqlite`)."""
    global Q, S, B
    from nyshporka.core import workspace as W

    ws = tmp_path / "ws"
    (ws / "data" / "derived").mkdir(parents=True)
    W.use(W.Workspace(root=ws, name="тест", origin="test"))

    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))

    from nyshporka.catalog import build as _B
    from nyshporka.catalog import query as _Q
    from nyshporka.catalog import store as _S

    Q, S, B = _Q, _S, _B
    src = tmp_path / "src"
    src.mkdir()
    p_tsv, c_tsv = _write_sources(src)
    _B.build_geog(p_tsv, c_tsv, cat / "geog-test-2026.08.sqlite",
                  pack_id="geog-test-2026.08", taken="2026-08-16")
    _S.invalidate()
    yield cat
    W.reset()
    _S.invalidate()


# ── інваріант 1: нуль щось означає ───────────────────────────────────────────

def test_empty_catalog_refuses_instead_of_returning_zero(tmp_path, monkeypatch):
    """Каталогу немає → відмова з підказкою, а НЕ порожній список."""
    from nyshporka.catalog import query as _Q
    from nyshporka.catalog import store as _S

    monkeypatch.setenv("NYSHPORKA_CATALOG", str(tmp_path / "порожньо"))
    _S.invalidate()
    with pytest.raises(_S.CatalogMissing) as exc:
        _Q.find_places("М'ястківка")
    assert "nysh catalog install" in str(exc.value), (
        "відмова мусить казати, ЧИМ це лікується"
    )
    _S.invalidate()


def test_known_absence_comes_with_coverage(catalog):
    """Села немає, але сказано, ДЕ шукали — це відповідь, а не мовчання."""
    ans = Q.find_places("Такогоселанемає")
    assert ans.rows == []
    assert ans.coverage, "порожній результат без покриття читався б як «ніде не шукали»"
    assert ans.coverage[0].taken == "2026-08-16"


def test_answer_refuses_to_exist_without_coverage():
    """Інваріант тримається КОДОМ, а не дисципліною викликача."""
    from nyshporka.catalog.query import Answer

    with pytest.raises(AssertionError):
        Answer(rows=[], coverage=[])


def test_missing_card_says_what_is_not_covered(catalog):
    ans = Q.place_card("немає-такої")
    assert ans.rows == [] and ans.coverage
    assert ans.partial and "немає" in ans.partial[0]


# ── інваріант 2: у кожного рядка є автор ─────────────────────────────────────

def test_every_row_carries_its_origin(catalog):
    for ans in (Q.find_places("М'ястківка"), Q.place_card("c1"),
                Q.siblings("c1"), Q.confusers("c1")):
        for row in ans.rows:
            assert row.get("origin") in {"catalog", "own"}, row
            assert row.get("pack_id"), row


# ── зміст ────────────────────────────────────────────────────────────────────

def test_finds_by_ukrainian_russian_and_latin(catalog):
    """Три написання однієї назви ведуть до тієї самої картки."""
    for q in ("М'ястківка", "Мястковка", "Мястківка"):
        cards = {r["card"] for r in Q.find_places(q).rows}
        assert "c1" in cards, q


def test_confession_is_a_filter_not_three_gazetteers(catalog):
    """Те саме містечко в іншій конфесії — окрема картка, і її видно."""
    cards = {r["card"] for r in Q.find_places("М'ястківка").rows}
    assert {"c1", "c3"} <= cards, (
        "шукати лише в православному розділі означало б не бачити рабинат"
    )
    sibs = {r["card"] for r in Q.siblings("c1").rows}
    assert sibs == {"c3"}


def test_card_joins_dictionaries_back(catalog):
    """`doc_type` і `parish` зберігаються словниками — на виході знову рядки."""
    card = Q.place_card("c1").rows[0]
    assert card["village_uk"] == "М'ястківка"
    assert [c["spr"] for c in card["cases"]] == ["864", "865"]
    assert card["cases"][0]["doc_type"] == "метрична книга"
    assert card["cases"][0]["parish"] == "Благовіщенська"
    assert card["cases"][0]["shifra"] == "224-1-864"


def test_letter_case_sorts_by_number_not_string(catalog):
    """«12а» — це справа №12, а не рядок «12а» між «1» і «2»."""
    card = Q.place_card("c2").rows[0]
    assert [c["spr"] for c in card["cases"]] == ["12а"]


def test_places_for_fond_keys_without_letter(catalog):
    m = Q.places_for_fond("224")
    assert ("1", "864") in m and ("1", "12") in m, (
        "ключ мусить бути без літери — у реєстрі опису номер і літера окремо"
    )
    assert m[("1", "864")]["village"] == "М'ястківка"


def test_confusers_finds_the_similar_name(catalog):
    """На робочому порозі однакова назва в іншій конфесії — конфузер №1."""
    got = {r["card"] for r in Q.confusers("c1").rows}
    assert "c3" in got


def test_confusers_see_every_place_not_a_shortlist(catalog):
    """🔴 Конфузери — це ПОВНИЙ скан, і це рішення за виміром.

    План передбачав двоступеневий відбір через триграмну FTS. Замір на всіх
    4566 картках живого газетира: прискорення ×6.9, але результат розійшовся на
    2362 картках, і в 1348 конфузерів було ВТРАЧЕНО — `fuzz.ratio` набирає 78 і
    на розсіяних збігах, без спільного тризнакового шматка.

    Конфузери — це список ПОПЕРЕДЖЕНЬ («чому знайшлось не те село»). Тихо
    вкорочений список попереджень гірший за повільний: він виглядає повним.
    Тест ловить повернення до відбору: «М'яколовичі» не мають із «М'ястківкою»
    жодної спільної триграми, тож через FTS не знайшлись би ніколи.
    """
    got = {r["card"] for r in Q.confusers("c1", min_score=40, limit=20).rows}
    assert "c2" in got, (
        "конфузер без спільної триграми зник — повернувся відбір замість скану"
    )


# ── схема пака ───────────────────────────────────────────────────────────────

def test_pack_carries_its_own_scope_and_date(catalog):
    p = S.installed("geog")[0]
    assert p.taken == "2026-08-16" and p.rows == len(CASES)
    con = sqlite3.connect(f"file:{p.path}?mode=ro", uri=True)
    scope = con.execute("SELECT dim, value, n FROM coverage_scope").fetchall()
    con.close()
    assert ("section", "church", 3) in scope
    assert ("section", "rabbinate", 1) in scope


def test_pack_of_wrong_schema_is_named_not_ignored(catalog):
    """Чужа схема → пак видно у переліку з причиною, а не тихо зникає."""
    bad = catalog / "geog-bad-2026.01.sqlite"
    con = sqlite3.connect(bad)
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO meta VALUES(?,?)",
                    [("schema", "999"), ("domain", "geog"),
                     ("pack_id", "geog-bad-2026.01")])
    con.commit()
    con.close()
    S.invalidate()
    packs = {p.pack_id: p for p in S.installed("geog")}
    assert "geog-bad-2026.01" in packs
    assert not packs["geog-bad-2026.01"].ok
    assert "999" in packs["geog-bad-2026.01"].problem
    # робочий пак поруч лишається робочим
    assert Q.find_places("М'ястківка").rows


def test_on_disk_column_never_ships_in_opys_pack(tmp_path):
    """🔴 `on_disk` описує ЧУЖИЙ диск — у паку його не має бути в принципі.

    Перевірка на двох рівнях: у схемі (щоб колонку не додали) і в СПРАВЖНЬОМУ
    зібраному паку (щоб її не додав збирач в обхід схеми). Поїхавши в пак, вона
    стала б станом диска дослідника, виданим за факт про архів, — і позначка
    «реєстр розходиться з бібліотекою» перестала б щось означати в усіх.
    """
    import csv as _csv
    import sqlite3 as _sq

    from nyshporka.catalog.build import build_opys
    from nyshporka.catalog.schema import OPYS

    assert "on_disk" not in OPYS

    src = tmp_path / "f999_opys_merged.tsv"
    with src.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh, delimiter="\t")
        w.writerow(["opys", "spr_int", "spr_letter", "title", "on_disk",
                    "year_from", "year_to"])
        w.writerow(["1", "43", "", "Метрична книга Ольгопольского уезда",
                    "data/raw/секретний/шлях", "1802", "1802"])
    out = tmp_path / "opys-test-2026.08.sqlite"
    build_opys(src, out, fond="999", pack_id="opys-test-2026.08",
               taken="2026-08-16")

    con = _sq.connect(f"file:{out}?mode=ro", uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(cases)")]
    dump = "\n".join(str(r) for r in con.execute("SELECT * FROM cases"))
    con.close()
    assert "on_disk" not in cols
    assert "секретний" not in dump, "шлях із диска дослідника потрапив у пак"


def test_uezd_is_materialised_at_build_not_regex_at_query(tmp_path):
    """Повіт рахується на ЗБІРЦІ — це та сама третина часу запиту вкладки.

    Заміряно: `facets()` ганяв regex повіту по кожному з 12 824 заголовків на
    кожен запит — 137 мс.
    """
    import csv as _csv
    import sqlite3 as _sq

    from nyshporka.catalog.build import build_opys

    src = tmp_path / "f999_opys_merged.tsv"
    with src.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh, delimiter="\t")
        w.writerow(["opys", "spr_int", "spr_letter", "title"])
        w.writerow(["1", "1", "", "Метрична книга Ольгопольского уезда"])
        w.writerow(["1", "2", "", "Книга без повіту"])
    out = tmp_path / "opys-u-2026.08.sqlite"
    build_opys(src, out, fond="999", pack_id="opys-u-2026.08", taken="2026-08-16")
    con = _sq.connect(f"file:{out}?mode=ro", uri=True)
    got = dict(con.execute("SELECT spr, uezd FROM cases"))
    con.close()
    assert got["1"] == "Ольгопільський"
    assert got["2"] == ""


def test_latin_query_finds_the_place_and_does_not_invent_one(catalog):
    """🆕 Латинка: `Miastkowka` → М'ястківка. Раніше це був НУЛЬ.

    🔴 Поріг тут виміряний і навмисно високий (84 при найвищому заміряному шумі
    80). На 70 гілка видавала «Ілляшівку» першим хітом — правдоподібне чуже село
    замість чесного нуля. Пропущений збіг людина перевірить; впевнену помилку
    вона понесе далі.
    """
    ans = Q.find_places("Miastkowka")
    assert ans.rows, "латинське написання мусить знаходити село"
    assert ans.rows[0]["village_uk"] == "М'ястківка"
    # вигаданого не додаємо: запит, схожий лише віддалено, лишається нулем
    assert Q.find_places("Zwiahel").rows == []


def test_cyrillic_queries_never_enter_the_latin_branch(catalog, monkeypatch):
    """Паритет зі старим газетиром тримається ПОБУДОВОЮ, а не збігом.

    Латинська гілка вмикається лише на латинському запиті, тож кириличний шлях
    лишається дослівно тим, що був.
    """
    from nyshporka.catalog import query as _Q

    called: list[str] = []
    real = _Q._add_latin_hits
    monkeypatch.setattr(_Q, "_add_latin_hits",
                        lambda *a, **k: (called.append("так"), real(*a, **k))[1])
    _Q.find_places("М'ястківка")
    _Q.find_places("Такогоселанемає")
    assert called == [], "кириличний запит зайшов у латинську гілку"


# ── пак довідників: розбіжності й знаменник ──────────────────────────────────
def test_a_conflict_in_the_pack_shows_what_the_sources_say(tmp_path) -> None:
    """🔴 Колонки звуться `value_a`/`value_b`, а читались як `a`/`b` — тобто в
    пак кожна розбіжність їхала ПОРОЖНЬОЮ. Черга ока в довіднику існувала й
    нічого не показувала: видно, що джерела розходяться, і не видно чим."""
    import sqlite3

    from nyshporka.catalog.build import build_opys

    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "conflicts.tsv").write_text(
        "opys\tspr\tfield\tvalue_a\tsrc_a\tvalue_b\tsrc_b\tscore\tverdict\tnote\n"
        "1\t7\ttitle\tМетрика Вільхівки\tarchium\tМетрика Ольхівки\twikisource\t0.20\t\t\n",
        encoding="utf-8")
    merged = tmp_path / "f1_opys_merged.tsv"
    merged.write_text("opys\tspr_int\tspr_letter\ttitle\n1\t7\t\tМетрика\n",
                      encoding="utf-8")

    out = tmp_path / "pack.sqlite"
    build_opys(merged, out, fond="1", pack_id="тест", taken="2026-01-01",
               registry_dir=reg)
    con = sqlite3.connect(out)
    a, b = con.execute("SELECT a, b FROM conflicts").fetchone()
    con.close()
    assert a == "Метрика Вільхівки" and b == "Метрика Ольхівки"


def test_a_known_bound_stops_the_pack_from_calling_it_unknown(tmp_path) -> None:
    """🔴 Формат покриття читався не той, тож знаменник НІКОЛИ не доїжджав:
    `denom` завжди порожній, і поруч завжди стояла нота «межа опису невідома» —
    навіть коли межа відома. Пак брехав в обидва боки одночасно."""
    import json
    import sqlite3

    from nyshporka.catalog.build import build_opys

    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "coverage.json").write_text(json.dumps(
        {"1": {"last_number": 7438, "present": 7263},
         "_total": {"present": 7263}}, ensure_ascii=False), encoding="utf-8")
    merged = tmp_path / "f1_opys_merged.tsv"
    merged.write_text("opys\tspr_int\tspr_letter\ttitle\n1\t7\t\tх\n2\t3\t\tх\n",
                      encoding="utf-8")

    out = tmp_path / "pack.sqlite"
    build_opys(merged, out, fond="1", pack_id="тест", taken="2026-01-01",
               registry_dir=reg)
    con = sqlite3.connect(out)
    got = {v: (d, note) for v, d, note in con.execute(
        "SELECT value, denom, note FROM coverage_scope WHERE dim='opys'")}
    con.close()

    assert got["1"][0] == 7438, "відома межа не доїхала"
    assert not got["1"][1], "відому межу названо невідомою"
    # А там, де межі справді немає, застереження лишається.
    assert got["2"][0] is None and "НИЖНЯ" in got["2"][1]
