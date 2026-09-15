"""🗃 Internet Archive: пошук по тексту з листом і кропом, текст по листах, кадри.

Перевіряється наш розбір, а не archive.org: відповіді записані у фікстурах
(`fixtures/sources/ia_*` — обрізані справжні відповіді 15.09.2026 на «Креницька»
у «Свободі» і «Шумилова» у ПЕВ; адреси завантажувачів із метаданих прибрано),
клієнт — двійник, що пам'ятає, куди його питали.
"""
from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources import ia as IA
from nyshporka.sources.base import SourceError
from nyshporka.sources.http import Fetcher
from nyshporka.sources.ia import IaSource, address_of, parse_query

FX = Path(__file__).parent / "fixtures" / "sources"
JP2_1910 = "Svoboda-1910-01%2fSvoboda-1910-01_jp2.zip%2fSvoboda-1910-01_jp2%2fSvoboda-1910-01_"
JP2_PEV = "podillya_vidomosti%2fPEV.1885_jp2.zip%2fPEV.1885_jp2%2fPEV.1885_"


def _fx(name: str) -> Any:
    return json.loads((FX / name).read_text(encoding="utf-8"))


class _Resp:
    def __init__(self, body: str | bytes) -> None:
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.text = body if isinstance(body, str) else ""
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник archive.org: відповідь за підрядком адреси, журнал запитів.

    Порядок ключів має значення: перший збіг виграє.
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
                if isinstance(body, (str, bytes)):
                    return _Resp(body)
                return _Resp(json.dumps(body, ensure_ascii=False))
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


def _src(api: _Api) -> IaSource:
    return IaSource(fetcher=Fetcher(base="https://archive.org", delay=0.0, client=api))


