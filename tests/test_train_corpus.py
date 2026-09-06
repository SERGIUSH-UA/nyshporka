"""Рецепти, джерела, збірник корпусу — на синтетичних кропах."""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from PIL import Image

from nyshporka.core import workspace as W
from nyshporka.train import corpus as C
from nyshporka.train import recipes as R
from nyshporka.train import sets as S
from nyshporka.train import sources as SRC


def _crop(path: Path, w: int = 300, h: int = 40) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (w, h), 200).save(path)


@pytest.fixture
def space(tmp_path: Path) -> W.Workspace:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\npreset = "lab"\n',
                                     encoding="utf-8")
    ws = W.Workspace(root=tmp_path, name="t", origin="test", preset="lab")
    W.use(ws)
    reg = S.registry(ws)
    for name, role in (("a", "train"), ("h", "holdout")):
        spec = S.SetSpec(name=name, role=role, drafts=[S.Draft(id="merge", dir="drafts/merge")])
        reg.save(spec)
        md = reg.merge_dir(spec)
        md.mkdir(parents=True)
        lines = ["Николай Ивановъ сынъ", "Марѳа Васильева дочь", "по тому объ обу объ",
                 "Званіе, имя, отчество", "Іоаннъ Петровъ"]
        (md / "0001.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (md / "_meta.json").write_text(json.dumps(
            {"version": 1, "pages": {"0001": {"conf": {"0": "high", "1": "med", "2": "med",
                                                       "3": "high", "4": "low"}}}}),
            encoding="utf-8")
        for i in range(5):
            _crop(reg.crops_of(spec) / "0001" / f"line_{i:03d}.png")
        reg.append_mark(name, "0001", 0, "Николай Ивановъ сынъ", "ok")
        reg.append_mark(name, "0001", 1, "Марѳа Васильева дочь", "ok")
        reg.append_mark(name, "0001", 1, "Марѳа Васильева дочь.", "ok")   # last wins
        reg.append_mark(name, "0001", 4, "Іоаннъ", "unsure")
    # зовнішнє джерело: manifest
    ext = tmp_path / "ext"
    for i in range(6):
        _crop(ext / "img" / f"{i}.png")
    (ext / "gt_train.txt").write_text(
        "\n".join(f"img/{i}.png\tзовнішній рядок номер {i} досить довгий" for i in range(6)) + "\n",
        encoding="utf-8")
    (tmp_path / "config" / "train").mkdir(parents=True)
    (tmp_path / "config" / "train" / "sources.yaml").write_text(
        f"version: 1\nsources:\n  ext:\n    kind: manifest\n    path: \"{ext.as_posix()}\"\n"
        f"    unify_i: true\n", encoding="utf-8")
    yield ws
    W.reset()


def _recipe(**mix: dict) -> R.Recipe:
    body = {"gt": {"cap": 0, "share": "20%"}, "pseudo": {"cap": 0, "rep": 1},
            "ext": {"cap": 0, "rep": 2}}
    body.update(mix)
    # квота 15 символів: перший рядок (20 симв.) її вичерпує, другий у val не йде
    return R.Recipe(name="t", mix=body, val={"quota_chars": {"gt": 15}, "min_len": 8},
                    pseudo={"conf_weight": {"high": 1.5}})


def test_train_params_mirror_the_job_validation() -> None:
    ours = set(R.TrainParams.model_fields)
    assert ours | R.COMPUTE_KEYS == R.JOB_PARAM_KEYS, (
        f"розійшлись: у нас зайве {ours - R.JOB_PARAM_KEYS}, "
        f"бракує {R.JOB_PARAM_KEYS - ours - R.COMPUTE_KEYS}")
    with pytest.raises(ValueError):
        R.TrainParams(min_epochs=20, epochs=10)
    with pytest.raises(ValueError):
        R.TrainParams(charset_mode="both")
    assert R.TrainParams(ddp="2").ddp == "2"


def test_package_recipes_load_and_smoke_overrides() -> None:
    book = R.load_book()
    assert {"domain", "lean", "own"} <= set(book.recipes)
    rec = R.get_recipe("own", smoke=True)
    assert rec.train.epochs == 1 and rec.train.max_steps == 80 and not rec.train.save_epochs
    rec = R.get_recipe("own", overrides={"epochs": 3})
    assert rec.train.epochs == 3
    with pytest.raises(R.RecipeError):
        R.get_recipe("нема")
    with pytest.raises(R.RecipeError):
        R.get_recipe("own", overrides={"lrr": 1})
    with pytest.raises(ValueError):
        R.Recipe(name="x", mix={"a": {"share": "60%", "cap": 0}, "b": {"share": "50%", "cap": 0}})


