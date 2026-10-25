"""📑 Описи фондів у PDF: каталог зі сторінки, шифра → файл, завантаження, TLS-режим.

Мережі тут немає. Сторінка-каталог — вигадана, у тому ж вигляді, що й жива
(знято 25.10.2026): windows-1251, суперечливий другий `<meta>`, заголовок
«Фонд N» і рядки «Опис …» з посиланнями, назви файлів нерегулярні (латинське
«F.», кириличне «Ф.», римські цифри, частини «4-1»). Фонди вигадані.
"""
from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from nyshporka.sources import opysy as O
from nyshporka.sources.base import SourceError, need
from nyshporka.sources.cfclient import ShieldError

PAGE = """<!DOCTYPE html>
<html><head><meta charset="windows-1251">
<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1" /></head><body>
<h2>Довідковий апарат</h2>
<a href="pdf/Putivnyk.pdf"> Файл в форматі pdf (2,4 MB)</a>
<b>Фонд 501</b> «Вигаданий магістрат, м. Лісове» <br>
Опис 1&nbsp;&nbsp;&nbsp;<a href="pdf/F. 501 op. 1.pdf" target="_blank"> Файл в форматі pdf (1,5 MB)</a> <br>
Опис 3<a href="pdf/F. 501, op. XVI.pdf" target="_blank"> Файл в форматі pdf (0,5 MB)</a><br>
Опис 4 т.1 <a href="pdf/F. 501 op.4-1.pdf" target="_blank"> Файл в форматі pdf (2 MB)</a> <br>
Опис 4 т.2 <a href="pdf/F. 501 op.4-2.pdf" target="_blank"> Файл в форматі pdf (2 MB)</a> <br>
Опис 7а<a href="pdf/F. 501 ор. 7а.pdf" target="_blank"> Файл в форматі pdf (3 MB)</a><br>
<p></p>
<b>Фонд 502 </b> «Інша установа» <br>
Опис 3 <a href="pdf/Ф. 502, оп. 3.pdf" target="_blank"> Файл в форматі pdf (600 KB)</a><br>
<p></p>
<b>Фонд У-9</b> «Колекція» <br>
Опис 1 <a href="pdf/F. У-9.pdf" target="_blank"> Файл в форматі pdf (0,6 MB)</a><br>
<b>Колекція мікрофільмів №9</b> Матеріали <br>
Опис 1 <a href="pdf/KMF-9 op. 1.pdf" target="_blank"> Файл в форматі pdf (3 MB)</a><br>
</body></html>"""

PAGE_BYTES = PAGE.encode("cp1251")
PDF = b"%PDF-1.4\n" + b"x" * 991            # 1000 байтів


class _R:
    def __init__(self, content: bytes, status: int = 200,
                 headers: dict[str, str] | None = None) -> None:
        self.content = content
        self.status_code = status
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="replace")


class FakeSite:
    """Двійник Fetcher + клієнта: сторінка, файли, лічильник запитів."""

    def __init__(self, files: dict[str, bytes] | None = None, *,
                 page: bytes = PAGE_BYTES, page_status: int = 200) -> None:
        self.files = files if files is not None else {}
        self.page = page
        self.page_status = page_status
        self.limiter = None
        self.gets: list[str] = []
        self.downloads: list[str] = []
        self.cut: int | None = None            # обрізати завантаження до N байтів

    def get(self, url: str, client: Any = None, **_kw: Any) -> _R:
        self.gets.append(url)
        if self.page_status >= 400:
            raise O.HttpError(f"{url}: HTTP {self.page_status}", status=self.page_status,
                              body="Access Denied errors.edgesuite.net")
        return _R(self.page)

    @contextmanager
    def client(self) -> Iterator[Any]:
        site = self

        class C:
            def get(self, url: str, headers: dict[str, str] | None = None) -> _R:
                site.gets.append(url)
                blob = site.files.get(url)
                if blob is None:
                    return _R(b"<html>500</html>", 500)
                return _R(blob[:5], 206, {"Content-Range": f"bytes 0-4/{len(blob)}"})

        yield C()

    def download(self, url: str, dest: Path, *, on_chunk: Any = None,
                 max_bytes: int = 0, **_kw: Any) -> int:
        self.downloads.append(url)
        blob = self.files[url]
        if self.cut is not None:
            blob = blob[:self.cut]
        dest.write_bytes(blob)
        if on_chunk:
            on_chunk(len(blob))
        return len(blob)


HOST = "https://tsdial.example.test"
SITE = types.SimpleNamespace(url=HOST, page="index5.html", shield="tls")


def _src(tmp_path: Path | None, fake: FakeSite | None = None) -> tuple[O.OpysySource, FakeSite]:
    fake = fake or FakeSite()
    src = O.OpysySource(tmp_path, site=SITE, fetcher=fake)    # type: ignore[arg-type]
    return src, fake


