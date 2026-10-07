"""🇵🇱 Джерело Szukaj w Archiwach: перелік сторінками, кеш, zip, різ розворотів.

Портал підставлено (`httpx.MockTransport`): тест мережевого джерела, що ходить у
мережу, перевіряв би чужий сервер, а не наш розбір. Одиниця вигадана — номер,
сигнатура й назва не відповідають жодній справжній.
"""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from nyshporka.core import szukaj as SZ
from nyshporka.sources.base import SourceError
from nyshporka.sources.http import Fetcher
from nyshporka.sources.szukaj import SzukajSource

UID = "9000001"
UNIT = f"https://www.szukajwarchiwach.gov.pl/jednostka/-/jednostka/{UID}"
SYGN = "99/7/0/1/3"


def _lines(d: ImageDraw.ImageDraw, x0: int, x1: int, h: int) -> None:
    for y in range(40, h - 40, 24):
        d.rectangle((x0, y, x1, y + 6), fill=0)


def _jpeg(kind: str) -> bytes:
    if kind == "cover":
        im = Image.new("L", (600, 900), 255)
        _lines(ImageDraw.Draw(im), 60, 540, 900)
    else:                                     # розворот із чистим згином 560-640
        im = Image.new("L", (1200, 900), 255)
        d = ImageDraw.Draw(im)
        _lines(d, 60, 560, 900)
        _lines(d, 640, 1140, 900)
    buf = BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


#: Скан → (id файла, хеш зображення, кадр). Сканів п'ять — більше за сторінку
#: переліку (`delta`=2 у підставному порталі), щоб перевірити гортання.
SCANS = {n: (str(500 + n), f"{n:064x}", _jpeg("cover" if n == 1 else "spread"))
         for n in range(1, 6)}
PER_PAGE = 2


def _item(n: int) -> str:
    plik, photo, _ = SCANS[n]
    return (f'<li><div class="jednostka-skan"> <a href="javascript:;" class="load-photo-slider" '
            f'data-plikId="{plik}" data-jednostkaid="{UID}" data-liczbawszystkichskanow="5">'
            f' <img alt=\'Obraz {n} z jednostki "[Księga]"\' '
            f'src="https://photos.szukajwarchiwach.gov.pl/{photo}_mid"> </a> '
            f'<span class="number-of-scan">{n}</span> <span class="opis">{plik}</span></div></li>')


def _list_page(page: int) -> str:
    nums = sorted(SCANS)[(page - 1) * PER_PAGE: page * PER_PAGE] or sorted(SCANS)[-PER_PAGE:]
    return ('<html><head><meta property="og:title" content="[Księga zapisów]" ></head><body>'
            '<a href="https://www.szukajwarchiwach.gov.pl/archiwum">Archiwum</a>'
            '<a href="https://www.szukajwarchiwach.gov.pl/zespol">Zespół</a>'
            f'<div class="title"> Sygnatura </div><div class="value"><p>{SYGN}</p></div>'
            '<div class="title"> Daty </div><div class="value"> 1700 - 1702 </div>'
            '<div class="title"> Archiwum </div><div class="value">Archiwum Testowe</div>'
            '<div class="title"> Zespół </div><div class="value">'
            '<a href="/zespol/-/zespol/4242">Księgi grodzkie testowe</a></div>'
            '<h3 class="h3 g-inline"> Skany (5) </h3>'
            + "".join(_item(n) for n in nums) + "</body></html>")


class Portal:
    """Підставний портал: що віддає і скільки разів у нього питали."""

    def __init__(self, *, geo_block: bool = False, flaky: int = 0, shield: bool = False,
                 stuck: bool = False) -> None:
        self.geo_block = geo_block
        self.stuck = stuck
        self.shield = shield
        self.flaky = flaky
        self.pages: list[int] = []
        self.photos: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.geo_block:
            return httpx.Response(403, text="<html>Incapsula incident</html>")
        url = str(req.url)
        if url.startswith(SZ.PHOTOS):
            photo = url.rsplit("/", 1)[-1].removesuffix("_max")
            self.photos.append(photo)
            for _, (_, h, blob) in SCANS.items():
                if h == photo:
                    return httpx.Response(200, content=blob)
            return httpx.Response(404)
        if url.startswith(UNIT):
            if self.shield:
                return httpx.Response(200, text='<html><body><iframe id="main-iframe" '
                                      'src="/_Incapsula_Resource?SWUDNSAI=31">Request '
                                      'unsuccessful. Incapsula incident ID: 1-2</iframe>'
                                      '</body></html>')
            if self.flaky:
                self.flaky -= 1
                return httpx.Response(200, text="Portlet jest tymczasowo niedostępny.")
            page = 1 if self.stuck else int(dict(req.url.params).get("_Jednostka_cur", "1"))
            self.pages.append(page)
            return httpx.Response(200, text=_list_page(page))
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    import nyshporka.sources.szukaj as mod

    monkeypatch.setattr(mod, "DELTA", PER_PAGE)


