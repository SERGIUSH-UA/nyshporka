"""Етапи справи в черзі: що кожен кличе, коли вважає себе зробленим і чим стає.

⚠ Рушій, мережа джерела й пул підмінені на їхніх швах: перевіряється, як етап
читає диск і як розкладає відмови на «повторить сама», «чекає вас» і
«остаточно», — а не те, що вже стережуть тести самих функцій.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _cherha import drop_space, frames, make_space, write_run

Q: Any = None
R: Any = None
ST: Any = None
REG: Any = None

SHIFRA = "ДАХмО 315-1-8433"
KEY = "DAHMO/315/8433"


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    make_space(tmp_path, monkeypatch)
    global Q, R, ST, REG
    from nyshporka.cases import register
    from nyshporka.queue import runner, stages, state

    Q, R, ST, REG = state, runner, stages, register
    # Профіль обміну — типовий: пул не питати, сам нічого не віддає.
    monkeypatch.setattr(ST, "_profile", lambda: SimpleNamespace(lookup=False, auto=False))
    yield tmp_path
    drop_space()


class Chytach:
    """Замість рушія: кладе текст на кадри, як раннер, і рахує виклики."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nyshporka.cloud import go
        from nyshporka.htr import run as HR
        from nyshporka.htr import session as S

        self.calls: list[dict[str, Any]] = []
        self.pages: list[int | None] = []      # скільки сторінок дати за виклик; None — усі
        self.trust = "fixed"
        self.books: list[str] = []
        self.book_notes: list[str] = []
        monkeypatch.setattr(HR, "plan", self.plan)
        monkeypatch.setattr(S, "read_case", self.read)
        monkeypatch.setattr(go, "bookkeeping", self.bookkeeping)

    def plan(self, case_dir: Any, **kw: Any) -> Any:
        from nyshporka.htr.run import count_frames

        d = Path(case_dir)
        out = ST._own_out(ST.Where(d, d, count_frames(d), "", {}))
        return SimpleNamespace(
            case_dir=d, out_dir=out, frames=count_frames(d),
            script=kw.get("script") or "cyrillic", script_trust=self.trust,
            script_why="підказок немає", model=Path("pysar_cyr_v17.pt"), voices=(),
            asked=kw)

    def read(self, plan: Any, **kw: Any) -> Any:
        from nyshporka.htr.session import ReadResult

        self.calls.append({"plan": plan, **kw})
        n = self.pages.pop(0) if self.pages else None
        write_run(plan.out_dir, plan.case_dir, key=kw.get("case_key", ""), pages=n)
        done = len(list(plan.out_dir.glob("*.txt")))
        return ReadResult(rc=0 if done == plan.frames else 3, done=done,
                          frames=plan.frames, missing=plan.frames - done,
                          partial=False, stopped=False)

    def bookkeeping(self, run_name: str) -> list[str]:
        self.books.append(run_name)
        return list(self.book_notes)


@pytest.fixture
def chytach(space: Path, monkeypatch: pytest.MonkeyPatch) -> Chytach:
    return Chytach(monkeypatch)


def _sprava(space: Path, *, shifra: str = SHIFRA, n: int = 3) -> Path:
    d = frames(space, "dahmo_315/spr-8433", n)
    if shifra:
        REG.describe(d, shifra=shifra)
    return d


def _add(ref: Any, **kw: Any) -> Any:
    from nyshporka import ops as O

    env = O.call("queue.add", {"refs": [str(ref)], **kw})
    assert env.ok, env.error
    return env


def _run(**kw: Any) -> dict[str, Any]:
    return R.run(say=lambda _t: None, **kw)


def _one() -> dict[str, Any]:
    return next(it for it in Q.load()["items"] if it["state"] != Q.DROPPED)


# ── тека на диску: увесь шлях ────────────────────────────────────────────────

