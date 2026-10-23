"""⬆️ Оновлення одним натиском: хто має кнопку, план, помічник наскрізь."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from nyshporka import ops as O
from nyshporka.daemon import app as D
from nyshporka.setup import update as U
from nyshporka.setup import updater


@pytest.fixture
def console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Консоль запущена, установка — інструментом uv, вийшла новіша версія."""
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_state_path", lambda: tmp_path / "state" / "state.json")
    monkeypatch.setattr(U, "tool_env", lambda: True)
    monkeypatch.setattr(U, "latest", lambda timeout=3.0: U.Release(installed="0.36.2", latest="0.37.0"))
    monkeypatch.setattr(U, "command", lambda preset="", add=(): ["uv", "tool", "install", "--force", "nyshporka[researcher]"])
    monkeypatch.setattr(D, "LAUNCH", {"argv": [sys.executable, "serve", "--port", "8799"],
                                      "cwd": str(tmp_path), "pid": 4242})
    monkeypatch.setattr(D, "_BUSY", [lambda: 0])
    spawned: list[list[str]] = []
    exits: list[float] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: spawned.append(list(argv)))
    monkeypatch.setattr(D, "request_exit", lambda delay=1.5: exits.append(delay) or True)
    return {"spawned": spawned, "exits": exits, "tmp": tmp_path}


def test_dev_or_pip_install_gets_a_command_not_a_button(console: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(U, "tool_env", lambda: False)
    env = O.call("update.apply", {})
    assert not env.ok and "майстром" in env.error and "uv tool install" in env.error
    assert console["spawned"] == [] and console["exits"] == []


def test_only_from_the_console(console: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "LAUNCH", {})
    env = O.call("update.apply", {})
    assert not env.ok and "nysh update" in env.error


def test_not_while_a_job_runs(console: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "_BUSY", [lambda: 2])
    env = O.call("update.apply", {})
    assert not env.ok and "2" in env.error and console["spawned"] == []


def test_nothing_newer_is_not_an_update(console: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(U, "latest", lambda timeout=3.0: U.Release(installed="0.37.0", latest="0.37.0"))
    env = O.call("update.apply", {})
    assert env.ok and env.data["latest"] is True and console["spawned"] == []


def test_dry_run_names_the_plan_and_reopens_without_a_second_tab(console: dict[str, Any]) -> None:
    env = O.call("update.apply", {"dry_run": True})
    assert env.ok
    plan = env.data["plan"]
    assert plan["cmd"][:3] == ["uv", "tool", "install"] and plan["from"] == "0.36.2" and plan["to"] == "0.37.0"
    assert plan["relaunch"][-4:] == ["serve", "--port", "8799", "--no-browser"]
    assert console["spawned"] == [] and console["exits"] == []


def test_apply_starts_the_helper_and_closes_the_console(console: dict[str, Any]) -> None:
    env = O.call("update.apply", {})
    assert env.ok and env.data["restarting"] is True
    assert console["exits"] == [1.5], "консоль просять завершитись, щоб помічник міг оновити"
    (argv,) = console["spawned"]
    helper, task = Path(argv[1]), Path(argv[2])
    assert helper.name == "updater.py" and helper.read_text(encoding="utf-8") == Path(updater.__file__).read_text(encoding="utf-8")
    t = json.loads(task.read_text(encoding="utf-8"))
    assert t["pid"] == 4242 and t["to"] == "0.37.0" and t["relaunch"][-1] == "--no-browser"


def _helper_task(tmp: Path, cmd: list[str]) -> dict[str, Any]:
    marker = tmp / "relaunched.txt"
    done = subprocess.run([sys.executable, "-c", "pass"], check=True)  # процес, якого вже немає
    assert done.returncode == 0
    return {"pid": 999999, "cmd": cmd, "env": {}, "after": [],
            "relaunch": [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')"],
            "cwd": str(tmp), "from": "0.36.2", "to": "0.37.0", "wait": 5,
            "log": str(tmp / "update.log"), "result": str(tmp / "result.json"), "_marker": str(marker)}


def _run_helper(tmp: Path, task: dict[str, Any]) -> dict[str, Any]:
    tp = tmp / "task.json"
    tp.write_text(json.dumps(task), encoding="utf-8")
    updater.main(str(tp))
    for _ in range(100):
        if Path(task["_marker"]).exists():
            break
        time.sleep(0.05)
    return json.loads(Path(task["result"]).read_text(encoding="utf-8"))


def test_helper_updates_and_reopens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кирилиця в журнал і з консоллю cp1252 (Windows-раннер GitHub): крок не падає
    на кодуванні, і вдале оновлення не записується невдалим."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    res = _run_helper(tmp_path, _helper_task(tmp_path, [sys.executable, "-c", "print('встановлено')"]))
    assert res["ok"] is True and res["to"] == "0.37.0"
    assert "встановлено" in (tmp_path / "update.log").read_text(encoding="utf-8")
    assert (tmp_path / "relaunched.txt").exists(), "консоль перезапущено"


def test_helper_reopens_even_when_the_update_fails(tmp_path: Path) -> None:
    res = _run_helper(tmp_path, _helper_task(tmp_path, [sys.executable, "-c", "raise SystemExit(3)"]))
    assert res["ok"] is False and res["rc"] == 3
    assert (tmp_path / "relaunched.txt").exists(), "оновлення впало — консоль усе одно відкривається"


def test_last_update_reaches_the_screen(console: dict[str, Any]) -> None:
    from nyshporka.setup import notices as N

    home = console["tmp"] / "state" / "update"
    home.mkdir(parents=True)
    (home / "update.log").write_text("помилка мережі\n", encoding="utf-8")
    (home / "result.json").write_text(json.dumps({"ok": False, "to": "0.37.0", "finished": time.time()}),
                                      encoding="utf-8")
    lu = N.snapshot()["last_update"]
    assert lu["ok"] is False and lu["to"] == "0.37.0" and "помилка мережі" in lu["tail"]


def test_relaunch_of_python_m_is_not_the_script_itself() -> None:
    """`python -m nyshporka serve`: argv[0] — `__main__.py`, який сам не стартує."""
    from nyshporka.ops_notices import _relaunch_argv

    got = _relaunch_argv([str(Path(__file__)), "serve"])  # будь-який справжній .py
    assert got[:3] == [sys.executable, "-m", "nyshporka"] and got[-1] == "--no-browser"


def test_helper_records_a_failed_relaunch_and_keeps_logs_apart(tmp_path: Path) -> None:
    task = _helper_task(tmp_path, [sys.executable, "-c", "print('встановлено')"])
    task["relaunch"] = [str(tmp_path / "немає-такого.exe")]
    task["console_log"] = str(tmp_path / "console.log")
    tp = tmp_path / "task.json"
    tp.write_text(json.dumps(task), encoding="utf-8")
    updater.main(str(tp))
    res = json.loads(Path(task["result"]).read_text(encoding="utf-8"))
    assert res["ok"] is True and res.get("relaunch_failed"), "консоль не відкрилась — це записано"
    assert "консоль не відкрилась" in (tmp_path / "update.log").read_text(encoding="utf-8")
    assert not tp.exists(), "завдання не лишається в тимчасовій теці"