def _source(portal: Portal, ws: Path | None = None) -> SzukajSource:
    client = httpx.Client(transport=httpx.MockTransport(portal))
    return SzukajSource(ws, pages=client,
                        fetcher=Fetcher(client=client, delay=0.0, attempts=1))


def _zip(path: Path, *, nums: tuple[int, ...] = (1, 2, 3, 4, 5), xml: bool = True) -> Path:
    stem = SYGN.replace("/", "_")
    with zipfile.ZipFile(path, "w") as z:
        for n in nums:
            plik, _, blob = SCANS[n]
            z.writestr(f"{stem}_{n}_{plik}.jpg", blob)
            if xml:
                z.writestr(f"{stem}_{n}_{plik}.xml",
                           "<Plik><daty>1700-1702</daty><nazwa>[Księga zapisów]</nazwa></Plik>")
    return path


# ── адресація ────────────────────────────────────────────────────────────────
def test_unit_addresses_round_trip() -> None:
    u = SZ.from_url(UNIT + "?fbclid=xyz")
    assert u is not None and u.ref == f"jednostka:{UID}"
    assert SZ.from_ref(u.ref) == u and SZ.from_ref(f"szukaj:unit:{UID}") == u
    assert SZ.from_url("https://www.szukajwarchiwach.gov.pl/zespol/-/zespol/1855") is None
    assert SZ.from_url("https://example.org/jednostka/-/jednostka/1") is None


def test_zip_names_parse_from_the_right() -> None:
    assert SZ.parse_zip_name("35_12_0_1_5_12_112652371.jpg") == ("35/12/0/1/5", 12, "112652371")
    # Серія `-` (АП Перемишль) лишається частиною сигнатури.
    assert SZ.parse_zip_name("56_2041_0_-_10_10_19542589.jpg") == ("56/2041/0/-/10", 10, "19542589")
    assert SZ.sygn_parts("35/12/0/1/5")["zespol"] == "12"


# ── маніфест ─────────────────────────────────────────────────────────────────
def test_manifest_walks_every_list_page() -> None:
    portal = Portal()
    man = _source(portal).manifest(UNIT)
    assert man.frames == 5 and portal.pages == [1, 2, 3]
    assert man.ref == f"jednostka:{UID}"
    assert man.meta["sygnatura"] == SYGN and man.meta["years"] == "1700-1702"
    assert man.meta["zespol_name"] == "Księgi grodzkie testowe", (
        "«Zespół» із хлібних крихт угорі сторінки — не назва фонду")
    assert man.meta["zespol_id"] == "4242" and man.meta["archiwum_name"] == "Archiwum Testowe"


def test_manifest_is_cached_in_the_workspace(tmp_path: Path) -> None:
    portal = Portal()
    _source(portal, tmp_path).manifest(UNIT)
    blocked = Portal(geo_block=True)
    man = _source(blocked, tmp_path).manifest(UNIT)
    assert man.frames == 5 and man.meta["listed_from"] == "portal"
    assert blocked.pages == [], "з кешу — без жодного запиту до порталу"


def test_geo_block_names_the_two_ways_out() -> None:
    with pytest.raises(SourceError, match="403") as err:
        _source(Portal(geo_block=True)).manifest(UNIT)
    assert "NYSHPORKA_PROXY_URL" in str(err.value) and "--from-zip" in str(err.value)


def test_incapsula_challenge_is_named_not_a_zero(tmp_path: Path) -> None:
    """Виклик захисту — це 200 з iframe; читати його як «сканів немає» не можна."""
    with pytest.raises(SourceError, match="Incapsula") as err:
        _source(Portal(shield=True)).manifest(UNIT)
    assert "--from-zip" in str(err.value) and "немає жодного скана" not in str(err.value)


def test_cached_unit_downloads_while_pages_are_challenged(tmp_path: Path) -> None:
    """Сторінки під викликом, `photos.` віддає: перелік із кешу — і скани беруться."""
    _source(Portal(), tmp_path).manifest(UNIT)
    portal = Portal(shield=True)
    res = _source(portal, tmp_path).fetch(UNIT, tmp_path / "book")
    assert res.frames == 5 and not res.errors and portal.pages == []


def test_short_list_is_refused_and_not_cached(tmp_path: Path) -> None:
    """Портал назвав 5 сканів, а гортання повторює першу сторінку: маніфест на 2
    скани читався б як уся книга — і кеш закріпив би це назавжди."""
    with pytest.raises(SourceError, match="обірвано"):
        _source(Portal(stuck=True), tmp_path).manifest(UNIT)
    assert not (tmp_path / "data" / "raw" / "szukaj").exists()


def test_portlet_hiccup_is_retried() -> None:
    assert _source(Portal(flaky=1)).manifest(UNIT).frames == 5


def test_portlet_down_for_good_refuses() -> None:
    with pytest.raises(SourceError, match="тимчасово"):
        _source(Portal(flaky=99)).manifest(UNIT)


def test_offline_refuses_instead_of_zero() -> None:
    with pytest.raises(SourceError, match="мережу вимкнено"):
        SzukajSource().manifest(UNIT)