def _svoboda_routes(**over: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {
        "page_production": _fx("ia_fts_svoboda.json"),
        "/metadata/svoboda_newspaper": _fx("ia_metadata_collection.json"),
        "/metadata/Svoboda-": _fx("ia_metadata_svoboda_1910.json"),
        "item_id=Svoboda-1910-01": _fx("ia_inside_1910.json"),
        "inside.php": {"matches": []},
    }
    routes.update(over)
    return routes


def _pev_routes() -> dict[str, Any]:
    return {
        "page_production": _fx("ia_fts_pev.json"),
        "/metadata/podillya_vidomosti": _fx("ia_metadata_pev.json"),
        "doc=PEV.1885&": _fx("ia_inside_pev.json"),
        "inside.php": {"matches": []},
    }


# ── розбір запиту й адреси ───────────────────────────────────────────────────

def test_scope_and_years_are_cut_out_of_the_words() -> None:
    q = parse_query('"Марію Креницьку" in:svoboda_newspaper year:1900-1920')
    assert (q.text, q.scope, q.year_from, q.year_to) == (
        '"Марію Креницьку"', "svoboda_newspaper", "1900", "1920")
    assert parse_query("Балта year:1910").year_to == "1910"


def test_every_accepted_address_form() -> None:
    assert address_of("ia:Svoboda-1910-01") == ("Svoboda-1910-01", "")
    assert address_of("ia:podillya_vidomosti/PEV.1900") == ("podillya_vidomosti", "PEV.1900")
    assert address_of("https://archive.org/details/Svoboda-1910-01/page/n2/mode/1up?q=x") \
        == ("Svoboda-1910-01", "")
    assert address_of("https://archive.org/details/podillya_vidomosti/PEV.1900/page/n521") \
        == ("podillya_vidomosti", "PEV.1900")
    with pytest.raises(SourceError):
        address_of("chtyvo:Avtor/Tvir")


# ── пошук ────────────────────────────────────────────────────────────────────

def test_every_occurrence_gets_its_leaf_and_crop() -> None:
    """🔴 Лист з inside.php — індекс jp2 без зсуву (звірено оком 15.09.2026)."""
    api = _Api(_svoboda_routes())
    hits = _src(api).search("Креницька in:svoboda_newspaper")

    placed = [h for h in hits if h.page is not None]
    assert [h.page for h in placed] == [2, 2], "два входження на листі 2"
    h = placed[0]
    assert h.ref == "ia:Svoboda-1910-01"
    assert h.acquirable
    assert f"{JP2_1910}0002.jp2/" in h.crop_url
    assert h.crop_url.startswith("https://iiif.archive.org/image/iiif/3/")
    assert "/page/n2/" in h.url
    assert placed[0].crop_url != placed[1].crop_url
    assert "%22collection%22" in api.gets[1], "межа — колекція, бо так каже її mediatype"


def test_the_denominator_travels_with_every_hit() -> None:
    hits = _src(_Api(_svoboda_routes())).search("Креницька in:svoboda_newspaper")

    assert hits and all("з 3 документів за запитом" in h.note for h in hits)
    assert all("лише точне слово" in h.note for h in hits)


def test_document_without_a_box_is_still_a_hit_and_says_why() -> None:
    hits = _src(_Api(_svoboda_routes())).search("Креницька in:svoboda_newspaper")
    bare = [h for h in hits if h.page is None]

    assert {h.ref for h in bare} == {"ia:Svoboda-1986-116", "ia:Svoboda-1977-075"}
    assert all("рамки немає" in h.note and not h.crop_url for h in bare)


def test_multi_document_record_takes_the_doc_from_the_file_name() -> None:
    api = _Api(_pev_routes())
    hits = _src(api).search("Шумилова in:podillya_vidomosti")

    pev1885 = [h for h in hits if h.ref == "ia:podillya_vidomosti/PEV.1885"]
    assert [h.page for h in pev1885] == [807, 1437]
    assert f"{JP2_PEV}0807.jp2/" in pev1885[0].crop_url
    assert "/details/podillya_vidomosti/PEV.1885/page/n807/" in pev1885[0].url
    assert "%22identifier%22" in api.gets[1], "запис — не колекція"


def test_year_of_a_document_comes_from_its_name_not_the_record() -> None:
    """🪤 У записі ПЕВ `year` один на всі томи — 1862."""
    hits = _src(_Api(_pev_routes())).search("Шумилова in:podillya_vidomosti")
    years = {h.ref.rsplit("/", 1)[-1]: h.years for h in hits}

    assert years["PEV.1885"] == "1885"
    assert years["PEV.1880"] == "1880"


def test_shifted_numbering_gives_no_crop() -> None:
    inside = _fx("ia_inside_1910.json")
    inside["leaf0_missing"] = True
    hits = _src(_Api(_svoboda_routes(**{"item_id=Svoboda-1910-01": inside}))).search(
        "Креницька in:svoboda_newspaper")
    first = hits[0]

    assert first.page is None and not first.crop_url
    assert "leaf0_missing" in first.note


def test_word_box_without_an_edge_falls_back_to_the_paragraph() -> None:
    """🪤 Сервер віддає рамку слова без правого краю — раніше це валило весь пошук."""
    inside = {"matches": [{"text": "a <IA_FTS_MATCH>Креницька</IA_FTS_MATCH> b", "par": [
        {"l": 100, "t": 200, "r": 900, "b": 400, "page": 5, "page_width": 1000,
         "page_height": 2000, "boxes": [{"l": 300, "t": 250, "b": 300, "page": 5}]},
        {"page": 6, "boxes": [{"l": 10, "t": 20, "b": 30, "page": 6}]}]}]}
    hits = _src(_Api(_svoboda_routes(**{"item_id=Svoboda-1910-01": inside}))).search(
        "Креницька in:svoboda_newspaper")
    by_leaf = {h.page: h for h in hits if h.page is not None}

    assert f"{JP2_1910}0005.jp2/" in by_leaf[5].crop_url
    assert "кроп по абзацу" in by_leaf[5].note
    assert by_leaf[6].crop_url == "" and "кроп не будую" in by_leaf[6].note


def test_word_box_without_a_left_edge_keeps_its_leaf_and_crop() -> None:
    """🔴 Ключ дедуплікації рахувався з `box["l"]` ДО запасної рамки абзацу, тож
    рамка без лівого краю випадала разом із листом (верифікатор 0.16.0)."""
    inside = {"matches": [{"text": "a <IA_FTS_MATCH>Креницька</IA_FTS_MATCH> b", "par": [
        {"l": 100, "t": 200, "r": 900, "b": 400, "page": 5, "page_width": 1000,
         "page_height": 2000, "boxes": [{"t": 250, "r": 400, "b": 300, "page": 5}]}]}]}
    hits = _src(_Api(_svoboda_routes(**{"item_id=Svoboda-1910-01": inside}))).search(
        "Креницька in:svoboda_newspaper")
    by_leaf = {h.page: h for h in hits if h.page is not None}

    assert 5 in by_leaf, "лист мусить лишитись у знахідці"
    assert f"{JP2_1910}0005.jp2/" in by_leaf[5].crop_url
    assert "кроп по абзацу" in by_leaf[5].note


def test_a_single_year_is_that_year_not_everything_before_it() -> None:
    """🔴 `{рік: "gte", рік: "lte"}` — один ключ: `year:1910` шукав «до 1910»."""
    from urllib.parse import parse_qs, urlparse

    def year_filter(q: str) -> Any:
        api = _Api(_svoboda_routes())
        _src(api).search(q)
        url = next(u for u in api.gets if "filter_map" in u)
        return json.loads(parse_qs(urlparse(url).query)["filter_map"][0])["year"]

    assert year_filter("Креницька in:svoboda_newspaper year:1910") == {"1910": "inc"}
    assert year_filter("Креницька in:svoboda_newspaper year:1900-1910") == {
        "1900": "gte", "1910": "lte"}


def test_positions_are_asked_only_for_the_first_documents(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(IA, "POSITION_MAX", 1)
    api = _Api(_svoboda_routes())
    hits = _src(api).search("Креницька in:svoboda_newspaper")

    assert sum("inside.php" in u for u in api.gets) == 1
    assert any("позицію не запитано" in h.note for h in hits)


def test_years_go_to_the_server_filter() -> None:
    api = _Api(_svoboda_routes())
    _src(api).search("Креницька year:1900-1920")

    assert "%22year%22" in api.gets[0]
    assert "%221900%22%3A+%22gte%22" in api.gets[0]


@pytest.mark.parametrize("q", [
    "Креницьк* in:svoboda_newspaper",
    "Креницька OR Креницьку",
    "Kреницька",                           # латинська K
    "Jersey in:svoboda_newspaper",
])
def test_syntax_the_index_does_not_know_is_a_refusal_not_zero(q: str) -> None:
    """🔴 Нуль на зірку чи OR читався б як «слова в текстах немає»."""
    api = _Api(_svoboda_routes())
    with pytest.raises(SourceError):
        _src(api).search(q)
    assert not any("page_production" in u for u in api.gets)


def test_latin_outside_a_blind_scope_is_searched() -> None:
    api = _Api(_svoboda_routes())
    _src(api).search("Jersey")

    assert any("page_production" in u for u in api.gets)


def test_scope_that_does_not_exist_is_refused() -> None:
    """🪤 На неіснуючий запис сервер віддає `{}`, а пошук з такою межею — 0."""
    api = _Api({"/metadata/nemaye_takoho": "{}"})
    with pytest.raises(SourceError, match="немає запису"):
        _src(api).search("Креницька in:nemaye_takoho")


def test_html_instead_of_json_is_a_refusal_not_zero() -> None:
    with pytest.raises(SourceError):
        _src(_Api({"page_production": "<!doctype html><html>…"})).search("Креницька")


def test_offline_is_a_refusal_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    with pytest.raises(SourceError):
        IaSource().search("Креницька")


# ── маніфест ─────────────────────────────────────────────────────────────────

def _scandata(leaves: list[tuple[int, bool]]) -> str:
    pages = "".join(f'<page leafNum="{n}"><addToAccessFormats>{str(ok).lower()}'
                    f"</addToAccessFormats></page>" for n, ok in leaves)
    return f"<book><pageData>{pages}</pageData></book>"


def test_manifest_counts_leaves_from_the_scan() -> None:
    api = _Api({"/metadata/Svoboda-1910-01": _fx("ia_metadata_svoboda_1910.json"),
                "_scandata.xml": (FX / "ia_scandata_1910.xml").read_text(encoding="utf-8")})
    man = _src(api).manifest("ia:Svoboda-1910-01")

    assert man.frames == 8
    assert man.bytes_estimate == 1036017
    assert man.meta["doc"] == "Svoboda-1910-01"


def test_leaf_left_out_of_access_formats_is_not_counted() -> None:
    api = _Api({"/metadata/podillya_vidomosti": _fx("ia_metadata_pev.json"),
                "PEV.1900_scandata.xml": _scandata([(0, True), (1, False), (2, True)])})
    man = _src(api).manifest("ia:podillya_vidomosti/PEV.1900")

    assert man.frames == 2
    assert man.meta["leaves"] == [0, 2]


def test_record_with_many_documents_needs_the_doc_named() -> None:
    api = _Api({"/metadata/podillya_vidomosti": _fx("ia_metadata_pev.json")})
    with pytest.raises(SourceError) as exc:
        _src(api).manifest("ia:podillya_vidomosti")

    assert "ia:podillya_vidomosti/PEV.1882" in str(exc.value)


# ── текст ────────────────────────────────────────────────────────────────────

def _text_api(blob: bytes, *, size: int | None = None, md5: str | None = None,
              scandata: str | None = None) -> _Api:
    md = copy.deepcopy(_fx("ia_metadata_svoboda_1910.json"))
    for f in md["files"]:
        if f["name"] == "Svoboda-1910-01_djvu.xml":
            f["size"] = str(len(blob) if size is None else size)
            f["md5"] = md5 or hashlib.md5(blob).hexdigest()
    return _Api({"/metadata/Svoboda-1910-01": md,
                 "_scandata.xml": scandata if scandata is not None
                 else (FX / "ia_scandata_1910.xml").read_text(encoding="utf-8")},
                blob=blob)


def _djvu(pages: list[tuple[int, list[str]]]) -> bytes:
    objs = "".join(
        f'<OBJECT usemap="Svoboda-1910-01_{leaf:04d}.djvu"><HIDDENTEXT><PAGECOLUMN><REGION>'
        f"<PARAGRAPH>{''.join(f'<LINE><WORD>{w}</WORD></LINE>' for w in words)}"
        f"</PARAGRAPH></REGION></PAGECOLUMN></HIDDENTEXT></OBJECT>"
        for leaf, words in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?><DjVuXML><BODY>{objs}</BODY></DjVuXML>'.encode()


def test_text_is_laid_out_by_leaf_and_counted(tmp_path: Path) -> None:
    blob = (FX / "ia_djvu_1910.xml").read_bytes()
    res = _src(_text_api(blob)).fetch("ia:Svoboda-1910-01", tmp_path)
    folder = tmp_path / "Svoboda-1910-01.text"

    assert (res.frames, res.skipped, res.errors) == (8, 0, [])
    assert sorted(p.name for p in folder.glob("n*.txt"))[0] == "n0000.txt"
    assert "Креницьку" in (folder / "n0002.txt").read_text(encoding="utf-8")
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["ia"]["identifier"] == "Svoboda-1910-01"
    assert meta["files"][0]["md5"] == hashlib.md5(blob).hexdigest()


def test_verified_text_is_not_downloaded_twice(tmp_path: Path) -> None:
    blob = (FX / "ia_djvu_1910.xml").read_bytes()
    api = _text_api(blob)
    src = _src(api)
    src.fetch("ia:Svoboda-1910-01", tmp_path)
    again = src.fetch("ia:Svoboda-1910-01", tmp_path)

    assert (again.frames, again.skipped) == (0, 8)
    assert len(api.streams) == 1


def test_text_with_wrong_checksum_never_lands(tmp_path: Path) -> None:
    blob = _djvu([(0, ["Рік"])])
    res = _src(_text_api(blob, md5=hashlib.md5(b"x").hexdigest())).fetch(
        "ia:Svoboda-1910-01", tmp_path)

    assert res.errors and "контрольна сума" in res.errors[0]
    assert not (tmp_path / "Svoboda-1910-01_djvu.xml").exists()
    assert not (tmp_path / "Svoboda-1910-01.text").exists()


def test_short_text_never_lands(tmp_path: Path) -> None:
    blob = _djvu([(0, ["Рік"])])
    res = _src(_text_api(blob, size=len(blob) + 10)).fetch("ia:Svoboda-1910-01", tmp_path)

    assert res.errors and "неповний" in res.errors[0]
    assert not (tmp_path / "Svoboda-1910-01_djvu.xml").exists()


def test_leaf_comes_from_usemap_not_from_position(tmp_path: Path) -> None:
    """🔴 Лист, не пущений у доступні формати, зсунув би всю нумерацію після себе."""
    blob = _djvu([(0, ["перша"]), (2, ["третя"])])
    scan = _scandata([(0, True), (1, False), (2, True)])
    res = _src(_text_api(blob, scandata=scan)).fetch("ia:Svoboda-1910-01", tmp_path)
    folder = tmp_path / "Svoboda-1910-01.text"

    assert res.frames == 2 and not res.errors
    assert (folder / "n0002.txt").read_text(encoding="utf-8").strip() == "третя"
    assert not (folder / "n0001.txt").exists()


def test_page_without_ocr_is_written_counted_and_named(tmp_path: Path) -> None:
    blob = _djvu([(0, ["Рік"]), (1, [])])
    scan = _scandata([(0, True), (1, True)])
    res = _src(_text_api(blob, scandata=scan)).fetch("ia:Svoboda-1910-01", tmp_path)

    assert res.frames == 2
    assert (tmp_path / "Svoboda-1910-01.text" / "n0001.txt").read_text(encoding="utf-8") == ""
    assert any("1 з 2 листів без тексту" in n for n in res.notes)


def test_leaf_missing_from_the_text_is_named(tmp_path: Path) -> None:
    blob = _djvu([(0, ["Рік"])])
    scan = _scandata([(0, True), (1, True)])
    res = _src(_text_api(blob, scandata=scan)).fetch("ia:Svoboda-1910-01", tmp_path)

    assert res.frames == 1
    assert any("n1" in n and "немає" in n for n in res.notes)


# ── кадри ────────────────────────────────────────────────────────────────────

def _jpeg() -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("L", (8, 8), 200).save(buf, "JPEG")
    return buf.getvalue()


def _frames_api(image: bytes) -> _Api:
    return _Api({"/metadata/Svoboda-1910-01": _fx("ia_metadata_svoboda_1910.json"),
                 "_scandata.xml": (FX / "ia_scandata_1910.xml").read_text(encoding="utf-8"),
                 "iiif.archive.org": image})


def test_frames_are_leaves_through_iiif(tmp_path: Path) -> None:
    api = _frames_api(_jpeg())
    src = _src(api)
    res = src.fetch("ia:Svoboda-1910-01", tmp_path, frames=(2, 3))
    again = src.fetch("ia:Svoboda-1910-01", tmp_path, frames=(2, 3))

    assert (res.frames, res.errors) == (2, [])
    assert (tmp_path / "n0002.jpg").exists()
    assert any(f"{JP2_1910}0002.jp2/full/max/0/default.jpg" in u for u in api.gets)
    assert (again.frames, again.skipped) == (0, 2)


def test_leaf_outside_the_scan_is_an_error_not_a_silent_gap(tmp_path: Path) -> None:
    res = _src(_frames_api(_jpeg())).fetch("ia:Svoboda-1910-01", tmp_path, frames=(7, 9))

    assert res.frames == 1
    assert len(res.errors) == 2 and "n8" in res.errors[0]


def test_answer_that_is_not_an_image_never_lands(tmp_path: Path) -> None:
    res = _src(_frames_api(b"<html>404</html>")).fetch(
        "ia:Svoboda-1910-01", tmp_path, frames=(2, 2))

    assert res.frames == 0 and res.errors
    assert not (tmp_path / "n0002.jpg").exists()


# ── реєстр ───────────────────────────────────────────────────────────────────

def test_browse_is_a_refusal() -> None:
    with pytest.raises(SourceError):
        IaSource().browse()


def test_ia_is_in_the_registry_out_of_the_box() -> None:
    from nyshporka.sources.registry import load

    src = load().get("ia")
    assert src is not None
    assert {"search", "manifest", "fetch"} <= set(src.caps)
    assert "address" not in src.caps
    assert src.catalog_source()[0] == "live"  # type: ignore[attr-defined]
