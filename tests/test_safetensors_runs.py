"""Прогін моделлю PP-OCRv6 (`.safetensors`) має рушій, як і будь-який інший.

Мета старих прогонів поля `engine` не несе, і рушій там вгадується з
розширення моделі. Розширення, якого ці місця не знають, лишає прогін «без
рушія»: без бейджа, без покриття письма, без гарда змішування теки.
"""
from __future__ import annotations

import pytest

from nyshporka import htr_store
from nyshporka.cases import collect


@pytest.mark.parametrize("model", ["skryba_pp_v3.safetensors", "diak_cyr_v6.safetensors"])
def test_run_engine_knows_safetensors(model: str) -> None:
    assert htr_store.run_engine({"model": model}) == "kraken"


def test_case_registry_knows_safetensors() -> None:
    assert collect._engine_of({"model": "skryba_pp_v3.safetensors"}) == "kraken"


def test_two_voices_still_name_the_main_engine() -> None:
    assert collect._engine_of({"model": "pysar_cyr_v19.pt+diak_v6"}) == "parseq"
