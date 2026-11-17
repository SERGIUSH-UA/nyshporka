"""Читання на карті Apple (MPS): вибір пристрою, окремий ключ кешу, PP без стелі.

Звірка 17.11.2026 (Apple M5 Pro, 3 кадри метричної книги 1882 р., Писар v31 +
Дяк v16 голосом): сегментація MPS і процесора побайтово та сама, тексти обох
голосів 376/376 рядків тотожні; 8.6 с/стор проти 65.3 на процесорі. Тотожність
трималась на двох правках, і кожна тут має приймач: PP-модель читає пачками
тієї самої розкладки, що й на процесорі, а злиття BN не падає на float64.
"""
from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from nyshporka.htr import runner as R

ROOT = Path(__file__).resolve().parents[1]
RUNNER_SRC = ROOT / "src" / "nyshporka" / "htr" / "runner.py"


# ── вибір пристрою ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("req", "cuda", "mps", "proven", "want"), [
    # auto: карта NVIDIA першою — як було й доти
    ("auto", True, True, frozenset({"mps"}), "cuda:0"),
    ("", True, False, frozenset(), "cuda:0"),
    # 🔴 MPS доступний, але не доведений — auto його НЕ бере
    ("auto", False, True, frozenset(), "cpu"),
    ("auto", False, True, frozenset({"mps"}), "mps"),
    ("auto", False, False, frozenset({"mps"}), "cpu"),
    # явно названий — береться, коли є
    ("mps", False, True, frozenset(), "mps"),
    ("cuda:1", True, False, frozenset(), "cuda:1"),
    ("cpu", True, True, frozenset({"mps"}), "cpu"),
    ("MPS", False, True, frozenset(), "mps"),
])
def test_resolve_device(req: str, cuda: bool, mps: bool, proven: frozenset[str],
                        want: str) -> None:
    got, _why = R.resolve_device(req, cuda_ok=cuda, mps_ok=mps, proven=proven)
    assert got == want


@pytest.mark.parametrize(("req", "word"), [("cuda:0", "CUDA"), ("mps", "MPS")])
def test_missing_device_falls_back_to_cpu_and_says_why(req: str, word: str) -> None:
    """Прогін, що відмовився стартувати, гірший за повільний — але мовчки
    підмінений пристрій теж не годиться: причина мусить бути в лозі."""
    got, why = R.resolve_device(req, cuda_ok=False, mps_ok=False)
    assert got == "cpu" and word in why


def test_unknown_device_is_refused() -> None:
    with pytest.raises(ValueError, match="невідомий пристрій"):
        R.resolve_device("gpu", cuda_ok=True, mps_ok=True)


def test_mps_is_not_proven_until_the_lineage_check_says_so() -> None:
    """Доки тотожності сегментації не доведено на справжніх кадрах, MPS лише
    за явним вибором — `auto` його не бере, а кеш ділиться за ключем."""
    if "mps" not in R.SEG_DEVICE_PROVEN:
        assert R.resolve_device("auto", cuda_ok=False, mps_ok=True)[0] == "cpu"


def test_device_default_comes_from_the_machine_env() -> None:
    """Пристрій машини — змінна, яку бачать усі обличчя й черга, а не прапорець
    одного з них."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    assert re.search(r'"--device", default=os\.environ\.get\(DEVICE_ENV\) or "auto"', src)
    assert R.DEVICE_ENV == "NYSH_HTR_DEVICE"


def test_mps_available_survives_old_and_broken_torch() -> None:
    assert R.mps_available(types.SimpleNamespace()) is False
    ok = types.SimpleNamespace(backends=types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True)))
    assert R.mps_available(ok) is True

    def boom() -> bool:
        raise RuntimeError("metal")

    bad = types.SimpleNamespace(backends=types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=boom)))
    assert R.mps_available(bad) is False


def test_on_accelerator() -> None:
    assert R.on_accelerator("cuda:0") and R.on_accelerator("mps")
    assert not R.on_accelerator("cpu")


# ── кеш сегментації ───────────────────────────────────────────────────────────

def _key(device: str) -> dict:
    seg = R.Segmenter("blla.mlmodel", device, key={"sato": "1,3", "kraken": "7.0.2",
                                                    "max_endpoints": 400})
    return seg._full_key()


def test_cuda_and_cpu_cache_keys_are_untouched() -> None:
    """🔴 Понад сто тисяч записів кешу: поле пристрою в ключі CUDA чи процесора
    знецінило б їх усі. Тож для них ключ байт у байт той самий, що й доти."""
    assert "device" not in _key("cuda:0")
    assert "device" not in _key("cpu")
    assert _key("cuda:0") == _key("cpu")


def test_unproven_mps_segmentation_lives_under_its_own_key() -> None:
    if "mps" in R.SEG_DEVICE_PROVEN:
        assert _key("mps") == _key("cpu")
    else:
        assert _key("mps") == {**_key("cpu"), "device": "mps"}


# ── поетапний час і назва машини ──────────────────────────────────────────────

def test_stages_say_card_on_mps() -> None:
    total = {"segment": 2.0, "seg_net": 1.0, "sato": 0.2, "polygon": 0.6,
             "recognize": 4.0, "other": 0.1}
    s = R.stages_summary(total, 1, "mps", gpu_sato=True)
    assert "мережа 1.0 с · карта" in s and "sato 0.2 с · карта" in s
    assert "розпізнавання 4.0 с · карта" in s


def test_machine_label_names_the_apple_card() -> None:
    assert "MPS" in R.machine_label("mps")


# ── PP-модель на MPS ──────────────────────────────────────────────────────────

def _pp_mps_branch() -> str:
    src = RUNNER_SRC.read_text(encoding="utf-8")
    start = src.index('    elif device == "mps":', src.index("def load_pp("))
    return src[start:src.index("    else:", start)]


def test_pp_on_mps_uses_the_mps_accelerator() -> None:
    assert 'accelerator="mps"' in _pp_mps_branch()


def test_pp_on_mps_batches_like_the_cpu() -> None:
    """🔴 PP-модель не інваріантна до пачки (41 зі 120 рядків збіглись між
    «пачками» й «по одному»). Стеля пікселів на MPS склала б пачки інакше, ніж
    процесор, — і 72 з 376 рядків голосу розійшлись. Тому стелі тут немає."""
    branch = _pp_mps_branch()
    assert "budget_px =" not in branch
    assert "recommended_max_memory" not in branch.split("cfg =")[-1]


def test_clahe_stays_off_mps() -> None:
    """Рівність до біта тримається на float64, якого MPS не має: 16 відступів на
    8 кадрах і повільніше за skimage. Тож MPS не серед доведених."""
    import sys

    sys.path.insert(0, str(ROOT / "src" / "nyshporka" / "htr" / "patches"))
    try:
        import fast_clahe
    finally:
        sys.path.pop(0)
    assert fast_clahe.proven("cuda:0") and fast_clahe.proven("cuda:1")
    assert not fast_clahe.proven("mps") and not fast_clahe.proven("cpu")


def test_pp_fuse_does_not_ask_mps_for_float64() -> None:
    """Злиття BN рахує ваги у float64; на MPS його немає, і злиття падало, тож Дяк
    ішов удвічі повільніше (30.5 проти 15.2 мс/рядок)."""
    src = (ROOT / "src" / "nyshporka" / "htr" / "patches" / "pp_fuse.py").read_text(
        encoding="utf-8")
    body = src[src.index("def _fold("):]
    assert ".double()" not in body, "float64 на пристрої моделі — на MPS це TypeError"
    assert 't.device.type == "mps"' in src
