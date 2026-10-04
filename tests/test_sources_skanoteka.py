"""📚 Джерело Сканотеки ПТГ: качання одиниці, різ розворотів, карта сканів.

Сайт підставлено (`httpx.MockTransport`): тест мережевого джерела, що ходить у
мережу, перевіряв би чужий сервер, а не наш розбір.

Три кадри — три випадки з ф.2 ЦДІАК: обкладинка (портретний кадр — один
аркуш), розворот із чистим згином і широкий аркуш без згину (вкладка). Різати
можна лише другий; перший і третій мусять лишитись цілими, інакше титул і
вкладка розрізаються посередині рядків.
"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from nyshporka.sources.http import Fetcher
from nyshporka.sources.skanoteka import SkanotekaSource, find_fold

UNIT = "https://sadowe.genealodzy.pl/id1703-sy160-se"
METBOX = "https://metbox3.genealodzy.pl/37/metryka_get.php"


def _lines(d: ImageDraw.ImageDraw, x0: int, x1: int, h: int) -> None:
    """«Рядки письма»: горизонтальні штрихи — саме їх ловить детектор згину."""
    for y in range(40, h - 40, 24):
        d.rectangle((x0, y, x1, y + 6), fill=0)


def _jpeg(kind: str) -> bytes:
    if kind == "cover":
        im = Image.new("L", (600, 900), 255)
        _lines(ImageDraw.Draw(im), 60, 540, 900)
    elif kind == "spread":
        im = Image.new("L", (1200, 900), 255)
        d = ImageDraw.Draw(im)
        _lines(d, 60, 560, 900)
        _lines(d, 640, 1140, 900)            # чиста смуга 560-640 — згин
    else:                                     # вкладка: рядки через усю ширину
        im = Image.new("L", (1200, 900), 255)
        _lines(ImageDraw.Draw(im), 60, 1140, 900)
    buf = BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


FILES = {"001": _jpeg("cover"), "002": _jpeg("spread"), "003": _jpeg("insert")}

#: 🔴 Перелік файлів на сторінці одиниці йде сіткою по стовпцях, а не підряд —
#: тут так само (003, 001, 002), щоб тест ловив качання «за позицією».
UNIT_PAGE = ("<html><body><div>Zespół:</div><div>2 / Księgi grodzkie kijowskie</div>"
             "<div>Jednostka:</div><div>160 / Księgi grodzkie kijowskie</div>"
             "<div>Lata:</div><div>1793</div><div>Pliki:</div>"
             + "".join(f'<a href="index.php?op=pg&id=1703&se=&sy=160&kt=&plik={s}.jpg">{s}</a>'
                       for s in ("003", "001", "002", "001"))
             + "</body></html>")
VIEW_PAGE = (f'<img src="{METBOX}?op=download&amp;dir=DIRTOK&amp;znak=ZNAK&amp;'
             f'plik=001.jpg">')


class Site:
    """Підставний сайт: що віддає і скільки разів у нього питали файли."""

    def __init__(self, broken: tuple[str, ...] = ()) -> None:
        self.broken = broken
        self.file_hits: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith(METBOX):
            q = dict(req.url.params)
            assert q["dir"] == "DIRTOK" and q["znak"] == "ZNAK"
            stem = q["plik"].removesuffix(".jpg")
            self.file_hits.append(stem)
            if stem in self.broken:
                return httpx.Response(200, content=FILES[stem][:200])   # обірваний
            return httpx.Response(200, content=FILES[stem])
        if "op=pg" in url:
            return httpx.Response(200, text=VIEW_PAGE)
        if url.startswith(UNIT):
            return httpx.Response(200, text=UNIT_PAGE)
        return httpx.Response(404)


def _source(site: Site) -> SkanotekaSource:
    client = httpx.Client(transport=httpx.MockTransport(site))
    return SkanotekaSource(fetcher=Fetcher(client=client, delay=0.0, attempts=1))


def test_manifest_from_unit_page() -> None:
    man = _source(Site()).manifest(UNIT)
    assert man.ref == "unit:sadowe/1703/160" and man.frames == 3
    assert "Księgi grodzkie kijowskie" in man.title and "1793" in man.title
    assert man.meta["url"] == UNIT and man.meta["files"] == ["001", "002", "003"]


def test_fetch_splits_only_real_spreads(tmp_path: Path) -> None:
    """Розворот — на дві сторінки; обкладинку й вкладку — цілими."""
    res = _source(Site()).fetch(UNIT, tmp_path)
    assert not res.errors and res.frames == 3
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == [
        "001.jpg", "002_L.jpg", "002_R.jpg", "003.jpg"]
    book = json.loads((tmp_path / "_skanoteka.json").read_text(encoding="utf-8"))
    assert book["unit"] == "160" and book["split"] is True
    assert set(book["frames"]["002"]["pages"]) == {"002_L.jpg", "002_R.jpg"}
    assert "портретний" in book["frames"]["001"]["split_skipped"]
    assert "згину не видно" in book["frames"]["003"]["split_skipped"]
    fold = book["frames"]["002"]["fold_x"]
    assert 560 <= fold <= 640, "різ мусить лягти в чисту смугу між сторінками"
    with Image.open(tmp_path / "002_L.jpg") as im:
        assert im.mode == "L", "сторінки зберігаються сірими"
    assert any("сторінок 4" in n for n in res.notes)


def test_whole_keeps_every_frame(tmp_path: Path) -> None:
    res = _source(Site()).fetch(UNIT, tmp_path, split=False)
    assert res.frames == 3
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["001.jpg", "002.jpg", "003.jpg"]
    book = json.loads((tmp_path / "_skanoteka.json").read_text(encoding="utf-8"))
    assert book["split"] is False


def test_resume_does_not_download_again(tmp_path: Path) -> None:
    site = Site()
    src = _source(site)
    src.fetch(UNIT, tmp_path)
    site.file_hits.clear()
    res = src.fetch(UNIT, tmp_path)
    assert (res.frames, res.skipped) == (0, 3) and site.file_hits == []
    (tmp_path / "002_R.jpg").unlink()             # половина зникла — скан береться знову
    res = src.fetch(UNIT, tmp_path)
    assert site.file_hits == ["002"] and (res.frames, res.skipped) == (1, 2)


def test_range_counts_scans(tmp_path: Path) -> None:
    site = Site()
    res = _source(site).fetch(UNIT, tmp_path, frames=(2, 2))
    assert site.file_hits == ["002"] and res.frames == 1


def test_broken_jpeg_is_an_error_not_a_page(tmp_path: Path) -> None:
    res = _source(Site(broken=("003",))).fetch(UNIT, tmp_path)
    assert res.frames == 2 and len(res.errors) == 1 and "003" in res.errors[0]
    assert res.causes and not (tmp_path / "003.jpg").exists()


def test_offline_refuses_instead_of_zero() -> None:
    from nyshporka.sources.base import SourceError

    with pytest.raises(SourceError, match="мережу вимкнено"):
        SkanotekaSource().manifest(UNIT)


def test_find_fold_on_plain_images() -> None:
    def load(b: bytes) -> Image.Image:
        return Image.open(BytesIO(b))

    fold = find_fold(load(FILES["002"]))
    assert fold is not None and 560 <= fold <= 640
    assert find_fold(load(FILES["003"])) is None


# ── Супряга: пакет знає зйомку і скан кожної сторінки ───────────────────────
def _fetched(dest: Path, *, split: bool = True) -> Path:
    from nyshporka.cases.acquire import record_fetch

    src = _source(Site())
    res = src.fetch(UNIT, dest, split=split)
    record_fetch(dest, res, source="skanoteka", ref=UNIT, url=UNIT, want=3)
    return dest


def test_bundle_gets_unit_ref_and_page_src(tmp_path: Path) -> None:
    from nyshporka.share import align
    from nyshporka.share.publish import _refs_from_sidecar

    d = _fetched(tmp_path / "a")
    assert _refs_from_sidecar(d) == [
        {"source": "skanoteka", "ref": "unit:sadowe/1703/160", "url": UNIT}]
    assert [(f["name"], f.get("src")) for f in align.frames_of(d)] == [
        ("001.jpg", "001"), ("002_L.jpg", "002L"), ("002_R.jpg", "002R"), ("003.jpg", "003")]


def test_two_people_same_unit_align_exactly(tmp_path: Path) -> None:
    """Однакове джерело — однакові імена й `src`: чужий текст лягає на свої кадри."""
    from nyshporka.share import align

    theirs = align.frames_of(_fetched(tmp_path / "їхнє"))
    ours = _fetched(tmp_path / "наше")
    assert align.page_names(theirs, ours) == {n: n for n in
                                              ("001.jpg", "002_L.jpg", "002_R.jpg", "003.jpg")}


def test_split_and_whole_do_not_pretend_to_align(tmp_path: Path) -> None:
    """Один різав, другий ні: сторінки різні, і точної прив'язки немає — чесно."""
    from nyshporka.share import align

    theirs = align.frames_of(_fetched(tmp_path / "їхнє"))
    ours = _fetched(tmp_path / "наше", split=False)
    assert align.page_names(theirs, ours) == {}


