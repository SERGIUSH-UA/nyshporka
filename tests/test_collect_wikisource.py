"""📜 Вікіджерела: перелік справ фонду зі сторінок опису «Архів:».

🔴 Заради чого збирач: зведений покажчик дає лише частину щорічної серії книг
консисторії, і «онлайн немає» ставало там, де том лежав на FamilySearch.
Повний перелік із плівками — на сторінці опису у Вікіджерелах. Головний
приймач нижче — справа з колонкою FS: рік і плівка доходять до реєстру фонду.

Розбір таблиці — чисті функції; мережа — двійник із записаними відповідями.
Кожен формат таблиці колись коштував мовчазної втрати, а не падіння.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar

import pytest

from nyshporka.fonds.collect import tsv as T
from nyshporka.fonds.collect import wikisource as W
from nyshporka.fonds.collect.base import Target

FIX = Path(__file__).parent / "fixtures" / "registry"
DAZHO = (FIX / "wikisource_dazho_1_78.txt").read_text(encoding="utf-8")


# ── розбір таблиці ───────────────────────────────────────────────────────────
def test_fs_column_with_an_explanation_in_the_header_is_read() -> None:
    """🔴 «Посилання на FamilySearch<br/>для відсутніх справ»: точний аліас цю
    колонку не впізнавав, і плівки зникали мовчки — саме вони кажуть «онлайн»."""
    rows = {r["spr_raw"]: r for r in W.parse_opys_page(DAZHO)}
    assert rows["1023"]["fs_film"] == "100000123"
    assert (rows["1023"]["year_from"], rows["1023"]["year_to"]) == ("1826", "1826")
    assert rows["1023"]["folios"] == "712"
    assert rows["1023"]["uezd"] == "Острозький"
    assert rows["1023"]["title"].endswith("Села А-К · Острозький пов.")
    assert rows["1009"]["fs_film"] == "", "порожня комірка FS — порожньо, не сусіднє"


def test_letter_numbers_keep_their_letter() -> None:
    rows = {r["spr_raw"]: r for r in W.parse_opys_page(DAZHO)}
    assert (rows["198а"]["spr_int"], rows["198а"]["spr_letter"]) == ("198", "а")


IRNBUV = """{{Архіви/опис
| назва = Матеріали інвентарної реформи. Колекція архівних документів
| рік = 1628–1917
}}
{| class="wikitable"
|-
! Номер справи
! Назва (Заголовок одиниці зберігання)
! Крайні дати
! Кількість аркушів
! Примітка
|-
| 1-2
| Відомість про казенних поселян, їх землі та інші угіддя.
| Липень 1816 р.
| 16
| Оригінали
|-
| 22
| Інвентар села, що належить поміщику.
| -
| 41
| Копія
|-
| 29-35
| Інвентарні правила, інвентар, статистичний опис і план маєтку.
| 1845-1866
| 67
| Оригінали та копії
|}
"""


def test_multiline_table_is_read() -> None:
    """Кожна комірка своїм рядком: регекс по рядку давав тут 0 справ без помилки."""
    rows = W.parse_opys_page(IRNBUV)
    assert [r["spr_raw"] for r in rows] == ["1-2", "22", "29-35"]
    grp = rows[-1]
    assert (grp["spr_int"], grp["spr_letter"], grp["spr_to"]) == ("29", "", "35")
    assert (grp["year_from"], grp["year_to"], grp["folios"]) == ("1845", "1866", "67")
    assert grp["note"] == "Оригінали та копії"
    assert (rows[1]["spr_to"], rows[1]["year_from"]) == ("", "")


def test_page_template_is_not_a_case_row() -> None:
    rows = W.parse_opys_page(IRNBUV)
    assert not [r for r in rows if "Колекція" in r["title"]]


def test_header_columns_map_by_name() -> None:
    txt = ("{| class=\"wikitable sortable\"\n"
           "! № !! Назва !! Церква !! Нас. пункти !! Повіт !! Дати !! Арк. !! Примітки"
           " !! Посилання на FamilySearch\n"
           "|-\n"
           "|[[/1190/]]||Метрична книга||Покровська||с. Кленове||Полтавський||"
           "1790-1795||210||||[https://www.familysearch.org/records/images/search-results"
           "?imageGroupNumbers=110032617 110032617]\n"
           "|}\n")
    (r,) = W.parse_opys_page(txt)
    assert r["church"] == "Покровська" and r["uezd"] == "Полтавський"
    assert r["title"] == "Метрична книга · Покровська · с. Кленове · Полтавський пов."
    assert (r["year_from"], r["folios"], r["fs_film"]) == ("1790", "210", "110032617")


def test_link_with_label_and_cell_attributes() -> None:
    (r,) = W.parse_opys_page("{|\n|-\n|[[/2а/|2а]]||Назва справи||1801||5\n|}\n")
    assert (r["spr_int"], r["spr_letter"], r["title"]) == ("2", "а", "Назва справи")
    (r,) = W.parse_opys_page(
        "{|\n|- style=\"vertical-align:top\"\n| style=\"x\" | 7\n| Назва\n| 1801\n| 3\n|}\n")
    assert (r["spr_int"], r["title"], r["folios"]) == ("7", "Назва", "3")


def test_abbreviated_group_end_and_broken_group() -> None:
    (r,) = W.parse_opys_page("{|\n|-\n| 3548-550\n| Договір\n| 1793\n| 24\n|}\n")
    assert (r["spr_int"], r["spr_to"]) == ("3548", "3550")
    (r,) = W.parse_opys_page("{|\n|-\n| 3548-548\n| Договір\n| 1793\n| 24\n|}\n")
    assert (r["spr_int"], r["spr_to"]) == ("3548", "")


def test_years_are_min_max_and_folios_the_first_number() -> None:
    assert W.parse_years("1860-80, 1851, 1846") == ("1846", "1860")
    assert W._folios("126+3") == "126", "126 аркушів і 3 вкладні — не 1263"


def test_case_card_fills_the_gaps_but_never_erases() -> None:
    """🔴 Картка без `link_FS` не затирає плівку з таблиці."""
    row = {"title": "", "year_from": "", "year_to": "", "fs_film": "100000123",
           "commons_file": ""}
    card = W.parse_case_page("{{Архіви/справа\n| назва = Метрична книга\n| рік = 1826\n"
                             "| link_commons = [[c:File:ДАЖО 1-78-1023.pdf]]\n}}\n")
    assert card is not None
    W.merge_case(row, card)
    assert row["fs_film"] == "100000123"
    assert (row["title"], row["year_from"]) == ("Метрична книга", "1826")
    assert row["commons_file"] == "ДАЖО 1-78-1023.pdf" and row["src"] == "both"
    assert W.parse_case_page("просто текст") is None


def test_pages_are_classified_within_the_fond_only() -> None:
    titles = ["Архів:ДАЖО/1/78", "Архів:ДАЖО/1/78/1023", "Архів:ДАЖО/1/78/198а",
              "Архів:ДАЖО/1/Л2"]
    opysy, cases = W.WikisourceCollector.classify(titles, "ДАЖО", "1")
    assert set(opysy) == {"78", "Л2"}
    assert {c[1] for c in cases} == {"1023", "198а"}


# ── збирач із двійником мережі ───────────────────────────────────────────────
class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass


class _Api:
    """Двійник Вікіджерел: перелік сторінок — GET, тексти — POST пачками."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.seen: list[str] = []

    def get(self, url: str) -> _Resp:
        from urllib.parse import parse_qs, urlparse

        self.seen.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert q.get("list") == "allpages", url
        prefix = "Архів:" + q["apprefix"]
        hits = [{"title": t} for t in self.pages if t.startswith(prefix)]
        return _Resp(json.dumps({"query": {"allpages": hits}}))

    def post(self, url: str, data: dict[str, str] | None = None,
             json: object = None) -> _Resp:
        import json as _j

        titles = (data or {})["titles"].split("|")
        pages = [{"title": t, "revisions": [{"slots": {"main": {"content": self.pages[t]}}}]}
                 for t in titles if t in self.pages]
        return _Resp(_j.dumps({"query": {"pages": pages}}))


