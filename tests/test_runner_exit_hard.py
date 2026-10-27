"""Вихід раннера минає фіналізацію інтерпретатора, а запис переживає зайнятий файл.

🔴 Відгук №3–4 з порталу (27.10.2026, Windows, ДАЧкО 833-1-*): шард дочитував
справу або падав на `os.replace` у `atomic_write`, а процес лишався живим із
нулем CPU, і `nysh read` чекав його вічно.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nyshporka.htr import runner as R

ROOT = Path(__file__).resolve().parents[1]


def _child(body: str) -> subprocess.CompletedProcess[str]:
    code = ("import sys, threading, time\n"
            "from nyshporka.htr import runner as R\n" + body)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=60, cwd=ROOT)


def test_vykhid_ne_chekaie_nedemonichnoho_potoku() -> None:
    """Потік, що не дає інтерпретатору завершитись, — модель зависання на виході."""
    got = _child("threading.Thread(target=time.sleep, args=(120,)).start()\n"
                 "R._exit_hard(lambda: 3)\n")
    assert got.returncode == 3


def test_vyniatok_drukuietsia_i_daie_kod_1() -> None:
    got = _child("threading.Thread(target=time.sleep, args=(120,)).start()\n"
                 "def bad():\n    raise PermissionError('zaniatyi')\n"
                 "R._exit_hard(bad)\n")
    assert got.returncode == 1
    assert "PermissionError: zaniatyi" in got.stderr


def test_sys_exit_zberihaie_kod() -> None:
    got = _child("R._exit_hard(lambda: sys.exit(2))\n")
    assert got.returncode == 2


def test_atomic_write_dochikuietsia_zaniatoho_failu(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Ціль зайнята довше за секунду (антивірус сканує tmp) — запис чекає, а не падає."""
    real = os.replace
    calls = {"n": 0}

    def busy(src, dst):
        calls["n"] += 1
        if calls["n"] < 6:
            raise PermissionError("busy")
        real(src, dst)

    monkeypatch.setattr(R.os, "replace", busy)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    p = tmp_path / "0001.txt"
    R.atomic_write(p, "текст")

    assert p.read_text(encoding="utf-8") == "текст"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_zdaietsia_zreshtoiu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def never(src, dst):
        raise PermissionError("busy")

    monkeypatch.setattr(R.os, "replace", never)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        R.atomic_write(tmp_path / "0001.txt", "x")
