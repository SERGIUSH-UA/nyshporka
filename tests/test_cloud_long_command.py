"""Довга команда їде на машину файлом по SFTP, а не рядком `exec`.

Підстава — перша справжня оренда (Vast, 19.09.2026). Команда розпакування кадрів
на 213 символів дійшла до `bash -c` без хвоста: «unexpected EOF while looking
for matching `)'». Вона не виконалась узагалі, приймач заливки чесно сказав
«0 кадрів із 3», машину погасили — але це коштувало двох оренд, бо коротші
команди того самого заходу проходили, і причина не була очевидною.
"""
from __future__ import annotations

import io
from typing import Any

from nyshporka.cloud import ssh as S


class _Channel:
    def __init__(self) -> None:
        self.closed_for_write = False

    def shutdown_write(self) -> None:
        self.closed_for_write = True

    def recv_exit_status(self) -> int:
        return 0


class _Stdin:
    def __init__(self, channel: _Channel) -> None:
        self.channel = channel
        self.written = ""

    def write(self, text: str) -> None:
        self.written += text

    def flush(self) -> None:
        pass


class _Stdout(io.StringIO):
    def __init__(self, text: str, channel: _Channel) -> None:
        super().__init__(text)
        self.channel = channel


class _File:
    def __init__(self, store: dict, name: str) -> None:
        self.store, self.name, self.text = store, name, ""

    def write(self, text: str) -> None:
        self.text += text

    def __enter__(self) -> _File:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.store[self.name] = self.text


class _Sftp:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def open(self, name: str, mode: str) -> _File:
        return _File(self.files, name)

    def get_channel(self) -> Any:
        class _Ch:
            def settimeout(self, _s: float) -> None:
                pass
        return _Ch()


class _Client:
    def __init__(self) -> None:
        self.execs: list[str] = []
        self.sftp = _Sftp()

    def exec_command(self, cmd: str, **kw: Any) -> tuple[Any, Any, Any]:
        self.execs.append(cmd)
        channel = _Channel()
        return _Stdin(channel), _Stdout("landed=3\n", channel), io.BytesIO(b"")

    def open_sftp(self) -> _Sftp:
        return self.sftp


def _session(client: _Client) -> S.SshSession:
    return S.SshSession(client, S.Host(name="box", user="root", host="203.0.113.7"))


def test_a_short_command_goes_as_it_always_did() -> None:
    client = _Client()
    got = _session(client).run("echo landed=3")
    assert client.execs == ["echo landed=3"]
    assert got.rc == 0 and got.out == "landed=3"


def test_a_long_command_travels_as_a_file() -> None:
    client = _Client()
    long_cmd = ("cd /workspace/nysh-run/some-case__a36470a1 && tar -xf "
                "/workspace/nysh-run/some-case__a36470a1/case.tar && rm -f "
                "/workspace/nysh-run/some-case__a36470a1/case.tar; "
                "echo landed=$(ls case 2>/dev/null | wc -l)")
    assert len(long_cmd) > S.LONG_COMMAND
    got = _session(client).run(long_cmd)
    # у рядок exec пішов лише короткий виклик файла — обрізати там нема чого
    (wire,) = client.execs
    assert len(wire) <= S.LONG_COMMAND and wire.startswith("sh /tmp/.nysh-")
    # код виходу самої команди мусить дожити до нас попри прибирання файла
    assert "nysh_rc=$?" in wire and wire.endswith("exit $nysh_rc")
    (script,) = client.sftp.files.values()
    assert script == long_cmd + "\n"
    assert got.out == "landed=3"


def test_the_length_that_matters_is_of_the_longest_line() -> None:
    """Багаторядковий скрипт із короткими рядками й так проходив — його не чіпаємо."""
    client = _Client()
    script = "\n".join(f"echo line{i}" for i in range(60))
    assert len(script) > S.LONG_COMMAND
    _session(client).run(script)
    assert client.execs == [script]
