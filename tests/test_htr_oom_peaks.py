"""Пік карти не валить сторінку і не стискає флот назавжди.

🔴 Інцидент (05.10.2026, DAZHO 1-78-1037, 1×V100 16 ГБ): один рядок «out of
memory» від піку одного шарда — і регулятор флоту назавжди зупинив його на 6
шардах, хоча в середньому карта була зайнята на 5–9 ГБ із 16, а 11 ядер із 17
стояли. Сторінка, яку задавив чужий пік, на повторі проходить; цей файл
доводить, що раннер її повторює, а рядок для наглядача каже, що пік ВІДНОВЛЕНО.

Раннер вантажиться за шляхом — так само, як його запускає наглядач.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("_runner_oom_peaks", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OOM_RETRY_SLEEP", 0.0)
    yield mod
    sys.modules.pop(spec.name, None)


def _oom() -> Exception:
    return torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")


def test_cuda_oom_is_told_apart_from_other_errors(runner):
    assert runner.is_cuda_oom(_oom())
    assert runner.is_cuda_oom(RuntimeError("CUDA out of memory. Tried to allocate 20 MiB"))
    assert runner.is_cuda_oom(RuntimeError("CUBLAS_STATUS_ALLOC_FAILED when calling"))
    # пам'ять ПРОЦЕСОРА повтором не лікується — це інша подія для регулятора
    assert not runner.is_cuda_oom(MemoryError())
    assert not runner.is_cuda_oom(ValueError("bad crop"))


def test_oom_line_does_not_trip_the_old_regulator(runner):
    """Старий регулятор рахує OOM за словами «out of memory» у будь-якому рядку
    шарда й стискає флот назавжди. Відновлений пік не має його зачіпати."""
    runner.CURRENT_PAGE[0] = "0002.jpg"
    line = runner.oom_line("seg_net", "retry")
    assert line.startswith("[htr-oom] ")
    assert "out of memory" not in line.lower()
    assert "memoryerror" not in line.lower()
    fields = dict(b.split("=", 1) for b in line.split()[1:])
    assert fields["stage"] == "seg_net"
    assert fields["page"] == "0002.jpg"
    assert fields["outcome"] == "retry"


def test_page_is_read_again_after_a_peak(runner, capsys):
    calls = []

    def run():
        calls.append(1)
        if len(calls) == 1:
            raise _oom()
        return "ok"

    assert runner.call_with_oom_retry(run, "cuda:0") == "ok"
    assert len(calls) == 2
    out = capsys.readouterr().out
    assert "outcome=retry" in out and "outcome=fail" not in out


def test_second_oom_fails_the_page_and_says_so(runner, capsys):
    def run():
        raise _oom()

    with pytest.raises(torch.cuda.OutOfMemoryError):
        runner.call_with_oom_retry(run, "cuda:0")
    out = capsys.readouterr().out
    assert "outcome=retry" in out and "outcome=fail" in out


@pytest.mark.parametrize("exc", [ValueError("bad crop"), MemoryError()])
def test_other_errors_are_not_retried(runner, exc):
    calls = []

    def run():
        calls.append(1)
        raise exc

    with pytest.raises(type(exc)):
        runner.call_with_oom_retry(run, "cuda:0")
    assert len(calls) == 1


def test_oom_on_the_processor_path_is_not_retried(runner):
    """На процесорі «повтор після піку сусіда» нічого не означає."""
    calls = []

    def run():
        calls.append(1)
        raise _oom()

    with pytest.raises(torch.cuda.OutOfMemoryError):
        runner.call_with_oom_retry(run, "cpu")
    assert len(calls) == 1


class _FakeTok:
    def decode(self, probs):
        n = probs.shape[0]
        ids = probs.argmax(-1)[:, 0].tolist()
        return [f"r{i}" for i in ids], [probs[k, 0] for k in range(n)]


class _FakePysar(torch.nn.Module):
    """Віддає «рядок N» для тензора зі значенням N; падає OOM на пачці > limit."""

    def __init__(self, limit: int):
        super().__init__()
        self.w = torch.nn.Parameter(torch.zeros(1))
        self.limit = limit
        self.sizes: list[int] = []
        self.tokenizer = _FakeTok()

    def forward(self, x):
        self.sizes.append(x.shape[0])
        if x.shape[0] > self.limit:
            raise _oom()
        idx = x.reshape(x.shape[0], -1)[:, 0].long()
        out = torch.zeros(x.shape[0], 1, 64)
        out[torch.arange(x.shape[0]), 0, idx] = 10.0
        return out


def test_pysar_batch_splits_in_half_on_oom_and_keeps_the_order(runner, capsys):
    tensors = [torch.full((3, 2, 2), float(i)) for i in range(11)]
    model = _FakePysar(limit=3)
    got = runner._parseq_decode(model, tensors, "cpu", batch=8)
    assert [t for t, _ in got] == [f"r{i}" for i in range(11)]
    assert max(s for s in model.sizes if s <= model.limit) <= 3
    assert "stage=recog_pysar" in capsys.readouterr().out


def test_pysar_oom_on_a_single_line_goes_up_to_the_page_retry(runner):
    model = _FakePysar(limit=0)
    with pytest.raises(torch.cuda.OutOfMemoryError):
        runner._parseq_decode(model, [torch.zeros(3, 2, 2)], "cpu", batch=4)


@pytest.fixture
def fake_card(runner, monkeypatch):
    """Лічильники пам'яті torch без карти: пік задає сам тест."""
    peak = {"b": 0}
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda *a, **k: None)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda *a, **k: peak["b"])
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda *a, **k: peak["b"])
    monkeypatch.setattr(torch.cuda, "memory_reserved", lambda *a, **k: peak["b"])
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    runner._VRAM_DEVICE[0] = "cuda:0"
    return peak


