"""🏚 Інвентаріум: ключ зі скриптів сайту, обхід із приймачем повноти, пошук і шифра.

Мережі тут немає: сайт і база підставлені двійником. Рядки — з живої бази
(знімок 28.09.2026), без полів волонтера.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.http import Fetcher
from nyshporka.sources.inventarium import (
    InventariumSource,
    find_credentials,
    split_signature,
)


def _jwt(role: str, ref: str) -> str:
    def seg(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'HS256'})}.{seg({'role': role, 'ref': ref})}.sig_{'x' * 12}"


REF = "abcdefghijklmnop"
ANON = _jwt("anon", REF)


def _rec(id_: str, village: str, sig: str, page: str, year: int, **kw: Any) -> dict[str, Any]:
    return {"id": id_, "approved": kw.get("approved", True),
            "old_settlement_name": village, "current_settlement_name": village,
            "current_district": kw.get("district", ""), "current_region": "",
            "case_signature": sig, "additional_case_signature": kw.get("extra"),
            "case_date": kw.get("case_date", str(year)), "inventory_year": year,
            "pages_count": kw.get("pages", ""), "inventory_start_page": page or None,
            "case_title": kw.get("title", ""), "inventory_type": "Інвентар",
            "scans_url": kw.get("scans", ""),
            # Поле, якого обхід не просить; двійник його віддає, щоб перевірити,
            # що навіть присланим воно в знімок не лягає.
            # Адреса складається з частин: цілою її ловить сканер приватного.
            "email": "volunteer" + "@" + "example.org"}


RECORDS = [
    _rec("7326d090", "Яроповичі", "ЦДІАК 2-1-171", "295", 1794, pages="597",
         district="Бердичівський район",
         scans="https://www.familysearch.org/ark:/61903/3:1:3QS7-L9"),
    _rec("da4dfc29", "Яроповичі", "ЦДІАК 2-1-179", "347", 1795, pages="779"),
    _rec("e0c11f47", "Скочище", "ЦДІАК 2-1-171", "14", 1794, pages="597"),
    _rec("1c310d0f", "Криве", "ЛННБ ім. Стефаника 5-1-4145/III", "134", 1763,
         case_date="XVIII ст."),
    _rec("9411c747", "Струцівка", "ЛННБ ім. Стефаника 5-1-4145/III", "31", 1774,
         case_date="XVIII ст."),
    _rec("000f5cc1", "Пустовіти", "AGAD ASK 1/7/0/9/4", "314", 1789),
    _rec("005816c3", "Голишів", "AGAD ASK-XLVI 1/7/0/9/20", "43", 1789,
         extra=["ЦДІАК-2227-1-158"]),
    _rec("30a9b011", "Косів", "", "", 1778, approved=False),
]


class _Resp:
    def __init__(self, text: str, headers: dict[str, str] | None = None) -> None:
        self.text = text
        self.headers = headers or {}
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class _Site:
    """Головна сторінка з посиланнями на скрипти; ключ — у другому скрипті."""

    def __init__(self, scripts: dict[str, str]) -> None:
        self.scripts = scripts

    def get(self, url: str) -> _Resp:
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        if path in ("", "/"):
            refs = "".join(f'<script src="/{p}"></script>' for p in self.scripts)
            return _Resp(f"<html>{refs}</html>")
        return _Resp(self.scripts[path])


class _Api:
    """PostgREST: сторінки по `limit`/`offset`, загальне число — у Content-Range."""

    def __init__(self, records: list[dict[str, Any]], *, claim: int | None = None) -> None:
        self.records = records
        self.claim = len(records) if claim is None else claim
        self.asked: list[str] = []

    def get(self, url: str) -> _Resp:
        from urllib.parse import parse_qs, urlparse

        self.asked.append(url)
        q = parse_qs(urlparse(url).query)
        lim, off = int(q["limit"][0]), int(q["offset"][0])
        page = self.records[off:off + lim]
        end = off + len(page) - 1
        return _Resp(json.dumps(page, ensure_ascii=False),
                     {"content-range": f"{off}-{end}/{self.claim}"})


GOOD_JS = f'let K=u("https://{REF}.supabase.co","{ANON}");'


def _src(tmp_path: Path, api: _Api | None = None, js: str = GOOD_JS) -> InventariumSource:
    site = _Site({"_next/static/chunks/a.js": "console.log(1)",
                  "_next/static/chunks/b.js": js})
    return InventariumSource(
        tmp_path,
        site=Fetcher(base="https://inv", delay=0.0, client=site),
        api=Fetcher(base="https://api", delay=0.0, client=api or _Api(RECORDS)))


@pytest.fixture
def crawled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InventariumSource:
    monkeypatch.setattr("nyshporka.sources.inventarium.PAGE", 3)
    src = _src(tmp_path)
    src.crawl()
    return src


def test_the_key_is_taken_only_if_it_is_anon_of_the_same_project() -> None:
    """Сервісний ключ або ключ чужого проєкту — не читання публічних даних."""
    service = _jwt("service_role", REF)
    foreign = _jwt("anon", "zzzzzzzzzzzzzzzz")
    text = f'"https://{REF}.supabase.co" "{service}" "{foreign}" "{ANON}"'
    assert find_credentials([text]) == (f"https://{REF}.supabase.co", ANON)
    assert find_credentials([f'"https://{REF}.supabase.co" "{service}"']) is None


def test_no_key_in_scripts_is_said_aloud(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="Supabase"):
        _src(tmp_path, js="console.log(2)").crawl()


def test_crawl_pages_through_the_whole_base(crawled: InventariumSource) -> None:
    kind, info = crawled.catalog_source()
    assert kind == "workspace" and info["rows"] == len(RECORDS)


def test_volunteer_email_never_reaches_the_snapshot(crawled: InventariumSource) -> None:
    assert crawled.snap_path is not None
    text = crawled.snap_path.read_text(encoding="utf-8")
    assert "@" not in text and "email" not in text


def test_a_short_crawl_writes_nothing(tmp_path: Path) -> None:
    """Сервер обіцяє більше, ніж віддав: неповна база виглядала б як повна."""
    src = _src(tmp_path, api=_Api(RECORDS, claim=len(RECORDS) + 5))
    with pytest.raises(SourceError, match="знімок не записано"):
        src.crawl()
    assert src.catalog_source()[0] == "none"


def test_without_snapshot_search_refuses_instead_of_zero(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="nysh crawl inventarium"):
        InventariumSource(tmp_path).search("Яроповичі")


def test_village_gives_case_and_page(crawled: InventariumSource) -> None:
    hits = crawled.search("Яроповичі")
    assert [(h.shifra, h.page) for h in hits] == [("ЦДІАК 2-1-171", 295),
                                                  ("ЦДІАК 2-1-179", 347)]
    first = hits[0]
    assert first.repo == "CDIAK" and first.fond == "2"
    assert first.url.startswith("https://www.familysearch.org/")
    assert "597" in first.note and not first.acquirable


def test_russian_spelling_finds_the_ukrainian_row(crawled: InventariumSource) -> None:
    """Назва з довідника XIX ст. («Яроповичи») мусить знаходити рядок «Яроповичі»."""
    assert [h.shifra for h in crawled.search("Яроповичи")] == \
        ["ЦДІАК 2-1-171", "ЦДІАК 2-1-179"]


def test_case_lists_its_villages_by_page(crawled: InventariumSource) -> None:
    """Для чого джерело: які села лежать у книзі й з якого аркуша."""
    hits = crawled.find_case("2", "1", "171")
    assert [(h.place.split(" · ")[0], h.page) for h in hits] == [("Скочище", 14),
                                                                 ("Яроповичі", 295)]
    assert crawled.find_case("2", "1", "171", repo="DAZHO") == []


def test_volume_suffix_must_match(crawled: InventariumSource) -> None:
    assert len(crawled.find_case("5", "1", "4145/III")) == 2
    assert crawled.find_case("5", "1", "4145/II") == []


def test_additional_signature_is_an_address_too(crawled: InventariumSource) -> None:
    hits = crawled.find_case("2227", "1", "158")
    assert [h.place.split(" · ")[0] for h in hits] == ["Голишів"]
    assert hits[0].shifra == "AGAD ASK-XLVI 1/7/0/9/20"


def test_unapproved_row_says_so(crawled: InventariumSource) -> None:
    (hit,) = crawled.search("Косів")
    assert "не затверджено" in hit.note and hit.page is None


@pytest.mark.parametrize(("sig", "want"), [
    ("ЦДІАК 2-1-171", ("ЦДІАК", "2", "1", "171")),
    ("ЛННБ ім. Стефаника 5-1-4145/III", ("ЛННБ ім. Стефаника", "5", "1", "4145/III")),
    ("ЦДІАК-2227-1-158", ("ЦДІАК", "2227", "1", "158")),
    ("AGAD ASK 1/7/0/9/4", ("", "", "", "")),
    ("AGAD ASK-XLVI 1/7/0/9/20", ("", "", "", "")),
    ("HU MNL OL, C 59 - IV. sorozat Com. Bereg", ("", "", "", "")),
])
def test_foreign_signatures_are_not_guessed_into_fonds(sig: str, want: tuple[str, ...]) -> None:
    assert split_signature(sig) == want