def test_cli_whole_refused_for_sources_without_spreads(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cli import app

    out = CliRunner().invoke(app, ["get", "commons", "file:X.pdf", "--out",
                                   str(tmp_path), "--whole"])
    assert out.exit_code == 2 and "розворотів не ріже" in out.output


@pytest.mark.parametrize(("shift", "aligned"), [(0, True), (2, True), (38, False)])
def test_same_src_but_other_cut_is_not_the_same_page(tmp_path: Path, shift: int,
                                                     aligned: bool) -> None:
    """🔴 Дві редакції детектора різали скан 185 ЦДІАК 2-1-160 на x=2878 і 2916:
    ті самі імена й `src`, а права сторінка зсунута. Точна прив'язка — лише
    коли збігся й різ (допуск кілька пікселів)."""
    from nyshporka.share import align

    theirs_dir = _fetched(tmp_path / "їхнє")
    ours = _fetched(tmp_path / "наше")
    f = ours / "_skanoteka.json"
    book = json.loads(f.read_text(encoding="utf-8"))
    for name in ("002_L.jpg", "002_R.jpg"):
        box = book["frames"]["002"]["pages"][name]["box"]
        box[0 if name.endswith("R.jpg") else 2] += shift
    f.write_text(json.dumps(book), encoding="utf-8")
    theirs = align.frames_of(theirs_dir)
    assert theirs[1]["box"][2] == theirs[2]["box"][0], "межі різу їдуть у frames.jsonl"
    assert bool(align.page_names(theirs, ours)) is aligned
