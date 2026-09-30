"""Черга справ: виконавець, зупинки й продовження.

Звіт користувача (29.09.2026): «що лишилось», «продовжуй», «дочитай поточну й
зупинись» — на це пакет не відповідав, і людина вела читання власним сценарієм.

⚠ Етапи тут підмінено простими: перевіряється сама черга — порядок, запис
перед дією, три класи зупинки, продовження після обриву. Справжні етапи —
у `test_queue_stages.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _cherha import drop_space, make_space

Q: Any = None
R: Any = None
ST: Any = None


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    global Q, R, ST
    from nyshporka.queue import runner, stages, state

    Q, R, ST = state, runner, stages
    yield tmp_path
    drop_space()


class Etapy:
    """Три прості етапи: «зроблено» — це позначка в словнику, як на диску."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.done: set[tuple[str, str]] = set()
        self.ran: list[tuple[str, str]] = []
        self.answers: dict[tuple[str, str], list[Any]] = {}
        self.hooks: dict[tuple[str, str], Any] = {}
        stages = tuple(self._stage(n) for n in ("a", "b", "c"))
        monkeypatch.setattr(ST, "STAGES", stages)
        monkeypatch.setattr(ST, "TITLES", {s.name: s.title for s in stages})

    def _stage(self, name: str) -> Any:
        def done(item: dict[str, Any], ctx: Any) -> bool:
            return (item["id"], name) in self.done

        def run(item: dict[str, Any], ctx: Any) -> Any:
            at = (item["id"], name)
            self.ran.append(at)
            if at in self.hooks:
                got = self.hooks[at](item, ctx)
                if got is not None:
                    return got
            queue = self.answers.get(at)
            if queue:
                return queue.pop(0)
            self.done.add(at)
            return ST.ok()

        return ST.Stage(name, f"етап {name}", done, run)


@pytest.fixture
def etapy(space: Path, monkeypatch: pytest.MonkeyPatch) -> Etapy:
    return Etapy(monkeypatch)


def _add(*ids: str, **opts: Any) -> None:
    with Q.edit() as q:
        for i in ids:
            q["items"].append(Q.new_item(i, {"dir": i}, dict(opts)))


def _state(item_id: str) -> dict[str, Any]:
    return next(it for it in Q.load()["items"] if it["id"] == item_id)


def _run(**kw: Any) -> dict[str, Any]:
    return R.run(say=lambda _t: None, **kw)


# ── звичайний хід ────────────────────────────────────────────────────────────

def test_sprava_prokhodyt_usi_etapy_po_cherzi(etapy: Etapy) -> None:
    _add("s1", "s2")

    got = _run()

    assert etapy.ran == [("s1", "a"), ("s1", "b"), ("s1", "c"),
                         ("s2", "a"), ("s2", "b"), ("s2", "c")]
    assert [h["state"] for h in got["handled"]] == [Q.DONE, Q.DONE]
    assert got["left"] == 0 and _state("s1")["state"] == Q.DONE
    rows = Q.read_journal()
    assert [(r["item"], r["stage"], r["outcome"]) for r in rows][:2] == [
        ("s1", "a", "ok"), ("s1", "b", "ok")]
    assert all("sec" in r for r in rows)


def test_zroblenyi_etap_ne_povtoriuietsia(etapy: Etapy) -> None:
    """Стан етапу судить диск: зроблене до черги вона не переробляє."""
    _add("s1")
    etapy.done |= {("s1", "a"), ("s1", "b")}

    _run()

    assert etapy.ran == [("s1", "c")]


# ── обрив і продовження ──────────────────────────────────────────────────────

class Vbyto(BaseException):
    """Процес убито посеред етапу: жодне `except Exception` цього не ловить."""


