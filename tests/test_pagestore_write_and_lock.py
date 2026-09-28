"""🗂 Сховище сторінок: запис переживає зайнятий файл, протухлий лок забирає один.

Аудит 29.09.2026, дві вади запису `data/pages/<REPO>/<fond>-<spr>.json`:

  · `_write` робив голий `tmp.replace(path)` зі спільним `.json.tmp`. На
    Windows заміна падає з PermissionError, поки файл читає збірка реєстру чи
    в'ювер, — нотатка не записувалась, а поруч лишався `.json.tmp`;
  · двоє чекачів, які бачать протухлий лок, обидва його «забирали»: A знімав
    і ставив свій, B знімав уже свіжий лок A — і обидва писали справу разом.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nyshporka.pagestore import store as S
from nyshporka.pagestore.models import CaseFile, PageNote


def _cf() -> CaseFile:
    cf = CaseFile(key="DAHMO/315/1", repo="DAHMO", fond="315", spr="1")
    cf.pages["0001.jpg"] = PageNote(scan="0001.jpg", page_type="birth",
                                    surnames=["Ковальскій"])
    return cf


def test_write_waits_out_a_busy_target(tmp_path: Path, monkeypatch) -> None:
    """Перша заміна падає, як на Windows під читачем, — запис усе одно лягає."""
    path = tmp_path / "315-1.json"
    real = os.replace
    calls = {"n": 0}

    def busy_once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "файл тримає читач", str(dst))
        return real(src, dst)

    monkeypatch.setattr(os, "replace", busy_once)
    S._write(path, _cf())

    assert calls["n"] == 2
    got = CaseFile.model_validate_json(path.read_text(encoding="utf-8"))
    assert got.pages["0001.jpg"].surnames == ["Ковальскій"]
    assert not list(tmp_path.glob("*.tmp")), "проміжний файл лишився поруч"


def test_second_waiter_does_not_remove_a_fresh_lock(tmp_path: Path,
                                                    monkeypatch) -> None:
    """B побачив протухлий лок, але A встиг його забрати — B мусить чекати.

    Гонка відтворюється детерміновано: перший `stat()` лока повертає B старий
    (протухлий) стан, а поки B «думає», A забирає лок і тримає його. Далі B
    діє на підставі застарілого спостереження — рівно те, що бувало між двома
    сесіями. ⚠ A тут — файл лока без відкритого дескриптора: на Windows
    відкритий дескриптор власника лишає ім'я в стані pending-delete і випадково
    маскує гонку, а на Linux (хмарні бокси) такого захисту немає.
    """
    path = tmp_path / "315-1.json"
    lockp = path.with_name(path.name + ".lock")
    lockp.write_text("999999", encoding="utf-8")
    old = time.time() - 120
    os.utime(lockp, (old, old))

    real_stat = Path.stat
    fired: list[int] = []

    def racing_stat(self, *args, **kw):
        if not fired and self == lockp:
            fired.append(1)
            seen = real_stat(self, *args, **kw)      # B бачить протухлий лок…
            lockp.unlink()                            # …а A тим часом його забирає
            lockp.write_text("A", encoding="utf-8")   # і тримає свіжий
            return seen
        return real_stat(self, *args, **kw)

    monkeypatch.setattr(Path, "stat", racing_stat)
    with pytest.raises(TimeoutError), S._lock(path, timeout=0.5):
        pytest.fail("B увійшов, поки лок тримає A")
    assert fired, "гонку не відтворено"
    assert lockp.read_text(encoding="utf-8") == "A", "свіжий лок A знято"
    assert not lockp.with_name(lockp.name + ".steal").exists()


def test_a_stale_lock_is_still_taken_over(tmp_path: Path) -> None:
    """Сторож не заважає головному: лок мертвого власника забирається."""
    path = tmp_path / "315-1.json"
    lockp = path.with_name(path.name + ".lock")
    lockp.write_text("999999", encoding="utf-8")
    old = time.time() - 120
    os.utime(lockp, (old, old))
    with S._lock(path, timeout=2):
        assert lockp.read_text(encoding="utf-8").strip() == str(os.getpid())
    assert not lockp.exists()
