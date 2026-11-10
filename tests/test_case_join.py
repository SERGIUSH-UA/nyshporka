"""Справа на двох котушках: `nysh cases join`.

ДАЧкО 931-1-855 (17.10.2026): голова на плівці 007803765, хвіст — на
007803766. Стережеться порядок «голова → хвіст» за наскрізним номером в імені і
те, що зайвий виклик не кладе справу поверх чужих кадрів.
"""
from __future__ import annotations

import json as _json
import os
from pathlib import Path

import pytest
from _cherha import drop_space, make_space

from nyshporka.cases import join as J


def _film(root: Path, name: str, n: int) -> Path:
    d = root / name
    d.mkdir()
    for i in range(1, n + 1):
        (d / f"{i:04d}.jpg").write_bytes(b"\xff\xd8" + name.encode() + bytes([i]) + b"\xff\xd9")
    return d


@pytest.fixture
def films(tmp_path: Path) -> tuple[Path, Path]:
    return _film(tmp_path, "007803765_x", 12), _film(tmp_path, "007803766_x", 6)


def test_join_keeps_head_then_tail(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, tail = films
    got = J.join(tmp_path / "op1-spr-855",
                 [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    names = sorted(p.name for p in (tmp_path / "op1-spr-855").glob("*.jpg"))
    assert names == ["0001_007803765_0009.jpg", "0002_007803765_0010.jpg",
                     "0003_007803765_0011.jpg", "0004_007803765_0012.jpg",
                     "0005_007803766_0002.jpg", "0006_007803766_0003.jpg",
                     "0007_007803766_0004.jpg"]
    assert got["frames"] == 7
    a = (tmp_path / "op1-spr-855" / "0005_007803766_0002.jpg").stat()
    b = (tail / "0002.jpg").stat()
    assert os.path.samestat(a, b)          # жорстке посилання, не копія
    again = J.join(tmp_path / "op1-spr-855",
                   [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    assert again["made"] == 0               # повтор нічого не дублює


def test_join_head_dgs_greater_than_tail(tmp_path: Path) -> None:
    """DGS голови більший за DGS хвоста (007810475 → 007810474): порядок — за --part."""
    head = _film(tmp_path, "007810475_x", 12)
    tail = _film(tmp_path, "007810474_x", 6)
    dest = tmp_path / "op1-spr-889"
    got = J.join(dest, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    names = sorted(p.name for p in dest.glob("*.jpg"))
    assert [n.split("_", 1)[1] for n in names] == [
        "007810475_0009.jpg", "007810475_0010.jpg", "007810475_0011.jpg",
        "007810475_0012.jpg", "007810474_0002.jpg", "007810474_0003.jpg", "007810474_0004.jpg"]
    assert got["first"].startswith("0001_007810475") and got["last"].startswith("0007_007810474")
    # конвеєр читає теку сортуванням імен
    from nyshporka.share import align
    assert [p.name for p in align.frames_sorted(dest)] == names
    again = J.join(dest, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    assert again["made"] == 0


def test_join_legacy_folder_still_completes(films: tuple[Path, Path], tmp_path: Path) -> None:
    """Тека старого зразка `<плівка>_<кадр>` не стає «чужою»: доробляється в тому ж зразку."""
    head, tail = films
    dest = tmp_path / "old"
    dest.mkdir()
    os.link(head / "0009.jpg", dest / "007803765_0009.jpg")
    rows = J.plan(dest, [J.Piece(head, "0009.jpg", "0010.jpg"), J.Piece(tail, "0002.jpg", "0003.jpg")])
    assert [r["dst"] for r in rows] == ["007803765_0009.jpg", "007803765_0010.jpg",
                                         "007803766_0002.jpg", "007803766_0003.jpg"]


def test_join_single_piece_cuts_part_of_film(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, _ = films
    got = J.join(tmp_path / "one", [J.Piece(head, "0009.jpg", "0011.jpg")])
    assert got["frames"] == 3 and got["first"] == "0001_007803765_0009.jpg"


def test_join_refuses_alien_frames(films: tuple[Path, Path], tmp_path: Path) -> None:
    head, tail = films
    d = tmp_path / "busy"
    d.mkdir()
    (d / "0001.jpg").write_bytes(b"\xff\xd8x\xff\xd9")
    with pytest.raises(J.JoinError, match="інші кадри"):
        J.plan(d, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])


def test_join_refuses_missing_file_and_no_pieces(films: tuple[Path, Path],
                                                    tmp_path: Path) -> None:
    head, tail = films
    with pytest.raises(J.JoinError, match="немає"):
        J.plan(tmp_path / "d", [J.Piece(head, "0009.jpg", "0099.jpg"),
                                J.Piece(tail, "0002.jpg", "0004.jpg")])
    with pytest.raises(J.JoinError, match="жодної"):
        J.plan(tmp_path / "d", [])


def test_parse_piece() -> None:
    p = J.parse_piece("data/raw/x/007803765_931=0821.jpg..0973.jpg")
    assert (p.src.name, p.first, p.last) == ("007803765_931", "0821.jpg", "0973.jpg")
    with pytest.raises(J.JoinError):
        J.parse_piece("0821.jpg..0973.jpg")


# ── прочитані плівки з кадрами в бакеті ─────────────────────────────────────
# ЦДІАК 127-1012-535 (29.10.2026): голова на плівці 007800124, хвіст — на
# 007800789; обидві прочитано трьома голосами, кадри лежать архівами R2.


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    yield tmp_path
    drop_space()


def _r2_film(space: Path, dgs: str, n: int, *, shifra: str, run: str) -> Path:
    """Плівка «лише прогнати»: у теці паспорт і маніфест, прогін і голос — у reports."""
    from nyshporka.cases import register as REG

    d = space / "data" / "raw" / "cdiak_127" / f"film-{dgs}"
    d.mkdir(parents=True)
    names = [f"{i:04d}.jpg" for i in range(1, n + 1)]
    (d / "_r2_frames.json").write_text(_json.dumps({
        "frames": [{"name": x, "size": 10, "w": 4, "h": 3, "sha256": dgs + x} for x in names],
        "parts": [{"key": f"cases/{dgs}/part-001.tar", "frames": names[:3], "bytes": 30},
                  {"key": f"cases/{dgs}/part-002.tar", "frames": names[3:], "bytes": 30}],
        "bucket": "test-bucket", "dgs": dgs}), encoding="utf-8")
    (d / "_fs_meta.json").write_text(_json.dumps({Path(x).stem: f"id-{dgs}-{x}" for x in names}),
                                     encoding="utf-8")
    REG.describe(d, shifra=shifra, dgs=dgs)
    for name, voice in ((run, False), (run + "-diak_v10", True)):
        out = space / "reports" / "htr" / name
        out.mkdir(parents=True)
        for x in names:
            (out / f"{Path(x).stem}.txt").write_text(f"{dgs} {x} {'дяк' if voice else 'писар'}\n",
                                                     encoding="utf-8")
            if not voice:
                (out / f"{Path(x).stem}.lines.json").write_text("{}", encoding="utf-8")
        (out / "_htr_meta.json").write_text(_json.dumps({
            "case_dir": str(d), "case_key": "", "frames_total": n,
            "model": "diak_cyr_v10.mlmodel" if voice else "pysar_x18_v1.pt",
            "done": n if voice else True, "stages_total": {"seg": 1.0},
            "failed": [names[-1]], "pages": {x: {"lines": 1} for x in names}}), encoding="utf-8")
    return d


@pytest.fixture
def two(space: Path) -> tuple[Path, Path]:
    from nyshporka.cases import db

    head = _r2_film(space, "007800124", 6, shifra="ЦДІАК 127-1012-529", run="film-007800124")
    tail = _r2_film(space, "007800789", 5, shifra="ЦДІАК 127-1012-538", run="film-007800789")
    db.rebuild(rescan=True)
    return head, tail


def _pieces(head: Path, tail: Path) -> list[J.Piece]:
    return [J.Piece(head, "0005.jpg", "0006.jpg"), J.Piece(tail, "0001.jpg", "0002.jpg")]


def test_r2_plivky_zvodiatsia_z_tekstom(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote

    head, tail = two
    PS.annotate_pages(PS.resolve_case("ЦДІАК 127-1012-538"),
                      [PageNote(scan="0002.jpg", page_type="birth", surnames=["Дідик"])])
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"

    got = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535")

    want = ["0001_007800124_0005.jpg", "0002_007800124_0006.jpg",
            "0003_007800789_0001.jpg", "0004_007800789_0002.jpg"]
    assert not list(dest.glob("*.jpg")), "кадрів на диску не було"
    man = _json.loads((dest / "_r2_frames.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in man["frames"]] == want and man["joined"] is True
    assert man["frames"][2]["src"] == {"film": "007800789", "name": "0001.jpg"}
    assert man["frames"][2]["sha256"] == "0078007890001.jpg"
    assert [(p["key"], p["names_in_archive"]) for p in man["parts"]] == [
        ("cases/007800124/part-002.tar", {want[0]: "0005.jpg", want[1]: "0006.jpg"}),
        ("cases/007800789/part-001.tar", {want[2]: "0001.jpg", want[3]: "0002.jpg"})]

    # прогін і голос справи — сторінки під новими іменами, мета справи
    assert got["key"] == "CDIAK/127/1012/535"
    assert got["runs"] == {"": "op1012-spr-535", "-diak_v10": "op1012-spr-535-diak_v10"}
    run = space / "reports" / "htr" / "op1012-spr-535"
    assert sorted(p.name for p in run.glob("0*")) == sorted(
        [Path(x).stem + s for x in want for s in (".txt", ".lines.json")])
    assert (run / "0003_007800789_0001.txt").read_text(encoding="utf-8") == "007800789 0001.jpg писар\n"
    meta = _json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    assert (meta["case_key"], meta["frames_total"], meta["done"]) == ("CDIAK/127/1012/535", 4, True)
    assert sorted(meta["pages"]) == want and meta["failed"] == ["0002_007800124_0006.jpg"]
    assert "stages_total" not in meta and [j["run"] for j in meta["join_from"]] == [
        "film-007800124", "film-007800789"]
    voice = _json.loads((space / "reports/htr/op1012-spr-535-diak_v10/_htr_meta.json").read_text(
        encoding="utf-8"))
    assert voice["done"] == 4, "у теці голосу `done` — число сторінок"

    # паспорт, ідентифікатори FS, нотатка сховища сторінок
    side = _json.loads((dest / "_source.json").read_text(encoding="utf-8"))
    assert side["shifra"] == "ЦДІАК 127-1012-535" and side["frames_remote"] is True
    assert side["r2_keys"] == ["cases/007800124/part-002.tar", "cases/007800789/part-001.tar"]
    assert [j["film"] for j in side["join_from"]] == ["007800124", "007800789"]
    fs = _json.loads((dest / "_fs_meta.json").read_text(encoding="utf-8"))
    assert fs["0004_007800789_0002"] == "id-007800789-0002.jpg"
    assert got["notes_moved"] == 1
    cf = PS.load_case(PS.resolve_case("ЦДІАК 127-1012-535"))
    assert list(cf.pages) == ["0004_007800789_0002.jpg"]
    assert cf.pages["0004_007800789_0002.jpg"].surnames == ["Дідик"]

    again = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535")
    assert again["made"] == 0 and again["runs"] == got["runs"]


def test_chastyny_spravy_tsilymy_plivkamy_znimaiutsia(space: Path) -> None:
    """Частини однієї справи на окремих плівках («д. 502», «д. 502-2» каталогу FS)
    після збирання справами не лишаються: в Супрягу пішли б і частини, і ціла
    (29.10.2026: 12 частин ДАОО ф.37)."""
    from nyshporka import library as L
    from nyshporka.cases import db

    a = _r2_film(space, "005685657", 4, shifra="ЦДІАК 127-1012-502", run="film-005685657")
    b = _r2_film(space, "005685658", 3, shifra="ЦДІАК 127-1012-502_2", run="film-005685658")
    db.rebuild(rescan=True)
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-502"
    pieces = [J.Piece(a, "0001.jpg", "0004.jpg"), J.Piece(b, "0001.jpg", "0003.jpg")]

    got = J.join(dest, pieces, shifra="ЦДІАК 127-1012-502", rebuild=False)

    assert sorted(got["retired"]) == sorted([str(a), str(b)])
    for d, run in ((a, "film-005685657"), (b, "film-005685658")):
        side = _json.loads((d / "_source.json").read_text(encoding="utf-8"))
        assert side["joined_into"] == "CDIAK/127/1012/502"
        assert sorted(side["joined_runs"]) == [run, run + "-diak_v10"]
        meta = _json.loads((space / "reports/htr" / run / "_htr_meta.json").read_text(encoding="utf-8"))
        assert meta["superseded"]["by"] == ["op1012-spr-502", "op1012-spr-502-diak_v10"]
        assert L.split_into(str(d.relative_to(L.case_base())).replace("\\", "/")) == [
            "CDIAK/127/1012/502"]

    # повтор доробляє те саме: прогони частин — з паспорта, текст на місці
    again = J.join(dest, pieces, shifra="ЦДІАК 127-1012-502", rebuild=False)
    assert again["runs"] == got["runs"] and again["made"] == 0

    # шматок плівки (не вся тека) нічого не знімає: решта плівки — інші справи
    c = _r2_film(space, "005685700", 5, shifra="ЦДІАК 127-1012-510", run="film-005685700")
    got = J.join(space / "data" / "raw" / "cdiak_127" / "op1012-spr-511",
                 [J.Piece(c, "0004.jpg", "0005.jpg")], shifra="ЦДІАК 127-1012-511", rebuild=False)
    assert got["retired"] == [] and "joined_into" not in _json.loads(
        (c / "_source.json").read_text(encoding="utf-8"))


def test_rozkladena_plivka_viddaie_tekst_z_zhurnalu(space: Path, two: tuple[Path, Path]) -> None:
    """Плівку вже розкладено, шматок справи лишився поза справами (`-`)."""
    from nyshporka.cases import split as SPL

    head, tail = two
    SPL.split(tail, [("-", "0001.jpg", "0002.jpg"), ("537", "0003.jpg", "0004.jpg"),
                     ("538", "0005.jpg", "0005.jpg")], rebuild=False)
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"

    got = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)

    run = space / "reports" / "htr" / got["runs"][""]
    assert (run / "0004_007800789_0002.txt").read_text(encoding="utf-8") == "007800789 0002.jpg писар\n"


def test_prochytane_bez_shyfry_vidmovliaie(space: Path, two: tuple[Path, Path]) -> None:
    head, tail = two
    with pytest.raises(J.JoinError, match="--shifra"):
        J.join(space / "x", _pieces(head, tail))
    assert not (space / "x").exists(), "відмова до запису"


def test_zmishani_chastyny_vidmovliaiut(space: Path, two: tuple[Path, Path], tmp_path: Path) -> None:
    head, _ = two
    disk = _film(tmp_path, "007899999_x", 3)
    with pytest.raises(J.JoinError, match="змішано"):
        J.plan(tmp_path / "y", [J.Piece(head, "0005.jpg", "0006.jpg"),
                                J.Piece(disk, "0001.jpg", "0002.jpg")])


def test_zibrana_z_bakieta_khmara_ne_perechytuie(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka.cloud import go as G

    head, tail = two
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"
    J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)

    assert G.joined_remote(dest) is True
    assert G.joined_remote(head) is False


# ── плівка, що вся розійшлась по склейках ───────────────────────────────────
# ANRM 211-20 (04.11.2026): плівка 005613345 — кінець справи 16 (к.1–1011) і
# початок справи 17 (к.1012–1035). Жодна склейка не бере її цілою, і доти вона
# лишалась у бібліотеці «справою 211-20-16» поруч зі склеєною — пішла б у пул.


def _side(d: Path) -> dict:
    return _json.loads((d / "_source.json").read_text(encoding="utf-8"))


def _meta(space: Path, run: str) -> dict:
    return _json.loads((space / "reports/htr" / run / "_htr_meta.json").read_text(encoding="utf-8"))


def test_plivka_dvokh_skleiok_znimaietsia_pislia_druhoi(space: Path) -> None:
    from nyshporka import library as L
    from nyshporka.cases import db

    a = _r2_film(space, "005613344", 4, shifra="ANRM 211-20-15", run="film-005613344")
    b = _r2_film(space, "005613345", 6, shifra="ANRM 211-20-16", run="film-005613345")
    c = _r2_film(space, "005613346", 3, shifra="ANRM 211-20-17", run="film-005613346")
    db.rebuild(rescan=True)
    raw = space / "data" / "raw" / "cdiak_127"

    first = J.join(raw / "op20-spr-16", [J.Piece(a, "0001.jpg", "0004.jpg"),
                                         J.Piece(b, "0001.jpg", "0003.jpg")],
                   shifra="ANRM 211-20-16", rebuild=False)
    assert first["retired"] == [str(a)], "шматок b — ще не вся плівка"
    side = _side(b)
    assert "split_into" not in side and [p["key"] for p in side["joined_parts"]] == [
        "ANRM/211/20/16"]

    second = J.join(raw / "op20-spr-17", [J.Piece(b, "0004.jpg", "0006.jpg"),
                                          J.Piece(c, "0001.jpg", "0003.jpg")],
                    shifra="ANRM 211-20-17", rebuild=False)

    assert sorted(second["retired"]) == sorted([str(b), str(c)])
    side = _side(b)
    assert side["split_into"] == ["ANRM/211/20/16", "ANRM/211/20/17"]
    assert sorted(side["joined_runs"]) == ["film-005613345", "film-005613345-diak_v10"]
    assert L.split_into(str(b.relative_to(L.case_base())).replace("\\", "/")) == [
        "ANRM/211/20/16", "ANRM/211/20/17"]
    assert _meta(space, "film-005613345")["superseded"]["by"] == sorted(
        [*first["runs"].values(), *second["runs"].values()])

    # повтор склейки бере прогони заміщеної плівки з паспорта й доробляє те саме
    again = J.join(raw / "op20-spr-17", [J.Piece(b, "0004.jpg", "0006.jpg"),
                                         J.Piece(c, "0001.jpg", "0003.jpg")],
                   shifra="ANRM 211-20-17", rebuild=False)
    assert again["runs"] == second["runs"] and again["made"] == 0


def test_chuzhyi_khvist_plivky_nazyvaietsia_poza_spravamy(space: Path) -> None:
    """ANRM 134-2-56: к.0871 плівки 005773174 — останній кадр справи 55, решта —
    голова справи 56. Справ у карті немає, тож `split` відмовляв («менше двох
    справ»), а плівка лишалась «справою 134-2-56»."""
    from nyshporka.cases import db
    from nyshporka.cases import split as SPL

    a = _r2_film(space, "005773174", 4, shifra="ANRM 134-2-56", run="film-005773174")
    b = _r2_film(space, "005773175", 3, shifra="ANRM 134-2-57", run="film-005773175")
    db.rebuild(rescan=True)
    J.join(space / "data" / "raw" / "cdiak_127" / "op2-spr-56",
           [J.Piece(a, "0002.jpg", "0004.jpg"), J.Piece(b, "0001.jpg", "0003.jpg")],
           shifra="ANRM 134-2-56", rebuild=False)
    assert "split_into" not in _side(a)

    assert SPL.rest_only(a, [("56", "0001.jpg", "0001.jpg")]) is None, "у карті справа"
    with pytest.raises(SPL.SplitError, match="не забрала жодна склейка"):
        SPL.rest_only(a, [("-", "0004.jpg", "0004.jpg")])   # к.0001 лишився нічиїм
    proba = SPL.rest_only(a, [("-", "0001.jpg", "0001.jpg")], dry_run=True)
    assert proba is not None and proba["dry_run"] and "split_into" not in _side(a)

    got = SPL.rest_only(a, [("-", "0001.jpg", "0001.jpg")])

    assert got is not None and got["split_into"] == ["ANRM/134/2/56"]
    assert (got["claimed"], got["outside"]) == (3, 1)
    assert _side(a)["split_into"] == ["ANRM/134/2/56"]
    assert _meta(space, "film-005773174")["superseded"]["by"] == [
        "op2-spr-56", "op2-spr-56-diak_v10"]


def test_kray_plivky_pidkazuie_mozhlyvyi_shmatok(space: Path) -> None:
    """Частина справи після `split` проходить ворота 75 % (знаменник — свої
    кадри): ANRM 211-20-22 — 280 кадрів кінця плівки з 614."""
    from nyshporka.cases import db
    from nyshporka.cases import split as SPL
    from nyshporka.share import kray

    f = _r2_film(space, "005613354", 6, shifra="ANRM 211-20-21", run="film-005613354")
    g = _r2_film(space, "005613355", 4, shifra="ANRM 211-20-23", run="film-005613355")
    db.rebuild(rescan=True)
    got = SPL.split(f, [("-", "0001.jpg", "0002.jpg"), ("21", "0003.jpg", "0004.jpg"),
                        ("22", "0005.jpg", "0006.jpg")], rebuild=False)
    dirs = {p["spr"]: space / p["dir"] for p in got["parts"] if p.get("dir")}

    assert kray.check(dirs["21"]) == []
    tail = kray.check(dirs["22"])
    assert [w["code"] for w in tail] == ["kray_plivky"] and "останнього кадру" in tail[0]["text"]

    # склейка, що починається з першого кадру плівки, — голова могла бути раніше
    dest = space / "data" / "raw" / "anrm_211" / "op20-spr-23"
    J.join(dest, [J.Piece(g, "0001.jpg", "0004.jpg")], shifra="ANRM 211-20-23", rebuild=False)
    both = kray.check(dest)
    assert [("першого" in w["text"], "останнього" in w["text"]) for w in both] == [
        (True, False), (False, True)]


# ── зняти склейку ────────────────────────────────────────────────────────────
# ANRM 195-1-50 (10.11.2026): голова на плівці 007787447 (к.911–1120, кінець —
# «CONTINUED ON»), а склейка взяла наступну плівку 007787448 цілою. Справі на
# ній належить лише пункт 1 (к.1–69), решта — ще 11 справ фонду 195.


def test_znyattia_skleiky_povertaie_chastyny(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka.cases import split as SPL
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote

    head, tail = two
    PS.annotate_pages(PS.resolve_case("ЦДІАК 127-1012-538"),
                      [PageNote(scan="0002.jpg", page_type="birth", surnames=["Дідик"])])
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"
    wrong = [J.Piece(head, "0001.jpg", "0006.jpg"), J.Piece(tail, "0001.jpg", "0005.jpg")]
    got = J.join(dest, wrong, shifra="ЦДІАК 127-1012-535", rebuild=False)
    assert sorted(got["retired"]) == sorted([str(head), str(tail)])
    before = {d: _side(d) for d in (head, tail)}

    proba = J.undo_plan(dest)
    assert proba["dry_run"] and sorted(proba["runs_removed"]) == sorted(got["runs"].values())
    assert {d: _side(d) for d in (head, tail)} == before, "проба нічого не пише"
    assert (dest / J.JOURNAL).is_file()

    done = J.undo(dest, rebuild=False)

    assert sorted(done["runs_removed"]) == ["op1012-spr-535", "op1012-spr-535-diak_v10"]
    assert not (space / "reports/htr/op1012-spr-535").exists()
    assert not dest.exists(), "тека склейки прибрана цілком"
    for d, run in ((head, "film-007800124"), (tail, "film-007800789")):
        side = _side(d)
        assert "joined_into" not in side and "joined_runs" not in side
        assert "superseded" not in _meta(space, run)
        assert "superseded" not in _meta(space, run + "-diak_v10")
    assert done["notes_moved"] == 1
    cf = PS.load_case(PS.resolve_case("ЦДІАК 127-1012-538"))
    assert list(cf.pages) == ["0002.jpg"] and cf.pages["0002.jpg"].surnames == ["Дідик"]

    # тепер правильна склейка: з хвостової плівки — лише перший пункт
    right = J.join(dest, [J.Piece(head, "0001.jpg", "0006.jpg"),
                          J.Piece(tail, "0001.jpg", "0002.jpg")],
                   shifra="ЦДІАК 127-1012-535", rebuild=False)
    assert right["frames"] == 8 and right["retired"] == [str(head)]
    assert [p["key"] for p in _side(tail)["joined_parts"]] == ["CDIAK/127/1012/535"]
    # а решту хвостової плівки — на справи
    SPL.split(tail, [("-", "0001.jpg", "0002.jpg"), ("537", "0003.jpg", "0004.jpg"),
                     ("538", "0005.jpg", "0005.jpg")], rebuild=False)
    assert _side(tail)["split_into"]


def test_znyattia_druhoi_skleiky_vertaie_plivku_v_biblioteku(space: Path) -> None:
    """Плівку зняло покриття двома склейками (`retire_if_covered`); зняли другу —
    плівка знову справа, а перша склейка свій шматок тримає."""
    from nyshporka.cases import db

    a = _r2_film(space, "005613344", 4, shifra="ANRM 211-20-15", run="film-005613344")
    b = _r2_film(space, "005613345", 6, shifra="ANRM 211-20-16", run="film-005613345")
    c = _r2_film(space, "005613346", 3, shifra="ANRM 211-20-17", run="film-005613346")
    db.rebuild(rescan=True)
    raw = space / "data" / "raw" / "cdiak_127"
    J.join(raw / "op20-spr-16", [J.Piece(a, "0001.jpg", "0004.jpg"),
                                 J.Piece(b, "0001.jpg", "0003.jpg")],
           shifra="ANRM 211-20-16", rebuild=False)
    after_first = _side(b)
    J.join(raw / "op20-spr-17", [J.Piece(b, "0004.jpg", "0006.jpg"),
                                 J.Piece(c, "0001.jpg", "0003.jpg")],
           shifra="ANRM 211-20-17", rebuild=False)
    assert _side(b)["split_into"] == ["ANRM/211/20/16", "ANRM/211/20/17"]

    done = J.undo(raw / "op20-spr-17", rebuild=False)

    assert _side(b) == after_first
    assert "superseded" not in _meta(space, "film-005613345")
    assert "joined_into" not in _side(c) and "superseded" not in _meta(space, "film-005613346")
    assert sorted(done["runs_restored"]) == sorted(
        ["film-005613345", "film-005613345-diak_v10", "film-005613346",
         "film-005613346-diak_v10"])
    assert (raw / "op20-spr-16" / J.JOURNAL).is_file(), "перша склейка ціла"
    assert (space / "reports/htr/op20-spr-16").is_dir()


def test_znyattia_lyshaie_zminenyi_prohin(space: Path, two: tuple[Path, Path]) -> None:
    head, tail = two
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"
    got = J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)
    run = space / "reports" / "htr" / got["runs"][""]
    (run / "0001_007800124_0005.txt").write_text("вичитано оком\n", encoding="utf-8")

    done = J.undo(dest, rebuild=False)

    assert done["runs_removed"] == ["op1012-spr-535-diak_v10"]
    assert run.is_dir() and any("змінено після склейки" in k for k in done["kept"])


def test_znyattia_kadry_na_dysku_lyshaie_chuzhe(space: Path) -> None:
    """Кадри на диску: прибираються лише жорсткі посилання склейки, плівки цілі,
    а чужий файл у теці лишає теку з поясненням."""
    head, tail = _film(space, "007803765_x", 12), _film(space, "007803766_x", 6)
    dest = space / "op1-spr-855"
    J.join(dest, [J.Piece(head, "0009.jpg", "0012.jpg"), J.Piece(tail, "0002.jpg", "0004.jpg")])
    (dest / "0005_007803766_0002.jpg").unlink()
    (dest / "0005_007803766_0002.jpg").write_bytes(b"\xff\xd8 vlasnyi \xff\xd9")
    (dest / "notatka.txt").write_text("моє", encoding="utf-8")

    done = J.undo(dest, rebuild=False)

    assert sorted(p.name for p in dest.iterdir()) == ["0005_007803766_0002.jpg", "notatka.txt"]
    assert done["files_removed"] == 7, "6 посилань склейки + журнал"
    assert any("лишились файли не зі склейки" in k for k in done["kept"])
    assert len(list(head.glob("*.jpg"))) == 12 and len(list(tail.glob("*.jpg"))) == 6


def test_skleika_z_imenem_prohonu_ne_holos_teky(space: Path) -> None:
    """ANRM 88-1-2285 (10.11.2026): тека-шматок з прогоном `op1-spr-2285`; справу
    зібрано склейкою `op1-spr-2285-joined`, і розкладка теки взяла прогони склейки
    за свої голоси — заміщувала їх і різала на частини."""
    from nyshporka.cases import db
    from nyshporka.cases import split as SPL

    a = _r2_film(space, "007787419", 6, shifra="ANRM 88-1-2285", run="op1-spr-2285")
    db.rebuild(rescan=True)
    dest = space / "data" / "raw" / "anrm_88" / "op1-spr-2285-joined"
    got = J.join(dest, [J.Piece(a, "0001.jpg", "0004.jpg")], shifra="ANRM 88-1-2285", rebuild=False)
    joined = sorted(got["runs"].values())
    assert all(r.startswith("op1-spr-2285-") for r in joined), "склейка — сусід за префіксом"

    done = SPL.split(a, [("-", "0001.jpg", "0004.jpg"), ("ANRM 88-1-2286", "0005.jpg", "0006.jpg")],
                     rebuild=False)

    for r in joined:
        assert "superseded" not in _meta(space, r), f"{r} — не голос теки"
    made = {v for p in done["parts"] for v in (p.get("runs") or {}).values()}
    assert not any("joined" in r for r in made)
    assert sorted(_json.loads((a / SPL.JOURNAL).read_text(encoding="utf-8"))["runs"]) == [
        "op1-spr-2285", "op1-spr-2285-diak_v10"]


def test_znyattia_bez_skleiky_vidmovliaie(space: Path) -> None:
    with pytest.raises(J.JoinError, match="склейки в теці немає"):
        J.undo(space / "nema")


def test_operatsiia_undo_proba_nichoho_ne_pyshe(space: Path, two: tuple[Path, Path]) -> None:
    from nyshporka import ops as O

    head, tail = two
    dest = space / "data" / "raw" / "cdiak_127" / "op1012-spr-535"
    J.join(dest, _pieces(head, tail), shifra="ЦДІАК 127-1012-535", rebuild=False)

    env = O.call("cases.join", {"dest": str(dest), "undo": True, "dry_run": True})

    assert env.ok and env.data["dry_run"] is True
    assert (dest / J.JOURNAL).is_file()
    assert not O.call("cases.join", {"dest": str(dest)}).ok, "без частин і без --undo — відмова"
