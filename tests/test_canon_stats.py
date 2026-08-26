"""📊 Зведення канону: «немає бази» ніколи не виглядає як «нуль осіб».

Ця відмінність і є тут головним предметом. Нуль читається як перевірений
результат — «я дивився, у тебе порожньо», — і по ньому людина закриває питання.
Відсутня база означає рівно протилежне: перевіряти не було чого.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

#: Мінімальна форма derived-бази — рівно ті таблиці й колонки, які читає
#: зведення. Повну схему будує `storage.reindex`; дублювати її тут означало б
#: заводити другий опис того самого й розходитись із ним.
SCHEMA = """
CREATE TABLE persons (id TEXT PRIMARY KEY, primary_name TEXT, sex TEXT,
  private INT, parent_family TEXT, hypothetical_parent_family TEXT, notes TEXT);
CREATE TABLE families (id TEXT PRIMARY KEY, husband TEXT, wife TEXT,
  hypothetical_husband TEXT, hypothetical_wife TEXT, notes TEXT);
CREATE TABLE places (id TEXT PRIMARY KEY, name TEXT, osm_id TEXT, lat REAL,
  lon REAL, admin_json TEXT, period_notes TEXT, notes TEXT);
CREATE TABLE sources (id TEXT PRIMARY KEY, type TEXT, title TEXT,
  authority TEXT, url TEXT, repository_ref TEXT, raw_path TEXT, fetched TEXT,
  coverage_json TEXT, notes TEXT);
CREATE TABLE facts (id INTEGER PRIMARY KEY, person_id TEXT, family_id TEXT,
  type TEXT, date_value TEXT, date_precision TEXT, date_qualifier TEXT,
  date_range_end TEXT, place_id TEXT, value TEXT, status TEXT);
CREATE TABLE citations (fact_id INT, source_id TEXT, page TEXT, quote TEXT,
  confidence TEXT, accessed TEXT, note TEXT);
CREATE TABLE media (person_id TEXT, sha256 TEXT, path TEXT, url TEXT,
  caption TEXT, type TEXT);
CREATE TABLE name_variants (person_id TEXT, form TEXT, lang TEXT,
  is_primary INT, given TEXT, surname TEXT);
"""


def _canon(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO persons (id) VALUES (?)",
                    [("P1",), ("P2",), ("P3",)])
    con.execute("INSERT INTO families (id) VALUES ('F1')")
    con.execute("INSERT INTO sources (id, title) VALUES ('S1', 'метрика')")
    con.execute("INSERT INTO sources (id, title) VALUES ('S2', 'без цитат')")
    con.executemany(
        "INSERT INTO facts (id, person_id, type, date_value) VALUES (?,?,?,?)",
        [(1, "P1", "birth", "1802-03-04"),
         (2, "P1", "death", "1861"),
         (3, "P2", "birth", "бл. 1810"),          # рік не витягується
         (4, "P3", "occupation", "")])            # дати немає зовсім
    con.executemany(
        "INSERT INTO citations (fact_id, source_id) VALUES (?,?)",
        [(1, "S1"), (2, "S1")])
    con.executemany(
        "INSERT INTO name_variants (person_id, is_primary, surname) VALUES (?,?,?)",
        [("P1", 1, "Вишневецький"), ("P2", 1, "Вишневецький"),
         ("P3", 1, "Фисюк"), ("P1", 0, "Wiszniowiecki")])
    con.commit()
    con.close()


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "data" / "derived").mkdir(parents=True)
    yield tmp_path
    W.reset()


def _summary():
    from nyshporka.storage import canon_stats

    return canon_stats.summary()


def test_no_canon_is_not_zero_people(space):
    """🔴 Головне розрізнення модуля.

    Нулі замість відсутньої бази читаються як перевірений результат, хоча
    перевіряти не було чого — і лікується це не пошуком у каноні, а його
    збиранням.
    """
    got = _summary()
    assert got["present"] is False
    assert got.get("why")
    assert "persons" not in got


def test_totals_and_breakdowns(space):
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    got = _summary()
    assert got["present"] is True
    assert (got["persons"], got["families"], got["sources"]) == (3, 1, 2)
    assert (got["facts"], got["citations"]) == (4, 2)
    types = {r["code"]: r["n"] for r in got["facts_by_type"]}
    assert types == {"birth": 2, "death": 1, "occupation": 1}


def test_uncited_facts_are_counted_separately(space):
    """🔴 Недоведений факт у дереві виглядає так само, як доведений.

    Поки його не рахують окремо, база росте, а частка доказаного мовчки падає —
    і помітно це стає лише тоді, коли хтось просить джерело.
    """
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    got = _summary()
    assert got["facts_uncited"] == 2          # факти 3 і 4 без цитат
    assert got["sources_uncited"] == 1        # S2


def test_a_year_that_cannot_be_read_makes_no_column(space):
    """«бл. 1810» року не дає, і підставляти нуль не можна: стовпчик на
    0-х роках виглядав би як подія, а не як невідома дата."""
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    decades = {r["decade"]: r["n"] for r in _summary()["facts_by_decade"]}
    assert decades == {1800: 1, 1860: 1}
    assert 0 not in decades


def test_people_without_dates(space):
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    # P2 має birth без читабельного року — але `date_value` не порожній, тож
    # особа вважається датованою: тут міряється наявність дати, а не її якість.
    assert _summary()["persons_no_dates"] == 1     # P3


def test_top_surnames_count_people_not_rows(space):
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    top = {r["code"]: r["n"] for r in _summary()["top_surnames"]}
    assert top == {"Вишневецький": 2, "Фисюк": 1}


def test_a_schema_from_another_version_says_so(space):
    """🔴 Схему derived-бази рухає `reindex`. Старий екран поверх нової бази
    мусить сказати саме це, а не показати спорожнілий канон."""
    path = space / "data" / "derived" / "nyshporka.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE persons (id TEXT)")     # решти таблиць немає
    con.commit()
    con.close()
    got = _summary()
    assert got["present"] is False
    assert "схем" in got["why"]


def test_coverage_reads_counts_from_spans_not_from_the_legend(space):
    """⚠ У `coverage.json` верхні `record_types`/`statuses` — довідники
    (`{id, label}`), а не підрахунки. Перша редакція прийняла їх за зведення й
    малювала стовпчики з нулями й порожніми підписами.
    """
    import json

    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    (space / "data" / "derived" / "coverage.json").write_text(json.dumps({
        "generated": "2026-08-23T23:21:04", "year_min": 1750, "year_max": 1935,
        "record_types": [{"id": "birth", "label": "Народження"},
                         {"id": "death", "label": "Смерті"}],
        "statuses": [{"id": "decoded", "label": "Прочитано"}],
        "sources": [
            {"id": "S1", "spans": [{"status": "decoded",
                                    "record_types": ["birth", "death"]}]},
            {"id": "S2", "spans": [{"status": "decoded",
                                    "record_types": ["birth"]}]},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    cov = _summary()["coverage"]
    assert (cov["year_min"], cov["year_max"]) == (1750, 1935)
    assert cov["sources"] == 2 and cov["spans"] == 2
    assert {r["code"]: r["n"] for r in cov["by_record_type"]} == {"birth": 2, "death": 1}
    # Підпис береться з довідника, а не лишається кодом.
    assert {r["label"] for r in cov["by_status"]} == {"Прочитано"}


def test_missing_coverage_file_is_simply_no_block(space):
    _canon(space / "data" / "derived" / "nyshporka.sqlite")
    assert _summary()["coverage"] == {}
