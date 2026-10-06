"""🏠 Зріз головної: швидкий, але не застарілий.

🔴 Головна на великому просторі по 14 с стояла сірими смугами (замір
06.10.2026): 12 із них — перевірка машини заради одного рядка чекліста, решта —
поштучні `stat` і розбір сотень файлів, які не змінювались. Прискорення
тримається на двох обіцянках, і тести тут — саме на них:

- повільне винесено ОКРЕМО, а не викинуто: машина приходить своєю операцією, і
  «ще не перевірено» не виглядає як «не готова»;
- пам'ять про файл живе рівно доти, доки файл не змінився: застаріле число
  на плитці без позначки гірше за повільне.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Порожній простір із власними коренями прогонів і сторінок."""
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W.reset()


def _pages_file(root: Path, name: str, statuses: list[str], records: int = 0) -> Path:
    from nyshporka.pagestore import store as PS

    f = PS.PAGES_ROOT / "R" / f"{name}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({
        "pages": {f"{i:04}.jpg": {"status": s} for i, s in enumerate(statuses)},
        "records": [{} for _ in range(records)],
    }), encoding="utf-8")
    return f


# ── машина окремо ────────────────────────────────────────────────────────────
def test_the_dashboard_does_not_wait_for_the_machine(space,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Зріз не запускає доктора; машину віддає окрема операція.

    Доки перевірка сиділа в `home.pulse`, на великому просторі вона коштувала 12 с із 14
    холодного зрізу — і щоп'ять хвилин знову, коли спливав кеш.
    """
    import nyshporka.ops_builtin as ob
    from nyshporka.setup import doctor

    calls: list[int] = []

    def fake_run() -> list[doctor.Check]:
        calls.append(1)
        return [doctor.Check(name="Прискорення (GPU)", level="fail", detail="")]

    monkeypatch.setattr(doctor, "run", fake_run)
    monkeypatch.setitem(ob._MACHINE, "data", None)

    env = ob.home_pulse(ob.PulseArgs(backfill=False))
    assert env.ok, env.error
    assert calls == [], "зріз головної знову чекає на перевірку машини"
    # «Ще не перевірено» — окремий стан, а не `ok: False`: фронт ховає крок,
    # а не фарбує його червоним.
    assert env.data["machine"] == {"pending": True}

    got = ob.home_machine(ob.NoArgs())
    assert got.ok
    assert calls == [1]
    assert got.data["ready"] is False
    assert got.data["bad"] == ["Прискорення (GPU)"]


# ── облік ока: пам'ять за штампом файлу ──────────────────────────────────────
def test_eye_totals_follow_every_edit_of_the_store(space) -> None:
    """🔴 Пам'ять про файл не переживає його зміни.

    Плитка «аркушів занесено» читає `totals()` на кожне відкриття головної, і
    тепер між відкриттями розібране пам'ятається. Правка, яку пам'ять не
    помітила, дала б на плитці вчорашнє число без жодної позначки.
    """
    from nyshporka.pagestore import store as PS

    f = _pages_file(space, "a", ["full", "partial"], records=1)
    got = PS.totals()
    assert (got["files"], got["pages"], got["full"], got["records"]) == (1, 2, 1, 1)

    _pages_file(space, "a", ["full", "full", "partial"], records=3)
    got = PS.totals()
    assert (got["pages"], got["full"], got["records"]) == (3, 2, 3), \
        "правку файлу сховища зведення не побачило"
    assert got["by_status"] == {"full": 2, "partial": 1}

    _pages_file(space, "b", ["skipped"])
    assert PS.totals()["pages"] == 4, "новий файл сховища не потрапив у зведення"

    f.unlink()
    got = PS.totals()
    assert (got["files"], got["pages"]) == (1, 1), "видалений файл лишився в зведенні"


def test_eye_totals_skip_a_broken_file_until_it_is_fixed(space) -> None:
    """Битий файл не валить зведення й не пам'ятається битим після ремонту."""
    from nyshporka.pagestore import store as PS

    f = _pages_file(space, "a", ["full"])
    f.write_text("{не json", encoding="utf-8")
    assert PS.totals()["files"] == 0
    _pages_file(space, "a", ["full", "partial"])
    got = PS.totals()
    assert (got["files"], got["pages"]) == (1, 2)
