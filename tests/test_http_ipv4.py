"""Транспорт «спершу IPv4»: мертвий IPv6 не має коштувати ~43 с на з'єднання."""
from __future__ import annotations

import urllib.request
from typing import Any, ClassVar

import httpx
import pytest

from nyshporka.sources import http


class _Fake:
    """Двійник `httpx.HTTPTransport`: пише, чим його створили й що він бачив."""

    stvoreno: ClassVar[list[_Fake]] = []
    #: local_address → виняток, який дає з'єднання цим шляхом.
    zbii: ClassVar[dict[str | None, Exception]] = {}

    def __init__(self, *, local_address: str | None = None, proxy: Any = None) -> None:
        self.local_address = local_address
        self.proxy = proxy
        self.timeouts: list[dict[str, Any]] = []
        _Fake.stvoreno.append(self)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.timeouts.append(dict(request.extensions.get("timeout") or {}))
        zbii = _Fake.zbii.get(self.local_address)
        if zbii is not None:
            raise zbii
        return httpx.Response(200, request=request)

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _chysto(monkeypatch: pytest.MonkeyPatch) -> None:
    _Fake.stvoreno = []
    _Fake.zbii = {}
    monkeypatch.setattr(httpx, "HTTPTransport", _Fake)
    monkeypatch.setattr(http, "_IPV4_NE_PRATSIUIE", False)
    monkeypatch.setattr(urllib.request, "getproxies", dict)


def _zapyt(t: Any, timeout: float = 300.0) -> httpx.Response:
    with httpx.Client(transport=t, timeout=timeout) as c:
        return c.put("https://r2.example/k", content=b"x")


def _shliakhy() -> list[str | None]:
    return [f.local_address for f in _Fake.stvoreno]


def test_ipv4_pershym_i_bez_zapasnoho() -> None:
    assert _zapyt(http.transport()).status_code == 200
    assert _shliakhy() == ["0.0.0.0"]
    assert http._IPV4_NE_PRATSIUIE is False


def test_mertvyi_ipv4_ide_zvychainym_shliakhom_i_procec_tse_pamiataie() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectError("[Errno 11001] getaddrinfo failed")
    assert _zapyt(http.transport()).status_code == 200
    assert _shliakhy() == ["0.0.0.0", None]
    assert http._IPV4_NE_PRATSIUIE is True

    # Наступний клієнт IPv4 уже не пробує: кожна спроба — зайве відмовлення.
    _Fake.stvoreno = []
    assert _zapyt(http.transport()).status_code == 200
    assert _shliakhy() == [None]


def test_tajmaut_ipv4_tezh_vede_na_zapasnyi() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectTimeout("timed out")
    assert _zapyt(http.transport()).status_code == 200
    assert _shliakhy() == ["0.0.0.0", None]


def test_sertyfikat_ne_liky_zapasnym_shliakhom() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] x")
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        _zapyt(http.transport())
    assert _shliakhy() == ["0.0.0.0"]
    assert http._IPV4_NE_PRATSIUIE is False


def test_upaly_obydva__pomylka_zvychainoho_shliakhu_i_bez_pamiati() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectError("[Errno 11001] getaddrinfo failed")
    _Fake.zbii[None] = httpx.ConnectError("[WinError 10061] refused")
    with pytest.raises(httpx.ConnectError, match="10061"):
        _zapyt(http.transport())
    assert http._IPV4_NE_PRATSIUIE is False


def test_lymit_zjednannia_lyshe_dlia_ipv4() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectTimeout("timed out")
    _zapyt(http.transport(), timeout=300.0)
    v4, zvychainyi = _Fake.stvoreno
    assert v4.timeouts[0]["connect"] == http.IPV4_CONNECT_S
    assert zvychainyi.timeouts[0]["connect"] == 300.0
    assert v4.timeouts[0]["read"] == 300.0, "решта лімітів не чіпається"


def test_proksi_nyshporky_ide_v_obydva_shliakhy() -> None:
    _Fake.zbii["0.0.0.0"] = httpx.ConnectError("x")
    _zapyt(http.transport("socks5://127.0.0.1:1080"))
    assert [f.proxy for f in _Fake.stvoreno] == ["socks5://127.0.0.1:1080"] * 2


def test_proksi_systemy__transport_ne_pidminiaietsia(
        monkeypatch: pytest.MonkeyPatch) -> None:
    # Власний транспорт вимкнув би підхоплення проксі з оточення в httpx.
    monkeypatch.setattr(urllib.request, "getproxies",
                        lambda: {"https": "http://proxy.corp:3128"})
    assert http.transport() is None
