"""Друк у хмарі: від теки підшивки до років `VYD/<код>/<рік>` — без локального рушія.

Розпізнає друк лише орендована машина (пакет оренди). Тут перевіряється те, що
робить Нишпорка: розгортає теку видання в номери, складає план друку (ваг немає,
текст лягає поза `reports/htr`), записує видання, після забору збирає роки в
порядку дат і не пакує неповного року.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image


def _issue(root: Path, year: str, name: str, pages: int) -> Path:
    d = (root / year / name) if year else (root / name)
    d.mkdir(parents=True)
    for k in range(1, pages + 1):
        Image.new("L", (20, 30), 200).save(d / f"{k:04d}.jpg", "JPEG")
    return d


@pytest.fixture
def ws(tmp_path: Path) -> Any:
    from nyshporka.core import workspace as W

    W.use(W.Workspace(root=tmp_path / "ws", name="тест", origin="test"))
    yield W.workspace()
    W.reset()


@pytest.fixture
def edition(tmp_path: Path) -> Path:
    root = tmp_path / "Колективізоване село"
    _issue(root, "1936", "4 (771) 1936-01-08", 2)
    _issue(root, "1936", "3 (770) 1936-01-06", 2)
    _issue(root, "1937", "1 (782) 1937-01-01", 1)
    return root


# ── розгортання ──────────────────────────────────────────────────────────────
def test_edition_folder_expands_into_issue_folders(edition: Path, tmp_path: Path) -> None:
    from nyshporka import print_edition as PE

    plain = tmp_path / "справа"
    plain.mkdir()
    got = PE.expand([str(edition), str(plain)])

    assert [Path(c).name for c in got.cases] == [
        "3 (770) 1936-01-06", "4 (771) 1936-01-08", "1 (782) 1937-01-01", "справа"]
    assert got.editions[0].title == "Колективізоване село"


def test_print_go_demands_an_edition_code_and_suggests_one(edition: Path) -> None:
    from nyshporka.cloud import go as GO

    with pytest.raises(GO.GoRefused, match="--vydannia KOLSELO_PYR"):
        GO._print_cases((str(edition),), vydannia="", title="", city="Пирятин",
                        dry_run=False)
    cases, ed = GO._print_cases((str(edition),), vydannia="kolselo_pyr", title="",
                                city="Пирятин", dry_run=False)
    assert len(cases) == 3
    assert {k: ed[k] for k in ("code", "title", "city")} == {
        "code": "KOLSELO_PYR", "title": "Колективізоване село", "city": "Пирятин"}


def test_an_issue_runs_under_the_edition_not_under_an_archive_case(edition: Path) -> None:
    """🔴 Ім'я й ключ номера — від видання. Ключ зі шляху (`CASES/1936/1/6`) у
    різних газет одного дня збігався, а ім'я теки номера («1 1934-02-12») — теж."""
    from nyshporka import print_edition as PE
    from nyshporka.cloud import go as GO

    cases, ed = GO._print_cases((str(edition),), vydannia="KOLSELO_PYR", title="",
                                city="", dry_run=False)
    runs = [PE.run_for(ed["runs"], c) for c in cases]
    assert [(r.name, r.key) for r in runs] == [
        ("kolselo_pyr_1936-01-06_3", "VYD/KOLSELO_PYR/1936"),
        ("kolselo_pyr_1936-01-08_4", "VYD/KOLSELO_PYR/1936"),
        ("kolselo_pyr_1937-01-01_1", "VYD/KOLSELO_PYR/1937")]


def test_a_city_folder_with_several_papers_is_run_paper_by_paper(tmp_path: Path) -> None:
    """`НБУВ/Пирятин` з трьома газетами: у кожної свій код — відмова з готовими
    командами, а не один захід під одним кодом."""
    from nyshporka.cloud import go as GO

    city = tmp_path / "cases" / "НБУВ" / "Пирятин"
    _issue(city / "Громадянин", "", "1 (1918-10-24)", 1)
    _issue(city / "За ударну працю", "1934", "1 1934-02-12", 1)
    _issue(city / "Колективізоване село", "1934", "16 (443) 1934-02-12", 1)

    with pytest.raises(GO.GoRefused, match="3 видань") as err:
        GO._print_cases((str(city),), vydannia="X1", title="", city="Пирятин",
                        dry_run=False)
    assert "Громадянин" in str(err.value) and "За ударну працю" in str(err.value)
    # одна газета з того самого міста — їде
    cases, _ = GO._print_cases((str(city / "За ударну працю"),), vydannia="ZAUDPR_PYR",
                               title="", city="", dry_run=False)
    assert [Path(c).name for c in cases] == ["1 1934-02-12"]
    # номери двох газет в одному заході — ні
    with pytest.raises(GO.GoRefused, match="різних видань"):
        GO._print_cases((str(city / "За ударну працю" / "1934" / "1 1934-02-12"),
                         str(city / "Колективізоване село" / "1934" / "16 (443) 1934-02-12")),
                        vydannia="X1", title="", city="", dry_run=False)


