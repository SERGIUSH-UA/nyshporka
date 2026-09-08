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
    assert led["in_store"] == 2 and led["runs"] == 2
    assert "pysar" in led["voices"] and "diak" in led["voices"]

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
    (space / "reports" / "htr" / "проба" / "note.md").write_text("Ковальскій у прогоні",
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

    expr = match_expr(["kovalskii"])
    assert '"koval"' in expr or '"kova"' in expr          # одиночна грама є
    long = match_expr(["kovalevskiego"])
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
