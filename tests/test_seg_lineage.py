"""Родовід сегментації: кеш переживає оновлення kraken — але лише доведене.

Ключ кешу сегментації несе версію kraken, бо інша версія може дати інші
полігони, тобто інший текст без жодної помилки. Але сира версія в ключі
знецінювала б увесь кеш (понад сто тисяч кадрів) при КОЖНОМУ оновленні, навіть
коли сегментація не змінилась. Тому в ключ іде родовід: найстаріша версія з
побайтово тією самою сегментацією, доведеною `kraken_lineage_verify`.

Тут — три обіцянки: старий запис влучає під новою версією; невідома версія
не влучає ні в що чуже; і планувальник хмари судить кеш так само, як раннер.
"""
from __future__ import annotations

from pathlib import Path

from nyshporka.htr import runner as R
from nyshporka.htr import seg as S

RUNNER_SRC = Path(R.__file__).read_text(encoding="utf-8")


def _key(kraken: str) -> dict:
    seg = R.Segmenter("model.mlmodel", "cuda:0",
                      key={"sato": "1,3", "kraken": kraken, "max_endpoints": 400})
    return seg._full_key()


def test_7_1_1_reads_the_cache_of_7_0_2() -> None:
    """🔴 Головне: оновлення на 7.1.1 не пересегментовує жодної справи."""
    assert R.SEG_LINEAGE["7.1.1"] == "7.0.2"
    assert _key(R.SEG_LINEAGE.get("7.1.1", "7.1.1")) == _key("7.0.2")


def test_unknown_version_is_its_own_lineage() -> None:
    """Неперевірена версія — свій ключ: промах кешу безпечний, хибне влучання — ні."""
    assert R.SEG_LINEAGE.get("7.9.9", "7.9.9") == "7.9.9"
    assert _key("7.9.9") != _key("7.0.2")


def test_runner_writes_the_lineage_not_the_raw_version() -> None:
    """Запис нової версії влучає і в раннер старої (бокс зі старим наглядачем)."""
    assert 'key={"sato": args.sato_sigmas, "kraken": SEG_KRAKEN,' in RUNNER_SRC
    # справжня версія — поза ключем, для слідства
    assert '"made_by": _made_by()' in RUNNER_SRC


def test_planner_judges_the_cache_like_the_runner() -> None:
    """🔴 Доти планувальник версію kraken не звіряв: кеш іншої версії він
    називав придатним, раннер на ньому промахувався, і кошторис мовчав про
    пересегментацію."""
    supported = {R.SEG_LINEAGE.get(v, v) for v in R.SUPPORTED_KRAKEN}
    assert set(S.EXPECTED_LINEAGE) == supported


def test_planner_rejects_a_cache_of_an_unproven_version(tmp_path: Path) -> None:
    import gzip
    import json

    def blob(name: str, kraken: str) -> Path:
        f = tmp_path / name
        key = {"sato": "1,3", "kraken": kraken, "max_endpoints": 400, "ceiling": 400,
               "seg_height": 0, "v": 1, "enhanced": ""}
        with gzip.open(f, "wt", encoding="utf-8") as fh:
            json.dump({"key": key, "seg": {}}, fh)
        return f

    assert S.key_problem([blob("0001.o0.c400.seg.json.gz", "7.0.2")]) == ""
    bad = S.key_problem([blob("0002.o0.c400.seg.json.gz", "7.9.9")])
    assert "kraken" in bad and "7.9.9" in bad


def test_runner_refuses_an_unsupported_kraken() -> None:
    """Жорсткий перехід: на непідтримуваній версії раннер не стартує й називає
    команду, яка лагодить. Звірка родоводу обходить це явним прапорцем."""
    assert R.SUPPORTED_KRAKEN == ("7.1.1",)
    assert "nysh htr install" in RUNNER_SRC
    assert '"--allow-any-kraken"' in RUNNER_SRC


# ── PP-OCRv6: полотно з кропів ───────────────────────────────────────────────
class _Crop:
    def __init__(self, w: int, h: int) -> None:
        self.width, self.height = w, h

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


def test_pp_groups_keep_every_crop_once_and_respect_every_cap(monkeypatch) -> None:
    """Кожен кроп — рівно в одній пачці, у порядку сортування; пачка не
    перевищує ні стелі рядків, ні бюджету пам'яті (рядків × найширший у
    масштабі моделі), ні стелі полотна — крім рядка, що сам більший за межу."""
    monkeypatch.setattr(R, "PP_CANVAS_MPX", 0.01)          # полотно ≤ 10 000 px
    monkeypatch.setattr(R, "PP_BATCH", 3)
    crops = [_Crop(w, 10) for w in (50, 300, 120, 80, 999, 200, 60, 70, 90)]
    height, budget = 10, 400.0                               # масштаб 1:1
    order = sorted(range(len(crops)), key=lambda i: crops[i].width)
    groups = R._pp_groups(crops, order, height, budget)
    assert [i for g in groups for i in g] == order, "кроп загубився або перемішався"
    for g in groups:
        wmax = max(crops[i].width for i in g)
        assert len(g) <= 3
        if len(g) > 1:
            assert wmax * len(g) <= budget, (g, "бюджет пам'яті")
            assert wmax * sum(crops[i].height for i in g) <= 10_000, (g, "полотно")


