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

import contextlib
import json
import os
import subprocess
import sys
import time


def _wait_gone(pid: int, timeout: float = 60.0) -> bool:
    """Дочекатись, доки процес зникне. `True` — зник."""
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not h:
            return True
        try:
            return bool(ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000)) == 0)
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


def _relaunch(argv: list[str], cwd: str, env: dict[str, str], out_path: str) -> str:
    """Відкрити консоль знову; повертає причину, якщо не вдалося (інакше «»).

    Вивід нової консолі — в окремий файл, а не в журнал оновлення: інакше
    «чому не оновилось» тонуло б під банером і попередженнями сервера.
    """
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        with open(out_path, "a", encoding="utf-8") as out:
            subprocess.Popen(argv, cwd=cwd or None, env=env, stdout=out, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def main(task_path: str) -> int:
    with open(task_path, encoding="utf-8") as fh:
        task = json.load(fh)
    env = {**os.environ, **{str(k): str(v) for k, v in (task.get("env") or {}).items()}}
    # Журнал — UTF-8, і Python-кроки (`nysh htr install`) пишуть у нього так само:
    # з кодуванням консолі cp1252 кирилиця падала UnicodeEncodeError, і вдале
    # оновлення записувалось невдалим (Windows-раннер GitHub, 23.10.2026).
    env["PYTHONIOENCODING"] = "utf-8"
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
                if _run(step, env, log) != 0:
                    result["after_failed"] = " ".join(step)
        log.write(f"\n{'✅ оновлено' if rc == 0 else '❌ не оновилось'} · перезапуск консолі\n")
    if task.get("relaunch"):
        why = _relaunch(task["relaunch"], task.get("cwd", ""), env,
                        task.get("console_log") or task["log"])
        if why:
            result["relaunch_failed"] = why
            with open(task["log"], "a", encoding="utf-8") as log:
                log.write(f"консоль не відкрилась: {why} — відкрийте Нишпорку ярликом\n")
    result["finished"] = time.time()
    with open(task["result"], "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    # Завдання (argv, теки) не лишається в тимчасовій теці назавжди.
    with contextlib.suppress(OSError):
        os.remove(task_path)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
