"""Черга розмітки: розбіжність голосів, режими, порожні кропи, мітки, зведення."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import sets as S
from nyshporka.train import store as ST

PAGE_W, PAGE_H = 600, 400
VOICE_A = {"0001": ["Николай Ивановъ сынъ Петровъ", "Марѳа Васильева дочь", "2 2",
                    "АГо ввілн ~~~~~~~~~~~~", "", "Приходскій Священникъ Ѳеодоръ Осиповъ",
                    "Иванъ Петровъ 45", "Село Ходъ"],
           "0002": ["Приходскій Священникъ Ѳеодоръ Осиповъ", "Анна Ѳедорова дочь Иванова",
                    "Дьячокъ Ѳедоръ", "Счетъ мѣсяцъ и день", ""]}
VOICE_B = {"0001": ["Николай Иванов сынь Петров", "Марфа Васильева дочь", "2",
                    "АГо ввілн ~~~~~~~~", "", "Приходский Священник Феодор Осипов",
                    "Иван Петров 45", "Село Ходь"],
           "0002": ["Приходский Священник Феодор Осипов", "Анна Федорова дочь Иванова",
                    "Дьячок Федор", "Счет месяц и день", ""]}


def _crop(path: Path, ink: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("L", (PAGE_W - 80, 40), 255)
    if ink:
        d = ImageDraw.Draw(im)
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
    for run, lines in (("r1", VOICE_A), ("r1-diak", VOICE_B)):
        d = htr / run
        d.mkdir(parents=True)
        for pg, ls in lines.items():
            (d / f"{pg}.txt").write_text("\n".join(ls) + "\n", encoding="utf-8")
        (d / "_htr_meta.json").write_text(json.dumps(
            {"pages": {pg: {"orient": 0, "lines": len(ls)} for pg, ls in lines.items()},
             "model": "pysar_cyr_v17.pt"}), encoding="utf-8")
    reg = S.registry(ws)
    spec = S.SetSpec(name="demo", source_run="r1",
                     drafts=[S.Draft(id="pysar", run="r1"), S.Draft(id="diak", run="r1-diak")])
    reg.save(spec)
    meta = {"version": 3, "source_run": "r1", "pages": {}}
    for pg, ls in VOICE_A.items():
        boxes = [[40, 20 + i * 40, PAGE_W - 40, 55 + i * 40] for i in range(len(ls))]
        for i in range(len(ls)):
            _crop(reg.crops_of(spec) / pg / f"line_{i:03d}.png", ink=bool(ls[i]))
        meta["pages"][pg] = {"n_lines": len(ls), "size": [PAGE_W, PAGE_H], "orient": 0,
                             "boxes": boxes, "polys": [None] * len(ls)}
    (reg.crops_of(spec) / S.CUT_META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    yield ws
    W.reset()


def test_usefulness_weights_length_and_punishes_loops() -> None:
    assert ST.usefulness(["2 2", "2"]) < 20, "однознакові уламки не лізуть угору"
    assert ST.usefulness(["АГо ввілн ~~~~~~~~~~~~", "АГо ввілн ~~~~~~~~"]) < 25
    agree = ST.usefulness(["Николай Ивановъ сынъ Петровъ"] * 2)
    differ = ST.usefulness(["Николай Ивановъ сынъ Петровъ", "Микола Иваненко сынъ Пет"])
    assert agree == 0 and differ > 20
    assert ST.usefulness(["Николай Ивановъ сынъ Петровъ"]) == 50.0, "нема з чим порівняти"


def test_name_score_wants_names_not_formula() -> None:
    assert ST.name_score(["Счетъ мѣсяцъ и день рожденія"]) == 0
    assert ST.name_score(["Иванъ Петровъ 45"]) == 0, "коротше за NAME_MIN_LEN"
    assert ST.name_score(["Николай Ивановъ сынъ Петровъ"]) >= 55
    assert ST.name_score(["Книга Метричная Данная Подольской губерніи"]) == 0


def test_dedupe_keeps_two_signatures_at_most() -> None:
    items = [{"drafts": [f"Діаконъ Ѳеодоръ Михальскій {i % 2}"]} for i in range(6)]
    assert len(ST.dedupe_similar(items)) == 2


def test_spread_goes_round_pages_and_hides_blank(space: W.Workspace) -> None:
    st = ST.Store("demo", ws=space)
    q = st.queue("spread")
    pages = [it["page"] for it in q["items"]]
    assert set(pages) == {"0001", "0002"}
    assert "0001" in pages[:6] and "0002" in pages[:12], "блоки з різних сторінок по колу"
    keys = {(it["page"], it["idx"]) for it in q["items"]}
    assert ("0001", 4) not in keys and ("0002", 4) not in keys, "порожні сховані"
    assert q["n_total"] == 13 and q["n_done"] == 0 and q["draft_srcs"] == ["pysar", "diak"]
    q2 = st.queue("spread", include_blank=True)
    assert ("0001", 4) in {(it["page"], it["idx"]) for it in q2["items"]}
    q3 = st.queue("page", page="0002")
    assert [it["idx"] for it in q3["items"]] == [0, 1, 2, 3]
    # Іменна черга пропускає сторінки, коротші за поріг (титул, порожній
    # аркуш): у фікстурі всі такі, тож вона порожня — і це не помилка.
    q4 = st.queue("names")
    assert q4["items"] == [] and q4["n_queue"] == 0


def test_set_without_voices_still_queues(space: W.Workspace) -> None:
    reg = S.registry(space)
    spec = reg.load("demo")
    spec.drafts = []
    reg.save(spec)
    st = ST.Store("demo", ws=space)
    q = st.queue("sequential")
    assert q["n_queue"] == 13, "свіжа нарізка без голосів не виглядає як «нема чого розмічати»"


def test_save_is_append_only_and_queue_skips_done(space: W.Workspace) -> None:
    st = ST.Store("demo", ws=space)
    st.save("0001", 0, "Николай Ивановъ сынъ ‹Петровъ|Петров›", "ok", draft="x", secs=3.4)
    st.save("0001", 0, "Николай Ивановъ сынъ Петровъ", "ok", draft="x", secs=1.0)
    lines = st.reg.marks_path("demo").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["text"].count("‹") == 0
    q = st.queue("sequential")
    assert ("0001", 0) not in {(it["page"], it["idx"]) for it in q["items"]}
    assert q["n_done"] == 1
    line = st.line("0001", 0)
    assert line["saved"]["status"] == "ok" and line["image"].startswith("data:image/png")
    assert [c["cur"] for c in line["context"]] == [True, False, False]
    with pytest.raises(S.SetError):
        st.line("0001", 42)


def test_stats_and_suggest(space: W.Workspace) -> None:
    st = ST.Store("demo", ws=space)
    st.save("0001", 0, "Николай Ивановъ сынъ Петровъ", "ok", secs=4)
    st.save("0001", 1, "Марѳа Васильева дочь", "ok", secs=2)
    st.save("0001", 2, "", "skip")
    d = st.stats()
    assert d["n_done"] == 3 and d["by_status"] == {"ok": 2, "skip": 1}
    assert d["cer_draft"] == 0.0 and d["cer_lines"] == 2 and d["median_secs"] == 3.0
    assert d["eta_min"] is not None and d["n_left"] == 10
    st.save("0002", 1, "Анна Ѳедорова дочь Иванова", "ok")
    st.save("0002", 2, "Дьячокъ Ѳедоръ Осиповъ", "ok")
    assert st.stats()["cer_draft"] > 0
    assert st.suggest("ма") == ["Марѳа Васильева дочь"]
    assert st.suggest("м") == []


def test_page_image_carries_boxes(space: W.Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.htr import view as VW

    monkeypatch.setattr(VW, "_page_image", lambda run, page: Image.new("RGB", (PAGE_W, PAGE_H), "white"))
    st = ST.Store("demo", ws=space)
    got = st.page_image("0001", 1800)
    assert got["image"].startswith("data:image/jpeg") and got["size"] == [PAGE_W, PAGE_H]
    assert set(got["boxes"]) == {str(i) for i in range(8)}
    assert (st.reg.set_dir("demo") / ST.PAGEVIEW_DIR / "0001_1800.jpg").is_file()


def test_ops_queue_line_save_stats(space: W.Workspace) -> None:
    from nyshporka import ops as O

    env = O.call("train.queue", {"name": "demo"})
    assert env.ok and env.data["n_queue"] > 0
    it = env.data["items"][0]
    env = O.call("train.line", {"name": "demo", "page": it["page"], "idx": it["idx"]})
    assert env.ok and env.data["drafts"]
    env = O.call("train.save", {"name": "demo", "page": it["page"], "idx": it["idx"],
                                "text": "текст", "status": "ok", "secs": 1.5})
    assert env.ok and env.data["rec"]["by"] == "eye"
    assert not O.call("train.save", {"name": "demo", "page": it["page"], "idx": it["idx"],
                                     "text": "x", "status": "maybe"}).ok
    env = O.call("train.stats", {"name": "demo"})
    assert env.ok and env.data["n_done"] == 1 and any(w.code == "cer_small" for w in env.warnings)
    assert O.call("train.suggest", {"name": "demo", "q": "те"}).data["items"] == ["текст"]
    assert not O.call("train.queue", {"name": "nope"}).ok
