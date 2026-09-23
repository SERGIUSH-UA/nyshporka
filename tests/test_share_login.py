"""🔑 Вхід у Супрягу через петлю: ключ приймається лише від свого входу.

Браузер тут підмінено: замість нього «сторінка сайту» сама шле POST на
порт, який слухає Нишпорка, — рівно те, що робить форма передачі.
"""
from __future__ import annotations

import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import keyring
import pytest
from keyring.backend import KeyringBackend

from nyshporka.share import login as L
from nyshporka.share import upload
from nyshporka.share.upload import KEYRING_SERVICE, KEYRING_USER, UploadError


class _Skhovyshche(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.data.pop((service, username), None)


@pytest.fixture
def skhovyshche(monkeypatch: pytest.MonkeyPatch) -> _Skhovyshche:
    was = keyring.get_keyring()
    kr = _Skhovyshche()
    keyring.set_keyring(kr)
    monkeypatch.delenv(upload.ENV_NAME, raising=False)
    yield kr
    keyring.set_keyring(was)


def _brauzer(monkeypatch: pytest.MonkeyPatch, *, state: str | None = None,
             token: str = "kliuch-z-saitu") -> dict[str, Any]:
    """Підмінити браузер «сторінкою», що шле форму на петлю."""
    seen: dict[str, Any] = {}

    def _open(url: str) -> bool:
        q = parse_qs(urlparse(url).query)
        seen["url"] = url
        port = q["port"][0]
        body = {"token": token, "state": state if state is not None else q["state"][0]}

        def _post() -> None:
            seen["resp"] = httpx.post(f"http://127.0.0.1:{port}/", data=body, timeout=10)

        # У потоці: `webbrowser.open` повертається одразу, і так само мусить тут.
        threading.Thread(target=_post, daemon=True).start()
        return True

    monkeypatch.setattr(L.webbrowser, "open", _open)
    return seen


def test_kliuch_z_pravylnym_state_lyahaie_u_skhovyshche(
    skhovyshche: _Skhovyshche, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _brauzer(monkeypatch)
    got = L.login(site="https://probe.invalid", timeout=10)

    assert got == "kliuch-z-saitu"
    assert skhovyshche.data[(KEYRING_SERVICE, KEYRING_USER)] == "kliuch-z-saitu"
    assert upload.token() == "kliuch-z-saitu"
    assert seen["url"].startswith("https://probe.invalid/cli?")
    assert seen["resp"].status_code == 200


def test_chuzhyi_state_ne_pryimaietsia(
    skhovyshche: _Skhovyshche, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Інакше будь-яка вкладка підсовує на цей порт СВІЙ ключ, і внески
    людини йдуть у чужий акаунт."""
    seen = _brauzer(monkeypatch, state="pidsunutyi-state-ne-toi")
    with pytest.raises(UploadError):
        L.login(site="https://probe.invalid", timeout=2)
    assert seen["resp"].status_code == 400
    assert (KEYRING_SERVICE, KEYRING_USER) not in skhovyshche.data


def test_slukhaie_lyshe_petliu(
    skhovyshche: _Skhovyshche, monkeypatch: pytest.MonkeyPatch
) -> None:
    adresy: list[tuple[str, int]] = []
    orig = L._Pryimach.__init__

    def _zapamiataty(self: Any, address: tuple[str, int], *a: Any, **kw: Any) -> None:
        adresy.append(address)
        orig(self, address, *a, **kw)

    monkeypatch.setattr(L._Pryimach, "__init__", _zapamiataty)
    _brauzer(monkeypatch)
    L.login(site="https://probe.invalid", timeout=10)
    assert adresy and adresy[0][0] == "127.0.0.1"


def test_bez_kliku_taimaut(
    skhovyshche: _Skhovyshche, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(L.webbrowser, "open", lambda url: True)
    with pytest.raises(UploadError, match="не прийшов"):
        L.login(site="https://probe.invalid", timeout=0.5)


def test_bez_skhovyshcha_kliuchiv_vidmova_do_brauzera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Анонімний акаунт народжується на кліку — без сховища ключ нікуди
    покласти, тож браузер навіть не відкривається."""
    from keyring.backends import fail

    was = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    vidkryto: list[str] = []
    monkeypatch.setattr(L.webbrowser, "open", lambda url: vidkryto.append(url) or True)
    try:
        with pytest.raises(UploadError, match="сховища ключів"):
            L.login(site="https://probe.invalid", timeout=1)
    finally:
        keyring.set_keyring(was)
    assert vidkryto == []


def test_logout_prybyraie_kliuch(skhovyshche: _Skhovyshche) -> None:
    L.save("stary")
    assert L.forget() is True
    assert upload.token() == ""
    assert L.forget() is False


def test_publish_bez_kliucha_radyt_login(
    skhovyshche: _Skhovyshche, tmp_path: Any
) -> None:
    paket = tmp_path / "x.nyshtext"
    paket.write_bytes(b"")
    with pytest.raises(UploadError, match="nysh share login"):
        upload.publish(paket)
