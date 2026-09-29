"""🚦 Реєстр живих прогонів: хто саме зараз тримає карту.

🔴 Навіщо він, коли є лок карти. Лок (`derived/htr_lock/gpu.lock`) серіалізує
**фазу сегментації** — секунди на сторінку. Він рятує від падіння, але не від
того, на що скаржаться: два `nysh read` у сусідніх терміналах СТАРТУЮТЬ разом,
обидва міряють вільну VRAM як свою й обидва беруть під себе стільки шардів,
скільки помістилось би одному. Далі вони цілу ніч штовхаються, і людина бачить
рівно те, про що написала: «запустив дві справи — вони пішли паралельно, а не
чергою» (звіт користувача 29.08.2026).

Черга застосунку (`daemon.workers._READ_GATE`) цього не закриває: вона живе в
процесі демона й прогонів командного рядка не бачить взагалі. А саме командний
рядок — головний шлях для довгої роботи: прогін ставлять на ніч, часто по ssh.

🔴 Шарди ОДНІЄЇ справи — не конфлікт, а штатний спосіб її прочитати. Тому
реєстр розрізняє прогони за справою, а не за самим фактом існування: другий
шард тієї самої теки проходить, чужа справа — ні.

🔴 Кожна операція над файлом — «прочитав → змінив → записав» під замком
`runs.lock`. Без нього шарди, що стартують разом, на Windows падали на
`replace()` з WinError 5, а там, де не падали, затирали записи одне одного:
живий прогін зникав із реєстру (звіт користувача 28.09.2026). Замок живе мить
операції й тримається дескриптором, тож процес, що впав, його не лишає.

⚠ Вікно між `others()` і `register()` лишається свідомо: два прогони, стартовані
в ту саму мить, обидва пройдуть перевірку. Ціна помилки в цей бік — те, що було
й доти; замок на весь старт довелося б знімати руками, коли він застрягне. Від
справжнього одночасного заходу на карту захищає лок сегментації.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka.core.lock import process_alive, process_started
from nyshporka.core.workspace import workspace
from nyshporka.core.xrate import _locked

#: Поруч із локом карти: та сама тека, той самий життєвий цикл.
FILE = "runs.json"
#: Скільки чекати сусіда, що саме пише реєстр. Операція триває мілісекунди;
#: довше — це вже не черга, а завислий процес, і краще впасти з назвою файла.
LOCK_TIMEOUT = 30.0
#: Повтори `replace()` на Windows: антивірус чи індексатор може на мить відкрити
#: свіжий файл без спільного доступу. Від сусіда-писаря береже замок, не вони.
REPLACE_TRIES = 5


@dataclass(frozen=True)
class Live:
    """Один живий прогін — рівно те, чим його можна назвати людині."""

    pid: int
    #: Час старту процесу. Без нього перевикористаний PID видає чужий процес
    #: за наш — і мертвий прогін блокує справу до кінця доби.
    created: float
    #: Чим цей прогін зайнятий: ім'я теки справи (воно ж у звіті).
    case: str
    #: Шифра, якщо відома. Порожня — не привід не показувати рядок.
    case_key: str
    #: «k/n» або порожньо. Показується, щоб було видно, що це шард.
    shard: str
    #: Коли записано (не те саме, що `created`: процес живе довше за запис).
    since: float

    @property
    def minutes(self) -> int:
        return max(0, int((time.time() - self.since) / 60))

    def label(self) -> str:
        what = self.case_key or self.case
        tail = f" · шард {self.shard}" if self.shard else ""
        return f"{what}{tail} · pid {self.pid} · {self.minutes} хв"


def path() -> Path:
    return workspace().derived / "htr_lock" / FILE


def _read(p: Path) -> list[dict[str, Any]]:
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return got if isinstance(got, list) else []


@contextmanager
def _transaction() -> Iterator[Path]:
    """Реєстр під замком на всю операцію; віддає шлях до файла."""
    p = path()
    with _locked(p.with_suffix(".lock"), timeout=LOCK_TIMEOUT):
        yield p


def _write(p: Path, rows: list[dict[str, Any]]) -> None:
    """Лише всередині `_transaction()`."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    for i in range(REPLACE_TRIES):
        try:
            tmp.replace(p)
            return
        except PermissionError:
            if i == REPLACE_TRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (i + 1))


def _row(d: dict[str, Any]) -> Live | None:
    try:
        return Live(pid=int(d["pid"]), created=float(d.get("created") or 0.0),
                    case=str(d.get("case") or ""),
                    case_key=str(d.get("case_key") or ""),
                    shard=str(d.get("shard") or ""),
                    since=float(d.get("since") or 0.0))
    except (KeyError, TypeError, ValueError):
        return None


def alive() -> list[Live]:
    """Живі прогони; мертві записи прибираються тут-таки.

    🔴 Реап робиться на КОЖНОМУ читанні, а не окремою командою. Осиротілий
    запис (сесію вбито, термінал закрито) інакше блокував би справу доти, доки
    хтось про нього згадає, — а це рівно та вада, від якої реєстр рятує, лише
    в протилежний бік: замість «дві справи разом» вийшло б «жодної».

    ⚠ «Не знаю» (немає psutil) трактується як ЖИВИЙ. Помилка в цей бік коштує
    зайвого попередження, у протилежний — завалених прогонів.
    """
    with _transaction() as p:
        rows = _read(p)
        keep: list[dict[str, Any]] = []
        out: list[Live] = []
        for d in rows:
            row = _row(d)
            if row is None:
                continue
            if process_alive(row.pid, row.created) is False:
                continue
            keep.append(d)
            out.append(row)
        if len(keep) != len(rows):
            _write(p, keep)
    return out


def others(case: str) -> list[Live]:
    """Живі прогони ІНШИХ справ. Шарди тієї самої сюди не потрапляють."""
    return [r for r in alive() if r.case != case]


def register(pid: int, *, case: str, case_key: str = "", shard: str = "",
             created: float | None = None) -> None:
    """Записати прогін як живий.

    ⚠ `created` — час старту ТОГО процесу, чий pid записуємо. Для власного це
    `start_time()`; для дочірнього його дає psutil, а коли не дає — лишається
    нуль, і тоді звірка PID вироджується в саму лише наявність. Це гірше, ніж
    із часом, але краще, ніж не писати нічого: без запису черги немає зовсім.
    """
    if created is None:
        created = process_started() if pid == os.getpid() else _created_of(pid)
    with _transaction() as p:
        rows = [d for d in _read(p) if int(d.get("pid") or 0) != pid]
        rows.append({"pid": pid, "created": created, "case": case,
                     "case_key": case_key, "shard": shard, "since": time.time()})
        _write(p, rows)


def _created_of(pid: int) -> float:
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return 0.0


def drop(pid: int) -> None:
    """Прибрати запис. Тихо: прогін міг і не реєструватись."""
    with _transaction() as p:
        rows = _read(p)
        keep = [d for d in rows if int(d.get("pid") or 0) != pid]
        if len(keep) != len(rows):
            _write(p, keep)
