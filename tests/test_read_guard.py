"""🚦 `nysh read` мусить стати в чергу, а не піти паралельно.

Скарга користувача (29.08.2026): «запустив дві справи — вони почались
паралельно, а не стали чергою». У застосунку черга з'явилась тоді ж, у
командному рядку — ні, а саме він несе довгу роботу.

🔴 Перевіряється тут не лок карти, а СТАРТ. Лок серіалізує лише фазу
сегментації; обидва прогони до нього доходять уже запущеними, і кожен встигає
поміряти вільну VRAM як свою — тобто взяти під себе стільки шардів, скільки
помістилось би одному.

⚠ План і сам запуск підмінені: справжній прогін потребує окремого середовища
рушіїв (~2.5 ГБ) і годин роботи. Перевіряється рівно те, що вирішує ця правка, —
дійшло до `Popen` чи ні.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nyshporka.cli import app
from nyshporka.core import workspace as W

runner = CliRunner()


class _Plan:
    """Стільки плану, скільки читає команда між перевіркою і запуском."""

    def __init__(self, case: Path, out: Path) -> None:
        self.case_dir = case
        self.out_dir = out
        self.frames = 2
        self.script = "cyrillic"
        self.model = Path("pysar_cyr_v17.pt")
        self.voice = None
        self.voices = ()
        self.gpu_lock = out.parent / "gpu.lock"
        # звичайний прогін кешу не шукає — команда мовчить про сегментацію
        self.seg_why = ""
        self.seg_ready = False

    def command(self, **_: Any) -> list[str]:
        return ["python", "-c", "pass"]


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n",
                                             encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setenv("GPURUNNER_DATA_DIR", str(tmp_path / "gpurunner"))

    case = tmp_path / "skany_a"
    case.mkdir()
    out = tmp_path / "reports" / "htr" / "skany_a"

    from nyshporka.htr import run as HR

    monkeypatch.setattr(HR, "plan", lambda d, **_: _Plan(Path(d).resolve(), out))
    yield tmp_path
    W.reset()


def _cloud_case(space: Path, *, phase: str = "running", verdict=None,
                status: str = "running", done: int = 1, total: int = 2) -> None:
    folder = space / "gpurunner" / "htr"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "htr-cloud.json").write_text(json.dumps({
        "session": "htr-cloud", "phase": phase, "verdict": verdict,
        "updated": "2026-10-09T09:02:29+00:00",
        "cases": [{"case_key": "DAHO/31/141/139", "status": status,
                   "pages_done": done, "n_pages_expected": total,
                   "detail": "чекає забору"}],
    }), encoding="utf-8")


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch):
    """Лічильник справжніх запусків: саме його й стереже ця правка."""
    import subprocess

    seen: list[list[str]] = []

    class _Proc:
        pid = os.getpid()
        stdout = iter(())

        def wait(self) -> int:
            return 0

    def fake(cmd, *a, **kw):
        seen.append(cmd)
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", fake)
    return seen


def test_a_foreign_live_run_stops_the_start(space, started) -> None:
    """🔴 Заради чого все: друга справа не стартує, поки йде перша."""
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="skany_b", case_key="ДАХмО 315-1-77")
    res = runner.invoke(app, ["read", str(space / "skany_a")])
    assert res.exit_code == 1
    assert not started, "прогін пішов попри живу чужу справу"


def test_the_refusal_names_what_is_busy(space, started) -> None:
    """Відмова мусить називати справу, а не просто «зайнято».

    ⚠ Без імені людині лишається гадати, що саме тримає карту, — і найпростіший
    вихід із такої відмови це `--force`, тобто рівно та поведінка, проти якої
    вона стоїть.
    """
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="skany_b", case_key="ДАХмО 315-1-77")
    res = runner.invoke(app, ["read", str(space / "skany_a")])
    assert "ДАХмО 315-1-77" in res.output
    assert "--force" in res.output


def test_force_still_starts(space, started) -> None:
    """Гард — запобіжник, а не заборона: людина може знати краще."""
    from nyshporka.htr import runs as R

    R.register(os.getpid(), case="skany_b")
    res = runner.invoke(app, ["read", str(space / "skany_a"), "--force"])
    assert res.exit_code == 0, res.output
    assert started


def test_a_shard_of_the_same_case_is_not_blocked(space, started) -> None:
    """🔴 Інакше правка вбила б шардинг — те, чим прогін і прискорюють."""
    from nyshporka.htr import runs as R

    R.register(12345678, case="skany_a", shard="1/3", created=0.0)
    res = runner.invoke(app, ["read", str(space / "skany_a"), "--shard", "2/3"])
    assert res.exit_code == 0, res.output
    assert started


def test_a_free_card_starts_at_once(space, started) -> None:
    res = runner.invoke(app, ["read", str(space / "skany_a")])
    assert res.exit_code == 0, res.output
    assert started


def test_an_active_cloud_case_stops_the_local_start(space, started,
                                                    monkeypatch) -> None:
    """🔴 Локальний реєстр порожній, але ця справа вже на орендованій машині."""
    from nyshporka.cases import resolve

    monkeypatch.setattr(resolve, "_from_path", lambda *_: "DAHO/31/141/139")
    _cloud_case(space, done=1788, total=1788)

    res = runner.invoke(app, ["read", str(space / "skany_a")])

    assert res.exit_code == 1
    assert "вже активна" in res.output and "1788/1788" in res.output
    assert not started, "локальний дубль пішов поверх живого наглядача"


def test_a_finished_cloud_case_requires_explicit_rerun(space, started,
                                                       monkeypatch) -> None:
    """Повний результат ще може чекати забору, хоча сесія вже завершилась."""
    from nyshporka.cases import resolve

    monkeypatch.setattr(resolve, "_from_path", lambda *_: "DAHO/31/141/139")
    _cloud_case(space, phase="finished", verdict="ok", status="done",
                done=1788, total=1788)

    refused = runner.invoke(app, ["read", str(space / "skany_a")])
    assert refused.exit_code == 1 and "вже прочитана" in refused.output
    assert not started

    allowed = runner.invoke(app, ["read", str(space / "skany_a"), "--rerun"])
    assert allowed.exit_code == 0, allowed.output
    assert started


def test_dry_run_may_inspect_an_active_cloud_case(space, started,
                                                  monkeypatch) -> None:
    from nyshporka.cases import resolve

    monkeypatch.setattr(resolve, "_from_path", lambda *_: "DAHO/31/141/139")
    _cloud_case(space)

    res = runner.invoke(app, ["read", str(space / "skany_a"), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert not started


def test_the_run_is_dropped_from_the_registry_after_it_ends(space,
                                                            started) -> None:
    """🔴 Інакше одна справа блокувала б наступну до перевірки живості."""
    from nyshporka.htr import runs as R

    runner.invoke(app, ["read", str(space / "skany_a")])
    assert R.alive() == []


def test_dry_run_never_registers(space, started) -> None:
    """`--dry-run` нічого не запускає, тож і карту не займає."""
    from nyshporka.htr import runs as R

    res = runner.invoke(app, ["read", str(space / "skany_a"), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert not started
    assert R.alive() == []
