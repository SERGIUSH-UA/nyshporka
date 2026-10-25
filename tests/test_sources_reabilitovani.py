"""🕯 «Реабілітовані історією»: розбір OCR-статей, пошук, кеш, відмови.

Мережі тут немає. Томи — вигадані, у форматі, знятому з живих томів 25.10.2026:
подвійні пробіли між словами, переноси «¬», колонтитул із номером і дороговказом,
рік із пробілом усередині («1 926»), стаття на розриві сторінок. Імена й села
вигадані (Вигадане, Лісове, Березівка).
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources import reabilitovani as R
from nyshporka.sources.base import SourceError
from nyshporka.sources.reabilitovani import (
    ReabilitovaniSource,
    first_date,
    norm,
    parse_query,
    parse_volume,
    resolve_oblast,
    spans_of_pageindex,
)


def sp(s: str) -> str:
    """Подвійні пробіли між словами — як віддає OCR searchtext."""
    return "  ".join(s.split(" "))


PAGES = [
    "ТИТУЛ\n" + sp("Реабілітовані історією"),
    "\n".join([
        "12", sp("Біографічні довідки про репресованих"), "КОВ",
        sp("КОВАЛЕНКО Петро Іванович, 1 904 р. н., с. Лісове Вигаданського району, "
           "українець, освіта початкова. Проживав у с. Лісове, селянин. Заарештований "
           "07.02.1949. Звинувачення: допомагав підпіллю. Військовим три¬"),
        sp("буналом військ МВС Вигаданської області 31.03.1949 засуджений на 10 років "
           "позбавлення волі. Реабілітований 18.09.1992. (9731 П)."),
        sp("КОВАЛЕНКО Марія Степанівна, 1925 р. н., с. Лісове Вигаданського району, "
           "українка, малописьменна. Проживала в с. Лісове, селянка. Заарештована "
           "15.03.1951. Звинувачення: постачала продукти. Військовим трибуналом "
           "28.06.1951 засуджена на 25 років. Реабілітована 24.02.1992. (7483 П)."),
        sp("ШЕВЧУК Іван Петрович, 1899 р. н., с. Березівка Вигаданського району, "
           "українець, освіта початкова. Проживав у м. Вигадане, коваль. Заарештований "
           "10.10.1946. Звинувачення: зв’язковий, ховав зброю"),
    ]) + "\n",
    "\n".join([
        "13", sp("Біографічні довідки про репресованих"), "ШЕВ",
        sp("у с. Лісове. Військовим трибуналом 20.02.1947 засуджений на 8 років. "
           "Реабілітований 02.11.1992. (14289 ТІ)."),
        sp("ЩУКА Олена, 1 926 р., с. Тихе Вигаданського району, українка. Проживала "
           "в с. Тихе, доярка. Заарештована 3.04.1948. Звинувачення: зв’язкова. "
           "Особливою нарадою 30.07.1948 засуджена на 10 років. Реабілітована "
           "11.11.1990. (1Ї456)."),
        sp("УГА — Українська Галицька Армія"),
        sp("Мельник Степан Андрійович, 1903 р., с. Тихе, освіта початкова. "
           "Заарештований 07. 12. 1944 р. ВКР СМЕРНІ (ст. 54- 1а КК УРСР). Підтримував "
           "зв’язок з УПА. Засуджений 19.04.1947 р. ВТ на 10 р. ВТТ. Звільнений "
           "28.03.1956 р. Реабі¬ літований 16.08.1991 р. (11356-П)."),
    ]) + "\n",
]


def text_and_index(pages: list[str]) -> tuple[str, list[list[int]]]:
    text = "".join(pages)
    idx: list[list[int]] = []
    pos = 0
    for p in pages:
        idx.append([pos, pos + len(p), 0, 0])
        pos += len(p)
    return text, idx


TEXT, INDEX = text_and_index(PAGES)
SPANS = [(a, b) for a, b, _, _ in INDEX]


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


# ── зведення написань і дати ────────────────────────────────────────────────

def test_norm_folds_ocr_and_spelling_differences() -> None:
    assert norm("Дем’янчук") == norm("ДЕМ'ЯНЧУК") == norm("Дем янчук")
    assert norm("Ґоша") == norm("Гоша")
    assert norm("Мїлий") == norm("Милий")
    # латинська «i» й «o» в кириличному слові
    assert norm("Кoвaленкo") == norm("Коваленко")


def test_first_date_numeric_textual_and_ocr_garbled() -> None:
    assert first_date("арешт 07.02.1949.") == "07.02.1949"
    assert first_date("з 16:03.1951.") == "16.03.1951"
    assert first_date("26:02. 1 946.") == "26.02.1946"
    assert first_date("15 березня 1938 р.") == "15.03.1938"
    assert first_date("жодної дати") == ""
    assert first_date("45.13.1950") == ""   # місяць 13 — не дата


# ── розбір тому ─────────────────────────────────────────────────────────────

def test_parse_volume_finds_all_articles_and_fields() -> None:
    arts, _ = parse_volume(TEXT, SPANS)
    names = [(a.surname, a.name) for a in arts]
    assert names == [("КОВАЛЕНКО", "Петро"), ("КОВАЛЕНКО", "Марія"), ("ШЕВЧУК", "Іван"),
                     ("ЩУКА", "Олена"), ("Мельник", "Степан")], names
    petro = arts[0]
    assert petro.patronymic == "Іванович"
    assert petro.born == "1904"            # «1 904» → 1904
    assert petro.birth_place == "с. Лісове Вигаданського району"
    assert petro.residence == "с. Лісове"
    assert petro.occupation == "селянин"
    assert petro.arrest == "07.02.1949"
    assert petro.charge == "допомагав підпіллю."
    assert "Вигаданської області 31.03.1949 засуджений на 10 років" in petro.verdict
    assert petro.rehab == "18.09.1992"
    assert petro.case_no == "9731 П"
    assert "трибуналом" in petro.text      # «три¬ / буналом» склеєно
    assert "Вигаданської" in petro.text
    assert petro.leaf == 1 and petro.leaf_end == 1


def test_article_over_page_break_gets_start_leaf_and_end_leaf() -> None:
    arts, _ = parse_volume(TEXT, SPANS)
    shev = next(a for a in arts if a.surname == "ШЕВЧУК")
    assert shev.leaf == 1 and shev.leaf_end == 2
    # колонтитул наступної сторінки не потрапив у середину статті
    assert "Біографічні" not in shev.text and "ШЕВ " not in shev.text
    assert "ховав зброю у с. Лісове" in shev.text
    assert shev.rehab == "02.11.1992"
    assert shev.case_no == "14289"          # «ТІ» замість «П» — «П» не вгадується


def test_ocr_damaged_case_number_is_left_empty_not_guessed() -> None:
    arts, _ = parse_volume(TEXT, SPANS)
    shchuka = next(a for a in arts if a.surname == "ЩУКА")
    assert shchuka.born == "1926"
    assert shchuka.case_no == ""            # «(1Ї456)» — літера на місці цифри
    assert shchuka.arrest == "03.04.1948"
    assert shchuka.residence == "с. Тихе"


def test_capitalised_surname_format_and_soft_hyphen_in_keyword() -> None:
    arts, _ = parse_volume(TEXT, SPANS)
    mel = next(a for a in arts if a.surname == "Мельник")
    assert mel.birth_place == "с. Тихе"
    assert mel.arrest == "07.12.1944"
    assert mel.rehab == "16.08.1991"       # «Реабі¬ літований» знайдено
    assert mel.case_no == "11356 П"
    assert mel.full_name == "Мельник Степан Андрійович"
    assert next(a for a in arts if a.surname == "КОВАЛЕНКО").full_name == \
        "Коваленко Петро Іванович"


def test_abbreviation_line_is_not_an_article() -> None:
    arts, _ = parse_volume(TEXT, SPANS)
    assert all("Галицька" not in a.text[:40] for a in arts)
    assert len(arts) == 5


def test_ocr_damaged_start_and_place_still_found() -> None:
    """«л ТЕСТОВИЙ…» (шматок сусіднього рядка), «с : Тихе», «у,с . Тихе»."""
    page = "14\n" + sp(
        "л ТЕСТОВИЙ Олег Петрович, 1919. р. н., с: Тихе Вигаданського району, "
        "українець. Проживав у,с . Тихе, селянин. Заарештований 07.02.1949. "
        "Звинувачення: допомагав. Реабілітований 01.03.1993. (10994 П).") + "\n"
    text, idx = text_and_index([page])
    arts, _ = parse_volume(text, [(a, b) for a, b, _, _ in idx])
    assert [(a.surname, a.born) for a in arts] == [("ТЕСТОВИЙ", "1919")]
    art = arts[0]
    assert art.residence.endswith("с. Тихе")
    q = parse_query("село:Тихе")
    assert ReabilitovaniSource._match(art, q, fuzzy=False)
    assert not ReabilitovaniSource._match(art, parse_query("село:Березівка"), fuzzy=False)


def test_districts_come_from_running_headers() -> None:
    pages = [f"{n}\nБіографічні довідки\nВигаданський район\n" for n in range(4)]
    text, idx = text_and_index(pages)
    _, districts = parse_volume(text, [(a, b) for a, b, _, _ in idx])
    assert districts == ["Вигаданський"]


def test_pageindex_must_fit_text() -> None:
    assert spans_of_pageindex(INDEX, len(TEXT)) == SPANS
    with pytest.raises(SourceError, match="не лягають на текст"):
        spans_of_pageindex([[0, 10, 0, 0], [10, 99999, 0, 0]], 100)
    with pytest.raises(SourceError, match="не з діапазоном"):
        spans_of_pageindex([["a", "b"]], 100)
    with pytest.raises(SourceError, match="не схожий"):
        spans_of_pageindex({}, 100)


# ── запит ───────────────────────────────────────────────────────────────────

def test_parse_query_person_place_and_filters() -> None:
    q = parse_query("Шевчук Іван Петрович oblast:Івано-Франківська book:3")
    assert (q.surname, q.name, q.patronymic) == ("Шевчук", "Іван", "Петрович")
    assert (q.oblast, q.book, q.place) == ("Івано-Франківська", "3", "")
    q = parse_query('село:"Слобода Болехівська" born:1904')
    assert q.place == "Слобода Болехівська" and q.born == "1904" and not q.has_person
    q = parse_query("село:Лісове Коваленко")
    assert q.place == "Лісове" and q.surname == "Коваленко"
    with pytest.raises(SourceError, match="рік"):
        parse_query("Шевчук born:abc")
    with pytest.raises(SourceError, match="номер тому"):
        parse_query("Шевчук book:x")


def test_resolve_oblast_ukrainian_latin_and_ambiguity() -> None:
    assert resolve_oblast("Івано-Франківська") == "Ivano-Frankivska_oblast"
    assert resolve_oblast("ivano") == "Ivano-Frankivska_oblast"
    assert resolve_oblast("Автономна") == "Avtonomna_Respublika_Krym"
    with pytest.raises(SourceError, match="немає серед томів"):
        resolve_oblast("Атлантида")
    with pytest.raises(SourceError, match="кількох областей"):
        resolve_oblast("Ч")


# ── джерело на двійнику мережі ──────────────────────────────────────────────

class _Resp:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.text = content.decode("utf-8", errors="replace")


class FakeIA:
    """Двійник archive.org: метадані запису й файли томів."""

    def __init__(self, *, corrupt: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.files: dict[str, bytes] = {}
        self.corrupt = corrupt or set()
        for slug, book, pages in (("Poltavska_oblast", 2, PAGES),
                                  ("Ivano-Frankivska_oblast", 1, PAGES[:2])):
            text, idx = text_and_index(pages)
            doc = f"{slug}_k.{book}"
            self.files[f"{doc}_hocr_searchtext.txt.gz"] = gzip.compress(text.encode("utf-8"))
            self.files[f"{doc}_hocr_pageindex.json.gz"] = gzip.compress(
                json.dumps(idx).encode("utf-8"))
            self.files[f"{doc}_page_numbers.json"] = json.dumps({"pages": [
                {"leafNum": i, "pageNumber": str(10 + i) if i else ""}
                for i in range(len(pages))]}).encode("utf-8")
        # том без індексу сторінок — до каталогу не потрапляє
        self.files["Odeska_oblast_k.1_hocr_searchtext.txt.gz"] = gzip.compress(b"x")

    def metadata(self) -> bytes:
        files = [{"name": n, "size": str(len(b)), "md5": md5(b)}
                 for n, b in self.files.items()]
        files.append({"name": "Poltavska_oblast_k.2.pdf", "size": "1", "md5": "0"})
        return json.dumps({"files": files}).encode("utf-8")

    def get(self, url: str, client: Any = None, *, max_bytes: int = 0,
            deadline_s: float = 0.0) -> _Resp:
        self.calls.append(url)
        if url.endswith("/metadata/reabilitovani"):
            return _Resp(self.metadata())
        name = url.rsplit("/", 1)[-1]
        from urllib.parse import unquote

        body = self.files[unquote(name)]
        if unquote(name) in self.corrupt:
            body = body[:-3] + b"xyz"
        return _Resp(body)

    def downloads(self) -> list[str]:
        return [c for c in self.calls if "/download/" in c]


def _src(tmp_path: Path, ia: FakeIA | None = None) -> tuple[ReabilitovaniSource, FakeIA]:
    ia = ia or FakeIA()
    return ReabilitovaniSource(tmp_path, fetcher=ia), ia  # type: ignore[arg-type]


def test_catalog_lists_only_volumes_with_text_and_index(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    vols = src.catalog()
    assert [(v.slug, v.book) for v in vols] == [("Ivano-Frankivska_oblast", 1),
                                                ("Poltavska_oblast", 2)]
    assert vols[0].label == "Івано-Франківська область, кн. 1"


def test_search_by_surname_gives_page_url_case_and_full_article(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    hits = src.search("Коваленко", limit=10)
    # той самий том двічі (дві області-двійники): 2 статті × 2 томи
    assert len(hits) == 4
    h = next(x for x in hits if x.title == "Коваленко Петро Іванович")
    assert h.years == "1904"
    assert h.place == "с. Лісове"
    assert "спр. 9731 П" in h.shifra
    assert "область, кн. " in h.shifra
    assert h.url == ("https://archive.org/details/reabilitovani/"
                     f"{h.ref.split(':')[0]}/page/n1/mode/1up")
    assert h.page == 1
    assert "Реабілітований 18.09.1992" in h.note
    assert "с. 11" in h.note              # друкований номер сторінки з page_numbers
    assert h.acquirable is False


def test_search_name_patronymic_narrow_and_place_mode(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    one = src.search("Коваленко Марія oblast:Полтавська", limit=10)
    assert [h.title for h in one] == ["Коваленко Марія Степанівна"]
    by_place = src.search("село:Тихе oblast:Полтавська", limit=10)
    assert sorted(h.title.split()[0] for h in by_place) == ["Мельник", "Щука"]
    # зведене написання: регістр і пробіли не заважають
    assert len(src.search('село:"ТИ ХЕ" oblast:Полтавська', limit=10)) == 2
    assert [h.title for h in src.search("Шевчук born:1899 oblast:Полтавська")] == \
        ["Шевчук Іван Петрович"]
    assert src.search("Шевчук born:1900 oblast:Полтавська") == []


def test_near_match_is_flagged_and_listed_after_exact(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    hits = src.search("Ковальонко oblast:Полтавська", limit=10)
    assert [h.title for h in hits] == ["Коваленко Петро Іванович",
                                       "Коваленко Марія Степанівна"]
    assert all(h.note.startswith("наближений збіг") for h in hits)
    exact = src.search("Коваленко oblast:Полтавська", limit=10)
    assert not any("наближений" in h.note for h in exact)


def test_zero_carries_coverage_denominator(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    hits = src.search("Невигаданий oblast:Полтавська")
    assert hits == [] and hits.truncated == ""
    kind, meta = src.catalog_source()
    assert kind == "live"
    assert meta["by_archive"] == {"Полтавська область · кн. 2 із 1": 5}
    assert meta["rows"] == 5


def test_cache_prevents_second_download_and_survives_new_instance(tmp_path: Path) -> None:
    src, ia = _src(tmp_path)
    src.search("Коваленко oblast:Полтавська")
    first = len(ia.downloads())
    assert first >= 2     # текст і індекс тому (і сторінка друку для знахідок)
    src.search("Шевчук oblast:Полтавська")
    # тому вже в пам'яті, але сторінка друку питається кешем, не мережею
    assert not [c for c in ia.downloads()[first:] if "searchtext" in c]
    src2, _ia2 = _src(tmp_path, ia)
    before = len(ia.downloads())
    assert len(src2.search("Коваленко oblast:Полтавська")) == 2
    assert len(ia.downloads()) == before        # усе з диска
    assert not any("/metadata/" in c for c in ia.calls[len(ia.calls) - 1:])


def test_catalog_cached_between_instances(tmp_path: Path) -> None:
    src, ia = _src(tmp_path)
    src.catalog()
    src2, _ = _src(tmp_path, ia)
    src2.catalog()
    assert [c for c in ia.calls if c.endswith("/metadata/reabilitovani")] == [
        f"{R.HOST}/metadata/{R.ITEM}"]


def test_corrupt_download_is_refused_and_not_cached(tmp_path: Path) -> None:
    ia = FakeIA(corrupt={"Poltavska_oblast_k.2_hocr_searchtext.txt.gz"})
    src, _ = _src(tmp_path, ia)
    with pytest.raises(SourceError, match=r"контрольна сума|байт"):
        src.search("Коваленко oblast:Полтавська")
    cache = tmp_path / "data" / "raw" / "reabilitovani" / "_cache"
    assert not list(cache.glob("*searchtext*"))


def test_fresh_limit_without_oblast_reports_unsearched_volumes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "FRESH_MAX", 1)
    src, ia = _src(tmp_path)
    hits = src.search("Коваленко")
    assert len(hits) == 2                                  # лише перший том
    assert "шукали в 1 із 2 томів" in hits.truncated
    assert "oblast:" in hits.truncated
    # наступний запит докачує решту з кешу першого
    hits2 = ReabilitovaniSource(tmp_path, fetcher=ia).search("Коваленко")  # type: ignore[arg-type]
    assert len(hits2) == 4 and hits2.truncated == ""


def test_limit_truncation_is_stated(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    hits = src.search("Коваленко", limit=1)
    assert len(hits) == 1
    assert "показано 1 із 4" in hits.truncated


def test_unknown_oblast_book_and_empty_filters_are_refusals(tmp_path: Path) -> None:
    src, _ = _src(tmp_path)
    with pytest.raises(SourceError, match="немає серед томів"):
        src.search("Коваленко oblast:Атлантида")
    with pytest.raises(SourceError, match="томів із текстом немає"):
        src.search("Коваленко oblast:Одеська")
    with pytest.raises(SourceError, match="тому 9"):
        src.search("Коваленко oblast:Полтавська book:9")
    with pytest.raises(SourceError, match="самі межі"):
        src.search("oblast:Полтавська")
    assert src.search("   ") == []


def test_offline_environment_is_a_refusal_not_zero(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.sources import http

    monkeypatch.setenv(http.ENV_OFFLINE, "1")
    src = ReabilitovaniSource(tmp_path)
    with pytest.raises(SourceError, match="мережу вимкнено"):
        src.search("Коваленко")


def test_without_workspace_works_in_memory_and_writes_nothing(tmp_path: Path) -> None:
    ia = FakeIA()
    src = ReabilitovaniSource(None, fetcher=ia)  # type: ignore[arg-type]
    assert len(src.search("Коваленко oblast:Полтавська")) == 2
    assert not list(tmp_path.iterdir())


def test_parser_version_bump_reparses_from_cached_raw(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, ia = _src(tmp_path)
    src.search("Коваленко oblast:Полтавська")
    n = len(ia.downloads())
    monkeypatch.setattr(R, "PARSER_VERSION", R.PARSER_VERSION + 1)
    src2, _ = _src(tmp_path, ia)
    assert len(src2.search("Коваленко oblast:Полтавська")) == 2
    assert len(ia.downloads()) == n          # сирий текст узято з диска


def test_registered_as_explicit_only_name_base() -> None:
    from nyshporka.sources.registry import load

    src = load(None).get("reabilitovani")
    assert src is not None
    assert getattr(src, "explicit_only", False) is True
    assert "search" in src.caps
