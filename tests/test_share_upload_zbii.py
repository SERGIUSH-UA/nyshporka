"""Заливання в Супрягу: повтори PUT і сигнал пулу про збій.

26.09.2026 перший внесок сторонньої людини застряг зареєстрованим без байтів:
PUT у сховище впав двічі поспіль, і пул не дізнався ні про збій, ні про
причину — байти йдуть у сховище повз нього.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from nyshporka.share import upload


@pytest.fixture(autouse=True)
def _bez_pauz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload, "PUT_PAUZY", (0.0, 0.0))


def test_put_povtoriuie_obryv(monkeypatch: pytest.MonkeyPatch) -> None:
    sproby: list[int] = []

    def _put(url: str, **kw: Any) -> Any:
        sproby.append(1)
        if len(sproby) < 3:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "put", _put)
    upload._put("https://r2.example/k?X-Amz-SignedHeaders=host", b"x")
    assert len(sproby) == 3


def test_put_kazhe_prychynu_bez_posylannia(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://r2.example/k?X-Amz-" + "Signature=SEKRET"
    sproby: list[int] = []

    def _put(u: str, **kw: Any) -> Any:
        sproby.append(1)
        raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] for {u}")

    monkeypatch.setattr(httpx, "put", _put)
    with pytest.raises(upload.UploadError) as ei:
        upload._put(url, b"x")
    assert "CERTIFICATE_VERIFY_FAILED" in str(ei.value), "причина мусить дійти до людини"
    assert "SEKRET" not in str(ei.value)
    assert ei.value.klas == upload.SERTYFIKAT and "антивірус" in ei.value.chomu
    assert len(sproby) == 1, "сталий збій повтор не виправить — не тримаємо людину"


@pytest.mark.parametrize("vyniatok, proksi, klas", [
    (httpx.ReadTimeout("timed out"), False, upload.TYMCHASOVYI),
    (httpx.ReadError("connection reset"), False, upload.TYMCHASOVYI),
    (httpx.ConnectError("[Errno 11001] getaddrinfo failed"), False, upload.BLOKUVANNIA),
    (httpx.ConnectError("[WinError 10061] refused"), False, upload.BLOKUVANNIA),
    (httpx.ConnectError("[WinError 10061] refused"), True, upload.PROKSI),
    (httpx.ProxyError("407 Proxy Authentication Required"), False, upload.PROKSI),
])
def test_klas_obryvu(monkeypatch: pytest.MonkeyPatch, vyniatok: Exception,
                     proksi: bool, klas: str) -> None:
    for name in ("NYSHPORKA_PROXY_URL", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    if proksi:
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    assert upload._klas_obryvu(vyniatok)[0] == klas


def test_put_403_tse_nasha_vada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "put", lambda u, **kw: httpx.Response(
        403, text="<Error><Code>AccessDenied</Code></Error>"))
    with pytest.raises(upload.UploadError) as ei:
        upload._put("https://r2.example/k", b"x")
    assert ei.value.klas == upload.VIDMOVA and "нашому боці" in ei.value.chomu


def test_put_kod_s3_i_bez_povtoru_na_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    sproby: list[int] = []

    def _put(u: str, **kw: Any) -> Any:
        sproby.append(1)
        return httpx.Response(403, text="<Error><Code>SignatureDoesNotMatch</Code></Error>")

    monkeypatch.setattr(httpx, "put", _put)
    with pytest.raises(upload.UploadError) as ei:
        upload._put("https://r2.example/k", b"x")
    assert "SignatureDoesNotMatch" in str(ei.value)
    assert len(sproby) == 1, "відмову підпису повтор не виправить"


def test_put_cherez_proksi_nyshporky(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _put(u: str, **kw: Any) -> Any:
        seen.update(kw)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "put", _put)
    monkeypatch.setenv("NYSHPORKA_PROXY_URL", "socks5://127.0.0.1:1080")
    upload._put("https://r2.example/k", b"x")
    assert seen["proxy"] == "socks5://127.0.0.1:1080"


# ── сигнал пулу ─────────────────────────────────────────────────────────────

class _Manifest:
    def as_json(self) -> dict[str, Any]:
        return {"case": {"shifra": "ДАХО 40-141-194"}}


def _pidhotuvaty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                 complete: Any = None) -> tuple[Path, list[tuple[Any, ...]]]:
    from nyshporka.share import bundle, catalog

    paket = tmp_path / "p.nyshtext"
    paket.write_bytes(b"bytes")
    monkeypatch.setattr(bundle, "read_manifest", lambda p: _Manifest())
    monkeypatch.setattr(catalog, "may_send_key", lambda home, explicit=False: True)

    def _request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        if url.endswith("/contributions"):
            return {"contribution": 1337, "upload": {"text": "https://r2.example/t"}}
        if complete is not None:
            complete()
        return {"ready": True, "status": "nove"}

    monkeypatch.setattr(upload, "_request", _request)
    zvity: list[tuple[Any, ...]] = []
    monkeypatch.setattr(upload, "_zvit_pro_zbii",
                        lambda home, tok, vnesok, etap, prychyna: zvity.append(
                            (vnesok, etap, prychyna)))
    return paket, zvity


def test_zbii_put_ide_v_pul(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paket, zvity = _pidhotuvaty(monkeypatch, tmp_path)

    def _put(url: str, blob: bytes) -> None:
        raise upload.UploadError("сховище не прийняло байти після 3 спроб: ReadTimeout")

    monkeypatch.setattr(upload, "_put", _put)
    with pytest.raises(upload.UploadError):
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    assert zvity == [(1337, "put_text",
                      "[tymchasovyi] сховище не прийняло байти після 3 спроб: ReadTimeout")]


def test_zbii_kazhe_shcho_robyty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Вивід команди — єдине, що точно читає будь-який агент."""
    paket, _ = _pidhotuvaty(monkeypatch, tmp_path)

    def _put(url: str, blob: bytes) -> None:
        raise upload.UploadError("сховище не прийняло байти після 3 спроб: ReadTimeout")

    monkeypatch.setattr(upload, "_put", _put)
    with pytest.raises(upload.UploadError) as ei:
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    assert "ReadTimeout" in str(ei.value)
    assert "Внесок 1337" in str(ei.value) and "Повторіть ту саму команду" in str(ei.value)


