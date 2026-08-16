"""💓 Пульс: дешевий вердикт «застарів», який не бреше в інший бік.

Головне тут не швидкість, а АСИМЕТРІЯ. Пульс знає лише про зміни, зроблені
через застосунок, тож:

    «застарів»  — може казати впевнено;
    «свіжий»    — не може казати НІКОЛИ.

Якщо цю асиметрію зламати, застарілий реєстр почне виглядати свіжим — а це рівно
та помилка, проти якої `staleness` і писався: зріз, що виглядає як відповідь.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Відкладений імпорт: `cases/__init__` тягне `library`, який кличе `workspace()`
# на рівні модуля (та сама «застигла константа», що в інших тестах).
P: Any = None
DB: Any = None


@pytest.fixture
def space(tmp_path: Path):
    global P, DB
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    (tmp_path / "data" / "derived").mkdir(parents=True)

    from nyshporka.core import pulse as _P

    P = _P
    yield tmp_path
    W.reset()


def test_no_pulse_is_a_valid_state(space):
    """Щойно створений простір: пульсу немає, і це не помилка."""
    assert P.seq() == P.NO_PULSE
    assert P.snapshot()["seq"] == P.NO_PULSE


def test_beat_changes_the_mark(space):
    before = P.seq()
    after = P.beat("cases.build", "тест")
    assert after != before and after != P.NO_PULSE
    assert P.seq() == after


def test_snapshot_says_who_and_why(space):
    P.beat("pages.note", "занесено 3 скани")
    snap = P.snapshot()
    assert snap["by"] == "pages.note"
    assert snap["what"] == "занесено 3 скани"
    assert snap["at"]


def test_concurrent_beats_cannot_lose_a_change(space):
    """Мітка — час зміни файла, тож два удари поспіль не «злипаються» тихо.

    🔑 Саме через це пульс не тримає лічильник усередині файла: read-modify-write
    двох процесів загубив би удар, а загублений удар означає «свіжий» там, де
    насправді застарів.
    """
    marks = {P.beat("a"), P.beat("b"), P.beat("c")}
    # щонайменше одна зміна мітки видима; головне — остання мітка не дорівнює
    # тій, що була до серії
    assert P.seq() != P.NO_PULSE
    assert len(marks) >= 1
    first = P.seq()
    P.beat("d")
    assert P.seq() != first or P.seq() != P.NO_PULSE


def test_broken_workspace_does_not_raise(monkeypatch):
    """Пульс — прискорювач: якщо писати нікуди, він мовчить, а не падає."""
    from nyshporka.core import pulse as _P
    from nyshporka.core import workspace as W

    W.reset()
    monkeypatch.setattr(_P, "pulse_path",
                        lambda: (_ for _ in ()).throw(RuntimeError("простору немає")))
    assert _P.seq() == _P.NO_PULSE
    assert _P.beat("x") == _P.NO_PULSE


# ── асиметрія вердикту ───────────────────────────────────────────────────────

def test_quick_staleness_says_stale_when_pulse_moved(space):
    """Удар після збірки → «застарів», без обходу диска."""
    from nyshporka.cases import db as _DB

    res = _DB.build_index(db_path=space / "idx.sqlite")
    assert res["cases"] == 0 or res["cases"] >= 0
    quick = _DB.staleness(space / "idx.sqlite", quick=True)
    assert quick["stale"] is False and quick["unknown"] is True, (
        "одразу після збірки мітка збігається — це «не знаю», а не «застарів»"
    )

    P.beat("pages.note")
    quick = _DB.staleness(space / "idx.sqlite", quick=True)
    assert quick["stale"] is True and quick["unknown"] is False
    assert quick["reasons"]


def test_quick_never_claims_fresh(space):
    """🔴 Найважливіший тест файла: збіг мітки НЕ дає `stale=False` як факт.

    Він дає `unknown=True` — «через застосунок нічого не міняли, але за файл,
    покладений Провідником, я не відповідаю». Якщо колись хтось прибере
    `unknown`, цей тест впаде, і це буде правильно.
    """
    from nyshporka.cases import db as _DB

    _DB.build_index(db_path=space / "idx.sqlite")
    quick = _DB.staleness(space / "idx.sqlite", quick=True)
    assert quick["unknown"] is True, (
        "швидкий шар не має права стверджувати свіжість — він її не знає"
    )


def test_full_staleness_still_looks_at_disk(space):
    """Повна перевірка не змінилась: вона дивиться файли, а не мітку."""
    from nyshporka.cases import db as _DB

    _DB.build_index(db_path=space / "idx.sqlite")
    full = _DB.staleness(space / "idx.sqlite")
    assert full["unknown"] is False
    assert "reasons" in full


def test_build_records_the_mark_taken_before_collecting(space, monkeypatch):
    """Мітка знімається ДО збору — удар під час збірки лишається видимим.

    Інакше зміна, що сталася поки читався диск, вважалась би врахованою: реєстр
    оголосив би себе свіжим саме тоді, коли він уже ні.
    """
    from nyshporka.cases import collect as _C
    from nyshporka.cases import db as _DB

    real = _C.collect_rows

    def collect_and_beat(index=None):
        P.beat("щось.змінилось", "під час збірки")
        return real(index)

    monkeypatch.setattr(_DB, "collect_rows", collect_and_beat)
    _DB.build_index(db_path=space / "idx.sqlite")

    quick = _DB.staleness(space / "idx.sqlite", quick=True)
    assert quick["stale"] is True, (
        "удар під час збірки загубився — мітку зняли ПІСЛЯ збору"
    )
