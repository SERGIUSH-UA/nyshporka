"""📈 Журнал спостережень: чесна крива або жодної.

Тут перевіряється не «чи пишеться файл», а три властивості, без яких графік
починає брехати тихо:

    дедуп     — кожне відкриття вкладки не ставить точку;
    стійкість — обірваний рядок не з'їдає всю історію;
    межа      — реконструйоване позначене як реконструйоване.

Остання найважливіша: точка бекфілу без мітки нічим не відрізняється від
виміряної, а вся вигода журналу саме в тому, що йому можна вірити.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

H: Any = None


@pytest.fixture
def space(tmp_path: Path):
    global H
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "data" / "derived").mkdir(parents=True)

    from nyshporka.core import history as _H

    H = _H
    yield tmp_path
    W.reset()


def test_empty_journal_is_a_valid_state(space):
    """Щойно створений простір: історії немає, і це не помилка."""
    assert H.read() == []


def test_first_snapshot_lands(space):
    assert H.record({"cases": 3, "frames": 40}, by="cases.build") is True
    rows = H.read()
    assert len(rows) == 1
    assert rows[0]["cases"] == 3
    assert rows[0]["by"] == "cases.build"
    assert rows[0]["src"] == "live"


def test_same_numbers_do_not_add_a_point(space):
    """🔴 Головне: дашборд відкривають десятки разів на день.

    Без дедупу файл ріс би на кожне відкриття, а крива перетворилась би на
    пряму з тисячі однакових точок — тобто коштувала б дорожче й показувала б
    менше.
    """
    H.record({"cases": 3, "frames": 40}, by="home.pulse")
    assert H.record({"cases": 3, "frames": 40}, by="home.pulse") is False
    assert len(H.read()) == 1


def test_changed_numbers_do_add_a_point(space):
    H.record({"cases": 3}, by="home.pulse")
    assert H.record({"cases": 4}, by="home.pulse") is True
    assert [r["cases"] for r in H.read()] == [3, 4]


def test_a_torn_line_does_not_eat_the_history(space):
    """🔴 Файл дописується конкурентно, тож половина рядка на хвості —
    очікуваний стан. Панель, яка гасне цілком через півтори тисячі байтів,
    втрачає всю історію заради одного зіпсованого дня.
    """
    H.record({"cases": 1}, by="test")
    H.record({"cases": 2}, by="test")
    path = H.history_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"at": "2026-01-01T00:00:00", "cases": 9')  # обірвано
    rows = H.read()
    assert [r["cases"] for r in rows] == [1, 2]


def test_rows_come_back_in_time_order(space):
    """Бекфіл дописує старі дати, тож порядок файла не є порядком часу."""
    H.record({"cases": 5}, by="test", at="2026-03-01T12:00:00")
    H.record({"cases": 1}, by="test", at="2026-01-01T12:00:00")
    assert [r["at"][:10] for r in H.read()] == ["2026-01-01", "2026-03-01"]


def test_compaction_keeps_one_row_per_old_day(space, monkeypatch):
    """Старе проріджується до однієї точки на добу — і саме до останньої:
    зріз доби це те, чим вона закінчилась, а не те, з чого почалась."""
    monkeypatch.setattr(H, "DENSE_DAYS", 0)      # усе вважається старим
    for i, at in enumerate(["2020-01-01T01:00:00", "2020-01-01T20:00:00",
                            "2020-01-02T01:00:00"]):
        H.record({"cases": i}, by="test", at=at)
    assert H.compact() == 2
    rows = H.read()
    assert [r["at"] for r in rows] == ["2020-01-01T20:00:00", "2020-01-02T01:00:00"]
    assert rows[0]["cases"] == 1                 # останній у добі, не перший


def test_backfill_marks_reconstructed_points(space):
    """🔴 Реконструйоване мусить бути видно як реконструйоване.

    Точка бекфілу без мітки нічим не відрізняється від виміряної, а її
    точність принципово нижча: мітка на диску каже, коли файл чіпали, а не
    коли число стало таким.
    """
    import json

    pages = space / "data" / "pages" / "DAHMO"
    pages.mkdir(parents=True)
    (pages / "230-1-3.json").write_text(json.dumps({
        "key": "DAHMO/230/3",
        "pages": {"0001": {"scan": "0001", "noted": "2026-02-10"},
                  "0002": {"scan": "0002", "noted": "2026-02-11"}},
    }, ensure_ascii=False), encoding="utf-8")

    res = H.backfill()
    assert res["written"] >= 2
    rows = H.read()
    assert rows and all(r["src"] == "backfill" for r in rows)
    # Ряд накопичувальний: другого дня аркушів більше, ніж першого.
    noted = [r["pages_noted"] for r in rows if "pages_noted" in r]
    assert noted == sorted(noted) and noted[-1] == 2


def test_backfill_does_not_overwrite_a_day_already_observed(space):
    """Живе спостереження сильніше за реконструкцію того самого дня."""
    import json

    pages = space / "data" / "pages" / "DAHMO"
    pages.mkdir(parents=True)
    (pages / "230-1-3.json").write_text(json.dumps({
        "key": "DAHMO/230/3",
        "pages": {"0001": {"scan": "0001", "noted": "2026-02-10"}},
    }, ensure_ascii=False), encoding="utf-8")

    H.record({"pages_noted": 77}, by="home.pulse", at="2026-02-10T09:00:00")
    H.backfill()
    same_day = [r for r in H.read() if r["at"][:10] == "2026-02-10"]
    assert len(same_day) == 1
    assert same_day[0]["src"] == "live" and same_day[0]["pages_noted"] == 77


def test_a_broken_workspace_is_silent_not_fatal(space, monkeypatch):
    """🔴 Журнал — надбудова. Без нього застосунок мусить працювати далі:
    невдача запису мовчить (точки не з'являється), а не валить виклик.

    ⚠ Простір тут ламається підміною шляху, а не `W.reset()`. Глобальний скид
    посеред тесту зносить override, поставлений ширшою фікстурою сусіднього
    модуля (`conftest` про це попереджає прямо), — і падають чужі тести,
    залежно від порядку. Саме так це вперше й проявилось.
    """
    monkeypatch.setattr(H, "history_path",
                        lambda: (_ for _ in ()).throw(RuntimeError("немає простору")))
    assert H.read() == []
    assert H.record({"cases": 1}, by="test") is False
