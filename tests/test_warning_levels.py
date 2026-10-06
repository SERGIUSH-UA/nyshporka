"""🔕 Рівні попереджень: тривогою — лише те, що ламає читання чи висновок.

Доти рівня не було, і консоль малювала жовтою плашкою кожне попередження: на
головному екрані їх стояло сім — облік, порада новачкові, фраза до агента й
хибне «читання не запуститься» на машині, яка щойно читала справу.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka.core.envelope import ALERT, NOTE, Envelope


def test_default_is_a_note_and_level_travels() -> None:
    env = Envelope().warn("x", "облік")
    assert env.warnings[0].level == NOTE
    assert env.as_dict()["warnings"] == [{"code": "x", "text": "облік", "level": NOTE}]
    assert Envelope().warn("y", "ламає", ALERT).as_dict()["warnings"][0]["level"] == ALERT


def test_agent_text_still_gets_every_warning() -> None:
    """Термінал і агент бачать усе — рівень стосується лише консолі."""
    env = Envelope().warn("a", "агентові", "agent").warn("n", "примітка")
    text = env.as_agent_text()
    assert "агентові" in text and "примітка" in text


def _setup(monkeypatch: pytest.MonkeyPatch, levels: list[str]) -> Envelope:
    from nyshporka.core.ops import NoArgs
    from nyshporka.ops_builtin import setup_check
    from nyshporka.setup import doctor, sample

    monkeypatch.setattr(doctor, "run", lambda: [
        doctor.Check(name=f"п{k}", level=lv, detail="") for k, lv in enumerate(levels)])
    monkeypatch.setattr(sample, "installed", lambda _ws: True)
    return setup_check(NoArgs())


def test_a_yellow_item_does_not_claim_reading_will_not_start(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 «Про новішу версію не питали» — не причина казати «не запуститься»."""
    env = _setup(monkeypatch, ["ok", "warn"])
    assert not [w for w in env.warnings if w.code == "not_ready"]


def test_a_real_failure_is_an_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _setup(monkeypatch, ["ok", "fail"])
    got = [w for w in env.warnings if w.code == "not_ready"]
    assert got and got[0].level == ALERT


def test_migration_nag_is_for_the_agent_only(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import migrate as M

    monkeypatch.setattr(M, "pending", lambda _root, _v: [
        M.Migration(version="9.9", title="t", body="", stale=[], steps=[])])
    env = Envelope()
    M.nag(env, tmp_path)
    assert env.warnings and all(w.level == "agent" for w in env.warnings)
    assert env.next and all(n.level == "agent" for n in env.next)


@pytest.mark.parametrize(("levels", "ready"), [(["ok", "warn"], True), (["ok", "fail"], False)])
def test_home_machine_step_is_red_only_on_failure(monkeypatch: pytest.MonkeyPatch,
                                                 levels: list[str], ready: bool) -> None:
    """Крок «Машина читає рукопис» на головній — та сама вада, що й `not_ready`."""
    import nyshporka.ops_builtin as ob
    from nyshporka.setup import doctor

    monkeypatch.setattr(doctor, "run", lambda: [
        doctor.Check(name=f"п{k}", level=lv, detail="") for k, lv in enumerate(levels)])
    monkeypatch.setitem(ob._MACHINE, "data", None)
    got = ob._pulse_machine()
    assert got["ready"] is ready
    assert got["bad"] == ([] if ready else ["п1"])
