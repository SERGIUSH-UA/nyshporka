"""🧰 Дії над текстом поверх стору: контекст, кроп, голоси, покриття, картка.

Усе на одній вигаданій справі з двома голосами, кадром і геометрією — щоб
кожна дія читала зі стору, а кроп різав саме той рядок, який назвали.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()

LINES = ["Кто совершалъ", "Священникъ Петръ", "Іоаннъ Ивановъ Коваль-",
         "пономъ Гри", "горіемъ и зпа", "ломщикомъ", "Волошинымъ",
         "Священникъ Пе", "тръ Гончаръ", "скій съ діакономъ",
         "скій по невѣстѣ села", "Вербки крестьяне",
         "Іоаннъ Ефимовъ Лѣновый", "подпись свидѣтелей", "и поручителей"]
BOXES = [[400, 970, 760, 1050], [340, 1190, 810, 1260], [345, 1380, 1900, 1450],
         [345, 1500, 800, 1560], [340, 1580, 820, 1640], [343, 1660, 790, 1720],
         [348, 1770, 810, 1830], [345, 2110, 830, 2170], [353, 2200, 810, 2260],
         [348, 2270, 820, 2330], [848, 1490, 1840, 1550], [848, 1570, 1860, 1630],
         [853, 1640, 1870, 1700], [2005, 890, 2510, 950], [2020, 1010, 2450, 1070]]


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from PIL import Image

    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    case_dir = tmp_path / "data" / "raw" / "проба" / "spr-1"
    case_dir.mkdir(parents=True)
    # кадр більший за геометрію (3000×4500 у рушія → 6000×9000 на диску)
    Image.new("RGB", (6000, 9000), "white").save(case_dir / "0004.jpg", quality=50)
    for run, model, second in (("проба", "pysar_cyr_v17.pt", False),
                               ("проба-diak_v4", "diak_cyr_v4.mlmodel", True)):
        d = tmp_path / "reports" / "htr" / run
        d.mkdir(parents=True)
        lines = list(LINES)
        if second:
            lines[2] = "Іоаннъ Ивановъ Ковач-"      # другий голос читає інакше
        (d / "0004.txt").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        if not second:
            (d / "0004.lines.json").write_text(
                json.dumps({"size": [3000, 4500], "boxes": BOXES}), encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps({
            "model": model, "script": "cyrillic", "case_dir": str(case_dir),
            "pages": {"0004.jpg": {"lines": len(lines), "orient": 0}},
        }), encoding="utf-8")

    from nyshporka import htr_store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "HTR_ROOT", tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба", "проба-diak_v4"]))
    yield tmp_path
    W.reset()


def test_ctx_reads_the_page_with_both_voices_and_geometry(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.ctx("проба", "4", 3, window=1)
    assert not got.get("error"), got
    assert got["page"] == "0004.jpg" and got["lines_total"] == 15
    assert [v["voice"] for v in got["voices"]] == ["pysar", "diak"]
    assert got["aligned"]
    nos = [it["no"] for it in got["window"]]
    assert nos == [2, 3, 4]
    mid = got["window"][1]
    assert mid.get("mark") == "»" and mid["text"].endswith("Коваль-")
    assert mid["voices"]["diak"].endswith("Ковач-")
    # геометрія: за рядком 3 на аркуші йде 11, хоч у файлі він восьмий після
    assert got["geo_next"] == 11 and mid["geo_next"] == 11
    full = T.ctx("проба", "0004.jpg", None)
    assert len(full["window"]) == 15


def test_crop_cuts_the_named_line_with_its_geometric_successor(space: Path) -> None:
    from PIL import Image

    from nyshporka.search import textops as T

    out = space / "crop.png"
    got = T.crop("проба", "4", 3, out=out)
    assert not got.get("error"), got
    assert got["next"] == 11 and got["scale_k"] == 2.0
    im = Image.open(out)
    # рамки 3 (345..1900 × 1380..1450) і 11 (848..1840 × 1490..1550) + pad 12, ×2
    assert got["box"] == [666, 2736, 3824, 3124]
    assert (im.width, im.height) == (3158, 388)
    assert got["text"].endswith("Коваль") and got["next_text"].startswith("скій")
    wide = T.crop("проба", "4", 1, with_next=False, wide=True, out=space / "w.png")
    assert wide["box"][0] == 0 and wide["box"][2] == 6000


def test_voices_marks_agreement_per_line(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.voices("проба", "0004", lines=(1, 4))
    assert not got.get("error"), got
    assert got["voices"] == ["pysar", "diak"] and got["aligned"]
    by_no = {it["no"]: it for it in got["lines"]}
    assert by_no[1]["agree"] and by_no[1]["sim"] == 100.0
    assert by_no[3]["sim"] is not None and by_no[3]["sim"] < 100
    assert got["agree"] + got["disagree"] == 4


def test_whatis_and_coverage_answer_without_a_registry(space: Path) -> None:
    from nyshporka.search import textops as T

    card = T.whatis("проба")
    assert [r["run"] for r in card["runs"]] == ["проба", "проба-diak_v4"]
    assert card["runs"][0]["in_store"] and card["runs"][0]["pages"] == 1
    words = dict(card["top_words"])
    assert "Вербки" in words or "Волошинымъ" in words
    cov = T.coverage("проба")
    # Реєстру справ у цьому просторі немає — але шлях модуля реєстру заморожений
    # на рівні імпорту, і сусідній тест міг лишити там свій. Тому перевіряється
    # форма відповіді, а не число: покриття відповідає, а не падає.
    assert isinstance(cov["cases"], list) and "total" in cov


def test_cli_ctx_and_crop_print_and_json(space: Path) -> None:
    from nyshporka.cli import app

    res = runner.invoke(app, ["text", "ctx", "проба", "4", "--line", "3", "--json"])
    assert res.exit_code == 0, res.output
    got = json.loads(res.output)
    assert got["ok"] and got["data"]["geo_next"] == 11
    res = runner.invoke(app, ["text", "ctx", "проба", "4", "--line", "3"])
    assert res.exit_code == 0, res.output
    assert "Коваль-" in res.output and "diak:" in res.output
    res = runner.invoke(app, ["text", "crop", "проба", "4", "3", "--out",
                              str(space / "c.png"), "--json"])
    assert res.exit_code == 0, res.output
    assert (space / "c.png").is_file()
    res = runner.invoke(app, ["text", "voices", "проба", "4", "--lines", "1-3", "--diff"])
    assert res.exit_code == 0, res.output
    assert "≠" in res.output


def test_find_prints_the_ledger_even_on_zero(space: Path) -> None:
    """🔴 Нуль без знаменника не є результатом: журнал друкується завжди."""
    from nyshporka.cli import app
    from nyshporka.search import textops as T

    got = T.find("Ковальскій", "проба", thresh=78, limit=10)
    assert not got.get("error"), got
    assert got["hits"], "фікстура беззмістовна: прізвище не знайшлось"
    led = got["ledger"]
    ids = {ch["id"]: ch for ch in led["channels"]}
    assert ids["surname"]["ran"] and ids["surname"]["hits"] >= 1
    # якорі: справа без ключа й років — канал мовчить, і причина названа
    assert not ids["anchor"]["ran"] and ids["anchor"]["why"]
    # прогін без ключа справи — область рівно один прогін, і журнал каже про один
    assert led["in_store"] == 1 and led["runs"] == 1
    assert led["voices"] == ["pysar"]

    zero = T.find("Шевченко", "проба", thresh=78, limit=10)
    assert not zero.get("error") and zero["hits"] == []
    assert zero["ledger"]["channels"][0]["hits"] == 0

    res = runner.invoke(app, ["text", "find", "Шевченко", "--case", "проба"])
    assert res.exit_code == 0, res.output
    assert "знаменник:" in res.output and "канали:" in res.output
    assert "не знайшлось" in res.output


def test_whole_stems_drop_fragments_of_a_split_surname() -> None:
    from nyshporka.search.store import whole_stems

    keep, dropped = whole_stems(["kovalskii", "koval-", "skii", "koval- skii", "kovalskogo"])
    assert keep == ["kovalskii", "kovalskogo"]
    assert set(dropped) == {"koval-", "skii", "koval- skii"}



@pytest.fixture
def case_space(space: Path) -> Path:
    """Той самий простір, але справа має ключ і бібліотеку — вердикти є куди класти."""
    import shutil

    from nyshporka import htr_store as S

    case_dir = space / "data" / "raw" / "dahmo_315" / "spr-8433"
    case_dir.mkdir(parents=True)
    shutil.copy(space / "data" / "raw" / "проба" / "spr-1" / "0004.jpg", case_dir / "0004.jpg")
    (case_dir / "_source.json").write_text(json.dumps({
        "shifra": "ДАХмО 315-1-8433", "repo": "DAHMO", "fond": "315",
        "opys": "1", "spr": "8433"}, ensure_ascii=False), encoding="utf-8")
    from nyshporka.library import build_library, write_library
    write_library(build_library())
    for run in ("проба", "проба-diak_v4"):
        mp = space / "reports" / "htr" / run / "_htr_meta.json"
        meta = json.loads(mp.read_text(encoding="utf-8"))
        meta["case_key"] = "DAHMO/315/8433"
        meta["case_dir"] = str(case_dir)
        mp.write_text(json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба", "проба-diak_v4"]))
    return space


def test_sheet_renders_cards_with_crops_and_verdict_fields(case_space: Path) -> None:
    from nyshporka.search import textops as T

    out = case_space / "sheet.html"
    got = T.sheet("Ковальскій", "DAHMO/315/8433", limit=10, crops=5, out=out)
    assert not got.get("error"), got
    assert got["cards"] >= 1 and got["crops"] >= 1
    html_doc = out.read_text(encoding="utf-8")
    assert "data:image/jpeg;base64," in html_doc
    assert '<select><option value="">—</option>' in html_doc
    assert "наш рід" in html_doc and "не прізвище" in html_doc
    assert 'data-run="проба"' in html_doc and "2-й голос" in html_doc
    # вердикт «наш рід» ніде не проставлений наперед
    assert 'value="hit" selected' not in html_doc


def test_verdicts_go_to_the_page_store_including_negatives(case_space: Path) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.search import textops as T

    rows = [
        {"run": "проба", "page": "0004.jpg", "line_no": 3, "verdict": "hit",
         "surname": "Ковальскій", "note": "розворот", "source": "sheet"},
        {"run": "проба", "page": "0004.jpg", "line_no": 12, "verdict": "noise", "note": ""},
        {"run": "проба", "page": "0004.jpg", "line_no": 1, "verdict": "щось", "note": ""},
    ]
    f = case_space / "v.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    got = T.verdicts_import(f, "DAHMO/315/8433", q="Ковальскій")
    assert not got.get("error"), got
    assert got["imported"] == 2 and got["by_verdict"] == {"hit": 1, "noise": 1}
    assert len(got["bad"]) == 1
    st = PS.case_status(PS.resolve_case("DAHMO/315/8433"), scans=["0004.jpg"])
    page = st["scans"][0]
    assert page["noted"] and page["status"] == "partial" and page["surnames_n"] == 1
    # журнал вердиктів: гортач наступного разу покаже, що вже судили
    known = T.verdicts_load("DAHMO/315/8433")
    assert known["проба|0004.jpg|3"]["verdict"] == "hit"
    assert known["проба|0004.jpg|12"]["verdict"] == "noise"
    # повторний гортач підхоплює вердикт у картку
    out = case_space / "sheet2.html"
    T.sheet("Ковальскій", "DAHMO/315/8433", limit=10, crops=0, out=out)
    assert 'value="hit" selected' in out.read_text(encoding="utf-8")


def test_cli_sheet_and_verdicts(case_space: Path) -> None:
    from nyshporka.cli import app

    out = case_space / "s.html"
    res = runner.invoke(app, ["text", "sheet", "Ковальскій", "--case", "DAHMO/315/8433",
                              "--crops", "0", "--out", str(out), "--json"])
    assert res.exit_code == 0, res.output
    assert out.is_file()
    f = case_space / "v2.json"
    f.write_text(json.dumps([{"run": "проба", "page": "0004.jpg", "line_no": 3,
                              "verdict": "unreadable", "note": "", "surname": ""}]),
                 encoding="utf-8")
    res = runner.invoke(app, ["text", "verdicts", str(f), "--case", "DAHMO/315/8433"])
    assert res.exit_code == 0, res.output
    assert "занесено 1" in res.output



def test_grep_layers_reads_canon_opys_and_notes_without_the_run_tree(space: Path) -> None:
    from nyshporka.cli import app
    from nyshporka.search import textops as T

    (space / "data" / "canonical" / "persons").mkdir(parents=True)
    (space / "data" / "canonical" / "persons" / "P-koval.md").write_text(
        "---\nid: P-koval\n---\nІван Ковальскій, син Петра\n", encoding="utf-8")
    reg = space / "data" / "raw" / "dahmo_315" / "registry"
    reg.mkdir(parents=True)
    (reg / "archium.tsv").write_text("315-1-8433\tМетрична книга, с. Ковалівка, Ковальського приходу\n", encoding="utf-8")
    (space / "reports" / "research").mkdir(parents=True)
    (space / "reports" / "research" / "KOVAL.md").write_text(
        "# Ковальські\n\nГіпотеза про Ковальских закрита.\n", encoding="utf-8")
    # тека прогонів під reports/ — шар нотаток її не торкається
    (space / "reports" / "htr" / "чужа").mkdir(parents=True, exist_ok=True)
    (space / "reports" / "htr" / "чужа" / "note.md").write_text("Ковальскій у прогоні",
                                                                encoding="utf-8")
    got = T.grep_layers(r"Коваль", ["canon", "opys", "notes"], limit=50)
    layers = {h["layer"] for h in got["hits"]}
    assert layers == {"canon", "opys", "notes"}
    assert got["layers"]["notes"]["files"] == 1 and got["layers"]["canon"]["hits"] == 1
    assert not any("htr" in h["file"] for h in got["hits"])

    res = runner.invoke(app, ["text", "grep", "Коваль", "--where", "all", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)["data"]
    assert data["layers"]["total"] == 4 and data["total"] >= 1
    res = runner.invoke(app, ["text", "grep", "Шевченко", "--where", "canon,notes"])
    assert res.exit_code == 0, res.output
    assert "не знайшлось" in res.output and "canon 1" in res.output



# ── правки за рецензіями 08.09 ───────────────────────────────────────────────
def test_literals_never_narrow_below_the_regex() -> None:
    """🔴 Найгірший клас: передфільтр відсіює рядок, який регекс мав би знайти."""
    from nyshporka.search.store import literals_of

    # група з альтернативою не дає жодного обов'язкового літерала
    assert literals_of(r"(Ков|Кав)аль") == ["аль"] or literals_of(r"(Ков|Кав)аль") is None
    assert literals_of(r"(?:Ковалевск|Ковальск)") is None
    # група з квантифікатором — теж необов'язкова
    assert literals_of(r"(Коваль)?инск") == ["инск"]
    assert literals_of(r"Ков(аль|ал)инск") == ["инск"]
    # звичайні гілки — як були
    assert literals_of(r"Дол[иіе]щ|Дал[иі]щ") == ["Дол", "Дал"]
    assert literals_of(r"Липовень?к") == ["Липовен"]


def test_grep_with_a_literal_too_short_after_norm_scans_everything(space: Path) -> None:
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    got = ST.grep(r"ськ|Коваль", ["проба"])
    assert not got["prefiltered"] and got["literal_pages"] is None
    assert got["total"] >= 1


def test_whole_stems_never_drop_what_the_person_typed() -> None:
    from nyshporka.search.store import whole_stems

    keep, dropped = whole_stems(["anna", "gana", "ganna"], keep=["anna"])
    assert "anna" in keep and "ganna" in keep
    keep, dropped = whole_stems(["kovalskii", "alskii", "koval-"], keep=["kovalskii"])
    assert keep == ["kovalskii"] and set(dropped) == {"alskii", "koval-"}


def test_short_stems_get_single_grams_in_the_prefilter() -> None:
    from nyshporka.search.store import match_expr

    expr = match_expr(["kovalskii"])                     # область: голі триграми
    assert '"kov"' in expr and '("' not in expr
    wide = match_expr(["kovalskii"], wide=True)          # корпус: короткому — і грами
    assert '"kova"' in wide and '("' in wide
    long = match_expr(["kovalevskiego"], wide=True)
    assert '("' in long and '"koval"' not in long.replace('("', "")  # лише пари


def test_anchor_names_with_apostrophe_or_hyphen_survive() -> None:
    from nyshporka.search.anchors import _clean_anchor

    assert _clean_anchor("В'ячеслав", ()) == "В'ячеслав"
    assert _clean_anchor("Марія-Анна", ()) == "Марія-Анна"
    assert _clean_anchor("митроп.", ()) == ""
    assert _clean_anchor("Ковальскій", ("koval",)) == ""


def test_crop_borrows_geometry_size_from_the_base_run(space: Path) -> None:
    """Голос Дяка без `.lines.json` ріже за рамками й розміром побратима."""
    from nyshporka.search import textops as T

    got = T.crop("проба-diak_v4", "4", 3, out=space / "d.png")
    assert not got.get("error"), got
    assert got["scale_k"] == 2.0 and got["next"] == 11


def test_verdicts_keep_page_type_and_require_a_human_for_surname_verdicts(case_space: Path) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote
    from nyshporka.search import textops as T

    ref = PS.resolve_case("DAHMO/315/8433")
    PS.annotate_pages(ref, [PageNote(scan="0004.jpg", page_type="birth", surnames=["Гончаръ"],
                                     status="partial", method="visual")])
    rows = [
        {"run": "проба", "page": "0004.jpg", "line_no": 3, "verdict": "hit",
         "surname": "Ковальскій", "note": "", "source": "sheet"},
        {"run": "проба", "page": "0004.jpg", "line_no": 7, "verdict": "other-surname",
         "surname": "", "note": "агент без гортача"},
        {"run": "проба", "page": "0004.jpg", "line_no": 12, "verdict": "noise", "note": ""},
    ]
    f = case_space / "v3.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    got = T.verdicts_import(f, "DAHMO/315/8433", q="Ковальскій")
    assert not got.get("error"), got
    assert got["imported"] == 2 and len(got["bad"]) == 1
    assert "виносить людина" in got["bad"][0]
    st = PS.case_status(ref, scans=["0004.jpg"])["scans"][0]
    assert st["page_type"] == "birth" and st["surnames_n"] == 2



# ── правки за другим раундом рецензій 08.09 ──────────────────────────────────
def test_literals_ignore_lookaround_comments_and_named_groups() -> None:
    from nyshporka.search.store import literals_of

    assert literals_of(r"(?!Ковалев)Ков\w+") == ["Ков"]
    assert literals_of(r"Ков(?#коментар)аль") in (["Ков"], ["аль"])
    assert literals_of(r"(?P<surname>Ковал)ь") == ["Ковал"] or literals_of(r"(?P<surname>Ковал)ь") == ["ь"] or literals_of(r"(?P<surname>Ковал)ь") is None
    assert literals_of(r"(?:Коваль)ск") == ["Коваль"]
    assert literals_of(r"Ков(?<!аль)ск") is None or "аль" not in (literals_of(r"Ков(?<!аль)ск") or [])


def test_grep_latin_literal_cut_inside_a_digraph_still_finds_the_line(space: Path) -> None:
    from nyshporka.search import store as ST

    run = space / "reports" / "htr" / "проба"
    (run / "0005.txt").write_text("Jan Kowalszczynski z zona\n", encoding="utf-8")
    meta = json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0005.jpg"] = {"lines": 1}
    (run / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    list(ST.ensure_all(["проба"]))
    got = ST.grep(r"Kowal[sś]zczynski", ["проба"])
    assert got["total"] == 1, got


def test_grep_does_not_count_a_stale_run_as_covered(space: Path) -> None:
    from nyshporka.search import store as ST

    list(ST.ensure_all(["проба"]))
    run = space / "reports" / "htr" / "проба"
    (run / "0006.txt").write_text("Новий Ковальскій\n", encoding="utf-8")
    meta = json.loads((run / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"]["0006.jpg"] = {"lines": 1}
    (run / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    got = ST.grep(r"Коваль", ["проба"])
    assert got["runs"] == 0 and got["unindexed"] == 1


def test_crop_refuses_borrowed_frames_of_another_segmentation(space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    d = space / "reports" / "htr" / "проба-skryba_v6"
    d.mkdir(parents=True)
    (d / "0004.txt").write_text("перший\nІоаннъ Ковальскій\nтретій\n", encoding="utf-8")
    meta = json.loads((space / "reports" / "htr" / "проба" / "_htr_meta.json").read_text(encoding="utf-8"))
    meta.update({"model": "skryba_f792_v6.mlmodel", "script": "latin",
                 "pages": {"0004.jpg": {"lines": 3, "orient": 0}}})
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    S._RUNS_CACHE = None
    list(ST.ensure_all(["проба-skryba_v6"]))
    got = T.crop("проба-skryba_v6", "4", 2, out=space / "x.png")
    assert got.get("error") and "нарізку" in got["error"]


def test_verdict_lands_under_the_existing_page_key(case_space: Path) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote
    from nyshporka.search import textops as T

    ref = PS.resolve_case("DAHMO/315/8433")
    # Унікальне ім'я аркуша: шлях сховища заморожений на рівні імпорту, і сусідні
    # тести лишають там свої «0004».
    PS.annotate_pages(ref, [PageNote(scan="0077", page_type="birth", surnames=["Гончаръ"],
                                     status="full", method="visual")])
    f = case_space / "v4.json"
    f.write_text(json.dumps([{"run": "проба", "page": "0077.jpg", "line_no": 12,
                              "verdict": "noise", "note": ""}]), encoding="utf-8")
    got = T.verdicts_import(f, "DAHMO/315/8433")
    assert got["imported"] == 1
    pages = PS.load_case(ref).pages
    assert "0077" in pages and "0077.jpg" not in pages
    assert pages["0077"].page_type == "birth"


def test_runs_cache_sees_a_meta_edited_in_place(space: Path) -> None:
    from nyshporka import htr_store as S

    rows = S.list_cases()
    assert rows and rows[0]["case_key"] == ""
    mp = space / "reports" / "htr" / "проба" / "_htr_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["case_key"] = "DAHMO/315/1"
    mp.write_text(json.dumps(meta), encoding="utf-8")   # на місці, без tmp+replace
    S._RUNS_CACHE = None
    rows = S.list_cases()
    assert rows[0]["case_key"] == "DAHMO/315/1"


def test_find_does_not_pull_profile_forms_for_a_lookalike_query(space: Path) -> None:
    from nyshporka.search import textops as T

    assert not T._query_is_profile("Шевченко")



# ── правки за третім раундом рецензій 08.09 ──────────────────────────────────
def test_find_page_tells_a_and_b_sides_of_a_spread_apart(space: Path) -> None:
    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    d = space / "reports" / "htr" / "розворот"
    d.mkdir(parents=True)
    (d / "0001a.txt").write_text("лівий аркуш\n", encoding="utf-8")
    (d / "0001b.txt").write_text("правий аркуш Ковальскій\n", encoding="utf-8")
    meta = json.loads((space / "reports" / "htr" / "проба" / "_htr_meta.json").read_text(encoding="utf-8"))
    meta["pages"] = {"0001a.jpg": {"lines": 1}, "0001b.jpg": {"lines": 1}}
    (d / "_htr_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    list(ST.ensure_all(["розворот"]))
    conn = ST.connect(readonly=True)
    try:
        assert T.find_page(conn, "розворот", "0001b") == "0001b.jpg"
        assert T.find_page(conn, "розворот", "1B.jpg") == "0001b.jpg"
        assert T.find_page(conn, "розворот", "1") == "0001a.jpg"
        assert T.find_page(conn, "розворот", "0001c") is None
    finally:
        conn.close()


def test_a_store_of_a_foreign_schema_answers_in_words_not_a_traceback(space: Path) -> None:
    import sqlite3

    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    list(ST.ensure_all(["проба"]))
    raw = sqlite3.connect(ST.path())
    raw.execute("update meta set value='1' where key='schema'")
    raw.commit()
    raw.close()
    assert ST.is_fresh("проба") is False
    for got in (T.ctx("проба", "4", line=3), T.voices("проба", "4"),
                T.crop("проба", "4", 3, out=space / "y.png")):
        assert got.get("error") and "схемою" in got["error"], got


def test_a_run_without_texts_is_not_counted_as_covered(space: Path) -> None:
    from nyshporka.search import store as ST

    d = space / "reports" / "htr" / "пусто"
    d.mkdir(parents=True)
    (d / "_htr_meta.json").write_text(json.dumps({"model": "pysar_cyr_v17.pt", "pages": {}}),
                                      encoding="utf-8")
    assert list(ST.ensure_all(["пусто"])) == []
    assert ST.is_fresh("пусто") is False
    got = ST.sweep(["kovalskii"], ["пусто", "проба"], thresh=78, build_budget=0)
    assert got["scanned"] == 1 and got["unindexed"] == 1


def test_profile_gate_accepts_a_spelling_that_carries_the_profile_substring(space: Path) -> None:
    from nyshporka.core import profile as P
    from nyshporka.search import textops as T

    (space / "config").mkdir(exist_ok=True)
    (space / "config" / "research_profile.yaml").write_text(
        "fallback: rid\nprofiles:\n  rid:\n    surname:\n      display: Ковальський\n"
        "      paradigm: adj_skyi\n      stems:\n        uk: Коваль\n"
        "      substrings:\n        - аваль\n", encoding="utf-8")
    P.reset()
    try:
        assert T._query_is_profile("Ковальскій")          # форма профілю
        assert T._query_is_profile("Кавальскій")          # описка з підрядком роду
        assert not T._query_is_profile("Ковалевський")    # сусідній рід без підрядка
        assert not T._query_is_profile("Шевченко")
    finally:
        P.reset()


def test_find_on_a_run_name_searches_and_reports_the_whole_case(case_space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.find("Ковальскій", "проба", thresh=78, limit=10)
    assert not got.get("error"), got
    led = got["ledger"]
    assert led["runs"] == 2 and led["in_store"] == 2
    assert got["case_key"] == "DAHMO/315/8433"
    assert {h["name"] for h in got["hits"]} >= {"проба", "проба-diak_v4"}
    ids = {ch["id"]: ch for ch in led["channels"]}
    assert "selfcheck" in ids and "шифр" not in (ids["selfcheck"]["why"] or "")


def test_sheet_shows_a_verdict_stored_under_the_page_store_key(case_space: Path) -> None:
    from nyshporka.pagestore import store as PS
    from nyshporka.pagestore.models import PageNote
    from nyshporka.search import textops as T

    ref = PS.resolve_case("DAHMO/315/8433")
    PS.annotate_pages(ref, [PageNote(scan="0004", page_type="birth", surnames=["Гончаръ"],
                                     status="full", method="visual")])
    h = T.find("Ковальскій", "DAHMO/315/8433", limit=10)["hits"][0]
    f = case_space / "v5.json"
    f.write_text(json.dumps([{"run": h["name"], "page": h["page"], "line_no": h["line_no"],
                              "verdict": "noise", "note": ""}]), encoding="utf-8")
    assert T.verdicts_import(f, "DAHMO/315/8433")["imported"] == 1
    out = case_space / "sheet2.html"
    got = T.sheet("Ковальскій", "DAHMO/315/8433", limit=10, crops=0, out=out)
    assert got["known_verdicts"] >= 1, got
    assert 'value="noise" selected' in out.read_text(encoding="utf-8")


def test_runs_list_sees_a_meta_edited_in_place_without_a_reset(space: Path) -> None:
    from nyshporka import htr_store as S

    rows = S.list_cases()
    assert rows and rows[0]["case_key"] == ""
    mp = space / "reports" / "htr" / "проба" / "_htr_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["case_key"] = "DAHMO/315/2"
    mp.write_text(json.dumps(meta), encoding="utf-8")   # на місці, кеш процесу НЕ скинуто
    by = {r["name"]: r for r in S.list_cases()}
    assert by["проба"]["case_key"] == "DAHMO/315/2"


def test_runs_cache_is_dropped_with_the_library(space: Path) -> None:
    from nyshporka import htr_store as S

    S._runs_cache_write({"x": {"stamp": "1", "row": {"name": "x"}}}, "lib-1")
    assert S._runs_cache_read("lib-1") == {"x": {"stamp": "1", "row": {"name": "x"}}}
    assert S._runs_cache_read("lib-2") == {}



# ── після живого пошуку 08.09: канон у selfcheck, серія як область, кроп ↑ ───
def test_selfcheck_counts_pages_cited_by_the_canon(case_space: Path) -> None:
    from nyshporka.pagestore.store import resolve_case
    from nyshporka.search import selfcheck as SC
    from nyshporka.search import textops as T

    ref = resolve_case("DAHMO/315/8433")
    canon = case_space / "data" / "canonical"
    (canon / "persons").mkdir(parents=True)
    (canon / "sources").mkdir(parents=True)
    (canon / "sources" / "S_TEST_KOVAL_CASE.md").write_text(
        "---\nid: S_TEST_KOVAL_CASE\ntype: archive\ntitle: 'ДАХмО 315-1-8433'\n"
        f"raw_path: {ref.path}/\n---\n\nДжерело.\n", encoding="utf-8")
    (canon / "persons" / "P-koval.md").write_text(
        "---\nid: P-koval\nnames:\n- form: Іван Ковальський\n  lang: uk\n  primary: true\n"
        "  given: Іван\n  surname: Ковальський\nsex: M\nfacts:\n- type: other\n"
        "  value: свідок\n  citations:\n  - source_id: S_TEST_KOVAL_CASE\n"
        "    page: стор. 3\n    confidence: direct\n    accessed: '2026-09-08'\n"
        "    note: ДАХмО 315-1-8433, скан 0004.jpg\n  status: confirmed\n"
        "media:\n- path: data/source/citations/dahmo/d8433_0004.jpg\n  type: document\n"
        "---\n\nСвідок.\n", encoding="utf-8")
    assert SC.canon_pages("Ковальскій", ref, 78) == {"0004"}
    got = T.find("Ковальскій", "DAHMO/315/8433", limit=10)
    sc = got["selfcheck"]
    assert sc["measured"] and sc["canon"] == 1 and sc["found"] == ["0004"], sc


def test_a_fond_or_opys_is_a_scope_too(case_space: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka.search import textops as T

    sc = S.runs_for_scope("315-1")
    assert sc["kind"] == "cases" and len(sc["rows"]) == 2 and sc["keys"] == ["DAHMO/315/8433"]
    assert len(S.runs_for_scope("ДАХмО 315-1")["rows"]) == 2
    with pytest.raises(ValueError):
        S.runs_for_scope("315-10")
    got = T.find("Ковальскій", "315-1", limit=10)
    assert not got.get("error") and got["hits"] and got["ledger"]["runs"] == 2


def test_crop_can_take_the_previous_line_for_a_hyphen_tail(space: Path) -> None:
    from nyshporka.search import textops as T

    got = T.crop("проба", "4", 3, with_prev=True, with_next=False, out=space / "p.png")
    assert not got.get("error"), got
    assert got["prev"] == 2 and got["prev_text"] and got["scale"] == 1.0


def test_sheet_says_when_it_cut_the_list(case_space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("text.sheet", {"q": "Ковальскій", "case": "DAHMO/315/8433", "limit": 1,
                                "crops": 0, "out": str(case_space / "s1.html")})
    assert env.ok, env
    assert any(w.code == "cut" for w in env.warnings), [w.code for w in env.warnings]


def test_the_opys_ceiling_is_named_when_it_bites(space: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Стеля обходу описів мусить називатись, а не мовчки різати вибірку.

    Мовчазне звуження читається як «не знайшлось»: нуль виходить про НАШ
    обхід, а виглядає як нуль про матеріал.
    """
    from nyshporka import ops as O
    from nyshporka.search import textops as T

    d = space / "data" / "derived" / "dahmo_opysy_ocr"
    d.mkdir(parents=True)
    for i in range(5):
        (d / f"{i}.txt").write_text("Ковальскій", encoding="utf-8")
    monkeypatch.setattr(T, "OPYS_FILE_CAP", 2)

    files, cuts = T.layer_files("opys")
    assert len(files) == 2 and cuts and "файлів 5" in cuts[0]

    env = O.call("text.grep", {"pattern": "Коваль", "where": "opys"})
    assert env.ok, env
    assert any(w.code == "layer_cut" for w in env.warnings), [w.code for w in env.warnings]


