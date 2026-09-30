"""Час сторінки за етапами: де саме він іде і на чому рахується.

🔴 «Карта ледь зайнята» людина читала як «читає процесором», хоча мережа
сегментації, sato й розпізнавання йшли на карті — просто недовго (звіт
користувача 29.09.2026). Без поетапного часу це здогад, а не відповідь.
"""
from __future__ import annotations

import pytest

from nyshporka.htr import runner as R


@pytest.fixture(autouse=True)
def _chysto() -> None:
    R.STAGES.clear()
    yield
    R.STAGES.clear()


def test_etap_rakhuie_chas_i_nakopychuie() -> None:
    f = R._timed(lambda x: x + 1, "sato")
    assert f(1) == 2 and f(2) == 3
    assert R.STAGES["sato"] >= 0.0
    assert list(R.STAGES) == ["sato"]


def test_etap_rakhuie_i_pry_vyniatku() -> None:
    def bad() -> None:
        raise ValueError("x")

    with pytest.raises(ValueError):
        R._timed(bad, "polygon")()
    assert "polygon" in R.STAGES


def test_obhortka_dilyt_atrybuty_z_funktsiieiu() -> None:
    """🔴 `ocr_page` пише собі `boxes`, а `_geom_of` читає їх через обгортку."""
    def inner() -> None:
        inner.boxes = [1]

    wrapped = R._timed(inner, "ocr")
    wrapped()
    assert wrapped.boxes == [1]
    wrapped.polys = [2]
    assert inner.polys == [2]


def test_pokhidni_etapy_storinky() -> None:
    R.STAGES.update({"ocr": 5.0, "segment": 3.0, "seg_net": 1.0, "sato": 1.5})
    got = R.page_stages(sec=6.0)
    assert got["recognize"] == 2.0, "ocr − segment"
    assert got["other"] == 1.0, "сторінка − ocr"
    assert got["sato"] == 1.5


def test_pidsumok_kazhe_de_rakhuietsia() -> None:
    total = {"segment": 6.0, "seg_net": 2.0, "gpu_wait": 1.0, "sato": 2.0,
             "polygon": 1.0, "recognize": 4.0, "other": 2.0}
    s = R.stages_summary(total, 2, "cuda:0", gpu_sato=True)
    assert "сегментація 3.0 с" in s and "чекання карти 0.5 с" in s
    assert "sato 1.0 с · карта" in s and "полігони 0.5 с · процесор" in s
    assert "розпізнавання 2.0 с · карта" in s
    assert "sato 1.0 с · процесор" in R.stages_summary(total, 2, "cuda:0", gpu_sato=False)
    assert R.stages_summary({}, 0, "cpu", gpu_sato=False) == ""


# ── з чим ішов прогін — поруч із замірами ─────────────────────────────────────

def test_konfihuratsiia_prohonu() -> None:
    """Заміри етапів без конфігурації не зіставити між машинами й запусками."""
    import argparse

    args = argparse.Namespace(shard="2/3", batch=32, voice_batch=8, gpu_sato=True)
    got = R.run_config(args, "cuda:0", 3)

    assert (got["shard"], got["shards"], got["batch"], got["voice_batch"]) == ("2/3", 3, 32, 8)
    assert got["device"] == "cuda:0" and got["gpu_sato"] is True
    assert got["cores"] >= 1 and got["cores_seen"] >= got["cores"]


def test_zvedena_meta_sumuie_etapy_shardiv(tmp_path) -> None:
    """🔴 Прогін шардами лишався без замірів: вони жили лише в партах."""
    import json

    for k, (segment, pages) in enumerate(((10.0, 4), (14.5, 6)), 1):
        (tmp_path / f"_htr_meta.part{k}.json").write_text(json.dumps({
            "pages": {f"000{k}.jpg": {}}, "done": True,
            "stages_total": {"segment": segment, "recognize": 1.0},
            "stages_pages": pages,
            "run_config": {"shard": f"{k}/2", "shards": 2, "batch": 32}}),
            encoding="utf-8")

    R.merge_meta(tmp_path, {"model": "m"})

    meta = json.loads((tmp_path / "_htr_meta.json").read_text(encoding="utf-8"))
    assert meta["stages_total"] == {"segment": 24.5, "recognize": 2.0}
    assert meta["stages_pages"] == 10
    assert meta["run_config"]["parts"] == ["1/2", "2/2"] and meta["run_config"]["shards"] == 2

