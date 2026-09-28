"""Файл геометрії не заливається як пакет.

28.09.2026 `publish` кликали циклом по всіх `*.nyshtext` теки, і файли
`….geom.nyshtext` їхали на місце тексту: `geom_path` від такого файла
повертає його ж, тож той самий файл лягав і як текст, і як геометрія. У пулі
опинився 31 внесок без жодної сторінки тексту.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.share import bundle
from nyshporka.share.upload import UploadError, publish


def test_heometriia_ne_paket(tmp_path: Path) -> None:
    tekst = tmp_path / ("ДАДнО_193-3-212" + bundle.SUFFIX)
    heom = bundle.geom_path(tekst)
    tekst.write_bytes(b"x")
    heom.write_bytes(b"y")
    with pytest.raises(UploadError, match="файл геометрії") as exc:
        publish(heom, base="https://example.invalid", auth="t")
    assert tekst.name in str(exc.value), "людині треба назвати, що заливати натомість"
