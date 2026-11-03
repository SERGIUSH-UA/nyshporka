"""🗂 Сайти обласних архівів: розбір сторінок, каталог, кадри з ZIP через `Range`.

Мережі тут немає: сторінки — уривки справжньої розмітки (звірено 03.11.2026),
ZIP — зібраний у пам'яті.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from nyshporka.archives import active
from nyshporka.sources import load
from nyshporka.sources import sitecases as S
from nyshporka.sources import sitecases_parsers as P
from nyshporka.sources.base import SourceError

# ── розбір ───────────────────────────────────────────────────────────────────

DAOO = """<div class="entry"><p><strong>Ф. 37. – Оп. 3a. – Спр. 228. &#8211;
<a href="https://archive.od.gov.ua/wp-content/uploads/2026/10/37.3a.228.pdf">[МЕТРИКА]</a></strong></p>
<p><strong>Ф. 37. – Оп. 3. – Спр. 20<strong>3</strong>. – <a href="/wp-content/uploads/2025/04/37.3.203.pdf">[МЕТРИКА]</a></strong></p>
<p>Ф. 37. – Оп. 3. – Спр. 150 ч.1 – <a href="/u/37.3.150.part1_.pdf">[МЕТРИКА]</a></p>
<p>Ф. 37. – Оп. 3. – Спр. 150 ч.2 – <a href="/u/37.3.150.part2_.pdf">[МЕТРИКА]</a></p>
<p>Ф. 924. – Оп. 1. – Спр. 9. Метрична книга (смерть), 1911-1922 [<a href="/d/0924_01_0009.djvu">METPИКА</a>]</p>
</div>"""


def test_daoo_number_torn_by_a_tag_is_not_read_as_another_case() -> None:
    """🔴 «Спр. 20<strong>3</strong>» — справа 203, а не 20: з пробілом на місці
    тегу на ф.37 виходив 191 дубль чужих шифр."""
    got = P.merge_parts(P.parse_daoo_opys("https://archive.od.gov.ua/x/", DAOO))
    keys = [P.CaseEntry.as_dict(e)["sprava"] for e in got]
    assert "203" in keys and "20" not in keys


def test_daoo_parts_become_one_case_with_several_files() -> None:
    got = P.merge_parts(P.parse_daoo_opys("https://archive.od.gov.ua/x/", DAOO))
    by = {(e.fond, e.opys, e.sprava): e for e in got}
    assert len(got) == len(by), "одна шифра — один запис"
    big = by[("37", "3", "150")]
    assert [f.label for f in big.files] == ["ч.1", "ч.2"]
    assert by[("37", "3а", "228")].files[0].kind == "pdf", "латинська «a» в описі — кирилична «а»"
    djvu = by[("924", "1", "9")]
    assert djvu.files[0].kind == "djvu" and djvu.years == "1911–1922"
    assert "[" not in djvu.title


DADNO = """<table><tr><td>&nbsp;</td><td>номер фонду</td><td>номер опису</td><td>номер справи</td><td>назва</td></tr>
<tr><td>&nbsp;</td><td style="x">193</td><td>3</td><td>679</td>
<td><span><strong>Метрична книга про народження, шлюб, смерть. Свято-Троїцька церква, с. Довгалівка. </strong></span><br />
<span><strong>1908, 1909, 1910 рр.</strong></span>&nbsp;
<a href="https://drive.google.com/file/d/1sPtrl5tKopqGLVcZMtxXCTJ_s4E2fkyO/view?usp=drive_link">Арк. 1-33</a>.&nbsp;
<a href="https://drive.google.com/file/d/1CcOLUkGLGocycchAFcaDeuAQSfT61lPI/view?usp=drive_link">Арк. 34-77</a></td></tr></table>"""


def test_dadno_row_gives_shifra_years_and_drive_parts() -> None:
    (e,) = P.parse_dadno_page("https://dp.archives.gov.ua/p", DADNO)
    assert (e.fond, e.opys, e.sprava) == ("193", "3", "679")
    assert e.years == "1908–1910"
    assert e.title.startswith("Метрична книга") and "Довгалівка" in e.title
    assert [f.kind for f in e.files] == ["drive", "drive"]
    assert [f.label for f in e.files] == ["Арк. 1-33", "Арк. 34-77"]
    assert P.drive_id(e.files[0].url) == "1sPtrl5tKopqGLVcZMtxXCTJ_s4E2fkyO"


DAHO = """<table>
<tr><td>40</td><td>105</td><td>1а</td><td><a href="https://daho.archives.gov.ua/40_105_1a.zip">Метрична книга Успенського собору м. Харкова, 1810-1820 роки</a></td><td>Zip &#8211; 768 Мб</td></tr>
<tr><td>40</td><td>105</td><td>1326</td><td>Метрична книга Українського військового поселення, 1853 рік
<a href="https://daho.archives.gov.ua/40_105_1326_%D1%87%D0%B0%D1%81%D1%82%D0%B8%D0%BD%D0%B0%201.zip">Частина 1 – Zip – 0,98 Гб</a>
<a href="https://daho.archives.gov.ua/40_105_1326_%D1%87%D0%B0%D1%81%D1%82%D0%B8%D0%BD%D0%B0%202.zip">Частина 2 – Zip – 990 Мб</a></td><td></td></tr>
<tr><td></td><td></td><td></td><td><a href="https://daho.archives.gov.ua/40_105_1326_%D1%87%D0%B0%D1%81%D1%82%D0%B8%D0%BD%D0%B0%203.zip">Частина 3</a></td><td></td></tr>
</table>"""


def test_daho_shifra_from_the_table_not_from_the_file_name() -> None:
    """Ім'я файла пише «1a» латиницею, таблиця — «1а»; шифра йде з таблиці."""
    got = P.parse_daho_page("https://archives.kh.gov.ua/?page_id=25402", DAHO)
    assert [e.sprava for e in got] == ["1а", "1326"]


