"""🔒 Замок простору: один писар, але без вічного замка.

Дві протилежні відмови, і обидві дорогі. Пустити другого писаря — черги
затирають одна одну, і завдання «зникають». Не пустити нікого після аварійного
завершення — застосунок більше не відкривається, і зрушити це можна лише
здогадавшись видалити службовий файл.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from nyshporka.core import lock as L


def test_first_takes_it_second_is_refused(tmp_path):
    with L.WorkspaceLock(tmp_path, port=8765) as first:
        assert first.held
        with pytest.raises(L.LockBusy) as exc:
            L.WorkspaceLock(tmp_path).acquire()
        # Повідомлення мусить казати, хто тримає й що робити.
        msg = str(exc.value)
        assert str(os.getpid()) in msg and "8765" in msg
        assert "Закрийте" in msg or "інший простір" in msg


def test_release_frees_the_space(tmp_path):
    lk = L.WorkspaceLock(tmp_path).acquire()
    lk.release()
    assert not lk.held
    L.WorkspaceLock(tmp_path).acquire().release()   # не має кинути


def test_context_manager_releases_even_on_error(tmp_path):
    with pytest.raises(RuntimeError), L.WorkspaceLock(tmp_path):
        raise RuntimeError("щось пішло не так")
    assert L.read(tmp_path) is None, "замок лишився після винятку"


def test_abandoned_lock_is_taken_over(tmp_path):
    """🔴 Вічний замок = «застосунок більше не запускається» після одного падіння.

    Тому покинутий (мертвий власник або мовчання довше за межу) забирається.
    """
    stale = {"pid": os.getpid(), "host": "old", "started": time.time(),
             "heartbeat": time.time() - L.STALE_SEC - 5, "port": None}
    (tmp_path / L.LOCK_NAME).write_text(json.dumps(stale), encoding="utf-8")

    with L.WorkspaceLock(tmp_path) as lk:
        assert lk.held
        assert L.read(tmp_path).heartbeat > stale["heartbeat"]


def test_live_lock_is_never_stolen(tmp_path):
    """Автоматичне «зняти й забрати» одного разу вб'є прогін на кілька годин."""
    with L.WorkspaceLock(tmp_path), pytest.raises(L.LockBusy):
        L.WorkspaceLock(tmp_path, steal_stale=True).acquire()


def test_started_is_the_process_time_not_the_lock_time(tmp_path):
    """🔴 Регресія: власний живий замок можна було вкрасти.

    Перша редакція клала в `started` момент створення `WorkspaceLock`, а звіряла
    його з `create_time()` процесу. Розходження — весь час, що процес прожив до
    відкриття простору, тож власний замок виглядав чужим і мертвим.

    Тест ловить це прямо, а не через наслідок: інакше наступний рефакторинг
    поверне ту саму підміну, і впаде вона знову лише в рідкісному сценарії.
    """
    psutil = pytest.importorskip("psutil")
    with L.WorkspaceLock(tmp_path):
        info = L.read(tmp_path)
        assert abs(info.started - psutil.Process().create_time()) < 2.0
        assert L._process_alive(info.pid, info.started), "власний процес — живий"


def test_dead_process_lock_is_taken_over(tmp_path, monkeypatch):
    fresh = {"pid": 999999, "host": "інша машина", "started": time.time(),
             "heartbeat": time.time(), "port": 8765}
    (tmp_path / L.LOCK_NAME).write_text(json.dumps(fresh), encoding="utf-8")
    monkeypatch.setattr(L, "_process_alive", lambda pid, started: False)
    with L.WorkspaceLock(tmp_path) as lk:
        assert lk.held


def test_pid_reuse_is_rejected_by_start_time(tmp_path, monkeypatch):
    """🔴 Через тиждень той самий номер дістанеться чужому процесу.

    Перевірка «чи живий PID» сказала б «так», і замок вважався б живим вічно.
    Розрізняє їх саме час старту.
    """
    seen: dict[str, float] = {}

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return True

        def status(self):
            return "running"

        def create_time(self):
            return seen["now"]

    psutil = pytest.importorskip("psutil")
    monkeypatch.setattr(psutil, "Process", FakeProc)
    seen["now"] = time.time()
    assert L._process_alive(4242, seen["now"])
    # той самий PID, але процес стартував пізніше — це вже не наш
    assert not L._process_alive(4242, seen["now"] - 3600)


def test_heartbeat_keeps_the_lock_fresh(tmp_path):
    with L.WorkspaceLock(tmp_path) as lk:
        first = L.read(tmp_path).heartbeat
        time.sleep(0.05)
        lk.beat()
        assert L.read(tmp_path).heartbeat > first


def test_corrupt_lock_file_does_not_block_forever(tmp_path):
    """Обірваний запис попередника — не привід не запускатись."""
    (tmp_path / L.LOCK_NAME).write_text("{обірваний", encoding="utf-8")
    assert L.read(tmp_path) is None
    with L.WorkspaceLock(tmp_path) as lk:
        assert lk.held


def test_release_does_not_remove_someone_elses_lock(tmp_path):
    """Якщо ми завмерли й замок перехопили — знімати чужий не можна."""
    lk = L.WorkspaceLock(tmp_path).acquire()
    other = {"pid": 999999, "host": "інший", "started": time.time(),
             "heartbeat": time.time(), "port": None}
    (tmp_path / L.LOCK_NAME).write_text(json.dumps(other), encoding="utf-8")
    lk.release()
    assert L.read(tmp_path).pid == 999999, "зняли чужий замок"


def test_lock_reports_who_holds_it(tmp_path):
    with L.WorkspaceLock(tmp_path, port=1234):
        info = L.read(tmp_path)
        assert info.pid == os.getpid() and info.port == 1234
        assert info.age() < 5 and not info.is_stale()


def test_reacquire_on_a_held_lock_is_a_noop(tmp_path):
    """🔴 `with WorkspaceLock(...).acquire() as l:` не має відмовляти сам собі.

    Це найприродніший запис, і `__enter__` у ньому кличе `acquire` вдруге.
    Без ідемпотентності процес знаходив власний щойно створений замок і
    відмовлявся стартувати — повідомленням «простір уже зайнято іншим
    процесом», яке називало чужим його ж pid. Спіймано на першому живому
    запуску демона, не тестом.
    """
    from nyshporka.core.lock import WorkspaceLock

    with WorkspaceLock(tmp_path).acquire() as held:
        assert held.held
    assert not (tmp_path / ".lock").exists()
