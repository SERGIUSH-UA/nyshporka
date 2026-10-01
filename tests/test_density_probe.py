"""Щільність нечитаної справи — з вибірки кадрів (гість `htr/density_probe.py`).

Хост: розбір відповіді гостя, кеш у похідних даних простору, тиха відмова там,
де оцінити нічим. Сам гість ганяється в середовищі рушіїв, тут — підміна.
"""
from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import pytest

from nyshporka.cloud import frames as F
from nyshporka.htr import density_probe as G


def _frames(d: Path, n: int = 30) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"{i:04d}.jpg").write_bytes(b"x")
    return d


@pytest.fixture
def engines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Середовище рушіїв «є», запуски гостя записуються, кеш — у tmp."""
    py = tmp_path / "venv" / "python.exe"
    py.parent.mkdir()
    py.write_bytes(b"")
    calls: list[list[str]] = []
    monkeypatch.setattr("nyshporka.setup.doctor.engine_venv", lambda: tmp_path / "venv")
    monkeypatch.setattr("nyshporka.htr.env.venv_python", lambda v: py)
    monkeypatch.setattr(F, "_probe_cache",
                        lambda frames, d: tmp_path / "cache" / f"{d.name}.json")
    answer = {"ok": True, "n": 40, "lines_mean": 33.3, "lines_median": 18.0,
              "device": "cuda:0", "sec": 55.0}

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(stdout="шум kraken\n" + json.dumps(answer) + "\n",
                                     stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_mean_not_median_and_the_answer_is_cached(tmp_path: Path, engines) -> None:
    d = _frames(tmp_path / "spr-11821")
    lines: list[str] = []
    assert F.lines_per_page_probe(d, on_line=lines.append) == 33.3   # середнє, не 18
    assert len(engines) == 1 and engines[0][-2:] == ["--sample", "40"]
    assert any("33.3" in s for s in lines)
    assert F.lines_per_page_probe(d) == 33.3
    assert len(engines) == 1, "вдруге з кешу, без сегментації"


def test_failed_probe_keeps_the_assumption(tmp_path: Path, engines,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    d = _frames(tmp_path / "spr-1")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(
        stdout=json.dumps({"ok": False, "why": "CUDA out of memory"}), stderr="",
        returncode=1))
    said: list[str] = []
    assert F.lines_per_page_probe(d, on_line=said.append) is None
    assert any("CUDA out of memory" in s for s in said)


def test_no_engines_no_frames_no_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nyshporka.setup.doctor.engine_venv", lambda: tmp_path / "nope")
    assert F.lines_per_page_probe(_frames(tmp_path / "a")) is None
    assert F.lines_per_page_probe(tmp_path / "missing") is None


def test_sample_skips_covers_and_spreads_evenly(tmp_path: Path) -> None:
    d = _frames(tmp_path / "c", 100)
    got = G.sample_frames(d, 40)
    assert len(got) == 40
    names = [p.name for p in got]
    assert names[0] == "0003.jpg" and "0099.jpg" not in names and "0097.jpg" not in names
    assert len(set(names)) == 40
    assert len(G.sample_frames(_frames(tmp_path / "small", 10), 40)) == 10
