"""Половинна точність на сегментації — ручка, і вона не сміє знецінити кеш.

Kraken приймає `blla.segment(autocast=…)`, а ми досі передавали лише модель і
пристрій, тобто рахували все у 32 бітах. Сегментація — 48% ціни сторінки
(замір 05.09.2026 на 148 рядках), тож ручка б'є саме туди.

🔴 Головна небезпека тут не швидкість, а КЕШ. Половинна точність дає інший
форвард, отже іншу нарізку, отже свій ключ. Але дописати ключ безумовно
означало б промазати повз усі наявні записи — а їх понад сто тисяч, і кожна
справа перечитувалась би з нуля. Тому ключ дописується ЛИШЕ коли ручку
ввімкнено, і саме це тут перевіряється.

## Замір 05.09.2026 (Tesla V100, 8 сторінок медіанної щільності, 944 рядки)

| варіант | с/стор |
|---|---|
| базовий | 8.20 |
| autocast | 8.15 |
| базовий, повтор | 8.15 |

Приросту **немає**: −0.6% при розкиді між повторами 0.6%. Зате текст поїхав —
`autocast` збігся з базовим лише на 2 сторінках із 9, тимчасом як два базові
прогони збіглися **9 з 9** (тобто конвеєр детермінований, і різниця саме від
ручки). Нуль виграшу за ненульову зміну нарізки.

🔑 Побічний висновок, важливіший за саму ручку: якщо половинна точність на
форварді нічого не змінює, то всередині сегментації дорога не карта, а
ПРОЦЕСОРНА векторизація. Отже шукати треба там — `--seg-height`,
`num_line_workers` нового API.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from nyshporka.htr.runner import Segmenter

RUNNER_SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "htr" / "runner.py"


def _key(**kwargs) -> dict:
    seg = Segmenter("model.mlmodel", "cuda:0",
                    key={"sato": "1,3", "kraken": "7.0.2", "max_endpoints": 400},
                    **kwargs)
    return seg._full_key()


def test_off_by_default_and_key_unchanged() -> None:
    """🔴 Приймач від знецінення кешу: з вимкненою ручкою ключ мусить лишитись
    БУКВАЛЬНО таким, яким був до її появи."""
    assert inspect.signature(Segmenter.__init__).parameters["autocast"].default is False
    key = _key()
    assert "autocast" not in key, (
        "ключ змінився при вимкненій ручці — усі наявні записи кешу промажуть")
    assert set(key) == {"sato", "kraken", "max_endpoints", "seg_height", "v"}


def test_on_gets_its_own_key() -> None:
    """Інший форвард — інший запис. Інакше теплий кеш підсунув би 32-бітну
    нарізку під виглядом половинної, і замір порівнював би сам себе."""
    assert _key(autocast=True)["autocast"] is True
    assert _key()["seg_height"] == _key(autocast=True)["seg_height"]


def test_flag_reaches_the_segmenter() -> None:
    """Ручка мусить доходити від командного рядка до виклику kraken. Обрив у
    середині виглядав би як «приросту немає» — тобто як відповідь на дослід."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    assert '"--seg-autocast"' in src, "немає прапорця"
    assert "autocast=args.seg_autocast" in src, "прапорець не доходить до Segmenter"
    assert "autocast=self._autocast" in src, "Segmenter не передає autocast у blla"
