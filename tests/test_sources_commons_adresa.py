"""Адреса файлу Commons — у тій формі, в якій її приносять люди."""
from __future__ import annotations

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.commons import CommonsSource


@pytest.mark.parametrize("ref, name", [
    ("file:Метрична_книга.pdf", "Метрична_книга.pdf"),
    ("File:Метрична_книга.pdf", "Метрична_книга.pdf"),          # link_commons Вікіджерел
    ("Файл:Метрична книга.pdf", "Метрична книга.pdf"),          # українські вікі
    ("https://commons.wikimedia.org/wiki/File:%D0%94%D0%90%D0%A5%D0%9E.pdf", "ДАХО.pdf"),
])
def test_nazva_z_adresy(ref: str, name: str) -> None:
    assert CommonsSource()._name(ref) == name


@pytest.mark.parametrize("ref", ["Category:Щось", "file:", "просто назва.pdf"])
def test_nezrozumila_adresa(ref: str) -> None:
    with pytest.raises(SourceError):
        CommonsSource()._name(ref)
