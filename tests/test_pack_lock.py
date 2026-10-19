"""Один повний пак тестів на машину — замок у `conftest._hold_pack_lock`.

Два паки поруч ділили ядра й пам'ять: 19.10.2026 пак на 2,5 хв тягнувся 10 хв,
а воркер xdist падав на вичерпаній пам'яті. Замок бере лише повний пак:
точкові прогони легкі й мусять іти, поки пак працює.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import _hold_pack_lock, _is_pack


def _cfg(*args: str, keyword: str = "", lf: bool = False) -> SimpleNamespace:
    return SimpleNamespace(args=list(args), option=SimpleNamespace(keyword=keyword, lf=lf))


@pytest.mark.parametrize("args", [("tests",), ("tests/sub",), ("tests", "tests/other")])
def test_a_full_pack_takes_the_lock(args: tuple[str, ...]) -> None:
    assert _is_pack(_cfg(*args))  # type: ignore[arg-type]


@pytest.mark.parametrize("cfg", [
    _cfg("tests/test_lock.py"), _cfg("tests/test_lock.py::test_x"),
    _cfg("tests/a.py", "tests/b.py"), _cfg("tests", keyword="trace"), _cfg("tests", lf=True)])
def test_a_point_run_does_not_wait_for_a_pack(cfg: SimpleNamespace) -> None:
    assert not _is_pack(cfg)  # type: ignore[arg-type]


@pytest.fixture
def own_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Свій файл замка: справжній тримає пак, у якому йде цей тест."""
    lock = tmp_path / "pack.lock"
    monkeypatch.setenv("NYSH_PACK_LOCK_FILE", str(lock))
    monkeypatch.delenv("NYSH_PACK_LOCK", raising=False)
    return lock


def test_a_free_machine_takes_the_lock_and_says_whose(own_lock: Path) -> None:
    cfg = _cfg("tests")
    _hold_pack_lock(cfg)  # type: ignore[arg-type]
    try:
        who = json.loads(own_lock.with_suffix(".who.json").read_text(encoding="utf-8"))
        assert who["pid"] > 0
    finally:
        cfg._nysh_pack_lock.close()  # type: ignore[attr-defined]


def test_a_second_pack_waits_then_gives_up_naming_the_holder(
        own_lock: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    from nyshporka.core.xrate import _locked

    monkeypatch.setenv("NYSH_PACK_WAIT", "0.3")
    own_lock.with_suffix(".who.json").write_text(json.dumps(
        {"pid": 4242, "cwd": "інша сесія", "since": "12:00"}), encoding="utf-8")
    with _locked(own_lock, timeout=0), pytest.raises(pytest.exit.Exception) as got:
        _hold_pack_lock(_cfg("tests"))  # type: ignore[arg-type]
    assert "4242" in str(got.value)
    assert "інша сесія" in capsys.readouterr().err


def test_the_switch_and_point_runs_take_no_lock(own_lock: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.core.xrate import _locked

    with _locked(own_lock, timeout=0):
        _hold_pack_lock(_cfg("tests/test_lock.py"))  # type: ignore[arg-type]
        monkeypatch.setenv("NYSH_PACK_LOCK", "0")
        _hold_pack_lock(_cfg("tests"))  # type: ignore[arg-type]
