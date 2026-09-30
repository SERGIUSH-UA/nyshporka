"""Номер кадру у справі й id кадру джерела — окремими полями.

🔴 Доки обидва жили лише в імені файла (`0037_f351120.jpg`), кожен читач
розбирав його по-своєму. Правило «номер сторінки — остання група цифр»
віддавало для такого імені id джерела: «скан 37» справи з ARCHIUM не
знаходився. Паспорт завантаження й перелік кадрів пакета цих полів не мали
зовсім (звіт користувача 29.09.2026).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nyshporka.core import framename
from nyshporka.share import align
from nyshporka.sources.base import FetchResult

# ── ім'я кадру ────────────────────────────────────────────────────────────────

def test_imia_buduietsia_i_rozbyraietsia_odnym_mistsem() -> None:
    assert framename.build(37, 351120) == "0037_f351120"
    assert framename.build(37) == "0037"
    assert framename.parse("0037_f351120.jpg") == framename.Frame(37, "351120")
    assert framename.parse(framename.build(5, "9")) == framename.Frame(5, "9")


@pytest.mark.parametrize("name", ["Image00148.jpg", "f792-1-55_0042.jpg",
                                  "1854_0012.jpg", "0012.jpg", "n0007.jpg"])
def test_neznaioma_forma_ne_vhaduietsia(name: str) -> None:
    """🔴 `1854_0012` — рік і номер, а не номер і id: без маркера не розбираємо."""
    assert framename.parse(name) == framename.Frame()


def test_forma_dzherela_lyshe_za_pidkazkoiu() -> None:
    assert framename.parse("0003_IMG_7712.jpg", "babynyar") == framename.Frame(3, "IMG_7712")
    assert framename.parse("n0007.jpg", "ia") == framename.Frame(7, "7")
    assert framename.parse("0003_IMG_7712.jpg") == framename.Frame()


# ── паспорт завантаження ──────────────────────────────────────────────────────

def test_pasport_nese_nomer_i_id_okremo(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import record_fetch

    for n, i in ((1, 1001), (2, 1002)):
        (tmp_path / f"{n:04d}_f{i}.jpg").write_bytes(b"jpg" + bytes([n]))
    record_fetch(tmp_path, FetchResult(dest=tmp_path, frames=2),
                 source="archium", ref="file:1", want=2)

    files = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["files"]
    assert [(f["n"], f["src"], f["pagecount"]) for f in files] == [
        (1, "1001", 1), (2, "1002", 1)]


def test_pasport_bez_id_ne_vyhaduie_ioho(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import frame_files

    (tmp_path / "Image00148.jpg").write_bytes(b"x")
    row = frame_files(tmp_path, tmp_path)[0]
    assert "n" not in row and "src" not in row


# ── перелік кадрів пакета й мітка ─────────────────────────────────────────────

def _teka(root: Path, names: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        (root / name).write_bytes(b"JPEG" + bytes([i]) * 8)
    return root


def test_perelik_kadriv_nese_id_dzherela(tmp_path: Path) -> None:
    d = _teka(tmp_path / "a", ["0001_f9001.jpg", "0002_f9002.jpg", "obkladynka.jpg"])
    got = align.frames_of(d)

    assert [f.get("src") for f in got] == ["9001", "9002", None]
    assert align.summary(got)["with_src"] == 2
    assert "with_src" not in align.summary(align.frames_of(_teka(tmp_path / "b", ["1.jpg"])))


def test_ti_sami_kadry_pid_inshymy_imenamy_exact(tmp_path: Path) -> None:
    """Дві людини качали ту саму справу й назвали файли по-різному."""
    theirs = align.frames_of(_teka(tmp_path / "a", ["0001_f9001.jpg", "0002_f9002.jpg"]))
    ours = _teka(tmp_path / "b", ["0101_f9001.jpg", "0102_f9002.jpg"])

    got = align.grade(theirs, ours)

    assert got.label == align.EXACT and got.matched == 2
    assert align.page_names(theirs, ours) == {
        "0001_f9001.jpg": "0101_f9001.jpg", "0002_f9002.jpg": "0102_f9002.jpg"}


def test_chastkovyi_zbih_id_ne_exact(tmp_path: Path) -> None:
    """🔴 Один спільний кадр із двох — не «ті самі кадри», і імен не перекладаємо."""
    theirs = align.frames_of(_teka(tmp_path / "a", ["0001_f9001.jpg", "0002_f9002.jpg"]))
    ours = _teka(tmp_path / "b", ["0101_f9001.jpg", "0102_f7777.jpg"])

    assert align.grade(theirs, ours).label == align.BY_POSITION
    assert align.page_names(theirs, ours) == {}


def test_vidpovidnist_lyshe_koly_id_maiut_usi(tmp_path: Path) -> None:
    theirs = align.frames_of(_teka(tmp_path / "a", ["0001_f9001.jpg", "0002_f9002.jpg"]))
    zaivyi = _teka(tmp_path / "b", ["0101_f9001.jpg", "0102_f9002.jpg", "obkladynka.jpg"])

    assert align.page_names(theirs, zaivyi) == {}
    assert align.page_names(theirs, None) == {}


# ── «скан 37» ─────────────────────────────────────────────────────────────────

def _stor(pages: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("create table runs (id integer primary key, run text)")
    conn.execute("create table pages (id integer primary key, run_id integer, "
                 "page text, stem text)")
    conn.execute("insert into runs values (1, 'spr-473')")
    for p in pages:
        conn.execute("insert into pages (run_id, page, stem) values (1, ?, ?)",
                     (p, Path(p).stem))
    return conn


def test_skan_za_nomerom_u_spravi_a_ne_za_id_dzherela() -> None:
    """🔴 `0037_f351120`: «37» — це кадр 37, а не кадр 351120."""
    from nyshporka.search.textops import find_page

    conn = _stor(["0036_f351119.jpg", "0037_f351120.jpg", "0038_f37.jpg"])

    assert find_page(conn, "spr-473", "37") == "0037_f351120.jpg"
    assert find_page(conn, "spr-473", "0036") == "0036_f351119.jpg"
    # id джерела й далі знаходить свій кадр — коли такого номера у справі немає
    assert find_page(conn, "spr-473", "351119") == "0036_f351119.jpg"


def test_skan_za_nomerom_u_zvychainykh_imenakh() -> None:
    from nyshporka.search.textops import find_page

    conn = _stor(["Image00036.jpg", "Image00037.jpg"])
    assert find_page(conn, "spr-473", "37") == "Image00037.jpg"
