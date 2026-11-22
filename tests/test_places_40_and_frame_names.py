"""0.48.1: збірна книга — до 40 сіл; задовге для машини ім'я кадру ловиться до оренди.

🔴 22.11.2026: книга на 27 сіл губила хвіст переліку — клієнт різав `covers` до 20,
а сервер Супряги бере 40. 21–22.11.2026: кадри з кирилицею в іменах (понад 255
байт разом із хвостом кешу сегментації) давали на машині `Errno 36`, і захід
переорендовував машини колом.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from nyshporka.share import card as K
from nyshporka.share.publish import _case_block

SELA = [f"с. Село{i:02d}, Уманський пов." for i in range(27)]


def test_the_card_takes_40_places_and_refuses_41() -> None:
    assert K.normalize(places=[f"с{i}" for i in range(40)])["places"][-1] == "с39"
    with pytest.raises(K.CardError):
        K.normalize(places=[f"с{i}" for i in range(41)])


def test_covers_of_a_27_village_book_all_ride_in_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "_source.json").write_text(
        json.dumps({"shifra": "ДАЧО 1-1-1", "covers": SELA}, ensure_ascii=False),
        encoding="utf-8")
    out = _case_block({"key": "DACHO/1/1/1"}, tmp_path)
    assert out["places"] == SELA


def test_a_frame_name_too_long_for_the_box_is_refused_before_rent(tmp_path: Path) -> None:
    from nyshporka.cloud import frames as F

    image = pytest.importorskip("PIL.Image")
    old = time.time() - 3600
    short = tmp_path / "0001.jpg"
    # 110 кириличних літер = 220 байт: на NTFS ім'я лягає, на Linux із хвостом
    # кешу (`.o270.c1600.seg.json.<pid>.tmp`) уже ні.
    long_ = tmp_path / (("Уманськийпереписдуш" * 10)[:110] + ".jpg")
    for f in (short, long_):
        image.new("RGB", (60, 90), (200, 190, 170)).save(f, "JPEG", quality=90)
        os.utime(f, (old, old))
    assert len(long_.stem.encode("utf-8")) > F.MAX_FRAME_STEM_BYTES

    rep = F.check_frames(tmp_path)

    assert len(rep.bad) == 1 and "задовге" in rep.bad[0] and long_.name in rep.bad[0]
