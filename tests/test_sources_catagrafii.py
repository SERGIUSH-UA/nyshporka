"""📜 Катаграфії Бессарабії: обхід із приймачем повноти, пошук за селом, шифра, дзеркало.

Мережі тут немає: сайт підставлено двійником. Рядки — у форматі файлів сайту
(знімок 10.10.2026), справи й кадри вигадані.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from nyshporka.fonds.collect.base import CollectError, Target
from nyshporka.fonds.collect.catagrafii import CatagrafiiCollector
from nyshporka.sources.base import SourceError
from nyshporka.sources.catagrafii import (
    CatagrafiiSource,
    consonants,
    reels,
    skeleton,
)
from nyshporka.sources.http import Fetcher

D_HEAD = ("dosar,year_from,year_to,title_ro,title_en,title_fr,title_ru,county,villages,"
          "microfilm,image_range,image_count,confidence,familysearch_url,inventory_page")
L_HEAD = ("dosar,volume,prefix,village,village_ru,county,folios,folio_from,folio_to,"
          "microfilm,image_range,image_count,confidence,image,familysearch_url")

DOSSIERS = [
    ["1", "1835", "1835", "Catagrafii cu ţărani din satele judeţului Orhei pentru anul 1835",
     "", "", "Ревизские сказки крестьян сёл Оргеевского уезда за 1835 год.", "Orhei", "4",
     "1000001 · 1000002", "61–1055 · 5–720", "1711", "sur",
     "https://www.familysearch.org/ark:/61903/3:1:AAAA?i=1", "2"],
    ["2", "1850", "1851", "Catagrafii cu ţărani din satele judeţului Cahul pentru anii 1850-1851",
     "", "", "Ревизские сказки крестьян сёл Кагульского уезда за 1850-1851 годы.", "Cahul",
     "2", "1000003", "852–980", "129", "estime", "", "30-31"],
    ["3", "1857", "1857", "Catagrafii cu ţărani din satele judeţului Iaşi pentru anul 1857",
     "", "", "Ревизские сказки крестьян сёл Ясского уезда за 1857 год.", "Iaşi", "2",
     "", "", "", "", "", "40"],
]
LINES = [
    ["1", "", "s.", "Beşghioz (Cupcui)", "Бешгиоз (Купкуй)", "", "1-20", "1", "20",
     "", "", "", "", "", ""],
    ["1", "", "s.", "Bravicea", "Бравича", "", "21-40", "21", "40", "", "", "", "", "77",
     "https://www.familysearch.org/ark:/61903/3:1:BBBB?i=76"],
    ["1", "II", "s.", "Ţahnăuţi", "Цахнэуць", "", "5-9", "5", "9",
     "1000002", "300–330", "31", "exacte", "", ""],
    ["1", "I", "s.", "Şercani", "Шеркань", "", "41-60", "41", "60", "", "", "", "", "", ""],
    ["2", "", "s.", "Tomai", "Томай", "", "1-64v", "1", "64", "", "", "", "", "", ""],
    ["2", "", "s.", "Soroceni", "Сороченй", "", "65-80", "65", "80", "", "", "", "", "", ""],
    ["3", "", "s.", "Tomai", "Томай", "", "1-12", "1", "12", "", "", "", "", "", ""],
    ["3", "", "s.", "Sângerei", "Сынджерей", "", "13-30", "13", "30", "", "", "", "", "", ""],
]
DICTIONARY = "Generated: 3 archival files, 8 inventory lines, 8 village spellings, 1835-1857."


def _csv(head: str, rows: list[list[str]]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head.split(","))
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


class _Resp:
    def __init__(self, body: bytes) -> None:
        self.content = body
        self.text = body.decode("utf-8")
        self.headers: dict[str, str] = {}
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class _Site:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.asked: list[str] = []

    def get(self, url: str) -> _Resp:
        path = "/" + url.split("//", 1)[-1].split("/", 1)[-1]
        self.asked.append(path)
        return _Resp(self.files[path])


def _files(dossiers: list[list[str]] = DOSSIERS, lines: list[list[str]] = LINES,
           dictionary: str = DICTIONARY) -> dict[str, bytes]:
    return {"/data/dossiers.csv": _csv(D_HEAD, dossiers),
            "/data/lignes.csv": _csv(L_HEAD, lines),
            "/data/DICTIONNAIRE.md": dictionary.encode("utf-8")}


def _src(ws: Path, files: dict[str, bytes] | None = None) -> CatagrafiiSource:
    site = _Site(files or _files())
    return CatagrafiiSource(ws, http=Fetcher(base="https://idx", delay=0.0, client=site))


@pytest.fixture
def crawled(tmp_path: Path) -> CatagrafiiSource:
    src = _src(tmp_path)
    src.crawl()
    return src


def _tree(ws: Path, films: list[str]) -> None:
    """Дерево регіону дзеркала в кеші простору — з теками плівок."""
    tree: dict[str, object] = {"": {"files": []},
                               "_1000000 - 1000500 - 500 плёнок/": {"files": []}}
    for f in films:
        tree[f"_1000000 - 1000500 - 500 плёнок/{f}/"] = {"files": ["0001.jpg", "0002.jpg"]}
    blob = ws / "data" / "cache" / "fsfiles" / "moldova.json.gz"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(gzip.compress(json.dumps(
        {"rootId": "/media/mihailo/x", "tree": tree}).encode("utf-8")))


# ── обхід ────────────────────────────────────────────────────────────────────

def test_crawl_keeps_the_files_verbatim_with_their_hashes(crawled: CatagrafiiSource) -> None:
    kind, info = crawled.catalog_source()
    assert kind == "workspace" and info["rows"] == len(LINES) and info["cases"] == 3
    assert crawled.snap_dir is not None
    state = json.loads((crawled.snap_dir / "state.json").read_text(encoding="utf-8"))
    body = (crawled.snap_dir / "lignes.csv").read_bytes()
    assert body == _files()["/data/lignes.csv"]
    assert state["sha256"]["lignes.csv"] == hashlib.sha256(body).hexdigest()
    assert state["declared"] == {"dossiers": 3, "lines": 8}


def test_a_truncated_file_writes_nothing(tmp_path: Path) -> None:
    """Справа оголошує більше сіл, ніж прийшло рядків: обрізаний файл виглядав би повним."""
    src = _src(tmp_path, _files(lines=LINES[:-1],
                                dictionary="Generated: 3 archival files, 7 inventory lines"))
    with pytest.raises(SourceError, match="знімок не записано"):
        src.crawl()
    assert src.catalog_source()[0] == "none"


def test_the_site_declaration_must_agree_with_the_files(tmp_path: Path) -> None:
    src = _src(tmp_path, _files(dictionary="Generated: 4 archival files, 8 inventory lines"))
    with pytest.raises(SourceError, match="оголошує справ 4"):
        src.crawl()


def test_a_changed_format_is_named(tmp_path: Path) -> None:
    files = _files()
    files["/data/lignes.csv"] = b"dosar,name\n1,x\n"
    with pytest.raises(SourceError, match="формат змінився"):
        _src(tmp_path, files).crawl()


def test_without_snapshot_search_refuses_instead_of_zero(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="nysh crawl catagrafii"):
        CatagrafiiSource(tmp_path).search("Tomai")


# ── пошук за селом ───────────────────────────────────────────────────────────

def test_romanian_letters_fold_with_cyrillic() -> None:
    assert skeleton("Beşghioz") == skeleton("Besgioz")
    assert skeleton("Sângerei") == skeleton("Sîngerei")
    assert skeleton("Ţahnăuţi")[:4] == skeleton("Цахнэуць")[:4] == "cahn"
    # румунське «ău/eu» — це «ов/ів» історичної назви
    assert consonants("Ţareuca") == consonants("Царівка")


def test_diacritics_are_not_needed(crawled: CatagrafiiSource) -> None:
    hits = crawled.search("Besgioz")
    assert [h.shifra for h in hits] == ["ANRM 134-2-1"]
    assert hits[0].page == 1 and hits[0].repo == "ANRM" and hits[0].fond == "134"
    assert [h.place.split(" · ")[0] for h in crawled.search("Sîngerei")] == ["Sângerei"]


def test_russian_rendering_is_searched_too(crawled: CatagrafiiSource) -> None:
    assert [h.place.split(" · ")[0] for h in crawled.search("Цахнэуць")] == ["Ţahnăuţi"]


def test_historic_name_comes_as_a_near_spelling(crawled: CatagrafiiSource) -> None:
    """«Бравичи» з довідника — не підрядок «Bravicea/Бравича», але те саме село."""
    hits = crawled.search("Бравичи")
    assert [h.place.split(" · ")[0] for h in hits] == ["Bravicea"]
    assert "схоже написання" in hits[0].note


def test_near_spellings_only_when_nothing_matches(crawled: CatagrafiiSource) -> None:
    """«Шеркани» має збіг — кістяк «srcn» (Soroceni) тоді не питається."""
    hits = crawled.search("Шеркань")
    assert [h.place.split(" · ")[0] for h in hits] == ["Şercani"]
    assert "схоже" not in hits[0].note


def test_a_year_keeps_only_cases_that_cover_it(crawled: CatagrafiiSource) -> None:
    assert [h.shifra for h in crawled.search("Tomai")] == ["ANRM 134-2-2", "ANRM 134-2-3"]
    assert [h.shifra for h in crawled.search("Томай 1857")] == ["ANRM 134-2-3"]
    assert crawled.search("1857") == []


def test_a_line_says_whose_frames_it_gives(crawled: CatagrafiiSource) -> None:
    """Кадри справи — на всю справу; власні кадри села — лише де покажчик їх звірив."""
    tah = crawled.search("Ţahnăuţi")[0]
    assert "кадри села: плівка 1000002, кадри 300-330" in tah.note
    assert tah.shifra == "ANRM 134-2-1, т.II" and tah.frames == 31
    brav = crawled.search("Bravicea")[0]
    assert "кадри на всю справу" in brav.note
    assert "кадр села в переглядачі FS: 77" in brav.note
    assert brav.url.endswith("BBBB?i=76") and not brav.acquirable


def test_estimated_bounds_are_said(crawled: CatagrafiiSource) -> None:
    assert "оцінено інтерполяцією" in crawled.search("Soroceni")[0].note


# ── за шифрою ────────────────────────────────────────────────────────────────

def test_case_gives_itself_then_villages_by_volume_and_sheet(crawled: CatagrafiiSource) -> None:
    hits = crawled.find_case("134", "2", "1")
    assert hits[0].ref == "cat:1" and hits[0].title.startswith("Catagrafii")
    assert hits[0].frames == 1711 and "сіл 4" in hits[0].note
    assert [h.place.split(" · ")[0] for h in hits[1:]] == [
        "Beşghioz (Cupcui)", "Bravicea", "Şercani", "Ţahnăuţi"]


def test_other_shifra_is_empty_not_a_guess(crawled: CatagrafiiSource) -> None:
    assert crawled.find_case("134", "2", "1", repo="DAZHO") == []
    assert crawled.find_case("211", "2", "1") == []
    assert crawled.find_case("134", "5", "1") == []
    assert crawled.find_case("134", "2", "99") == []


def test_two_reels_pair_by_position() -> None:
    assert reels("1000001 · 1000002", "61–1055 · 5–720") == [("1000001", "61-1055"),
                                                             ("1000002", "5-720")]
    assert reels("2360600 · 2360600", "5–90 · 400–420") == [("2360600", "5-90"),
                                                            ("2360600", "400-420")]


# ── дзеркало ─────────────────────────────────────────────────────────────────

def test_case_on_the_mirror_gives_the_command(tmp_path: Path) -> None:
    _tree(tmp_path, ["1000001", "1000003"])
    src = _src(tmp_path)
    src.crawl()
    note = src.find_case("134", "2", "1")[0].note
    assert ('`nysh get fsfilm "moldova/_1000000 - 1000500 - 500 плёнок/1000001" '
            '--frames 61-1055 --out <тека>`') in note
    assert "плівка 1000002, кадри 5-720 (на дзеркалі moldova її немає" in note
    line = src.search("Tomai 1850")[0].note
    assert "дзеркало `moldova/_1000000 - 1000500 - 500 плёнок/1000003`" in line


def test_without_the_tree_the_mirror_is_not_claimed(crawled: CatagrafiiSource) -> None:
    note = crawled.find_case("134", "2", "1")[0].note
    assert "дзеркало не звірено" in note and "її немає" not in note


# ── збирач реєстру ───────────────────────────────────────────────────────────

def test_collector_is_only_for_its_fond(tmp_path: Path) -> None:
    col = CatagrafiiCollector(tmp_path, source=_src(tmp_path))
    assert not col.plan(Target("ANRM", "211")).ready
    assert not col.plan(Target("ANRM", "134", ("1",))).ready
    with pytest.raises(CollectError, match=r"лише ANRM ф.134"):
        col.collect(Target("DAZHO", "134"), dest=tmp_path / "reg")


def test_collector_writes_films_and_names_what_it_cannot(tmp_path: Path) -> None:
    from nyshporka.fonds.merge.sources import SourceBook, read_tsv
    from nyshporka.fonds.merge.titles import fuse_text

    col = CatagrafiiCollector(tmp_path, source=_src(tmp_path))
    plan = col.plan(Target("ANRM", "134"))
    assert plan.ready and plan.requests == 3
    res = col.collect(Target("ANRM", "134"), dest=tmp_path / "reg")
    rows = {r["spr_int"]: r for r in read_tsv(res.out)}
    assert rows["1"]["fs_film"] == "1000001" and rows["1"]["opys"] == "2"
    assert rows["3"]["fs_film"] == "" and rows["2"]["year_to"] == "1851"
    blind = {b.kind: b.count for b in res.blind}
    assert blind == {"second_reel": 1, "no_film": 1}
    assert res.quality["з плівкою"] == 2

    reg, _conf = fuse_text(SourceBook(rows={"catagrafii": read_tsv(res.out)}))
    r = reg[("2", "1", "")]
    assert r["title_src"] == "catagrafii" and r["fs_film"] == "1000001"
    assert r["fs_url"].endswith("AAAA?i=1")


def test_a_film_without_dgs_is_a_free_channel_not_an_order(tmp_path: Path) -> None:
    """Плівка справи без DGS — вільний канал; інакше весь фонд ліг би в замовлення."""
    from nyshporka.fonds.merge.run import merge_fond

    reg = tmp_path / "reg"
    CatagrafiiCollector(tmp_path, source=_src(tmp_path)).collect(
        Target("ANRM", "134"), dest=reg)
    res = merge_fond(Target("ANRM", "134"), dest=reg, out=tmp_path / "f134_opys_merged.tsv")
    assert res.channels["film"] == 2 and res.channels["order"] == 1
