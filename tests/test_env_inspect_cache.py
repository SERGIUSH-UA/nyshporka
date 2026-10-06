"""⏱ Огляд середовища рушіїв для плану читання — раз на стан середовища.

Холодний прохід 07.10.2026: «Що робитимемо» і «Читати» кожне стояло ~13 с на
«Хвилинку…», бо план щоразу запускав десять процесів чужого інтерпретатора.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nyshporka.htr import env as E
from nyshporka.htr import manifest as M


@pytest.fixture
def venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    v = tmp_path / "venv"
    py = E.venv_python(v)
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    (v / "Lib" / "site-packages").mkdir(parents=True)
    (v / "pyvenv.cfg").write_text("", encoding="utf-8")
    man = M.active()
    pinned = {M.dist_name(s): s.split("==", 1)[1].strip()
              for s in man.packages if "==" in s}
    calls: list[str] = []

    def probe(_py: Path, code: str, timeout: int = 120) -> str | None:
        calls.append(code)
        if "importlib.metadata" in code:
            dist = code.split("m.version(")[1].split(")")[0].strip("'\"")
            return pinned.get(dist, "1.0")
        if code == E.CUDA_WORKS:
            return "True"
        if "get_device_capability" in code:
            return "8.6"
        if "torch.__version__" in code:
            return "2.0"
        return ""

    monkeypatch.setattr(E, "_probe", probe)
    monkeypatch.setattr(E, "_INSPECTED", {})
    return v, calls


def test_second_plan_reuses_the_inspection(venv) -> None:
    v, calls = venv
    assert E.inspect_cached(v).ok
    first = len(calls)
    assert first > 0
    assert E.inspect_cached(v).ok
    assert len(calls) == first, "повторний план знову запускав процеси огляду"


def test_reinstalling_a_package_invalidates_the_cache(venv) -> None:
    v, calls = venv
    E.inspect_cached(v)
    first = len(calls)
    site = v / "Lib" / "site-packages"
    later = time.time() + 5
    os.utime(site, (later, later))       # тека пакетів змінилась — як після install
    E.inspect_cached(v)
    assert len(calls) > first, "після зміни середовища огляд узято з кешу"


def test_a_failed_inspection_is_not_cached(venv, monkeypatch) -> None:
    v, calls = venv
    monkeypatch.setattr(E, "_probe", lambda *_a, **_k: calls.append("x") or None)
    assert not E.inspect_cached(v).ok
    n = len(calls)
    assert not E.inspect_cached(v).ok
    assert len(calls) > n, "невдалий огляд закешовано — полагоджене не побачать"


def test_a_fresh_diagnostic_inspection_warms_the_plan(venv) -> None:
    v, calls = venv
    assert E.inspect(v).ok                # так кличе діагностика головної
    n = len(calls)
    assert E.inspect_cached(v).ok
    assert len(calls) == n, "план не скористався свіжим оглядом діагностики"


def test_the_cache_expires(venv, monkeypatch) -> None:
    v, calls = venv
    E.inspect_cached(v)
    n = len(calls)
    monkeypatch.setattr(E, "INSPECT_TTL_SEC", 0.0)
    E.inspect_cached(v)
    assert len(calls) > n, "огляд пережив свій строк — карту чи драйвер могли змінити"


def test_a_plan_during_a_running_inspection_waits_and_reuses_it(venv, monkeypatch) -> None:
    """Діагностика головної оглядає середовище у фоні; план, що прийшов посеред
    огляду, не запускає поруч другий — чекає й бере готовий."""
    import threading

    v, calls = venv
    slow = E._probe

    def slow_probe(py, code, timeout=120):
        time.sleep(0.02)
        return slow(py, code, timeout)

    monkeypatch.setattr(E, "_probe", slow_probe)
    t = threading.Thread(target=E.inspect, args=(v,))
    t.start()
    time.sleep(0.05)                       # огляд діагностики вже йде
    assert E.inspect_cached(v).ok
    t.join()
    one = len(calls)
    calls.clear()
    E.inspect(v)
    assert one == len(calls), "план запустив свій огляд поруч із тим, що вже йшов"

