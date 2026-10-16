"""Видання з уже прочитаних номерів, коли кадри лежать деінде (`nysh print adopt`).

16.10.2026: 1 606 номерів «Колективізованого села» прочитано на чужому сховищі
партнера; тексти вдома, кадрів немає — і `nysh print assemble` казав «нема з
чого збирати», бо запис видання робив лише `cloud go --print` з теки кадрів.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nyshporka import vydannia_issues as VI


@pytest.fixture
def ws(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield W.workspace()
    W.reset()


def _read_issue(root: Path, run: str, pages: int, *, read: int | None = None,
                code: str = "KOLSELO_PYR") -> Path:
    """Тека номера так, як її кладе забір друку: txt + мета + підсумок."""
    year = run.split("_")[2][:4]
    d = root / run
    d.mkdir(parents=True)
    names = [f"{k:04d}__IMG_{k:03d}.jpg" for k in range(1, pages + 1)]
    done = names[: pages if read is None else read]
    for n in done:
        (d / f"{Path(n).stem}.txt").write_text(f"{run} {n}\n", encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps({
        "case_key": f"VYD/{code}/{year}", "model": "PaddleOCR-VL-1.6-0.9B",
        "case_dir": "/tmp/htrcase/pq_001", "pages": {n: {"lines": 1} for n in done}}),
        encoding="utf-8")
    (d / "htr_case_summary.json").write_text(json.dumps({
        "case": run, "n_pages_expected": pages}), encoding="utf-8")
    return d


# ── ім'я прогону ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("run, no, date, supplement", [
    ("kolselo_pyr_1938-03-15_60", "60", "1938-03-15", False),
    ("kolselo_pyr_1935-08-12_dod-111", "111", "1935-08-12", True),
    ("kolselo_pyr_1935-08-12_dod", "", "1935-08-12", True),
    ("kolselo_pyr_1936-01-06", "", "1936-01-06", False),
    ("kolselo_pyr_1937-12-12-13_x", None, None, None),
    ("hromadia_pyr_1918-10-24_1", None, None, None),       # чуже видання
    ("kolselo_pyr_1936-13-01_1", None, None, None),        # не дата
])
def test_run_name_is_the_inverse_of_the_ident(run: str, no, date, supplement) -> None:
    got = VI.parse_run_name("KOLSELO_PYR", run)
    if no is None:
        assert got is None
        return
    assert got is not None and (got.no, got.date, got.supplement) == (no, date, supplement)
    assert f"kolselo_pyr_{got.ident}" == run


# ── adopt → assemble ─────────────────────────────────────────────────────────
def test_adopted_issues_assemble_into_complete_years_without_frames(ws: Any) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    root = PR.out_root()
    _read_issue(root, "kolselo_pyr_1936-01-08_4", 2)
    _read_issue(root, "kolselo_pyr_1936-01-06_3", 2)
    _read_issue(root, "kolselo_pyr_1935-08-12_dod-111", 1)
    _read_issue(root, "kolselo_pyr_1935-08-12_111", 2)
    _read_issue(root, "hromadia_pyr_1918-10-24_1", 2, code="HROMADIA_PYR")   # не наше

    got = PE.adopt("KOLSELO_PYR", title="Колективізоване село", city="Пирятин")
    assert got.issues == 4 and got.years == [1935, 1936]

    years = {y.year: y for y in PE.assemble("KOLSELO_PYR")}
    y36 = years[1936]
    assert y36.complete and (y36.pages, y36.issues, y36.read) == (4, 2, 4)
    texts = [(y36.run_dir / f"{k:04d}.txt").read_text(encoding="utf-8").split()[0]
             for k in range(1, 5)]
    assert texts == ["kolselo_pyr_1936-01-06_3"] * 2 + ["kolselo_pyr_1936-01-08_4"] * 2
    rows = json.loads((y36.run_dir / "issues.json").read_text(encoding="utf-8"))
    assert [(r["no"], r["first_page"], r["pages"]) for r in rows] == [("3", 1, 2), ("4", 3, 2)]
    y35 = json.loads((years[1935].run_dir / "issues.json").read_text(encoding="utf-8"))
    assert [(r["no"], r.get("note")) for r in y35] == [("111", None), ("111", "додаток")]


def test_a_page_the_summary_knows_but_nobody_read_keeps_the_year_incomplete(ws: Any) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    _read_issue(PR.out_root(), "kolselo_pyr_1937-01-02_1", 3, read=2)
    PE.adopt("KOLSELO_PYR")
    (y,) = PE.assemble("KOLSELO_PYR")
    assert (y.pages, y.read) == (3, 2) and not y.complete


def test_a_local_issue_folder_wins_over_an_adopted_text(ws: Any, tmp_path: Path) -> None:
    """Номер, що вже записаний із локальними кадрами, `adopt` не підміняє."""
    from PIL import Image

    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    frames = tmp_path / "Колективізоване село" / "1936" / "3 (770) 1936-01-06"
    frames.mkdir(parents=True)
    for k in (1, 2):
        Image.new("L", (20, 30), 200).save(frames / f"{k:04d}.jpg", "JPEG")
    out = PR.out_root() / "kolselo_pyr_1936-01-06_3"
    out.mkdir(parents=True)
    for k in (1, 2):
        (out / f"{k:04d}.txt").write_text("локально\n", encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({"case_key": "VYD/KOLSELO_PYR/1936",
                                                    "pages": {}}), encoding="utf-8")
    PE.record("KOLSELO_PYR", title="КС", city="", issues=[(out.name, frames, out)])

    got = PE.adopt("KOLSELO_PYR")
    assert got.issues == 0
    (y,) = PE.assemble("KOLSELO_PYR")
    rows = json.loads((y.run_dir / "issues.json").read_text(encoding="utf-8"))
    assert rows[0]["no_total"] == "770", "запис із теки кадрів, а не з тексту"


def test_adopt_refuses_a_bad_code(ws: Any) -> None:
    from nyshporka import print_edition as PE

    with pytest.raises(ValueError):
        PE.adopt("к")


def test_print_adopt_op_points_to_assemble(ws: Any) -> None:
    from nyshporka import ops as O
    from nyshporka.cloud import printed as PR

    _read_issue(PR.out_root(), "kolselo_pyr_1936-01-06_3", 2)
    env = O.call("print.adopt", {"vydannia": "KOLSELO_PYR", "title": "КС"})
    assert env.ok and env.data["issues"] == 1
    assert any("наскрізних" in str(w) for w in env.warnings)


# ── картка видання → картка в пулі ───────────────────────────────────────────
def _adopted_year(ws: Any) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    root = PR.out_root()
    _read_issue(root, "kolselo_pyr_1938-01-01_1", 2)
    _read_issue(root, "kolselo_pyr_1938-01-03_2", 2)
    _read_issue(root, "kolselo_pyr_1938-01-03_dod-2", 1)
    PE.adopt("KOLSELO_PYR")


def test_pack_refuses_a_bare_card_and_names_what_to_fill(ws: Any) -> None:
    from nyshporka import ops as O

    _adopted_year(ws)
    env = O.call("print.pack", {"vydannia": "KOLSELO_PYR", "dry_run": True})
    assert not env.ok
    for field in ("title", "city", "doc_type", "holder"):
        assert field in env.error
    assert "nysh print card KOLSELO_PYR" in env.error


def test_the_card_rides_into_every_year_where_the_pool_shows_it(ws: Any, monkeypatch) -> None:
    from nyshporka import ops as O
    from nyshporka.share import print_pack as PP

    _adopted_year(ws)
    env = O.call("print.card", {
        "vydannia": "KOLSELO_PYR", "title": "Колективізоване село", "city": "Пирятин",
        "doc_type": "newspaper", "holder": "НБУВ, відділ газетних фондів",
        "places": ["Пирятинський район", "Полтавська область"],
        "organ": ["1932–1937: Орган Пирятинського РПК та РВК Харківської області",
                  "1938–1940: Орган Пирятинського РК КП(б)У та РВК Полтавської області"],
        "scans_url": "https://example.org/kolselo"})
    assert env.ok and env.data["gaps"] == []

    seen: dict[str, Any] = {}

    def fake(src, code, year, **kw):  # noqa: ANN001
        seen.update(kw, year=year)
        return {"manifest": {}, "gates": {"passed": True}, "path": "x", "dry_run": True}

    monkeypatch.setattr(PP, "pack_print", fake)
    env = O.call("print.pack", {"vydannia": "KOLSELO_PYR", "dry_run": True})
    assert env.ok, env.error
    assert seen["publisher_place"] == "Пирятин" and seen["doc_type"] == "newspaper"
    assert seen["places"] == ["Пирятинський район", "Полтавська область"]
    assert seen["links"][0] == {"role": "scans", "url": "https://example.org/kolselo",
                                "label": "скани підшивки"}
    note = seen["note"]
    assert note.startswith("Орган Пирятинського РК КП(б)У та РВК Полтавської області.")
    assert "Місце видання — Пирятин." in note
    assert "За 1938 рік у пулі 2 номери і 1 додаток, 5 сторінок" in note
    assert "перший — № 1 від 01.01.1938, останній — № 2 від 03.01.1938" in note
    assert "Підшивка: НБУВ, відділ газетних фондів." in note


def test_pack_print_puts_place_and_genre_where_the_pool_reads_them(tmp_path: Path) -> None:
    from nyshporka.share.print_pack import pack_print

    src = tmp_path / "y"
    src.mkdir()
    (src / "0001.txt").write_text("Колективізоване село\n", encoding="utf-8")
    got = pack_print(src, "KOLSELO_PYR", 1938, title="Колективізоване село",
                     ocr_by="PaddleOCR-VL", publisher_place="Пирятин",
                     places=["Полтавська область"], doc_type="newspaper", dry_run=True)
    case = got["manifest"]["case"]
    assert case["place"] == "Пирятин" and case["doc_type"] == "newspaper"
    assert case["places"] == ["Пирятин", "Полтавська область"]


def test_an_unknown_genre_is_refused(ws: Any) -> None:
    from nyshporka import print_edition as PE

    _adopted_year(ws)
    with pytest.raises(ValueError, match="жанр"):
        PE.set_card("KOLSELO_PYR", doc_type="газетка")


def test_places_follow_the_years_of_the_administrative_division() -> None:
    from nyshporka import print_edition as PE

    rec = {"places": ["Пирятинський район", "1932–1937: Харківська область",
                      "1937–1940: Полтавська область"]}
    assert PE.places_for(rec, 1936) == ["Пирятинський район", "Харківська область"]
    assert PE.places_for(rec, 1937) == ["Пирятинський район", "Харківська область",
                                        "Полтавська область"]
    assert PE.places_for(rec, 1940) == ["Пирятинський район", "Полтавська область"]