def test_zapys_pered_diieiu_i_prodovzhennia_pislia_obryvu(etapy: Etapy) -> None:
    """🔴 Убитий посеред читання виконавець лишає на диску «у роботі, етап b»,
    а наступний запуск бере ту саму справу з того самого етапу й попереднього
    не повторює."""
    _add("s1", "s2")

    def _kill(item: Any, ctx: Any) -> None:
        raise Vbyto

    etapy.hooks[("s1", "b")] = _kill
    with pytest.raises(Vbyto):
        _run()

    stan = _state("s1")
    assert (stan["state"], stan["stage"]) == (Q.RUNNING, "b")
    assert not Q.runner_alive(), "замок виконавця мусить зникнути разом із ним"

    del etapy.hooks[("s1", "b")]
    etapy.ran.clear()
    got = _run()

    assert etapy.ran[:2] == [("s1", "b"), ("s1", "c")], "етап a повторено"
    assert [h["id"] for h in got["handled"]] == ["s1", "s2"]
    assert _state("s1")["state"] == Q.DONE


def test_obryv_pislia_dii_do_zapysu_ne_povtoriuie_zroblene(etapy: Etapy) -> None:
    """Етап устиг зробити своє, а запис про це — ні: судить диск, не запис."""
    _add("s1")
    with Q.edit() as q:
        Q.settle(q["items"][0], Q.RUNNING, stage="b")
    etapy.done |= {("s1", "a"), ("s1", "b")}

    _run()

    assert etapy.ran == [("s1", "c")]


def test_druhyi_vykonavets_vidmovliaie(etapy: Etapy) -> None:
    _add("s1")
    with Q.own(), pytest.raises(Q.RunnerBusy, match="вже веде"):
        _run()
    assert etapy.ran == []


def test_dodane_pid_chas_roboty_ne_hubytsia(etapy: Etapy) -> None:
    """`queue add` з другого термінала, поки виконавець пише свій стан."""
    from nyshporka import ops as O

    _add("s1")
    d = Q.home().parent / "raw" / "f_1" / "spr-2"
    d.mkdir(parents=True)
    (d / "0001.jpg").write_bytes(b"x")

    def _add_mid(item: Any, ctx: Any) -> None:
        assert O.call("queue.add", {"refs": [str(d)]}).ok

    etapy.hooks[("s1", "b")] = _add_mid
    got = _run()

    assert len(Q.load()["items"]) == 2
    assert len(got["handled"]) == 2, "додану посеред роботи справу не взято"


# ── зупинки ──────────────────────────────────────────────────────────────────

def test_stop_after_case_bere_odnu(etapy: Etapy) -> None:
    _add("s1", "s2")

    got = _run(stop_after_case=True)

    assert [h["id"] for h in got["handled"]] == ["s1"]
    assert _state("s2")["state"] == Q.QUEUED


def test_prapor_pislia_spravy_dorobliaie_potochnu(etapy: Etapy) -> None:
    """«Дочитай поточну й зупинись»: прапор, поставлений посеред справи, її не рве."""
    _add("s1", "s2")

    def _flag(item: Any, ctx: Any) -> None:
        with Q.edit() as q:
            q["stop"] = Q.STOP_AFTER_CASE

    etapy.hooks[("s1", "a")] = _flag
    got = _run()

    assert _state("s1")["state"] == Q.DONE and _state("s2")["state"] == Q.QUEUED
    assert got["stopped"] == Q.STOP_AFTER_CASE
    assert Q.load()["stop"] == "", "прапор мусить зніматись, щойно його виконано"


def test_stop_now_hasyt_posered_etapu(etapy: Etapy) -> None:
    _add("s1", "s2")

    def _now(item: Any, ctx: Any) -> Any:
        with Q.edit() as q:
            q["stop"] = Q.STOP_NOW
        assert ctx.should_stop()
        return ST.Outcome(ST.STOPPED, "stopped", "зупинено на прохання: 1 із 3")

    etapy.hooks[("s1", "b")] = _now
    got = _run()

    stan = _state("s1")
    assert (stan["state"], stan["stage"]) == (Q.QUEUED, "b")
    assert [h["id"] for h in got["handled"]] == ["s1"] and _state("s2")["state"] == Q.QUEUED


