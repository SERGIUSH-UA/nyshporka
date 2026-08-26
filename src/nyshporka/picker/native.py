"""🪟 Системне вікно вибору: питаємо ОС, а не браузер.

Браузер абсолютного шляху не віддасть — і не віддасть ніколи, це його межа, не
наша. Але діалог тут відкриває не браузер, а сам застосунок на машині людини,
тож питання «а чи можна взагалі» відповіді не потребує: можна.

🔴 Чого цей модуль не обіцяє: що людина побачить вікно. Демон слухає петлю, але
петля не доводить, що браузер на цій же машині — тунель дає рівно ту саму
картину. Тому `ask()` чесно розрізняє «людина скасувала», «вікно не відкрилось»,
«ніхто не відповів» і «Tk упав»: кожен із цих випадків лікується по-різному, і
звести їх у порожню відповідь означало б віддати нуль без знаменника.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from nyshporka.picker._dialog import SENTINEL

Mode = Literal["dir", "file", "files", "save"]
State = Literal["picked", "cancelled", "timeout", "unavailable", "error"]

#: Скільки чекаємо на людину, поки не вважаємо вікно загубленим. П'ять хвилин —
#: не про швидкість вибору, а про те, що далі вікно вже напевно висить забуте
#: (найчастіше — позаду браузера), і тримати процес немає сенсу.
DEFAULT_TIMEOUT_S = 300.0

#: Як адресуємо дитину. модулем, а не шляхом до файлу: у колесі шлях може не
#: існувати взагалі, і збій вилазив би лише в користувача.
CHILD = ("-m", "nyshporka.picker._dialog")

#: Аварійний вимикач. Потрібен двом: тому, у кого Tk вішає систему, і приймачу —
#: інакше тест перевіряв би машину розробника, а не програму.
KILL_SWITCH = "NYSHPORKA_NO_NATIVE_PICKER"

#: Відкриті зараз вікна: слот → процес. Слот — це поле, яке питає («read.case_dir»).
_LIVE: dict[str, subprocess.Popen[bytes]] = {}
#: Доступ іде з кількох потоків (кожна довга робота крутиться у своєму), і
#: забути це легко: словник не зламається гучно, він просто загубить процес,
#: якого потім нікому буде вбити.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class FileType:
    """Рядок фільтра діалогу: «Ваги рушія» — `*.mlmodel`, `*.pt`."""

    label: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Ability:
    """Чи вміє ця машина показати системне вікно — і чому ні."""

    can: bool
    #: Чому ні — готовим текстом людині, а не кодом помилки.
    why: str = ""
    #: Що з цим зробити. Порожньо — робити нічого, середовище таке.
    fix: str = ""
    display: str = ""


@dataclass(frozen=True)
class Choice:
    """Що відповіла людина — і чи вона взагалі відповідала."""

    state: State
    paths: tuple[str, ...] = field(default=())
    why: str = ""
    took_s: float = 0.0

    @property
    def path(self) -> str:
        """Перший шлях — для режимів `dir`, `file`, `save`."""
        return self.paths[0] if self.paths else ""

    @property
    def ok(self) -> bool:
        return self.state == "picked" and bool(self.paths)


# ── чи вміємо ────────────────────────────────────────────────────────────────
def probe(*, deep: bool = False, python: str | None = None) -> Ability:
    """Чи можна тут показати вікно. Дешево — без запуску процесів.

    🔴 Питається заздалегідь, до того, як людина побачить кнопку. Кнопка, яка
    не працює, — це та сама обіцянка без входу, що й дія без екрана: вона
    читається як несправність застосунку, а не як межа середовища.
    """
    if os.environ.get(KILL_SWITCH):
        return Ability(can=False, why="системне вікно вимкнено налаштуванням машини",
                       display="off")

    import importlib.util

    if importlib.util.find_spec("tkinter") is None:
        return Ability(
            can=False,
            why="цей Python зібрано без tkinter, а системне вікно показує саме він",
            fix="переставте застосунок інсталятором — він приносить власний "
                "інтерпретатор; на Linux бракує пакета python3-tk",
            display="none")

    if sys.platform == "win32":
        if _session_zero():
            return Ability(can=False, display="win32",
                           why="застосунок працює службою, а служби не можуть "
                               "показувати вікна — вибирайте теку тут")
        display = "win32"
    elif sys.platform == "darwin":
        display = "aqua"
    else:
        wayland, x11 = os.environ.get("WAYLAND_DISPLAY"), os.environ.get("DISPLAY")
        if not wayland and not x11:
            return Ability(
                can=False, display="none",
                why="сесії з екраном тут немає (ні DISPLAY, ні WAYLAND_DISPLAY) — "
                    "так виглядає запуск по ssh, у контейнері або службою")
        display = "wayland" if wayland else "x11"

    if not deep:
        return Ability(can=True, display=display)

    # Глибока перевірка ловить те, чого не бачить жодна дешева: пакет `tkinter`
    # на місці, а бібліотеки Tk у системі немає. Дізнатись про це в мить, коли
    # людина вже натиснула кнопку, — найгірший момент.
    got = _run({"mode": "probe"}, timeout_s=20.0, python=python, slot="")
    if got.get("state") == "ready":
        return Ability(can=True, display=display)
    return Ability(can=False, display=display,
                   why=str(got.get("error") or "вікно не створюється"),
                   fix="на Linux бракує пакета python3-tk")


def _session_zero() -> bool:
    """Чи це сесія служб. Вікна з неї не видно нікому від часів Vista."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        sid = ctypes.c_ulong()
        if not k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid)):
            return False
        return sid.value == 0
    except Exception:
        return False


