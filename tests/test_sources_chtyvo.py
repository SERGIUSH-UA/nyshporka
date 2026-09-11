"""📖 Чтиво на shron.org: пошук по повному тексту, адреса твору, звірка файлів.

Тут перевіряється наш розбір, а не чужий сервер: відповіді DSpace записані у
фікстурах (`fixtures/sources/chtyvo_*.json` — обрізані справжні відповіді на
один твір), а клієнт — двійник, що пам'ятає, куди його питали.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.chtyvo import PAGE_MAX, ChtyvoSource, slug_of
from nyshporka.sources.http import Fetcher
from nyshporka.utils.pdftext import extract, judge

FX = Path(__file__).parent / "fixtures" / "sources"
SLUG = ("Zadorozhniuk_Andrii/Lytovski_statuty_v_Podilskii_hubernii_u_pershii_"
        "polovyni_XIX_st_danyna_tradytsii_chy_pravovi_rudymen")
UUID = "46bacfed-af93-42a0-be80-83d762bf1211"
LONG = "Podilska huberniia ta lytovski statuty u pershii polovyni XIX stolittia"


def _fx(name: str) -> Any:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def _item() -> dict[str, Any]:
    objs = _fx("chtyvo_search.json")["_embedded"]["searchResult"]["_embedded"]["objects"]
    return dict(objs[0]["_embedded"]["indexableObject"])


def _bundles(blob: bytes, name: str, *, size: int | None = None,
             md5: str | None = None) -> dict[str, Any]:
    """Бандли з одним файлом під підготовлений вміст — сума й розмір від нього."""
    data = _fx("chtyvo_bundles.json")
    for b in data["_embedded"]["bundles"]:
        if b["name"] == "ORIGINAL":
            bs = b["_embedded"]["bitstreams"]["_embedded"]["bitstreams"][0]
            bs["name"] = name
            bs["sizeBytes"] = len(blob) if size is None else size
            bs["checkSum"]["value"] = md5 or hashlib.md5(blob).hexdigest()
    return data


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник shron.org: відповідь за підрядком адреси й журнал запитів.

    Порядок ключів має значення: адреса бандлів містить адресу твору.
    """

    def __init__(self, routes: dict[str, Any], blob: bytes = b"") -> None:
        self.routes = routes
        self.blob = blob
        self.gets: list[str] = []
        self.streams: list[str] = []

    def get(self, url: str, **_: object) -> _Resp:
        self.gets.append(url)
        for key, body in self.routes.items():
            if key in url:
                return _Resp(body if isinstance(body, str) else json.dumps(body))
        raise AssertionError(f"неочікуваний запит: {url}")

    def stream(self, method: str, url: str) -> Any:
        self.streams.append(url)
        blob = self.blob

        @contextmanager
        def _cm() -> Any:
            class R:
                @staticmethod
                def raise_for_status() -> None:
                    pass

                @staticmethod
                def iter_bytes(chunk: int = 0) -> list[bytes]:
                    return [blob]
            yield R()
        return _cm()


def _src(api: _Api) -> ChtyvoSource:
    return ChtyvoSource(fetcher=Fetcher(base="https://shron.org", delay=0.0, client=api))


def _pdf(pages: list[str]) -> bytes:
    """Найпростіший PDF: сторінка на рядок; порожній рядок — сторінка без шару."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {5 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# ── пошук ────────────────────────────────────────────────────────────────────

def test_search_maps_metadata_to_hits() -> None:
    api = _Api({"/discover/search/objects": _fx("chtyvo_search.json")})
    hits = _src(api).search("литовські статути")

    assert len(hits) == 1
    h = hits[0]
    assert h.source == "chtyvo"
    assert h.ref == f"chtyvo:{SLUG}"
    assert h.title.startswith("Литовські статути")
    assert h.years == "2013"
    assert h.acquirable
    assert h.url == f"https://chtyvo.shron.org/authors/{SLUG}/"
    assert "PDF" in h.note
    # Межа відповіді видна в самій знахідці, а не лише в кількості рядків.
    assert "з 1 за запитом" in h.note


def test_page_never_exceeds_what_the_server_answers_honestly() -> None:
    """🔴 На `size=500` сервер каже, що всього знахідок сто, хоч їх 445."""
    api = _Api({"/discover/search/objects": _fx("chtyvo_search.json")})
    _src(api).search("метричні", limit=500)

    assert f"size={PAGE_MAX}&" in api.gets[0]
    assert "size=500" not in api.gets[0]
    assert "scope=9ac3a705-237c-4f5c-9995-9b4e834bffb5" in api.gets[0]


def test_query_goes_as_typed() -> None:
    """Зірочка й лапки — синтаксис пошуку сервера; їх не можна ні зрізати, ні
    загубити при кодуванні."""
    api = _Api({"/discover/search/objects": _fx("chtyvo_search.json")})
    _src(api).search('"метричні книги" Поділл*')

    assert "query=%22" in api.gets[0]
    assert "%2A" in api.gets[0]


def test_html_instead_of_json_is_a_refusal_not_zero() -> None:
    api = _Api({"/discover/search/objects": "<!doctype html><html>…"})
    with pytest.raises(SourceError):
        _src(api).search("статути")


def test_offline_is_a_refusal_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вимкнена мережа, що віддає порожній список, читалась би як «книги немає»."""
    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    with pytest.raises(SourceError):
        ChtyvoSource().search("статути")