def test_teka_z_pasportom_dokhodyt_do_kintsia(space: Path, chytach: Chytach) -> None:
    d = _sprava(space)
    env = _add(d)
    assert [s["state"] for s in env.data["rows"][0]["stages"]] == [
        "skip", "done", "todo", "skip", "todo", "todo", "skip"]

    _run()

    stan = _one()
    assert stan["state"] == Q.DONE and stan["id"] == KEY
    assert len(chytach.calls) == 1 and chytach.calls[0]["case_key"] == KEY
    assert chytach.books == ["spr-8433"]
    assert [r["stage"] for r in Q.read_journal()] == ["catalog", "read", "books"]
    # Другий захід нічого не переробляє: усе видно з диска.
    with Q.edit() as q:
        Q.settle(q["items"][0], Q.QUEUED)
    _run()
    assert len(chytach.calls) == 1 and chytach.books == ["spr-8433"]


def test_status_pokazuie_etapy_i_zalyshok(space: Path, chytach: Chytach) -> None:
    from nyshporka import ops as O

    _add(_sprava(space, n=4))

    env = O.call("queue.status", {})

    row = env.data["rows"][0]
    assert (row["frames"], row["pages"], row["state"]) == (4, 0, Q.QUEUED)
    assert env.data["left"] == {"cases": 1, "pages": 4, "sec_per_page": None,
                                "eta_sec": None}


# ── паспорт ──────────────────────────────────────────────────────────────────

def test_bez_shyfry_chekaie_liudynu_i_yde_dali_pislia_neii(space: Path,
                                                        chytach: Chytach) -> None:
    """🔴 Шифру черга не вигадує: справа стає з командою реєстрації, а після
    `nysh case --shifra …` іде далі без окремого «я полагодив»."""
    d = frames(space, "inshe/skany")
    _add(d)

    _run()

    stan = _one()
    assert (stan["state"], stan["stage"], stan["code"]) == (Q.BLOCKED, "passport",
                                                          "no_passport")
    assert "nysh case" in stan["fix"] and "--shifra" in stan["fix"]
    assert chytach.calls == []

    REG.describe(d, shifra=SHIFRA)
    _run()

    assert _one()["state"] == Q.DONE and len(chytach.calls) == 1


def test_lyshe_pasport_zavantazhuvacha_tse_ne_shyfra(space: Path, chytach: Chytach) -> None:
    from nyshporka.cases.acquire import record_fetch
    from nyshporka.sources.base import FetchResult

    d = frames(space, "inshe/zavantazhene")
    record_fetch(d, FetchResult(dest=d, frames=3), source="archium", ref="x", want=3,
                 extra={"shifra_claimed": SHIFRA})
    _add(d)

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "loader_only")
    assert chytach.calls == []


def test_zbirnu_teku_cherha_ne_bere(space: Path) -> None:
    from nyshporka import ops as O

    d = frames(space, "rgia_592/RGIA_592_25_926_929")

    env = O.call("queue.add", {"refs": [str(d)]})

    assert env.ok and env.data["added"] == 0
    assert "збірна тека" in env.data["rows"][0]["why"]
    assert any(w.code == "not_added" for w in env.warnings)
    assert Q.load()["items"] == []


def test_add_ne_dubliuie_i_dry_run_ne_pyshe(space: Path) -> None:
    from nyshporka import ops as O

    d = _sprava(space)

    assert O.call("queue.add", {"refs": [str(d)], "dry_run": True}).data["added"] == 0
    assert not Q.path().exists()
    assert O.call("queue.add", {"refs": [str(d)]}).data["added"] == 1
    again = O.call("queue.add", {"refs": [str(d), "data/raw/dahmo_315/spr-8433"]})
    assert again.data["added"] == 0 and "уже в черзі" in again.data["rows"][0]["why"]
    assert not O.call("queue.add", {"refs": ["немає/такого"]}).data["added"]


# ── читання ──────────────────────────────────────────────────────────────────