def test_stop_now_mizh_etapamy_nastupnoho_ne_bere(etapy: Etapy) -> None:
    """Прапор, що прийшов, поки етап дороблявся: наступний етап не починається."""
    _add("s1")

    def _flag(item: Any, ctx: Any) -> None:
        with Q.edit() as q:
            q["stop"] = Q.STOP_NOW

    etapy.hooks[("s1", "a")] = _flag
    _run()

    assert etapy.ran == [("s1", "a")]
    assert (_state("s1")["state"], _state("s1")["stage"]) == (Q.QUEUED, "b")


def test_ctrl_c_povertaie_spravu_v_cherhu(etapy: Etapy) -> None:
    _add("s1")

    def _ctrl_c(item: Any, ctx: Any) -> None:
        raise KeyboardInterrupt

    etapy.hooks[("s1", "b")] = _ctrl_c
    got = _run()

    assert got["stopped"] == Q.STOP_NOW
    assert (_state("s1")["state"], _state("s1")["stage"]) == (Q.QUEUED, "b")


# ── три класи зупинки справи ─────────────────────────────────────────────────

def test_sprava_shcho_chekaie_liudynu_cherhu_ne_zupyniaie(etapy: Etapy) -> None:
    _add("s1", "s2")
    etapy.answers[("s1", "b")] = [ST.blocked("no_passport", "шифри немає", 'nysh case "x"')]

    got = _run()

    stan = _state("s1")
    assert (stan["state"], stan["stage"], stan["code"]) == (Q.BLOCKED, "b", "no_passport")
    assert stan["why"] == "шифри немає" and stan["fix"] == 'nysh case "x"'
    assert _state("s2")["state"] == Q.DONE
    assert (got["left"], got["waiting"]) == (0, 1)


def test_ostatochna_vidmova(etapy: Etapy) -> None:
    _add("s1")
    etapy.answers[("s1", "a")] = [ST.failed("not_found", "кадрів там немає")]

    _run()

    assert _state("s1")["state"] == Q.FAILED
    assert etapy.ran == [("s1", "a")]


def test_tymchasova_vidmova_povtoriuietsia_za_rozkladom(etapy: Etapy) -> None:
    import time

    _add("s1", "s2")
    etapy.answers[("s1", "a")] = [ST.retry("host_down", "хост лежить")]

    got = _run()

    stan = _state("s1")
    assert (stan["state"], stan["attempts"]) == (Q.RETRY, {"a": 1})
    chekaty = Q.stamp(stan["not_before"]) - time.time()
    assert R.BACKOFF[0] - 60 < chekaty <= R.BACKOFF[0] + 1
    assert _state("s2")["state"] == Q.DONE and got["next_retry_at"]
    # Час ще не настав: другий запуск справу не чіпає.
    etapy.ran.clear()
    _run()
    assert etapy.ran == []


def test_pislia_trokh_povtoriv_chekaie_liudynu(etapy: Etapy) -> None:
    _add("s1")
    etapy.answers[("s1", "a")] = [ST.retry("x", "хост лежить", after=0.001)] * 9

    for _ in range(len(R.BACKOFF) + 1):
        _run()

    stan = _state("s1")
    assert stan["state"] == Q.BLOCKED and "після 3 повторів" in stan["why"]
    assert len(etapy.ran) == len(R.BACKOFF) + 1


def test_terpliache_chekannia_sprob_ne_rakhuie(etapy: Etapy) -> None:
    """Зайнята карта — не збій: справа чекає, скільки треба, і не стає «чекає вас»."""
    _add("s1")
    etapy.answers[("s1", "a")] = [
        ST.retry("gpu_busy", "карта зайнята", after=0.001, patient=True)
        for _ in range(len(R.BACKOFF) + 3)]

    _run()

    # Спроб більше, ніж дозволено збоям, — а справа дійшла до кінця.
    assert etapy.ran.count(("s1", "a")) == len(R.BACKOFF) + 4
    assert _state("s1")["state"] == Q.DONE


