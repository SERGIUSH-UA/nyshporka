"""🛟 Захід під поганим зв'язком: обрив каналу не вбиває роботу й не гасить машину.

Вади з рецензії 19.09.2026. Спільне в усіх: захід реагував на стан НАШОГО
зв'язку з машиною так, ніби це стан роботи на ній, — і кожна така реакція
коштувала оплаченого читання.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_cloud_go import NAMES, Box1, _go, _wire

from nyshporka.cloud import go as GO
from nyshporka.cloud import run as RUN
from nyshporka.cloud.base import ChannelDropped, Completed

pytest.importorskip("PIL.Image")


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return tmp_path


def _count_stops(monkeypatch) -> list[str]:
    """Скільки разів роботу зупиняли ДО гасіння (саме гасіння б'є pid завжди)."""
    stops: list[str] = []
    real = RUN.stop_job

    def stop_job(st: Any) -> bool:
        stops.append(st.run_id)
        return real(st)

    monkeypatch.setattr(RUN, "stop_job", stop_job)
    return stops


def _drop_polls(session: Box1, monkeypatch, backend: Any, *, broken: set[int],
                finish_at: int, exc: BaseException) -> dict[str, Any]:
    """Опитування з номерами `broken` рвуться; на `finish_at` робота дочитана."""
    seen: dict[str, Any] = {"n": 0, "released_during_drop": []}
    real_run = session.run

    def run(cmd: str, *, timeout: Any = None, on_line: Any = None) -> Completed:
        if "echo pages=" in cmd:
            seen["n"] += 1
            if seen["n"] in broken:
                seen["released_during_drop"] += list(backend.released)
                raise exc
            if seen["n"] == finish_at:
                session.pretend_read(NAMES)
        return real_run(cmd, timeout=timeout, on_line=on_line)

    monkeypatch.setattr(session, "run", run)
    return seen


@pytest.mark.parametrize("exc", [EOFError(), OSError("Socket is closed"),
                                 ChannelDropped("канал обірвався")])
def test_a_channel_drop_while_polling_never_kills_the_job(
        space: Path, monkeypatch, exc: BaseException) -> None:
    """🔴 Сирий `EOFError` з опитування летів у `except Exception` нагляду, той
    кликав `stop_job` — і здорова робота на оплаченій машині гинула."""
    session = Box1(space / "box", [[]])              # робота жива й читає
    case, backend, _ = _wire(space, monkeypatch, session)
    seen = _drop_polls(session, monkeypatch, backend, broken={2, 3, 4},
                       finish_at=6, exc=exc)
    stops = _count_stops(monkeypatch)

    warnings: list[str] = []
    res = _go(case, on_event=lambda kind, text, **_: (
        warnings.append(text) if kind == "warning" else None))

    assert res.verdict == "ok", res.why
    assert stops == [], "роботу не вбито"
    assert seen["released_during_drop"] == [], "під час обриву машину не гасили"
    assert backend.released == ["ok"] and backend.acquired == 1
    assert sum("не відповідає" in w for w in warnings) == 3


def test_no_answer_about_the_pid_is_not_a_dead_job(space: Path, monkeypatch) -> None:
    """🔴 `alive()` без відповіді раніше був `False`: нагляд виходив з очікування,
    забирав частину справи, виносив `incomplete` і гасив машину."""
    session = Box1(space / "box", [["0000"]])
    case, backend, _ = _wire(space, monkeypatch, session)
    real_spawn = session.spawn

    def spawn(cmd: str, *, log: str, pidfile: str) -> int:
        pid = real_spawn(cmd, log=log, pidfile=pidfile)
        (session._run_dir() / RUN.DONE_FLAG).unlink(missing_ok=True)
        session.alive_flag = True                    # одна сторінка є, читає далі
        return pid

    monkeypatch.setattr(session, "spawn", spawn)
    calls = {"n": 0}

    def alive(pid: int) -> bool:
        calls["n"] += 1
        if calls["n"] in (3, 4):
            raise ChannelDropped("машина не відповіла, чи живий pid")
        if calls["n"] == 6:
            session.pretend_read(NAMES)
        return session.alive_flag

    monkeypatch.setattr(session, "alive", alive)
    stops = _count_stops(monkeypatch)
    res = _go(case)
    assert (res.verdict, res.pages_done) == ("ok", 3), res.why
    assert stops == [] and backend.released == ["ok"]


def test_silence_beyond_the_limit_is_still_a_failure(space: Path, monkeypatch) -> None:
    """Лічильник відмов лишається стелею: вічно мовчазна машина — збій."""
    session = Box1(space / "box", [[]])
    case, backend, _ = _wire(space, monkeypatch, session)
    _drop_polls(session, monkeypatch, backend, broken=set(range(1, 500)),
                finish_at=-1, exc=EOFError())
    monkeypatch.setattr(GO, "FETCH_RETRY_PAUSES", (), raising=False)
    res = _go(case)
    assert res.verdict == "failed"
    assert len(backend.released) == 1 and backend.released[0].startswith("failed")


# ── забір ────────────────────────────────────────────────────────────────────
def _break_fetch(session: Box1, monkeypatch, *, times: int, exc: BaseException) -> dict[str, int]:
    """Перші `times` спроб забрати архів рвуться."""
    seen = {"n": 0}
    real_get = session.get

    def get(remote: str, local: Path) -> int:
        seen["n"] += 1
        if seen["n"] <= times:
            raise exc
        return real_get(remote, local)

    monkeypatch.setattr(session, "get", get)
    return seen


def test_one_network_blip_at_fetch_time_does_not_cost_the_whole_case(
        space: Path, monkeypatch) -> None:
    """🔴 Збій мережі в мить забору раніше вів просто до гасіння: машина жива,
    текст на ній — і його знищували разом із нею."""
    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)
    seen = _break_fetch(session, monkeypatch, times=3,
                        exc=ChannelDropped("канал обірвався (забір result.tar)"))
    pauses: list[float] = []
    monkeypatch.setattr(GO, "_sleep", pauses.append)
    told: list[str] = []

    res = _go(case, on_event=lambda kind, text, **_: told.append(text))

    assert (res.verdict, res.pages_done) == ("ok", 3), res.why
    assert seen["n"] == 4 and backend.released == ["ok"]
    assert [p for p in pauses if p] == [15.0, 30.0, 60.0], "паузи наростають"
    assert sum("забір не вдався" in t for t in told) == 3, "людині сказано"


