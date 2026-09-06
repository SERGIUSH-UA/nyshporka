"""Нарізка кропів із прогону: полігон-фолбек, мета, автовідбір, голоси."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from nyshporka.core import workspace as W
from nyshporka.train import cut as C
from nyshporka.train import sets as S
from nyshporka.train import voices as V

PAGE_W, PAGE_H = 400, 300


def _page_image(dark_rows: list[tuple[int, int]]) -> Image.Image:
    im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    d = ImageDraw.Draw(im)
    for y0, y1 in dark_rows:
        d.rectangle((20, y0, PAGE_W - 20, y1), fill="black")
    return im


def _make_run(htr: Path, name: str, pages: dict[str, list[str]], *, geometry: bool = True,
              model: str = "pysar_cyr_v17.pt", chars_of: dict[str, int] | None = None) -> None:
    d = htr / name
    d.mkdir(parents=True)
    meta_pages = {}
    for pg, lines in pages.items():
        (d / f"{pg}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        boxes = [[20, 10 + i * 40, PAGE_W - 20, 40 + i * 40] for i in range(len(lines))]
        polys = [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]] for b in boxes]
        if geometry:
            (d / f"{pg}.lines.json").write_text(
                json.dumps({"size": [PAGE_W, PAGE_H], "boxes": boxes, "polys": polys}),
                encoding="utf-8")
        meta_pages[pg] = {"orient": 0, "lines": len(lines),
                          "chars": (chars_of or {}).get(pg, sum(len(x) for x in lines))}
    (d / "_htr_meta.json").write_text(json.dumps(
        {"pages": meta_pages, "model": model, "script": "cyrillic", "case_key": "T/1-2-3",
         "case_dir": ""}), encoding="utf-8")


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    htr = ws.htr_reports
    _make_run(htr, "r1", {"0001": ["а", "б", "в"], "0002": ["г", "д"]})
    _make_run(htr, "r1-diak", {"0001": ["А", "Б", "В"], "0002": ["Г", "Д"]},
              geometry=False, model="diak_cyr_v4.mlmodel")
    _make_run(htr, "r-bad", {"0001": ["x", "y"], "0002": ["z", "w"]}, geometry=False)
    yield ws
    W.reset()


def _images(run: str, page: str) -> Image.Image:
    n = 3 if page == "0001" else 2
    return _page_image([(10 + i * 40, 40 + i * 40) for i in range(n)])


def test_poly_cut_writes_one_crop_per_line_and_meta(space: W.Workspace) -> None:
    rep = C.make_set("r1", "demo", pages=["0001", "0002"], title="проба",
                     prefer_engine=False, ws=space, image_of=_images)
    assert rep.n_lines == 5 and not any(p.error for p in rep.pages)
    reg = S.registry(space)
    spec = reg.load("demo")
    assert spec.source_run == "r1" and spec.case == "T/1-2-3"
    assert [d.id for d in spec.drafts] == ["pysar_cyr_v17"]
    assert reg.crop_pages(spec) == {"0001": 3, "0002": 2}
    meta = reg.cut_meta(spec)
    assert meta["version"] == 3 and meta["pages"]["0001"]["crop_source"] == "poly"
    assert len(meta["pages"]["0001"]["boxes"]) == 3
    with Image.open(reg.crop_path(spec, "0001", 1)) as im:
        assert im.size == (PAGE_W - 40, 30)
        # полігон — маска: усередині рядок чорний, тобто кроп узято з того місця
        assert im.getpixel((im.width // 2, im.height // 2)) == (0, 0, 0)
    assert any("полігоном" in w for w in rep.warnings)


def test_recut_appends_pages_and_refuses_another_run(space: W.Workspace) -> None:
    C.make_set("r1", "demo", pages=["0001"], prefer_engine=False, ws=space, image_of=_images)
    C.make_set("r1", "demo", pages=["0002"], prefer_engine=False, ws=space, image_of=_images)
    reg = S.registry(space)
    assert set(reg.cut_meta(reg.load("demo"))["pages"]) == {"0001", "0002"}
    with pytest.raises(C.CutError, match="інший прогін"):
        C.make_set("r-bad", "demo", pages=["0001"], prefer_engine=False, ws=space,
                   image_of=_images)


def test_missing_geometry_and_unknown_pages_are_named(space: W.Workspace) -> None:
    with pytest.raises(C.CutError, match="не має сторінок"):
        C.make_set("r1", "x", pages=["0009"], prefer_engine=False, ws=space, image_of=_images)
    rep = C.make_set("r-bad", "nogeo", pages=["0001"], prefer_engine=False, ws=space,
                     image_of=_images)
    assert rep.n_lines == 0 and "рамок" in rep.pages[0].error
    with pytest.raises(C.CutError):
        C.make_set("r1", "y", prefer_engine=False, ws=space, image_of=_images)


def test_size_mismatch_refuses_to_cut(space: W.Workspace) -> None:
    def small(run: str, page: str) -> Image.Image:
        return Image.new("RGB", (100, 100), "white")

    rep = C.make_set("r1", "sz", pages=["0001"], prefer_engine=False, ws=space, image_of=small)
    assert rep.pages[0].error and "не збігається" in rep.pages[0].error


def test_pick_pages_prefers_dense_body_and_skips_the_head() -> None:
    pages = {f"{i:04d}": {"lines": 40, "chars": 100 + i * 10} for i in range(1, 41)}
    pages["0003"] = {"lines": 5, "chars": 30}          # титулка — не кандидат
    meta = {"pages": pages}
    got = C.pick_pages(meta, 3)
    assert len(got) == 3 and "0003" not in got
    assert all(int(p) > C.SKIP_FIRST for p in got)
    assert C.pick_pages({"pages": {"0001": {"lines": 3, "chars": 9}}}, 2) == []


def test_voice_from_run_is_taken_only_when_aligned(space: W.Workspace) -> None:
    C.make_set("r1", "demo", pages=["0001", "0002"], prefer_engine=False, ws=space,
               image_of=_images)
    rep = V.add_from_run("demo", "r1-diak", ws=space)
    assert rep.voice == "diak" and rep.pages == 2 and rep.lines == 5
    reg = S.registry(space)
    spec = reg.load("demo")
    assert [d.id for d in spec.voices()] == ["pysar_cyr_v17", "diak"]
    assert reg.draft_lines(spec, spec.voices()[1], "0001") == ["А", "Б", "В"]
    with pytest.raises(V.VoiceError, match="не вирівняний"):
        V.add_from_run("demo", "r-bad", ws=space)
    with pytest.raises(V.VoiceError, match="зарезервоване"):
        V.add_from_run("demo", "r1-diak", voice_id="merge", ws=space)


def test_ops_cut_and_voices_round_trip(space: W.Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka.htr import view as VW

    monkeypatch.setattr(VW, "_page_image", _images)
    env = O.call("train.cut", {"run": "r1", "name": "demo", "pages": "0001,0002",
                               "no_engine": True})
    assert env.ok and env.data["lines"] == 5
    assert any(n.op == "train.voices" for n in env.next)
    env = O.call("train.voices", {"name": "demo", "from_run": "r1-diak"})
    assert env.ok and env.data["voices"] == ["pysar_cyr_v17", "diak"]
    assert any(n.op == "train.export" for n in env.next)
    assert not O.call("train.voices", {"name": "demo"}).ok
    env = O.call("train.sets", {"name": "demo"})
    assert env.data["sets"][0]["n_crops"] == 5
