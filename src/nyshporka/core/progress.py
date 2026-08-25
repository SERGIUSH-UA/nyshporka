"""📶 Прогрес довгої роботи — один канал на всі підпроцеси.

Важка робота (завантаження плівки, читання справи, трен) живе в окремому
процесі, і єдине, що з нього видно, — потік рядків. Тому прогрес їде тим самим
потоком, але окремим, машинним каналом: рядок із префіксом і JSON.

🔴 Чому не «розібрати звичайний вивід». Раннер друкує для людини, і формат тих
рядків міняється щоразу, коли комусь треба щось дописати. Парсер такого виводу
ламається мовчки: прогрес завмирає, вотчдог за 10 хвилин тиші вбиває ЖИВИЙ
прогін, і виглядає це як «завис». Явний канал ламається гучно — рядок або
розібрався, або ні.

🔴 Схема версійована. Поля прогресу міняються (додався `skipped`, з'явився
`basis`), і читач старої версії мусить це помітити, а не мовчки читати число
не того сенсу.

    from nyshporka.core.progress import emit, parse
    emit(phase="fetch", i=12, n=300, item="0012.jpg")
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TextIO

#: Префікс машинного каналу. Довгий і незвичайний навмисно: він не має
#: випадково зустрітись у людському виводі чи в тексті сторінки.
PREFIX = "@@PROGRESS@@"
SCHEMA = 1


@dataclass(frozen=True)
class Event:
    """Одне повідомлення прогресу."""

    phase: str = ""
    i: int = 0
    n: int = 0
    item: str = ""
    done: int = 0
    skipped: int = 0
    failed: int = 0
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def pct(self) -> float:
        return round(100.0 * self.i / self.n, 1) if self.n else 0.0


def emit(*, phase: str = "", i: int = 0, n: int = 0, item: str = "",
         done: int = 0, skipped: int = 0, failed: int = 0, message: str = "",
         stream: TextIO | None = None, **extra: Any) -> None:
    """Надіслати подію прогресу.

    Пишемо в stdout і одразу зливаємо: підпроцес часто буферизує вивід, а
    прогрес, який доїде через хвилину, — це прогрес, якого немає.
    """
    payload: dict[str, Any] = {"v": SCHEMA, "phase": phase, "i": i, "n": n}
    if item:
        payload["item"] = item
    for key, value in (("done", done), ("skipped", skipped), ("failed", failed)):
        if value:
            payload[key] = value
    if message:
        payload["message"] = message
    payload.update(extra)
    out = stream or sys.stdout
    # ensure_ascii — щоб рядок лишався одним рядком у будь-якому кодуванні консолі
    print(f"{PREFIX} {json.dumps(payload, ensure_ascii=True)}", file=out, flush=True)


def parse(line: str) -> Event | None:
    """Рядок → подія, або None якщо це звичайний вивід.

    None — це не помилка: у потоці змішані людські рядки й машинні, і більшість
    із них не наші.
    """
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX):].strip())
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if int(data.get("v") or 0) != SCHEMA:
        # Чужа версія схеми. Мовчки читати поля, які могли змінити сенс, гірше,
        # ніж не прочитати нічого: показник, що бреше, гірший за відсутній.
        return None
    known = {"phase", "i", "n", "item", "done", "skipped", "failed", "message"}
    return Event(
        phase=str(data.get("phase") or ""),
        i=int(data.get("i") or 0), n=int(data.get("n") or 0),
        item=str(data.get("item") or ""),
        done=int(data.get("done") or 0), skipped=int(data.get("skipped") or 0),
        failed=int(data.get("failed") or 0),
        message=str(data.get("message") or ""),
        extra={k: v for k, v in data.items() if k not in known and k != "v"},
    )


def split(line: str) -> tuple[Event | None, str | None]:
    """Рядок → (подія, людський рядок). Рівно одне з двох буде не-None.

    Так споживач не мусить вирішувати двічі: подія йде в прогрес, решта — у
    хвіст лога, який читає людина, коли щось пішло не так.
    """
    ev = parse(line)
    return (ev, None) if ev is not None else (None, line)


# ── поступ у тому самому процесі ─────────────────────────────────────────────
# 🔴 Другий канал того самого прогресу, і він потрібен саме тому, що перший
# міжпроцесний. Довга операція, яка виконується ТУТ-таки (свіп по корпусу,
# збирання індексу, обхід каталогу), нічого нікуди не друкує: вона рахує й
# повертає конверт. Доти це означало, що робота на чверть години показувалась
# у черзі як «іде» — і відрізнити її від зависання можна було лише чеканням.
#
# Контекстна змінна, а не аргумент: та сама операція працює й у командному
# рядку, де черги немає, — і тоді просто звітує в порожнечу, нічого про
# різницю не знаючи. Прокидати ж приймач крізь чотири шари викликів означало б
# навчити кожен із них випадку «нікуди».
_SINK: ContextVar[Callable[[int, int, str], None] | None] = ContextVar(
    "progress_sink", default=None)


def report(i: int, n: int, note: str = "") -> None:
    """Сказати, де робота зараз. Без приймача — нічого не робить.

    ⚠ Кличеться З РОБОЧОГО ПОТОКУ, і витримувати це мусить сам приймач: тіло
    операції крутиться в окремому потоці, а черга живе в циклі подій.

    ⚠ Поступ — НЕ результат. «Пройшли 900 із 1159» не означає «900 прочесано»:
    частина могла не мати індексу. Числа роботи й числа відповіді рахуються
    окремо, інакше обсяг спроби видається за обсяг зробленого.
    """
    fn = _SINK.get()
    if fn is None:
        return
    try:
        fn(int(i), int(n), str(note or ""))
    except Exception:
        # 🔴 Збій ЗВІТУ не має права зупинити роботу. Прогін, який упав, бо не
        # зміг сказати, що він на 900-му, — найгірший рід відмови: втрачено
        # все зроблене, і причина не має стосунку до задачі.
        return


@contextmanager
def sink(fn: Callable[[int, int, str], None] | None) -> Iterator[None]:
    """Приймати поступ у цьому контексті."""
    token = _SINK.set(fn)
    try:
        yield
    finally:
        _SINK.reset(token)
