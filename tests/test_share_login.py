"""🔑 Вхід у Супрягу через петлю: ключ приймається лише від свого входу.

Браузер тут підмінено: замість нього «сторінка сайту» сама шле POST на
порт, який слухає Нишпорка, — рівно те, що робить форма передачі.
"""
from __future__ import annotations

import threading
from typing import Any, ClassVar
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
        # Потік запам'ятовується: `login()` повертається, щойно сервер відповів,
        # а записати відповідь у `seen` потік ще може не встигнути — без
        # `join` тест падав через раз на чужій гонитві, а не на вході.
        seen["thread"] = threading.Thread(target=_post, daemon=True)
        seen["thread"].start()
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
    seen["thread"].join(timeout=10)
    assert seen["resp"].status_code == 200


def test_chuzhyi_state_ne_pryimaietsia(
    skhovyshche: _Skhovyshche, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Інакше будь-яка вкладка підсовує на цей порт СВІЙ ключ, і внески
    людини йдуть у чужий акаунт."""
    seen = _brauzer(monkeypatch, state="pidsunutyi-state-ne-toi")
    with pytest.raises(UploadError):
        L.login(site="https://probe.invalid", timeout=2)
    seen["thread"].join(timeout=10)
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


def test_keyring_u_yadri_a_ne_v_extras() -> None:
    """Dev-оточення ставить усі extras, тож без цього тесту випадіння keyring
    з ядра не видно ніде, крім установки людини (так і сталось 23.09)."""
    import tomllib
    from pathlib import Path

    meta = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml")
                         .read_text(encoding="utf-8"))
    assert any(d.startswith("keyring") for d in meta["project"]["dependencies"])


# ── пошук і видача: ключ їде сам, 401 перекладається людині ─────────────────


class _Fetcher:
    """Замість мережі: запам'ятати заголовки й відповісти заданим."""

    seen: ClassVar[list[dict[str, str]]] = []
    status = 200

    def __init__(self, *, headers: dict[str, str], **_: Any) -> None:
        _Fetcher.seen.append(dict(headers))

    def get(self, url: str) -> Any:
        from nyshporka.sources.http import HttpError

        if _Fetcher.status != 200:
            raise HttpError(f"{url}: HTTP {_Fetcher.status}", status=_Fetcher.status)
        return type("R", (), {"text": '{"rows": [], "count": 0, "of": 3}'})()


@pytest.fixture
def merezha(monkeypatch: pytest.MonkeyPatch) -> type[_Fetcher]:
    import nyshporka.sources.http as H

    _Fetcher.seen = []
    _Fetcher.status = 200
    monkeypatch.setattr(H, "Fetcher", _Fetcher)
    # Мережі тут немає — її заміняє `_Fetcher`, тож заборону знімаємо.
    monkeypatch.delenv(H.ENV_OFFLINE, raising=False)
    return _Fetcher


#: Адреса пулу, якій довіряється ключ. Запити не йдуть нікуди — `_Fetcher`.
PUL = "https://api.nyshporka.online/v1"


def test_poshuk_nese_kliuch(skhovyshche: _Skhovyshche, merezha: type[_Fetcher]) -> None:
    from nyshporka.share import catalog

    L.save("kliuch-1")
    catalog.search("315", PUL)
    assert merezha.seen[-1]["Authorization"] == "Bearer kliuch-1"


@pytest.mark.parametrize("base", [
    "https://probe.invalid/v1",               # чужий домен
    "http://api.nyshporka.online/v1",         # свій домен, але відкритим HTTP
    "https://nyshporka.online.evil.test/v1",  # підробка під свій домен
])
def test_kliuch_ne_ide_na_chuzhu_adresu(
    skhovyshche: _Skhovyshche, merezha: type[_Fetcher], base: str
) -> None:
    """🔴 Адресу пулу міняє змінна `NYSHPORKA_TOLOKA` — ключ за нею не їде."""
    from nyshporka.share import catalog

    L.save("kliuch-1")
    catalog.search("315", base)
    assert "Authorization" not in merezha.seen[-1]


def test_publish_ne_shle_kliuch_na_chuzhyi_pul(
    skhovyshche: _Skhovyshche, tmp_path: Any
) -> None:
    L.save("kliuch-1")
    paket = tmp_path / "p.nyshtext"
    paket.write_bytes(b"x")
    with pytest.raises(UploadError, match="не надсилається"):
        upload.publish(paket, base="https://probe.invalid/v1")


def test_bez_merezhi_pul_ne_pytaietsia(monkeypatch: pytest.MonkeyPatch) -> None:
    """`NYSHPORKA_NO_NETWORK` — жодного запиту до пулу, чесна відмова."""
    from nyshporka.share import catalog

    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    got = catalog.lookup("ДАХмО 315-1-8433")
    assert got["found"] is False and got.get("offline") is True
    with pytest.raises(catalog.PoolError, match="NO_NETWORK"):
        catalog.search("315")


def test_bez_kliucha_zapyt_bez_zaholovka(
    skhovyshche: _Skhovyshche, merezha: type[_Fetcher]
) -> None:
    from nyshporka.share import catalog

    catalog.search("315", PUL)
    assert "Authorization" not in merezha.seen[-1]


def test_401_kazhe_yak_pidiednatys(
    skhovyshche: _Skhovyshche, merezha: type[_Fetcher]
) -> None:
    from nyshporka.share import catalog

    merezha.status = 401
    with pytest.raises(catalog.PotribenKliuch, match="nysh share login"):
        catalog.search("315", PUL)


def test_lookup_bez_kliucha_ne_valyt_prohin(
    skhovyshche: _Skhovyshche, merezha: type[_Fetcher]
) -> None:
    """Перед прогоном пул питають мовчки: 401 — це «не знайдено», а не збій."""
    from nyshporka.share import catalog

    merezha.status = 401
    got = catalog.lookup("ДАХмО 315-1-8433", base=PUL)
    assert got["found"] is False
    assert got.get("need_key") is True
