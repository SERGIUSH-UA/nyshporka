"""Поіменний індекс сторінки й сторінка розвороту: прив'язка, підказка, ворота, експорт."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import gate as G
from nyshporka.train import roster as RO
from nyshporka.train import sets as S
from nyshporka.train import spread as SP
from nyshporka.train import tasks as T

SIZE = 1000
# Розворот сповідного розпису: ліва сторінка — двори 17 і 18, права — двір 19.
# (рамка, голос Писаря, голос Дяка)
LINES = [
    ([100, 60, 400, 100], "Посполитые и ихъ Домашніе", "Посполитые и их Домашние"),   # 0
    ([60, 120, 90, 150], "Лог", "по"),                                                 # 1 лічильник
    ([100, 120, 380, 150], "Симеонъ Леонтіевъ Дрига", "Симеон Леонтиев Дрига"),        # 2
    ([390, 120, 420, 150], "Ло", "4о"),                                                # 3 вік
    ([100, 160, 380, 190], "Жена Его Марія Григоріева", "Жена Его Мария Григориева"),  # 4
    ([425, 160, 445, 190], "38", "3"),                                                 # 5 вік
    ([100, 200, 380, 230], "Дѣти ихъ Михаилъ", "Дети их Михаил"),                      # 6
    ([390, 200, 420, 230], "14", "1"),                                                 # 7 вік
    ([100, 240, 380, 270], "Кондратъ Николаевъ Погребній", "Кондрат Николаев Погребни"),  # 8
    ([390, 240, 420, 270], "55", "5"),                                                 # 9 вік
    ([100, 280, 380, 310], "Жена Его Елена Ѳеодорова", "Жена Его Елена Феодорова"),    # 10
    ([425, 280, 445, 310], "41", "4"),                                                 # 11 вік
    ([600, 120, 880, 150], "Гавріилъ Ѳеодоровъ Дрозденко", "Гавриил Феодоров Дрозденко"),  # 12
    ([890, 120, 920, 150], "51", "5"),                                                 # 13 вік
]
ROSTER = {
    "source": {"title": "тестовий індекс", "by": "індексатори"},
    "pages": {"0001": [
        {"given": "Симеон", "patronymic": "Леонтиев", "surname": "Крига", "relation": "Глава",
         "age": "40", "household": "17"},
        {"given": "Мария", "patronymic": "Григориева", "relation": "Жена", "age": "38",
         "household": "17"},
        {"given": "Михаил", "relation": "Сын", "age": "14", "household": "17"},
        {"given": "Кондрат", "patronymic": "Николаев", "surname": "Погребний",
         "relation": "Глава", "age": "55", "household": "18"},
        {"given": "Елена", "patronymic": "Феодорова", "relation": "Жена", "age": "41",
         "household": "18"},
        {"given": "Гавриил", "patronymic": "Феодоров", "surname": "Дрозденко",
         "relation": "Глава", "age": "51", "household": "19"},
    ]},
}


def _crop(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (250, 50), 255)
    d = ImageDraw.Draw(im)
    for x in range(10, 240, 14):
        d.line((x, 8, x + 6, 42), fill=40, width=3)
    im.save(path)


def _run(htr: Path, name: str, texts: list[str], geo: bool) -> None:
    d = htr / name
    d.mkdir(parents=True)
    (d / "0001.txt").write_text("\n".join(texts) + "\n", encoding="utf-8")
    if geo:
        boxes = [b for b, *_ in LINES]
        (d / "0001.lines.json").write_text(json.dumps(
            {"size": [SIZE, SIZE], "boxes": boxes, "polys": [None] * len(boxes)}),
            encoding="utf-8")
    (d / "_htr_meta.json").write_text(json.dumps(
        {"pages": {"0001.jpg": {"orient": 0, "lines": len(texts)}},
         "model": "pysar_cyr_v28.pt"}), encoding="utf-8")


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    _run(ws.htr_reports, "r1", [a for _, a, _ in LINES], geo=True)
    _run(ws.htr_reports, "r1-diak", [b for _, _, b in LINES], geo=False)
    reg = S.registry(ws)
    spec = S.SetSpec(name="sp", source_run="r1", domain="сповідний розпис",
                     drafts=[S.Draft(id="pysar", run="r1"), S.Draft(id="diak", run="r1-diak")])
    reg.save(spec)
    n = len(LINES)
    meta = {"version": 3, "source_run": "r1",
            "pages": {"0001": {"n_lines": n, "size": [SIZE, SIZE], "orient": 0,
                               "boxes": [b for b, *_ in LINES], "polys": [None] * n,
                               "crop_source": "poly"}}}
    for i in range(n):
        _crop(reg.crops_of(spec) / "0001" / f"line_{i:03d}.png")
    (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "roster.json").write_text(json.dumps(ROSTER, ensure_ascii=False),
                                          encoding="utf-8")
    return ws


def _answers(ws: W.Workspace, rows: dict[str, tuple[str, str]]) -> None:
    d = S.registry(ws).set_dir("sp") / T.TASKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.answer.json").write_text(json.dumps(
        {k: {"m": m, "c": c} for k, (m, c) in rows.items()}, ensure_ascii=False),
        encoding="utf-8")


# ── розворот ─────────────────────────────────────────────────────────────────
def test_gutter_is_widest_empty_band_not_first_gap() -> None:
    boxes = [b for b, *_ in LINES]
    x, gap, crossing = SP.gutter(boxes, SIZE)
    assert 445 < x < 600 and crossing == 0 and gap >= 100
    assert SP.side_lines(boxes, SIZE, "left") == list(range(12))
    assert SP.side_lines(boxes, SIZE, "right") == [12, 13]


def test_side_roundtrip_and_own_lines(space: W.Workspace) -> None:
    rep = SP.mark_side("sp", "left", ws=space)
    assert rep.pages["0001"]["lines"] == 12
    spec = S.registry(space).load("sp")
    assert S.SetSpec.from_dict(spec.as_dict()).side == spec.side
    assert spec.own_lines()["0001"] == set(range(12))
    SP.mark_side("sp", "", ws=space)
    assert not S.registry(space).load("sp").side


def test_export_takes_only_marked_page(space: W.Workspace) -> None:
    SP.mark_side("sp", "left", ws=space)
    rep = T.export_tasks("sp", sheets=False, ws=space)
    txt = rep.files[0].read_text(encoding="utf-8")
    assert "0001:2\n" in txt and "0001:12\n" not in txt
    assert any("іншої сторінки розвороту" in w for w in rep.warnings)


# ── прив'язка ────────────────────────────────────────────────────────────────
def test_match_heads_members_and_ages() -> None:
    _, pages = RO.load_dict(ROSTER)
    people = pages["0001"]
    boxes = [b for b, *_ in LINES]
    voices = [[a for _, a, _ in LINES], [b for _, _, b in LINES]]
    pm = RO.match_page("0001", people, boxes, SIZE, voices, own=set(range(12)))
    names = {i: people[pi].full for i, (pi, _) in pm.names.items()}
    assert names == {2: "Симеон Леонтиев Крига", 4: "Мария Григориева", 6: "Михаил",
                     8: "Кондрат Николаев Погребний", 10: "Елена Феодорова"}
    ages = {j: people[pi].age for j, pi in pm.ages.items()}
    assert ages == {3: "40", 5: "38", 7: "14", 9: "55", 11: "41"}
    assert pm.reliable


def test_member_stays_in_own_household_block() -> None:
    # Друга «Марія» в дворі 18: прив'язується лише в блоці свого двору.
    _, pages = RO.load_dict(ROSTER)
    people = pages["0001"]
    people.append(RO.Person(given="Мария", relation="Дочь", age="9", household="18"))
    boxes = [b for b, *_ in LINES]
    voices = [[a for _, a, _ in LINES], [b for _, _, b in LINES]]
    pm = RO.match_page("0001", people, boxes, SIZE, voices, own=set(range(12)))
    by_person = {pi: i for i, (pi, _) in pm.names.items()}
    assert by_person[1] == 4            # Марія двору 17 — у своєму блоці
    assert len(people) - 1 not in by_person   # двору 18 «Марія» на аркуші немає — не липне


def test_build_writes_hints_and_export_shows_them(space: W.Workspace) -> None:
    SP.mark_side("sp", "left", ws=space)
    rep = RO.build("sp", space.root / "roster.json", ws=space)
    assert rep.summary()["matched"] == 5 and rep.summary()["ages"] == 5
    reg = S.registry(space)
    spec = reg.load("sp")
    src = next(h for h in spec.hint_sources if h.id == RO.ROSTER_LINE_ID)
    hints = reg.hint_data(spec, src)
    assert hints["0001:2"]["text"] == "Симеон Леонтиев Крига (глава) 40"
    assert hints["0001:3"]["text"].startswith("графа віку")   # голоси «Ло/4о» віку не читають
    assert "40" not in hints["0001:3"]["text"]
    assert not hints["0001:9"]["doubt"]                   # голос «55» — певна
    txt = T.export_tasks("sp", sheets=False, ws=space).files[0].read_text(encoding="utf-8")
    assert "ІНДЕКС: Симеон Леонтиев Крига (глава) 40" in txt
    # Смужка віку з короткими голосами без підказки в завдання не йшла б.
    assert "0001:5\n" in txt and "ІНДЕКС: вік 38" in txt
    assert "двір 19: Гавриил Феодоров Дрозденко (глава) 51" in txt


def test_dry_run_writes_nothing(space: W.Workspace) -> None:
    RO.build("sp", space.root / "roster.json", dry_run=True, ws=space)
    spec = S.registry(space).load("sp")
    assert not spec.hint_sources
    assert not (S.registry(space).set_dir("sp") / RO.STATE_FILE).exists()


# ── ворота ───────────────────────────────────────────────────────────────────
def test_import_demotes_absent_name_and_wrong_age(space: W.Workspace) -> None:
    SP.mark_side("sp", "left", ws=space)
    RO.build("sp", space.root / "roster.json", ws=space)
    _answers(space, {
        "0001:2": ("Симеонъ Леонтіевъ Березовскій", "high"),
        "0001:3": ("47", "high"),          # вік прив'язано без голосу — не суддя
        "0001:8": ("Кондратъ Николаевъ Погребній", "high"),
        "0001:9": ("57", "high"),          # індекс і голос — 55: мітка без опори
        "0001:6": ("Дѣти ихъ Михаилъ", "med"),
        "0001:0": ("Причтъ Островской Архангельской церкви", "high"),
    })
    rep = T.import_answers("sp", ws=space)
    reg = S.registry(space)
    conf = reg.merge_conf(reg.load("sp"))["0001"]
    assert conf["2"] == "low" and conf["9"] == "low"
    assert conf["3"] == "high" and conf["8"] == "high" and conf["6"] == "med"
    assert conf["0"] == "high"          # рядок причту й церкви не судиться
    assert any("Березовскій" in d for d in rep.roster_demoted)
    assert any("за індексом осіб" in w for w in rep.warnings)


def test_age_kept_when_a_voice_reads_it(space: W.Workspace) -> None:
    RO.build("sp", space.root / "roster.json", ws=space)
    # Індекс каже 38, обидва голоси й мітка — «3»: індекс не суддя.
    _answers(space, {"0001:5": ("3", "high")})
    T.import_answers("sp", ws=space)
    reg = S.registry(space)
    assert reg.merge_conf(reg.load("sp"))["0001"]["5"] == "high"


def test_unreliable_page_has_no_gate(space: W.Workspace, tmp_path: Path) -> None:
    few = {"pages": {"0001": ROSTER["pages"]["0001"][:2]}}
    f = tmp_path / "few.json"
    f.write_text(json.dumps(few, ensure_ascii=False), encoding="utf-8")
    rep = RO.build("sp", f, ws=space)
    assert not rep.pages[0].reliable
    _answers(space, {"0001:8": ("Кондратъ Николаевъ Березовскій", "high")})
    T.import_answers("sp", ws=space)
    reg = S.registry(space)
    assert reg.merge_conf(reg.load("sp"))["0001"]["8"] == "high"


def test_suspect_grounded_by_roster_and_lowered_otherwise(space: W.Workspace) -> None:
    SP.mark_side("sp", "left", ws=space)
    RO.build("sp", space.root / "roster.json", ws=space)
    _answers(space, {
        "0001:3": ("40", "high"),          # голоси «Ло/4о» — сміття; опора — вік з індексу
        "0001:2": ("Симеонъ Леонтіевъ Крига", "high"),   # голоси «Дрига», індекс — «Крига»
        "0001:1": ("102", "high"),         # лічильник, голоси «Лог/по», ряду нема — без опори
    })
    T.import_answers("sp", ws=space)
    sus = {s["idx"] for s in T.suspects_of("sp", ws=space)}
    assert 3 not in sus and 2 not in sus and 1 in sus
    lr = T.lower_suspects("sp", ws=space)
    assert lr.lowered == ["0001:1"]
    reg = S.registry(space)
    conf = reg.merge_conf(reg.load("sp"))["0001"]
    assert conf["1"] == "low" and conf["2"] == "high" and conf["3"] == "high"


def test_series_support_frames_counter_in_its_column() -> None:
    boxes = [[60, 100 + 40 * k, 90, 130 + 40 * k] for k in range(5)] + [[300, 100, 330, 130]]
    merged = ["102", "103", "105", "106", "130", "104"]
    got = G.series_support(merged, boxes, SIZE)
    assert got == {1, 2}                # 103 між 102 і 105; 105 між 103 і 106
    assert 4 not in got                 # 130 — стрибок, без опори
    assert 5 not in got                 # інша графа


def test_form_words_are_not_names() -> None:
    assert RO.name_words("Жена Его Марія Григоріева") == ["Марія", "Григоріева"]
    assert RO.name_words("Посполитые и ихъ Домашніе") == []
    assert RO.name_words("Псаломщикъ Причтъ") == []


def test_lower_keeps_label_a_voice_reads_and_saves_previous_conf(space: W.Workspace) -> None:
    RO.build("sp", space.root / "roster.json", ws=space)
    _answers(space, {
        "0001:6": ("Дети их Михаил", "high"),   # голос Дяка дає те саме, Писаря — інакше
        "0001:1": ("102", "med"),               # без опори
    })
    T.import_answers("sp", ws=space)
    lr = T.lower_suspects("sp", ws=space)
    assert lr.lowered == ["0001:1"]
    side = S.registry(space).set_dir("sp") / T.TASKS_DIR / T.LOWERED_FILE
    assert json.loads(side.read_text(encoding="utf-8")) == {"0001:1": "med"}


def test_name_line_grounded_by_household() -> None:
    p = RO.Person(given="Мария", patronymic="Григориева", relation="Жена", age="38",
                  household="17")
    assert not RO.grounds("Жена Симеона Марія", "name", p)
    assert RO.grounds("Жена Симеона Марія", "name", p, "Симеон Леонтиев Крига Мария Григориева")
    assert RO.name_words("Служителка Пономариха") == []
