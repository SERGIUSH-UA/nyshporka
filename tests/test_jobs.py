"""📋 Черга завдань: гонка, ідемпотентність, курсор, відновлення.

Тут перевіряється не «черга працює», а чотири конкретні відмови, кожна з яких
не падає й тому невидима: подвоєний прогін, повторений ретрай, загублена подія
для читача без стріму, і завдання-привид після перезапуску.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from nyshporka.core.jobs import JobBus, JobState

pytestmark = pytest.mark.asyncio


@pytest.fixture
def bus(tmp_path) -> JobBus:
    return JobBus(tmp_path / "jobs.json")


# ── гонка постановки ─────────────────────────────────────────────────────────
async def test_concurrent_enqueue_with_same_key_gives_one_job(bus):
    """🔴 Та сама відмова, що була в наявному менеджері.

    Постановка робила read-check-append без синхронізації, тож два одночасні
    запити (два вікна браузера, або людина й агент) давали ДВА завдання на ту
    саму справу. Помилки немає: обидва «успішно поставлені», а далі два прогони
    б'ються за карту й за ті самі сторінки.
    """
    results = await asyncio.gather(*[
        bus.enqueue("read", cfg={"case": "X"}, idempotency_key="k1")
        for _ in range(12)
    ])
    ids = {rec.id for rec, _ in results}
    assert len(ids) == 1, f"постановка задвоїлась: {ids}"
    assert sum(1 for _, created in results if created) == 1, "створити мали рівно раз"
    assert len(bus.jobs()) == 1


async def test_repeated_key_after_the_fact_returns_the_same_job(bus):
    """Ретрай агента після обриву мережі не має ставити ще один прогін."""
    first, created = await bus.enqueue("read", idempotency_key="abc")
    assert created
    again, created2 = await bus.enqueue("read", idempotency_key="abc")
    assert not created2 and again.id == first.id


async def test_different_keys_are_different_jobs(bus):
    a, _ = await bus.enqueue("read", idempotency_key="a")
    b, _ = await bus.enqueue("read", idempotency_key="b")
    assert a.id != b.id and len(bus.jobs()) == 2


async def test_no_key_means_no_deduplication(bus):
    """Без ключа два запити — це два завдання, і це правильно."""
    a, _ = await bus.enqueue("read")
    b, _ = await bus.enqueue("read")
    assert a.id != b.id


# ── попередня перевірка ──────────────────────────────────────────────────────
async def test_precheck_refusal_is_a_readable_error(bus):
    async def refuse():
        return "справа вже читається іншим завданням"

    with pytest.raises(ValueError, match="вже читається"):
        await bus.enqueue("read", precheck=refuse)
    assert not bus.jobs(), "відмовлене завдання не має лишати сліду"


async def test_precheck_runs_twice_once_outside_and_once_under_lock(bus):
    """🔴 Дорога перевірка йде ДО лока, але повторюється ПІД ним.

    Тільки до лока — двоє пройшли б її одночасно. Тільки під локом — читання
    диска серіалізувало б усіх, а не лише запис.
    """
    calls = 0

    async def counting():
        nonlocal calls
        calls += 1
        return None

    await bus.enqueue("read", precheck=counting)
    assert calls == 2


# ── курсор для читача без стріму ─────────────────────────────────────────────
async def test_cursor_returns_only_what_is_new(bus):
    a, _ = await bus.enqueue("read", title="перше")
    events, cur = bus.since(0)
    assert len(events) == 1 and events[0]["job"]["id"] == a.id

    events2, cur2 = bus.since(cur)
    assert events2 == [] and cur2 == cur

    await bus.enqueue("read", title="друге")
    events3, _ = bus.since(cur)
    assert len(events3) == 1 and events3[0]["job"]["title"] == "друге"


async def test_wait_returns_immediately_when_there_is_news(bus):
    await bus.enqueue("read")
    events, _ = await asyncio.wait_for(bus.wait(0, timeout=5), timeout=1)
    assert events


async def test_wait_wakes_up_on_change(bus):
    """Блокування на сервері: один виклик замість циклу опитувань."""
    cur = bus.seq

    async def later():
        await asyncio.sleep(0.05)
        await bus.enqueue("read", title="пізніше")

    task = asyncio.create_task(later())
    events, _ = await asyncio.wait_for(bus.wait(cur, timeout=5), timeout=2)
    await task
    assert events and events[0]["job"]["title"] == "пізніше"


async def test_wait_times_out_with_state_not_error(bus):
    """Тиша — це відповідь «нічого не змінилось», а не помилка."""
    events, cur = await asyncio.wait_for(bus.wait(bus.seq, timeout=0.1), timeout=2)
    assert events == [] and cur == bus.seq


async def test_every_change_advances_the_cursor(bus):
    job, _ = await bus.enqueue("read")
    seqs = [job.seq]
    for state in (JobState.RUNNING, JobState.DONE):
        upd = await bus.update(job.id, state=state)
        seqs.append(upd.seq)
    assert seqs == sorted(set(seqs)), f"курсор не зростає монотонно: {seqs}"


# ── оновлення ────────────────────────────────────────────────────────────────
async def test_update_of_unknown_job_is_none_not_crash(bus):
    """Прогін міг завершитись, поки подія йшла з підпроцесу — це нормальна гонка."""
    assert await bus.update("нема-такого", state=JobState.DONE) is None


async def test_cancel_does_not_resurrect_a_finished_job(bus):
    job, _ = await bus.enqueue("read")
    await bus.update(job.id, state=JobState.DONE)
    after = await bus.cancel(job.id)
    assert after.state is JobState.DONE


async def test_progress_percent_is_derived_not_stored(bus):
    from nyshporka.core.jobs import Progress

    job, _ = await bus.enqueue("read")
    await bus.update(job.id, progress=Progress(i=41, n=100, basis="робота"))
    assert bus.get(job.id).progress.pct == 41.0
    assert bus.get(job.id).as_dict()["progress"]["pct"] == 41.0


async def test_progress_with_zero_total_does_not_divide_by_zero(bus):
    from nyshporka.core.jobs import Progress

    job, _ = await bus.enqueue("read")
    await bus.update(job.id, progress=Progress(i=0, n=0))
    assert bus.get(job.id).progress.pct == 0.0


# ── переживання перезапуску ──────────────────────────────────────────────────
async def test_state_survives_restart(bus, tmp_path):
    job, _ = await bus.enqueue("read", title="довга справа", cfg={"case": "X"})
    await bus.update(job.id, state=JobState.DONE, result={"pages": 20})

    fresh = JobBus(tmp_path / "jobs.json")
    assert fresh.load() == 1
    got = fresh.get(job.id)
    assert got.title == "довга справа" and got.result == {"pages": 20}


async def test_running_jobs_come_back_as_queued(bus, tmp_path):
    """🔴 Процес, що їх виконував, помер разом із застосунком.

    Лишити їх «у роботі» означало б чергу, назавжди зайняту привидами: нові
    завдання не стартують, бо «одне вже біжить», і зрушити це можна лише
    руками, здогадавшись подивитись у JSON.
    """
    job, _ = await bus.enqueue("read")
    await bus.update(job.id, state=JobState.RUNNING)

    fresh = JobBus(tmp_path / "jobs.json")
    fresh.load()
    assert fresh.get(job.id).state is JobState.QUEUED


async def test_broken_state_file_does_not_block_startup(tmp_path):
    """Краще почати з порожньою чергою, ніж не запуститись зовсім."""
    path = tmp_path / "jobs.json"
    path.write_text("{обірваний", encoding="utf-8")
    assert JobBus(path).load() == 0


async def test_failed_persist_does_not_kill_a_live_job(bus, monkeypatch):
    """🔴 Диск може бути повний або зайнятий антивірусом.

    Втратити стан на рестарті прикро; впасти посеред живого прогону — гірше:
    користувач втратить години роботи через невдалий запис службового файлу.

    Права доступу тут не годяться для перевірки (на Windows `chmod` теки нічого
    не забороняє), тому ламається саме операція запису.
    """
    import os as _os

    def boom(*_a, **_kw):
        raise OSError("диск повний")

    monkeypatch.setattr(_os, "replace", boom)
    job, created = await bus.enqueue("read")     # не має кинути
    assert created and job.state is JobState.QUEUED
    # і черга в пам'яті лишається правильною
    assert bus.get(job.id) is job


async def test_persisted_file_is_valid_json(bus):
    await bus.enqueue("read", title="перевірка")
    data = json.loads(bus.path.read_text(encoding="utf-8"))
    assert data["jobs"] and data["seq"] >= 1
