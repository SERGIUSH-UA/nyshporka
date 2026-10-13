"""Hungaricana: том бібліотеки порталу — відоме джерело зйомки.

Переглядач і тека тому на CDN називають той самий том; розійдуться — і пул
матиме дві зйомки однієї книги.
"""
from __future__ import annotations

import pytest

from nyshporka.core import hungaricana
from nyshporka.share.publish import _refs_from_links

ID = "KANepszaml_012_Nagybocsko_Nagybocsko__158_VelikijBicskiv-NagyBocsko"
VIEW = f"https://library.hungaricana.hu/hu/view/{ID}/"


@pytest.mark.parametrize("url", [
    f"https://library.hungaricana.hu/hu/view/{ID}/?pg=250&layout=s",
    f"https://library.hungaricana.hu/en/view/{ID}/",
    f"library.hungaricana.hu/hu/view/{ID}",
    ("https://static-cdn.hungaricana.hu/pdf1/KarpataljaiNepszamlalas1921/"
     f"{ID}-1591878074/page0250.pdf"),
    f"https://static-cdn.hungaricana.hu/pdf1/KarpataljaiNepszamlalas1921/{ID}-1591878074/",
])
def test_odyn_tom_z_usikh_form(url: str) -> None:
    got = _refs_from_links([{"label": "скани", "url": url}])
    assert got == [{"source": "hungaricana", "ref": f"view:{ID}", "url": VIEW}]


@pytest.mark.parametrize("url", [
    "https://library.hungaricana.hu/hu/collection/KANepszaml_012/",
    "https://archives.hungaricana.hu/en/lear/Fogoly/164912",
    f"https://static-cdn.hungaricana.hu/pdf1/KarpataljaiNepszamlalas1921/{ID}/thumb/page0001.jpg",
    f"https://example.org/hu/view/{ID}/",
])
def test_inshe_ne_zjomka(url: str) -> None:
    assert hungaricana.from_url(url) is None


def test_ref_tudy_i_nazad() -> None:
    vol = hungaricana.from_url(VIEW)
    assert vol is not None
    assert hungaricana.from_ref(vol.ref) == vol
    assert hungaricana.from_ref(f"hungaricana:view:{ID}") == vol
    assert hungaricana.from_ref("view:") is None
    assert hungaricana.from_ref("view:../x") is None
    assert hungaricana.from_ref(f"page:{ID}") is None