def test_daho_parts_title_comes_from_the_cell_and_continuation_rows_join() -> None:
    got = P.parse_daho_page("https://archives.kh.gov.ua/?page_id=25402", DAHO)
    e = got[1]
    assert e.title == "Метрична книга Українського військового поселення, 1853 рік"
    assert e.years == "1853"
    assert len(e.files) == 3, "рядок без шифри — продовження попередньої справи"
    assert all(f.kind == "zip" for f in e.files)


DAMO = """<table class="striped-table"><tr><td>№ з\\п</td><td>Заголовок справи</td><td>zip-архів</td></tr>
<tr><td>1</td><td><a href="/digital-archive/f0335/0335-002/0335-002-001/">Межова книга казенної пустки біля села Варварівки, 1798</a></td>
<td><a href="/resources/digital-archive/before-1917/0335-002/0335-002-001.zip"><img src="/z.png"></a></td></tr></table>"""


def test_damo_case_from_slug_and_zip() -> None:
    (e,) = P.parse_damo_opys("https://archive.mk.ua/digital-archive/f0335/0335-002/", DAMO, "335")
    assert (e.fond, e.opys, e.sprava) == ("335", "2", "1")
    assert e.files[0].url.endswith("/0335-002-001.zip") and e.files[0].kind == "zip"
    assert e.page.endswith("/0335-002-001/")


@pytest.mark.parametrize(("slug", "fond"), [("f0335", "335"), ("r0510", "Р-510"),
                                            ("n1016", "Н-1016"), ("p0136", "П-136")])
def test_damo_fond_slug(slug: str, fond: str) -> None:
    assert P.damo_fond(slug) == fond


DAHEO = """<div class="breadcrumbs"><span itemprop="name">Головна</span>
<span itemprop="name">Фонд № 259. Церкви Дніпровського повіту Херсонської губернії (ОАФ)</span>
<span class="breadcrumbs__current">Опис 1. Фонд 259</span></div>
<div class="entry themeform"><p><a href="https://drive.google.com/file/d/1_KYMstmSMrzmfYeeecCmc1ohuVJOlX4m/view?usp=sharing">Справа 1. Справа надана користувачем</a></p>
<p><a href="https://drive.google.com/file/d/16jPp9oML-BTvRO_tZKnWf2mhEzvzyU4z/view?usp=sharing">Справа 1 відновлена з фотокопій</a></p>
<p><a href="https://drive.google.com/file/d/1abcdefghijklmnopqrstuvwxyz/view">Справа 2</a></p>
<div class="clear"></div></div>"""


def test_daheo_fond_and_opys_from_breadcrumbs_and_variants_stay_together() -> None:
    got = P.parse_daheo_page("https://kherson.archives.gov.ua/x/opys-1-fond-259/", DAHEO)
    by = {e.sprava: e for e in got}
    assert set(by) == {"1", "2"}
    assert all((e.fond, e.opys) == ("259", "1") for e in got)
    assert len(by["1"].files) == 2, "оригінал і «відновлена з фотокопій» — обидва в справі 1"


