"""Обрив каналу — подія транспорту, а не вирок роботі на машині.

Підстава — рецензія хмарного заходу 19.09.2026. `SshSession.run` віддавав
`EOFError`/`OSError`/`SSHException` сирими, лічильник відмов опитування рахує
лише `CloudError`, тож хвилинний обрив зв'язку летів просто в аварійний
обробник, і той убивав здорову роботу на оплаченій машині. Другий бік тієї ж
вади: `alive()` читав порожній вивід обірваного каналу як «мертвий».
"""
from __future__ import annotations

import io
import threading
from typing import Any

import pytest

from nyshporka.cloud import ssh as S
from nyshporka.cloud.base import ChannelDropped, CloudError


class _Channel:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc

    def recv_exit_status(self) -> int:
        return self.rc


class _Stdout(io.StringIO):
    def __init__(self, text: str, rc: int = 0) -> None:
        super().__init__(text)
        self.channel = _Channel(rc)


class _Breaking:
    """stdout, який рветься посеред читання."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.channel = _Channel(-1)

    def readline(self) -> str:
        raise self.exc


class _Client:
    def __init__(self, stdout: Any, stderr: Any = None,
                 exec_exc: BaseException | None = None) -> None:
        self.stdout, self.stderr, self.exec_exc = stdout, stderr, exec_exc

    def exec_command(self, cmd: str, **kw: Any) -> tuple[Any, Any, Any]:
        if self.exec_exc is not None:
            raise self.exec_exc
        return None, self.stdout, self.stderr or io.BytesIO(b"")


def _session(client: Any) -> S.SshSession:
    return S.SshSession(client, S.Host(name="box", user="root", host="203.0.113.7"))


@pytest.mark.parametrize("exc", [EOFError(), OSError("Socket is closed"),
                                 TimeoutError("timed out")])
def test_a_broken_read_is_a_channel_drop_not_a_raw_error(exc: BaseException) -> None:
    with pytest.raises(ChannelDropped):
        _session(_Client(_Breaking(exc))).run("echo hi")


def test_a_refused_exec_is_a_channel_drop_too() -> None:
    """`SSHException` упізнається за іменем класу в родоводі: paramiko —
    необов'язкова залежність, і модуль імпортується без неї."""

    class SSHException(Exception):
        pass

    class ChannelException(SSHException):
        pass

    client = _Client(None, exec_exc=ChannelException("SSH session not active"))
    with pytest.raises(ChannelDropped):
        _session(client).run("echo hi")
    with pytest.raises(KeyError):                 # чуже лишається чужим
        _session(_Client(None, exec_exc=KeyError("x"))).run("echo hi")


def test_a_missing_file_is_still_an_answer_not_a_drop() -> None:
    """`FileNotFoundError` — відповідь машини; `exists` на неї спирається."""

    class Sftp:
        def stat(self, _p: str) -> None:
            raise FileNotFoundError(_p)

        def get_channel(self) -> Any:
            class Ch:
                def settimeout(self, _s: float) -> None:
                    pass
            return Ch()

    class Client:
        def open_sftp(self) -> Sftp:
            return Sftp()

    assert _session(Client()).exists("/nope") is False


def test_dead_is_only_an_explicit_answer() -> None:
    """🔴 Порожній вивід обірваного каналу (rc=-1) — не «робота скінчилась»."""
    assert _session(_Client(_Stdout("nysh_job=A\n"))).alive(7) is True
    assert _session(_Client(_Stdout("motd 0\nnysh_job=D\n"))).alive(7) is False
    with pytest.raises(CloudError, match="не відповіла"):
        _session(_Client(_Stdout("", rc=-1))).alive(7)


def test_a_flood_of_stderr_does_not_deadlock_the_read() -> None:
    """🔴 stdout і stderr ділять одне вікно каналу: хто не читає stderr, поки
    чекає на stdout, той висне, щойно команда напише в stderr понад вікно.

    Модель вікна: stdout «закривається» лише після того, як stderr вичитано.
    """
    drained = threading.Event()

    class Stderr:
        def read(self) -> bytes:
            drained.set()
            return b"x" * (3 << 20)

    class Stdout:
        channel = _Channel(0)

        def __init__(self) -> None:
            self.lines = ["done\n"]

        def readline(self) -> str:
            if not drained.wait(5.0):
                raise AssertionError("stderr ніхто не читає — взаємне блокування")
            return self.lines.pop(0) if self.lines else ""

    got = _session(_Client(Stdout(), Stderr())).run("noisy")
    assert got.out == "done" and len(got.err) == 3 << 20
