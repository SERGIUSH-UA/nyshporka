"""⬆️ Помічник оновлення одним натиском — окремий процес, лише стандартна бібліотека.

Консоль (`update.apply`) копіює цей файл у тимчасову теку й запускає його
базовим інтерпретатором — тим, якого `uv tool install --force` не чіпає, — а
сама завершується. На Windows файл працюючого процесу заблокований, тож
оновлювати середовище, з якого запущено `nysh`, можна лише після виходу з нього.

🔴 Нічого з `nyshporka` тут не імпортується: саме цей пакет зараз замінюється, і
половина старого з половиною нового — гірше за будь-яку відмову.

Кроки: дочекатись, доки сервер (PID) зникне → команда оновлення → (якщо стоїть
рушій) `nysh htr install` → перезапустити консоль тими самими прапорцями →
записати результат у файл, який нова консоль покаже людині. Оновлення впало —
консоль усе одно перезапускається, і людина бачить журнал, а не порожнечу.

    python updater.py <завдання.json>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def _wait_gone(pid: int, timeout: float = 60.0) -> bool:
    """Дочекатись, доки процес зникне. `True` — зник."""
    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not h:
            return True
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000)) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.3)
    return False


def _run(cmd: list[str], env: dict[str, str], log) -> int:  # type: ignore[no-untyped-def]
    log.write(f"\n$ {' '.join(cmd)}\n")
    log.flush()
    try:
        return subprocess.call(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    except OSError as exc:
        log.write(f"не запустилось: {exc}\n")
        return 127


def _relaunch(argv: list[str], cwd: str, env: dict[str, str], log_path: str) -> None:
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(log_path, "a", encoding="utf-8") as out:
        subprocess.Popen(argv, cwd=cwd or None, env=env, stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def main(task_path: str) -> int:
    with open(task_path, encoding="utf-8") as fh:
        task = json.load(fh)
    env = {**os.environ, **{str(k): str(v) for k, v in (task.get("env") or {}).items()}}
    result = {"ok": False, "from": task.get("from", ""), "to": task.get("to", ""),
              "log": task["log"], "started": time.time()}
    with open(task["log"], "w", encoding="utf-8") as log:
        log.write(f"оновлення {result['from']} → {result['to']}\n")
        # Весь ланцюг запуску (обгортка, Python середовища, сервер): поки живий
        # хоч один, його файли заблоковані й оновлення їх не замінить.
        pids = [int(x) for x in (task.get("pids") or [task["pid"]])]
        gone = all(_wait_gone(p, float(task.get("wait", 60))) for p in pids)
        time.sleep(1.0)  # Windows відпускає файли щойно завершених процесів не миттєво
        log.write(f"консоль {'завершилась' if gone else 'не завершилась за відведений час'}\n")
        rc = _run(task["cmd"], env, log) if gone else 1
        result["ok"] = rc == 0
        result["rc"] = rc
        if rc == 0 and task.get("after"):
            for step in task["after"]:
                _run(step, env, log)
        log.write(f"\n{'✅ оновлено' if rc == 0 else '❌ не оновилось'} · перезапуск консолі\n")
    result["finished"] = time.time()
    with open(task["result"], "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    if task.get("relaunch"):
        _relaunch(task["relaunch"], task.get("cwd", ""), env, task["log"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
