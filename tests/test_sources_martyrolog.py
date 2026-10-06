"""🕯 «Український мартиролог ХХ ст.»: розбір видачі й картки, знаменник, відмови.

Мережі тут немає: сторінки зняті з живої бази 06.10.2026 і урізані до трьох
осіб у групі архіву (`tests/fixtures/sources/martyrolog_*.html`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.martyrolog import (
    MartyrologSource,
    denied,
    parse_card,
    parse_coverage,
    parse_results,
    split_query,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "sources"


def _page(name: str) -> str:
    return (FIX / f"martyrolog_{name}.html").read_text(encoding="utf-8")


#: Відсіч Akamai дослівно, як її віддав сайт на `curl` 06.10.2026.
DENIED = """<HTML><HEAD>
<TITLE>Access Denied</TITLE>
</HEAD><BODY>
<H1>Access Denied</H1>
You don't have permission to access "http&#58;&#47;&#47;archives&#46;gov&#46;ua&#47;um&#46;php" on this server.<P>
Reference&#32;&#35;18&#46;9ce2e17&#46;1791300244&#46;7ba85e99
<P>https&#58;&#47;&#47;errors&#46;edgesuite&#46;net&#47;18&#46;9ce2e17</P>
</BODY>
</HTML>"""


class _R:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=httpx.Request("GET", "x"),
                response=httpx.Response(self.status_code))


class _Site:
    """Двійник бази: відповідає за параметрами адреси."""

    def __init__(self, *, status: int = 200, body: str | None = None) -> None:
        self.seen: list[str] = []
        self.status = status
        self.body = body

    def get(self, url: str) -> _R:
        self.seen.append(url)
        if self.body is not None:
            return _R(self.body, self.status)
        if "id=93267" in url:
            return _R(_page("card_93267"))
        if "id=" in url:
            return _R(_page("card_113944"))
        if "p=3" in url:
            return _R(_page("list_p3"))
        if "p=2" in url:
            # Друга сторінка в фікстурах не знята — та сама розмітка, що й третя.
            return _R(_page("list_p3"))
        if "ln=" in url and "%D0%96%D0%BC%D1%83%D1%80" in url:   # «Жмур…» — вигадане прізвище
            return _R(_page("zero"))
        return _R(_page("list_p1"))


def _src(site: _Site) -> MartyrologSource:
    return MartyrologSource(client=site)


# ── розбір ───────────────────────────────────────────────────────────────────

def test_results_carry_total_pages_archive_and_birth_year() -> None:
    r = parse_results(_page("list_p1"))
    assert r.total == 139 and r.pages == 3
    assert r.by_archive["ЦДАГОУ"] == 29 and r.by_archive["ДА Волинської області"] == 30
    first = r.rows[0]
    # Підсвітка збігу посеред подвійного прізвища не розриває слово.
    assert first.name == "Кузьмук (Кузьмюк-Шевчук) Степан Антонович"
    assert (first.id, first.born, first.archive) == ("115638", "1904", "ЦДАГОУ")
    # Особа отримує архів групи, під якою стоїть, а не першої на сторінці.
    assert any(x.archive == "ДА Волинської області" for x in r.rows)


def test_unknown_birth_year_is_blank_not_question_marks() -> None:
    rows = parse_results(_page("list_p1")).rows + parse_results(_page("list_p3")).rows
    assert all("?" not in x.born for x in rows)


def test_zero_page_is_an_honest_zero() -> None:
    r = parse_results(_page("zero"))
    assert r.total == 0 and r.rows == []


def test_unknown_markup_is_not_a_zero() -> None:
    """🔴 Сторінка без лічильника й без «не дав результатів» — не нуль."""
    with pytest.raises(SourceError, match="розмітка"):
        parse_results("<html><body>щось інше</body></html>")


def test_card_gives_case_shifra_and_fields() -> None:
    c = parse_card(_page("card_93267"), "93267")
    assert c.name == "Шевчук Ян Віцентович" and c.archive == "ЦДАГОУ"
    assert c.shifra == "ф. 263, оп. 1, спр. 53440"
    assert c.get("Місце проживання на момент арешту") == "м. Варшава"
    assert c.get("Дата арешту") == "13.02.1922"
    # «_невідомо» і порожня реабілітація — порожнеча бази, а не значення.
    assert c.get("Стаття звинувачення") == ""
    assert c.get("Відомості щодо реабілітації") == ""
    assert c.added == "05.08.2022"


def test_card_with_letter_prefixed_fond() -> None:
    c = parse_card(_page("card_113944"), "113944")
    assert c.shifra == "ф. Р-7641, оп. 5, спр. 709"
    assert c.get("Вирок") == "8 р. ВТТ" and c.archive == "ДА Сумської області"


def test_sidebar_counts_add_up_to_the_announced_total() -> None:
    """Лічильники по архівах — знаменник нуля; 02.10.2026 ДАС оголосила 170 468."""
    cov = parse_coverage(_page("card_93267"))
    assert len(cov) == 27 and sum(cov.values()) == 170468
    assert cov["ДА Вінницької області"] == 373


def test_query_splits_surname_name_patronymic() -> None:
    assert split_query("Шевчук Ян Віцентович") == ("Шевчук", "Ян", "Віцентович")
    assert split_query("Кузьмюк-Шевчук") == ("Кузьмюк-Шевчук", "", "")
    assert split_query("  ") == ("", "", "")


# ── пошук ────────────────────────────────────────────────────────────────────

def test_search_opens_each_card_and_says_it_is_truncated() -> None:
    site = _Site()
    hits = _src(site).search("Шевчук", limit=4)
    assert len(hits) == 4
    h = hits[0]
    assert h.source == "martyrolog" and h.ref == "person:115638"
    assert h.url.endswith("um.php?id=115638")
    # Двійник на цю адресу віддає картку 113944 — шифра береться з картки.
    assert h.shifra == "ДА Сумської області ф. Р-7641, оп. 5, спр. 709"
    assert h.fond == "Р-7641" and h.years == "1895–?"
    # Знаменник: показано 4 з 139, і по яких архівах решта.
    cut = getattr(hits, "truncated", "")
    assert "4 з 139" in cut and "ЦДАГОУ 29" in cut
    # 1 сторінка видачі + 4 картки; зайвих сторінок не гортали.
    assert sum("id=" in u for u in site.seen) == 4
    assert not any("p=2" in u for u in site.seen)


def test_search_pages_through_when_limit_exceeds_first_page() -> None:
    site = _Site()
    hits = _src(site).search("Шевчук", limit=12)
    assert len(hits) == 12
    assert any("p=2" in u for u in site.seen)


def test_search_zero_returns_empty() -> None:
    assert list(_src(_Site()).search("Жмуренко")) == []


def test_empty_query_asks_nothing() -> None:
    site = _Site()
    assert _src(site).search("  ") == []
    assert site.seen == []


def test_coverage_and_catalog_source_after_a_request() -> None:
    src = _src(_Site())
    src.search("Шевчук", limit=1)
    assert src.coverage()["ЦДАГОУ"] == 28181
    kind, meta = src.catalog_source()
    assert kind == "live" and meta["rows"] == 170468


def test_akamai_denial_is_a_refusal_not_a_zero() -> None:
    with pytest.raises(SourceError, match="Akamai"):
        _src(_Site(status=403, body=DENIED)).search("Шевчук")
    # Та сама сторінка зі статусом 200 (проксі, кеш) — теж відмова.
    with pytest.raises(SourceError, match="Akamai"):
        _src(_Site(status=200, body=DENIED)).search("Шевчук")
    assert denied(DENIED)


def test_without_curl_cffi_it_names_the_real_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Системний curl тут гарантовано 403 — відмова мусить назвати `cfshield`."""
    import nyshporka.sources.cfclient as C
    import nyshporka.sources.martyrolog as M

    monkeypatch.setattr(C, "have_curl_cffi", lambda: False)
    monkeypatch.setattr(M, "offline", lambda: False)
    with pytest.raises(SourceError, match="cfshield"):
        MartyrologSource().search("Шевчук")