def test_years_and_numbers() -> None:
    assert P.years_of("1908, 1909, 1910 рр.") == "1908–1910"
    assert P.years_of("1774-1812 роки") == "1774–1812"
    assert P.years_of("без років") == ""
    assert P.norm_num("0029") == "29" and P.norm_num("1a") == "1а"


@pytest.mark.parametrize(("ref", "want"), [
    ("37/3а/228", ("37", "3а", "228")),
    ("37-3a-228", ("37", "3а", "228")),
    ("ф.37 оп.3а спр.228", ("37", "3а", "228")),
    ("ДАОО 37-3а-228", ("37", "3а", "228")),
    ("Р-510/1/3", ("Р-510", "1", "3")),
    ("193", ("193", "", "")),
])
def test_parse_key(ref: str, want: tuple[str, str, str]) -> None:
    assert S.parse_key(ref) == want


# ── віддалений ZIP ───────────────────────────────────────────────────────────

def _zip(names: list[str], *, deflate: bool) -> bytes:
    buf = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", method) as z:
        z.writestr("40_105_1/", b"")
        for n in names:
            z.writestr(n, (n * 50).encode())
    return buf.getvalue()


def _ranger(blobs: dict[str, bytes], *, ranges: bool = True):
    asked: list[tuple[str, int, int]] = []

    def get(url: str, start: int, end: int) -> tuple[int, bytes, int]:
        data = blobs[url]
        asked.append((url, start, end))
        if not ranges:
            return 200, data, 0
        return 206, data[start:end + 1], len(data)

    return get, asked


@pytest.mark.parametrize("deflate", [False, True])
def test_remote_zip_reads_single_members(deflate: bool) -> None:
    names = ["40_105_1/a-0002.jpg", "40_105_1/a-0001.jpg", "40_105_1/opys.txt"]
    get, _asked = _ranger({"u": _zip(names, deflate=deflate)})
    rz = S.RemoteZip(get, "u")
    frames = S.frames_of(rz.members())
    assert [m.name for m in frames] == ["40_105_1/a-0001.jpg", "40_105_1/a-0002.jpg"], \
        "лише зображення, у порядку імен"
    assert rz.read(frames[0]) == ("40_105_1/a-0001.jpg" * 50).encode()


def test_remote_zip_without_range_says_so() -> None:
    get, _ = _ranger({"u": _zip(["x/1.jpg"], deflate=False)}, ranges=False)
    with pytest.raises(S._NoRange):
        S.RemoteZip(get, "u").members()


# ── джерело ──────────────────────────────────────────────────────────────────

def _source(tmp_path: Path, parser: str = "daho") -> S.SiteCasesSource:
    site = active().site({"daho": "DAHO", "daoo": "DAOO"}[parser], "cases")
    assert site is not None
    return S.SiteCasesSource(tmp_path, site=site, repo={"daho": "DAHO", "daoo": "DAOO"}[parser])


def test_every_cases_site_in_the_pack_has_a_known_parser(tmp_path: Path) -> None:
    sites = dict(active().sites("cases"))
    assert set(sites) == {"DAOO", "DADNO", "DAHO", "DAMO", "DAHEO", "DALUO", "DARO", "DASO"}
    assert all(s.parser in P.CRAWLERS for s in sites.values())
    ids = [s.id for s in load(tmp_path).all() if isinstance(s, S.SiteCasesSource)]
    assert sorted(ids) == ["site-dadno", "site-daheo", "site-daho", "site-daluo", "site-damo",
                           "site-daoo", "site-daro", "site-daso"]


def test_without_a_catalog_zero_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="nysh crawl site-daho"):
        _source(tmp_path).search("Харків")


def _crawled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> S.SiteCasesSource:
    src = _source(tmp_path)
    monkeypatch.setattr(src, "_get_page", lambda url: (url, DAHO))
    monkeypatch.setattr(S, "offline", lambda: False)
    stats = src.crawl()
    assert stats["cases"] == 2
    return src


