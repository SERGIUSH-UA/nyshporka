"""Прочитати одну справу: запустити раннер, довести до кінця, порахувати повноту.

Одна функція на всіх, хто читає справу з цього процесу: `nysh read` і черга
справ. Доти тіло жило в команді, і кожен новий викликач мусив би його
переписати — саме так читання в застосунку й у терміналі розійшлись двома
паралельними шляхами.

🔴 Приймач повноти — диск, а не код повернення: при шардингу тиха втрата
сторінок дає rc=0 і порожній перелік збоїв.
"""
from __future__ import annotations

import contextlib
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nyshporka.core.progress import Event, split

#: Як часто питати «чи не просили зупинитись», поки раннер мовчить.
STOP_POLL_SEC = 2.0
#: Скільки чекати на ввічливе завершення, перш ніж убити.
KILL_AFTER_SEC = 5.0

EventFn = Callable[[Event | None, str | None], None]
StopFn = Callable[[], bool]


@dataclass
class Pace:
    """Темп МАШИНИ за цей запуск — те, що можна порівнювати між людьми.

    🔴 Рядок раннера «… с/стор» — це один шард і разом із завантаженням
    моделей. При трьох шардах кожен пише своє, і жодне не є темпом машини, а
    на трьох аркушах зразка завантаження з'їдає половину. Тут — від початку
    першої сторінки до кінця останньої, усіма шардами разом.
    """

    shards: int = 1
    pages: int = 0
    lines: int = 0
    voices: int = 0
    hw: str = ""
    first_start: float = 0.0
    last_end: float = 0.0

    def page(self, ev: Event, now: float) -> None:
        """Одна прочитана сторінка (подія раннера з полем `lines`)."""
        if ev.phase != "htr" or "lines" not in ev.extra:
            return
        sec = float(ev.extra.get("sec") or 0.0)
        if not self.pages:
            self.first_start = now - sec
        self.pages += 1
        self.lines += int(ev.extra.get("lines") or 0)
        self.voices = int(ev.extra.get("voices") or self.voices)
        self.hw = str(ev.extra.get("hw") or self.hw)
        self.last_end = now

    @property
    def sec_per_page(self) -> float:
        return (self.last_end - self.first_start) / self.pages if self.pages else 0.0

    def line(self) -> str:
        if not self.pages:
            return ""
        return (f"темп: {self.sec_per_page:.1f} с/стор · {self.pages} стор · "
                f"{self.lines / self.pages:.0f} рядк/стор · голосів {self.voices or '?'} · "
                f"шардів {self.shards} · {self.hw or 'пристрій невідомий'}")


@dataclass(frozen=True)
class ReadResult:
    """Чим скінчилось читання — з диска, а не з коду повернення."""

    rc: int
    done: int          # сторінок із текстом у теці виходу
    frames: int        # кадрів у плані
    missing: int       # кадрів без тексту; 0 для часткового прогону
    partial: bool      # читали частину навмисно (--limit / --pages / --shard)
    stopped: bool      # зупинено на прохання, а не дочитано
    notes: tuple[str, ...] = ()
    pace: Pace | None = None

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.missing and not self.stopped


def commands(plan: Any, *, case_key: str = "", workers: int = 1, device: str = "",
             limit: int = 0, pages: str = "", shard: str = "", gpu_lock: str = "",
             gpu_sato: bool = True, seg_height: int = 0) -> tuple[list[list[str]], list[str]]:
    """Команди раннера для цього читання і застереження до них.

    Один процес — рівно та команда, яку `nysh read` збирав завжди. Кілька —
    через `Plan.shards`: шард, спільний лок і зняте з карти sato там
    народжуються разом.
    """
    if workers > 1 and not shard:
        cmds, notes = plan.shards(workers, device=device, case_key=case_key,
                                  limit=limit, pages=pages, seg_height=seg_height)
        return cmds, notes
    cmd = plan.command(case_key=case_key, limit=limit, pages=pages, shard=shard,
                       gpu_lock=gpu_lock or str(plan.gpu_lock or ""),
                       gpu_sato=gpu_sato, seg_height=seg_height)
    return [cmd], []


