"""Голоси за PP-основою: Регент (`regent_v4.safetensors`) + Скриба PPv4 одним проходом.

11.11.2026, дослідник: «у них же однакова основа». Регент і Скриба PPv4 — обидва
PP-OCRv6 і ріжуть ті самі кропи (`_line_crops`), а хмара доти вимагала двох
заходів: двічі заливка кадрів, двічі сегментація, дві оренди.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── розв'язування голосів ─────────────────────────────────────────────────────
def test_pp_main_takes_a_pp_voice(tmp_path: Path, monkeypatch) -> None:
    from nyshporka.htr import run as R

    main = tmp_path / "regent_v4.safetensors"
    skryba = tmp_path / "skryba_pp_v4.safetensors"
    monkeypatch.setattr(R, "pick_model", lambda s, **_: (skryba, None))
    assert R.resolve_voices(["latin"], main=main) == (skryba,)


def test_pp_main_takes_a_kraken_voice(tmp_path: Path, monkeypatch) -> None:
    from nyshporka.htr import run as R

    main = tmp_path / "regent_v4.safetensors"
    diak = tmp_path / "diak_cyr_v4.mlmodel"
    monkeypatch.setattr(R, "resolve_model", lambda s: (diak, "cyrillic"))
    assert R.resolve_voices(["diak_cyr_v4.mlmodel"], main=main) == (diak,)


def test_pp_main_refuses_a_parseq_voice(tmp_path: Path, monkeypatch) -> None:
    """PP-гілка раннера PARSeq-голосу не тримає — відмова до оренди, а не на машині."""
    from nyshporka.htr import run as R

    pysar = tmp_path / "pysar_cyr_v29.pt"
    monkeypatch.setattr(R, "pick_model", lambda s, **_: (pysar, None))
    with pytest.raises(R.ReadError, match="PARSeq"):
        R.resolve_voices(["cyrillic"], main=tmp_path / "regent_v4.safetensors")


def test_classic_kraken_main_still_refuses(tmp_path: Path) -> None:
    from nyshporka.htr.run import ReadError, resolve_voices

    with pytest.raises(ReadError, match="mlmodel"):
        resolve_voices(["latin"], main=tmp_path / "skryba_f792_v6.mlmodel")


# ── раннер: голос за PP-основою вирівняний по масці основного тексту ─────────
class _Seg:
    def segment(self, im, stem, orient, enhanced):
        return object()


def _wire_pp(monkeypatch, main_reads: list[str], voice_reads: list[str]):
    from nyshporka.htr import runner as RN

    crops = [f"crop{i}" for i in range(len(main_reads))]

    def fake_line_crops(im, seg):
        fake_line_crops.boxes = [[i, 0, i + 1, 1] for i in range(len(crops))]
        fake_line_crops.polys = [None] * len(crops)
        return list(crops)

    monkeypatch.setattr(RN, "_line_crops", fake_line_crops)
    monkeypatch.setattr(RN, "_note_line_extent", lambda c: None)
    monkeypatch.setattr(RN, "pp_read_crops",
                        lambda pp, cs: [(t, 0.9) for t in main_reads])
    monkeypatch.setattr(RN, "pp_decode_crops", lambda pp, cs: list(voice_reads))
    return RN


class _Im:
    width, height = 100, 50


def test_pp_voice_is_aligned_with_the_main_text(monkeypatch) -> None:
    """Основна модель замовчала на рядку 1 — рядок 1 голосу випадає разом із ним,
    і рядок N теки голосу лишається рядком N основної теки (і рамкою N)."""
    RN = _wire_pp(monkeypatch, ["а", "", "в"], ["A", "B", "C"])
    rec = (("net", {"cfg": 1}, 0), [("skryba_pp_v4", "ppocr", "voice")], 1)
    lines, _ = RN.ocr_page_pp(_Im(), _Seg(), rec)
    assert lines == ["а", "в"]
    assert RN.ocr_page_parseq.side == {"skryba_pp_v4": ["A", "C"]}
    assert RN.ocr_page_parseq.side_lost == {"skryba_pp_v4": 1}, \
        "рядок, який прочитав лише голос, рахується, а не губиться мовчки"


def test_pp_without_voices_leaves_no_stale_side(monkeypatch) -> None:
    """Голоси попередньої сторінки не переходять на сторінку без ансамблю."""
    RN = _wire_pp(monkeypatch, ["а"], [])
    RN.ocr_page_parseq.side = {"skryba_pp_v4": ["старе"]}
    RN.ocr_page_pp(_Im(), _Seg(), ("net", {"cfg": 1}, 0))
    assert RN.ocr_page_parseq.side == {}


def test_geom_snapshot_carries_the_voices_of_that_reading(monkeypatch) -> None:
    """Голоси знімаються разом із рамками того повороту, що переміг: гард
    орієнтації може прочитати ще один поворот уже після переможця."""
    from nyshporka.htr import runner as RN

    monkeypatch.setattr(RN.ocr_page_parseq, "side", {"v": ["x"]}, raising=False)
    monkeypatch.setattr(RN.ocr_page_parseq, "side_lost", {}, raising=False)
    snap = RN._geom_of("ppocr")
    RN.ocr_page_parseq.side = {"v": ["інший поворот"]}
    assert snap["side"] == {"v": ["x"]}
    assert RN._geom_of("kraken")["side"] == {}
