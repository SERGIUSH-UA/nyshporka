"""🧠 Канон у пам'яті процесу: перечитується, лише коли на диску щось змінилось.

Екран «Канон» на відкритті кличе три операції (перевірка, рішення, перелік), і
кожна читала й розбирала всі картки наново; відкриття картки — ще одна повна
перевірка. На роді в 900 карток це секунди на кожен клік (22.10.2026). Процес
консолі живе годинами, тож прочитаний канон варто тримати, доки він той самий.

«Той самий» — за відбитком: ім'я, час зміни й розмір кожної картки, `regions.yml`,
маніфест доказів, журнал вердиктів гортача і сьогоднішня дата (перевірка
пише «не оновлювалась N днів»). Правка будь-якого з них дає новий відбиток, і
наступний виклик читає канон з диска.

🔴 Час зміни NTFS оновлюється тиками системного годинника, тож дві правки
однакового розміру в межах тіку дали б той самий відбиток. Тому свіжо
змінений канон (молодший за `_SETTLE` секунд) не кешується зовсім: його просто
читають щоразу, доки він не «відстоїться». Так само робить git з індексом.

🔴 Чого відбиток не бачить: файл доказу, що зник із диска без правки картки чи
маніфесту. Перевірка покаже його відсутність після наступної будь-якої правки.
Повна свіжа перевірка — `nysh canon check` (CLI — окремий процес, кешу не має).

Повернені об'єкти спільні для всіх викликів: читати, не змінювати.
"""
from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from nyshporka.canon.check import KINDS, Canon, Report, check, load, manifest_path

#: Скільки секунд канон мусить простояти без змін, щоб його можна було кешувати.
_SETTLE = 2.0

_LOCK = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.Lock] = {}
_CANON: dict[Path, tuple[tuple[Any, ...], Canon]] = {}
_REPORT: dict[Path, tuple[tuple[Any, ...], Report]] = {}


def _stat(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (path.name, st.st_mtime_ns, st.st_size)


def stamp(root: Path) -> tuple[tuple[Any, ...], int]:
    """Відбиток канону і найновіший час зміни в ньому (нс)."""
    canonical = Canon(root=root).canonical
    parts: list[Any] = [date.today().isoformat()]
    newest = 0
    for kind in KINDS:
        folder = canonical / kind
        try:
            entries = sorted(e for e in folder.iterdir() if e.suffix == ".md")
        except OSError:
            parts.append((kind, None))
            continue
        for e in entries:
            s = _stat(e)
            parts.append((kind, s))
            if s:
                newest = max(newest, s[1])
    for extra in (canonical / "regions.yml", manifest_path(root),
                  # журнал вердиктів гортача — той самий файл, що читає `_verdict_ready`
                  canonical.parent / "derived" / "verdicts.json"):
        s = _stat(extra)
        parts.append(s)
        if s:
            newest = max(newest, s[1])
    return tuple(parts), newest


def _settled(newest_ns: int) -> bool:
    return time.time() - newest_ns / 1e9 >= _SETTLE


def _root_lock(root: Path) -> threading.Lock:
    with _LOCK:
        return _ROOT_LOCKS.setdefault(root, threading.Lock())


def report(root: Path) -> Report:
    """Перевірка канону без перерахунку sha256 — з пам'яті, якщо канон той самий.

    Три одночасні запити екрана чекають одне читання, а не роблять три.
    """
    with _root_lock(root):
        key, newest = stamp(root)
        got = _REPORT.get(root)
        if got and got[0] == key:
            return got[1]
        rep = check(root)
        if _settled(newest):
            _REPORT[root] = (key, rep)
            _CANON[root] = (key, rep.canon)
        return rep


def canon(root: Path) -> Canon:
    """Прочитаний канон — з пам'яті, якщо на диску той самий."""
    with _root_lock(root):
        key, newest = stamp(root)
        got = _CANON.get(root)
        if got and got[0] == key:
            return got[1]
        c = load(root)
        if _settled(newest):
            _CANON[root] = (key, c)
        return c


def forget() -> None:
    """Забути все (тести)."""
    with _LOCK:
        _CANON.clear()
        _REPORT.clear()