def test_stalyi_zbii_ne_radyt_povtoriuvaty(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    """Повтор на сталому збої веде по колу: кожна спроба — сигнал, результату нуль."""
    paket, zvity = _pidhotuvaty(monkeypatch, tmp_path)

    def _put(url: str, blob: bytes) -> None:
        raise upload.UploadError("сховище не прийняло байти: ConnectError: getaddrinfo",
                                 klas=upload.BLOKUVANNIA, chomu="адреса сховища недосяжна")

    monkeypatch.setattr(upload, "_put", _put)
    with pytest.raises(upload.UploadError) as ei:
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    tekst = str(ei.value)
    assert "Повторіть ту саму команду" not in tekst
    assert "цього не виправить: адреса сховища недосяжна" in tekst
    assert upload.ISSUES in tekst and ei.value.klas == upload.BLOKUVANNIA
    assert zvity[0][2].startswith("[blokuvannia]"), "клас мусить дійти до розробника"


@pytest.mark.parametrize("klas, dali", [
    (upload.TYMCHASOVYI, ["share.publish"]),
    (upload.BLOKUVANNIA, []),
])
def test_dali_pislia_zboiu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                           klas: str, dali: list[str]) -> None:
    """🔴 Після збою — не «перевірити, що пакет знайшовся»: пакета немає."""
    from nyshporka import ops as O

    paket, _ = _pidhotuvaty(monkeypatch, tmp_path)

    def _put(url: str, blob: bytes) -> None:
        raise upload.UploadError("збій", klas=klas, chomu="причина")

    monkeypatch.setattr(upload, "_put", _put)
    monkeypatch.setenv(upload.ENV_NAME, "k")
    env = O.call("share.publish", {"path": str(paket),
                                   "base": "https://nyshporka.online/v1"})
    assert not env.ok
    assert [n.op for n in env.next] == dali