def test_nedochytane_dochytuietsia_povtorom(space: Path, chytach: Chytach) -> None:
    _add(_sprava(space, n=4))
    chytach.pages = [2, None]

    _run()

    assert len(chytach.calls) == 2 and _one()["state"] == Q.DONE


def test_uperto_nepovne_chekaie_rishennia_pro_uryvok(space: Path,
                                                     chytach: Chytach) -> None:
    from nyshporka import ops as O

    _add(_sprava(space, n=4))
    chytach.pages = [2] * 9

    _run()

    stan = _one()
    assert (stan["state"], stan["stage"], stan["code"]) == (Q.BLOCKED, "read", "incomplete")
    assert "прочитано 2 із 4" in stan["why"] and "--partial" in stan["fix"]
    assert len(chytach.calls) == len(R.BACKOFF) + 1 and chytach.books == []

    assert O.call("queue.set", {"ref": KEY, "partial": "кадри 3-4 зіпсовані"}).ok
    _run()

    assert _one()["state"] == Q.DONE
    assert len(chytach.calls) == len(R.BACKOFF) + 1, "прийнятий уривок перечитано"


def test_karta_zainiata_chekaie_a_ne_chytaie(space: Path, chytach: Chytach) -> None:
    import os

    from nyshporka.htr import runs as RUNS

    _add(_sprava(space))
    RUNS.register(os.getpid(), case="insha-sprava", case_key="ДАХмО 315-1-77")

    _run()

    stan = _one()
    assert (stan["state"], stan["code"]) == (Q.RETRY, "gpu_busy")
    assert "ДАХмО 315-1-77" in stan["why"] and chytach.calls == []
    assert stan["attempts"].get("read", 0) == 0
    RUNS.drop(os.getpid())


def test_nevyznachene_pysmo_ne_chytaietsia_navmannia(space: Path,
                                                    chytach: Chytach) -> None:
    from nyshporka import ops as O

    _add(_sprava(space))
    chytach.trust = "unknown"

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "script_unsure")
    assert chytach.calls == []

    assert O.call("queue.set", {"ref": KEY, "script": "latin"}).ok
    _run()

    assert _one()["state"] == Q.DONE
    assert chytach.calls[0]["plan"].asked["script"] == "latin"


def test_vidmova_planu_chytannia_chekaie_liudynu(space: Path, chytach: Chytach,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.htr import run as HR

    _add(_sprava(space))

    def _no(case_dir: Any, **kw: Any) -> Any:
        raise HR.ReadError("середовище рушіїв не готове — `nysh htr install`")

    monkeypatch.setattr(HR, "plan", _no)
    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "read_refused")
    assert "nysh htr install" in _one()["why"]