def test_crawl_writes_a_catalog_that_search_browse_and_address_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _crawled(tmp_path, monkeypatch)
    data = json.loads((tmp_path / src.catalog_rel).read_text(encoding="utf-8"))
    assert len(data["cases"]) == 2 and data["parser"] == "daho"

    fresh = _source(tmp_path)
    assert [h.ref for h in fresh.search("Успенськ")] == ["40/105/1а"]
    assert [h.ref for h in fresh.find_case("40", "105", "1a")] == ["40/105/1а"]
    assert [n.ref for n in fresh.browse(None)] == ["40"]
    assert [n.ref for n in fresh.browse("40")] == ["40/105"]
    assert [n.ref for n in fresh.browse("40/105")] == ["40/105/1а", "40/105/1326"]


def test_absent_case_names_what_the_site_does_have(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _crawled(tmp_path, monkeypatch)
    with pytest.raises(SourceError) as exc:
        src.manifest("40/105/9999")
    msg = str(exc.value)
    assert "не «не" in msg and "nysh crawl site-daho" in msg
    assert "опис 105 фонду 40 на сайті є" in msg


def test_empty_parse_does_not_overwrite_the_catalog(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _crawled(tmp_path, monkeypatch)
    monkeypatch.setattr(src, "_get_page", lambda url: (url, "<html>нова розмітка</html>"))
    with pytest.raises(SourceError, match="не знайшов жодної справи"):
        src.crawl()
    assert len(json.loads((tmp_path / src.catalog_rel).read_text(encoding="utf-8"))["cases"]) == 2


def test_fetch_takes_only_the_asked_frames_from_zip_parts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _crawled(tmp_path, monkeypatch)
    e = src._resolve("40/105/1326")
    blobs = {f.url: _zip([f"p/{i:04d}.jpg" for i in range(1, 4)], deflate=True) for f in e.files}
    get, _ = _ranger(blobs)
    monkeypatch.setattr(src, "_get_range", get)
    dest = tmp_path / "case"

    res = src.fetch("40/105/1326", dest, frames=(3, 5))

    names = sorted(p.name for p in dest.iterdir() if p.suffix == ".jpg")
    # Три частини по три кадри: кадри 3–5 — останній першої й два другої.
    assert names == ["p1_0003.jpg", "p2_0001.jpg", "p2_0002.jpg"]
    assert res.frames == 3 and not res.errors
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["site_cases"]["sprava"] == "1326"

    again = src.fetch("40/105/1326", dest, frames=(3, 5))
    assert again.frames == 0 and again.skipped == 3, "наявні кадри не качаються вдруге"


def test_files_case_refuses_a_frame_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _source(tmp_path, "daoo")
    monkeypatch.setattr(src, "_get_page", lambda url: (url, DAOO))
    monkeypatch.setattr(S, "offline", lambda: False)
    monkeypatch.setattr(P, "crawl_daoo",
                        lambda get, base, stats, tick=None: iter(P.parse_daoo_opys(base, DAOO)))
    monkeypatch.setitem(P.CRAWLERS, "daoo", P.crawl_daoo)
    src.crawl()
    with pytest.raises(SourceError, match="файлами"):
        src.fetch("37/3а/228", tmp_path / "c", frames=(1, 2))


DAMO_NO_ZIP = """<table class="striped-table"><tr><td>1</td>
<td><a href="/digital-archive/f0035/0035-001/0035-001-001/">Справа без архіву</a></td></tr></table>"""

GALLERY = """<div class="ngg-gallery-thumbnail"><a href="https://archive.mk.ua/wp-content/gallery/0035-001-001/0035-001-001-002.jpg" data-src="x"><img src="t2.jpg"></a></div>
<div class="ngg-gallery-thumbnail"><a href="https://archive.mk.ua/wp-content/gallery/0035-001-001/0035-001-001-001.jpg"><img src="t1.jpg"></a></div>
<a href="https://archive.mk.ua/wp-content/gallery/0035-001-001/0035-001-001-001.jpg">дубль</a>"""


def test_damo_case_without_zip_falls_back_to_the_gallery() -> None:
    """Частина описів ДАМО (ф.35–39) не має колонки ZIP — це не «справ немає»:
    кадри лежать галереєю на сторінці справи (41 опис у живому обході)."""
    (e,) = P.parse_damo_opys("https://archive.mk.ua/digital-archive/f0035/0035-001/",
                             DAMO_NO_ZIP, "35")
    assert [f.kind for f in e.files] == ["gallery"]
    assert e.files[0].url.endswith("/0035-001-001/")


DAMO_LETTERED = """<table class="striped-table"><tr><td>2</td>
<td><a href="/digital-archive/r0398/r0398-001/r0398-001-002/">Листування</a></td>
<td><a href="/resources/digital-archive/after-1917/r0398-001/r0398-001-002.zip">zip</a></td></tr></table>"""


def test_damo_lettered_case_slug_is_a_case() -> None:
    """🔴 Справи радянських і нотаріальних фондів адресуються з літерою
    (`r0398-001-002`). Розбір чекав цифр на початку, і 32 описи ДАМО виходили
    порожніми (обхід 03.11.2026)."""
    (e,) = P.parse_damo_opys("https://archive.mk.ua/digital-archive/r0398/r0398-001/",
                             DAMO_LETTERED, "Р-398")
    assert (e.fond, e.opys, e.sprava) == ("Р-398", "1", "2")
    assert [f.kind for f in e.files] == ["zip"]


DAMO_NO_TR = """<table class="striped-table"><thead><tr><td>№ справи</td><td>Назва справи</td></tr></thead>
<tbody>
<td>1</td>
<td><a href="/digital-archive/f0218/0218-001-001/">Ревізькі казки</a></td>
</tr>
</tbody></table>"""


def test_row_without_opening_tr_is_read() -> None:
    """ДАМО ф.218: після `<tbody>` одразу `<td>`, без `<tr>` — рядок справи губився."""
    (e,) = P.parse_damo_opys("https://archive.mk.ua/digital-archive/f0218/0218-001/",
                             DAMO_NO_TR, "218")
    assert (e.opys, e.sprava, e.title) == ("1", "1", "Ревізькі казки")


def test_gallery_images_are_unique_and_in_name_order() -> None:
    got = P.gallery_images("https://archive.mk.ua/x/", GALLERY)
    assert [u.rsplit("/", 1)[-1] for u in got] == ["0035-001-001-001.jpg", "0035-001-001-002.jpg"]


def test_invisible_marks_are_stripped_from_links() -> None:
    """🔴 `href="…/opys-1/ ‎"` — з копіювання в редакторі сайту; з таким
    хвостом сервер відповідав 404, і обхід ДАХеО падав цілим."""
    ((url, _),) = P.links("https://k.ua/", '<a href="https://k.ua/opys-1/ ‎">Опис 1</a>')
    assert url == "https://k.ua/opys-1/"


def test_a_dead_inner_page_is_recorded_not_fatal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _source(tmp_path)
    monkeypatch.setattr(S, "offline", lambda: False)
    pages = {"index": DAHO}

    def crawler(get, base, stats, tick=None):  # type: ignore[no-untyped-def]
        _, t = get("index")
        yield from P.parse_daho_page(base, t)
        _, dead = get("dead")
        assert dead == "", "сторінка, що не відкрилась, — порожня, а не виняток"
        stats.pages += 2

    def get_page(url: str) -> tuple[str, str]:
        if url not in pages:
            raise SourceError(f"{url}: HTTP 404")
        return url, pages[url]

    monkeypatch.setattr(src, "_get_page", get_page)
    monkeypatch.setitem(P.CRAWLERS, "daho", crawler)
    stats = src.crawl()
    assert stats["cases"] == 2
    assert "не відкрилось 1" in stats["summary"] and stats["short"]
    data = json.loads((tmp_path / src.catalog_rel).read_text(encoding="utf-8"))
    assert data["failed_pages"] == ["dead"]


def test_a_dead_index_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _source(tmp_path)
    monkeypatch.setattr(S, "offline", lambda: False)

    def get_page(url: str) -> tuple[str, str]:
        raise SourceError("HTTP 503")

    monkeypatch.setattr(src, "_get_page", get_page)
    with pytest.raises(SourceError, match="503"):
        src.crawl()
    assert not (tmp_path / src.catalog_rel).exists()


def test_gallery_case_is_fetched_frame_by_frame(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = S.SiteCasesSource(tmp_path, site=active().site("DAMO", "cases"), repo="DAMO")  # type: ignore[arg-type]
    monkeypatch.setattr(S, "offline", lambda: False)
    monkeypatch.setitem(P.CRAWLERS, "damo", lambda get, base, stats, tick=None: iter(
        P.parse_damo_opys("https://archive.mk.ua/digital-archive/f0035/0035-001/", DAMO_NO_ZIP, "35")))
    monkeypatch.setattr(src, "_get_page", lambda url: (url, GALLERY))
    src.crawl()
    monkeypatch.setattr(src, "_image_reader", lambda url: (lambda: url.encode()))

    assert src.manifest("35/1/1").frames == 2
    res = src.fetch("35/1/1", tmp_path / "c", frames=(2, 2))
    assert res.frames == 1
    assert sorted(p.name for p in (tmp_path / "c").glob("*.jpg")) == ["0035-001-001-002.jpg"]


class _Stream:
    def __init__(self, status: int, body: bytes, total: int) -> None:
        self.status_code = status
        self.headers = {"content-range": f"bytes 0-{len(body) - 1}/{total}"} if status == 206 else {}
        self._body = body
        self.read_calls = 0

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def iter_bytes(self):  # type: ignore[no-untyped-def]
        self.read_calls += 1
        if self.status_code != 206:
            raise AssertionError("тіло відповіді без Range не мусить читатись")
        for i in range(0, len(self._body), 4):
            yield self._body[i:i + 4]


class _StreamClient:
    def __init__(self, replies: list[_Stream]) -> None:
        self.replies = replies

    def stream(self, method: str, url: str, headers: dict[str, str]) -> _Stream:
        return self.replies.pop(0)


def _with_client(tmp_path: Path, client: _StreamClient) -> S.SiteCasesSource:
    from nyshporka.sources.http import Fetcher

    site = active().site("DAHO", "cases")
    assert site is not None
    return S.SiteCasesSource(tmp_path, site=site, repo="DAHO",
                             fetcher=Fetcher(base=site.url, delay=0.0, client=client))


def test_range_ignored_by_the_server_is_not_downloaded(tmp_path: Path) -> None:
    """🔴 Сервер ДАХО віддав на `Range: bytes=0-0` цілий ZIP (~1 ГБ) — запит висів,
    читаючи гігабайт у пам'ять. Тепер 200 замість 206 (двічі) — відмова без читання."""
    big = [_Stream(200, b"x" * 64, 0), _Stream(200, b"x" * 64, 0)]
    src = _with_client(tmp_path, _StreamClient(list(big)))
    with pytest.raises(S._NoRange):
        src._get_range("https://daho.archives.gov.ua/a.zip", 0, 0)
    assert all(s.read_calls == 0 for s in big)


def test_range_body_is_cut_at_the_asked_length(tmp_path: Path) -> None:
    src = _with_client(tmp_path, _StreamClient([_Stream(206, b"0123456789abcdef", 990)]))
    code, data, total = src._get_range("https://daho.archives.gov.ua/a.zip", 0, 5)
    assert (code, data, total) == (206, b"012345", 990)


def test_one_inconsistent_cache_reply_is_retried(tmp_path: Path) -> None:
    src = _with_client(tmp_path, _StreamClient([_Stream(200, b"", 0), _Stream(206, b"PK", 5)]))
    assert src._get_range("https://daho.archives.gov.ua/a.zip", 0, 1)[1] == b"PK"


# ── ДАЛуО, ДАРО, ДАСО ────────────────────────────────────────────────────────

DALUO_PUB = """<div id="tab19">реєстри <a href="../download/fonds/fonds_1.zip">zip</a></div>
<div id="tab60" class="tab_v"><h3>Фонд №303 «Колекція книг ДРАЦС»</h3>
<p>Опис №3 справ постійного зберігання, Біловодського районного відділу ДРАЦС за 1939-1945 роки</p>
справа № 6 <a href="../download/digital_files/P-303_Op3_C-6.zip">у форматі ZIP</a>
справа № 7 <a href="../download/digital_files/P-303_Op3_C-7.zip">у форматі ZIP</a>
<p>Опис №18 справ постійного зберігання Старобільського відділу ДРАЦС за 1944 рік</p>
справа № 39 <a href="../download/digital_files/P-303_Op18_C-39.zip">у форматі ZIP</a>
<p>Метричні книги</p> Фонд 3, Метрична книга … 1883-1885 <a href="../download/2021/mb1883.pdf">PDF</a>
</div><div id="tab20">збірники</div>"""

DALUO_SFD = """<table><tr><th>Номер фонду</th><th>Номер опису</th><th>Номер справи</th><th>Склад</th>
<th colspan='2'>Дати</th><th>Аркушів</th><th>PDF</th></tr>
<tr><td>Ф-62</td><td>1</td><td>4</td><td><a href='gallery.php?p=2'>Ревізькі казки села Михайлівки</a></td>
<td>березень 1816 р.</td><td>березень 1816 р.</td><td>22 / 22</td>
<td><a target='_blank' href='MF-SFD/pdf/ДА_Луганської_обл.Ф.Ф-62.Оп.1.Спр.4.pdf'>24.9 Мб</a></td></tr>
<tr><td>Р-332</td><td>невідомо</td><td>3</td><td>Без опису</td><td>1920</td><td>1921</td><td>5</td>
<td><a href='MF-SFD/pdf/x.pdf'>1 Мб</a></td></tr></table>"""


def test_daluo_racs_zip_shifra_comes_from_the_file_name() -> None:
    got = P.parse_daluo_pub("https://lg.archives.gov.ua/pages/fonds-publications.html", DALUO_PUB)
    assert [(e.fond, e.opys, e.sprava) for e in got] == [
        ("Р-303", "3", "6"), ("Р-303", "3", "7"), ("Р-303", "18", "39")]
    assert got[0].title.startswith("Біловодського") and got[0].years == "1939–1945"
    assert got[0].files[0].url == "https://lg.archives.gov.ua/download/digital_files/P-303_Op3_C-6.zip"


def test_daluo_insurance_table_single_quoted_links_and_unknown_opys() -> None:
    """`href='…'` в одинарних лапках; опис «невідомо» — без шифри, не справа."""
    (e,) = P.parse_daluo_sfd("https://lg.archives.gov.ua/fonds/", DALUO_SFD)
    assert (e.fond, e.opys, e.sprava, e.years) == ("62", "1", "4", "1816")
    assert e.files[0].kind == "pdf" and "Спр.4.pdf" in e.files[0].url


DARO = """<table><tr><th>Номер справи</th><th>Заголовок справи</th><th>Завантажити</th></tr>
<tr><td> 1</td><td><a href="/upload/a1.pdf"><p>Метрична книга, м. Березне, 1931-1932 рр., ч.1</p></a></td>
<td><a href="/upload/a1.pdf">dl</a></td></tr>
<tr><td> 1</td><td><a href="/upload/a2.pdf"><p>Метрична книга, м. Березне, 1931-1932 рр., ч.2</p></a></td>
<td><a href="/upload/a2.pdf">dl</a></td></tr>
<tr><td> 3</td><td><a href="/upload/b.pdf"><p>Метрична книга, с. Балашівка, 1932р.</p></a></td>
<td><a href="/upload/b.pdf">dl</a></td></tr></table>"""


def test_daro_parts_of_one_case_are_one_case() -> None:
    got = P.parse_daro_opys("https://rv.archives.gov.ua/ocifrovani-sprav", DARO, "Р-740", "7")
    assert [(e.sprava, len(e.files)) for e in got] == [("1", 2), ("3", 1)]
    assert [f.label for f in got[0].files] == ["ч.1", "ч.2"]
    assert got[0].title == "Метрична книга, м. Березне, 1931-1932 рр"


def test_daro_opys_map_never_guesses() -> None:
    """🔴 Сторінка не несе шифри. Опис 13 (277 од. проти 270 в оп.16) — поза картою."""
    assert (5, 5, 13) not in P.DARO_OPYSY
    assert P.DARO_OPYSY[(5, 5, 14)] == ("Р-740", "7")


DASO = """<p><span class="text1"> Фонд 437</span><span class="text2">- Путивльське казначейство</span>
<span class="text1"> Опис 1 </span><blockquote>Окладні аркуші. 1890-1900 рр.</blockquote>
<a href="./storage/fonds/F437/x-437-1-10_1.pdf" class="button">Справа 10-1</a>
<a href="./storage/fonds/F437/x-437-1-10_2.pdf" class="button">10-2</a>
<a href="./storage/fonds/F437/x-437-1-11.pdf" class="button">11</a></p>
<p>Фонд 814 Конотопська міська управа <a href="./storage/opus/do1917/005/f814o1L.pdf">Опис 1Л</a>
<a href="./storage/fonds/F814/x-814-1л-1.pdf">1</a></p>
<p>Фонд Р 1655 - Народний суд Опис 1 Судові справи. 1920-1923 рр.
<a href="./storage/fonds/R1655/x-r1655-1-232.pdf">232</a>
<a href="./storage/fonds/R1655/y.djvu">619 Виконавчі комітети волосних рад, 1921</a></p>
<p>Фонд - P-7720 Опис 1 Білопільський район
<a href="./storage/fonds/P7720/p7720op1d412.pdf">Справа №412</a></p>"""


def test_daso_walks_fond_opys_and_case_buttons() -> None:
    got = P.parse_daso_page("http://46.201.250.75/r1p07.php", DASO)
    by = {(e.fond, e.opys, e.sprava): e for e in got}
    assert set(by) == {("437", "1", "10"), ("437", "1", "11"), ("814", "1л", "1"),
                       ("Р-1655", "1", "232"), ("Р-1655", "1", "619"), ("Р-7720", "1", "412")}
    # «10-1», «10-2» — частини однієї справи
    assert [f.label for f in by[("437", "1", "10")].files] == ["ч.1", "ч.2"]
    assert by[("437", "1", "11")].years == "1890–1900"
    # назва в самій кнопці, DjVu — теж файл справи
    e = by[("Р-1655", "1", "619")]
    assert e.title.startswith("Виконавчі комітети") and e.files[0].kind == "djvu"


@pytest.mark.parametrize(("raw", "fond"), [("Р 1655", "Р-1655"), ("P-7720", "Р-7720"),
                                           ("П-4459", "П-4459"), ("442", "442")])
def test_daso_fond_letters(raw: str, fond: str) -> None:
    assert P.daso_fond(raw) == fond


def test_daso_same_files_on_two_pages_are_one_case() -> None:
    page = """<p>Фонд 992 Опис 1 Справи <a href="./storage/fonds/F992/a.pdf">1</a></p>"""
    more = page + """<p>Фонд 993 Опис 1 Інше <a href="./storage/fonds/F993/b.pdf">5</a></p>"""
    # меню з незакритим `<a>` — як на живому сайті: друга сторінка мусить знайтись
    pages = {"http://h/": '<li><a href="./r1p10.php">a <li><a href="./r1p14.php">b</a>',
             "http://h/r1p10.php": page, "http://h/r1p14.php": more}
    stats = P.CrawlStats()
    got = list(P.crawl_daso(lambda u: (u, pages[u]), "http://h", stats))
    assert [(e.fond, e.sprava) for e in got] == [("992", "1"), ("993", "5")]
    assert stats.pages == 3


def test_zip_of_pdf_parts_gives_files_not_zero_frames() -> None:
    """ДАЛуО кладе в ZIP PDF-частини справи: без цього маніфест казав «0 кадрів»."""
    ms = [S.ZipMember(name=n, offset=0, csize=1, usize=1, method=0)
          for n in ("P-303_Op3_C-6_10.pdf", "P-303_Op3_C-6_2.pdf", "P-303_Op3_C-6_1.pdf")]
    assert S.frames_of(ms) == []
    assert [m.name for m in S.docs_of(ms)] == [
        "P-303_Op3_C-6_1.pdf", "P-303_Op3_C-6_2.pdf", "P-303_Op3_C-6_10.pdf"]


def test_zip_frames_without_leading_zeros_keep_page_order() -> None:
    """`1, 2, 10`, а не `1, 10, 2`: номер `--frames` мусить бути номером сторінки."""
    ms = [S.ZipMember(name=n, offset=0, csize=1, usize=1, method=0)
          for n in ("sp/10.jpg", "sp/2.jpg", "sp/1.jpg", "sp/0003.jpg")]
    assert [m.name for m in S.frames_of(ms)] == ["sp/1.jpg", "sp/2.jpg", "sp/0003.jpg",
                                                 "sp/10.jpg"]


def test_zip_of_pdf_parts_is_planned_as_files(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Джерело справді бере PDF із ZIP: маніфест — 2 файли, а не 0 кадрів."""
    ms = [S.ZipMember(name=n, offset=0, csize=1, usize=1, method=0)
          for n in ("C-6_2.pdf", "C-6_1.pdf", "readme.txt")]

    class _Zip:
        def __init__(self, get_range: object, url: str) -> None:
            pass

        def members(self) -> list[S.ZipMember]:
            return ms

        def read(self, m: S.ZipMember) -> bytes:
            return b"%PDF"

    monkeypatch.setattr(S, "RemoteZip", _Zip)
    src = _source(tmp_path)
    e = P.CaseEntry(fond="Р-303", opys="3", sprava="6", title="", years="", page="x",
                    files=[P.CaseFile(url="https://h/a.zip", kind="zip")])
    monkeypatch.setattr(src, "_resolve", lambda ref: e)
    monkeypatch.setattr(src, "_online", lambda: None)
    m = src.manifest("Р-303/3/6")
    assert (m.frames, m.meta["unit"]) == (2, "файл")
    assert [f.name for f in src._frame_plan(e)] == ["C-6_1.pdf", "C-6_2.pdf"]
