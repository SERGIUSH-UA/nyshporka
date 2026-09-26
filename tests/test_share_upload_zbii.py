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

    def _put(u: str, **kw: Any) -> Any:
        raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] for {u}")

    monkeypatch.setattr(httpx, "put", _put)
    with pytest.raises(upload.UploadError) as ei:
        upload._put(url, b"x")
    assert "CERTIFICATE_VERIFY_FAILED" in str(ei.value), "причина мусить дійти до людини"
    assert "SEKRET" not in str(ei.value)
    assert "3 спроб" in str(ei.value)


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
                      "сховище не прийняло байти після 3 спроб: ReadTimeout")]


def test_vidmova_pulu_ne_dubliuietsia(monkeypatch: pytest.MonkeyPatch,
                                      tmp_path: Path) -> None:
    """Ворота відмовили на `complete` — пул це вже знає, звіт зайвий."""
    def _vorota() -> None:
        raise upload.UploadError("ворота не пустили пакет", status=400)

    paket, zvity = _pidhotuvaty(monkeypatch, tmp_path, complete=_vorota)
    monkeypatch.setattr(upload, "_put", lambda url, blob: None)
    with pytest.raises(upload.UploadError):
        upload.publish(paket, base="https://nyshporka.online/v1", auth="k")
    assert zvity == []


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
