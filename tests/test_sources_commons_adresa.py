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


# ── аудит 29.09.2026: розмір із Commons — стеля качання ─────────────────────

def test_fail_bilshyi_za_obitsianyi_obryvaietsia_na_steli(tmp_path) -> None:
    """🔴 Доти качання читало скільки дадуть, а розмір звірявся ПІСЛЯ: сервер
    міг заповнити диск раніше, ніж звірка встигала відмовити."""
    import json

    import httpx

    from nyshporka.sources.http import Fetcher

    info = {"query": {"pages": [{"imageinfo": [{
        "url": "https://upload.example/f.pdf", "size": 100, "mime": "application/pdf"}]}]}}

    def _answer(req: httpx.Request) -> httpx.Response:
        if "api.php" in str(req.url):
            return httpx.Response(200, text=json.dumps(info))
        return httpx.Response(200, content=b"x" * 50_000)

    src = CommonsSource(fetcher=Fetcher(
        base="https://commons.example", delay=0.0,
        client=httpx.Client(transport=httpx.MockTransport(_answer))))
    res = src.fetch("file:Справа.pdf", tmp_path)
    assert res.errors and "більше 100 байт" in res.errors[0], res.errors
    assert not any(tmp_path.iterdir())