def test_khid_zalyvky(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paket, _ = _pidhotuvaty(monkeypatch, tmp_path)
    monkeypatch.setattr(upload, "_put", lambda url, blob: None)
    khid: list[str] = []
    upload.publish(paket, base="https://nyshporka.online/v1", auth="k", say=khid.append)
    assert khid[0].startswith("заливаю текст:") and "МБ" in khid[0]
    assert khid[1].startswith("✓ текст за")
    assert khid[-1] == "пул перевіряє пакет…"


def test_puls_poky_zalyvaie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Довгий PUT не мовчить: агент бачить, що процес живий."""
    import time

    paket, _ = _pidhotuvaty(monkeypatch, tmp_path)
    monkeypatch.setattr(upload, "PULS_S", 0.02)
    monkeypatch.setattr(upload, "_put", lambda url, blob: time.sleep(0.2))
    khid: list[str] = []
    upload.publish(paket, base="https://nyshporka.online/v1", auth="k", say=khid.append)
    assert any(r.startswith("…ще заливаю текст") for r in khid)


def test_khid_u_stderr_json_chystyi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    from nyshporka.ops_share import SharePublishArgs, share_publish

    paket, _ = _pidhotuvaty(monkeypatch, tmp_path)
    monkeypatch.setattr(upload, "_put", lambda url, blob: None)
    monkeypatch.setenv(upload.ENV_NAME, "k")
    env = share_publish(SharePublishArgs(path=str(paket), base="https://nyshporka.online/v1"))
    assert env.ok
    got = capsys.readouterr()
    assert "заливаю текст" in got.err
    assert got.out == "", "stdout належить JSON-конверту"


def test_vidmova_pulu_ne_dubliuietsia(monkeypatch: pytest.MonkeyPatch,
                                      tmp_path: Path) -> None:
    """Ворота відмовили на `complete` — пул це вже знає, звіт зайвий."""
    def _vorota() -> None:
        raise upload.UploadError("ворота не пустили пакет", status=400)

    paket, zvity = _pidhotuvaty(monkeypatch, tmp_path, complete=_vorota)
    monkeypatch.setattr(upload, "_put", lambda url, blob: None)
    with pytest.raises(upload.UploadError) as ei:
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    assert zvity == []
    assert "Повторіть" not in str(ei.value), "відмову воріт повтор не виправить"


def test_ctrl_c_tezh_ide_v_pul(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paket, zvity = _pidhotuvaty(monkeypatch, tmp_path)

    def _put(url: str, blob: bytes) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(upload, "_put", _put)
    with pytest.raises(KeyboardInterrupt):
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    assert zvity and zvity[0][1] == "put_text"


def test_zvit_sam_ne_padaie(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.share import catalog

    def _fetcher(*a: Any, **k: Any) -> Any:
        raise catalog.PoolError("мережі немає")

    monkeypatch.setattr(catalog, "_fetcher", _fetcher)
    upload._zvit_pro_zbii("https://nyshporka.online/v1", "k", 1, "put_text", "x")


# ── share.pull і запит ключа ────────────────────────────────────────────────

@pytest.mark.parametrize("znaideno, dali", [(0, []), (1, ["share.import"])])
def test_pull_radyt_pryiniaty_lyshe_znaidene(monkeypatch: pytest.MonkeyPatch,
                                             znaideno: int, dali: list[str]) -> None:
    """🔴 Під нулем знахідок «прийняти знайдений пакет» посилає по неіснуюче."""
    from nyshporka import ops as O
    from nyshporka.share import catalog as C

    rows = [C.Row(shifra="ДАХО 40-141-194", url="https://x/t", sha256="a" * 64)][:znaideno]
    monkeypatch.setattr(C, "search", lambda *a, **k: (rows, len(rows), 1334))
    env = O.call("share.pull", {"query": "Салтів"})
    assert env.ok
    assert [n.op for n in env.next] == dali


class _Potik:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.parametrize("stdin_tty, stdout_tty, pytaie", [
    (True, False, False),    # Windows: NUL на вході видає себе за термінал
    (False, True, False),
    (True, True, True),
])
def test_kliuch_pytaie_lyshe_v_terminali(monkeypatch: pytest.MonkeyPatch, stdin_tty: bool,
                                         stdout_tty: bool, pytaie: bool) -> None:
    import sys

    import typer

    from nyshporka.share import cli as SC

    pytano: list[str] = []
    monkeypatch.setattr(upload, "token", lambda: "")
    monkeypatch.setattr(sys, "stdin", _Potik(stdin_tty))
    monkeypatch.setattr(sys, "stdout", _Potik(stdout_tty))
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: pytano.append("так") or False)
    SC._kliuch_abo_vkhid(as_json=False)
    assert bool(pytano) is pytaie


def test_kliuch_bez_vidpovidi_ne_obryvaie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кінець вводу на запитанні — не «Aborted.», а далі до зрозумілої відмови."""
    import sys

    import click
    import typer

    from nyshporka.share import cli as SC

    def _abort(*a: Any, **k: Any) -> bool:
        raise click.exceptions.Abort()

    monkeypatch.setattr(upload, "token", lambda: "")
    monkeypatch.setattr(sys, "stdin", _Potik(True))
    monkeypatch.setattr(sys, "stdout", _Potik(True))
    monkeypatch.setattr(typer, "confirm", _abort)
    monkeypatch.setattr(SC.console, "print", lambda *a, **k: None)
    SC._kliuch_abo_vkhid(as_json=False)
