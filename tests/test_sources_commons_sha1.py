"""📚 Commons: файл лягає в теку справи лише тоді, коли збігся SHA-1.

Завантаження дочитується через `Range`, тож довжина сходиться і в склеєного зі
шматків файла. Звірка розміру цього не ловить — ловить лише хеш, який Commons
називає сам.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from nyshporka.sources.commons import BASE, CommonsSource
from nyshporka.sources.http import Fetcher

_BODY = b"%PDF-1.4 " + bytes(range(256)) * 20


def _source(sha1: str) -> CommonsSource:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/w/api.php":
            ii = {"url": "https://upload.example/f.pdf", "size": len(_BODY),
                  "mime": "application/pdf", "sha1": sha1, "pagecount": 3}
            return httpx.Response(200, content=json.dumps(
                {"query": {"pages": [{"imageinfo": [ii]}]}}).encode())
        return httpx.Response(200, content=_BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CommonsSource(fetcher=Fetcher(base=BASE, client=client, delay=0.0))


def test_zbizhnyi_sha1_kladet_fail(tmp_path: Path) -> None:
    res = _source(hashlib.sha1(_BODY).hexdigest()).fetch("file:Справа.pdf", tmp_path)
    assert not res.errors and res.frames == 3
    assert (tmp_path / "Справа.pdf").read_bytes() == _BODY


@pytest.mark.parametrize("bad", ["0" * 40])
def test_khybnyi_sha1_ne_kladet_fail(tmp_path: Path, bad: str) -> None:
    """🔴 Правильна довжина з битими сторінками — гірше за відсутній файл: по
    ньому читатимуть і шукатимуть, не знаючи, що він зіпсований."""
    res = _source(bad).fetch("file:Справа.pdf", tmp_path)
    assert res.errors and "SHA-1" in res.errors[0]
    assert not (tmp_path / "Справа.pdf").exists()
