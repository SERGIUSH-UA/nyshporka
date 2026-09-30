"""`nysh queue` у командному рядку й перевірка доктора.

Відповіді операцій стережуть `test_queue.py` і `test_queue_stages.py`; тут —
те, що бачить людина: таблиця, причина зупинки, команда «що далі».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _cherha import drop_space, frames, make_space
from typer.testing import CliRunner

runner = CliRunner()

Q: Any = None
APP: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    global Q, APP
    from nyshporka.cli import app
    from nyshporka.queue import state

    Q, APP = state, app
    yield tmp_path
    drop_space()


def test_hrupa_vydna_v_dovidtsi(space: Path) -> None:
    res = runner.invoke(APP, ["--help"])
    assert "queue" in res.output
    res = runner.invoke(APP, ["queue", "--help"])
    for cmd in ("add", "run", "start", "stop", "retry", "set", "drop"):
        assert cmd in res.output


def test_porozhnia_cherha_kazhe_yak_dodaty(space: Path) -> None:
    res = runner.invoke(APP, ["queue"])

    assert res.exit_code == 0, res.output
    assert "черга порожня" in res.output and "nysh queue add" in res.output


def test_perelik_pokazuie_prychynu_i_komandu(space: Path) -> None:
    d = frames(space, "inshe/skany")
    res = runner.invoke(APP, ["queue", "add", str(d)])
    assert res.exit_code == 0, res.output
    assert "шифр" in res.output          # тека без шифри — сказано одразу при додаванні

    with Q.edit() as q:
        Q.settle(q["items"][0], Q.BLOCKED, stage="passport", code="no_passport",
                 why="паспорта немає, а з імені теки шифру не зібрати",
                 fix='nysh case "data/raw/inshe/skany" --shifra "<архів фонд-опис-справа>"')
    res = runner.invoke(APP, ["queue"])

    assert res.exit_code == 0, res.output
    assert "чекає вас" in res.output and "паспорта немає" in res.output
    assert "nysh case" in res.output and "0/3" in res.output
    assert "ніхто не веде" in res.output


def test_json_viddaie_povnyi_konvert(space: Path) -> None:
    d = frames(space, "inshe/skany")
    runner.invoke(APP, ["queue", "add", str(d)])

    res = runner.invoke(APP, ["queue", "--json"])

    env = json.loads(res.output)
    assert env["ok"] and env["data"]["rows"][0]["frames"] == 3
    assert [s["stage"] for s in env["data"]["rows"][0]["stages"]] == [
        "fetch", "passport", "catalog", "pool", "read", "books", "share"]


def test_run_na_porozhnii_cherzi_nichoho_ne_robyt(space: Path) -> None:
    res = runner.invoke(APP, ["queue", "run"])

    assert res.exit_code == 0, res.output
    assert "проведено справ: 0" in res.output


def test_run_pry_zhyvomu_vykonavtsi_vidmovliaie(space: Path) -> None:
    with Q.own():
        res = runner.invoke(APP, ["queue", "run"])

    assert res.exit_code == 1 and "вже веде" in res.output


def test_set_retry_drop_z_riadka(space: Path) -> None:
    d = frames(space, "inshe/skany")
    runner.invoke(APP, ["queue", "add", str(d)])

    assert runner.invoke(APP, ["queue", "set", "skany", "--pool", "read",
                               "--script", "latin", "--no-share"]).exit_code == 0
    assert Q.load()["items"][0]["opts"] == {"pool": "read", "share": False,
                                            "script": "latin"}
    assert runner.invoke(APP, ["queue", "retry", "--all"]).exit_code == 0
    assert runner.invoke(APP, ["queue", "drop", "skany", "--why", "не та"]).exit_code == 0
    assert Q.load()["items"][0]["state"] == Q.DROPPED
    assert runner.invoke(APP, ["queue", "drop", "skany"]).exit_code == 1


# ── доктор ───────────────────────────────────────────────────────────────────

def test_doktor_kazhe_pro_cherhu(space: Path) -> None:
    from nyshporka.setup import doctor as D

    assert D._queue in D.CHECKS
    assert D._queue().detail == "черга порожня"

    with Q.edit() as q:
        q["items"] += [Q.new_item("s1", {"dir": "x"}, {}), Q.new_item("s2", {"dir": "y"}, {})]
    got = D._queue()
    assert got.level == "ok" and "у черзі 2" in got.detail and "nysh queue run" in got.fix

    with Q.edit() as q:
        Q.settle(q["items"][0], Q.BLOCKED, stage="passport", why="шифри немає")
    got = D._queue()
    assert got.level == "warn" and "чекає вашого рішення: 1" in got.detail

    with Q.edit() as q:
        Q.settle(q["items"][1], Q.RUNNING, stage="read")
    got = D._queue()
    assert got.level == "warn" and "обірвано на справі «s2»" in got.detail
    with Q.own():
        assert "обірвано" not in D._queue().detail