def test_offline_refuses_instead_of_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NYSHPORKA_NO_NETWORK", "1")
    with pytest.raises(SourceError, match="мережу вимкнено"):
        MartyrologSource().search("Шевчук")


# ── реєстр і загальний пошук ─────────────────────────────────────────────────

def test_martyrolog_is_in_the_registry() -> None:
    from nyshporka.sources.registry import _builtin

    src = next(s for s in _builtin(None) if s.id == "martyrolog")
    assert getattr(src, "explicit_only", False)


def test_general_find_does_not_ask_the_person_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Назва села як прізвище ловила б чужих людей — база лише явно."""
    import nyshporka.ops_builtin as ob
    from nyshporka.ops_builtin import CatalogSearchArgs, catalog_search

    asked: list[str] = []

    class _Spy(MartyrologSource):
        def search(self, q: str, *, limit: int = 30) -> list:  # type: ignore[override]
            asked.append(q)
            return []

    class _Reg:
        def __init__(self) -> None:
            self.s = _Spy(client=_Site())

        def with_cap(self, cap: str) -> list:
            return [self.s]

        def get(self, sid: str) -> object:
            return self.s if sid == "martyrolog" else None

    monkeypatch.setattr(ob, "_registry", lambda: _Reg())
    env = catalog_search(CatalogSearchArgs(q="Липовеньке", by_address=False))
    assert asked == []
    cov = env.data["coverage"]
    assert cov["not_asked"][0]["source"] == "martyrolog"
    assert all(z["source"] != "martyrolog" for z in cov["zeros"])

    env = catalog_search(CatalogSearchArgs(q="Шевчук", source="martyrolog",
                                           by_address=False))
    assert asked == ["Шевчук"]
    assert env.data["coverage"]["searched"] == ["martyrolog"]


def test_rows_markup_change_is_not_a_zero() -> None:
    """🔴 Сайт назвав «знайдено 139», а рядків не розібрано — це змінена
    розмітка рядків, а не «такої особи в базі немає»."""
    body = _page("list_p1").replace('class="rn"', 'class="birth"')
    with pytest.raises(SourceError):
        parse_results(body)


def test_coverage_by_archive_reaches_the_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покриття бази по архівах — знаменник «немає»; доти його не бачив ні
    агент, ні термінал."""
    from nyshporka import ops_builtin as OB

    src = _src(_Site())

    class _Reg:
        def get(self, sid: str) -> object:
            return src if sid == "martyrolog" else None

        def with_cap(self, _cap: str) -> list[object]:
            return [src]

        def all(self) -> list[object]:
            return [src]

    monkeypatch.setattr(OB, "_registry", lambda: _Reg())
    env = OB.catalog_search(OB.CatalogSearchArgs(q="Шевчук", source="martyrolog", limit=2))
    (basis,) = env.data["coverage"]["basis"]
    per = basis["by_archive"]
    assert len(per) == 27 and sum(per.values()) == 170468
    said = " ".join(w.text for w in env.warnings)
    assert "фонд цілком" not in said, "порада про фонд — не для бази осіб"


def test_empty_query_returns_hits() -> None:
    from nyshporka.sources.base import Hits

    assert isinstance(_src(_Site()).search("  "), Hits)
