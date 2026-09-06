"""Канал А: завдання арбітрам, відповіді, ворота, аркуші, дивилка."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import gate as G
from nyshporka.train import sets as S
from nyshporka.train import sheets as SH
from nyshporka.train import tasks as T
from nyshporka.train import view as V

PAGE_W, PAGE_H = 600, 400
LINES = {"0001": ["Николай Ивановъ сынъ", "Марѳа Васильева", "по тому объ обу объ",
                  "Приходскій Священникъ", "Село Ходъ"],
         "0002": ["Иванъ Петровъ", "Анна Ѳедорова", "Дьячокъ Ѳедоръ"]}
VOICE_B = {"0001": ["Николай Иванов сынь", "Марфа Васильева", "по тому объ обу об",
                    "Приходский Священник", "Село Ходь"],
           "0002": ["Иван Петров", "Анна Федорова", "Дьячок Федор"]}


def _boxes(n: int) -> list[list[int]]:
    return [[40, 20 + i * 60, PAGE_W - 40, 60 + i * 60] for i in range(n)]


def _page(n: int, blank: set[int] = frozenset()) -> Image.Image:
    im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    d = ImageDraw.Draw(im)
    for i, b in enumerate(_boxes(n)):
        if i in blank:
            continue
        for x in range(b[0] + 10, b[2] - 10, 14):
            d.line((x, b[1] + 8, x + 6, b[3] - 8), fill="black", width=3)
    return im


def _crop(path: Path, ink: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (PAGE_W - 80, 40), 255)
    if ink:
        d = ImageDraw.Draw(im)
        # Чорнило на скані темне, але не чорне (0 — це заливка поза полігоном,
        # яку частка чорнила виключає). 40 — типова щільність штриха.
        for x in range(10, im.width - 10, 14):
            d.line((x, 8, x + 6, 32), fill=40, width=3)
    im.save(path)


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    htr = ws.htr_reports
    for run, lines in (("r1", LINES), ("r1-diak", VOICE_B)):
        d = htr / run
        d.mkdir(parents=True)
        for pg, ls in lines.items():
            (d / f"{pg}.txt").write_text("\n".join(ls) + "\n", encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps(
            {"pages": {pg: {"orient": 0, "lines": len(ls)} for pg, ls in lines.items()},
             "model": "pysar_cyr_v17.pt"}), encoding="utf-8")
    reg = S.registry(ws)
    spec = S.SetSpec(name="demo", source_run="r1", domain="проба",
                     drafts=[S.Draft(id="pysar", run="r1"), S.Draft(id="diak", run="r1-diak")],
                     glossary={"Ѳедоръ": "з титулу"})
    reg.save(spec)
    meta = {"version": 3, "source_run": "r1", "pages": {}}
    for pg, ls in LINES.items():
        for i in range(len(ls)):
            _crop(reg.crops_of(spec) / pg / f"line_{i:03d}.png", ink=not (pg == "0001" and i == 4))
        meta["pages"][pg] = {"n_lines": len(ls), "size": [PAGE_W, PAGE_H], "orient": 0,
                             "boxes": _boxes(len(ls)), "polys": [None] * len(ls),
                             "crop_source": "poly"}
    (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    yield ws
    W.reset()


def _img(run: str, page: str) -> Image.Image:
    return _page(len(LINES[page]))


# ── ворота ───────────────────────────────────────────────────────────────────
def test_gate_rules_on_text() -> None:
    assert G.verdict(G.signals("по тому объ обу объ", ["по тому объ", "обу объ"], None),
                     "по тому объ обу объ")
    assert not G.verdict(G.signals("Въ селѣ Ходъ", ["Въ селѣ Ходъ", "Въ селе Ход"], None),
                         "Въ селѣ Ходъ")
    assert not G.verdict(G.signals("Отъ 10 до 15 г.", ["Отъ 10", "до 15"], None),
                         "Отъ 10 до 15 г.")
    assert G.verdict(G.signals("текст", ["a", "b"], 0.0001), "текст"), "без чорнила → low"
    sig = G.signals("ПРОКУРОРЪ", ["Пркурр", "Ілосуо"], None)
    assert G.suspect(sig, "ПРОКУРОРЪ") and not G.verdict(sig, "ПРОКУРОРЪ")
    assert G.grounded("Остапенко", ["Атаманенко", "Атаманенка"]) < G.GROUNDED_MIN


def test_shift_is_judged_by_blocks_not_by_page() -> None:
    def word(i: int, k: int) -> str:
        return "".join(chr(0x430 + (i * 7 + k * 5 + j * 3) % 32) for j in range(9))

    voices = [[" ".join(word(i, k) for k in range(5)) for i in range(40)]]
    llm = voices[0][:20] + voices[0][21:] + [""]   # хвіст з'їхав на +1
    blocks = G.shifted_blocks(llm, voices)
    assert blocks and blocks[0][2] == 1 and blocks[0][0] >= 20


def test_ink_fraction_separates_blank_from_written(space: W.Workspace) -> None:
    reg = S.registry(space)
    spec = reg.load("demo")
    assert G.ink_fraction(reg.crop_path(spec, "0001", 0)) > G.INK_MIN
    assert G.ink_fraction(reg.crop_path(spec, "0001", 4)) < G.INK_MIN


# ── експорт ──────────────────────────────────────────────────────────────────
def test_export_cuts_by_pages_and_puts_notes_before_rows(space: W.Workspace) -> None:
    rep = T.export_tasks("demo", pages_per_file=1, ws=space, image_of=_img)
    assert len(rep.files) == 2 and rep.rows == 7
    assert rep.dropped_blank == ["0001:4"]
    txt = rep.files[0].read_text(encoding="utf-8")
    assert txt.index("★ СЛОВНИК") < txt.index("Рядки:")
    assert txt.index("★ АРКУШІ") < txt.index("Рядки:")
    assert "нysh train import" not in txt and "nysh train import --set demo" in txt
    assert "МАРКЕРІВ РОЗБІЖНОСТІ НЕ СТАВ" in txt and "скупо" not in txt.lower()
    assert "0001:0\n  A: Николай Ивановъ сынъ\n  B: Николай Иванов сынь" in txt
    assert "0002" not in txt.split("Рядки:")[1]
    assert rep.sheets["0001"] == ["0001.png"]
    assert (rep.out.parent / T.SHEETS_DIR / "0001.drafts.txt").is_file()


def test_export_folds_unanimous_and_needs_two_voices(space: W.Workspace) -> None:
    reg = S.registry(space)
    spec = reg.load("demo")
    (space.htr_reports / "r1-diak" / "0002.txt").write_text(
        "\n".join(LINES["0002"]) + "\n", encoding="utf-8")
    rep = T.export_tasks("demo", pages=["0002"], ws=space, image_of=_img, sheets=False)
    txt = rep.files[0].read_text(encoding="utf-8")
    assert "0002:0\n  = Иванъ Петровъ" in txt and "★ ЗГОРТКА" in txt
    with pytest.raises(T.TaskError, match="немає сторінок"):
        T.export_tasks("demo", pages=["0099"], ws=space, image_of=_img)
    spec.drafts = spec.drafts[:1]
    reg.save(spec)
    with pytest.raises(T.TaskError, match="ДВА голоси"):
        T.export_tasks("demo", ws=space, image_of=_img)


# ── імпорт ───────────────────────────────────────────────────────────────────
def test_import_partial_answer_gates_and_meta(space: W.Workspace) -> None:
    T.export_tasks("demo", pages_per_file=3, ws=space, image_of=_img, sheets=False)
    reg = S.registry(space)
    tasks = reg.set_dir("demo") / T.TASKS_DIR
    (tasks / "demo_part01.answer.json").write_text(json.dumps({
        "0001:0": {"m": "Николай Ивановъ сынъ", "c": "high"},
        "0001:1": {"m": "Марѳа ‹Васильева|Василиева›", "c": "high"},
        "0001:2": {"m": "по тому объ обу объ", "c": "med"},
        "0001:3": {"m": "", "c": "high"},
        "0002:0": {"m": "Иванъ Петровъ", "c": "high"},
        "0002:2": {"m": "Дьячокъ Ѳадоръ", "c": "high"},
        "0009:0": {"m": "чуже", "c": "high"},
        "зайве": {"m": "x", "c": "high"},
    }, ensure_ascii=False), encoding="utf-8")
    rep = T.import_answers("demo", ws=space)
    assert rep.rows == 6 and rep.pages == ["0001", "0002"]
    assert len(rep.rejected) == 2
    merged = (reg.merge_dir(reg.load("demo")) / "0001.txt").read_text(encoding="utf-8").splitlines()
    assert merged[1] == "Марѳа Васильева", "маркер не знято"
    assert merged[3] == "" and len(merged) == 4
    meta = json.loads((reg.merge_dir(reg.load("demo")) / S.META_FILE).read_text(encoding="utf-8"))
    conf = meta["pages"]["0001"]["conf"]
    assert conf["1"] == "low" and conf["2"] == "low" and conf["0"] == "high"
    spec = reg.load("demo")
    assert spec.merge() is not None
    assert reg.stats("demo")["n_merged"] == 6
    assert any("маркери" in w for w in rep.warnings)
    assert any("белькіт" in w for w in rep.warnings)
    # злиття не є голосом для наступного експорту
    rep2 = T.export_tasks("demo", only_missing=True, ws=space, image_of=_img, sheets=False)
    assert rep2.rows == 1 and "0002:1" in rep2.files[0].read_text(encoding="utf-8")
    assert "  C:" not in rep2.files[0].read_text(encoding="utf-8")
    # другий захід доливає, а не затирає
    (tasks / "demo_part02.answer.json").write_text(json.dumps(
        {"0002:1": {"m": "Анна Ѳедорова", "c": "med"}}, ensure_ascii=False), encoding="utf-8")
    rep3 = T.import_answers("demo", ws=space)
    assert rep3.rows == 7
    merged2 = (reg.merge_dir(spec) / "0002.txt").read_text(encoding="utf-8").splitlines()
    assert merged2 == ["Иванъ Петровъ", "Анна Ѳедорова", "Дьячокъ Ѳадоръ"]
    sus = T.suspects_of("demo", ws=space)
    assert all(s["page"] in ("0001", "0002") for s in sus)


def test_parse_answer_survives_truncation_and_fences() -> None:
    raw = '```json\n{"0001:0": {"m": "текст \\"з лапками\\"", "c": "high"}, "0001:1": {"m": "обірв'
    got = T.parse_answer(raw)
    assert got == {"0001:0": {"m": 'текст "з лапками"', "c": "high"}}
    assert T.parse_answer('{"a:1": {"m": "x", "c": "low"}}') == {"a:1": {"m": "x", "c": "low"}}


def test_spelling_split_between_files() -> None:
    got = G.spelling_splits(["Ѳедоръ"], {"a.json": {"1": "Священникъ Ѳедоръ"},
                                         "b.json": {"2": "Священникъ Ѳадоръ"}})
    assert got and set(got[0]["forms"]) == {"Ѳедоръ", "Ѳадоръ"}
    assert not G.spelling_splits(["Ѳедоръ"], {"a.json": {"1": "Ѳедоръ"}, "b.json": {"2": "Ѳедоръ"}})


# ── аркуші ───────────────────────────────────────────────────────────────────
def test_bands_use_an_anchor_not_a_chain() -> None:
    # A–B перекриваються на 62%, B–C на 62%, а A–C лише на 25%: ланцюг злив би
    # всі три в одну смугу, якір дає дві.
    boxes = [[0, 0, 100, 40], [0, 15, 100, 55], [0, 30, 100, 70]]
    assert len(set(SH.bands(boxes).values())) == 2


def test_sheet_tiles_big_pages_and_caps_boxes(tmp_path: Path) -> None:
    im = Image.new("RGB", (4000, 3000), "white")
    boxes = [[100, 50 + i * 60, 3900, 100 + i * 60] for i in range(45)]
    files, note = SH.render_sheet(im, boxes, tmp_path, "big")
    assert len(files) > 1 and "тайлів" in note
    small = Image.new("RGB", (800, 600), "white")
    files, note = SH.render_sheet(small, boxes[:5], tmp_path, "small")
    assert files == [tmp_path / "small.png"] and "одним аркушем" in note


# ── дивилка ──────────────────────────────────────────────────────────────────
def test_view_strip_zoom_ctx(space: W.Workspace) -> None:
    s = V.strip("demo", "0001", [0, 1, 9], ws=space)
    assert s.width > 0 and "немає: [9]" in s.note and s.data_url.startswith("data:image/png")
    z = V.zoom("demo", "0001", 0, frm=0.0, to=0.25, k=2.0, ws=space)
    assert "на 8 літер" in z.note
    c = V.ctx("demo", "0001", 0, pad=20, ws=space, image_of=_img)
    assert c.width > 0 and "рамка" in c.note
    with pytest.raises(V.ViewError):
        V.zoom("demo", "0001", 42, ws=space)


def test_ops_glossary_export_import_round_trip(space: W.Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka.htr import view as VW

    monkeypatch.setattr(VW, "_page_image", _img)
    env = O.call("train.glossary", {"name": "demo", "add": "Ходъ", "why": "титул"})
    assert env.ok and "Ходъ" in env.data["glossary"]
    env = O.call("train.export", {"name": "demo", "pages_per_file": 3})
    assert env.ok and env.data["rows"] == 7 and any(n.op == "train.import" for n in env.next)
    assert not O.call("train.import", {"name": "demo"}).ok, "без відповідей — відмова"
    reg = S.registry(space)
    (reg.set_dir("demo") / T.TASKS_DIR / "demo_part01.answer.json").write_text(
        json.dumps({"0001:0": {"m": "Николай Ивановъ сынъ", "c": "high"}}), encoding="utf-8")
    env = O.call("train.import", {"name": "demo"})
    assert env.ok and env.data["rows"] == 1
    env = O.call("train.gates", {"name": "demo", "suspects": True, "gt": True})
    assert env.ok and "suspects" in env.data and env.data["gt_shifted"] == []
    env = O.call("train.sheets", {"name": "demo", "pages": "0002"})
    assert env.ok and "0002" in env.data["pages"]
    env = O.call("train.view", {"name": "demo", "page": "0001", "mode": "strip", "lines": "0-1"})
    assert env.ok and env.data["image"].startswith("data:image/png")
