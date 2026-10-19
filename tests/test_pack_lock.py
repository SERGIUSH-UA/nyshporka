"""Один повний пак тестів на машину — замок у `conftest._hold_pack_lock`.

Два паки поруч ділили ядра й пам'ять: 19.10.2026 пак на 2,5 хв тягнувся 10 хв,
а воркер xdist падав на вичерпаній пам'яті. Замок бере лише повний пак:
точкові прогони легкі й мусять іти, поки пак працює.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import _is_pack


def _cfg(*args: str) -> SimpleNamespace:
    return SimpleNamespace(invocation_params=SimpleNamespace(args=list(args)))


@pytest.mark.parametrize("args", [(), ("-q", "-n", "4"), ("tests",), ("tests/", "-k", "trace")])
def test_a_full_pack_takes_the_lock(args: tuple[str, ...]) -> None:
    assert _is_pack(_cfg(*args))  # type: ignore[arg-type]


@pytest.mark.parametrize("args", [("tests/test_lock.py",), ("tests/test_lock.py::test_x",),
                                  ("tests/a.py", "tests/b.py")])
def test_a_point_run_does_not_wait_for_a_pack(args: tuple[str, ...]) -> None:
    assert not _is_pack(_cfg(*args))  # type: ignore[arg-type]