# ── питаємо ──────────────────────────────────────────────────────────────────
def ask(mode: Mode = "dir", *,
        title: str = "",
        start: str | Path | None = None,
        types: Sequence[FileType] = (),
        name: str = "",
        slot: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        python: str | None = None) -> Choice:
    """Показати системне вікно й дочекатись відповіді.

    `slot` — чиє це вікно («read.case_dir»). Новий запит у зайнятому слоті
    прибирає попереднє вікно: інакше друге натискання кнопки лишало б два
    діалоги, які змагаються за «поверх усіх», і другий ховав би перший — гірше,
    ніж не відкрити жодного.
    """
    able = probe(python=python)
    if not able.can:
        return Choice(state="unavailable", why=able.why)

    if slot:
        close(slot)

    req: dict[str, object] = {
        "mode": mode, "title": title, "start": _start_dir(start), "name": name,
        "types": [{"label": t.label, "patterns": list(t.patterns)} for t in types]}
    t0 = time.monotonic()
    got = _run(req, timeout_s=timeout_s, python=python, slot=slot)
    took = time.monotonic() - t0

    state = str(got.get("state") or "error")
    raw = got.get("paths")
    paths = tuple(str(p) for p in raw) if isinstance(raw, list) else ()
    if state == "picked" and paths:
        return Choice(state="picked", paths=paths, took_s=took)
    if state == "cancelled":
        return Choice(state="cancelled", took_s=took)
    if state == "timeout":
        return Choice(state="timeout", took_s=took,
                      why="ніхто не закрив системне вікно — найчастіше це означає, "
                          "що воно відкрилось позаду вікна браузера")
    return Choice(state="error", took_s=took,
                  why=str(got.get("error") or "вікно не відповіло"))


def close(slot: str) -> bool:
    """Прибрати вікно цього слота. `True` — було що прибирати.

    Єдиний спосіб закрити системний діалог ззовні — прибити процес, якому він
    належить. Тому вбивство тут не грубість, а сам механізм.
    """
    with _LOCK:
        proc = _LIVE.pop(slot, None)
    if proc is None:
        return False
    _terminate(proc)
    return True


def live() -> tuple[str, ...]:
    """Слоти, у яких зараз відкрито вікно."""
    with _LOCK:
        return tuple(_LIVE)


# ── нутрощі ──────────────────────────────────────────────────────────────────
def _start_dir(start: str | Path | None) -> str:
    """Звідки відкривати. Неіснуючий шлях підіймається до живого предка.

    Інакше Tk на Windows мовчки відкриє «Документи», і людина вирішить, що
    параметр не діє.
    """
    if not start:
        return ""
    p = Path(os.path.abspath(Path(str(start)).expanduser()))
    if p.is_file():
        p = p.parent
    for _ in range(64):
        if p.is_dir() or p.parent == p:
            return str(p)
        p = p.parent
    return ""


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    # 🔴 Кодування задається явно. На Windows дефолт — cp1251, і заголовок
    # «Оберіть теку ф.230 оп.1» чи шлях із кирилицею повертався б покаліченим.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(req: dict[str, object], *, timeout_s: float, python: str | None,
         slot: str) -> dict[str, object]:
    exe = python or sys.executable
    flags = 0
    if sys.platform == "win32":
        # Без цього при кожному натисканні кнопки блимає чорне вікно консолі.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [exe, *CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_child_env(), creationflags=flags)
    except OSError as exc:
        return {"state": "error", "error": f"вікно не запустилось: {exc}"}

    if slot:
        with _LOCK:
            _LIVE[slot] = proc

    payload = json.dumps(req, ensure_ascii=False).encode("utf-8")
    try:
        out, err = proc.communicate(input=payload, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        return {"state": "timeout"}
    finally:
        if slot:
            with _LOCK:
                if _LIVE.get(slot) is proc:
                    del _LIVE[slot]

    text = out.decode("utf-8", "replace")
    parsed = _parse(text)
    if parsed is not None:
        return parsed
    # Відповіді немає — значить дитина померла або не дійшла до неї. Хвіст
    # `stderr` іде в причину: без нього людині лишається «нічого не сталось».
    tail = err.decode("utf-8", "replace").strip().splitlines()
    why = tail[-1] if tail else f"вікно завершилось без відповіді (код {proc.returncode})"
    return {"state": "error", "error": why}


def _parse(text: str) -> dict[str, object] | None:
    """Наш рядок із виводу дитини.

    Береться останній рядок із міткою: Tk і Gtk на Linux пишуть попередження
    просто в потік, і без мітки батько розбирав би саме їх.
    """
    found: dict[str, object] | None = None
    for line in text.splitlines():
        if not line.startswith(SENTINEL):
            continue
        try:
            got = json.loads(line[len(SENTINEL):])
        except ValueError:
            continue
        if isinstance(got, dict):
            found = got
    return found


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Ввічливо, потім силою — дзеркало того, як гасяться прогони рушія."""
    try:
        proc.terminate()
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError, ProcessLookupError):
            proc.kill()


__all__ = ["CHILD", "DEFAULT_TIMEOUT_S", "KILL_SWITCH", "Ability", "Choice",
           "FileType", "Mode", "State", "ask", "close", "live", "probe"]