# ── адреса твору ─────────────────────────────────────────────────────────────

def test_slug_is_read_from_every_accepted_form() -> None:
    assert slug_of(f"chtyvo:{SLUG}") == SLUG
    assert slug_of(f"https://chtyvo.shron.org/authors/{SLUG}/") == SLUG
    assert slug_of("https://chtyvo.org.ua/authors/Avtor/Tvir/") == "Avtor/Tvir"
    assert slug_of("https://chtyvo.shron.org/authors/Avtor/%D0%A2%D0%B2%D1%96%D1%80") \
        == "Avtor/Твір"
    assert slug_of(f"item:{UUID}") == ""
    assert slug_of("chtyvo:tilky_avtor") == ""


def test_page_address_is_resolved_through_dspace_not_fetched() -> None:
    """🔴 robots.txt сайту бібліотеки закриває все — туди не ходимо зовсім."""
    api = _Api({"/bundles": _fx("chtyvo_bundles.json"),
                "/discover/search/objects": _fx("chtyvo_search.json")})
    man = _src(api).manifest(f"https://chtyvo.shron.org/authors/{SLUG}/")

    assert man.title.startswith("Литовські статути")
    assert all("chtyvo." not in u for u in api.gets + api.streams)
    assert "%22chtyvo%3A" in api.gets[0], "слаг шукається фразою"


def test_near_slug_is_refused_with_the_page_address() -> None:
    """Пошук нечіткий: сусідній твір того самого автора не має стати нашим."""
    api = _Api({"/discover/search/objects": _fx("chtyvo_search.json")})
    with pytest.raises(SourceError) as exc:
        _src(api).manifest("chtyvo:Zadorozhniuk_Andrii/Inshyi_tvir")

    assert "не відновлено" in str(exc.value)
    assert "https://chtyvo.shron.org/authors/Zadorozhniuk_Andrii/Inshyi_tvir/" in str(exc.value)


def test_item_and_handle_addresses() -> None:
    api = _Api({"/bundles": _fx("chtyvo_bundles.json"), "/pid/find": _item(),
                f"/core/items/{UUID}": _item()})
    src = _src(api)

    assert src.manifest(f"item:{UUID}").title.startswith("Литовські статути")
    assert src.manifest("handle:shron/36564").title.startswith("Литовські статути")
    assert any("/pid/find?id=shron/36564" in u for u in api.gets)


def test_unknown_address_is_refused() -> None:
    with pytest.raises(SourceError):
        _src(_Api({})).manifest("file:knyha.pdf")


def test_manifest_counts_original_files_only() -> None:
    """Мініатюра — не файл твору; порахована, вона зробила б знаменник хибним."""
    api = _Api({"/bundles": _fx("chtyvo_bundles.json"), f"/core/items/{UUID}": _item()})
    man = _src(api).manifest(f"item:{UUID}")

    assert man.frames == 1
    assert man.bytes_estimate == 574061
    files = man.meta["files"]
    assert isinstance(files, list)
    assert files[0]["md5"] == "14b26131c4d5b040f4010431b7287fb5"
    assert man.meta["url"] == f"https://chtyvo.shron.org/authors/{SLUG}/"


# ── завантаження ─────────────────────────────────────────────────────────────

def _fetch_api(blob: bytes, name: str, **kw: Any) -> _Api:
    return _Api({"/bundles": _bundles(blob, name, **kw), f"/core/items/{UUID}": _item()},
                blob=blob)


def test_file_with_wrong_checksum_never_lands(tmp_path: Path) -> None:
    """🔴 Пошкоджений файл під правильним іменем ліг би в облік як книга."""
    api = _fetch_api(b"abc", "knyha.djvu", md5=hashlib.md5(b"xyz").hexdigest())
    res = _src(api).fetch(f"item:{UUID}", tmp_path)

    assert res.errors and "контрольна сума" in res.errors[0]
    assert not (tmp_path / "knyha.djvu").exists()
    assert res.frames == 0


def test_short_file_never_lands(tmp_path: Path) -> None:
    api = _fetch_api(b"abc", "knyha.djvu", size=10)
    res = _src(api).fetch(f"item:{UUID}", tmp_path)

    assert res.errors and "неповний" in res.errors[0]
    assert not (tmp_path / "knyha.djvu").exists()


