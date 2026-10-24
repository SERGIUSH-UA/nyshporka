"""🏛 ARCHIUM: адреса переглядача замість `file:<id>` і вибір джерела за хостом.

Людина копіює з браузера `https://<хост>/file-viewer/<id>`; знати внутрішній
`file:<id>` і id джерела вона не мусить. Мережі тут немає: відповіді записані.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.sources import archium as A
from nyshporka.sources import load
from nyshporka.sources.base import SourceError
from nyshporka.sources.http import Fetcher



class _Resp:
    status_code = 200

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _Recorded:
    """Клієнт із записаними відповідями (за підрядком адреси). Мережі нема."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str) -> _Resp:
        self.asked.append(url)
        for key, body in self.pages.items():
            if key in url:
                return _Resp(body)
        raise AssertionError(f"тест не готував відповіді на {url}")


FIX = Path(__file__).resolve().parent / "fixtures" / "sources"


@pytest.fixture(scope="module")
def viewer_html() -> str:
    return (FIX / "archium_viewer.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("url", [
    "https://archium.tsdial.archives.gov.ua/file-viewer/143179",
    "https://archium.tsdial.archives.gov.ua/file-viewer/143179/",
    "https://ARCHIUM.tsdial.archives.gov.ua/file-viewer/143179/?page=3#x",
])
def test_viewer_url_is_parsed_with_trailing_slash_and_query(url: str) -> None:
    assert A.parse_viewer_url(url) == ("https", "archium.tsdial.archives.gov.ua", "143179")


@pytest.mark.parametrize("ref", ["file:5301", "https://x.ua/fonds/", "inv:1", ""])
def test_not_a_viewer_url(ref: str) -> None:
    assert A.parse_viewer_url(ref) is None


def test_manifest_accepts_url_and_keeps_file_ref(tmp_path: Path, viewer_html: str) -> None:
    src = A.ArchiumSource(workspace=tmp_path, fetcher=Fetcher(
        base=A.BASE, delay=0.0, client=_Recorded({"file-viewer/5301": viewer_html})))
    man = src.manifest(f"{A.BASE}/file-viewer/5301/?x=1")
    assert man.frames == 47
    # Паспорт несе стабільний `file:<id>`, а не те, як адресу написали.
    assert man.ref == "file:5301"


def test_source_refuses_url_of_another_host(tmp_path: Path) -> None:
    """id справ на різних майданчиках збігаються: чужий хост не качаємо мовчки."""
    src = A.ArchiumSource(workspace=tmp_path)
    with pytest.raises(SourceError, match="tsdial"):
        src.manifest("https://archium.tsdial.archives.gov.ua/file-viewer/143179")


@pytest.mark.parametrize("source_id", ["archium", "archium-cdiak", "archium-cdial"])
def test_known_host_picks_its_own_source(tmp_path: Path, source_id: str) -> None:
    reg = load(tmp_path)
    got = A.route_viewer_url(
        reg, source_id, "https://archium.tsdial.archives.gov.ua/file-viewer/143179/")
    assert got is not None
    src, ref, note = got
    assert src.id == "archium-cdial" and ref == "file:143179" and note == ""
    # ДАХмО лишається під історичним id.
    dahmo = A.route_viewer_url(reg, "archium-cdial",
                               "https://archium.dahmo.gov.ua/file-viewer/5301")
    assert dahmo is not None and dahmo[0].id == "archium"


def test_other_sources_and_plain_refs_are_not_touched(tmp_path: Path) -> None:
    reg = load(tmp_path)
    assert A.route_viewer_url(reg, "commons", "https://archium.dahmo.gov.ua/file-viewer/1") is None
    assert A.route_viewer_url(reg, "archium", "file:5301") is None


def test_unknown_archium_host_is_probed_and_used_adhoc(tmp_path: Path, viewer_html: str) -> None:
    rec = _Recorded({"file-viewer/77": viewer_html})
    got = A.route_viewer_url(
        load(tmp_path), "archium", "https://archium.newarch.gov.ua/file-viewer/77",
        fetcher=Fetcher(base="https://archium.newarch.gov.ua", delay=0.0, client=rec))
    assert got is not None
    src, ref, note = got
    assert src.id == "archium-newarch-gov-ua" and ref == "file:77"
    assert src.base == "https://archium.newarch.gov.ua"
    assert "archives.yaml" in note and "archium.newarch.gov.ua" in note
    assert len(rec.asked) == 1, "проба — один GET"
    # Власні id не збігаються з жодним відомим: знаменник «де шукали» чесний.
    assert src.id not in {s.id for s in load(tmp_path).all()}


def test_unknown_host_that_is_not_archium_gives_clear_error(tmp_path: Path) -> None:
    rec = _Recorded({"file-viewer": "<html><body>Hello</body></html>"})
    with pytest.raises(SourceError, match="не схожий на ARCHIUM"):
        A.route_viewer_url(
            load(tmp_path), "archium", "https://example.org/file-viewer/9",
            fetcher=Fetcher(base="https://example.org", delay=0.0, client=rec))
