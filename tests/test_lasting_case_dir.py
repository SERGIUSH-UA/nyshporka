"""Мета прогону веде на теку справи, а не на тимчасовий стейджинг.

02.10.2026: 107 мет посилались на scratchpad агента, якого вже не було, —
хмарні 74/84 ЦДІАК ф.2 (23.09) і локальний ANRM 208-1183 (08.09).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nyshporka import htr_store as S
from nyshporka import library as L


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    raw = tmp_path / "raw"
    case = raw / "cdiak_2" / "spr-84"
    stage = tmp_path / "scratchpad" / "stage84" / "pages"
    for d in (case, stage):
        d.mkdir(parents=True)
        for n in ("0001.jpg", "0002.jpg"):
            (d / n).write_bytes(b"x")
    monkeypatch.setattr(S, "_case_roots", lambda: [raw])
    row = {"key": "CDIAK/2/84", "repo": "CDIAK", "fond": "2", "opys": None, "spr": "84",
           "frames": 2, "desc_source": "source_json", "path": str(case)}
    monkeypatch.setattr(L, "load_library", lambda *a, **kw: [row])
    return {"raw": raw, "case": case, "stage": stage}


def test_a_staging_dir_gives_way_to_the_case_dir(layout: dict[str, Path]) -> None:
    got = S.lasting_case_dir(layout["stage"], "CDIAK/2/84", ["0001.jpg", "0002.jpg"])
    assert got == str(layout["case"]).replace("\\", "/")


def test_a_dir_in_the_store_stays(layout: dict[str, Path]) -> None:
    assert S.lasting_case_dir(layout["case"], "CDIAK/2/84") == str(layout["case"])


def test_other_frame_names_keep_the_given_dir(layout: dict[str, Path]) -> None:
    """Стейджинг-рендер PDF має інші імена: кроп з теки справи був би чужим аркушем."""
    names = ["0001.jpg", "p0003.jpg"]
    assert S.lasting_case_dir(layout["stage"], "CDIAK/2/84", names) == str(layout["stage"])


def test_without_a_key_there_is_nothing_to_look_up(layout: dict[str, Path]) -> None:
    assert S.lasting_case_dir(layout["stage"], "", ["0001.jpg"]) == str(layout["stage"])


def test_the_meta_and_its_voices_are_relinked(tmp_path: Path, layout: dict[str, Path]) -> None:
    runs = tmp_path / "htr"
    for name in ("cdiak_2-spr-84", "cdiak_2-spr-84-diak_v4"):
        (runs / name).mkdir(parents=True)
        (runs / name / "_htr_meta.json").write_text(json.dumps({
            "case_dir": str(layout["stage"]), "case_key": "CDIAK/2/84",
            "pages": {"0001.jpg": {}, "0002.jpg": {}}}), encoding="utf-8")
    assert S.relink_lasting(runs / "cdiak_2-spr-84") == 2
    for name in ("cdiak_2-spr-84", "cdiak_2-spr-84-diak_v4"):
        meta = json.loads((runs / name / "_htr_meta.json").read_text(encoding="utf-8"))
        assert meta["case_dir"] == str(layout["case"]).replace("\\", "/")
        assert meta["case_dir_was"] == str(layout["stage"])
    assert S.relink_lasting(runs / "cdiak_2-spr-84") == 0


def test_the_cloud_plan_carries_the_case_dir_not_the_staging(
        tmp_path: Path, layout: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Наглядач після забору пише в мету саме `case_dir` плану."""
    import types

    from nyshporka.cloud import supervised as SV

    monkeypatch.setattr(SV, "post_fetch_hooks", lambda names: [])
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"cases": [{"name": "cdiak_2-spr-84"}]}), encoding="utf-8")
    leg = types.SimpleNamespace(name="cdiak_2-spr-84", source=layout["stage"],
                                plan=types.SimpleNamespace(case_key="CDIAK/2/84"))
    SV._patch_plan(plan, types.SimpleNamespace(legs=[leg]))  # type: ignore[arg-type]
    got = json.loads(plan.read_text(encoding="utf-8"))["cases"][0]["case_dir"]
    assert got == str(layout["case"]).replace("\\", "/")


def test_frames_in_the_pages_subdir_of_the_case(layout: dict[str, Path]) -> None:
    pages = layout["case"] / "pages"
    pages.mkdir()
    for f in layout["case"].glob("*.jpg"):
        f.rename(pages / f.name)
    got = S.lasting_case_dir(layout["stage"], "CDIAK/2/84", ["0001.jpg", "0002.jpg"])
    assert got == str(pages).replace("\\", "/")
