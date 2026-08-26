"""🔒 Один писар на робочий простір.

Черги, стан завдань і кеші — файли з атомарною заміною, і вони розраховані на
один процес-писар. Другий застосунок, піднятий на тому самому просторі, затирав
би чергу першого, а з боку користувача це виглядало б як «завдання зникають».

Тому простір береться під замок: хто тримає файл `.lock`, той і пише. Решта —
читачі або клієнти по HTTP.

🔴 Три речі, без яких замок робить гірше, ніж його відсутність:

* **Живучість перевіряється, а не припускається.** Процес міг упасти без
  прибирання, і вічний замок означав би «застосунок більше не запускається»
  після одного аварійного завершення. Тому в файлі лежить PID + час старту, а
  свіжість підтверджується биттям серця.
* **PID-reuse відсікається часом старту.** Через тиждень той самий номер
  дістанеться чужому процесу, і перевірка «чи живий PID» сказала б «так».
* **Чужий замок не знімається силоміць.** Максимум — повідомити, хто тримає й
  на якому порту. Автоматичне «зняти й забрати» одного разу вб'є живий прогін
  на кілька годин.
"""
from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path

LOCK_NAME = ".lock"
#: Як часто писар підтверджує, що живий.
HEARTBEAT_SEC = 10.0
#: Скільки терпіти тишу, перш ніж вважати замок покинутим. Із запасом у 4 удари:
#: заміри на цьому конвеєрі показують паузи до 10 с на важких сторінках.
STALE_SEC = 45.0


class LockBusy(RuntimeError):
    """Простір уже під замком у живого процесу."""

    def __init__(self, holder: LockInfo) -> None:
        where = f" на порту {holder.port}" if holder.port else ""
        super().__init__(
            f"простір уже відкрито іншим процесом (pid {holder.pid} на "
            f"{holder.host}{where}, останній сигнал {holder.age():.0f} с тому). "
            f"Закрийте його або відкрийте інший простір.")
        self.holder = holder


@dataclass(frozen=True)
class LockInfo:
    pid: int
    host: str
    started: float
    heartbeat: float
    port: int | None = None

    def age(self) -> float:
        return max(0.0, time.time() - self.heartbeat)

    def is_stale(self) -> bool:
        return self.age() > STALE_SEC

    def as_dict(self) -> dict[str, object]:
        return {"pid": self.pid, "host": self.host, "started": self.started,
                "heartbeat": self.heartbeat, "port": self.port}


def _process_started() -> float:
    """Час старту цього процесу.

    🔴 Саме процесу, а не момент створення замка. Перша редакція клала сюди
    `time.time()` при створенні `WorkspaceLock`, і звірка з `create_time()`
    розходилась на весь час, що процес прожив до відкриття простору. Наслідок:
    власний живий замок виглядав чужим і мертвим, тобто його можна було вкрасти
    — рівно та відмова, від якої замок і мав захищати.
    """
    try:
        import psutil

        return float(psutil.Process().create_time())
    except Exception:
        return _IMPORT_TIME


#: Фолбек, коли psutil недоступний: момент завантаження модуля. Не точний час
#: старту процесу, але стабільний у межах його життя — а це все, що потрібно
#: для звірки «той самий процес чи ні».
_IMPORT_TIME = time.time()


def _alive_state(pid: int, started: float) -> bool | None:
    """Чи живий той самий процес: True / False / None — «не знаю».

    Без звірки часу старту перевірка ламається через тиждень: PID
    перевикористовується, і чужий процес виглядає як наш власний писар.

    🔴 «Не знаю» — окремий стан, а не «живий». Від нього залежить, чи можна
    забрати замок: живого не чіпаємо ніколи, точно мертвого забираємо одразу,
    а при невідомості лишається єдиний доступний доказ — тиша довша за
    `STALE_SEC`.
    """
    try:
        import psutil
    except ImportError:
        return None                       # без psutil судити нема чим
    try:
        p = psutil.Process(pid)
        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
            return False
        return bool(abs(float(p.create_time()) - started) < 2.0)
    except Exception:
        return False


def _process_alive(pid: int, started: float) -> bool:
    """Сумісний вигляд: «не знаю» трактується як живий (нікого не чіпати)."""
    return _alive_state(pid, started) is not False


