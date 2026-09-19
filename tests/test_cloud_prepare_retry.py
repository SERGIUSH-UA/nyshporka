"""Підготовка середовища переживає обрив каналу до машини.

Підстава — справжня оренда 19.09.2026: `uv pip install kraken` на пів хвилині
завантаження колес повернув rc=-1 (канал SSH закрився без статусу виходу).
Машину погасили, оплачений підйом пішов у нуль. Кроки встановлення ідемпотентні,
а вже скачане `uv` тримає в кеші — тож обрив лікується перепідключенням і
повтором того самого кроку, а не новою орендою.
"""
from __future__ import annotations

from typing import Any

import pytest

from nyshporka.cloud import run as RUN
from nyshporka.cloud.base import Completed


class _Box:
    """Сесія, у якої встановлення пакета обривається задану кількість разів."""

    def __init__(self, drops: int, log: list[str]) -> None:
        self.drops, self.log = drops, log

    def resolve(self, remote: str) -> str:
        return remote

    def run(self, cmd: str, *, timeout: Any = None, on_line: Any = None) -> Completed:
        self.log.append(cmd)
        if "command -v uv" in cmd:
            return Completed(rc=0, out="yes")
        if "import kraken" in cmd:
            return Completed(rc=0, out="OK 2.4.0 True")
        if " pip install " in cmd and self.drops > 0:
            self.drops -= 1
            return Completed(rc=-1, out="Downloading nvidia-cudnn-cu12 (674.0MiB)", err="")
        return Completed(rc=0, out="")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RUN.time, "sleep", lambda _s: None)


def test_a_dropped_channel_is_reconnected_and_the_step_repeated() -> None:
    log: list[str] = []
    said: list[str] = []
    fresh = _Box(drops=0, log=log)
    reconnects: list[int] = []

    def reconnect() -> _Box:
        reconnects.append(1)
        return fresh

    RUN.prepare(_Box(drops=1, log=log), "/work/run1", on_line=said.append,
                reconnect=reconnect)
    assert reconnects == [1]
    installs = [c for c in log if " pip install " in c]
    # той самий крок пішов удруге — вже на свіжій сесії — і далі все як завжди
    assert installs[0] == installs[1]
    assert any("перепідключаюсь" in line for line in said)


def test_a_channel_that_keeps_dropping_fails_in_words() -> None:
    log: list[str] = []
    with pytest.raises(RUN.RunError, match="не поставився"):
        RUN.prepare(_Box(drops=99, log=log), "/work/run1",
                    reconnect=lambda: _Box(drops=99, log=log))
    assert len([c for c in log if " pip install " in c]) == RUN.PREPARE_RETRIES


def test_without_a_way_to_reconnect_nothing_is_retried() -> None:
    log: list[str] = []
    with pytest.raises(RUN.RunError):
        RUN.prepare(_Box(drops=1, log=log), "/work/run1")
    assert len([c for c in log if " pip install " in c]) == 1
