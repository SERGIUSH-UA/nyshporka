"""Сегментатори (`--segment-only`): геометрія сторінки окремими процесами.

🔴 Навіщо (05.10.2026, DAZHO 1-78-1037, 1×V100 16 ГБ, квота 17 ядер): шард рахує
сторінку послідовно — ~5 с геометрії на процесорі, потім ~5 с розпізнавання, — а
більше 6 шардів не вміщала пам'ять карти, бо кожен несе всі моделі
розпізнавання. 11 ядер стояли. Сегментатор несе лише мережу сегментації, ріже
сторінки наперед у кеш, і читач бере нарізку готовою.

Що тут доведено: сегментатор не бере чужого (текст, нарізка, клейм читача), не
пише тексту й мети; читач не чекає вічно на завислого сегментатора; ручки, з
якими сегментатор крутився б вхолосту, відмовляються вголос.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pytest

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location("_runner_segmenters", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def _args(**kw) -> argparse.Namespace:
    base = dict(seg_cache=True, orient_check=False, force_orient=0, shard="3/8",
                max_endpoints=400, min_conf=0.0, min_chars=0.0, sure_conf=0.0,
                guard_warmup=0, batch=32, enhance="none", keep_cache=False)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.mark.parametrize("kw, claim, word", [
    ({"seg_cache": False}, True, "кешу"),
    ({}, False, "--claim"),
    ({"orient_check": True}, True, "--orient-check"),
])
def test_segmenter_refuses_knobs_that_would_make_it_idle(runner, kw, claim, word):
    why = runner.segment_only_refusal(_args(**kw), claim)
    assert word in why


def test_segmenter_with_proper_knobs_is_allowed(runner):
    assert runner.segment_only_refusal(_args(), True) == ""


def _claim(d: Path, stem: str, pid: int) -> None:
    (d / "_claims").mkdir(parents=True, exist_ok=True)
    (d / "_claims" / f"{stem}.claim").write_text(f"{pid} 1/8 2026-10-05T12:00:00\n",
                                                 encoding="utf-8")


def _dead_pid() -> int:
    # pid, якого точно немає: найбільший можливий плюс запас
    return 2**22 + 12345


def test_reader_waits_only_for_a_live_segmenter_without_a_result(runner, tmp_path):
    out = tmp_path
    segq = out / runner.SEGQ_DIR
    cache: set[str] = set()

    def cached(stem):
        return stem in cache

    assert not runner.seg_in_progress(out, "0001", cached)       # заявки немає
    _claim(segq, "0001", os.getpid())
    assert runner.seg_in_progress(out, "0001", cached)           # ріже живий
    cache.add("0001")
    assert not runner.seg_in_progress(out, "0001", cached)       # нарізка є
    _claim(segq, "0002", _dead_pid())
    assert not runner.seg_in_progress(out, "0002", cached)       # сегментатор помер
    _claim(segq, "0003", os.getpid())
    (segq / "0003.failed").write_text("boom\n", encoding="utf-8")
    assert not runner.seg_in_progress(out, "0003", cached)       # упав на ній
    _claim(segq, "0004", os.getpid())
    (out / "0004.txt").write_text("x\n", encoding="utf-8")
    assert not runner.seg_in_progress(out, "0004", cached)       # уже прочитано


def test_page_feed_returns_to_deferred_pages_until_none_left(runner):
    pages = [Path(f"{k:04d}.jpg") for k in range(1, 4)]
    deferred: list = []
    seen: list[str] = []
    waits = {"0002": 2}
    for i, src in runner.page_feed(pages, deferred, pause=0.0):
        left = waits.get(src.stem, 0)
        if left:
            waits[src.stem] = left - 1
            deferred.append((i, src))
            continue
        seen.append(src.stem)
    assert seen == ["0001", "0003", "0002"]


class _FakeSegmenter:
    def __init__(self, d: Path):
        self.dir = d
        self._model = object()

    def _file(self, stem, orient):
        return self.dir / f"{stem}.o{orient}.seg.json.gz"


class _FakeCeiling:
    def set_ceiling(self, n):
        pass

    def reset(self):
        pass


def test_segmenter_cuts_only_free_pages_and_writes_no_text(runner, tmp_path, monkeypatch):
    case = tmp_path / "case"
    out = tmp_path / "out"
    segdir = tmp_path / "seg"
    for d in (case, out, segdir):
        d.mkdir()
    pages = []
    for k in range(1, 6):
        p = case / f"{k:04d}.jpg"
        p.write_bytes(b"")
        pages.append(p)
    (out / "0001.txt").write_text("прочитано\n", encoding="utf-8")   # текст є
    (segdir / "0002.o0.seg.json.gz").write_bytes(b"")              # нарізка є
    _claim(out, "0003", _dead_pid())                               # клейм читача
    seg = _FakeSegmenter(segdir)
    calls: list[str] = []

    def fake_process_page(src, segmenter, rec_model, *a, **k):
        assert rec_model is None                 # жодної моделі розпізнавання
        calls.append(src.stem)
        if src.stem == "0005":
            raise ValueError("битий кадр")
        segmenter._file(src.stem, 0).write_bytes(b"")
        return {"lines": []}

    monkeypatch.setattr(runner, "process_page", fake_process_page)
    cache: dict = {}
    rc = runner.segment_only_loop(_args(), pages, out, seg, "cpu", "parseq", 2, False,
                                  {}, _FakeCeiling(), cache)
    assert rc == 0
    assert calls == ["0004", "0005"]
    segq = out / runner.SEGQ_DIR
    assert (segq / "_claims" / "0004.claim").exists()
    assert (segq / "0005.failed").exists()      # читач не чекатиме на неї
    assert [t.name for t in out.glob("*.txt")] == ["0001.txt"]   # нового тексту немає
    assert not list(out.glob("_htr_meta*.json"))
    assert cache["seg_model"] is seg._model     # модель сегментації — на всю чергу


def test_segmenter_steps_back_when_a_reader_claimed_the_page_in_between(
        runner, tmp_path, monkeypatch):
    case, out, segdir = tmp_path / "case", tmp_path / "out", tmp_path / "seg"
    for d in (case, out, segdir):
        d.mkdir()
    p = case / "0001.jpg"
    p.write_bytes(b"")
    real_claim = runner.claim_page

    def claim_then_reader_arrives(d, stem, shard=""):
        ok = real_claim(d, stem, shard)
        _claim(out, stem, os.getpid())            # читач заклеймив у вікні
        return ok

    monkeypatch.setattr(runner, "claim_page", claim_then_reader_arrives)
    monkeypatch.setattr(runner, "process_page",
                        lambda *a, **k: pytest.fail("сторінку читача різати не можна"))
    runner.segment_only_loop(_args(), [p], out, _FakeSegmenter(segdir), "cpu", "parseq",
                             2, False, {}, _FakeCeiling(), {})
    # заявку знято: інакше читач чекав би на нарізку, якої ніхто не робить
    assert not (out / runner.SEGQ_DIR / "_claims" / "0001.claim").exists()


def test_drained_segmenter_leaves_the_queue(runner, tmp_path, monkeypatch):
    case, out, segdir = tmp_path / "case", tmp_path / "out", tmp_path / "seg"
    for d in (case, out, segdir):
        d.mkdir()
    p = case / "0001.jpg"
    p.write_bytes(b"")
    (out / runner.DRAIN_DIR).mkdir()
    (out / runner.DRAIN_DIR / "3").write_text("", encoding="utf-8")   # шард 3 (k=2)
    monkeypatch.setattr(runner, "process_page",
                        lambda *a, **k: pytest.fail("злитий сегментатор не ріже"))
    cache: dict = {}
    runner.segment_only_loop(_args(), [p], out, _FakeSegmenter(segdir), "cpu", "parseq",
                             2, False, {}, _FakeCeiling(), cache)
    assert cache.get("drained") is True


def test_a_segmenter_does_not_run_under_the_text_supervisor(runner, tmp_path, monkeypatch):
    """Голова `--supervise` перезапускає воркер, поки немає ТЕКСТУ, — сегментатор
    тексту не пише, і крутився б до стелі перезапусків, виходячи з «неповно»."""
    monkeypatch.setattr(runner, "supervise",
                        lambda *a, **k: pytest.fail("сегментатор пішов під голову"))
    monkeypatch.setattr(runner, "KRAKEN_PIN_VERSION", "0.0.0")    # далі — відмова, швидко
    monkeypatch.delenv("NYSHPORKA_HTR_CHILD", raising=False)
    args = argparse.Namespace(case_dir=str(tmp_path), out_dir=str(tmp_path / "out"),
                              progress_json=False, supervise=3, allow_any_kraken=False,
                              segment_only=True)
    assert runner._main_case(args) == 2
    called = []
    monkeypatch.setattr(runner, "supervise", lambda *a, **k: called.append(1) or 0)
    args.segment_only = False
    runner._main_case(args)
    assert called, "читач без голови — тест нічого не доводить"
