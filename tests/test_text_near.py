"""Два слова поруч: усі чотири види пари, вікно рядків і заборона самозбігу."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PAGES = {
    # ім'я + прізвище в одному рядку, село — у наступному
    "0001": "родился Иванъ Вербищинскій сынъ\nвъ селѣ Вербівцахъ\n",
    # два прізвища сусідніми рядками
    "0002": "Вербищинскій Петръ\nсвидѣтель Павелъ Шевчукъ\n",
    # «Іван» усередині іншого прізвища — не пара
    "0003": "восприемникъ Иваненко Стефанъ\n",
    # ім'я + по батькові + прізвище
    "0004": "крестилъ Иванъ Петровъ Вербищинскій сынъ\n",
    # село за три рядки від прізвища
    "0005": "Вербищинскій крестилъ\nмладенца\nсвященникъ\nвъ Вербівцахъ\n",
    # прізвище в кінці рядка: склейка переносу несе його й на наступний
    "0006": "свидѣтель Вербищинскій\nвъ Вербівцахъ\n",
    # «jan» із гнізда імені «Іван» сидить усередині «Стефанъ» — не пара
    "0007": "свидѣтель Стефанъ Вербищинскій сынъ\n",
}


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    d = tmp_path / "reports" / "htr" / "проба"
    d.mkdir(parents=True)
    for stem, text in PAGES.items():
        (d / f"{stem}.txt").write_text(text, encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps({
        "model": "pysar_cyr_v17.pt", "script": "cyrillic",
        "pages": {f"{s}.jpg": {"lines": 4} for s in PAGES}}), encoding="utf-8")
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    monkeypatch.setenv("NYSH_FAST", "0")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    assert list(ST.ensure_all(["проба"])) == ["проба"]
    yield tmp_path
    W.reset()

def _pairs(q: str, other: str, window: int = 1) -> dict[str, tuple[int, int, str, str]]:
    """Сторінка → (рядок першого, рядок другого, слово першого, слово другого)."""
    from nyshporka.search import textops as T

    res = T.near(q, other, "проба", window=window, limit=100)
    assert not res.get("error"), res
    return {str(h["page"]).split(".")[0]: (h["line_no"], h["near"]["line_no"], h["matched"],
                                          h["near"]["matched"]) for h in res["hits"]}


def test_given_name_and_surname_on_one_line(space: Path) -> None:
    got = _pairs("Вербищинскій", "Иванъ", window=0)
    assert set(got) == {"0001", "0004"}
    line_a, line_b, word_a, word_b = got["0001"]
    assert (line_a, line_b, word_b) == (1, 1, "Иванъ")
    assert "Вербищинскій" in word_a


def test_surname_and_village_need_the_window(space: Path) -> None:
    assert "0001" not in _pairs("Вербищинскій", "Вербівцахъ", window=0)
    assert _pairs("Вербищинскій", "Вербівцахъ", window=1)["0001"][:2] == (1, 2)
    # три рядки між ними — лише з вікном 3
    assert "0005" not in _pairs("Вербищинскій", "Вербівцахъ", window=2)
    assert _pairs("Вербищинскій", "Вербівцахъ", window=3)["0005"][:2] == (1, 4)


def test_a_word_at_the_line_end_reaches_the_next_line(space: Path) -> None:
    """Склейка переносу: прізвище в кінці рядка знайдене й на наступному."""
    assert _pairs("Вербищинскій", "Вербівцахъ", window=0)["0006"][:2] == (2, 2)


def test_given_name_and_patronymic(space: Path) -> None:
    got = _pairs("Иванъ", "Петровъ", window=0)
    assert set(got) == {"0004"}


def test_two_surnames_of_one_record(space: Path) -> None:
    got = _pairs("Вербищинскій", "Шевчукъ", window=1)
    assert set(got) == {"0002"}
    assert got["0002"][:2] == (1, 2)


def test_the_word_found_first_does_not_count_as_the_second(space: Path) -> None:
    """«Іван» усередині «Иваненко» на тому самому місці — не пара."""
    got = _pairs("Иваненко", "Иванъ", window=0)
    assert "0003" not in got


def test_order_of_the_two_words_does_not_matter(space: Path) -> None:
    a = _pairs("Вербищинскій", "Иванъ", window=1)
    b = _pairs("Иванъ", "Вербищинскій", window=1)
    assert a and a == b


def test_a_zero_names_its_denominator(space: Path) -> None:
    from nyshporka.search import textops as T

    res = T.near("Вербищинскій", "Шевчукъ", "проба", window=0)
    assert res["hits"] == [] and res["total"] == 0
    assert res["first_total"] >= 6 and res["first_pages"] == 6
    assert res["pages"] == 7


def test_a_short_twin_from_the_name_nest_is_left_out(space: Path) -> None:
    from nyshporka.search import textops as T

    res = T.near("Вербищинскій", "Иванъ", "проба", window=0)
    assert "jan" in res["stems_short_dropped"]
    assert "0007" not in {str(h["page"]).split(".")[0] for h in res["hits"]}
    # набране людиною коротке слово лишається
    typed = T.near("Вербищинскій", "Jan", "проба", window=0)
    assert "jan" in typed["stems_other"] and "jan" not in typed["stems_short_dropped"]


def test_near_lines_window_and_unknown_pages(space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    stem = S._norm("Вербищинскій")
    spots = [("проба", "0005.jpg", 4, ""), ("проба", "0005.jpg", 3, ""),
             ("проба", "9999.jpg", 1, "")]
    got = ST.near_lines([stem], spots, window=3)
    assert got[0][0] == 1 and got[1][0] == 1
    assert 2 not in got
    assert 1 not in ST.near_lines([stem], spots, window=1)


def test_one_pair_is_counted_once_across_the_line_break_glue(space: Path) -> None:
    from nyshporka.search import textops as T

    res = T.near("Вербищинскій", "Вербівцахъ", "проба", window=1, limit=100)
    on_0006 = [h for h in res["hits"] if str(h["page"]).startswith("0006")]
    assert len(on_0006) == 1 and on_0006[0]["line_no"] == 1
    assert res["total"] == len(res["hits"])


def test_a_missing_first_word_is_not_reported_as_a_missing_pair(space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("text.near", {"q": "Шевчуковскій", "other": "Иванъ", "case": "проба"})
    msg = " ".join(w.text for w in env.warnings)
    assert "не знайдено" in msg and "не шукали" in msg
    assert "пари не знайшлось" not in msg