def test_resolve_reps_keeps_shares_and_names_the_rounding_step() -> None:
    mix = {"gt": R.MixEntry(share="10%"), "ext": R.MixEntry(rep=1)}
    reps, warn = R.resolve_reps(mix, {"gt": 100, "ext": 9000})
    assert reps == {"gt": 10, "ext": 1} and not warn
    # 0.1·1111/44 = 2.525 → rep 3, а на 9.5% уже 2.40 → rep 2: сходинка
    reps, warn = R.resolve_reps(mix, {"gt": 44, "ext": 1000})
    assert reps["gt"] == 3 and warn and "сходинка" in warn[0]
    reps, warn = R.resolve_reps({"gt": R.MixEntry(share="10%")}, {"gt": 5})
    assert reps == {"gt": 1} and warn


def test_sources_read_gt_and_pseudo_with_guards(space: W.Workspace) -> None:
    reg = S.registry(space)
    gt = SRC.read_gt(reg)
    texts = sorted(t for _, t in gt.rows)
    assert texts == ["Марѳа Васильева дочь.", "Николай Ивановъ сынъ"], "holdout або unsure протекли"
    assert len(SRC.read_gt(reg, include_unsure=True).rows) == 3
    manual = {str(p) for p, _ in SRC.read_gt(reg, include_unsure=True).rows}
    ps = SRC.read_pseudo(reg, R.PseudoOpts(conf_weight={"high": 1.5}), manual=manual)
    got = {t for _, t in ps.rows}
    # low (4), белькіт (2) і рядки з ручною міткою (0, 1, 4) виключені; h — holdout
    assert got == {"Званіе, имя, отчество"}, got
    assert list(ps.kept) == ["a"] and ps.kept["a"][0][:2] == ["0001", 3]
    assert len(ps.weight) == 1


def test_sources_external_manifest_and_bad_kind(space: W.Workspace) -> None:
    ext = SRC.load_sources(space)["ext"]
    it = SRC.read_external(ext)
    assert len(it.rows) == 6 and all("i" not in t for _, t in it.rows)
    with pytest.raises(SRC.SourceError):
        SRC.read_external(SRC.SourceSpec(id="x", kind="zip"))


def test_plan_and_build_produce_a_reproducible_tgz(space: W.Workspace) -> None:
    rec = _recipe()
    cp = C.plan(rec, ws=space)
    ids = {s.id for s in cp.per_source}
    assert ids == {"gt", "pseudo", "ext"} and cp.holdout == ["h"]
    assert cp.reps["ext"] == 2 and cp.reps["gt"] >= 1
    rep = C.build("v1", cp, ws=space)
    assert rep.rows_train > 0 and rep.failed == 0
    assert rep.rows_val == 1 and rep.val_by_source["gt"]["rows"] == 1
    with tarfile.open(rep.tgz) as tf:
        names = tf.getnames()
    assert "gt_train.txt" in names and "corpus.json" in names
    assert not any(n.endswith(".jsonl") for n in names)
    assert all(n.startswith(("images/", "gt_", "corpus.json")) for n in names)
    man = C.load_manifest("v1", ws=space)
    assert man["plan"]["holdout"] == ["h"] and man["kept"]["a"]
    assert man["recipe"]["train"]["epochs"] == rec.train.epochs
    first = (rep.out / "gt_train.txt").read_bytes()
    with pytest.raises(C.CorpusError, match="force"):
        C.build("v1", cp, ws=space)
    rep2 = C.build("v1", C.plan(rec, ws=space), ws=space, force=True)
    assert (rep2.out / "gt_train.txt").read_bytes() == first, "збірка не відтворювана"
    hist = C.charset_of(cp)
    assert hist["ъ"] > 0


def test_plan_refuses_without_sources_and_warns_on_unknown(space: W.Workspace) -> None:
    rec = R.Recipe(name="t", mix={"nope": {"cap": 0, "rep": 1}})
    with pytest.raises(C.CorpusError):
        C.plan(rec, ws=space)
    cp = C.plan(_recipe(nope={"cap": 0, "rep": 1}), ws=space)
    assert any("nope" in w for w in cp.warnings)