def test_a_box_that_is_gone_is_not_waited_for(space: Path, monkeypatch) -> None:
    from nyshporka.cloud.base import BoxGone

    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)
    seen = _break_fetch(session, monkeypatch, times=99, exc=BoxGone("інстансу немає"))
    res = _go(case)
    assert res.verdict == "failed" and "інстансу немає" in res.why
    assert seen["n"] == 2, "основна спроба й одна аварійна — без очікування"
    assert len(backend.released) == 1


def test_fetch_retries_end_at_the_ceiling(space: Path, monkeypatch) -> None:
    """Стеля лишається стелею: після неї — кілька спроб, і гасимо без забору."""
    import time as _t

    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)
    seen = _break_fetch(session, monkeypatch, times=999,
                        exc=ChannelDropped("канал обірвався"))
    clock = {"t": _t.time()}
    monkeypatch.setattr(GO, "_now", lambda: clock["t"])
    monkeypatch.setattr(GO, "_sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

    res = _go(case, max_hours=1.0)
    assert res.verdict == "failed" and res.released is True
    assert len(backend.released) == 1, "машину погашено рівно раз"
    assert 10 < seen["n"] < 60, "чекали до стелі години, а не вічно й не один раз"
    assert any("забрати прочитане не вдалось" in n for n in res.notes)