# ── качання ──────────────────────────────────────────────────────────────────
def test_fetch_splits_spreads_and_writes_the_map(tmp_path: Path) -> None:
    res = _source(Portal()).fetch(UNIT, tmp_path)
    assert not res.errors and res.frames == 5
    names = sorted(p.name for p in tmp_path.glob("*.jpg"))
    assert names[:3] == ["0001.jpg", "0002_L.jpg", "0002_R.jpg"] and len(names) == 9
    book = json.loads((tmp_path / SZ.MAP_NAME).read_text(encoding="utf-8"))
    assert book["source"] == SZ.HOST and book["unit"] == UID and book["sygnatura"] == SYGN
    rec = book["frames"]["0002"]
    assert rec["scan"] == 2 and rec["plik_id"] == "502" and rec["photo"] == SCANS[2][1]
    assert 560 <= rec["fold_x"] <= 640
    assert SZ.read_map(tmp_path)["0002_R.jpg"] == ("2", "R")
    assert SZ.read_map(tmp_path)["0001.jpg"] == ("1", "-")


def test_resume_and_range(tmp_path: Path) -> None:
    portal = Portal()
    src = _source(portal)
    src.fetch(UNIT, tmp_path, frames=(2, 3))
    assert sorted(portal.photos) == sorted([SCANS[2][1], SCANS[3][1]])
    portal.photos.clear()
    res = src.fetch(UNIT, tmp_path)
    assert (res.frames, res.skipped) == (3, 2)
    assert SCANS[2][1] not in portal.photos


def test_from_zip_needs_no_network(tmp_path: Path) -> None:
    """Zip, скачаний у браузері: ні переліку, ні сканів із порталу."""
    z = _zip(tmp_path / "skany.zip")
    blocked = Portal(geo_block=True)
    src = _source(blocked)
    man = src.manifest(UNIT, from_zip=z)
    assert man.frames == 5 and man.meta["listed_from"] == "zip"
    assert man.meta["title"] == "[Księga zapisów]" and man.meta["sygnatura"] == SYGN
    res = src.fetch(UNIT, tmp_path / "book", from_zip=z)
    assert res.frames == 5 and not res.errors
    assert blocked.pages == [] and blocked.photos == []
    book = json.loads((tmp_path / "book" / SZ.MAP_NAME).read_text(encoding="utf-8"))
    assert book["taken_from"] == "zip" and book["frames"]["0004"]["plik_id"] == "504"


def test_zip_missing_scans_is_refused(tmp_path: Path) -> None:
    """Перелік із порталу (кеш) — 5 сканів, у zip лише 3: розкладати неповне не можна."""
    _source(Portal(), tmp_path).manifest(UNIT)
    z = _zip(tmp_path / "skany.zip", nums=(1, 2, 3))
    with pytest.raises(SourceError, match="немає 2 сканів"):
        _source(Portal(geo_block=True), tmp_path).fetch(UNIT, tmp_path / "book", from_zip=z)


def test_zip_of_two_units_is_refused(tmp_path: Path) -> None:
    z = tmp_path / "mix.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("99_7_0_1_3_1_501.jpg", SCANS[1][2])
        zf.writestr("99_7_0_1_4_1_601.jpg", SCANS[1][2])
    with pytest.raises(SourceError, match="кількох одиниць"):
        _source(Portal(geo_block=True)).manifest(UNIT, from_zip=z)


def test_broken_jpeg_is_an_error_not_a_page(tmp_path: Path) -> None:
    z = tmp_path / "skany.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("99_7_0_1_3_1_501.jpg", SCANS[1][2][:200])
    res = _source(Portal(geo_block=True)).fetch(UNIT, tmp_path / "b", from_zip=z)
    assert res.frames == 0 and len(res.errors) == 1 and res.causes


# ── Супряга: пакет знає зйомку і скан кожної сторінки ───────────────────────
def test_bundle_gets_unit_ref_and_page_src(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import record_fetch
    from nyshporka.share import align
    from nyshporka.share.publish import _refs_from_sidecar

    d = tmp_path / "a"
    res = _source(Portal()).fetch(UNIT, d)
    record_fetch(d, res, source="szukaj", ref=UNIT, url=UNIT, want=5)
    assert _refs_from_sidecar(d) == [{"source": "szukaj", "ref": f"jednostka:{UID}",
                                      "url": UNIT}]
    rows = {f["name"]: f for f in align.frames_of(d)}
    assert rows["0002_R.jpg"]["src"] == "2R" and rows["0001.jpg"]["src"] == "1"
    assert rows["0002_L.jpg"]["box"][0] == 0


def test_cli_rejects_from_zip_for_a_source_that_cannot(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    z = _zip(tmp_path / "skany.zip", nums=(1,))
    got = CliRunner().invoke(app, ["get", "commons", "file:X.pdf", "--out", str(tmp_path / "o"),
                                   "--from-zip", str(z)])
    assert got.exit_code != 0