def test_dir_is_its_own_layer_and_a_missing_path_is_said_out_loud(space: Path) -> None:
    """`--dir` раніше домішувався до нотаток і для решти шарів МОВЧКИ зникав.

    Тепер у нього свій шар зі своїм знаменником, і кожна причина не прочитати
    щось називається: неіснуючий шлях давав рівно нуль без жодного слова.
    """
    from nyshporka import ops as O
    from nyshporka.search import textops as T

    outside = space.parent / "чужа-тека"
    outside.mkdir(exist_ok=True)
    (outside / "нотатка.md").write_text("Ковальскій згадується тут", encoding="utf-8")

    files, notes = T.dir_files([str(outside)])
    assert len(files) == 1 and not notes
    _, notes = T.dir_files([str(space / "нема-такого")])
    assert notes and "не існує" in notes[0]

    # шар канону — той, для якого тека раніше ігнорувалась мовчки
    got = T.grep_layers("Коваль", ["canon"], extra=[str(outside)])
    assert got["layers"]["dir"]["hits"] == 1

    env = O.call("text.grep", {"pattern": "Коваль", "where": "canon",
                               "extra": str(space / "нема-такого")})
    assert env.ok, env
    assert any(w.code == "layer_cut" for w in env.warnings), [w.code for w in env.warnings]


