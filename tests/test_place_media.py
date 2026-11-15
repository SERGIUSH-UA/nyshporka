"""🗺 Докази про саме місце: вирізка з карти чи рядок довідника поселень.

Досі їх можна було лише згадати шляхом у нотатках картки, і тоді база роду
й сайт про них не знали. Тепер картка місця має `media`, як і картка особи.
ID вигадані (`PL9…`).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nyshporka.core import workspace as W
from nyshporka.models import MediaRef, Place, Source
from nyshporka.storage.files import read_place, write_entity

SHA = "f" * 64
CROP = "data/source/citations/maps/atlas1809_pl9001.jpg"


def _place() -> Place:
    return Place(
        id="PL9001", name="Село", admin=["Україна"], coords=(48.5, 28.5),
        media=[MediaRef(path=CROP, sha256=SHA, type="document",
                        caption="Атлас 1809, повітова карта — «Село» зі знаком церкви")],
        notes=f"Доказ: `{CROP}`",
    )


@pytest.fixture
def space(tmp_path: Path):
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    crop = tmp_path / CROP
    crop.parent.mkdir(parents=True)
    crop.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xD9]))
    canon = tmp_path / "data" / "canonical"
    for kind, e in (("places", _place()),
                    ("sources", Source(id="S_TEST_MAP", type="archive", title="Атлас"))):
        (canon / kind).mkdir(parents=True, exist_ok=True)
        write_entity(canon / kind / f"{e.id}.md", e)
    yield tmp_path
    W.reset()


def test_place_card_keeps_media(space: Path) -> None:
    got = read_place(space / "data" / "canonical" / "places" / "PL9001.md")
    assert [(m.path, m.sha256, m.type) for m in got.media] == [(CROP, SHA, "document")]


def test_old_place_card_without_media_still_reads() -> None:
    assert Place(id="PL9002", name="Хутір").media == []


def test_reindex_writes_place_media(space: Path) -> None:
    from nyshporka.storage.reindex import reindex

    rep = reindex(space)
    con = sqlite3.connect(rep.sqlite_path)
    try:
        rows = con.execute("SELECT place_id, path, sha256, type FROM place_media").fetchall()
    finally:
        con.close()
    assert rows == [("PL9001", CROP, SHA, "document")]


def test_stats_count_place_media(space: Path) -> None:
    from nyshporka.storage import canon_stats
    from nyshporka.storage.reindex import reindex

    reindex(space)
    assert canon_stats.summary()["place_media"] == 1


def test_stats_survive_base_without_place_media(space: Path) -> None:
    """База, зібрана старшою Нишпоркою, таблиці не має — це нуль, а не падіння."""
    from nyshporka.storage import canon_stats
    from nyshporka.storage.reindex import reindex

    rep = reindex(space)
    con = sqlite3.connect(rep.sqlite_path)
    con.execute("DROP TABLE place_media")
    con.commit()
    con.close()
    assert canon_stats.summary()["place_media"] == 0


def test_place_page_shows_its_media(space: Path) -> None:
    from nyshporka.site import build as B

    rep = B.build(space, public=False, html=False)
    page = (rep.out / "docs" / "places" / "PL9001.md").read_text(encoding="utf-8")
    assert "Атлас 1809, повітова карта" in page
    assert "документ у сторі доказів" in page
    assert "локальне фото" not in page