def _coll(api: _Api) -> W.WikisourceCollector:
    from nyshporka.sources.http import Fetcher

    return W.WikisourceCollector(fetcher=Fetcher(base="https://в", delay=0.0, client=api))


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Код архіву — підпис із паку; `codes` не потрібні."""
    from nyshporka import archives

    class _Repo:
        label = "ДАЖО"

    class _Pack:
        repositories: ClassVar[dict[str, object]] = {"DAZHO": _Repo()}

        def codes_for(self, repo: str, system: str) -> tuple[str, ...]:
            return ()

    monkeypatch.setattr(archives, "active", lambda: _Pack())


PAGES = {
    "Архів:ДАЖО/1/78": DAZHO,
    "Архів:ДАЖО/1/78/1023": ("{{Архіви/справа\n| назва = Метричні книги\n| рік = 1826\n"
                             "| link_commons = [[c:File:ДАЖО 1-78-1023.pdf]]\n}}\n"),
    "Архів:ДАЖО/1/78/1150": ("{{Архіви/справа\n| назва = Справа лише з картки\n"
                             "| рік = 1870\n| link_FS = https://www.familysearch.org/"
                             "search/film/104123456\n}}\n"),
    "Архів:ДАЖО/1/57": "== Справи ==\nопис ще не транскрибовано\n",
    # чужий фонд з тим самим початком номера — не наш
    "Архів:ДАЖО/10/1": "{|\n|-\n|[[/5/]]||Чужа справа||1900||1\n|}\n",
}


def test_collect_writes_what_merge_reads(tmp_path: Path, pack: None) -> None:
    api = _Api(PAGES)
    res = _coll(api).collect(Target(repo="DAZHO", fond="1"), dest=tmp_path)
    assert res.out.name == "wikisource.tsv"
    fields, rows = T.read_tsv(res.out)
    assert tuple(fields) == W.FIELDS
    by = {(r["opys"], r["spr_raw"]): r for r in rows}
    r1023 = by[("78", "1023")]
    assert (r1023["year_from"], r1023["fs_film"], r1023["src"]) == ("1826", "100000123", "both")
    assert r1023["commons_file"] == "ДАЖО 1-78-1023.pdf"
    assert by[("78", "1150")]["fs_film"] == "104123456", "справа лише з картки теж іде"
    assert not [r for r in rows if r["title"] == "Чужа справа"], "фонд 10 — не фонд 1"
    from urllib.parse import parse_qs, urlparse

    prefixes = {parse_qs(urlparse(u).query)["apprefix"][0] for u in api.seen}
    assert prefixes == {"ДАЖО/1/"}, "префікс без кінцевої `/` тягнув би фонди 10–19"
    kinds = {b.kind for b in res.blind}
    assert "no_table" in kinds, "опис без таблиці — названий, а не мовчазний нуль"
    assert res.quality["з плівкою FamilySearch"] >= 2


def test_void_positions_are_not_cases(tmp_path: Path, pack: None) -> None:
    """🔴 «Вільний номер» і «Справа вибула» — рядки таблиці, але не справи:
    у реєстрі вони стали б фантомами в черзі замовлень (ЦДІАК ф.224 — дві такі)."""
    pages = {"Архів:ДАЖО/1/9": ("{|\n|-\n|[[/1/]]||Метрична книга||1800||10\n"
                                "|-\n|[[/2/]]||вільний номер||||\n"
                                "|-\n|[[/3/]]||Справа вибула||||\n|}\n")}
    res = _coll(_Api(pages)).collect(Target(repo="DAZHO", fond="1"), dest=tmp_path)
    _, rows = T.read_tsv(res.out)
    assert [r["spr_int"] for r in rows] == ["1"]
    void = {b.kind: b for b in res.blind}["void"]
    assert void.count == 2 and void.where is not None and void.where.is_file()


def test_collect_keeps_opysy_it_did_not_touch(tmp_path: Path, pack: None) -> None:
    T.write_tsv(tmp_path / "wikisource.tsv", W.FIELDS,
                [{"opys": "74", "spr_int": "1", "title": "інший опис"}])
    res = _coll(_Api(PAGES)).collect(Target(repo="DAZHO", fond="1", opys=("78",)),
                                     dest=tmp_path)
    _, rows = T.read_tsv(res.out)
    assert {r["opys"] for r in rows} == {"74", "78"} and res.kept == 1


def test_plan_names_the_codes_it_tried(pack: None) -> None:
    p = _coll(_Api({})).plan(Target(repo="DAZHO", fond="1"))
    assert not p.ready and "ДАЖО" in p.why and "codes.wikisource" in p.needs


def test_unknown_archive_is_refused_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import archives

    class _Pack:
        repositories: ClassVar[dict[str, object]] = {}

        def codes_for(self, repo: str, system: str) -> tuple[str, ...]:
            return ()

    monkeypatch.setattr(archives, "active", lambda: _Pack())
    p = _coll(_Api(PAGES)).plan(Target(repo="NOPE", fond="1"))
    assert not p.ready and p.needs


def test_merge_turns_the_film_into_an_online_copy(tmp_path: Path, pack: None,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Приймач усього: після злиття справа 1023 має плівку в реєстрі фонду."""
    from nyshporka.fonds.merge.run import merge_fond

    reg = tmp_path / "registry"
    _coll(_Api(PAGES)).collect(Target(repo="DAZHO", fond="1"), dest=reg)
    monkeypatch.undo()                       # злиттю — справжній пак архівів
    out = tmp_path / "f1_opys_merged.tsv"
    merge_fond(Target(repo="DAZHO", fond="1"), dest=reg, out=out)
    _, rows = T.read_tsv(out)
    (row,) = [r for r in rows if r.get("opys") == "78" and r.get("spr_int") == "1023"]
    assert row["fs_dgs"] == "100000123" or row.get("fs_film") == "100000123"
    assert re.search(r"imageGroupNumbers=100000123", row.get("fs_url", ""))