def test_zupynka_posered_chytannia(space: Path, chytach: Chytach,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.htr import session as S
    from nyshporka.htr.session import ReadResult

    d = _sprava(space, n=4)
    _add(d)

    def _stopped(plan: Any, **kw: Any) -> Any:
        write_run(plan.out_dir, plan.case_dir, pages=1)
        with Q.edit() as q:
            q["stop"] = Q.STOP_NOW
        assert kw["should_stop"]() is True
        return ReadResult(rc=1, done=1, frames=4, missing=3, partial=False, stopped=True)

    monkeypatch.setattr(S, "read_case", _stopped)
    got = _run()

    stan = _one()
    assert (stan["state"], stan["stage"]) == (Q.QUEUED, "read")
    assert got["stopped"] == Q.STOP_NOW and "прочитано 1 із 4" in stan["why"]


def test_oblik_zainiatyi_povtoryt_sam(space: Path, chytach: Chytach) -> None:
    _add(_sprava(space))
    chytach.book_notes = ["стор зайнятий"]

    _run()

    assert (_one()["state"], _one()["stage"], _one()["code"]) == (Q.RETRY, "books",
                                                                 "books_busy")


# ── пул ──────────────────────────────────────────────────────────────────────

class Pul:
    """Пул на швах етапу: зріз, каталог, перегляд пакета, прийняття."""

    def __init__(self, space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from nyshporka import ops as O
        from nyshporka.share import catalog, pool, suggest

        self.space = space
        self.synced: list[tuple[str, str]] = []
        self.cell: Any = None
        self.rows: list[Any] = []
        self.label = "exact"
        self.down = False
        self.taken: list[str] = []
        self.quad = "DAHMO/315/1/8433"
        self._call = O.call
        monkeypatch.setattr(suggest, "_pool_key", lambda key: self.quad)
        monkeypatch.setattr(pool, "sync", self.sync)
        monkeypatch.setattr(pool, "by_key", lambda quad: self.cell)
        monkeypatch.setattr(catalog, "search", lambda q, *a, **kw: (self.rows, len(self.rows), 9))
        monkeypatch.setattr(O, "call", self.call)

    def sync(self, base: str = "", *, repo: str = "", fond: str = "") -> dict[str, Any]:
        if self.down:
            raise RuntimeError("пул не відповідає")
        self.synced.append((repo, fond))
        return {}

    def maie(self, pages: int, frames_n: int, *, mine: bool = False, packs: int = 1) -> None:
        self.cell = SimpleNamespace(pages=pages, frames=frames_n, mine=mine,
                                    coverage=pages / frames_n, publishers=["Сусід"], n=packs)
        self.rows = [SimpleNamespace(repo="DAHMO", fond="315", opys="1", spr="8433",
                                     shifra=SHIFRA, url=f"https://pool/{i}.nyshtext",
                                     sha256="ab" * 32) for i in range(packs)]

    def call(self, name: str, payload: dict[str, Any]) -> Any:
        from nyshporka.core.envelope import ok

        if name == "share.inspect":
            return ok({"alignment": {"label": self.label, "why": "імена збіглись"}})
        if name == "share.pull":
            self.taken.append(payload["query"])
            d = self.space / "data" / "raw" / "dahmo_315" / "spr-8433"
            run = write_run(self.space / "reports" / "htr" / "сусід-8433", d, key=KEY,
                            shared={"publisher": "Сусід"})
            return ok({"imported": {"runs": [run.name], "pages": 3}})
        return self._call(name, payload)


@pytest.fixture
def pul(space: Path, monkeypatch: pytest.MonkeyPatch) -> Pul:
    return Pul(space, monkeypatch)


def test_pul_ne_pytaietsia_poky_ne_dozvoleno(space: Path, chytach: Chytach,
                                             pul: Pul) -> None:
    """🔴 Запит про справу несе її шифру: без дозволу в профілі чи рішення по
    справі черга в пул не ходить (`PRIVACY.md`)."""
    pul.maie(3, 3)
    env = _add(_sprava(space))
    assert env.data["rows"][0]["pool_mode"] == "read"

    _run()

    assert pul.synced == [] and pul.taken == []
    assert _one()["state"] == Q.DONE and len(chytach.calls) == 1


def test_profil_dozvoliaie_pytaty_pul(space: Path, chytach: Chytach, pul: Pul,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ST, "_profile", lambda: SimpleNamespace(lookup=True, auto=False))
    _add(_sprava(space))

    _run()

    assert pul.synced == [("DAHMO", "315")]
    assert _one()["evidence"]["pool"]["verdict"] == "absent" and len(chytach.calls) == 1


def test_pevne_beretsia_z_pulu_zamist_prohonu(space: Path, chytach: Chytach,
                                             pul: Pul) -> None:
    """Повне покриття й точна прив'язка: чужий текст узято, читання й віддачі немає."""
    pul.maie(3, 3)
    _add(_sprava(space), pool="auto", share=True)

    _run()

    stan = _one()
    assert stan["state"] == Q.DONE and pul.taken == [SHIFRA]
    assert stan["evidence"]["pool"]["verdict"] == "taken"
    assert chytach.calls == [], "справу з пулу перечитано своїм рушієм"
    assert "share" not in [r["stage"] for r in Q.read_journal()], "чуже віддано назад"
    assert chytach.books == ["spr-8433"], "узяте з пулу не пішло в облік"


def test_nepovne_pokryttia_chekaie_rishennia(space: Path, chytach: Chytach,
                                            pul: Pul) -> None:
    from nyshporka import ops as O

    pul.maie(2, 3)
    _add(_sprava(space), pool="auto")

    _run()

    stan = _one()
    assert (stan["state"], stan["code"]) == (Q.BLOCKED, "pool_needs_decision")
    assert "2 стор. із 3 кадрів (67%)" in stan["why"] and "Сусід" in stan["why"]
    assert "--pool take" in stan["fix"] and "--pool read" in stan["fix"]
    assert pul.taken == [] and chytach.calls == []

    assert O.call("queue.set", {"ref": KEY, "pool": "read"}).ok
    _run()

    assert _one()["state"] == Q.DONE and len(chytach.calls) == 1 and pul.taken == []


def test_nepevna_pryviazka_chekaie_rishennia(space: Path, chytach: Chytach,
                                            pul: Pul) -> None:
    from nyshporka import ops as O

    pul.maie(3, 3)
    pul.label = "by-position"
    _add(_sprava(space), pool="auto")

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "pool_needs_decision")
    assert "by-position" in _one()["why"] and pul.taken == []

    assert O.call("queue.set", {"ref": KEY, "pool": "take"}).ok
    _run()

    assert pul.taken == [SHIFRA] and _one()["state"] == Q.DONE and chytach.calls == []


def test_kilka_paketiv_u_puli_vybyraie_liudyna(space: Path, chytach: Chytach,
                                              pul: Pul) -> None:
    pul.maie(3, 3, packs=2)
    _add(_sprava(space), pool="auto")

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "pool_ambiguous")
    assert pul.taken == []


