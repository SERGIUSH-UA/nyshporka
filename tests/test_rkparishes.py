"""⛪ РК-парафії: до якого костелу ходило село.

Що тут тримається тестом:

1. **Село знаходиться будь-якою мовою.** Склад парафії записаний польською й
   українською, а питають українською, російською й латинкою; згортання форм
   (`geog.rkparish.fold`) зводить їх до однієї.
2. **Рядок книги без шифри не зникає.** Він їде як у джерелі (`raw`), бо
   вигадана шифра гірша за порожню, а пропущений рядок — за обидві.
3. **Нуль зі знаменником, відсутній пак — не нуль.** `parish.find` без пака
   каже, що склад парафій не перевірено, а не «костелу немає».
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

#: Вигадані парафії: ні назви, ні шифри не належать жодному джерелу.
PARISHES: list[dict[str, Any]] = [
    {"gubernia": "gubernia-podolska", "dekanat": "dekanat-testowy",
     "parish_slug": "zielonka", "parish_name": "Zielonka - Kościół św. Jana",
     "url": "https://example.org/zielonka", "is_overview": False,
     "villages": ["Zielonka", "Kowalowce", "Wójtówka"],
     "villages_uk": ["м-ко Зелінка", "сс. Ковалівці", "Війтівка та ін"],
     "books": [
         {"years": "1903-1907", "archive_text": "ARCH", "shifra": "9-1-73",
          "shifry": ["9-1-73"], "types": ["chrzty", "śluby", "pogrzeby"],
          "raw_row": ["1903-1907", "ARCH", "9-1-73"]},
         {"years": "1880", "archive_text": "ARCH", "shifra": None, "shifry": [],
          "types": ["chrzty"], "raw_row": ["1880", "ARCH", "KStp-7"]},
     ],
     "geneteka_links": [], "drive_links": ["https://example.org/kopie"]},
    {"gubernia": "gubernia-kijowska", "dekanat": "dekanat-inny",
     "parish_slug": "lipnik", "parish_name": "Lipnik - Kościół NMP",
     "url": "https://example.org/lipnik", "is_overview": False,
     "villages": ["Lipnik", "Hrabówka"], "villages_uk": ["Липник", "Грабівка"],
     "books": []},
    # огляд деканату з переліком сіл — це не парафія, у відповідь не йде
    {"gubernia": "gubernia-podolska", "dekanat": "dekanat-testowy",
     "parish_slug": "1-dekanat-testowy", "parish_name": "Dekanat testowy",
     "url": "https://example.org/dekanat", "is_overview": True,
     "villages": ["Kowalowce"], "books": []},
]


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(cat))
    from nyshporka.catalog import build as B
    from nyshporka.catalog import store as S

    src = tmp_path / "parishes.json"
    src.write_text(json.dumps(PARISHES, ensure_ascii=False), encoding="utf-8")
    B.build_rkparishes(src, cat / "rkparishes-test-2026.10.sqlite",
                       pack_id="rkparishes-test-2026.10", taken="2026-10-19",
                       source="https://example.org")
    S.invalidate()
    yield cat
    S.invalidate()


def _find(q: str, also: list[str] | None = None) -> list[dict[str, Any]]:
    from nyshporka.catalog.query import find_rk_parishes

    return find_rk_parishes(q, also=also).rows


def test_clean_name_drops_settlement_marks() -> None:
    from nyshporka.geog.rkparish import clean_name

    assert clean_name("сс. Ковалівці") == "Ковалівці"
    assert clean_name("м-ко Зелінка") == "Зелінка"
    assert clean_name("передм. м-ка Зелінка") == "Зелінка"
    assert clean_name("Війтівка та ін") == "Війтівка"


@pytest.mark.parametrize("q", ["Ковалівці", "Коваловцы", "Kowalowce"])
def test_village_found_in_any_language(catalog: Path, q: str) -> None:
    rows = _find(q)
    assert [r["slug"] for r in rows] == ["zielonka"]
    assert rows[0]["score"] == 100
    assert rows[0]["url"] == "https://example.org/zielonka"
    assert rows[0]["pack_id"] == "rkparishes-test-2026.10"


def test_cyrillic_query_shows_cyrillic_village_name(catalog: Path) -> None:
    """Рівний бал — назва мовою запиту, а не польська форма."""
    assert _find("Ковалівці")[0]["village"] == "Ковалівці"
    assert _find("Kowalowce")[0]["village"] == "Kowalowce"


def test_polish_o_kreska_meets_russian_and_ukrainian(catalog: Path) -> None:
    """Wójtówka ↔ Войтовка (ó → о) і ↔ Війтівка (ó → і)."""
    assert _find("Войтовка")[0]["slug"] == "zielonka"
    assert _find("Війтівка")[0]["slug"] == "zielonka"


def test_polish_h_meets_cyrillic_g(catalog: Path) -> None:
    """Hrabówka ↔ Грабовка: польське h проти кириличного г."""
    assert _find("Грабовка")[0]["slug"] == "lipnik"


def test_overview_page_is_not_a_parish(catalog: Path) -> None:
    assert all(r["slug"] != "1-dekanat-testowy" for r in _find("Kowalowce"))


def test_book_without_shifra_travels_raw_and_books_sorted(catalog: Path) -> None:
    books = _find("Kowalowce")[0]["books"]
    assert [b["years"] for b in books] == ["1880", "1903-1907"]
    assert books[0]["shifra"] == "" and "KStp-7" in books[0]["raw"]
    assert books[1]["shifra"] == "9-1-73"


def test_unknown_village_is_zero_with_coverage(catalog: Path) -> None:
    from nyshporka.catalog.query import find_rk_parishes

    ans = find_rk_parishes("Неіснуюче")
    assert ans.rows == []
    assert [c.pack_id for c in ans.coverage] == ["rkparishes-test-2026.10"]


class _Duck:
    def parishes(self, _form: str) -> list[Any]:
        return []


def test_parish_find_carries_rk_block(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_catalog as OC

    monkeypatch.setattr(OC, "_duck", lambda: _Duck())
    env = OC.parish_find(OC.ParishFindArgs(q="Ковалівці", books=False))
    assert env.data["rk_installed"] is True
    assert [r["slug"] for r in env.data["rk_parishes"]] == ["zielonka"]
    assert any(c.source == "rkparishes-test-2026.10" for c in env.coverage)


def test_parish_find_without_pack_says_not_checked(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_catalog as OC
    from nyshporka.catalog import store as S

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("NYSHPORKA_CATALOG", str(empty))
    S.invalidate()
    monkeypatch.setattr(OC, "_duck", lambda: _Duck())
    env = OC.parish_find(OC.ParishFindArgs(q="Ковалівці", books=False))
    assert env.data["rk_installed"] is False and env.data["rk_parishes"] == []
    S.invalidate()