def test_wait_dochikuietsia_povtoru(etapy: Etapy) -> None:
    _add("s1")
    etapy.answers[("s1", "a")] = [ST.retry("x", "хост лежить", after=0.01)]

    got = R.run(say=lambda _t: None, wait=True, sleep=lambda _s: __import__("time").sleep(0.02))

    assert _state("s1")["state"] == Q.DONE and len(got["handled"]) == 2


def test_etap_skazav_zrobleno_a_dysk_ni(etapy: Etapy) -> None:
    """🔴 Інакше наступні етапи будувались би на тому, чого немає."""
    _add("s1")
    etapy.hooks[("s1", "a")] = lambda item, ctx: ST.ok()

    _run()

    assert (_state("s1")["state"], _state("s1")["code"]) == (Q.BLOCKED, "not_confirmed")
    assert etapy.ran == [("s1", "a")]


def test_nespodivanyi_zbii_etapu_ne_valyt_cherhu(etapy: Etapy) -> None:
    _add("s1", "s2")

    def _boom(item: Any, ctx: Any) -> None:
        raise ValueError("несподіване")

    etapy.hooks[("s1", "a")] = _boom
    _run()

    assert _state("s1")["state"] == Q.BLOCKED and "ValueError" in _state("s1")["why"]
    assert _state("s2")["state"] == Q.DONE


def test_polahodzhene_liudynoiu_ide_dali_samo(etapy: Etapy) -> None:
    """Після `nysh case --shifra …` окремої команди «я полагодив» не треба."""
    _add("s1")
    etapy.answers[("s1", "b")] = [ST.blocked("no_passport", "шифри немає")]
    _run()
    assert _state("s1")["state"] == Q.BLOCKED

    etapy.done.add(("s1", "b"))          # людина полагодила: диск це показує
    etapy.ran.clear()
    _run()

    assert etapy.ran == [("s1", "c")] and _state("s1")["state"] == Q.DONE


def test_ne_polahodzhene_lyshaietsia_chekaty(etapy: Etapy) -> None:
    _add("s1")
    etapy.answers[("s1", "b")] = [ST.blocked("no_passport", "шифри немає")]
    _run()
    etapy.ran.clear()

    _run()

    assert etapy.ran == [] and _state("s1")["state"] == Q.BLOCKED


def test_dokaz_etapu_liahaie_v_spravu(etapy: Etapy) -> None:
    _add("s1")

    def _z_dokazom(item: Any, ctx: Any) -> Any:
        etapy.done.add(("s1", "a"))
        return ST.ok(shared={"sha256": "abc"})

    etapy.hooks[("s1", "a")] = _z_dokazom
    _run()

    assert _state("s1")["evidence"] == {"shared": {"sha256": "abc"}}


# ── файл черги ───────────────────────────────────────────────────────────────

def test_pobytyi_fail_cherhy_ne_perezapysuietsia(space: Path) -> None:
    """🔴 Побитий файл — не порожня черга: у ньому перелік замовленого."""
    from nyshporka import ops as O

    Q.home().mkdir(parents=True)
    Q.path().write_text('{"items": [', encoding="utf-8")

    with pytest.raises(Q.QueueError, match="побитий"):
        Q.load()
    assert not O.call("queue.status", {}).ok
    assert not O.call("queue.add", {"refs": ["x"]}).ok
    assert Q.path().read_text(encoding="utf-8") == '{"items": ['