def test_two_folders_of_one_issue_stop_the_run(edition: Path) -> None:
    from nyshporka.cloud import go as GO

    _issue(edition, "1936", "3 1936-01-06", 1)
    with pytest.raises(GO.GoRefused, match="той самий номер двічі"):
        GO._print_cases((str(edition),), vydannia="KOLSELO_PYR", title="", city="",
                        dry_run=False)


def test_print_refuses_an_archive_case_key(edition: Path) -> None:
    from nyshporka.cloud import go as GO

    res = GO.go(str(edition), backend="vast", script="print", vydannia="KOLSELO_PYR",
                case_key="CASES/1936/1/6", dry_run=True)
    assert res.verdict == "refused" and "--case-key" in res.why


def test_unparsed_folders_stop_the_run_before_renting(edition: Path) -> None:
    from nyshporka.cloud import go as GO

    (edition / "1936" / "нотатки").mkdir()
    with pytest.raises(GO.GoRefused, match="не розібрались як номер"):
        GO._print_cases((str(edition),), vydannia="KOLSELO_PYR", title="", city="",
                        dry_run=False)


# ── план друку ───────────────────────────────────────────────────────────────
def test_print_plan_has_no_weights_and_writes_outside_reports(ws: Any, edition: Path) -> None:
    from nyshporka.cloud import plan as PL
    from nyshporka.cloud import printed as PR

    issue = edition / "1936" / "3 (770) 1936-01-06"
    plan = PL.build(issue, backend="vast", script="print", case_key="VYD/KOLSELO_PYR/1936",
                    out_name="kolselo_pyr_1936-01-06_3")

    assert (plan.script, plan.model.name, plan.voice) == ("print", PR.MODEL, None)
    assert plan.out_dir == PR.out_root() / "kolselo_pyr_1936-01-06_3"
    assert plan.case_key == "VYD/KOLSELO_PYR/1936"
    assert ws.htr_reports not in plan.out_dir.parents
    with pytest.raises(PL.PlanError, match="один рушій"):
        PL.build(issue, backend="vast", script="print", model="pysar_cyr_v19.pt",
                 case_key="VYD/KOLSELO_PYR/1936", out_name="kolselo_pyr_1936-01-06_3")


def test_a_print_plan_without_the_edition_is_refused(ws: Any, edition: Path) -> None:
    """Без видання ключ лишалось би брати зі шляху — тобто з дати номера."""
    from nyshporka.cloud import plan as PL

    with pytest.raises(PL.PlanError, match="кодом видання"):
        PL.build(edition / "1936" / "4 (771) 1936-01-08", backend="vast", script="print")


# ── давніший захід: кадри вже в сховищі ──────────────────────────────────────
def _old_plan(ws: Any, issue: Path, key: str) -> None:
    """План наглядача з заходу, коли номер ішов безіменною справою."""
    d = ws.derived / "cloud" / "supervised" / "runs" / "htr-old"
    d.mkdir(parents=True, exist_ok=True)
    url = f"https://acc0.r2.cloudflarestorage.com/bkt/{key}?sig=x"
    (d / "plan.json").write_text(json.dumps(
        {"cases": [{"case": "x", "case_dir": str(issue), "pages_url": url}]}),
        encoding="utf-8")


def _old_stage(ws: Any, issue: Path, owner: Path | None = None) -> Path:
    stage = ws.derived / "cloud" / "frames" / issue.name
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "_from.txt").write_text(str((owner or issue).resolve()), encoding="utf-8")
    return stage


def test_an_issue_finds_its_frames_from_the_earlier_run(ws: Any, edition: Path) -> None:
    """Партнер залив 1 789 номерів, коли друку ще не було: стиснута копія й
    адреса в сховищі лишились під іменем теки номера."""
    from nyshporka import print_edition as PE

    PE._PLAN_KEYS.clear()
    issue = edition / "1936" / "3 (770) 1936-01-06"
    _old_plan(ws, issue, "cases/3-770-1936-01-06.tar")
    stage = _old_stage(ws, issue)

    assert PE.legacy_frames(issue) == (stage, "cases/3-770-1936-01-06.tar")


