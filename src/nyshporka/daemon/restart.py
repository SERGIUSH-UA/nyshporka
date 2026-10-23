"""🔁 Зробити щось, поки консоль закрита, і відкрити її знову.

Дві дії консолі не можна виконати, поки вона жива:

* оновлення (`update.apply`) — на Windows файли середовища, з якого запущено
  `nysh`, заблоковані, поки працює процес;
* перенос роду в проєкт (`project.adopt_restart`) — `adopt.apply` навмисно
  відмовляє, поки Майстерню тримає застосунок: переносити теки з-під живого
  сервера означало б, що він допише файл туди, звідки той уже поїхав.

Тож консоль кладе завдання у файл, запускає окремий процес-помічник
(`setup/updater.py`, лише стандартна бібліотека) і завершується. Помічник
чекає, доки весь ланцюг запуску зникне, виконує команду й відкриває консоль
тими самими прапорцями. Результат лягає у файл, який нова консоль покаже.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def relaunch_argv(argv: list[str]) -> list[str]:
    """Той самий `nysh serve` з тими самими прапорцями — і без другої вкладки."""
    rest = list(argv[1:]) or ["serve"]
    if "serve" in rest and "--no-browser" not in rest:
        rest.append("--no-browser")
    return launcher(argv) + rest


def launcher(argv: list[str]) -> list[str]:
    """Чим запускати `nysh` цієї установки: той самий файл, що й консоль.

    `python -m nyshporka serve`: argv[0] — `__main__.py`, сам він не стартує.
    """
    head = argv[0] if argv else ""
    if head.lower().endswith(".py"):
        return [sys.executable, "-m", "nyshporka"]
    if head and Path(head).is_file():
        return [head]
    if head and Path(head + ".exe").is_file():
        return [head + ".exe"]
    if shutil.which("nysh"):
        return [str(shutil.which("nysh"))]
    return [sys.executable, "-m", "nyshporka"]


def launch_chain(pid: int, argv0: str) -> list[int]:
    """Сервер і предки, що належать цій установці: обгортка `nysh.exe`, Python середовища.

    🔴 На Windows `nysh.exe` від uv запускає Python середовища, а той — базовий
    Python, який і слухає порт. Поки живі обгортка й Python середовища, їхні файли
    заблоковані, і `uv tool install --force` їх не замінить. Тож помічник чекає
    весь ланцюг, а не лише процес сервера.
    """
    out = [pid]
    try:
        import psutil
    except ImportError:
        return out
    roots = [Path(sys.prefix).resolve()]
    if argv0:
        roots.append(Path(argv0).resolve().parent)

    def ours(p: psutil.Process) -> bool:
        with contextlib.suppress(Exception):
            parts = [p.exe(), *p.cmdline()[:2]]
            for x in parts:
                rx = Path(x).resolve()
                if any(rx == r or r in rx.parents for r in roots):
                    return True
        return False

    with contextlib.suppress(Exception):
        cur = psutil.Process(pid).parent()
        while cur is not None and ours(cur) and len(out) < 6:
            out.append(cur.pid)
            cur = cur.parent()
    return out


def task_for(cmd: list[str], home: Path, *, cwd: str = "", title: str = "",
             env: dict[str, str] | None = None, after: list[list[str]] | None = None,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Завдання помічникові для цієї консолі: що виконати, кого чекати, як відкрити знову.

    `home` — тека журналу й результату дії (`update`, `adopt`): нова консоль
    читає звідти, чим скінчилось.
    """
    from nyshporka.daemon import app as D

    argv = list(D.LAUNCH.get("argv") or [])
    pid = int(D.LAUNCH.get("pid") or 0)
    home.mkdir(parents=True, exist_ok=True)
    return {"pid": pid, "pids": launch_chain(pid, argv[0] if argv else ""),
            "cmd": cmd, "cmd_cwd": cwd, "title": title, "env": env or {},
            "after": after or [], "relaunch": relaunch_argv(argv),
            "cwd": D.LAUNCH.get("cwd") or "", "wait": 90,
            "log": str(home / f"{home.name}.log"), "result": str(home / "result.json"),
            "console_log": str(home / "console.log"), **(extra or {})}


def run_after_exit(task: dict[str, Any]) -> None:
    """Запустити помічника з завданням і попросити консоль завершитись."""
    from nyshporka.daemon import app as D

    tmp = Path(tempfile.mkdtemp(prefix="nysh-restart-"))
    helper = tmp / "updater.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "setup" / "updater.py", helper)
    task_path = tmp / "task.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    with contextlib.suppress(OSError):
        Path(task["result"]).unlink()
    base_py = getattr(sys, "_base_executable", "") or sys.executable
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED | NEW_GROUP
    subprocess.Popen([base_py, str(helper), str(task_path)], cwd=str(tmp), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=sys.platform != "win32")
    D.request_exit(1.5)


def last_result(home: Path) -> dict[str, Any] | None:
    """Чим скінчилась остання така дія: результат помічника і хвіст журналу."""
    res = home / "result.json"
    if not res.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(res.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    log = Path(str(data.get("log") or home / f"{home.name}.log"))
    with contextlib.suppress(OSError):
        data["tail"] = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
    return data
