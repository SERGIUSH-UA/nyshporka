"""Батч kraken-голосу: один битий кроп не сміє знулити кошик.

🔴 Інцидент, проти якого це написано (05.09.2026, план модернізації): гілка
батча в `kraken_decode_crops` при винятку робила `out += [""] * len(chunk)`,
тобто при батчі 32 одна зіпсована стрічка мовчки стирала 32 рядки другого
голосу. На 75-рядковій сторінці це 40% Дяка, і виглядало це як «Дяк тут нічого
не прочитав» — порожній рядок голосу невідрізненний від нерозпізнаного.

Схема винесена в `_decode_in_batches` без torch, тож доводиться тут, де рушіїв
немає. Раннер вантажиться за шляхом — так само, як його запускає наглядач.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location("_runner_voice_batch", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def _fakes(poison: set[int]):
    """`run_batch` падає, якщо в кошику є отруєний елемент; `run_one` падає
    лише на самому отруєному. Обидва рахують виклики."""
    calls = {"batch": [], "one": []}

    def run_batch(chunk):
        calls["batch"].append(list(chunk))
        if any(i in poison for i in chunk):
            raise RuntimeError("битий кроп у кошику")
        return [f"рядок {i}" for i in chunk]

    def run_one(i):
        calls["one"].append(i)
        if i in poison:
            raise RuntimeError("битий кроп")
        return f"рядок {i}"

    return run_batch, run_one, calls


def test_a_poisoned_line_does_not_zero_its_whole_basket(runner) -> None:
    """Один битий кроп → один порожній рядок, а не 32."""
    run_batch, run_one, calls = _fakes({17})
    out = runner._decode_in_batches(list(range(40)), 32, run_batch, run_one)
    assert len(out) == 40
    assert out[17] == ""
    assert sum(1 for x in out if x) == 39, "кошик із битим кропом знулив сусідів"
    assert out[16] == "рядок 16" and out[18] == "рядок 18"
    # фолбек ішов по одному лише для кошика, що впав
    assert sorted(calls["one"]) == list(range(32))


def test_batches_are_sequential_and_the_tail_is_short(runner) -> None:
    """75 рядків батчем 16 = кошики 16,16,16,16,11; порядок — як у вході."""
    run_batch, run_one, calls = _fakes(set())
    out = runner._decode_in_batches(list(range(75)), 16, run_batch, run_one)
    assert out == [f"рядок {i}" for i in range(75)]
    assert [len(c) for c in calls["batch"]] == [16, 16, 16, 16, 11]
    assert calls["one"] == [], "без збоїв фолбек по одному не кличеться"


def test_batch_one_never_calls_run_batch(runner) -> None:
    """`batch=1` — режим звірки з еталоном `rpred`: жодного кошика."""
    run_batch, run_one, calls = _fakes({3})
    out = runner._decode_in_batches(list(range(5)), 1, run_batch, run_one)
    assert calls["batch"] == []
    assert out == ["рядок 0", "рядок 1", "рядок 2", "", "рядок 4"]


def test_a_short_basket_answer_is_a_failure_not_a_shift(runner) -> None:
    """Кошик, що віддав менше рядків, ніж отримав, зсунув би решту сторінки —
    той самий клас тихої вади, що й зсув голосу відносно маски `kept`."""
    def run_batch(chunk):
        return ["лише один"]

    _, run_one, _ = _fakes(set())
    out = runner._decode_in_batches(list(range(6)), 3, run_batch, run_one)
    assert out == [f"рядок {i}" for i in range(6)]


def test_batch_error_hook_runs_before_the_fallback(runner) -> None:
    """Після OOM у кошику фолбек по одному впав би на першому ж кропі —
    гачок (`torch.cuda.empty_cache`) мусить спрацювати ДО нього."""
    order: list[str] = []

    def run_batch(chunk):
        raise MemoryError("OOM")

    def run_one(i):
        order.append(f"one{i}")
        return "x"

    runner._decode_in_batches([1, 2], 2, run_batch, run_one,
                              on_batch_error=lambda: order.append("hook"))
    assert order == ["hook", "one1", "one2"]


def test_voice_batch_lever_reaches_the_runner(tmp_path: Path) -> None:
    """Ручка `--voice-batch` доти існувала лише для прямого виклику раннера:
    `Plan.command` її не передавав, тож із застосунку батч був недосяжний."""
    from nyshporka.htr.run import Plan

    plan = Plan(case_dir=tmp_path / "справа", out_dir=tmp_path / "out",
                model=tmp_path / "m.pt", script="cyrillic", frames=10,
                python=tmp_path / "py.exe", runner=tmp_path / "runner.py")
    cmd = plan.command(voice_batch=16)
    assert cmd[cmd.index("--voice-batch") + 1] == "16"
    for v in (0, 1):
        assert "--voice-batch" not in plan.command(voice_batch=v), (
            "0/1 = дефолт раннера, прапорець не сміє просочуватись")
