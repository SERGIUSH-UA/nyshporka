"""🛑 Скасування роботи, живучість замка й один 404 усередині плівки.

Три відмови, які об'єднує те, що система після них звітує про успіх:
скасований прогін сам оголошував себе виконаним, замок живого демона віддавався
другому процесу як покинутий, а один відсутній кадр із дев'ятисот забирав із
собою лічильники всіх узятих.
"""
from __future__ import annotations

import time

import pytest

from nyshporka.core.jobs import JobBus, JobState


@pytest.fixture
def bus(tmp_path) -> JobBus:
    return JobBus(tmp_path / "jobs.json")


# ── скасування ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cancel_runs_the_stopper(bus):
    """«Спинити» доходить до підпроцесу, а не лише до кольору рядка."""
    job, _ = await bus.enqueue("read", title="справа")
    stopped: list[str] = []
    bus.on_stop(job.id, lambda: stopped.append(job.id))

    await bus.cancel(job.id)
    assert stopped == [job.id], "зупинювач не викликано"
    assert bus.get(job.id).state == JobState.CANCELLED


@pytest.mark.asyncio
async def test_cancelled_job_cannot_become_done(bus):
    """🔴 Виконавець доходить до кінця тіла й ставить DONE — стан не рухається.

    Саме через це скасований HTR-прогін через кілька годин з'являвся в списку
    як успішно завершений.
    """
    job, _ = await bus.enqueue("read", title="справа")
    await bus.cancel(job.id)

    await bus.update(job.id, state=JobState.DONE, result={"pages": 120})
    after = bus.get(job.id)
    assert after.state == JobState.CANCELLED
    assert after.result == {"pages": 120}, "корисний результат мав записатись"


@pytest.mark.asyncio
async def test_cancel_releases_idempotency_key(bus):
    """Скасував — можна запустити знову, не чекаючи десять хвилин.

    Ключ ідемпотентності живе 600 с; доти повторний запуск тієї самої справи
    повертав скасований запис із `created=False` і не стартував нічого.
    """
    job, created = await bus.enqueue("read", title="справа",
                                     idempotency_key="read:/out/спр4")
    assert created
    await bus.cancel(job.id)

    again, created2 = await bus.enqueue("read", title="справа",
                                        idempotency_key="read:/out/спр4")
    assert created2, "повторний запуск упирався в скасовану роботу"
    assert again.id != job.id


@pytest.mark.asyncio
async def test_stopper_failure_does_not_block_cancel(bus):
    """Не вдалось убити процес — стан усе одно скасований."""
    job, _ = await bus.enqueue("read", title="справа")

    def boom() -> None:
        raise ProcessLookupError("процес уже помер")

    bus.on_stop(job.id, boom)
    await bus.cancel(job.id)
    assert bus.get(job.id).state == JobState.CANCELLED


# ── замок простору ───────────────────────────────────────────────────────────
def test_live_lock_is_not_stolen_after_stale_timeout(tmp_path, monkeypatch):
    """🔴 Тиша сама по собі більше не привід забрати замок у живого процесу.

    Було `is_stale() OR не живий`, а серце демона билось один раз — тож будь-який
    демон, старший за 45 с, віддавав свій простір першому охочому.
    """
    from nyshporka.core import lock as L

    holder = L.WorkspaceLock(tmp_path, port=8765).acquire()
    try:
        # відмотуємо серцебиття далеко за межу протухлості
        info = L.read(tmp_path)
        stale = {**info.as_dict(), "heartbeat": time.time() - L.STALE_SEC * 10}
        (tmp_path / L.LOCK_NAME).write_text(
            __import__("json").dumps(stale), encoding="utf-8")

        # процес (цей самий, живий) — psutil його бачить
        with pytest.raises(L.LockBusy):
            L.WorkspaceLock(tmp_path).acquire()
    finally:
        holder.release()


