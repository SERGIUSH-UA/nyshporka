"""🏛 Що екран описів має чим намалювати.

🔴 Файл існує через питання дослідника: «чому інтерфейс фондів не взяли з
оригінальної Нишпорки». Виявилось, що майже все, чого бракувало на екрані, уже
рахувалось у `fonds/registry.py` — і просто не виходило наверх. `summarize()`
рахує вісімнадцять показників, віддавалось чотири; `facets()` і
`surname_list()` не викликала жодна операція в усьому пакеті; покриття лежало в
`coverage.json` і нікуди не йшло.

Тому перевірки тут — не про обчислення (вони давно є й покриті окремо), а про
доставку: чи доходить пораховане до того, хто малює.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.core import workspace as W
from nyshporka.fonds.registry import FIELDS


def _tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FIELDS), delimiter="\t",
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


@pytest.fixture
def fond(tmp_path, monkeypatch):
    """Простір із реєстром опису на три справи."""
    root = tmp_path / "простір"
    (root / "data" / "raw").mkdir(parents=True)
    (root / W.MARKER).write_text('[workspace]\nschema = 1\nname = "тест"\n',
                                 encoding="utf-8")
    _tsv(root / "data" / "raw" / "dahmo_230" / "f230_opys_merged.tsv", [
        {"opys": "1", "spr_int": "1", "spr_letter": "", "spr": "1",
         "title": "Поіменний список дворян Балтського повіту",
         "year_from": "1801", "year_to": "1801", "folios": "126",
         "dv_no": "17", "commons_url": "https://c/1", "commons_size": "74448896",
         "commons_pages": "207", "surnames": "Шевченко, Петренко",
         "on_disk": "", "num_src": "ocr"},
        {"opys": "1", "spr_int": "2", "spr_letter": "", "spr": "2",
         "title": "Іменні списки дворян Ушицького повіту",
         "year_from": "1844", "year_to": "1844", "folios": "106",
         "commons_url": "https://c/2", "commons_size": "83886080",
         "commons_pages": "200", "truncated_mirror": "1",
         "mirror_url": "https://m/2", "mirror_size": "26214400",
         "on_disk": "", "num_src": "interp", "src_page": "12"},
        {"opys": "3", "spr_int": "13", "spr_letter": "", "spr": "13",
         "title": "Виводи дворянства", "year_from": "1802", "year_to": "1802",
         "folios": "479", "on_disk": "", "num_src": "ocr"},
    ])
    monkeypatch.setenv(W.ENV_WORKSPACE, str(root))
    W.reset()
    from nyshporka.fonds import registry as R
    R.invalidate()
    yield root
    W.reset()
    R.invalidate()


def test_the_fond_card_carries_the_whole_summary(fond) -> None:
    """🔴 Вісімнадцять показників рахувались, віддавалось чотири.

    Рядок метаданих екрана («N справ · M зі сканом · K качати · P ✂ · …») —
    це і є `summarize`. Без нього екран не може сказати ні скільки справ
    обрізає дзеркало, ні скільки номерів відновлено між якорями.
    """
    env = O.call("fond.list", {})
    assert env.ok, env.error
    f = next(x for x in env.data["fonds"] if x["id"] == "dahmo_230")
    s = f["summary"]
    assert s["rows"] == 3
    assert s["commons"] == 2, "справи зі сканом на Commons"
    assert s["truncated"] == 1, "обрізане дзеркало не порахувалось"
    assert s["interp"] == 1, "відновлений номер не порахувався"
    assert s["with_surnames"] == 1


def test_the_facets_reach_the_screen(fond) -> None:
    """🔴 `facets()` не викликала жодна операція в усьому пакеті.

    Без переліку описів із лічильниками фільтр довелося б набирати наосліп —
    не знаючи ні того, які описи є, ні скільки справ за кожним.
    """
    env = O.call("fond.rows", {"fond": "dahmo_230"})
    assert env.ok, env.error
    opys = {o["code"]: o["n"] for o in env.data["facets"]["opys"]}
    assert opys == {"1": 2, "3": 1}, opys


def test_the_alphabet_surnames_reach_the_screen(fond) -> None:
    """Порожній список — законний стан («алфавітки немає»), а не поломка:
    саме тому поле є завжди, і екран може вимкнути фільтр із поясненням."""
    env = O.call("fond.rows", {"fond": "dahmo_230"})
    assert env.ok, env.error
    assert env.data["surnames"] == [], "алфавітки в цій фікстурі немає"


def test_coverage_says_it_was_not_counted_instead_of_showing_zeros(fond) -> None:
    """🔴 «Не рахувалось» і «нуль» — різні відповіді.

    Покриття рахується лише там, де відомі межі описів; показати замість
    цього нулі означало б сказати «фонд не покрито», чого ніхто не міряв.
    """
    env = O.call("fond.rows", {"fond": "dahmo_230"})
    assert env.ok, env.error
    assert env.data["coverage"] is None


def test_the_row_carries_what_it_costs_to_take(fond) -> None:
    """🔴 25 МБ проти 771 МБ на тій самій справі — це обрізане дзеркало.

    Розмір і число сторінок їдуть у рядок, бо саме ними вирішують, звідки
    качати й чи качати взагалі. Плюс `dv_no`, чий `None` означає «схема цього
    фонду такого поля не знає», а не «порожньо».
    """
    env = O.call("fond.rows", {"fond": "dahmo_230"})
    assert env.ok, env.error
    by_spr = {r["spr"]: r for r in env.data["rows"]}
    # ⚠ Рядками, а не числами: реєстр читає TSV як текст, і
    # мовчазна конверсія тут ховала б «немає поля» під нулем.
    assert by_spr["1"]["commons_size"] == "74448896"
    assert by_spr["1"]["commons_pages"] == "207"
    assert by_spr["1"]["dv_no"] == "17"
    assert by_spr["2"]["truncated_mirror"], "обрізане дзеркало не доїхало"
    assert by_spr["2"]["num_src"] == "interp"
    assert by_spr["2"]["src_page"] == "12", "нема куди звірити відновлений номер"


def test_a_half_downloaded_case_is_flagged_partial(fond, monkeypatch) -> None:
    """🔴 Прапорець `partial` не виставлявся ніколи.

    `row_status` приймає кадри четвертим аргументом, поріг `_PARTIAL_RATIO`
    написано, CLI аргумент передає — а операція його не передавала, тож
    недовантажена справа виглядала так само, як повна.
    """
    from nyshporka.fonds import registry as R

    key = ("1", "1", "")
    monkeypatch.setattr(R, "live_on_disk",
                        lambda *_a, **_k: {key: "data/raw/dahmo_230/spr-1"})
    # 100 кадрів із очікуваних 207 — менше за поріг 0.9
    monkeypatch.setattr(R, "live_frames", lambda *_a, **_k: {key: 100})

    env = O.call("fond.rows", {"fond": "dahmo_230"})
    assert env.ok, env.error
    row = next(r for r in env.data["rows"] if r["spr"] == "1")
    assert "partial" in row["flags"], row["flags"]
    assert row["frames_disk"] == 100 and row["frames_expected"] == 207
