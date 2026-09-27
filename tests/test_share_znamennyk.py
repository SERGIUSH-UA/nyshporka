"""Знаменник покриття в маніфесті — кадри копії справи, а не теки на диску."""
from __future__ import annotations

from nyshporka.share import gates
from nyshporka.share.bundle import Manifest
from nyshporka.share.publish import _znamennyk


def _blok(n: int) -> dict[str, int]:
    return {"total": n, "listed": n, "with_sha256": 0, "with_apid": 0}


def test_urivok_z_dzerkala_diistaie_znamennyk_z_reiestru() -> None:
    got = _znamennyk(_blok(5), {"fs_frames": "824"})
    assert got["total"] == 824
    assert got["on_disk"] == 5
    # За `listed` іде прив'язка тексту до кадрів — її чіпати не можна.
    assert got["listed"] == 5


def test_drybnyi_nedobir_ne_uryvok() -> None:
    # Завантажувач пропускає технічні кадри: 612 із 619 — повна справа.
    assert _znamennyk(_blok(612), {"fs_frames": "619"}) == _blok(612)


def test_bez_reiestru_lyshaietsia_dysk() -> None:
    assert _znamennyk(_blok(5), None) == _blok(5)
    assert _znamennyk(_blok(5), {"fs_frames": ""}) == _blok(5)


def test_commons_pages_tezh_znamennyk() -> None:
    assert _znamennyk(_blok(10), {"commons_pages": "300"})["total"] == 300


def test_vorota_bachat_uryvok() -> None:
    # Саме заради цього: 5 із 824 без пояснення ворота не пускають.
    m = Manifest(case={"shifra": "ДАОО 37-3-1386"},
                 frames=_znamennyk(_blok(5), {"fs_frames": "824"}),
                 decode={"pages": 5, "voices": [{"model": "m", "pages": 5}]})
    def uryvok(v: gates.Verdict) -> bool:
        return any("уривок" in r for r in v.refusals)

    assert uryvok(gates.check(m))
    assert not uryvok(gates.check(m, partial_why="кадри 1-5 — титул і покажчик"))


def test_prychyna_urivka_z_manifestu() -> None:
    # Сервер кличе ворота без `partial_why`: причину мусить дати маніфест.
    m = Manifest(case={"shifra": "ЦДІАК 127-1078-2901"},
                 frames=_blok(195), extra={"partial": "прочитано кадри 1–14 із 195"},
                 decode={"pages": 14, "voices": [{"model": "m", "pages": 14}]})
    v = gates.check(m)
    assert not any("уривок" in r for r in v.refusals), v.refusals
    assert any("1–14" in t for c, t in v.warnings if c == "partial")
