"""📖 План читання каже, що вже лежить у теці й що з цим зробить запуск.

Раннер у теці з текстом не перечитує, а доганяє. «Читати» на повністю
прочитаній справі доти не робило нічого й нічого не казало.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nyshporka.core.envelope import ALERT, Envelope
from nyshporka.ops_builtin import _plan_existing


def _case(tmp: Path, frames: int, texts: int, model: str) -> SimpleNamespace:
    case, out = tmp / "case", tmp / "out"
    case.mkdir()
    out.mkdir()
    for k in range(1, frames + 1):
        (case / f"{k:04d}.jpg").write_bytes(b"\xff\xd8")
    for k in range(1, texts + 1):
        (out / f"{k:04d}.txt").write_text("рядок", encoding="utf-8")
    if texts:
        (out / "_htr_meta.json").write_text(json.dumps({"model": model}),
                                            encoding="utf-8")
    return SimpleNamespace(case_dir=case, out_dir=out, model=Path("pysar_cyr_v19.pt"))


def _run(p: SimpleNamespace) -> Envelope:
    env = Envelope(data={"plan": {}})
    _plan_existing(env, p)
    return env


def test_fully_read_by_an_older_model_says_nothing_will_be_read(tmp_path: Path) -> None:
    env = _run(_case(tmp_path, 3, 3, "pysar_cyr_v4.pt"))
    w = [x for x in env.warnings if x.code == "nothing_to_read"]
    assert w and w[0].level == ALERT
    assert "pysar_cyr_v4.pt" in w[0].text and "окремою текою" in w[0].text
    assert env.data["done_pages"] == 3 and env.data["prev_model"] == "pysar_cyr_v4.pt"


def test_partly_read_by_an_older_model_warns_of_a_mixed_corpus(tmp_path: Path) -> None:
    env = _run(_case(tmp_path, 3, 1, "pysar_cyr_v4.pt"))
    assert [x.code for x in env.warnings] == ["catch_up_mixed"]
    assert "дочитає лише решту (2)" in env.warnings[0].text


def test_same_model_partly_read_just_continues(tmp_path: Path) -> None:
    env = _run(_case(tmp_path, 3, 1, "pysar_cyr_v19.pt"))
    assert [x.code for x in env.warnings] == ["catch_up"]


def test_fresh_case_says_nothing(tmp_path: Path) -> None:
    env = _run(_case(tmp_path, 3, 0, ""))
    assert env.warnings == [] and env.data["done_pages"] == 0
