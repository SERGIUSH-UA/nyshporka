"""🧪 Книжковий бланк → таблиця актів: графи з `-cells`, акти за рядком-закриттям.

Вигадана сторінка книги померлих і вигадані імена; ні справжніх кадрів, ні людей.
"""
from __future__ import annotations

import json
from pathlib import Path

W, H = 1000, 1600

#: Межі граф бланка (x0, x1) — за частками шаблону `liber_mortuorum`.
GRAPHS = [(20, 50), (55, 105), (110, 160), (165, 215), (220, 490), (495, 525),
          (530, 555), (560, 585), (590, 610), (615, 680), (685, 890), (895, 970)]


def _write(d: Path, boxes: list, texts: list[str], extra: dict | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "p1.txt").write_text("\n".join(texts) + "\n", encoding="utf-8")
    (d / "p1.lines.json").write_text(json.dumps({"size": [W, H], "boxes": boxes, **(extra or {})}),
                                     encoding="utf-8")


def _cells(d: Path, graphs: list = GRAPHS) -> None:
    """Голос `-cells`: шапка (120–290) і дві випадкові смуги тіла на кожну графу,
    плюс заголовок на всю ширину, який графою не є."""
    boxes = [[0, 0, W, 100]]
    for x0, x1 in graphs:
        boxes += [[x0, 120, x1, 290], [x0, 400, x1, 700], [x0, 900, x1, 1300]]
    _write(d, boxes, [""] * len(boxes), {"cells": [[0, i, 0] for i in range(len(boxes))]})


def _act(y: int, day: str, name: str, surname: str, age: str) -> list[tuple[list[int], str]]:
    return [([60, y, 100, y + 30], day),
             ([170, y, 210, y + 30], "12"),
             ([225, y, 480, y + 30], name),
             ([620, y, 675, y + 30], age),
             ([700, y, 880, y + 30], "ordinaria"),
             ([225, y + 40, 400, y + 70], surname),
             # рядок-закриття тягнеться через пів сторінки
             ([300, y + 80, 870, y + 110], "Sepecwit Bruzacki Parochus")]


def _page(tmp: Path, graphs: list = GRAPHS) -> tuple[Path, Path]:
    # шапка над таблицею рукою: «Copia … Parochus» схоже на рядок-закриття
    lines = [([30, 10, 900, 60], "Copia ex libro mortuorum, Parochus loci"),
             ([230, 150, 480, 200], "Nomen Mortui"),
             *_act(320, "11", "Petrus filius Joannis", "Wyrozub", "60"),
             *_act(460, "14", "Anna uxor Michaelis", "Kostryk", "35"),
             *_act(600, "2", "Paulus filius Basilii", "Zahraj", "8")]
    run, cells = tmp / "r", tmp / "r-cells"
    _write(run, [b for b, _t in lines], [t for _b, t in lines])
    _cells(cells, graphs)
    return run, cells


def test_acts_split_by_closing_line_and_land_in_their_graphs(tmp_path: Path) -> None:
    from nyshporka.records.book_table import assemble, to_rows

    run, cells = _page(tmp_path)
    t = assemble(run, cells, "p1")
    assert t.why == ""
    assert {"mortis", "domus", "nomen", "dies_vitae", "morbus"} <= set(t.columns)
    assert len(t.acts) == 3
    rows = to_rows(t)
    assert rows[0]["mortis"] == "11" and rows[1]["mortis"] == "14"
    assert rows[1]["nomen"].startswith("Anna uxor Michaelis | Kostryk")
    assert rows[2]["dies_vitae"] == "8" and rows[2]["morbus"] == "ordinaria"
    # шапка граф над тілом таблиці в акт не потрапляє
    assert all("Nomen Mortui" not in r["nomen"] for r in rows)
    # номер рядка прогону — щоб дійти до кропа
    assert t.acts[0].cells["nomen"][0][0] == 5


def test_closing_line_split_in_two_is_one_boundary(tmp_path: Path) -> None:
    """Рушій розрізав «Sepelivit … Parochus» на два рядки: це одна межа, не акт."""
    from nyshporka.records.book_table import assemble

    run, cells = _page(tmp_path)
    geo = json.loads((run / "p1.lines.json").read_text(encoding="utf-8"))
    texts = (run / "p1.txt").read_text(encoding="utf-8").splitlines()
    _write(run, [*geo["boxes"], [700, 412, 880, 442]], [*texts, "Parochus loci"])
    t = assemble(run, cells, "p1")
    assert len(t.acts) == 3 and "Parochus loci" in t.acts[0].text("morbus")


def test_missing_tick_graph_goes_to_nearest_not_margin(tmp_path: Path) -> None:
    """Сітка не побачила вузьких граф галочок: рядок у щілині — до найближчої графи."""
    from nyshporka.records.book_table import _column_of, assemble

    run, cells = _page(tmp_path, [g for g in GRAPHS if g not in ((530, 555), (590, 610))])
    t = assemble(run, cells, "p1")
    assert "alia" not in t.columns and "femina" not in t.columns
    assert _column_of([592, 0, 608, 10], t.columns) != "margo"
    assert _column_of([980, 0, 995, 10], t.columns) == "margo"


def test_no_grid_is_an_honest_refusal(tmp_path: Path) -> None:
    from nyshporka.records.book_table import assemble

    run, cells = _page(tmp_path)
    _write(cells, [[0, 0, W, 100]], ["Liber"])
    t = assemble(run, cells, "p1")
    assert not t.found and "сітки" in t.why


def test_columns_scale_to_run_frame(tmp_path: Path) -> None:
    """Голос `-cells` з кадру іншого розміру: межі граф — у координатах прогону."""
    from nyshporka.records.book_table import LIBER_MORTUORUM, find_columns

    boxes = []
    for x0, x1 in GRAPHS:
        boxes += [[x0, 120, x1, 290], [x0, 400, x1, 700]]
    cols, top = find_columns({"size": [W, H], "boxes": boxes}, LIBER_MORTUORUM, 2 * W, 2 * H)
    assert cols["nomen"] == (440, 980) and top == 580
