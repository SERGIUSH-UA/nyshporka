"""Запис, який не лишає обрізаного файлу, і читання, яке не бреше порожнечею.

Дві біди, від яких тут захист, — різні, але ходять парою і разом знищують
роботу людини:

1. **Обрив посеред запису.** `path.write_text(...)` спершу вкорочує файл до нуля,
   а потім наповнює. Ctrl+C, повний диск чи падіння в цю мить лишають на диску
   обрізаний JSON. Ідіома `tmp` + `os.replace` розписана в пакеті руками
   принаймні в шістнадцяти місцях — і рівно там, де лежать РІШЕННЯ ЛЮДИНИ
   (вердикти хітів, прив'язки прогонів, черга розбіжностей фонду), її забули.

2. **Тихе `except: return {}`.** Читач, який на побитому файлі віддає порожньо,
   у парі з писачем `data = load(); data[k] = v; save(data)` не просто ховає
   помилку — він СТИРАЄ все, що там було. Одна зайва кома, вписана редактором у
   `overrides.json`, коштує всіх попередніх прив'язок. Тому `read_json` розводить
   «файла ще немає» (порожньо — нормальний стан) і «файл не розбирається»
   (виняток, і хай писач відмовиться писати).

Атомарність тут — тільки від обриву, не від двох писачів одночасно: для цього
потрібен лок (`pagestore.store._lock`, `core.lock`).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = ["CorruptFileError", "atomic_write_bytes", "atomic_write_text",
           "read_json", "write_json"]

#: Скільки разів перечекати зайнятий файл на Windows.
_REPLACE_TRIES = 4
_REPLACE_PAUSE = 0.2


class CorruptFileError(RuntimeError):
    """Файл є, але не розбирається. Читати нíчого — і писати поверх НЕ МОЖНА."""

    def __init__(self, path: Path, why: str) -> None:
        self.path = Path(path)
        super().__init__(
            f"{path} не розбирається ({why}). Файл НЕ перезаписано, щоб не "
            f"втратити те, що в ньому лишилось: полагодьте його руками або "
            f"відсуньте вбік, і повторіть дію.")


def _replace(tmp: Path, path: Path) -> None:
    """`os.replace` із перечікуванням: на Windows ціль може саме читати в'ювер."""
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_REPLACE_PAUSE)


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8",
                      newline: str | None = None) -> Path:
    """Записати текст так, щоб на диску був або старий файл, або новий цілий.

    `newline` — як у `open()`: `None` перекладає `\\n` у `os.linesep` (на Windows
    це CRLF), `"\\n"` пише байт-у-байт. Реєстри фондів звіряються ПОБАЙТОВО з
    золотом, тож там передається явний LF.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid у назві: паралельні шарди й агентські сесії інакше перетирають tmp
    # один одному, і в ціль їде чужа половина.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding=encoding, newline=newline)
    _replace(tmp, path)
    return path


def atomic_write_bytes(path: Path | str, blob: bytes) -> Path:
    """Те саме для кадрів: недокачаний скан не має виглядати як завантажений."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
    tmp.write_bytes(blob)
    _replace(tmp, path)
    return path


def write_json(path: Path | str, data: Any, *, indent: int = 2,
               trailing_nl: bool = True, newline: str | None = None) -> Path:
    """JSON атомарно, кирилицею як є (`ensure_ascii=False`).

    `trailing_nl` — чи ставити перенос у кінці файлу; `newline` — чим писати
    самі переноси (див. `atomic_write_text`).
    """
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    return atomic_write_text(path, text + ("\n" if trailing_nl else ""),
                             newline=newline)


def read_json(path: Path | str, default: Any = None) -> Any:
    """Прочитати JSON. Немає файла — `default`; є, але побитий — виняток.

    🔴 Саме тут проходить межа, через яку губилися дані: «порожньо» повертається
    ТІЛЬКИ коли файла справді немає. Побитий вміст — це `CorruptFileError`, бо
    інакше наступний запис зітре рішення, які там ще читаються очима.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:                      # тека зникла, немає прав, диск відпав
        raise CorruptFileError(path, f"не читається: {e}") from e
    if not raw.strip():                       # порожній файл — те саме, що немає
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise CorruptFileError(path, f"рядок {e.lineno}: {e.msg}") from e