def test_a_stranger_copy_under_the_same_name_is_not_taken(ws: Any, tmp_path: Path) -> None:
    """«1 1934-02-12» є і в іншій газеті: копія з таким іменем, підписана ЧУЖОЮ
    текою, не наша."""
    from nyshporka import print_edition as PE

    PE._PLAN_KEYS.clear()
    ours = _issue(tmp_path / "Колективізоване село", "1934", "1 1934-02-12", 1)
    theirs = _issue(tmp_path / "За ударну працю", "1934", "1 1934-02-12", 1)
    _old_stage(ws, ours, owner=theirs)

    assert PE.legacy_frames(ours) == (None, "")


def test_the_key_is_read_from_a_presigned_link() -> None:
    from nyshporka import print_edition as PE

    assert PE._key_of_url("https://acc0.r2.cloudflarestorage.com/bkt/cases/"
                          "3%20%28770%29.tar?X=1") == "cases/3 (770).tar"
    assert PE._key_of_url("https://bkt.acc0.r2.cloudflarestorage.com/cases/a.tar?X=1") \
        == "cases/a.tar"


# ── наглядач ─────────────────────────────────────────────────────────────────
def test_print_plan_needs_a_supervisor_that_can_print(tmp_path: Path) -> None:
    from nyshporka.cloud import supervised as SUP
    from nyshporka.cloud.go import GoRefused

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"params": {"engine": "paddle_vl"}}), encoding="utf-8")
    with pytest.raises(GoRefused, match="не вміє друк"):
        SUP._check_engine(plan)
    plan.write_text(json.dumps({"params": {"engine": "paddle_vl"}, "print_engine": 1}),
                    encoding="utf-8")
    SUP._check_engine(plan)


