"""Журнал обміну й каталог пулу: хто, що і коли.

🔴 Журнал живе в `data/share`, а не в `data/derived`, і тест це стереже. У
похідному лежить те, що відтворюється повторним запитом; журнал обміну —
навпаки, єдиний доказ походження чужого факту, і повторити його нема з чого:
пакет міг зникнути з тієї адреси наступного дня.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.share import catalog as C
from nyshporka.share import journal


@pytest.fixture
def space(tmp_path: Path):
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    yield tmp_path
    W.reset()


def test_journal_lives_outside_derived(space: Path) -> None:
    journal.record(journal.PACKED, shifra="ДАХмО 315-1-8433", pages=8)
    path = journal.journal_path()
    assert path.is_file()
    assert "derived" not in path.parts
    assert path.parent == space / "data" / "share"


def test_events_come_back_newest_first(space: Path) -> None:
    journal.record(journal.PACKED, shifra="A", pages=1)
    journal.record(journal.IMPORTED, shifra="B", pages=2, publisher="oksana")
    rows = journal.read()
    assert [r["shifra"] for r in rows] == ["B", "A"]
    assert [r["shifra"] for r in journal.read(journal.PACKED)] == ["A"]


def test_stats_count_cases_not_events(space: Path) -> None:
    """Повторний імпорт тієї самої справи не подвоює зроблену роботу."""
    for _ in range(3):
        journal.record(journal.IMPORTED, shifra="ДАХмО 315-1-8433", pages=8,
                       publisher="oksana", bytes=1000)
    got = journal.stats()
    assert got["imported"]["cases"] == 1
    assert got["imported"]["pages"] == 8
    assert got["events"] == 3
    assert got["from"] == [{"publisher": "oksana", "cases": 1}]


def test_broken_line_does_not_kill_the_journal(space: Path) -> None:
    journal.record(journal.PACKED, shifra="A", pages=1)
    with journal.journal_path().open("a", encoding="utf-8") as fh:
        fh.write("{ це не json\n")
    journal.record(journal.PACKED, shifra="B", pages=1)
    assert [r["shifra"] for r in journal.read()] == ["B", "A"]


def test_bundle_is_kept_as_proof(space: Path, tmp_path: Path) -> None:
    src = tmp_path / "out" / "pack.nyshtext"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"zzz")
    dest = journal.keep(src, "pack.nyshtext")
    assert dest.is_file()
    assert dest.parent == space / "data" / "share" / "inbox"


# ── каталог ──────────────────────────────────────────────────────────────────

def test_catalog_round_trip() -> None:
    from nyshporka.share.bundle import Manifest

    m = Manifest(case={"shifra": "ДАХмО 315-1-8433", "repo": "DAHMO",
                       "fond": "315", "opys": "1", "spr": "8433",
                       "years": [1846, 1846], "places": ["Ольгопіль"]},
                 decode={"pages": 3770, "voices": [{"run": "r", "model": "diak_v4"}]},
                 frames={"total": 3772},
                 publisher={"handle": "sergiy", "contact": "t.me/x"},
                 license={"text": "CC0-1.0"})
    row = C.row_for(m, sha256="ff" * 32, nbytes=4_000_000, url="https://x/y")
    text = C.header() + "\n" + row.as_tsv()
    back = C.parse(text)
    assert len(back) == 1
    assert back[0].shifra == "ДАХмО 315-1-8433"
    assert back[0].pages == "3770"
    assert back[0].publisher == "sergiy"
    assert back[0].url == "https://x/y"


def test_catalog_tolerates_unknown_columns() -> None:
    """Каталог живий: стара Нишпорка мусить читати новий, а не падати на ньому."""
    text = ("shifra\tpages\tхтозна_що\n"
            "ДАХмО 315-1-8433\t3770\tщось нове\n")
    rows = C.parse(text)
    assert rows[0].shifra == "ДАХмО 315-1-8433"
    assert rows[0].pages == "3770"


def test_tabs_in_a_field_cannot_break_the_row() -> None:
    from nyshporka.share.bundle import Manifest

    m = Manifest(case={"shifra": "ДАХмО\t315-1-8433"},
                 decode={"pages": 1, "voices": []}, frames={"total": 1},
                 license={"text": "CC0-1.0"})
    assert m.shifra.count("\t") == 1
    assert C.row_for(m).as_tsv().count("\t") == len(C.COLUMNS) - 1


def test_find_is_forgiving_about_how_people_write_a_shifra() -> None:
    rows = C.parse(C.header() + "\n"
                   + "ДАХмО 315-1-8433\tDAHMO\t315\t1\t8433\t1846\tОльгопіль\n")
    assert C.find(rows, "8433")
    assert C.find(rows, "ольгопіль")
    assert C.find(rows, "ДАХмО 315-1-8433")
    assert not C.find(rows, "Вінниця")


def test_base_url_can_be_pointed_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Своє дзеркало або тестовий сервер — без правки коду."""
    assert C.catalog_url() == f"{C.DEFAULT_BASE}/{C.CATALOG_NAME}"
    monkeypatch.setenv(C.ENV_BASE, "https://probа.example/toloka/")
    assert C.catalog_url() == f"https://probа.example/toloka/{C.CATALOG_NAME}"
    assert C.catalog_url("https://inshe/x") == f"https://inshe/x/{C.CATALOG_NAME}"


def test_summarize_groups_by_publisher_and_fond() -> None:
    rows = C.parse(
        C.header() + "\n"
        + "A\tDAHMO\t315\t1\t1\t\t\t100\t100\t2\tm\t1\ts\tCC0\tsergiy\t\t\t\n"
        + "B\tDAHMO\t315\t1\t2\t\t\t50\t50\t1\tm\t1\ts\tCC0\toksana\t\t\t\n")
    got = C.summarize(rows)
    assert got["cases"] == 2
    assert got["pages"] == 150
    assert got["publishers"][0] == {"publisher": "sergiy", "cases": 1, "pages": 100}
    assert got["fonds"][0] == {"fond": "DAHMO 315", "cases": 2}