def _url(name: str) -> str:
    return O.OpysySource(None, site=SITE)._url(name)    # type: ignore[arg-type]


# ── сторінка-каталог ─────────────────────────────────────────────────────────

def test_page_is_read_as_cp1251_despite_the_second_meta() -> None:
    text = O.decode_page(PAGE_BYTES)
    assert "Вигаданий магістрат" in text and "�" not in text


def test_undecodable_page_is_refused_not_replaced() -> None:
    raw = b'<meta charset="utf-8">\x93 bad'
    with pytest.raises(SourceError, match="не читається як utf-8"):
        O.decode_page(raw)


def test_catalog_rows_fond_titles_and_sizes() -> None:
    es = O.parse_catalog(O.decode_page(PAGE_BYTES))
    by = {(e.fond, e.label): e for e in es}
    assert set(by) == {("501", "1"), ("501", "3"), ("501", "4 т.1"), ("501", "4 т.2"),
                       ("501", "7а"), ("502", "3"), ("У-9", "1"), ("KMF-9", "1")}
    e = by[("501", "1")]
    assert e.fond_title == "«Вигаданий магістрат, м. Лісове»"
    assert e.name == "F. 501 op. 1.pdf" and e.size_hint == int(1.5 * (1 << 20))
    assert by[("502", "3")].size_hint == 600 * 1024            # «(600 KB)»
    assert "Putivnyk.pdf" not in {x.name for x in es}           # довідник — не опис


def test_page_without_rows_is_refused_not_an_empty_catalog() -> None:
    with pytest.raises(SourceError, match="не знайдено жодного опису"):
        O.parse_catalog("<html><body>порожньо</body></html>")


# ── шифра → файл ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,name", [
    ("501/1", "F. 501 op. 1.pdf"),
    ("501-1", "F. 501 op. 1.pdf"),
    ("ЦДІАЛ 501-1", "F. 501 op. 1.pdf"),
    ("ф.501 оп.1", "F. 501 op. 1.pdf"),
    ("F. 501 op. 3", "F. 501, op. XVI.pdf"),        # підпис «3», у файлі римське — ключ із підпису
    ("501/XVI", "F. 501, op. XVI.pdf"),             # римське з імені файла = 16 ≠ 3, але назване
    ("501-4-1", "F. 501 op.4-1.pdf"),
    ("501/4 т.2", "F. 501 op.4-2.pdf"),
    ("501 7а", "F. 501 ор. 7а.pdf"),                # кириличне «ор.» в імені
    ("502-3", "Ф. 502, оп. 3.pdf"),                 # кирилична «Ф.»
    ("У-9", "F. У-9.pdf"),
    ("KMF-9/1", "KMF-9 op. 1.pdf"),
    ("file:F. 501 op. 1.pdf", "F. 501 op. 1.pdf"),
])
def test_ref_resolves_through_the_page_not_by_guessing(ref: str, name: str) -> None:
    src, _ = _src(None)
    assert src._resolve(ref).name == name


def test_unknown_fond_and_opys_say_online_has_none_and_what_is() -> None:
    src, _ = _src(None)
    with pytest.raises(SourceError, match="фонду 999 немає на сторінці-каталозі"):
        src._resolve("999/1")
    with pytest.raises(SourceError, match=r"опису 99 фонду 501 онлайн немає.*501/1"):
        src._resolve("501/99")


def test_ambiguous_opys_lists_the_parts() -> None:
    src, _ = _src(None)
    with pytest.raises(SourceError, match=r"онлайн немає.*4 т\.1.*4 т\.2"):
        src._resolve("501/4")
    with pytest.raises(SourceError, match="назвіть один"):
        src._resolve("501")


def test_case_number_is_not_silently_dropped() -> None:
    src, _ = _src(None)
    with pytest.raises(SourceError, match=r"шифру СПРАВИ.*nysh get cdial-opysy 501/1"):
        src._resolve("ЦДІАЛ 501-1-115")


def test_cyrillic_name_goes_to_server_as_utf8_percent_encoding() -> None:
    assert _url("Ф. 502, оп. 3.pdf") == \
        f"{HOST}/pdf/%D0%A4.%20502%2C%20%D0%BE%D0%BF.%203.pdf"


# ── кеш каталогу ─────────────────────────────────────────────────────────────

def test_catalog_is_cached_between_instances(tmp_path: Path) -> None:
    src, fake = _src(tmp_path)
    assert len(src.entries()) == 8
    src2, _ = _src(tmp_path, fake)
    assert len(src2.entries()) == 8
    assert len([g for g in fake.gets if g.endswith("index5.html")]) == 1