def test_stage_peak_is_recorded_per_stage(runner, fake_card):
    def seg():
        fake_card["b"] = 2100 * 2**20
        return "seg"

    def rec():
        fake_card["b"] = 900 * 2**20
        return "rec"

    runner._vram_stage(seg, "seg_net")()
    runner._vram_stage(rec, "recog_pp")()
    assert {k: v for k, v in runner.STAGE_VRAM.items() if "_resv" not in k} == {
        "seg_net": 2100, "recog_pp": 900}
    # утримане в кеші після етапу — окремим полем: це те, що бачить nvidia-smi
    assert runner.STAGE_VRAM["seg_net_resv"] == 2100
    # пік сторінки — найбільший з етапів, хоч кожен етап скидав лічильник
    assert runner.page_memory("cuda:0")["vram_peak_mb"] == 2100
    assert runner.page_memory("cuda:0")["vram_stages"]["recog_pp"] == 900


def test_stage_retry_repeats_a_peak_once_and_names_the_stage(runner, fake_card, capsys):
    calls = []

    def seg():
        calls.append(1)
        if len(calls) == 1:
            raise _oom()
        return "seg"

    assert runner._vram_stage(seg, "seg_net", retry=True)() == "seg"
    assert len(calls) == 2
    assert "stage=seg_net" in capsys.readouterr().out


def test_stage_without_retry_passes_the_oom_up_with_its_name(runner, fake_card):
    def rec():
        raise _oom()

    with pytest.raises(torch.cuda.OutOfMemoryError) as ei:
        runner._vram_stage(rec, "recog_pp")()
    assert runner._oom_stage(ei.value) == "recog_pp"


def test_stage_is_transparent_without_a_card(runner):
    runner._VRAM_DEVICE[0] = ""
    calls = []

    def seg():
        calls.append(1)
        raise _oom()

    with pytest.raises(torch.cuda.OutOfMemoryError):
        runner._vram_stage(seg, "seg_net", retry=True)()
    assert len(calls) == 1


def test_the_cache_is_released_after_every_card_stage(runner, fake_card, monkeypatch):
    """Звільнене етапом не має висіти в кеші процесу до кінця сторінки."""
    calls = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: calls.append(1))
    runner._vram_stage(lambda: None, "recog_pp")()
    assert calls, "кеш після етапу не віддано"
    calls.clear()
    runner._EMPTY_AFTER_STAGE[0] = False          # --keep-cache
    runner._vram_stage(lambda: None, "recog_pp")()
    assert not calls