def test_dead_holder_lock_is_taken_immediately(tmp_path):
    """Мертвий власник — замок забирається одразу, не чекаючи 45 с."""
    import json

    from nyshporka.core import lock as L

    (tmp_path / L.LOCK_NAME).write_text(json.dumps({
        "pid": 999_999, "host": "нема", "started": time.time(),
        "heartbeat": time.time(), "port": None}), encoding="utf-8")

    taken = L.WorkspaceLock(tmp_path).acquire()
    try:
        assert taken.held
    finally:
        taken.release()


# ── один 404 усередині плівки ────────────────────────────────────────────────
def test_status_error_is_wrapped_into_http_error():
    """🔴 4xx виходить як `HttpError`, який цикли завантаження вже ловлять.

    Голий `httpx.HTTPStatusError` пролітав крізь `except (HttpError, OSError)`:
    один 404 на кадрі №300 із 991 валив увесь прогін, губив лічильники 299 уже
    взятих кадрів і не давав спрацювати запобіжнику «10 промахів поспіль».
    """
    import httpx

    from nyshporka.sources.http import Fetcher, HttpError

    class _Resp:
        status_code = 404

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("нема", request=None,  # type: ignore[arg-type]
                                        response=None)          # type: ignore[arg-type]

    f = Fetcher(delay=0.0)
    with pytest.raises(HttpError) as got:
        f._send("https://архів/кадр/300.jpg", lambda: _Resp())
    assert "404" in str(got.value)


# ── загальна довга операція (аудит 29.09.2026) ───────────────────────────────
@pytest.mark.asyncio
async def test_a_cancelled_generic_op_blocks_a_second_run_until_its_thread_ends(
        bus, monkeypatch):
    """🔴 «Скасувати» над злиттям реєстру не спиняло потоку — і гейт відкривався.

    Загальний виконавець гасителя не реєструє, тож скасування лише
    перефарбовувало рядок, а `registry.merge` ішов далі. Гейт дивився на стан,
    тож другий клік заводив паралельне злиття того самого реєстру — рівно те,
    від чого гейт ставили. Тепер робота «йде», доки йде потік, а скасування
    чесно каже, що перервати її не може.
    """
    import asyncio
    import threading

    from nyshporka import ops as O
    from nyshporka.core.envelope import Envelope
    from nyshporka.daemon import workers as W

    entered = threading.Event()
    release = threading.Event()
    runs: list[int] = []

    class _Op:
        summary = "злиття реєстру"

    def fake_call(name, payload=None):
        runs.append(1)
        entered.set()
        release.wait(5)
        return Envelope(ok=True, data={"merged": 3})

    monkeypatch.setattr(O, "get", lambda name: _Op())
    monkeypatch.setattr(O, "call", fake_call)

    job = await W._start_generic(bus, "registry.merge", {"fond": "904"})
    assert await asyncio.to_thread(entered.wait, 5), "тіло операції не стартувало"

    await bus.cancel(job.id)
    await asyncio.sleep(0.05)
    after = bus.get(job.id)
    assert after.state == JobState.CANCELLED
    assert any(w["code"] == "cant_interrupt" for w in after.warnings), (
        "скасування вдавало, що спинило роботу")

    with pytest.raises(ValueError, match="ще йде"):
        await W._start_generic(bus, "registry.merge", {"fond": "904"})
    assert runs == [1], "друге злиття пішло паралельно з першим"

    release.set()
    await W._GENERIC_RUNS[job.id]
    done = bus.get(job.id)
    assert done.state == JobState.CANCELLED
    assert done.result == {"merged": 3}
    assert any(w["code"] == "finished_after_cancel" for w in done.warnings)

    again = await W._start_generic(bus, "registry.merge", {"fond": "904"})
    assert again.id != job.id, "після кінця потоку новий запуск мав піти"
    tail = W._GENERIC_RUNS.get(again.id)
    if tail is not None:
        await tail