def test_stale_catalog_is_used_with_a_note_when_refresh_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, _ = _src(tmp_path)
    src.entries()
    monkeypatch.setattr(O, "CATALOG_TTL_DAYS", -1)       # кеш прострочено
    broken = FakeSite(page_status=500)
    src2, _ = _src(tmp_path, broken)
    assert len(src2.entries()) == 8
    assert "каталог із кешу" in src2._note


def test_no_cache_and_site_refuses_is_an_honest_error_naming_akamai(tmp_path: Path) -> None:
    src, _ = _src(tmp_path, FakeSite(page_status=403))
    with pytest.raises(SourceError, match="Akamai відсік"):
        src.entries()


def test_offline_environment_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.sources import http

    monkeypatch.setenv(http.ENV_OFFLINE, "1")
    src = O.OpysySource(tmp_path, site=SITE)       # type: ignore[arg-type]
    with pytest.raises(SourceError, match="мережу вимкнено"):
        src.entries()


# ── browse / manifest / fetch ────────────────────────────────────────────────

def test_browse_root_and_fond() -> None:
    src, _ = _src(None)
    root = src.browse()
    assert {n.ref for n in root} == {"501", "502", "У-9", "KMF-9"}
    assert "описів: 5" in next(n.label for n in root if n.ref == "501")
    kids = src.browse("501")
    assert [n.ref for n in kids][:2] == ["501/1", "501/3"]
    assert all(n.kind == "file" for n in kids)
    with pytest.raises(SourceError, match="опису онлайн немає"):
        src.browse("999")


def test_manifest_takes_size_from_content_range_and_checks_pdf() -> None:
    fake = FakeSite({_url("F. 501 op. 1.pdf"): PDF, _url("F. 501, op. XVI.pdf"): b"<html>no"})
    src, _ = _src(None, fake)
    m = src.manifest("501/1")
    assert m.frames == 1 and m.bytes_estimate == len(PDF)
    assert m.meta["text_layer"] is False and m.meta["fond"] == "501"
    assert str(m.meta["suggested_dest"]).startswith("data/raw/cdial_501")
    with pytest.raises(SourceError, match="не схожа на PDF"):
        src.manifest("501/XVI")


def test_missing_file_on_site_says_500_means_no_such_name() -> None:
    src, _ = _src(None, FakeSite({}))
    with pytest.raises(SourceError, match=r"500.*немає під цим іменем"):
        src.manifest("501/1")


def test_fetch_writes_pdf_and_passport_then_skips_the_second_time(tmp_path: Path) -> None:
    fake = FakeSite({_url("F. 501 op. 1.pdf"): PDF})
    src, _ = _src(None, fake)
    dest = tmp_path / "cdial_501"
    res = src.fetch("501/1", dest)
    assert res.errors == [] and res.frames == 1 and res.bytes == len(PDF)
    assert (dest / "F. 501 op. 1.pdf").read_bytes() == PDF
    meta = (dest / "meta.json").read_text(encoding="utf-8")
    assert '"cdial_opysy"' in meta and '"text_layer": false' in meta and "sha1" in meta
    assert any("без текстового шару" in n for n in res.notes)
    again = src.fetch("501/1", dest)
    assert again.skipped == 1 and again.frames == 0 and len(fake.downloads) == 1


def test_short_download_does_not_stay_under_the_right_name(tmp_path: Path) -> None:
    fake = FakeSite({_url("F. 501 op. 1.pdf"): PDF})
    fake.cut = 400
    src, _ = _src(None, fake)
    res = src.fetch("501/1", tmp_path)
    assert res.frames == 0 and "400 байт замість 1000" in res.errors[0]
    assert not list(tmp_path.glob("*.pdf"))


def test_frames_range_is_refused(tmp_path: Path) -> None:
    src, _ = _src(None, FakeSite({_url("F. 501 op. 1.pdf"): PDF}))
    with pytest.raises(SourceError, match="один PDF"):
        src.fetch("501/1", tmp_path, frames=(1, 5))


def test_no_search_and_no_pretending(tmp_path: Path) -> None:
    src, _ = _src(None)
    assert "search" not in src.caps
    with pytest.raises(SourceError, match="пошуку за текстом"):
        src.search("501")
    with pytest.raises(SourceError, match="не вміє search"):
        need(src, "search")


# ── явний режим TLS браузера ─────────────────────────────────────────────────

def test_tls_client_without_curl_cffi_is_an_error_with_the_extra(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.sources import cfclient

    monkeypatch.setattr(cfclient, "have_curl_cffi", lambda: False)
    with pytest.raises(ShieldError, match=r"nyshporka\[cfshield\]"):
        cfclient.TlsClient()
    from nyshporka.sources.http import Fetcher

    with pytest.raises(ShieldError, match="запасного шляху немає"):
        Fetcher(tls=True).get(f"{HOST}/x")


class _FakeCffiResp:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.content = body
        self.headers = headers or {}

    def iter_content(self, chunk_size: int = 1024) -> Iterator[bytes]:
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self) -> None:
        pass


