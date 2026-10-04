"""Щільність нечитаної справи — із прочитаних сусідів по опису, без вибірки.

Партія з 25 метрик одного опису стояла 35 хв на вибірці карти, хоча 22 книги
того опису вже були прочитані. Тут — реєстр справ у tmp і підмінена вибірка.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nyshporka.cases import db as CDB
from nyshporka.cloud import frames as F
from nyshporka.cloud import go as G


def _registry(path: Path, rows: list[tuple[str, int, int]]) -> Path:
    """Реєстр справ чинної схеми: (ключ, рядків, сторінок) прогону з найбільшим обсягом."""
    con = sqlite3.connect(path)
    con.executescript(CDB._SCHEMA)
    for key, lines, pages in rows:
        repo, fond, opys, spr = key.split("/")
        con.execute("INSERT INTO cases (key, repo, fond, opys, spr, htr_stage, "
                    "htr_lines_max, htr_pages_max) VALUES (?,?,?,?,?,?,?,?)",
                    (key, repo, fond, opys, spr, "both" if pages else "none",
                     lines, pages))
    con.commit()
    con.close()
    return path


R740 = [("DARO/R-740/2/58", 7400, 100),     # 74
        ("DARO/R-740/2/59", 8200, 100),     # 82
        ("DARO/R-740/2/63", 9000, 100),     # 90
        ("DARO/R-740/4/76", 30000, 100),    # інший опис — 300
        ("DARO/R-740/2/70", 0, 0)]          # нечитана — не сусід


def test_neighbours_give_the_median_of_their_means(tmp_path: Path) -> None:
    db = _registry(tmp_path / "r.sqlite", R740)
    assert F.neighbour_lines_per_page("DARO/R-740/2/70", db_path=db) == (82.0, 3)


def test_another_opys_is_not_a_neighbour(tmp_path: Path) -> None:
    db = _registry(tmp_path / "r.sqlite", R740)
    # Справа опису 4: її єдиний «сусід» — вона сама, а три справи опису 2 чужі.
    assert F.neighbour_lines_per_page("DARO/R-740/4/77", db_path=db) is None


def test_the_case_itself_and_thin_reads_do_not_count(tmp_path: Path) -> None:
    db = _registry(tmp_path / "r.sqlite", [("DAHMO/315/1/1", 900, 9),   # < 10 стор.
                                           ("DAHMO/315/1/2", 5000, 100),
                                           ("DAHMO/315/1/3", 6000, 100)])
    assert F.neighbour_lines_per_page("DAHMO/315/1/2", db_path=db) is None


def test_no_registry_no_opys_no_answer(tmp_path: Path) -> None:
    assert F.neighbour_lines_per_page("DARO/R-740/2/70", db_path=tmp_path / "нема") is None
    db = _registry(tmp_path / "r.sqlite", R740)
    assert F.neighbour_lines_per_page("DAHMO/315/75", db_path=db) is None


@pytest.fixture
def probes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Реєстр R740 як бойовий, вибірка підмінена: кожна дає 50 + номер виклику."""
    monkeypatch.setattr(CDB, "DB_PATH", _registry(tmp_path / "r.sqlite", R740))
    calls: list[Path] = []

    def fake_probe(pack, *, on_line=None):
        calls.append(Path(pack))
        return 50.0 + len(calls)

    monkeypatch.setattr(F, "lines_per_page_probe", fake_probe)
    return calls


def test_a_batch_with_read_neighbours_never_probes(tmp_path: Path, probes) -> None:
    said: list[str] = []
    d = G._Density(batch=True)
    for spr in (70, 71, 72):
        got = d.of(tmp_path / "out", tmp_path / f"spr-{spr}", f"DARO/R-740/2/{spr}",
                   lambda kind, s: said.append(s))
        assert got == 82.0
    assert probes == []
    assert any("медіана 3 прочитаних справ" in s for s in said)


def test_a_series_without_neighbours_is_probed_three_times(tmp_path: Path, probes) -> None:
    d = G._Density(batch=True)
    got = [d.of(tmp_path / "out", tmp_path / f"spr-{i}", f"DAKO/280/2/{i}",
                lambda kind, s: None) for i in range(5)]
    assert len(probes) == 3
    assert got == [51.0, 52.0, 53.0, 52.0, 52.0]


def test_a_single_case_is_probed_even_with_neighbours(tmp_path: Path, probes) -> None:
    got = G._Density(batch=False).of(tmp_path / "out", tmp_path / "spr-70",
                                     "DARO/R-740/2/70", lambda kind, s: None)
    assert got == 51.0 and len(probes) == 1


def test_own_reading_beats_neighbours(tmp_path: Path, probes) -> None:
    out = tmp_path / "out"
    out.mkdir()
    for i in range(12):
        (out / f"{i:04d}.txt").write_text("а\nб\nв\n", encoding="utf-8")
    assert G._Density(batch=True).of(out, tmp_path / "spr-70", "DARO/R-740/2/70",
                                     lambda kind, s: None) == 3.0
    assert probes == []