def test_pul_nedostupnyi_povtoryt_sam(space: Path, chytach: Chytach, pul: Pul) -> None:
    pul.down = True
    _add(_sprava(space), pool="auto")

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.RETRY, "pool_unavailable")
    assert "--pool read" in _one()["why"] and chytach.calls == []


def test_zvirka_pulu_stariie(space: Path, chytach: Chytach, pul: Pul) -> None:
    """Справа простояла довше за свіжість зрізу — перед читанням пул питається знову."""
    import time

    from nyshporka.share import pool

    d = _sprava(space)
    _add(d, pool="auto")
    item = _one()
    item["evidence"] = {"pool": {"at": Q.now(), "verdict": "absent"}}
    assert ST.pool_done(item, ST.Ctx()) is True

    davno = time.time() - (pool.SVIZHYI_DNIV + 1) * 86400
    item["evidence"]["pool"]["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                                   time.localtime(davno))
    assert ST.pool_done(item, ST.Ctx()) is False


# ── віддача ──────────────────────────────────────────────────────────────────

class Viddacha:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nyshporka import ops as O

        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.dry: dict[str, Any] = {"gates": {"refusals": []}}
        self.sent: Any = None
        self._call = O.call
        monkeypatch.setattr(O, "call", self.call)

    def call(self, name: str, payload: dict[str, Any]) -> Any:
        from nyshporka.core.envelope import fail, ok

        if name == "share.pack":
            self.calls.append((name, payload))
            return ok(self.dry if payload.get("dry_run")
                      else {"path": "out/x.nyshtext", "sha256": "cd" * 32})
        if name == "share.publish":
            self.calls.append((name, payload))
            if isinstance(self.sent, dict):
                env = fail(self.sent.get("error", "відмова"))
                env.data = self.sent
                return env
            return ok({"outcome": self.sent or "viddano"})
        return self._call(name, payload)

    def names(self) -> list[str]:
        return [n + (":dry" if p.get("dry_run") else "") for n, p in self.calls]


@pytest.fixture
def viddacha(space: Path, monkeypatch: pytest.MonkeyPatch) -> Viddacha:
    return Viddacha(monkeypatch)


def test_bez_poznachky_ne_viddaie(space: Path, chytach: Chytach,
                                  viddacha: Viddacha) -> None:
    _add(_sprava(space))

    _run()

    assert _one()["state"] == Q.DONE and viddacha.calls == []


def test_z_poznachkoiu_viddaie_odyn_raz(space: Path, chytach: Chytach,
                                        viddacha: Viddacha) -> None:
    _add(_sprava(space), share=True)

    _run()

    stan = _one()
    assert viddacha.names() == ["share.pack:dry", "share.pack", "share.publish"]
    assert stan["state"] == Q.DONE and stan["evidence"]["shared"]["sha256"] == "cd" * 32
    assert viddacha.calls[1][1] == {"case": KEY, "partial": ""}
    with Q.edit() as q:
        Q.settle(q["items"][0], Q.QUEUED)
    _run()
    assert len(viddacha.calls) == 3, "віддану справу віддано вдруге"


def test_run_share_viddaie_bez_poznachky_spravy(space: Path, chytach: Chytach,
                                               viddacha: Viddacha) -> None:
    _add(_sprava(space))

    _run(share=True)

    assert "share.publish" in viddacha.names()


def test_zghoda_zavzhdy_viddaie(space: Path, chytach: Chytach, viddacha: Viddacha,
                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ST, "_profile", lambda: SimpleNamespace(lookup=False, auto=True))
    _add(_sprava(space))

    _run()

    assert "share.publish" in viddacha.names()


def test_vidmova_pakuvannia_chekaie_liudynu(space: Path, chytach: Chytach,
                                           viddacha: Viddacha) -> None:
    _add(_sprava(space), share=True)
    viddacha.dry = {"gates": {"refusals": []}, "pack_refusals": ["кадрів справи не названо"]}

    _run()

    stan = _one()
    assert (stan["state"], stan["stage"], stan["code"]) == (Q.BLOCKED, "share",
                                                          "pack_refused")
    assert "кадрів справи не названо" in stan["why"]
    assert viddacha.names() == ["share.pack:dry"], "пакет із відмовою зібрано й залито"


def test_stelia_pulu_povtoryt_pislia_nazvanoho_chasu(space: Path, chytach: Chytach,
                                                    viddacha: Viddacha) -> None:
    import time

    _add(_sprava(space), share=True)
    viddacha.sent = {"error": "429", "status": 429, "rate_limited": True,
                     "retry_after": 900}

    _run()

    stan = _one()
    assert (stan["state"], stan["code"]) == (Q.RETRY, "upload_retry")
    assert 840 < Q.stamp(stan["not_before"]) - time.time() <= 901


def test_vidmova_pulu_ostatochna(space: Path, chytach: Chytach,
                                 viddacha: Viddacha) -> None:
    _add(_sprava(space), share=True)
    viddacha.sent = {"error": "ворота пулу", "status": 400, "klas": "",
                     "refusals": [{"rule": "short_lines"}]}

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.FAILED, "pool_refused")


