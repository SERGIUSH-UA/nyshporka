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


def test_the_card_memory_is_released_after_every_frame(tmp_path: Path) -> None:
    """🔴 02.10.2026, ЦДІАК 127-1016-247: кожен розворот має свою ширину, і кеш
    алокатора torch тримав блоки під кожну — 5.7 ГБ зарезервованого на 4-ГБ
    карті за шість кадрів, а замір ріс до 8–12 ГБ RAM. Карта віддається після
    КОЖНОГО кадру-сторінки."""
    released: list[int] = []

    class _Img:
        def __init__(self, size):
            self.size = size

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def convert(self, mode):
            return self

    sizes = {"a": (3905, 3100), "label": (9000, 1800), "b": (4111, 3100)}
    rets = {"cls_map": {"aux": {"_start_separator": 0, "_end_separator": 1},
                        "baselines": {"default": 2}},
            "heatmap": {}}

    class _Heat(dict):
        def __getitem__(self, key):
            return key

    rets["heatmap"] = _Heat()
    blla = types.SimpleNamespace(compute_segmentation_map=lambda im, _m, model, dev: rets)
    kseg = types.SimpleNamespace(
        vectorize_lines=lambda h, text_direction, max_endpoints: [1] * 7)
    got = G.count_lines([Path(k) for k in sizes], object(), "cuda:0", blla=blla, kseg=kseg,
                        release=lambda: released.append(1),
                        open_image=lambda f: _Img(sizes[Path(f).name]))
    assert got == [7, 7]
    assert len(released) == 2, "етикетку не сегментуємо, а після кожної сторінки — віддати"


def test_without_a_card_the_probe_counts_with_the_runner_sigmas() -> None:
    """02.10.2026, 127-1016-247: без карти замір брав рідні sigmas kraken
    (1,3,5,7,9) і рахував 158 рядків там, де раннер зі своїми (1,3) бачить 114."""
    import re

    src = (Path(G.__file__).parent / "runner.py").read_text(encoding="utf-8")
    default = re.search(r'"--sato-sigmas", default="([^"]*)"', src)
    assert default and tuple(int(p) for p in default.group(1).split(",")) == G.SATO_SIGMAS

    seen: list[tuple] = []
    skf = types.SimpleNamespace(sato=lambda image, sigmas=(1, 3, 5, 7, 9), **kw:
                                seen.append(tuple(sigmas)))
    G.install_sato(skf, "cpu", install_gpu=lambda *a, **kw: pytest.fail("карти немає"))
    skf.sato("heat", black_ridges=False, mode="constant")   # так кличе kraken
    assert seen == [G.SATO_SIGMAS]

    gpu: list[tuple] = []
    G.install_sato(skf, "cuda:0", install_gpu=lambda s, device: gpu.append((s, device)))
    assert gpu == [(G.SATO_SIGMAS, "cuda:0")]
