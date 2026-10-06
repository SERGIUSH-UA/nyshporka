"""🪢 Процес читання разом з усіма нащадками — як одне ціле.

Раннер читає не сам: наглядач запускає робочий процес, а той тримає карту.
Гасити їх поодинці ненадійно, бо на Windows убитий батько не забирає дітей:
діти лишаються сиротами, читають далі й тримають карту, а `psutil` уже не
знайде їх через батька, якого немає. Саме так 06.10.2026 у людини «Спинити»
зафарбувало прогін, а він дочитав ще 15 сторінок і не пустив до карти
наступне читання.

На Windows процес кладеться в Job Object з `KILL_ON_JOB_CLOSE`:

- `kill()` гасить усіх членів одним викликом, хоч би в якому порядку вони
  народились і хоч би хто з них уже помер;
- нащадки потрапляють у той самий об'єкт самі, без нашої участі;
- коли закривається останній дескриптор (наш процес завершився, впав, його
  вбили з диспетчера задач), система гасить усе дерево. Сиріт не буває.

⚠ Дескриптор тримається, доки живий `Contained`. Загублений об'єкт закриє його
збирачем сміття і вб'є читання посеред справи, тож власник тримає посилання
до кінця читання і закриває його сам (`close()`).

На інших системах об'єкта немає: `contain` повертає `None`, а зупинка йде
через `htr.session.kill_tree` — дерево знімається ДО першого вбивства.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class Contained:
    """Дескриптор Job Object з одним процесом читання і його нащадками."""

    def __init__(self, handle: int, pid: int) -> None:
        self._handle = handle
        self.pid = pid

    def kill(self) -> None:
        """Погасити всіх членів. Повторний виклик і мертві члени — не помилка."""
        if self._handle:
            with contextlib.suppress(OSError):
                _kernel32().TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Закрити дескриптор. ⚠ Живих членів це вб'є — кликати після кінця."""
        handle, self._handle = self._handle, 0
        if handle:
            with contextlib.suppress(OSError):
                _kernel32().CloseHandle(handle)

    def __del__(self) -> None:  # pragma: no cover — страховка, не шлях
        self.close()


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                          wintypes.LPVOID, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.TerminateJobObject.restype = wintypes.BOOL
    k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def _limits() -> Any:
    """`JOBOBJECT_EXTENDED_LIMIT_INFORMATION` з одним прапорцем."""
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic),
                    ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = _Extended()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return info


def contain(pid: int) -> Contained | None:
    """Покласти процес у власний Job Object. `None` — не Windows або не вдалось.

    Кликати одразу після старту процесу: нащадки, народжені ПІСЛЯ цього,
    потрапляють в об'єкт самі. Раннеру до першого нащадка — секунди (імпорти й
    моделі), а нам — мілісекунди.
    """
    if sys.platform != "win32" or pid <= 0 or pid == os.getpid():
        return None
    import ctypes

    try:
        k = _kernel32()
    except OSError:
        return None
    job = k.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _limits()
    proc = 0
    try:
        if not k.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                         ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
        proc = k.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not proc:
            raise OSError(ctypes.get_last_error(), "OpenProcess")
        if not k.AssignProcessToJobObject(job, proc):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
    except OSError:
        k.CloseHandle(job)
        return None
    finally:
        if proc:
            k.CloseHandle(proc)
    return Contained(int(job), pid)
