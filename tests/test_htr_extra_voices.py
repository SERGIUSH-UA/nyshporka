"""Третій голос тим самим проходом (`--with latin`).

Мішане письмо доти вимагало двох прогонів: Писар+Дяк, а потім окремо Скриба
на тій самій сегментації. Раннер уміє N голосів з першого дня, обмеження жило
в обгортці — `Plan.voice` був одним полем.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _plan(tmp_path: Path, **kw):
    from nyshporka.htr.run import Plan

    return Plan(case_dir=tmp_path / "справа", out_dir=tmp_path / "out",
                model=tmp_path / "pysar_cyr_v17.pt", script="cyrillic", frames=10,
                python=tmp_path / "py.exe", runner=tmp_path / "runner.py", **kw)


def test_all_voices_reach_the_runner_in_one_models_flag(tmp_path: Path) -> None:
    diak, skryba = tmp_path / "diak_cyr_v4.mlmodel", tmp_path / "skryba_f792_v6.mlmodel"
    cmd = _plan(tmp_path, voice=diak, extra_voices=(skryba,)).command()
    assert cmd.count("--models") == 1
    assert cmd[cmd.index("--models") + 1] == f"{diak},{skryba}"


def test_extra_voice_without_second_voice_still_goes(tmp_path: Path) -> None:
    """`--one-voice --with latin` — Писар і Скриба, без Дяка."""
    skryba = tmp_path / "skryba_f792_v6.mlmodel"
    cmd = _plan(tmp_path, extra_voices=(skryba,)).command()
    assert cmd[cmd.index("--models") + 1] == str(skryba)


def test_no_voices_no_flag(tmp_path: Path) -> None:
    assert "--models" not in _plan(tmp_path).command()


def test_extra_voice_on_kraken_main_is_refused(tmp_path: Path) -> None:
    """Ансамбль у раннері — лише в PARSeq-гілці; за kraken-основою `--models`
    ігнорується з рядком у лозі, і людина чекала б теку, якої не буде."""
    from nyshporka.htr.run import ReadError, resolve_voices

    with pytest.raises(ReadError, match="PARSeq"):
        resolve_voices(["latin"], main=tmp_path / "skryba_f792_v6.mlmodel")


def test_voice_equal_to_main_or_taken_is_skipped(tmp_path: Path, monkeypatch) -> None:
    from nyshporka.htr import run as R

    main = tmp_path / "pysar_cyr_v17.pt"
    diak = tmp_path / "diak_cyr_v4.mlmodel"
    skryba = tmp_path / "skryba_f792_v6.mlmodel"
    names = {"cyrillic": main, "diak_cyr_v4.mlmodel": diak, "latin": skryba}
    monkeypatch.setattr(R, "pick_model", lambda s, **_: (names[s], None))
    monkeypatch.setattr(R, "resolve_model", lambda s: (names[s], "cyrillic"))
    got = R.resolve_voices(["cyrillic", "diak_cyr_v4.mlmodel", "latin", "latin"],
                           main=main, have=[diak])
    assert got == (skryba,)


def test_cloud_commands_carry_extra_voices() -> None:
    from nyshporka.cloud.run import remote_commands

    shards, _ = remote_commands(
        remote_dir="/opt/run", python="/opt/venv/bin/python",
        model="/opt/run/models/pysar_cyr_v17.pt",
        voice="/opt/run/models/diak_cyr_v4.mlmodel",
        extra_voices=["/opt/run/models/skryba_f792_v6.mlmodel"],
        script="cyrillic", case_key="X/1/2", workers=1, device="cuda:0")
    cmd = shards[0].cmd
    assert cmd[cmd.index("--models") + 1] == (
        "/opt/run/models/diak_cyr_v4.mlmodel,/opt/run/models/skryba_f792_v6.mlmodel")


class _Caught(Exception):
    pass


def _catch_plan(monkeypatch, seen: dict):
    from nyshporka.htr import run as R

    def fake(case_dir, **kw):
        seen.update(kw)
        raise _Caught

    monkeypatch.setattr(R, "plan", fake)


def test_read_plan_op_passes_voices_and_model(monkeypatch) -> None:
    """Застосунок і агент ходять через операцію: без цього `--with` був лише
    в командному рядку, а поле моделі у формі взагалі ніде не діяло."""
    from nyshporka.ops_builtin import ReadArgs, read_plan

    seen: dict = {}
    _catch_plan(monkeypatch, seen)
    with pytest.raises(_Caught):
        read_plan(ReadArgs(case_dir="x", also=["latin"], model="m.pt"))
    assert seen["also"] == ["latin"] and seen["model"] == "m.pt"


def test_queued_reading_passes_voices_and_model(monkeypatch) -> None:
    import asyncio

    from nyshporka.daemon import workers as W

    seen: dict = {}
    _catch_plan(monkeypatch, seen)
    with pytest.raises(_Caught):
        asyncio.run(W._start_read(None, None, {"case_dir": "x", "also": ["latin", " "],
                                               "model": "m.pt"}))
    assert seen["also"] == ["latin"] and seen["model"] == "m.pt"