def test_pp_budget_bounds_the_widest_batch() -> None:
    """🔴 Бюджет VRAM, а не лише число рядків: пачка 16 найширших рядків
    коштувала +1.57 ГБ, і на 4 ГБ прохід сповзав у спільну пам'ять Windows."""
    crops = [_Crop(1200, 70) for _ in range(16)]
    budget = 800 / R.PP_MB_PER_KPX * 1000                  # 800 МБ
    groups = R._pp_groups(crops, list(range(16)), 96, budget)
    per = 1200 * 96 / 70
    assert all(len(g) * per * R.PP_MB_PER_KPX / 1000 <= 800 for g in groups)
    assert len(groups) > 1


def test_pp_voice_is_wired_like_the_kraken_voice() -> None:
    """Голос PP вирівнюється по масці основного тексту так само, як Дяк v4, —
    інакше тека голосу з'їхала б відносно рамок `.lines.json` мовчки."""
    assert 'elif eengine == "ppocr":' in RUNNER_SRC
    assert "pp_decode_crops(erec, crops)" in RUNNER_SRC
    assert R._ENGINE_BY_SUFFIX[".safetensors"] == "ppocr"
    assert R._META_ENGINE["ppocr"] == "kraken", "мета мусить казати рушій, який знає стор"
    assert "num_line_workers=0" in RUNNER_SRC


class _Half:
    """Підроблений `pp_fp16`: облік викликів, або збій."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enabled = 0

    def enable_fp16(self, rec):  # type: ignore[no-untyped-def]
        if self.fail:
            raise RuntimeError("cuDNN впав")
        self.enabled += 1
        return rec


def test_pp_reads_fp32_unless_asked(monkeypatch) -> None:
    """🔴 fp16 на справжніх сторінках у 5.5 раза повільніший (V100: 19.8 проти
    3.6 с/стор на розпізнавання) — кожна нова ширина рядка коштує вибору ядер.
    Тож дефолт — fp32, а латка кличеться лише з `--pp-precision fp16`."""
    assert R.PP_PRECISION == "fp32"
    assert 'if device.startswith("cuda") and PP_PRECISION == "fp16":' in RUNNER_SRC
    assert '"--pp-precision", choices=("fp32", "fp16")' in RUNNER_SRC
    assert "calibrate" not in RUNNER_SRC, "калібрування на одній пачці бреше — його немає"


def test_fp16_on_request_and_failure_reads_fp32(monkeypatch, capsys) -> None:
    import sys

    half = _Half()
    monkeypatch.setitem(sys.modules, "pp_fp16", half)
    R._pp_half(object())
    assert half.enabled == 1
    monkeypatch.setitem(sys.modules, "pp_fp16", _Half(fail=True))
    R._pp_half(object())                       # не падає: прискорювач, не умова
    assert "читаю у fp32" in capsys.readouterr().out


def test_torch_native_triton_ops_are_off_before_torch_loads(monkeypatch) -> None:
    """🔴 torch 2.14 на Linux підміняє `bmm` зовнішнього добутку власним
    triton-ядром, а triton без gcc не збирає свій C-модуль: падала КОЖНА
    сторінка (Vast V100, 04.10.2026). Вимикач читається при реєстрації
    операцій, тож стоїть до першого `import torch` — і в раннері, і в Писарі,
    і в оточенні кожного підпроцесу рушіїв."""
    import re

    from nyshporka.htr import env

    switch = 'os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")'
    for name in ("runner.py", "pysar_lines_infer.py"):
        src = (Path(R.__file__).parent / name).read_text(encoding="utf-8")
        assert switch in src, name
        first = re.search(r"^\s*(import torch|from torch)", src, re.M)
        assert first and src.index(switch) < first.start(), f"{name}: вимикач після torch"
    monkeypatch.delenv("TORCH_DISABLE_NATIVE_JIT", raising=False)
    assert env.foreign_env()["TORCH_DISABLE_NATIVE_JIT"] == "1"
    monkeypatch.setenv("TORCH_DISABLE_NATIVE_JIT", "0")
    assert env.foreign_env()["TORCH_DISABLE_NATIVE_JIT"] == "0", "явне рішення — сильніше"


def test_pp_batch_budget_is_per_shard_not_a_share_of_the_card() -> None:
    """🔴 Частка карти множилась на число шардів: 20% на кожен — і на V100 16 ГБ
    шард із двома PP-голосами тримав 3.4 ГБ, а регулятор садив менше шардів.
    Стала 768 МБ: 4 шарди разом 7561 → 6535 МБ, швидкість та сама."""
    assert 256 <= R.PP_VRAM_MB <= 1024
    assert "PP_VRAM_SHARE" not in RUNNER_SRC