def test_porozhnia_cherha(space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("queue.status", {})

    assert env.ok and env.data["rows"] == [] and env.data["runner"]["alive"] is False
    assert not Q.path().exists(), "перегляд не мусить нічого писати"


# ── рішення людини ───────────────────────────────────────────────────────────

def test_retry_set_drop(etapy: Etapy) -> None:
    from nyshporka import ops as O

    _add("s1", "s2")
    etapy.answers[("s1", "a")] = [ST.failed("not_found", "немає")]
    etapy.answers[("s2", "a")] = [ST.blocked("pool_needs_decision", "у пулі є")]
    _run()

    assert O.call("queue.retry", {"ref": "s1"}).data == {"queued": ["s1"]}
    assert _state("s1")["state"] == Q.QUEUED and _state("s1")["attempts"] == {}

    env = O.call("queue.set", {"ref": "s2", "pool": "read", "partial": "лише початок"})
    assert env.ok and env.data["state"] == Q.QUEUED
    assert _state("s2")["opts"] == {"pool": "read", "partial_why": "лише початок"}
    assert not O.call("queue.set", {"ref": "s2", "pool": "може"}).ok

    assert O.call("queue.drop", {"ref": "s1", "why": "не наша"}).ok
    assert _state("s1")["state"] == Q.DROPPED and _state("s1")["why"] == "не наша"
    assert not O.call("queue.drop", {"ref": "нема такої"}).ok
    rows = O.call("queue.status", {}).data["rows"]
    assert [r["id"] for r in rows] == ["s2"]


def test_stop_bez_vykonavtsia_nichoho_ne_stavyt(etapy: Etapy) -> None:
    from nyshporka import ops as O

    env = O.call("queue.stop", {"now": True})

    assert env.ok and any(w.code == "no_runner" for w in env.warnings)
    assert Q.load()["stop"] == ""


def test_stop_pry_zhyvomu_vykonavtsi(etapy: Etapy) -> None:
    from nyshporka import ops as O

    _add("s1")
    with Q.own():
        assert O.call("queue.stop", {}).data == {"stop": Q.STOP_AFTER_CASE,
                                                "runner_alive": True}
        assert O.call("queue.status", {}).data["runner"]["alive"] is True
        assert O.call("queue.start", {}).data["started"] is False


def test_start_na_porozhnii_cherzi_vidmovliaie(space: Path) -> None:
    from nyshporka import ops as O

    env = O.call("queue.start", {})

    assert not env.ok and "немає справ" in env.error


def test_start_pidnimaie_toho_samoho_vykonavtsia_vidcheplenym(
        etapy: Etapy, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кнопка «Запустити» піднімає `nysh queue run` — той самий виконавець, що
    в терміналі, — відчепленим від застосунку й з виводом у файл."""
    import subprocess
    import sys

    from nyshporka import ops as O
    from nyshporka.core.workspace import workspace

    seen: list[tuple[list[str], dict[str, Any]]] = []

    class _Proc:
        pid = 4242

    def _popen(cmd: list[str], **kw: Any) -> Any:
        seen.append((cmd, kw))
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", _popen)
    _add("s1")

    env = O.call("queue.start", {"share": True})

    assert env.ok and env.data["started"] is True and env.data["pid"] == 4242
    cmd, kw = seen[0]
    assert cmd == [sys.executable, "-m", "nyshporka", "queue", "run", "--share"]
    assert kw["cwd"] == str(workspace().root), "простір виконавець бере з робочої теки"
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw.get("start_new_session") or kw.get("creationflags"), "процес не відчеплено"
    assert env.data["log"].endswith("run.log") and (Q.home() / "run.log").exists()


def test_status_kazhe_pro_obirvanoho_vykonavtsia(etapy: Etapy) -> None:
    from nyshporka import ops as O

    _add("s1")
    with Q.edit() as q:
        Q.settle(q["items"][0], Q.RUNNING, stage="b")

    env = O.call("queue.status", {})

    assert any(w.code == "runner_gone" for w in env.warnings)


def test_zhurnal_perezhyvaie_pobytyi_riadok(space: Path) -> None:
    Q.journal(item="s1", stage="a", outcome="ok", sec=1.0)
    with (Q.home() / "journal.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{не json\n")
    Q.journal(item="s1", stage="b", outcome="ok", sec=2.0)

    rows = Q.read_journal()

    assert [r.get("stage") for r in rows] == ["a", None, "b"] and "broken" in rows[1]
    assert json.loads((Q.home() / "journal.jsonl").read_text(
        encoding="utf-8").splitlines()[0])["item"] == "s1"