def test_good_file_counts_and_repeat_skips(tmp_path: Path) -> None:
    api = _fetch_api(b"djvu-bytes", "knyha.djvu")
    src = _src(api)
    first = src.fetch(f"item:{UUID}", tmp_path)
    again = src.fetch(f"item:{UUID}", tmp_path)

    assert (first.frames, first.skipped, first.errors) == (1, 0, [])
    assert (again.frames, again.skipped, again.errors) == (0, 1, [])
    assert len(api.streams) == 1, "звірений файл качався вдруге"


def test_passport_carries_book_and_checksum(tmp_path: Path) -> None:
    blob = b"djvu-bytes"
    _src(_fetch_api(blob, "knyha.djvu")).fetch(f"item:{UUID}", tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))

    assert meta["book"]["slug"] == SLUG
    assert meta["book"]["dspace_item"] == UUID
    assert meta["files"][0]["md5"] == hashlib.md5(blob).hexdigest()
    assert meta["text_layer"]["knyha.djvu"]["verdict"] == "not_pdf"


def test_book_without_pdf_says_regex_will_not_see_it(tmp_path: Path) -> None:
    res = _src(_fetch_api(b"djvu-bytes", "knyha.djvu")).fetch(f"item:{UUID}", tmp_path)

    assert any("немає PDF" in n for n in res.notes)
    assert not res.errors, "відсутність шару — не збій завантаження"


def test_pdf_gets_its_text_layer(tmp_path: Path) -> None:
    res = _src(_fetch_api(_pdf([LONG, LONG]), "knyha.pdf")).fetch(f"item:{UUID}", tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))

    assert res.frames == 1 and not res.errors and not res.notes
    assert meta["text_layer"]["knyha.pdf"]["verdict"] == "ok"
    assert "lytovski statuty" in (tmp_path / "knyha.pdf.text" / "p0002.txt").read_text(
        encoding="utf-8")


def test_asking_for_frames_is_refused_not_ignored(tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        _src(_Api({})).fetch(f"item:{UUID}", tmp_path, frames=(1, 5))


def test_browse_is_a_refusal() -> None:
    with pytest.raises(SourceError):
        ChtyvoSource().browse()


def test_chtyvo_is_in_the_registry_out_of_the_box() -> None:
    """Джерело, якого немає в реєстрі, не бере участі в жодному знаменнику."""
    from nyshporka.sources.registry import load

    src = load().get("chtyvo")
    assert src is not None
    assert {"search", "manifest", "fetch"} <= set(src.caps)
    assert src.catalog_source()[0] == "live"  # type: ignore[attr-defined]


# ── текстовий шар ────────────────────────────────────────────────────────────

def test_text_layer_is_written_page_by_page(tmp_path: Path) -> None:
    """Знахідка регексу несе лише файл і рядок — сторінку видно з імені файла."""
    pdf = tmp_path / "k.pdf"
    pdf.write_bytes(_pdf([LONG, LONG + " druha storinka"]))
    layer = extract(pdf)

    assert (layer.pages, layer.pages_with_text, layer.verdict) == (2, 2, "ok")
    assert "druha storinka" in (tmp_path / "k.pdf.text" / "p0002.txt").read_text(
        encoding="utf-8")


def test_scan_without_text_layer_writes_nothing(tmp_path: Path) -> None:
    """🔴 Порожній текст на місці сторінки дав би регексу хибний нуль."""
    pdf = tmp_path / "skan.pdf"
    pdf.write_bytes(_pdf(["", ""]))
    layer = extract(pdf)

    assert (layer.pages, layer.pages_with_text, layer.verdict) == (2, 0, "image")
    assert not (tmp_path / "skan.pdf.text").exists()
    assert "0 з 2" in layer.explain("skan.pdf")


def test_partial_layer_keeps_real_text_and_names_the_share(tmp_path: Path) -> None:
    pdf = tmp_path / "chastkovo.pdf"
    pdf.write_bytes(_pdf([LONG, "", ""]))
    layer = extract(pdf)

    assert layer.verdict == "image"
    assert (tmp_path / "chastkovo.pdf.text" / "p0001.txt").exists()
    assert not (tmp_path / "chastkovo.pdf.text" / "p0002.txt").exists()
    assert "1 з 3" in layer.explain("chastkovo.pdf")


def test_stale_pages_of_an_earlier_extract_are_removed(tmp_path: Path) -> None:
    pdf = tmp_path / "k.pdf"
    pdf.write_bytes(_pdf([LONG, LONG]))
    extract(pdf)
    pdf.write_bytes(_pdf([LONG]))
    extract(pdf)

    assert not (tmp_path / "k.pdf.text" / "p0002.txt").exists()


def test_broken_fonts_are_flagged() -> None:
    """Кирилиця в латиниці-1 — формально літери, тож `isalpha` її пропускав би."""
    assert judge(["Ïîä³ëüñüêà ãóáåðí³ÿ òà ëèòîâñüê³ ñòàòóòè " * 3]) == "garbage"
    assert judge(["Подільська губернія та литовські статути " * 3]) == "ok"
