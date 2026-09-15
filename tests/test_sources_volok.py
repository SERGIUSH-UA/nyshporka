"""📷 Фотоархів О. Волока: розбір списку, пошук по зрізу, новий список у простір.

Мережі тут немає, бо її немає й у джерела: воно шукає по списку назв.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from nyshporka.sources.base import SourceError
from nyshporka.sources.volok import (
    SNAPSHOT_NAME,
    VolokSource,
    album_of,
    parse_list,
    write_snapshot,
)

# Рядки у формі живого списку від 12.09.2026: посилання, назва, `<br>`.
LIST_HTML = """\
<a href="https://flickr.com/photos/alexander_volok/albums/72177720322819149">АРХІВ - РГИА 0592-032 Крестьянский Поземельный Банк - Таврическая губерния, Мелитопольский уезд</a><br>
<a href="https://flickr.com/photos/alexander_volok/albums/72177720319126030">АРХІВ - РГИА 1293-167-0034 Таврическая губерния. Проект перестройки еврейской синагоги в гор. Мелитополе (1890)</a><br>
<a href="https://flickr.com/photos/alexander_volok/albums/72177720324353233">КНИГА - Список дворян, внесенных в родословную книгу Подольской губернии (1913)</a><br>
<a href="https://flickr.com/photos/alexander_volok/albums/72177720334884507">АРХІВ - ГАКО (Курськ) РАЦС р2795-4-1673</a><br>
<a href="https://flickr.com/photos/alexander_volok/albums/1">АРХІВ - ДАДО (ДАДнО) Р-6508-014пош-0036 Шлюб 1945</a><br>
<a href="https://flickr.com/photos/alexander_volok/albums/1">АРХІВ - дубль того самого альбому</a><br>
<a href="https://example.org/not-an-album">не альбом</a><br>
"""


def _src(tmp_path: Path, html: str = LIST_HTML) -> VolokSource:
    albums, skipped = parse_list(html)
    bundled = tmp_path / "bundled"
    write_snapshot(albums, bundled, taken="2026-09-12", origin="List20260912.zip",
                   sha256="0" * 64, skipped=skipped)
    return VolokSource(tmp_path / "ws", bundled_dir=bundled)


def test_the_list_is_read_link_by_link_and_foreign_links_are_counted() -> None:
    albums, skipped = parse_list(LIST_HTML)
    assert [a.album for a in albums][:2] == ["72177720322819149", "72177720319126030"]
    assert len(albums) == 5          # дубль альбому не рахується двічі
    assert skipped == 1


def test_archive_shifra_and_years_come_out_of_the_title() -> None:
    a = album_of("1", "АРХІВ - РГИА 1293-167-0034 Проект синагоги в гор. Мелитополе (1890)")
    assert (a.kind, a.archive, a.shifra, a.years) == ("АРХІВ", "РГИА", "1293-167-0034", "1890")
    assert a.title.startswith("РГИА 1293-167-0034")


def test_an_opys_with_a_suffix_is_still_a_shifra() -> None:
    a = album_of("1", "АРХІВ - ДАДО (ДАДнО) Р-6508-014пош-0036 Шлюб 1945")
    assert (a.archive, a.shifra, a.years) == ("ДАДО (ДАДнО)", "Р-6508-014пош-0036", "1945")


def test_a_fond_prefix_with_a_space_does_not_stick_to_the_archive() -> None:
    a = album_of("1", "АРХІВ - ГА РФ Р 6978-001-0470 Протоколы заседаний (1917)")
    assert (a.archive, a.shifra) == ("ГА РФ", "Р 6978-001-0470")


def test_without_a_shifra_no_archive_is_invented() -> None:
    a = album_of("1", "АРХІВ - РГИА 0592-032 Крестьянский Поземельный Банк - Мелитопольский уезд")
    assert (a.archive, a.shifra) == ("", "")


def test_a_ukrainian_query_finds_a_russian_title(tmp_path: Path) -> None:
    hits = _src(tmp_path).search("Мелітопольський")
    assert [h.ref for h in hits] == ["album:72177720322819149"]
    assert hits[0].url.endswith("/albums/72177720322819149")
    assert hits[0].acquirable is False
    assert "список від 2026-09-12" in hits[0].note


def test_every_word_of_the_query_must_be_in_the_title(tmp_path: Path) -> None:
    src = _src(tmp_path)
    assert len(src.search("Мелитопол")) == 2
    assert [h.shifra for h in src.search("Мелитопол синагоги")] == ["1293-167-0034"]


def test_a_truncated_answer_names_how_many_there_were(tmp_path: Path) -> None:
    hits = _src(tmp_path).search("Мелитопол", limit=1)
    assert len(hits) == 1
    assert "з 2 за запитом" in hits[0].note


def test_without_any_list_the_search_refuses_instead_of_answering_zero(tmp_path: Path) -> None:
    src = VolokSource(tmp_path / "ws", bundled_dir=tmp_path / "empty")
    assert src.catalog_source()[0] == "none"
    with pytest.raises(SourceError, match="crawl volok --from"):
        src.search("Мелітополь")


def test_a_newer_list_in_the_workspace_wins_over_the_bundled_one(tmp_path: Path) -> None:
    src = _src(tmp_path)
    assert src.catalog_source()[0] == "bundled"
    newer = tmp_path / "List20261001.zip"
    with zipfile.ZipFile(newer, "w") as zf:
        zf.writestr("List20261001.htm",
                    '<a href="https://flickr.com/photos/alexander_volok/albums/9">'
                    "КНИГА - Мелитопольский уезд (1900)</a><br>")
    meta = src.import_list(newer)
    assert (meta["taken"], meta["rows"]) == ("2026-10-01", 1)
    kind, info = src.catalog_source()
    assert (kind, info["taken"]) == ("workspace", "2026-10-01")
    assert (tmp_path / "ws" / VolokSource.LIST_REL / SNAPSHOT_NAME).is_file()
    assert [h.ref for h in src.search("Мелитопол")] == ["album:9"]


def test_a_list_without_a_date_in_its_name_is_refused(tmp_path: Path) -> None:
    f = tmp_path / "list.htm"
    f.write_text(LIST_HTML, encoding="utf-8")
    with pytest.raises(SourceError, match="дати"):
        _src(tmp_path).import_list(f)


def test_a_file_without_album_links_is_refused(tmp_path: Path) -> None:
    f = tmp_path / "List20261001.htm"
    f.write_text("<a href='https://example.org'>x</a>", encoding="utf-8")
    with pytest.raises(SourceError, match="жодного посилання"):
        _src(tmp_path).import_list(f)


def test_volok_is_in_the_registry_with_its_bundled_list() -> None:
    from nyshporka.sources.registry import load

    src = load().get("volok")
    assert src is not None
    kind, info = src.catalog_source()   # type: ignore[attr-defined]
    assert kind == "bundled" and info["rows"] and info["taken"]
