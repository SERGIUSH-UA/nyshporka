"""Реєстр наборів: опис, мітки, кропи, голоси з прогону, зведення."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from nyshporka.train import sets as S


def _crop(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (120, 32), 255).save(path)


@pytest.fixture
def reg(tmp_path: Path) -> S.Registry:
    htr = tmp_path / "reports" / "htr"
    run = htr / "demo-run"
    run.mkdir(parents=True)
    (run / "_htr_meta.json").write_text('{"pages": {"0001": {}}}', encoding="utf-8")
    (run / "0001.txt").write_text("перший\nдругий\nтретій\n", encoding="utf-8")
    r = S.Registry(tmp_path / "data" / "train", htr_reports=htr)
    spec = S.SetSpec(name="demo", title="проба", source_run="demo-run",
                     drafts=[S.Draft(id="pysar", run="demo-run"),
                             S.Draft(id="merge", dir="drafts/merge")])
    r.save(spec)
    for i in range(3):
        _crop(r.crops_of(spec) / "0001" / f"line_{i:03d}.png")
    return r


def test_spec_roundtrip_and_name_is_the_folder(reg: S.Registry) -> None:
    spec = reg.load("demo")
    assert spec.title == "проба" and spec.role == "train"
    assert [d.id for d in spec.drafts] == ["pysar", "merge"]
    raw = json.loads(reg.spec_path("demo").read_text(encoding="utf-8"))
    raw["name"] = "чуже"
    reg.spec_path("demo").write_text(json.dumps(raw), encoding="utf-8")
    assert reg.load("demo").name == "demo", "ім'я — тека, а не поле"


def test_bad_names_are_refused(reg: S.Registry) -> None:
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(S.SetError):
            reg.set_dir(bad)
    with pytest.raises(S.SetError):
        reg.save(S.SetSpec(name="x", role="test"))


def test_voices_never_include_the_merge(reg: S.Registry) -> None:
    spec = reg.load("demo")
    assert [d.id for d in spec.voices()] == ["pysar"]
    assert spec.merge() is not None and spec.merge().dir == "drafts/merge"


def test_marks_are_append_only_and_last_wins(reg: S.Registry) -> None:
    reg.append_mark("demo", "0001", 1, "Ивановъ ‹а|б›", "ok", draft="Ивановь", secs=3.2)
    reg.append_mark("demo", "0001", 1, "Ивановъ а", "unsure")
    marks = reg.marks("demo")
    assert marks[("0001", 1)]["status"] == "unsure"
    assert marks[("0001", 1)]["text"] == "Ивановъ а"
    lines = reg.marks_path("demo").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "історія правок не зберігається"
    first = json.loads(lines[0])
    assert first["text"] == "Ивановъ а", "маркер розбіжності протік у мітку"
    assert first["by"] == "eye" and first["secs"] == 3.2
    with pytest.raises(S.SetError):
        reg.append_mark("demo", "0001", 0, "x", "maybe")
    with pytest.raises(S.SetError):
        reg.append_mark("demo", "0001", 0, "x", "ok", kind="photo")


def test_crops_counted_from_disk_and_any_index_width(reg: S.Registry) -> None:
    spec = reg.load("demo")
    assert reg.crop_pages(spec) == {"0001": 3}
    assert reg.crop_path(spec, "0001", 2) is not None
    _crop(reg.crops_of(spec) / "0002" / "line_0007.png")
    assert reg.crop_path(spec, "0002", 7) is not None
    assert reg.crop_path(spec, "0002", 8) is None
    assert reg.crop_path(spec, "../0001", 0) is None


def test_draft_text_comes_from_the_run_without_copy(reg: S.Registry) -> None:
    spec = reg.load("demo")
    voice = spec.voices()[0]
    assert reg.draft_lines(spec, voice, "0001") == ["перший", "другий", "третій"]
    assert reg.draft_lines(spec, voice, "0002") is None
    assert reg.run_dir("../demo-run") is None and reg.run_dir("нема") is None


def test_stats_are_denominators_not_self_report(reg: S.Registry) -> None:
    md = reg.merge_dir(reg.load("demo"))
    md.mkdir(parents=True)
    (md / "0001.txt").write_text("перший\n\nтретій\n", encoding="utf-8")
    (md / "_meta.json").write_text(json.dumps(
        {"version": 1, "pages": {"0001": {"conf": {"0": "high", "2": "low"}}}}),
        encoding="utf-8")
    reg.append_mark("demo", "0001", 0, "перший", "ok")
    st = reg.stats("demo")
    assert st["n_crops"] == 3 and st["n_pages"] == 1 and st["crops_present"]
    assert st["n_marked"] == 1 and st["by_status"]["ok"] == 1
    assert st["merge"] == {"high": 1, "med": 0, "low": 1} and st["n_merged"] == 2
    assert st["voices"] == ["pysar"]


def test_names_hide_hidden_sets_unless_asked(reg: S.Registry) -> None:
    reg.save(S.SetSpec(name="secret", hidden=True))
    assert reg.names() == ["demo"]
    assert reg.names(hidden=True) == ["demo", "secret"]
    assert reg.exists("demo") and not reg.exists("nope")


def test_ops_sets_warns_about_marks_without_crops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka.core import workspace as W

    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test", preset="lab"))
    try:
        reg = S.registry()
        reg.save(S.SetSpec(name="lost"))
        reg.append_mark("lost", "0001", 0, "текст", "ok")
        env = O.call("train.sets", {})
        assert env.ok and env.data["n"] == 1
        assert any(w.code == "crops_missing" for w in env.warnings)
        env = O.call("train.sets", {"name": "nope"})
        assert not env.ok
        env = O.call("train.doctor", {})
        assert env.ok and env.data["sets"]["without_crops"] == ["lost"]
    finally:
        W.reset()