def read_case(plan: Any, *, case_key: str = "", workers: int = 1, device: str = "",
              limit: int = 0, pages: str = "", shard: str = "", gpu_lock: str = "",
              gpu_sato: bool = True, seg_height: int = 0,
              on_event: EventFn | None = None,
              should_stop: StopFn | None = None) -> ReadResult:
    """Запустити раннер(и) по справі й дочекатись кінця.

    `on_event(подія, рядок)` дістає кожен рядок виводу: подію прогресу або
    людський текст. `should_stop()` питається раз на `STOP_POLL_SEC`; сказав
    «так» — діти гасяться, а прочитане лишається на диску, і наступний запуск
    у ту саму теку його пропустить.
    """
    from nyshporka.htr import runs as R
    from nyshporka.htr.run import count_frames

    cmds, notes = commands(plan, case_key=case_key, workers=workers, device=device,
                           limit=limit, pages=pages, shard=shard, gpu_lock=gpu_lock,
                           gpu_sato=gpu_sato, seg_height=seg_height)
    plan.out_dir.mkdir(parents=True, exist_ok=True)

    # Кілька процесів ділять ядра: без цього кожен бере під BLAS усі.
    from nyshporka.htr.env import foreign_env
    from nyshporka.htr.run import shard_env

    env = foreign_env(shard_env(len(cmds)) if len(cmds) > 1 else None)
    lines: queue.Queue[str | None] = queue.Queue()
    procs: list[Any] = []
    pace = Pace(shards=len(cmds))
    stopped = False
    try:
        for k, cmd in enumerate(cmds):
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1,
                                    env=env)
            procs.append(proc)
            # ⚠ Реєструємо ДОЧІРНІЙ pid, а не свій: помирає першим саме він, і
            # по ньому ж видно, чи робота ще йде.
            R.register(proc.pid, case=plan.case_dir.name, case_key=case_key,
                       shard=shard or (f"{k + 1}/{len(cmds)}" if len(cmds) > 1 else ""))
            threading.Thread(target=_pump, args=(proc, lines), daemon=True).start()

        live = len(procs)
        while live:
            try:
                line = lines.get(timeout=STOP_POLL_SEC)
            except queue.Empty:
                line = ""
            if line is None:
                live -= 1
            elif line:
                ev, human = split(line)
                if ev is not None:
                    pace.page(ev, time.monotonic())
                if on_event is not None:
                    on_event(ev, human)
            if not stopped and should_stop is not None and should_stop():
                stopped = True
                for proc in procs:
                    _terminate(proc)
        rc = max((int(p.wait() or 0) for p in procs), default=0)
    finally:
        # Знімається і при Ctrl+C: інакше справа лишалась би «зайнятою» до
        # перевірки живості.
        for proc in procs:
            R.drop(proc.pid)

    done = len(list(plan.out_dir.glob("*.txt")))
    # 🔴 «Усі кадри мають текст» дійсне лише для повного прогону. Частковий
    # прочитав менше навмисно, і рахувати різницю як утрату означало б лякати
    # червоним там, де все гаразд.
    partial = bool(limit or pages or shard)
    missing = 0 if partial else max(0, count_frames(plan.case_dir) - done)
    return ReadResult(rc=rc, done=done, frames=int(plan.frames), missing=missing,
                      partial=partial, stopped=stopped, notes=tuple(notes), pace=pace)


def _pump(proc: Any, lines: queue.Queue[str | None]) -> None:
    """Рядки одного процесу — у спільну чергу; `None` означає «цей скінчив»."""
    try:
        for line in proc.stdout:
            lines.put(line.rstrip())
    finally:
        lines.put(None)


def _terminate(proc: Any) -> None:
    """Погасити раннер разом із його дітьми. Прочитані сторінки вже на диску."""
    if proc.poll() is not None:
        return
    kill_tree(int(proc.pid))
    try:
        proc.wait(timeout=KILL_AFTER_SEC)
    except subprocess.TimeoutExpired:
        proc.kill()


def kill_tree(pid: int, grace: float = KILL_AFTER_SEC) -> None:
    """Погасити процес і ВСІХ його нащадків: попросити, зачекати, вбити.

    🔴 Раннер читає не сам: його наглядач (`--supervise`) запускає робочий
    процес, а той тримає карту й пише в той самий канал виводу. `terminate()`
    гасив лише наглядача — робочий читав далі, канал не закривався, і
    «зупинити зараз» дочитувало справу до кінця (знайдено живим прогоном
    черги 30.09.2026: після зупинки прочитано ще 23 сторінки).
    """
    import os

    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            root = psutil.Process(pid)
            family = [*root.children(recursive=True), root]
        except psutil.Error:
            return
        for p in family:
            with contextlib.suppress(psutil.Error):
                p.terminate()
        _gone, alive = psutil.wait_procs(family, timeout=grace)
        for p in alive:
            with contextlib.suppress(psutil.Error):
                p.kill()
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, check=False)
        return
    with contextlib.suppress(OSError):
        os.kill(pid, 9)
