"""Норма видачі пулу (з 20.11.2026): клієнт розуміє відмову й не б'ється в неї.

- 429 з `/v1/d` — окрема відмова з текстом пулу й машинною частиною;
- серія зупиняється на першій такій відмові й каже, скільки взято;
- перед серією клієнт питає залишок і попереджає, що серія ляже частинами;
- кнопка порталу (`/paket/`) і старі адреси `cdn.` ідуть на `/v1/d/` з ключем.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nyshporka.share import accept as A
from nyshporka.share import catalog as C
from nyshporka.sources.http import HttpError

KLIUCH = "b/cdiak/57-1-442/29426/text.nyshtext"
VYDACHA = f"{C.DEFAULT_BASE}/d/{KLIUCH}"


@pytest.mark.parametrize(("src", "kudy"), [
    (f"https://nyshporka.online/paket/{KLIUCH}", VYDACHA),
    (f"https://www.nyshporka.online/paket/{KLIUCH}", VYDACHA),
    (f"https://cdn.nyshporka.online/{KLIUCH}", VYDACHA),
    # Переписаний пакет лежить під `p/<мітка>/`, а видається за початковим ключем.
    (f"https://cdn.nyshporka.online/p/15d2bcdd67ea/{KLIUCH}", VYDACHA),
    # Підписана адреса живе пів години — видача дасть свіжу й запише людину з ключем.
    (f"https://cdn.nyshporka.online/{KLIUCH}?t=1.abc", VYDACHA),
    (VYDACHA, VYDACHA),
    ("https://cdn.nyshporka.online/zvid/1/x.tar", "https://cdn.nyshporka.online/zvid/1/x.tar"),
    ("http://nyshporka.online/paket/" + KLIUCH, "http://nyshporka.online/paket/" + KLIUCH),
    ("https://example.org/paket/" + KLIUCH, "https://example.org/paket/" + KLIUCH),
    ("C:/inbox/paket.nyshtext", "C:/inbox/paket.nyshtext"),
])
def test_adresa_vydachi(src: str, kudy: str) -> None:
    assert A.adresa_vydachi(src) == kudy


def test_imia_faila_te_same() -> None:
    """Переписана адреса дає те саме ім'я в inbox, що й пряма."""
    assert A._name_for(A.adresa_vydachi(f"https://nyshporka.online/paket/{KLIUCH}")) == \
        A._name_for(VYDACHA)


