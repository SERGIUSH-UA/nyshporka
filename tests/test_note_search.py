"""👁 Нотатник у пошуку: поряд із рядком, окремим каналом, без впливу на знаменник.

🔴 Головне тут — що НЕ змінюється. Око читало вибрані рядки, а не сторінку;
якби його записи потрапили в знаменник чи в основний канал, справа «прочитана»
трьома рядками давала б нуль, який читається як «людини немає».
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tests import test_text_ops as _tt

# Фікстури простору з двома голосами й геометрією — ті самі, що в `test_text_ops`.
space = _tt.space
case_space = _tt.case_space
BOXES = _tt.BOXES

runner = CliRunner()
CASE = "DAHMO/315/8433"


def _note_read(text: str = "Іоаннъ Ивановъ Ковальскій") -> dict:
    from nyshporka.cli import app

    r = runner.invoke(app, ["note", "read", CASE, "4", "--line", "3", "--text", text,
                            "--model", "claude-opus-5-5", "--json"])
    assert r.exit_code == 0, r.output
    return json.loads(r.stdout)["data"]


def test_read_takes_the_engine_reading_and_the_frame_box(case_space: Path) -> None:
    (n,) = _note_read()["notes"]
    assert n["page"] == "0004.jpg"
    assert n["line"] == {"run": "проба", "line_no": 3, "bbox": BOXES[2]}
    assert n["was"]["text"] == "Іоаннъ Ивановъ Коваль-"


def test_ctx_puts_the_reading_next_to_its_line(case_space: Path) -> None:
    from nyshporka.search import textops as T

    _note_read()
    got = T.ctx(CASE, "4", 3, window=1)
    by_no = {it["no"]: it for it in got["window"]}
    assert [r["text"] for r in by_no[3]["notebook"]] == ["Іоаннъ Ивановъ Ковальскій"]
    assert "notebook" not in by_no[2] and "notebook" not in by_no[4]


def test_find_reports_the_notebook_as_its_own_channel_and_keeps_the_denominator(
        case_space: Path) -> None:
    from nyshporka.search import textops as T

    before = T.find("Ковальскій", CASE, thresh=78, limit=10)
    _note_read()
    after = T.find("Ковальскій", CASE, thresh=78, limit=10)

    chans = {c["id"]: c for c in after["ledger"]["channels"]}
    assert chans["notebook"]["ran"] and chans["notebook"]["hits"] == 1
    assert after["notebook"]["hits"][0]["was"] == "Іоаннъ Ивановъ Коваль-"
    for k in ("frames", "decoded", "runs", "in_store", "pages_scoped"):
        assert after["ledger"][k] == before["ledger"][k], k
    assert after["total"] == before["total"]
    assert after["hits"] == before["hits"], "око не голос: основний канал той самий"


def test_a_reading_with_another_name_is_not_a_hit(case_space: Path) -> None:
    from nyshporka.search import textops as T

    _note_read("Іоаннъ Ивановъ Шевчукъ")
    got = T.find("Ковальскій", CASE, thresh=78, limit=10)
    chans = {c["id"]: c for c in got["ledger"]["channels"]}
    assert chans["notebook"]["ran"] and chans["notebook"]["hits"] == 0


def test_grep_reaches_the_page_store_and_the_notebook(case_space: Path) -> None:
    from nyshporka.search import textops as T

    _note_read()
    got = T.grep_layers("Ковальскій", ["pages"])
    assert got["layers"]["pages"]["hits"] >= 1
    assert got["hits"][0]["file"].startswith("data/pages/DAHMO/")