def test_print_fetch_hooks_assemble_years(ws: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.cloud import supervised as SUP

    monkeypatch.setattr(SUP, "nysh_exe", lambda: "nysh")
    hooks = SUP.print_fetch_hooks()

    assert [h["cmd"][1:] for h in hooks] == [["print", "assemble"], ["cases", "build"]]
    assert all(h["cwd"] == str(ws.root) for h in hooks)


def test_print_params_name_only_the_engine() -> None:
    """Ворота друку (Ampere, VRAM, диск, ціна тисячі сторінок, датацентри) вшиті
    в наглядача за самим рушієм: план, складений будь-ким, отримує ті самі."""
    from nyshporka.cloud import printed as PR

    assert PR.plan_params() == ["engine=paddle_vl", "script=print"]


# ── роки ─────────────────────────────────────────────────────────────────────
def _read(out_root: Path, run: str, issue: Path, skip: str = "") -> Path:
    out = out_root / run
    out.mkdir(parents=True, exist_ok=True)
    for frame in sorted(issue.glob("*.jpg")):
        if frame.name != skip:
            (out / f"{frame.stem}.txt").write_text(f"{issue.name} {frame.stem}\n",
                                                   encoding="utf-8")
    return out


def test_years_are_assembled_in_date_order(ws: Any, edition: Path) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    issues = [edition / "1936" / "4 (771) 1936-01-08", edition / "1936" / "3 (770) 1936-01-06",
              edition / "1937" / "1 (782) 1937-01-01"]
    rows = [(i.name, i, _read(PR.out_root(), i.name, i)) for i in issues]
    PE.record("KOLSELO_PYR", title="Колективізоване село", city="Пирятин", issues=rows)

    years = {y.year: y for y in PE.assemble("KOLSELO_PYR")}

    y36 = years[1936]
    assert y36.complete and (y36.pages, y36.issues) == (4, 2)
    assert y36.missing_numbers == []
    texts = [(y36.run_dir / f"{k:04d}.txt").read_text(encoding="utf-8").strip()
             for k in range(1, 5)]
    assert texts == ["3 (770) 1936-01-06 0001", "3 (770) 1936-01-06 0002",
                     "4 (771) 1936-01-08 0001", "4 (771) 1936-01-08 0002"]
    meta = json.loads((y36.run_dir / "_htr_meta.json").read_text(encoding="utf-8"))
    assert meta["case_key"] == "VYD/KOLSELO_PYR/1936" and meta["engine"] == "print"
    rows36 = json.loads((y36.run_dir / "issues.json").read_text(encoding="utf-8"))
    assert [(r["no"], r["first_page"], r["no_total"]) for r in rows36] == [
        ("3", 1, "770"), ("4", 3, "771")]
    assert y36.run_dir.name == "vyd_kolselo_pyr_1936"
    # Наскрізні 772–781 лежать між роками: це пропуск зібрання, а не року.
    assert years[1937].missing_numbers == []
    st = PE.status("KOLSELO_PYR")[0]
    assert all(y["missing_numbers"] == [] for y in st["years"])


def test_a_year_with_a_missing_page_is_searchable_but_not_complete(ws: Any,
                                                                  edition: Path) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    i3 = edition / "1936" / "3 (770) 1936-01-06"
    i4 = edition / "1936" / "4 (771) 1936-01-08"
    rows = [(i3.name, i3, _read(PR.out_root(), i3.name, i3)),
            (i4.name, i4, _read(PR.out_root(), i4.name, i4, skip="0002.jpg"))]
    PE.record("KOLSELO_PYR", title="Колективізоване село", city="", issues=rows)

    y36 = next(y for y in PE.assemble("KOLSELO_PYR") if y.year == 1936)

    assert not y36.complete and y36.read == 3
    assert y36.missing_pages == ["4 (1936-01-08) 0002.jpg"]
    assert not (y36.run_dir / "0004.txt").exists() and (y36.run_dir / "0003.txt").exists()
    st = PE.status("KOLSELO_PYR")[0]["years"]
    assert [(y["year"], y["read"], y["pages"]) for y in st] == [(1936, 3, 4), (1937, 0, 1)]


def test_pack_refuses_an_incomplete_year(ws: Any, edition: Path) -> None:
    from nyshporka import ops as O
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    i3 = edition / "1936" / "3 (770) 1936-01-06"
    PE.record("KOLSELO_PYR", title="Колективізоване село", city="",
              issues=[(i3.name, i3, _read(PR.out_root(), i3.name, i3, skip="0001.jpg"))])
    PE.set_card("KOLSELO_PYR", city="Пирятин", doc_type="newspaper", holder="тестова підшивка")

    env = O.call("print.pack", {"vydannia": "KOLSELO_PYR", "year": 1936, "dry_run": True})

    assert env.ok and env.data["packs"] == [] and env.data["skipped"] == ["VYD/KOLSELO_PYR/1936"]


def test_edition_follows_the_supervisor_out_dirs(ws: Any, edition: Path) -> None:
    """Наглядач кладе текст за своїм slug-ім'ям справи — видання йде за ним."""
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    i3 = edition / "1936" / "3 (770) 1936-01-06"
    PE.record("KOLSELO_PYR", title="", city="", issues=[(i3.name, i3, PR.out_root() / i3.name)])
    slug = PR.out_root() / "3-770-1936-01-06"
    _read(PR.out_root(), "3-770-1936-01-06", i3)

    assert PE.repoint({i3.name: str(slug), "чужий номер": "x"}) == 1
    y36 = next(y for y in PE.assemble("KOLSELO_PYR") if y.year == 1936)
    # номер 3 прочитано за текою наглядача; номер 4 у цьому тесті не читали
    assert y36.read == 2 and all(m.startswith("4 ") for m in y36.missing_pages)



# ── разова книга (відгук 18.10.2026) ─────────────────────────────────────────
@pytest.fixture
def book(tmp_path: Path) -> Path:
    """Книга — тека кадрів без номерів і дат: «Список избирателей…», 1912."""
    return _issue(tmp_path, "", "Список избирателей 1912", 3)


def test_a_book_runs_as_one_unit_of_its_year(book: Path) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import go as GO

    cases, ed = GO._book_case((str(book),), vydannia="izbir_ekat", title="",
                              city="Катеринослав", year=1912)
    run = PE.run_for(ed["runs"], cases[0])
    assert (run.name, run.key) == ("izbir_ekat_1912", "VYD/IZBIR_EKAT/1912")
    assert ed["book"] == 1912 and ed["title"] == "Список избирателей 1912"


@pytest.mark.parametrize("cases, code, year, why", [
    (2, "IZBIR", 1912, "одна тека"),
    (1, "", 1912, "назвіть код"),
    (1, "IZBIR", 12, "рік видання"),
])
def test_a_book_refuses_what_it_cannot_honestly_name(book: Path, cases: int, code: str,
                                                     year: int, why: str) -> None:
    from nyshporka.cloud import go as GO

    with pytest.raises(GO.GoRefused, match=why):
        GO._book_case(tuple([str(book)] * cases), vydannia=code, title="", city="",
                      year=year)


def test_book_without_print_is_refused(book: Path) -> None:
    from nyshporka.cloud import go as GO

    res = GO.go(str(book), book=1912, dry_run=True, backend="fake")
    assert res.verdict == "refused" and "--print" in res.why


def test_a_book_is_assembled_without_issue_numbers_or_dates(ws: Any, book: Path) -> None:
    """🔴 Дати й номера в книги немає — і в зібраному році їх не з'являється."""
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    PE.record("IZBIR_EKAT", title="Список городских избирателей", city="Катеринослав",
              issues=[("izbir_ekat_1912", book, _read(PR.out_root(), "izbir_ekat_1912", book))],
              book=1912)

    (y,) = PE.assemble("IZBIR_EKAT")
    assert y.complete and (y.year, y.pages, y.issues) == (1912, 3, 1)
    rows = json.loads((y.run_dir / "issues.json").read_text(encoding="utf-8"))
    assert rows == [{"first_page": 1, "pages": 3, "note": "книга"}]
    note = PE.year_note(PE.load_record("IZBIR_EKAT"), 1912, rows, 3)
    assert "книга, 1912" in note and "номер" not in note and "від" not in note


def test_a_book_packs_with_the_book_genre(ws: Any, book: Path) -> None:
    from nyshporka import ops as O
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    PE.record("IZBIR_EKAT", title="Список городских избирателей", city="Катеринослав",
              issues=[("izbir_ekat_1912", book, _read(PR.out_root(), "izbir_ekat_1912", book))],
              book=1912)
    PE.assemble("IZBIR_EKAT")
    PE.set_card("IZBIR_EKAT", doc_type="book", holder="примірник ЦДІАК, бібліотека")

    env = O.call("print.pack", {"vydannia": "IZBIR_EKAT", "year": 1912, "dry_run": True})

    assert env.ok, env.error
    assert env.data["skipped"] == [] and len(env.data["packs"]) == 1


def test_a_locally_read_book_keeps_its_own_model(ws: Any, book: Path) -> None:
    """🔴 25.10.2026: книга, прочитана Писарем на своїй машині, лягла б у пул
    з підписом «PaddleOCR-VL, хмарний прогін»."""
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    out = _read(PR.out_root(), "izbir_ekat_1912", book)
    (out / "_htr_meta.json").write_text(json.dumps(
        {"model": "pysar_cyr_v28.pt", "engine": "parseq", "script": "cyrillic",
         "device": "cuda:0"}), encoding="utf-8")
    PE.record("IZBIR_EKAT", title="Список городских избирателей", city="Катеринослав",
              issues=[("izbir_ekat_1912", book, out)], book=1912)

    (y,) = PE.assemble("IZBIR_EKAT")
    meta = json.loads((y.run_dir / "_htr_meta.json").read_text(encoding="utf-8"))
    assert (meta["model"], meta["engine"]) == ("pysar_cyr_v28.pt", "parseq")
    assert PE.ocr_by(meta) == "pysar_cyr_v28.pt (Нишпорка, рушій parseq)"
    note = PE.year_note(PE.load_record("IZBIR_EKAT"), 1912, [], 3, meta)
    assert "pysar_cyr_v28.pt" in note and "PaddleOCR" not in note
    # Хмарний друк мети в теку номера не кладе — підпис лишається старим.
    assert PE.ocr_by({"model": "PaddleOCR-VL-1.6-0.9B"}) == PE.OCR_BY


def test_a_book_and_issues_never_share_a_code(ws: Any, book: Path, edition: Path) -> None:
    from nyshporka import print_edition as PE
    from nyshporka.cloud import printed as PR

    PE.record("IZBIR_EKAT", title="Список", city="",
              issues=[("izbir_ekat_1912", book, _read(PR.out_root(), "izbir_ekat_1912", book))],
              book=1912)
    i3 = edition / "1936" / "3 (770) 1936-01-06"
    with pytest.raises(ValueError, match="уже має книгу"):
        PE.record("IZBIR_EKAT", title="", city="",
                  issues=[(i3.name, i3, _read(PR.out_root(), i3.name, i3))])
    PE.record("KOLSELO_PYR", title="Колективізоване село", city="",
              issues=[(i3.name, i3, _read(PR.out_root(), i3.name, i3))])
    with pytest.raises(ValueError, match="номери періодичного видання"):
        PE.record("KOLSELO_PYR", title="", city="",
                  issues=[("kolselo_pyr_1912", book, PR.out_root() / "x")], book=1912)