def read(root: Path) -> LockInfo | None:
    """Хто тримає простір. None — вільно або файл нечитабельний."""
    path = Path(root) / LOCK_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return LockInfo(pid=int(data["pid"]), host=str(data.get("host") or ""),
                        started=float(data.get("started") or 0.0),
                        heartbeat=float(data.get("heartbeat") or 0.0),
                        port=(int(data["port"]) if data.get("port") else None))
    except (KeyError, TypeError, ValueError):
        return None


class WorkspaceLock:
    """Замок простору. Використовувати як контекст.

    `steal_stale=True` (дефолт) дозволяє забрати покинутий замок — той, чий
    власник мертвий або мовчить довше за `STALE_SEC`. Живий замок не забирається
    ніколи.
    """

    def __init__(self, root: Path, *, port: int | None = None,
                 steal_stale: bool = True) -> None:
        self.root = Path(root)
        self.path = self.root / LOCK_NAME
        self.port = port
        self.steal_stale = steal_stale
        self._started = _process_started()
        self._held = False

    # ── життєвий цикл ────────────────────────────────────────────────────────
    def acquire(self) -> WorkspaceLock:
        # 🔴 Повторний виклик на вже взятому замку — не помилка, а нормальний
        # наслідок природного запису `with WorkspaceLock(...).acquire() as l:`
        # (там `__enter__` кличе `acquire` вдруге). Без цієї гілки процес
        # знаходив власний щойно створений замок і відмовляв сам собі —
        # повідомленням «простір уже зайнято іншим процесом», яке називало
        # чужим його ж pid. Спіймано на першому ж живому запуску демона.
        if self._held:
            return self
        self.root.mkdir(parents=True, exist_ok=True)
        if self._try_create():
            self._held = True
            return self

        holder = read(self.root)
        if holder is None:
            # Файл є, але нечитабельний — обірваний запис попередника.
            if self.steal_stale:
                self._force_write()
                self._held = True
                return self
            raise LockBusy(LockInfo(pid=0, host="?", started=0.0, heartbeat=0.0))

        # 🔴 Було `is_stale() OR не живий` — тобто самої тиші вистачало, щоб
        # забрати замок у живого процесу. А серце в демоні билось рівно один
        # раз, перед `uvicorn.run`, тож будь-який демон старший за 45 секунд
        # віддавав свій простір першому охочому: два писарі на одну чергу — те,
        # що цей модуль оголошує неприпустимим у першому ж абзаці.
        # Тепер: точно мертвий — забираємо одразу; «не знаю» (немає psutil) —
        # лише коли мовчить довше за `STALE_SEC`; живий — ніколи.
        alive = _alive_state(holder.pid, holder.started)
        if self.steal_stale and (alive is False
                                 or (alive is None and holder.is_stale())):
            self._force_write()
            self._held = True
            return self
        raise LockBusy(holder)

    def beat(self) -> None:
        """Підтвердити, що писар живий. Викликати частіше за `STALE_SEC`."""
        if self._held:
            self._force_write()

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            # Знімаємо лише свій замок: за час роботи його міг перехопити інший
            # процес (якщо ми надовго завмерли), і чужий знімати не можна.
            cur = read(self.root)
            if cur and cur.pid == os.getpid():
                self.path.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def held(self) -> bool:
        return self._held

    def __enter__(self) -> WorkspaceLock:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()

    # ── запис ────────────────────────────────────────────────────────────────
    def _payload(self) -> str:
        info = LockInfo(pid=os.getpid(), host=socket.gethostname(),
                        started=self._started, heartbeat=time.time(), port=self.port)
        return json.dumps(info.as_dict(), ensure_ascii=False)

    def _try_create(self) -> bool:
        """Створити замок атомарно. False — вже існує."""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except OSError:
            return False
        try:
            os.write(fd, self._payload().encode("utf-8"))
        finally:
            os.close(fd)
        return True

    def _force_write(self) -> None:
        tmp = self.path.with_suffix(".lock.tmp")
        tmp.write_text(self._payload(), encoding="utf-8")
        os.replace(tmp, self.path)
