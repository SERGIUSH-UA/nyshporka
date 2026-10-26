"""✍ Письмо моделі за іменем файлу (`runner.model_script`).

Мета прогону несе `script`, і від нього залежать журнал знаменника пошуку
(«латинський голос прошукано») та позначка голосу в пулі. Спеціалісти на
PP-OCRv6 письма в імені не мають; без явного рядка вони падали в запасне
«ppocr → латинка», і кириличний Логофет ішов латинкою (371 прогін у
Майстерні, 27.10.2026).
"""
from __future__ import annotations

import pytest

from nyshporka.htr.runner import model_script


@pytest.mark.parametrize("model, engine, script", [
    ("logofet_ro_v10.safetensors", "ppocr", "cyrillic"),
    ("regent_v4.safetensors", "ppocr", "cyrillic"),
    ("diak_cyr_v10.safetensors", "ppocr", "cyrillic"),
    ("pysar_cyr_v28.pt", "parseq", "cyrillic"),
    ("pysar_x18_v1.pt", "parseq", "cyrillic"),
    ("skryba_pp_v3.safetensors", "ppocr", "latin"),
    ("skryba_f792_v6.mlmodel", "kraken", "latin"),
])
def test_known_models(model: str, engine: str, script: str) -> None:
    assert model_script(model, engine) == script


def test_unknown_ppocr_model_still_falls_back_to_latin() -> None:
    """Запасне правило лишається для чужих моделей без відомого префікса."""
    assert model_script("someone_else.safetensors", "ppocr") == "latin"