def test_a_crop_taken_by_the_registry_says_so(case_space: Path) -> None:
    """Кроп — приймач ока, і підміна аркуша тут коштує вердикту.

    🔴 Хмарний прогін пише в мету теку орендованого бокса. Після гасіння оренди
    шлях мертвий, кадр добирає резолвер за шифрою — і збіг ІМЕНІ файла ще не є
    збігом кадру. Раніше про це не було ні слова.
    """
    import json as _json

    from nyshporka import htr_store as S
    from nyshporka import ops as O

    mp = case_space / "reports" / "htr" / "проба" / "_htr_meta.json"
    meta = _json.loads(mp.read_text(encoding="utf-8"))
    meta["case_dir"] = "/tmp/htrcase/pages_dl_02"
    mp.write_text(_json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()

    got = S.resolve_scan_how("проба", "0004.jpg")
    assert got is not None and got[2] == "registry"

    env = O.call("text.crop", {"case": "проба", "page": "4", "line": 3,
                               "out": str(case_space / "c.png")})
    assert env.ok, env
    assert any(w.code == "frame_by_registry" for w in env.warnings), \
        [w.code for w in env.warnings]


def test_frames_match_meta_refuses_a_run_whose_frames_are_gone(case_space: Path) -> None:
    """«Кадрів стільки ж» доказом не є — тому три перевірки, і кожна зі своєю
    причиною. Мовчазний False тут був би тим самим мовчазним звуженням."""
    import json as _json

    from nyshporka import htr_store as S

    ok_now, why = S.frames_match_meta("проба")
    assert ok_now, why

    mp = case_space / "reports" / "htr" / "проба" / "_htr_meta.json"
    meta = _json.loads(mp.read_text(encoding="utf-8"))
    meta["case_dir"] = "/tmp/htrcase/pages_dl_02"
    meta["case_key"] = ""
    mp.write_text(_json.dumps(meta), encoding="utf-8")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    bad, why = S.frames_match_meta("проба")
    assert not bad and "кадрів немає" in why, why
