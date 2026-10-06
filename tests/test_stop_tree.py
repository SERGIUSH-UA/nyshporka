"""🛑 «Спинити» гасить читання з УСІМА нащадками — на справжніх процесах.

Раннер читає не сам: наглядач запускає робочий процес, і той пише прогрес у
спільний канал. 06.10.2026 у людини застосунок гасив наглядача раніше, ніж
знімав дерево, робочий процес лишався сиротою й дочитав ще 15 сторінок під
написом «спинено», не пускаючи до карти наступне читання.

Двійник тут нічого не доведе: вада сидить у тому, як Windows поводиться з
дітьми вбитого батька. Тому — справжні процеси Python: «наглядач» запускає
«робочого», той друкує в успадкований канал, поки живий.
"""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import time

import psutil
import pytest

from nyshporka.core.jobs import JobBus
from nyshporka.core.proctree import contain

#: «Наглядач»: запускає «робочого» з успадкованим виводом, друкує його pid,
#: далі живе сам. «Робочий» друкує рядок прогресу раз на 0,2 с.
SUPERVISOR = (
    "import subprocess, sys, time\n"
    "kid = subprocess.Popen([sys.executable, '-c', "
    "'import time\\nwhile True:\\n print(\"page\", flush=True)\\n time.sleep(0.2)'])\n"
    "print(kid.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _gone(pid: int, within: float = 10.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not psutil.pid_exists(pid):
            return True
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.Error:
            return True
        time.sleep(0.1)
    return False


def _cleanup(*pids: int) -> None:
    for pid in pids:
        with contextlib.suppress(psutil.Error):
            psutil.Process(pid).kill()


# ── Job Object ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="Job Object є лише на Windows")
def test_kill_takes_children_born_after_contain() -> None:
    """Нащадок, народжений ПІСЛЯ `contain`, потрапляє в об'єкт сам."""
    proc = subprocess.Popen([sys.executable, "-c", SUPERVISOR],
                            stdout=subprocess.PIPE, text=True)
    tree = contain(proc.pid)
    assert tree is not None
    kid = int(proc.stdout.readline())  # type: ignore[union-attr]
    try:
        tree.kill()
        assert _gone(proc.pid) and _gone(kid), "робочий процес пережив зупинку"
    finally:
        tree.close()
        _cleanup(proc.pid, kid)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object є лише на Windows")
def test_closing_the_handle_leaves_no_orphans() -> None:
    """Власник помер (застосунок закрили) — дерево гине разом із ним."""
    proc = subprocess.Popen([sys.executable, "-c", SUPERVISOR],
                            stdout=subprocess.PIPE, text=True)
    tree = contain(proc.pid)
    assert tree is not None
    kid = int(proc.stdout.readline())  # type: ignore[union-attr]
    try:
        tree.close()
        assert _gone(proc.pid) and _gone(kid)
    finally:
        _cleanup(proc.pid, kid)


def test_contain_refuses_itself_and_nonsense() -> None:
    import os

    assert contain(os.getpid()) is None
    assert contain(0) is None


# ── зупинка в застосунку ─────────────────────────────────────────────────────

async def _supervisor() -> tuple[asyncio.subprocess.Process, int]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", SUPERVISOR,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    assert proc.stdout is not None
    kid = int((await proc.stdout.readline()).decode())
    return proc, kid


async def _drain(proc: asyncio.subprocess.Process) -> None:
    assert proc.stdout is not None
    while await proc.stdout.readline():
        pass


@pytest.mark.parametrize("with_job", [False, True], ids=["kill_tree", "job_object"])
async def test_stop_reading_kills_the_worker_and_frees_the_channel(
        tmp_path, with_job: bool) -> None:
    """🔴 Головне: після «Спинити» робочий мертвий і канал закрився.

    `kill_tree` — шлях без Job Object (не Windows або `contain` не вдався):
    дерево мусить зніматись ДО того, як гине корінь.
    """
    from nyshporka.daemon.workers import _stop_reading

    if with_job and sys.platform != "win32":
        pytest.skip("Job Object є лише на Windows")
    bus = JobBus(tmp_path / "jobs.json")
    job, _ = await bus.enqueue("read", title="справа")
    proc, kid = await _supervisor()
    trees = [contain(proc.pid) if with_job else None]
    pumps = [asyncio.create_task(_drain(proc))]
    try:
        await asyncio.sleep(0.5)          # робочий уже друкує
        await _stop_reading(bus, job.id, [proc], trees, pumps)
        assert _gone(kid), "робочий процес читає далі під «спинено»"
        assert _gone(proc.pid)
        # Канал закрився — отже, читання застосунку відпустить карту.
        await asyncio.wait_for(asyncio.gather(*pumps, return_exceptions=True), 5)
        assert not (bus.get(job.id).error or "")
    finally:
        for t in trees:
            if t is not None:
                t.close()
        _cleanup(proc.pid, kid)


async def test_a_survivor_is_named_not_hidden(tmp_path, monkeypatch) -> None:
    """Процес, який не вдалось погасити, називається в завданні — не мовчки."""
    import nyshporka.htr.session as S
    from nyshporka.daemon.workers import _stop_reading

    bus = JobBus(tmp_path / "jobs.json")
    job, _ = await bus.enqueue("read", title="справа")
    proc, kid = await _supervisor()
    monkeypatch.setattr(S, "kill_tree", lambda pid, grace=5.0: [kid])
    monkeypatch.setattr("nyshporka.daemon.workers.STOP_DRAIN_SEC", 0.5)
    try:
        await _stop_reading(bus, job.id, [proc], [None], [])
        err = bus.get(job.id).error or ""
        assert str(kid) in err and "диспетчері задач" in err
    finally:
        _cleanup(proc.pid, kid)