def test_429_vydachi_tse_norma(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nyshporka.sources import http

    monkeypatch.delenv("NYSHPORKA_NO_NETWORK", raising=False)
    tilo = json.dumps({"detail": {"text": "Тижневу норму вичерпано: 100 з 100 книг.",
                                  "norma": {"riven": "bez_vnesku", "mezha": 100}}})

    def download(self: Any, url: str, dest: Path, **kw: Any) -> None:
        assert url == VYDACHA
        raise HttpError("429", status=429, body=tilo, retry_after=7200)

    monkeypatch.setattr(http.Fetcher, "download", download)
    with pytest.raises(A.NormaVycherpana) as exc:
        A.fetch(f"https://nyshporka.online/paket/{KLIUCH}", tmp_path)
    assert "Тижневу норму вичерпано" in str(exc.value)
    assert not str(exc.value).startswith("HTTP")
    assert exc.value.retry_after == 7200
    assert exc.value.norma == {"riven": "bez_vnesku", "mezha": 100}


@pytest.fixture
def seriia(monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka import ops_share

    taken: list[str] = []

    def accept(url: str, sha256: str = "", force: bool = False,
               replace: bool = False) -> dict[str, Any]:
        if len(taken) >= 2:
            raise A.NormaVycherpana("Тижневу норму вичерпано.", retry_after=3600,
                                    norma={"riven": "bez_vnesku", "mezha": 2})
        taken.append(url)
        return {"case_key": url, "pages": 10, "runs": [f"run_{url}"]}

    monkeypatch.setattr(A, "accept", accept)
    monkeypatch.setattr(ops_share, "_index_taken", lambda env, runs: None)
    monkeypatch.setattr(ops_share, "_after_import", lambda env, got: env)
    rows = [C.Row(shifra=f"RGIA 592-25-{i}", repo="RGIA", fond="592", opys="25", spr=str(i),
                  url=f"u{i}", sha256=f"u{i}", pages="10", years="1900", models="")
            for i in range(1, 6)]
    monkeypatch.setattr(C, "search", lambda q, base="", *, limit=50, offset=0:
                        (rows[offset:offset + limit], len(rows), 99))

    def run(norma: dict[str, Any] | None) -> tuple[Any, list[str]]:
        monkeypatch.setattr(C, "norma_vydachi", lambda base="": norma)
        taken.clear()
        return ops_share.share_pull(ops_share.SharePullArgs(take=True, repo="RGIA",
                                                            fond="592")), taken

    return run


def test_seriia_zupyniaietsia_na_normi(seriia: Any) -> None:
    env, taken = seriia(None)
    assert len(taken) == 2
    zupynka = [w for w in env.warnings if "norma_vydachi" in str(w)]
    assert len(zupynka) == 1, env.warnings
    assert "узято 2, не взято 3" in str(zupynka[0])
    assert env.data["norma_zupynka"]["ne_vziato"] == 3
    assert "next_attempt_at" in env.data["norma_zupynka"]


def test_seriia_poperedzhaie_napered(seriia: Any) -> None:
    env, _ = seriia({"rezhym": "vidmova", "riven": "bez_vnesku", "vikno": "tyzhden",
                     "mezha": 100, "vziato": 98, "zalyshok": 2})
    napered = [w for w in env.warnings if "ще 2 нових" in str(w)]
    assert len(napered) == 1, env.warnings
    assert env.data["norma_vydachi"]["zalyshok"] == 2


def test_seriia_v_tini_ne_strashyt(seriia: Any) -> None:
    """У тіні пул рахує, але видає все — попереджати про частини нема чого."""
    env, _ = seriia({"rezhym": "tin", "riven": "anonim", "vikno": "doba",
                     "mezha": 10, "vziato": 10, "zalyshok": 0})
    assert not [w for w in env.warnings if "нових" in str(w)]
    assert env.data["norma_vydachi"]["rezhym"] == "tin"


def test_seriia_bez_normy_yak_ranishe(seriia: Any) -> None:
    env, _ = seriia({"rezhym": "vymk", "zalyshok": 0})
    assert "norma_vydachi" not in env.data
    assert not [w for w in env.warnings if "ще 0 нових" in str(w)]


@pytest.fixture
def pul_429(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Справжній HTTP-сервер на петлі: 429 з потрібним тілом і заголовком."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    monkeypatch.delenv("NYSHPORKA_NO_NETWORK", raising=False)
    vidpovid: dict[str, Any] = {}
    zapyty: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            zapyty.append(self.path)
            tilo = vidpovid["tilo"].encode()
            self.send_response(429)
            self.send_header("Retry-After", str(vidpovid["retry_after"]))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(tilo)))
            self.end_headers()
            self.wfile.write(tilo)

        def log_message(self, *a: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    potik = threading.Thread(target=server.serve_forever, daemon=True)
    potik.start()

    def zadaty(tilo: str, retry_after: int) -> tuple[str, list[str]]:
        vidpovid.update(tilo=tilo, retry_after=retry_after)
        zapyty.clear()
        return f"http://127.0.0.1:{server.server_address[1]}/v1/d/{KLIUCH}", zapyty

    yield zadaty
    server.shutdown()
    server.server_close()


def test_norma_kriz_spravzhnii_fetcher(pul_429: Any, tmp_path: Path) -> None:
    """Пул тримає заголовок ≥ 901 с — клієнт не чекає мовчки, а одразу зупиняється;
    час береться з JSON."""
    import time

    tilo = json.dumps({"detail": {"text": "Норму без ключа вичерпано.",
                                  "norma": {"riven": "anonim", "retry_after": 120}}})
    adresa, zapyty = pul_429(tilo, 901)
    pochatok = time.monotonic()
    with pytest.raises(A.NormaVycherpana) as exc:
        A.fetch(adresa, tmp_path)
    assert time.monotonic() - pochatok < 10
    assert len(zapyty) == 1
    assert exc.value.retry_after == 120
    assert exc.value.norma["riven"] == "anonim"


@pytest.fixture
def vydacha_i_skhovyshche(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Два справжні сервери на петлі: видача дає 302 на «підписану адресу» сховища.

    Різні порти — різне походження для httpx, як `api.nyshporka.online` і
    `cdn.nyshporka.online` насправді.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    monkeypatch.delenv("NYSHPORKA_NO_NETWORK", raising=False)
    baity = bytes(range(256)) * 40
    pobacheno: dict[str, list[dict[str, str]]] = {"vydacha": [], "skhovyshche": []}
    adresy: dict[str, str] = {}

    class Vydacha(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            pobacheno["vydacha"].append(dict(self.headers.items()))
            self.send_response(302)
            self.send_header("Location", adresy["skhovyshche"] + "?t=1767225600.abc")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a: Any) -> None:
            pass

    class Skhovyshche(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            pobacheno["skhovyshche"].append(dict(self.headers.items()))
            diapazon = self.headers.get("Range")
            if diapazon:
                vid = int(diapazon.removeprefix("bytes=").split("-")[0])
                tilo = baity[vid:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {vid}-{len(baity) - 1}/{len(baity)}")
            else:
                tilo = baity
                self.send_response(200)
            self.send_header("Content-Length", str(len(tilo)))
            self.end_headers()
            self.wfile.write(tilo)

        def log_message(self, *a: Any) -> None:
            pass

    servery = [ThreadingHTTPServer(("127.0.0.1", 0), h) for h in (Vydacha, Skhovyshche)]
    for s in servery:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    adresy["skhovyshche"] = f"http://127.0.0.1:{servery[1].server_address[1]}/supriaha/{KLIUCH}"
    yield (f"http://127.0.0.1:{servery[0].server_address[1]}/v1/d/{KLIUCH}", baity, pobacheno)
    for s in servery:
        s.shutdown()
        s.server_close()


def test_kliuch_ne_yide_v_skhovyshche(vydacha_i_skhovyshche: Any, tmp_path: Path) -> None:
    """Ключ — лише видачі; `cdn.` за 302 його не бачить (сховище прочитало б його
    як спробу підпису). Докачка з `Range` доходить до `cdn.` через 302."""
    from nyshporka.sources.http import Fetcher

    adresa, baity, pobacheno = vydacha_i_skhovyshche
    f = Fetcher(headers={"Authorization": "Bearer sekret"})
    ciel = tmp_path / "text.nyshtext"
    assert f.download(adresa, ciel) == len(baity)
    assert ciel.read_bytes() == baity
    assert pobacheno["vydacha"][0].get("Authorization") == "Bearer sekret"
    assert "Authorization" not in pobacheno["skhovyshche"][0]

    # Обірване раніше: `.part` з половиною — докачка просить решту, і сховище
    # дістає `Range` уже після переадресації.
    pobacheno["skhovyshche"].clear()
    druhyi = tmp_path / "geom.nyshtext"
    druhyi.with_name(druhyi.name + ".part").write_bytes(baity[:1000])
    assert f.download(adresa, druhyi) == len(baity)
    assert druhyi.read_bytes() == baity
    assert pobacheno["skhovyshche"][0].get("Range") == "bytes=1000-"
    assert "Authorization" not in pobacheno["skhovyshche"][0]


def test_429_bez_normy_ne_norma(pul_429: Any, tmp_path: Path) -> None:
    """429 без `detail.norma` (rate limit `cdn.`, чужий проксі) — звичайна відмова,
    серію через нього не зупиняємо."""
    adresa, _ = pul_429("<html>Too Many Requests</html>", 901)
    with pytest.raises(A.AcceptError) as exc:
        A.fetch(adresa, tmp_path)
    assert not isinstance(exc.value, A.NormaVycherpana)
