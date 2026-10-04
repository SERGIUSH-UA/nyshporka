"""📚 Сканотека ПТГ: зйомка в пулі й скан кожної сторінки.

Відгук стороннього користувача (жовтень 2026): справи ЦДІАК ф.2 зі Сканотеки
`share publish` пакував без джерела сканів — «в каталозі пулу скани не
покажуться». Паспорт таких справ несе адресу одиниці вкладеним блоком
`source`, якого пакувальник не читав.

Кадр Сканотеки — розворот; завантажувач ріже його на `185_L.jpg`/`185_R.jpg`
і пише карту в `_split.json`. Людина, яка звіряє знахідку, знає лише номер
скана в джерелі, тож сторінка мусить уміти назвати свій скан.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _cherha import drop_space, make_space, write_run

from nyshporka.core import skanoteka as SK

UNIT = "https://sadowe.genealodzy.pl/id1703-sy160-se"
SCAN_185 = ("https://sadowe.genealodzy.pl/index.php?op=pg&id=1703&se=&sy=160&kt=&plik=185.jpg")


def _json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _passport() -> dict:
    """Так паспорт пише завантажувач Сканотеки (ЦДІАК 2-1-160)."""
    return {"shifra": "ЦДІАК 2-1-160", "source": {
        "name": "Skanoteka ПТГ", "url": UNIT, "fond_page": "https://sadowe.genealodzy.pl/id1703",
        "unit": 160, "fond_id": 1703, "frames_source": 878}}


def _map() -> dict:
    return {"source": "sadowe.genealodzy.pl", "fond_id": 1703, "unit": 160, "split": True,
            "frames": {
                "001": {"src": "001.jpg", "pages": {"001.jpg": {"side": "-"}}},
                "185": {"src": "185.jpg", "pages": {"185_L.jpg": {"side": "L"},
                                                    "185_R.jpg": {"side": "R"}}}}}


def _case(root: Path, *, with_map: bool = True, frames: bool = True) -> Path:
    d = root / "data" / "raw" / "cdiak_2" / "spr-160"
    _json(d / "_source.json", _passport())
    if with_map:
        _json(d / "_split.json", _map())
    if frames:
        for name in ("001.jpg", "185_L.jpg", "185_R.jpg"):
            (d / name).write_bytes(b"jpg")
    return d


# ── адреси ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    UNIT,
    "https://sadowe.genealodzy.pl/id1703-sy160-se?x=1",
    "sadowe.genealodzy.pl/id1703-sy160-se",
    SCAN_185,
    "https://sadowe.genealodzy.pl/index.php?op=pg&id=1703&sy=160&plik=185.jpg",
])
def test_unit_from_both_address_forms(url: str) -> None:
    got = SK.from_url(url)
    assert got == SK.Unit("sadowe", "1703", "160")
    assert got.ref == "unit:sadowe/1703/160" and got.url == UNIT
    assert got.scan_url("185") == SCAN_185


@pytest.mark.parametrize("url", [
    "https://sadowe.genealodzy.pl/id1703",                       # сторінка фонду, не зйомка
    "https://metryki.genealodzy.pl/metryka.php?ar=1&zs=0159d&sy=1870&kt=2&skan=006.jpg",
    "https://evil.example/id1703-sy160-se",
    "https://sadowe.genealodzy.pl.evil.example/id1703-sy160-se",
    "",
])
def test_not_a_unit(url: str) -> None:
    assert SK.from_url(url) is None


def test_every_base_of_the_engine_is_known() -> None:
    for host in ("skanoteka", "sadowe", "notariaty", "meldunkowe"):
        assert SK.from_url(f"https://{host}.genealodzy.pl/id12-sy3-se") == SK.Unit(host, "12", "3")


def test_ref_round_trip_and_passport() -> None:
    u = SK.Unit("sadowe", "1703", "160")
    assert SK.from_ref(u.ref) == u and SK.from_ref("skanoteka:" + u.ref) == u
    assert SK.from_ref("unit:evil/1703/160") is None
    assert SK.unit_of(_passport()) == u
    assert SK.unit_of({"source": "wikimedia_commons"}) is None      # `source` буває рядком
    assert SK.unit_of({"source_url": UNIT}) == u


# ── карта сторінок ───────────────────────────────────────────────────────────
def test_map_is_read_only_when_it_is_a_skanoteka_map(tmp_path: Path) -> None:
    _json(tmp_path / "a" / "_split.json", _map())
    assert SK.read_map(tmp_path / "a") == {"001.jpg": ("001", "-"), "185_L.jpg": ("185", "L"),
                                           "185_R.jpg": ("185", "R")}
    # журнал `nysh cases split` під тим самим іменем — не карта
    _json(tmp_path / "b" / "_split.json", {"state": "done", "parts": [{"dir": "x"}]})
    assert SK.read_map(tmp_path / "b") == {}


def test_page_name_scan_side_and_cite() -> None:
    assert SK.page_scan("185_R.jpg") == ("185", "R")
    assert SK.page_scan("001.jpg") == ("001", "-")
    assert SK.page_scan("Image00148.jpg") is None
    assert SK.src_of("185", "R") == "185R" and SK.src_of("001", "-") == "001"
    assert SK.parse_src("185R") == ("185", "R") and SK.parse_src("001") == ("001", "-")
    # рядок для документа: шифра, скан, бік, адреса
    assert SK.cite("ЦДІАК 2-1-160", "185", "R", SCAN_185) == (
        f"ЦДІАК 2-1-160, скан 185 (права сторінка) — {SCAN_185}")


# ── пул: зйомка й сторінки ───────────────────────────────────────────────────
def test_passport_with_nested_source_gives_skanoteka_ref(tmp_path: Path) -> None:
    """🔴 Доти такий паспорт не давав жодного посилання: `source` — блок, а не рядок."""
    from nyshporka.share.publish import _ref_z_adresy, _refs_from_links, _refs_from_sidecar

    d = _case(tmp_path)
    want = {"source": "skanoteka", "ref": "unit:sadowe/1703/160", "url": UNIT}
    assert _refs_from_sidecar(d) == [want]
    assert _ref_z_adresy(SCAN_185) == want
    assert _refs_from_links([{"label": "скани", "url": UNIT}]) == [want]


def test_nested_source_with_unknown_host_stays_a_plain_link(tmp_path: Path) -> None:
    from nyshporka.share.publish import _refs_from_sidecar

    _json(tmp_path / "_source.json", {"source": {"url": "https://example.org/x"}})
    assert _refs_from_sidecar(tmp_path) == [
        {"source": "url", "ref": "https://example.org/x", "url": "https://example.org/x"}]


def test_no_refs_text_names_skanoteka_as_known() -> None:
    from nyshporka.share.gates import _no_refs_text

    m = SimpleNamespace(links=[{"label": "x", "url": "https://example.org/x"}])
    assert "Skanoteka ПТГ" in _no_refs_text(m)  # type: ignore[arg-type]


def test_frames_carry_scan_and_side(tmp_path: Path) -> None:
    """Кожна сторінка в `frames.jsonl` знає свій скан і бік — і з картою, і без неї."""
    from nyshporka.share import align

    d = _case(tmp_path)
    assert [(f["name"], f.get("src")) for f in align.frames_of(d)] == [
        ("001.jpg", "001"), ("185_L.jpg", "185L"), ("185_R.jpg", "185R")]
    (d / "_split.json").unlink()                       # без карти — за формою імені
    assert [f.get("src") for f in align.frames_of(d)] == ["001", "185L", "185R"]


def test_frame_names_mean_nothing_without_the_source(tmp_path: Path) -> None:
    """`0042.jpg` у теці без Сканотеки — номер кадру справи, не скан."""
    from nyshporka.share import align

    d = tmp_path / "інша"
    d.mkdir()
    (d / "0042.jpg").write_bytes(b"jpg")
    assert "src" not in align.frames_of(d)[0]


def test_frames_in_pages_subdir_find_passport_and_map(tmp_path: Path) -> None:
    from nyshporka.share import align

    d = _case(tmp_path, frames=False)
    pages = d / "pages"
    pages.mkdir()
    (pages / "185_R.jpg").write_bytes(b"jpg")
    assert align.frames_of(pages)[0]["src"] == "185R"


# ── клієнт показує скан сторінки ─────────────────────────────────────────────
@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    yield tmp_path
    drop_space()


def test_page_link_of_own_case(space: Path) -> None:
    d = _case(space)
    write_run(space / "reports" / "htr" / "spr-160", d, key="CDIAK/2/1/160")
    got = SK.page_link("spr-160", "185_R.jpg")
    assert got is not None
    assert got["url"] == SCAN_185 and got["scan"] == "185" and got["side"] == "R"
    assert got["cite"] == f"ЦДІАК 2-1-160, скан 185 (права сторінка) — {SCAN_185}"
    assert SK.page_link("spr-160", "Image00148.jpg") is None


def test_page_link_survives_removed_frames(space: Path) -> None:
    """Кадри після прочитання знято, а карта й паспорт лишились — посилання є."""
    d = _case(space)
    write_run(space / "reports" / "htr" / "spr-160", d, key="CDIAK/2/1/160")
    for f in d.glob("*.jpg"):
        f.unlink()
    got = SK.page_link("spr-160", "185_L.jpg")
    assert got is not None and got["side"] == "L"


def test_page_link_of_accepted_run(space: Path) -> None:
    """Прийнятий з пулу прогін: скан і одиниця — з того, що приніс пакет."""
    d = space / "data" / "raw" / "чужа"
    d.mkdir(parents=True)
    write_run(space / "reports" / "htr" / "чужа", d, shared={
        "shifra": "ЦДІАК 2-1-160",
        "refs": [{"source": "skanoteka", "ref": "unit:sadowe/1703/160", "url": UNIT}],
        "page_src": {"0185.jpg": "185R"}})
    got = SK.page_link("чужа", "0185.jpg")
    assert got is not None and got["url"] == SCAN_185
    assert got["cite"].startswith("ЦДІАК 2-1-160, скан 185 (права сторінка)")


def test_accept_keeps_refs_and_page_src() -> None:
    from nyshporka.share.accept import _page_src

    m = SimpleNamespace(refs=[{"source": "skanoteka", "ref": "unit:sadowe/1703/160"}])
    frames = [{"name": "185_R.jpg", "src": "185R"}, {"name": "001.jpg", "src": "001"},
              {"name": "x.jpg"}]
    assert _page_src(m, frames, {"185_R.jpg": "0185.jpg"}) == {  # type: ignore[arg-type]
        "0185.jpg": "185R", "001.jpg": "001"}
    m.refs = [{"source": "commons", "ref": "file:X.pdf"}]
    assert _page_src(m, frames, {}) == {}  # type: ignore[arg-type]


# ── `nysh cases split` не чіпає карту ────────────────────────────────────────
def test_split_refuses_and_keeps_the_skanoteka_map(space: Path) -> None:
    """🔴 `--undo` видаляв `_split.json` як свій журнал — а це єдиний зв'язок
    сторінки з номером скана в джерелі."""
    from nyshporka.cases import split as SPL

    d = _case(space)
    before = (d / "_split.json").read_bytes()
    with pytest.raises(SPL.SplitError, match="Сканотеки"):
        SPL.undo(d)
    with pytest.raises(SPL.SplitError, match="Сканотеки"):
        SPL.split(d, [("160", "001.jpg", "185_R.jpg")])
    assert (d / "_split.json").read_bytes() == before