def test_the_collector_is_registered() -> None:
    from nyshporka.fonds.collect.registry import load

    assert load().get("wikisource") is not None


def test_an_alias_finds_the_archive_spelled_otherwise(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    """Підпис паку «ІРНБУВ», а проєкт пише «ІР НБУВ» — так його знає псевдонім."""
    from nyshporka import archives

    class _Repo:
        label = "ІРНБУВ"
        aliases = ("ІР НБУВ", "Інститут рукопису НБУВ")

    class _Pack:
        repositories: ClassVar[dict[str, object]] = {"IRNBUV": _Repo()}

        def codes_for(self, repo: str, system: str) -> tuple[str, ...]:
            return ()

    monkeypatch.setattr(archives, "active", lambda: _Pack())
    pages = {"Архів:ІР НБУВ/6/1": "{|\n|-\n| 29-35\n| Інвентар маєтку\n| 1845\n| 67\n|}\n"}
    coll = _coll(_Api(pages))
    p = coll.plan(Target(repo="IRNBUV", fond="6"))
    assert p.ready and p.opys == ("1",)
    res = coll.collect(Target(repo="IRNBUV", fond="6"), dest=tmp_path)
    assert res.rows == 1 and "ІР НБУВ" in res.notes[0]


# ── збій — не нуль ───────────────────────────────────────────────────────────
class _Lame(_Api):
    """Двійник, у якого тексти віддає не API, а щось інше (503, помилка, обрізка)."""

    def __init__(self, pages: dict[str, str], body: str = "", drop: int = 0,
                 cont: bool = False) -> None:
        super().__init__(pages)
        self.body, self.drop, self.cont = body, drop, cont
        self.posts = 0

    def post(self, url: str, data: dict[str, str] | None = None,
             json: object = None) -> _Resp:
        import json as _j

        self.posts += 1
        if self.body:
            return _Resp(self.body)
        titles = [t for t in (data or {})["titles"].split("|") if t in self.pages]
        if self.cont and "rvcontinue" not in (data or {}):
            # Перша відповідь — лише половина текстів і `continue` на решту.
            half = titles[: len(titles) // 2]
            pages = [{"title": t, "revisions": [{"slots": {"main": {
                "content": self.pages[t]}}}]} for t in half]
            pages += [{"title": t} for t in titles[len(half):]]
            return _Resp(_j.dumps({"continue": {"rvcontinue": "x", "continue": "||"},
                                   "query": {"pages": pages}}))
        if self.cont:
            titles = titles[len(titles) // 2:]
        titles = titles[: len(titles) - self.drop]
        pages = [{"title": t, "revisions": [{"slots": {"main": {
            "content": self.pages[t]}}}]} for t in titles]
        return _Resp(_j.dumps({"query": {"pages": pages}}))


def _rows78(path: Path) -> list[dict[str, str]]:
    _, rows = T.read_tsv(path)
    return [r for r in rows if r["opys"] == "78"]


@pytest.mark.parametrize("lame", [
    _Lame(PAGES, body="<html><body>503 Service Unavailable</body></html>"),
    _Lame(PAGES, body='{"error": {"code": "maxlag", "info": "Waiting"}}'),
    _Lame(PAGES, drop=1),
], ids=["503-html", "api-error", "lost-page"])
def test_failure_does_not_erase_the_collected_opys(tmp_path: Path, pack: None,
                                                    lame: _Lame) -> None:
    """🔴 Збій на другому прогоні стирав рядки опису: опис без тексту йшов у
    «не транскрибовано», а злиття викидало його старі рядки як «торкнуті»."""
    target = Target(repo="DAZHO", fond="1", opys=("78",))
    first = _coll(_Api(PAGES)).collect(target, dest=tmp_path)
    before = _rows78(first.out)
    assert before
    with pytest.raises(W.WikisourceError):
        _coll(lame).collect(target, dest=tmp_path)
    assert _rows78(first.out) == before


def test_opys_page_without_table_keeps_the_rows_collected_before(tmp_path: Path,
                                                                 pack: None) -> None:
    """🔴 Таблицю опису перенесли чи переверстали — сторінка без таблиці. Повторне
    збирання стирало рядки опису, а `no_table` поруч казало, що нуль нічого не
    означає."""
    target = Target(repo="DAZHO", fond="1", opys=("78",))
    first = _coll(_Api(PAGES)).collect(target, dest=tmp_path)
    before = _rows78(first.out)
    assert before
    pages = {**PAGES, "Архів:ДАЖО/1/78": "== Справи ==\nтаблицю перенесено на підсторінки\n"}
    res = _coll(_Api(pages)).collect(target, dest=tmp_path)
    assert _rows78(res.out) == before
    assert any(b.kind == "no_table" and "лишено" in b.why for b in res.blind)


def test_continuation_is_followed(tmp_path: Path, pack: None) -> None:
    """Відповідь, що вперлась у ліміт розміру, дочитується за `continue`."""
    api = _Lame(PAGES, cont=True)
    res = _coll(api).collect(Target(repo="DAZHO", fond="1", opys=("78",)), dest=tmp_path)
    assert api.posts == 2
    assert {r["spr_raw"] for r in _rows78(res.out)} >= {"1023", "1150"}


def test_plan_network_failure_is_not_ready(pack: None,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """`HttpError` — RuntimeError, а не OSError: план падав винятком і валив
    увесь `registry build`."""
    from nyshporka.sources.http import HttpError

    def boom(*_a: object, **_k: object) -> list[str]:
        raise HttpError("uk.wikisource.org: ConnectError")

    monkeypatch.setattr(W.WikisourceCollector, "_titles", boom)
    p = _coll(_Api(PAGES)).plan(Target(repo="DAZHO", fond="1"))
    assert not p.ready and "не відповіли" in p.why


def test_plan_api_error_is_not_a_zero(pack: None) -> None:
    class _Err(_Api):
        def get(self, url: str) -> _Resp:
            return _Resp('{"error": {"code": "readonly", "info": "maintenance"}}')

    p = _coll(_Err(PAGES)).plan(Target(repo="DAZHO", fond="1"))
    assert not p.ready and "readonly" in p.why, "збій API — не «опис не транскрибовано»"


def test_absent_opys_is_named_not_a_silent_zero(tmp_path: Path, pack: None) -> None:
    p = _coll(_Api(PAGES)).plan(Target(repo="DAZHO", fond="1", opys=("999",)))
    assert not p.ready and "999" in p.why
    part = Target(repo="DAZHO", fond="1", opys=("78", "999"))
    p = _coll(_Api(PAGES)).plan(part)
    assert p.ready and "999" in p.why
    res = _coll(_Api(PAGES)).collect(part, dest=tmp_path)
    absent = {b.kind: b for b in res.blind}["opys_absent"]
    assert absent.count == 1 and "999" in absent.why


def test_fs_film_only_from_an_address_that_carries_it() -> None:
    """🔴 `cat=` в ark-адресі — номер каталогу, не плівка; картка ставила його
    понад плівкою з таблиці."""
    ark = ("{{Архіви/справа\n| назва = Метрична книга\n| link_FS = https://www."
           "familysearch.org/ark:/61903/3:1:3QS7-L9M3-1234?i=12&cat=1938521\n}}\n")
    card = W.parse_case_page(ark)
    assert card is not None and card["fs_film"] == ""
    assert W._dgs("https://www.familysearch.org/search/film/104123456") == "104123456"
    assert W._dgs("https://www.familysearch.org/ark:/61903/3:1:X?cat=1938521") == ""


def test_template_cell_with_pipes_is_kept_whole() -> None:
    assert W._cell("{{FS|dgs=104123456|item=2}}") == "{{FS|dgs=104123456|item=2}}"
    assert W._cell('style="x" | текст') == "текст"