@pytest.fixture
def fake_cffi(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"sessions": [], "calls": []}

    class RequestsError(Exception):
        pass

    class Session:
        def __init__(self, **kw: Any) -> None:
            seen["sessions"].append(kw)

        def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeCffiResp:
            return self.request("GET", url, headers=headers)

        def request(self, method: str, url: str, headers: dict[str, str] | None = None,
                    stream: bool = False) -> _FakeCffiResp:
            seen["calls"].append((method, url, headers, stream))
            if "boom" in url:
                raise RequestsError("handshake")
            if headers and headers.get("Range", "").startswith("bytes=") \
                    and not headers["Range"].startswith("bytes=0-"):
                start = int(headers["Range"][6:-1])
                return _FakeCffiResp(206, PDF[start:], {"Content-Range":
                                                        f"bytes {start}-{len(PDF) - 1}/{len(PDF)}"})
            return _FakeCffiResp(200, PDF)

    mod = types.ModuleType("curl_cffi")
    req = types.ModuleType("curl_cffi.requests")
    req.Session = Session                                            # type: ignore[attr-defined]
    req.errors = types.SimpleNamespace(RequestsError=RequestsError)  # type: ignore[attr-defined]
    mod.requests = req                                               # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", mod)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", req)
    return seen


def test_fetcher_tls_mode_impersonates_chrome_without_a_foreign_user_agent(
        fake_cffi: dict[str, Any]) -> None:
    from nyshporka.sources.cfclient import IMPERSONATE
    from nyshporka.sources.http import Fetcher

    f = Fetcher(base=HOST, delay=0.0, attempts=1, tls=True,
                headers={"Referer": f"{HOST}/index5.html"})
    r = f.get(f"{HOST}/pdf/x.pdf")
    assert r.status_code == 200 and r.content == PDF
    kw = fake_cffi["sessions"][0]
    assert kw["impersonate"] == IMPERSONATE
    assert kw["headers"]["Referer"] == f"{HOST}/index5.html"
    assert not any(k.lower() == "user-agent" for k in kw["headers"])


def test_tls_transport_error_is_httpx_transport_error(fake_cffi: dict[str, Any]) -> None:
    from nyshporka.sources.cfclient import TlsClient

    c = TlsClient()
    with pytest.raises(httpx.TransportError, match="handshake"):
        c.get(f"{HOST}/boom")


def test_tls_download_resumes_from_part_with_range(
        fake_cffi: dict[str, Any], tmp_path: Path) -> None:
    from nyshporka.sources.http import Fetcher

    dest = tmp_path / "f.pdf"
    (tmp_path / "f.pdf.part").write_bytes(PDF[:300])
    f = Fetcher(base=HOST, delay=0.0, attempts=1, tls=True)
    got = f.download(f"{HOST}/pdf/f.pdf", dest, max_bytes=len(PDF))
    assert got == len(PDF) and dest.read_bytes() == PDF
    assert fake_cffi["calls"][-1][2] == {"Range": "bytes=300-"}


def test_tls_403_from_akamai_comes_out_as_http_error_with_status(
        fake_cffi: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import curl_cffi.requests as cr

    from nyshporka.sources.http import Fetcher

    monkeypatch.setattr(
        cr.Session, "request",
        lambda self, m, u, headers=None, stream=False:
        _FakeCffiResp(403, b"Access Denied errors.edgesuite.net"))
    f = Fetcher(base=HOST, delay=0.0, attempts=1, tls=True)
    with pytest.raises(O.HttpError) as ei:
        f.get(f"{HOST}/pdf/x.pdf")
    assert ei.value.status == 403 and "Access Denied" in ei.value.body


def test_akamai_marks() -> None:
    from nyshporka.sources.cfclient import akamai_denied

    assert akamai_denied("<TITLE>Access Denied</TITLE>")
    assert not akamai_denied("<html>усе добре</html>")


# ── реєстр і пак ─────────────────────────────────────────────────────────────

def test_pack_describes_the_host_as_tls_shielded() -> None:
    from nyshporka.archives import active

    sites = dict(active().sites("opysy"))
    s = sites["CDIAL"]
    assert s.shield == "tls" and s.page == "index5.html" and s.source_id == "cdial-opysy"


def test_registered_with_card_and_browse_manifest_fetch() -> None:
    from nyshporka.sources.registry import load

    src = load(None).get("cdial-opysy")
    assert src is not None
    assert {"browse", "manifest", "fetch"} <= set(src.caps)