def test_uryvok_yide_z_prychynoiu(space: Path, chytach: Chytach, viddacha: Viddacha) -> None:
    from nyshporka import ops as O

    _add(_sprava(space, n=4), share=True)
    chytach.pages = [2] * 9
    _run()
    assert O.call("queue.set", {"ref": KEY, "partial": "кадри 3-4 зіпсовані"}).ok

    _run()

    assert viddacha.calls[-2][1] == {"case": KEY, "partial": "кадри 3-4 зіпсовані"}


# ── справа з реєстру опису: кадри ────────────────────────────────────────────

class Dzherelo:
    def __init__(self, space: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from nyshporka.cases import take

        self.take = take
        self.dir = space / "data" / "raw" / "dahmo_315" / "spr-8433"
        self.plan: dict[str, Any] = {
            "key": KEY, "case_dir": str(self.dir), "channel": "archium", "ref": "x",
            "why": "переглядач архіву", "title": "Метрична книга", "film": "",
            "shifra_needs_eye": False}
        self.fail: tuple[str, dict[str, Any]] | None = None
        self.calls = 0
        monkeypatch.setattr(take, "plan", lambda key: dict(self.plan))
        monkeypatch.setattr(take, "take", self.do)

    def do(self, key: str, **kw: Any) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            text, meta = self.fail
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            raise self.take.TakeError(text)
        for i in (1, 2, 3):
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{i:04d}.jpg").write_bytes(b"x")
        (self.dir / "meta.json").write_text(json.dumps(
            {"fetch_state": "complete", "fetched_by": "archium", "shifra": SHIFRA}),
            encoding="utf-8")
        kw["on_progress"](3, 3)
        return {"pages": 3, "files": 3}


@pytest.fixture
def dzherelo(space: Path, monkeypatch: pytest.MonkeyPatch) -> Dzherelo:
    return Dzherelo(space, monkeypatch)


def test_sprava_z_reiestru_opysu_sama_bere_kadry(space: Path, chytach: Chytach,
                                                 dzherelo: Dzherelo) -> None:
    env = _add(KEY)
    row = env.data["rows"][0]
    assert (row["kind"], row["channel"], row["id"]) == ("key", "archium", KEY)

    _run()

    assert dzherelo.calls == 1 and _one()["state"] == Q.DONE
    assert [r["stage"] for r in Q.read_journal()][:1] == ["fetch"]
    assert Q.read_pulse() == {}, "пульс лишився після виконавця"


def test_khost_lezhyt_povtoryt_sam(space: Path, chytach: Chytach,
                                   dzherelo: Dzherelo) -> None:
    _add(KEY)
    dzherelo.fail = ("узято 0 із 3", {"fetch_state": "empty",
                                      "fetch_causes": {"host_down": 3}})

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.RETRY, "host_down")
    assert chytach.calls == []


