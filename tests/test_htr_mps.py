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


# ── доведеність прив'язана до версії torch ────────────────────────────────────

def test_proven_devices_follow_the_torch_version() -> None:
    """🔴 Ядра MPS — частина збірки torch: доведене на 2.14 на 2.15 не переноситься."""
    table = {"mps": ("2.14",)}
    assert R.proven_devices("2.14.0", table) == frozenset({"mps"})
    assert R.proven_devices("2.14.1+cpu", table) == frozenset({"mps"})
    assert R.proven_devices("2.15.0", table) == frozenset()
    assert R.proven_devices("", table) == frozenset()


def test_runner_sets_the_proven_devices_before_choosing_one() -> None:
    """Доведеність рахується з torch ЦЬОГО процесу — до вибору пристрою, бо
    `auto` і ключ кешу читають саме її."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    sets = src.index('globals()["SEG_DEVICE_PROVEN"] = proven_devices(')
    assert sets < src.index("device, why = resolve_device(", sets)


def test_mps_segmentation_says_where_it_was_made() -> None:
    """Доведений MPS ділить ключ із процесором, тож пристрій лишається поза ключем."""
    assert R._made_by("mps")["device"] == "mps"
    assert R._made_by("cuda:1")["device"] == "cuda"
    assert "device" not in R._made_by()


# ── доктор на Mac ─────────────────────────────────────────────────────────────

def _doctor_on_mac(monkeypatch: pytest.MonkeyPatch, torch_v: str, proven: tuple[str, ...],
                   env: str = "") -> object:
    from nyshporka.htr.env import EnvReport
    from nyshporka.setup import doctor

    monkeypatch.setattr(doctor, "_engine_report",
                        lambda: EnvReport(ok=True, python=Path("py"), torch=torch_v,
                                          cuda=False, mps=True))
    from nyshporka.htr import gpu

    monkeypatch.setattr(gpu, "SEG_DEVICE_PROVEN_ON", {"mps": proven} if proven else {})
    if env:
        monkeypatch.setenv(R.DEVICE_ENV, env)
    else:
        monkeypatch.delenv(R.DEVICE_ENV, raising=False)
    return doctor._torch()


def test_doctor_does_not_call_an_apple_mac_cardless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Доти рядок казав «CUDA недоступна · карти драйвер не показує» — на машині,
    де карта є в самому чипі."""
    got = _doctor_on_mac(monkeypatch, "2.14.0", ("2.14",))
    assert got.level == "ok" and "MPS" in got.detail  # type: ignore[attr-defined]
    assert "CUDA" not in got.detail  # type: ignore[attr-defined]


def test_doctor_says_when_the_card_is_there_but_unproven(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _doctor_on_mac(monkeypatch, "2.15.0", ("2.14",))
    assert got.level == "warn" and "процесор" in got.detail  # type: ignore[attr-defined]
    assert f"{R.DEVICE_ENV}=mps" in got.fix  # type: ignore[attr-defined]
    chosen = _doctor_on_mac(monkeypatch, "2.15.0", ("2.14",), env="mps")
    assert chosen.level == "ok" and "окремо" in chosen.detail  # type: ignore[attr-defined]


def test_doctor_names_a_machine_pinned_to_the_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _doctor_on_mac(monkeypatch, "2.14.0", ("2.14",), env="cpu")
    assert got.level == "warn" and f"{R.DEVICE_ENV}=cpu" in got.detail  # type: ignore[attr-defined]


def test_the_app_mirror_matches_the_runner() -> None:
    """Застосунок не імпортує раннер (той при імпорті міняє ліміти потоків
    процесу), тож тримає копію — і копія не сміє розійтись мовчки."""
    from nyshporka.htr import gpu

    assert gpu.DEVICE_ENV == R.DEVICE_ENV
    assert gpu.SEG_DEVICE_PROVEN_ON == R.SEG_DEVICE_PROVEN_ON
    for v in ("2.13.1", "2.14.0", "2.14.2+cpu", "2.15.0", ""):
        assert gpu.proven_devices(v) == R.proven_devices(v)


def test_doctor_does_not_import_the_runner() -> None:
    src = (ROOT / "src" / "nyshporka" / "setup" / "doctor.py").read_text(encoding="utf-8")
    assert "htr.runner import" not in src and "htr import runner" not in src


def test_proven_mps_is_chosen_by_auto_on_torch_214() -> None:
    """Звірка 17.11.2026 (24 сегментації, 3921 рядок тотожні) — MPS доведений для
    torch 2.14, тож на Apple Silicon `auto` читає картою."""
    proven = R.proven_devices("2.14.0")
    assert "mps" in proven
    assert R.resolve_device("auto", cuda_ok=False, mps_ok=True, proven=proven)[0] == "mps"
    assert R.resolve_device("auto", cuda_ok=True, mps_ok=True, proven=proven)[0] == "cuda:0"


def test_proven_mps_shares_the_cache_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Доведена сегментація ділить ключ із процесорною: справа, сегментована на
    Mac, не сегментується вдруге на машині з карткою NVIDIA — і навпаки."""
    monkeypatch.setattr(R, "SEG_DEVICE_PROVEN", R.proven_devices("2.14.0"))
    assert _key("mps") == _key("cpu")
    monkeypatch.setattr(R, "SEG_DEVICE_PROVEN", R.proven_devices("2.15.0"))
    assert _key("mps") == {**_key("cpu"), "device": "mps"}
