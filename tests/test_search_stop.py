"""🔎 Пошук по корпусу: видно, що він робить, його можна спинити, і він не
питає перелік прогонів тридцять разів.

Холодний прохід 07.10.2026: пошук «у прочитаному» висів на «прогін 0 із 0»,
«Спинити» лише дописувало «перервати не можна», робота дійшла через 24 хв, а
теплий пошук коштував 105 с, з них 33 с — повторні переліки прогонів.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from nyshporka.core import progress as P
from nyshporka.core.envelope import ALERT, ok
from nyshporka.core.jobs import JobBus, JobState

# ── сигнал зупинки ───────────────────────────────────────────────────────────

def test_stopped_is_false_without_a_scope_and_follows_the_event() -> None:
    assert P.stopped() is False
    ev = threading.Event()
    with P.stop_scope(ev):
        assert P.stopped() is False
        ev.set()
        assert P.stopped() is True
    assert P.stopped() is False


# ── фонова робота: пошук спиняється, решта чесно каже «не можна» ─────────────

async def _run(tmp_path, monkeypatch, op_name: str) -> tuple[JobBus, Any, list[str]]:
    import nyshporka.ops as O
    from nyshporka.daemon import workers as W

    seen: list[str] = []

    def body(name: str, payload: dict[str, Any]) -> Any:
        # Тіло, що питає про зупинку, як `store.sweep`, — але не довше 10 с.
        end = time.monotonic() + 10
        while time.monotonic() < end:
            P.report(1, 2, "блоки корпусу")
            if P.stopped():
                seen.append("stopped")
                return ok({"hits": [], "coverage": {}})
            time.sleep(0.02)
        seen.append("ran-out")
        return ok({"hits": []})

    monkeypatch.setattr(O, "call", body)
    monkeypatch.setattr(O, "get", lambda _n: type("Op", (), {"summary": "проба"})())
    bus = JobBus(tmp_path / "jobs.json")
    job = await W._start_generic(bus, op_name, {"q": "x"})
    await asyncio.sleep(0.2)
    await bus.cancel(job.id)
    for _ in range(300):
        if seen:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)
    return bus, bus.get(job.id), seen


async def test_search_sweep_really_stops(tmp_path, monkeypatch) -> None:
    _bus, job, seen = await _run(tmp_path, monkeypatch, "search.find")
    assert seen == ["stopped"], "пошук не спинився — дочекався кінця"
    assert job.state == JobState.CANCELLED
    assert not any(w.get("code") == "cant_interrupt" for w in job.warnings)


async def test_other_generic_ops_say_they_cannot_be_interrupted(tmp_path, monkeypatch) -> None:
    _bus, job, seen = await _run(tmp_path, monkeypatch, "registry.merge")
    assert seen == ["ran-out"], "операцію без кооперативної зупинки перервано"
    # Доробилась до кінця — і про це підсумкова примітка, що заміняє тимчасове
    # «перервати не можна» (`FINISHED_AFTER_CANCEL`).
    assert any(w.get("code") == "finished_after_cancel" for w in job.warnings)


# ── пошук передає поступ і зупинку свіпу стору ───────────────────────────────

def test_search_wires_progress_and_stop_into_the_store_sweep(monkeypatch) -> None:
    """🔴 Саме ця нитка була порвана: стор уміє звітувати й спинятись, а пошук
    не давав йому ні приймача поступу, ні сигналу зупинки — «0 із 0» без кінця."""
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    got: dict[str, Any] = {}

    def fake_sweep(stems, names, **kw):
        got.update(kw)
        return {"hits": [], "scanned": 1, "runs": 1, "unindexed": 0,
                "backend": "store", "cancelled": True}

    monkeypatch.setattr(S, "runs_for_scope", lambda _n: {
        "rows": [{"name": "r1", "pages_done": 1}], "kind": "all", "key": "",
        "shifra": ""})
    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "stale_count", lambda *_a, **_k: 0)
    monkeypatch.setattr(D, "is_fresh", lambda _r: True)
    monkeypatch.setattr(ST, "sweep", fake_sweep)
    res = S.search("Ярошинський", context=0, rank=False, profile=False, given=False)
    assert got.get("progress") is P.report, "поступ свіпу нікуди не йде"
    assert got.get("cancel") is P.stopped, "сигнал зупинки до свіпу не доходить"
    assert res.get("stopped") is True, "спинений свіп загубив свою позначку"


@pytest.mark.parametrize("cancelled", [True, False])
def test_a_stopped_case_search_leaves_no_searched_trace(monkeypatch, cancelled) -> None:
    """🔴 Спинений свіп справу не прочесав. Його слід «0 знахідок по всіх
    сторінках» затирав повний запис того самого запиту, і `coverage
    --unsearched` ховав справу як шукану."""
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST
    from nyshporka.search import trace as TRACE

    noted: list[str] = []
    monkeypatch.setattr(S, "runs_for_scope", lambda _n: {
        "rows": [{"name": "r1", "pages_done": 10, "frames": 10}], "kind": "case",
        "key": "DAHMO/315/1/1", "shifra": "ДАХмО 315-1-1"})
    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "stale_count", lambda *_a, **_k: 0)
    monkeypatch.setattr(D, "is_fresh", lambda _r: True)
    monkeypatch.setattr(ST, "sweep", lambda *_a, **_k: {
        "hits": [], "scanned": 1, "runs": 1, "unindexed": 0, "backend": "store",
        "cancelled": cancelled})
    monkeypatch.setattr(TRACE, "of", lambda _k: [])
    monkeypatch.setattr(TRACE, "stale", lambda _k, _m: [])
    monkeypatch.setattr(TRACE, "note", lambda key, **_kw: noted.append(key))
    S.search("Ярошинський", name="DAHMO/315/1/1", context=0, rank=False,
             profile=False, given=False)
    assert noted == ([] if cancelled else ["DAHMO/315/1/1"])


# ── один перелік прогонів на пошук ───────────────────────────────────────────

def test_one_listing_walks_the_runs_root_once(monkeypatch) -> None:
    from nyshporka import htr_store as S

    calls: list[int] = []
    rows = [{"name": "a"}]

    def fake_list() -> list[dict[str, Any]]:
        calls.append(1)
        return rows

    # Справжній `list_cases` спершу дивиться на знімок, тож підміняємо лише
    # дорогу частину — сам обхід — через кеш-штамп.
    monkeypatch.setattr(S, "_runs_stamp", lambda: calls.append(1) or (1, 1, 1, ""))
    monkeypatch.setattr(S, "_RUNS_CACHE", ((1, 1, 1, ""), rows))
    with S.one_listing():
        for _ in range(30):
            assert S.list_cases() is rows
    assert len(calls) == 1, f"перелік прогонів у межах пошуку зібрано {len(calls)} разів"
    S.list_cases()
    assert len(calls) == 2, "поза знімком перелік знову свіжий"


# ── спинений пошук не видається за повний ────────────────────────────────────

def test_a_stopped_search_is_an_alert(monkeypatch) -> None:
    from nyshporka import htr_store as S
    from nyshporka.ops_builtin import SearchArgs, search_run

    monkeypatch.setattr(S, "search", lambda *a, **k: {
        "hits": [], "cases": 40, "pages": 900, "runs_total": 4800,
        "unindexed": 0, "stopped": True, "scope": "all"})
    monkeypatch.setattr(S, "list_cases", lambda: [])
    env = search_run(SearchArgs(q="Ярошинський", where="decode"))
    got = [w for w in env.warnings if w.code == "search_stopped"]
    assert got and got[0].level == ALERT
    assert "40" in got[0].text and "4800" in got[0].text


@pytest.fixture(autouse=True)
def _no_listing_leak() -> Any:
    """Знімок переліку не має пережити тест."""
    from nyshporka import htr_store as S

    yield
    assert S._LISTING.get() is None
