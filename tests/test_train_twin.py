"""Двійник рядка: той самий запис іншим письмом — пари, підказка арбітрам, ворота."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import sets as S
from nyshporka.train import tasks as T
from nyshporka.train import twin as TW

# Розворот двомовного бланка: ліва половина кирилицею, права польською.
# Рядок 5 і 11 — графа віку (вузька рамка), решта — записи.
CYR = ["1. Дворъ", "Ѳеодоръ Ѳеодоровъ сынъ Полищукъ", "жена его Ѳекла Ильина дочь",
       "Дѣти у нихъ сынъ Иванъ", "дочь Евдокія", "40"]
LAT = ["1. Chałupa", "Tedor Fedorow Poliszczuk", "Zona iego Tekla Iłkowa",
       "Dzieci u nich Syn Iwan", "Córka Jeudocha", "40"]
# Кириличний голос на польській половині: каша, але «нихъ сынъ» народжує.
CYR_ON_LAT = ["1. Халупа", "Тедор Федоровъ Полищук", "Зона иего Текла Илкова",
              "Дзеци у нихъ Сынъ Иван", "Корка Иеудоха", "40"]
# Латинський голос на кириличній половині: каша без польських формул.
LAT_ON_CYR = ["1 Dbopb", "Oeodopb Oeodopobb cbinb Hoauyykb", "wena ero Oekaa Haburia aoub",
              "Atmu y nuxb cbinb Uband", "aoub Ebaokia", "40"]
SIZE = 1000


def _boxes() -> list[list[int]]:
    out = []
    for x0 in (50, 550):
        for i in range(5):
            out.append([x0, 100 + i * 60, x0 + 250, 150 + i * 60])
        out.append([x0 + 350, 160, x0 + 380, 210])   # вік — на висоті рядка 1
    return out


def _crop(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (250, 50), 255)
    d = ImageDraw.Draw(im)
    for x in range(10, 240, 14):
        d.line((x, 8, x + 6, 42), fill=40, width=3)
    im.save(path)


def _run(htr: Path, name: str, pages: dict[str, list[str]], geo: bool) -> None:
    d = htr / name
    d.mkdir(parents=True)
    for pg, ls in pages.items():
        (d / f"{pg}.txt").write_text("\n".join(ls) + "\n", encoding="utf-8")
        if geo:
            boxes = _boxes()[:len(ls)]
            (d / f"{pg}.lines.json").write_text(json.dumps(
                {"size": [SIZE, SIZE], "boxes": boxes, "polys": [None] * len(boxes)}),
                encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps(
        {"pages": {f"{pg}.jpg": {"orient": 0, "lines": len(ls)} for pg, ls in pages.items()},
         "model": "pysar_cyr_v28.pt"}), encoding="utf-8")


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    htr = ws.htr_reports
    # Розворот: сторінка 0001 має обидві половини.
    _run(htr, "r1", {"0001": CYR + CYR_ON_LAT}, geo=True)
    _run(htr, "r1-diak", {"0001": [t.replace("ъ", "") for t in CYR + CYR_ON_LAT]}, geo=False)
    _run(htr, "r1-lat", {"0001": LAT_ON_CYR + LAT}, geo=False)
    # Чергування через аркуш: 0001 кирилицею, 0002 польською.
    _run(htr, "r2", {"0001": CYR, "0002": CYR_ON_LAT}, geo=True)
    _run(htr, "r2-diak", {"0001": [t.replace("ъ", "") for t in CYR],
                          "0002": CYR_ON_LAT}, geo=False)
    _run(htr, "r2-lat", {"0001": LAT_ON_CYR, "0002": LAT}, geo=False)
    reg = S.registry(ws)
    for name, run, n in (("tw", "r1", 12), ("tp", "r2", 6)):
        spec = S.SetSpec(name=name, source_run=run, domain="ревізька казка 1795",
                         drafts=[S.Draft(id="pysar", run=run),
                                 S.Draft(id="diak", run=f"{run}-diak")])
        reg.save(spec)
        meta = {"version": 3, "source_run": run,
                "pages": {"0001": {"n_lines": n, "size": [SIZE, SIZE], "orient": 0,
                                   "boxes": _boxes()[:n], "polys": [None] * n,
                                   "crop_source": "poly"}}}
        for i in range(n):
            _crop(reg.crops_of(spec) / "0001" / f"line_{i:03d}.png")
        (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    return ws


# ── чисті функції ────────────────────────────────────────────────────────────
def test_key_puts_both_scripts_side_by_side() -> None:
    a = TW.key("Ѳеодоръ Ѳеодоровъ Полищукъ")
    b = TW.key("Fedor Fedorow Poliszczuk")
    assert TW.sim(a, b) >= 0.85
    assert TW.sim(TW.key("жена его"), TW.key("Zona iego")) >= 0.6


def test_script_by_formulae_of_its_own_voice() -> None:
    assert TW.script_of(CYR, LAT_ON_CYR) == "cyrillic"
    assert TW.script_of(CYR_ON_LAT, LAT) == "latin"
    assert TW.script_of(["Тогожъ"], ["Togoz"]) == ""


def test_align_is_monotonic_and_pairs_records() -> None:
    got = TW.align(CYR[:5], LAT[:5])
    assert [(a, b) for a, b, _ in got if a in (1, 2, 3)] == [(1, 1), (2, 2), (3, 3)]
    assert all(b1 < b2 for (_, b1, _), (_, b2, _) in itertools.pairwise(got))


def test_halves_split_spread_by_gutter() -> None:
    left, right = TW.halves(_boxes(), SIZE)
    assert left == list(range(6)) and right == list(range(6, 12))


def test_church_name_supported_by_folk_form() -> None:
    assert TW.unsupported("Дѣти у нихъ сынъ Игнатъ", "Dzieci u nich Syn Hnat") == []
    assert TW.unsupported("дочь Параскевія", "Córka Paraska") == []
    assert TW.unsupported("Онофрей Ивановъ", "Onufry Iwanow") == []
    assert TW.unsupported("жена его Мария Григоріева", "Zona iego Marya Hrehorowa") == []


def test_invented_surname_has_no_support() -> None:
    got = TW.unsupported("Иванъ Петровъ сынъ Березовскій", "Iwan Petrow Syn Tatarczuk")
    assert got == ["Березовскій"]


def test_formula_words_are_not_names() -> None:
    assert TW.name_words("Жена Его Сынъ Дочь") == []
    # обрізана друкована шапка графи й огризок на межі смужки — не імена
    assert TW.name_words("Муже- Жен-") == []
    assert TW.name_words("жена Его Ефимия Гав") == ["Ефимия"]
    assert TW.name_words("Отецъ Его Иванъ") == ["Иванъ"]
    assert TW.name_words("Ojciec iego Szlachcic") == []
    assert TW.name_words("Упражняется хлѣбопашествомъ") == []
    assert TW.name_words("въ Селеніи") == []
    assert TW.name_words("1795 Года Іюня 4 Дня") == []


# ── набір ────────────────────────────────────────────────────────────────────
def test_spread_twin_hints_and_own_half(space: W.Workspace) -> None:
    rep = TW.build("tw", twin_run="r1-lat", ws=space)
    assert [p.twin_page for p in rep.pages] == ["0001"] and not rep.missing
    reg = S.registry(space)
    spec = reg.load("tw")
    assert spec.twin["pages"]["0001"]["own"] == list(range(6))
    src = next(h for h in spec.hint_sources if h.id == TW.TWIN_ID)
    hints = reg.hint_data(spec, src)
    assert hints["0001:1"]["text"] == "Tedor Fedorow Poliszczuk"
    page = reg.hint_data(spec, next(h for h in spec.hint_sources if h.id == TW.TWIN_PAGE_ID))
    assert "Zona iego Tekla" in page["0001"]["text"]


def test_dry_run_writes_nothing(space: W.Workspace) -> None:
    TW.build("tw", twin_run="r1-lat", dry_run=True, ws=space)
    spec = S.registry(space).load("tw")
    assert not spec.twin and not spec.hint_sources


def test_export_skips_other_script_and_shows_twin(space: W.Workspace) -> None:
    TW.build("tw", twin_run="r1-lat", ws=space)
    rep = T.export_tasks("tw", sheets=False, ws=space)
    txt = rep.files[0].read_text(encoding="utf-8")
    assert "0001:1\n" in txt and "0001:7\n" not in txt
    assert "ДВІЙНИК: Tedor Fedorow Poliszczuk" in txt
    assert "той самий запис іншим письмом" in txt
    assert any("іншого письма" in w for w in rep.warnings)
    assert sorted(T.pending_rows(S.registry(space), S.registry(space).load("tw"))["0001"]) \
        == [0, 1, 2, 3, 4]   # «40» — графа віку: коротка смужка, не рядок завдання


def test_import_demotes_name_absent_from_twin(space: W.Workspace) -> None:
    TW.build("tw", twin_run="r1-lat", ws=space)
    d = S.registry(space).set_dir("tw") / T.TASKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.answer.json").write_text(json.dumps({
        "0001:1": {"m": "Ѳеодоръ Ѳеодоровъ сынъ Березовскій", "c": "high"},
        "0001:2": {"m": "жена его Ѳекла Ильина дочь", "c": "high"},
        "0001:3": {"m": "Дѣти у нихъ сынъ Иванъ", "c": "med"}}, ensure_ascii=False),
        encoding="utf-8")
    rep = T.import_answers("tw", ws=space)
    reg = S.registry(space)
    conf = reg.merge_conf(reg.load("tw"))["0001"]
    assert conf["1"] == "low"
    assert conf["2"] == "high" and conf["3"] == "med"
    assert rep.twin_demoted and "Березовскій" in rep.twin_demoted[0]


def test_pages_layout_takes_neighbour_of_other_script(space: W.Workspace) -> None:
    rep = TW.build("tp", twin_run="r2-lat", ws=space)
    assert [(p.page, p.twin_page, p.note) for p in rep.pages] == [("0001", "0002", "pages")]
    spec = S.registry(space).load("tp")
    assert "own" not in spec.twin["pages"]["0001"]
    assert spec.twin_own() == {}


def test_mixed_run_set_names_its_script(space: W.Workspace) -> None:
    reg = S.registry(space)
    spec = reg.load("tp")
    spec.script = "mixed"
    reg.save(spec)
    with pytest.raises(TW.TwinError, match="--script"):
        TW.build("tp", twin_run="r2-lat", ws=space)
    TW.build("tp", twin_run="r2-lat", script="cyrillic", ws=space)
    assert reg.load("tp").script == "cyrillic"


def test_line_twins_only_sure_pairs(space: W.Workspace) -> None:
    TW.build("tw", twin_run="r1-lat", ws=space)
    reg = S.registry(space)
    spec = reg.load("tw")
    assert TW.line_twins(reg, spec, "0001")[1] == "Tedor Fedorow Poliszczuk"
    assert 5 not in TW.line_twins(reg, spec, "0001")   # графа віку пари не має


def test_label_grounded_by_twin_pair() -> None:
    assert TW.grounds("42", "42")
    assert not TW.grounds("42", "24")
    assert TW.grounds("ынъ Ризакъ —", "syn Ryzak")
    assert not TW.grounds("Иванъ Березовскій", "Iwan Tatarczuk")
    assert not TW.grounds("дочь", "")


def test_pages_layout_neighbour_by_frame_number(space: W.Workspace) -> None:
    # Частковий прогін: прочитано 0005 (кирилиця) і 0009 (польська) — не сусіди.
    _run(space.htr_reports, "r3", {"0005": CYR, "0009": CYR_ON_LAT}, geo=True)
    _run(space.htr_reports, "r3-lat", {"0005": LAT_ON_CYR, "0009": LAT}, geo=False)
    reg = S.registry(space)
    spec = S.SetSpec(name="tq", source_run="r3", drafts=[S.Draft(id="pysar", run="r3")])
    reg.save(spec)
    meta = {"version": 3, "source_run": "r3",
            "pages": {"0005": {"n_lines": 6, "size": [SIZE, SIZE], "orient": 0,
                               "boxes": _boxes()[:6], "polys": [None] * 6, "crop_source": "poly"}}}
    for i in range(6):
        _crop(reg.crops_of(spec) / "0005" / f"line_{i:03d}.png")
    (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    rep = TW.build("tq", twin_run="r3-lat", ws=space)
    assert rep.missing == ["0005"]
    assert any("0004, 0006" in w for w in rep.warnings)