def test_vidmovleno_v_dostupi_chekaie_liudynu(space: Path, chytach: Chytach,
                                              dzherelo: Dzherelo) -> None:
    _add(KEY)
    dzherelo.fail = ("узято 0 із 3", {"fetch_state": "empty", "fetch_causes": {"denied": 3}})

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "denied")


def test_kadriv_tam_nemaie_ostatochno(space: Path, chytach: Chytach,
                                      dzherelo: Dzherelo) -> None:
    _add(KEY)
    dzherelo.fail = ("узято 0 із 3", {"fetch_state": "empty",
                                      "fetch_causes": {"not_found": 3}})

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.FAILED, "not_found")


def test_bez_kanalu_chekaie_liudynu(space: Path, chytach: Chytach,
                                    dzherelo: Dzherelo) -> None:
    dzherelo.plan.update(channel="", why="жодного каналу: справу замовляють в архіві")
    _add(KEY)

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "no_channel")
    assert "замовляють в архіві" in _one()["why"] and dzherelo.calls == 0


def test_interpolovana_shyfra_chekaie_oka(space: Path, chytach: Chytach,
                                          dzherelo: Dzherelo) -> None:
    from nyshporka import ops as O

    dzherelo.plan["shifra_needs_eye"] = True
    _add(KEY)

    _run()

    assert (_one()["state"], _one()["code"]) == (Q.BLOCKED, "shifra_needs_eye")
    assert dzherelo.calls == 0, "кадри покладено під не звірену шифру"

    assert O.call("queue.set", {"ref": KEY, "shifra_ok": True}).ok
    _run()

    assert dzherelo.calls == 1 and _one()["state"] == Q.DONE
