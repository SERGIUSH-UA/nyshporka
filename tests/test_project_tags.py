"""Хто замовив: прогони, черга, джоби й хмарні заходи несуть проєкт.

Майстерня читає для всіх проєктів одною машиною, тож без позначки «моє / все»
й собівартість проєкту не відрізнити від чужих — а черга в проєкті дала б два
виконавці на одну карту.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nyshporka.core import projects as P
from nyshporka.core import workspace as W

pytestmark = pytest.mark.real_paths


def _hub(tmp_path: Path, *, hub_only: bool = False) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    flag = "hub_only = true\n" if hub_only else ""
    (hub / W.MARKER).write_text(f'[workspace]\nname = "Майстерня"\nkeys = 2\n{flag}',
                                encoding="utf-8")
    return hub


def _project(hub: Path, pid: str) -> Path:
    root = hub / W.PROJECTS_DIR / pid
    root.mkdir(parents=True)
    (root / W.MARKER).write_text(f'[project]\nname = "Рід {pid}"\nkind = "family"\n',
                                 encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def test_tag_and_legacy_records(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    assert P.tag(W._build(alpha, "test")) == "alpha"
    assert P.tag(W._build(hub, "test")) == "."
    assert P.tag(W._build(_hub(tmp_path / "p", hub_only=True), "test")) == ""
    # Запис до хвилі проєктів — корінь старого типу.
    assert P.tag_of(None) == "." and P.is_mine(None, W._build(hub, "test"))
    assert not P.is_mine(None, W._build(alpha, "test"))


def test_queue_lives_in_the_hub_and_items_carry_project(tmp_path: Path) -> None:
    from nyshporka import ops as O
    from nyshporka.queue import state as Q

    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    W.use(W._build(alpha, "test"))
    assert Q.home() == hub / "data" / "queue"
    with Q.edit() as q:
        q["items"].append(Q.new_item("a1", {"key": "DAHMO/315/1/1"}, {}))
    W.use(W._build(beta, "test"))
    with Q.edit() as q:
        q["items"].append(Q.new_item("b1", {"key": "DAHMO/315/1/2"}, {}))
    assert [it["project"] for it in Q.load()["items"]] == ["alpha", "beta"]
    env = O.call("queue.status", {"mine": True, "all": True})
    assert env.ok, env.error
    assert [r["id"] for r in env.data["rows"]] == ["b1"]
    assert env.data["rows"][0]["project"] == "beta"


def _meta(run: Path, **extra: object) -> Path:
    run.mkdir(parents=True)
    p = run / "_htr_meta.json"
    p.write_text(json.dumps({"case_key": "DAHMO/315/1/1", "pages": {}, **extra}),
                 encoding="utf-8")
    return p


def test_run_meta_is_stamped_once_with_the_ordering_project(tmp_path: Path) -> None:
    from nyshporka import htr_store as S

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    meta = _meta(hub / "reports" / "htr" / "dahmo-315-1")
    assert S.stamp_project(meta.parent) == 1
    assert json.loads(meta.read_text(encoding="utf-8"))["project"] == "alpha"
    # Дочитування з іншого проєкту прогону своїм не робить.
    assert S.stamp_project(meta.parent, "beta") == 0
    assert json.loads(meta.read_text(encoding="utf-8"))["project"] == "alpha"


def test_runs_list_mine(tmp_path: Path) -> None:
    from nyshporka import htr_store as S
    from nyshporka import ops as O

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    runs = hub / "reports" / "htr"
    _meta(runs / "old-run")                                   # без позначки — корінь
    _meta(runs / "alpha-run", project="alpha")
    W.use(W._build(alpha, "test"))
    S._RUNS_CACHE = None
    env = O.call("runs.list", {"mine": True})
    assert env.ok, env.error
    assert [r["name"] for r in env.data["runs"]] == ["alpha-run"]
    W.use(W._build(hub, "test"))
    S._RUNS_CACHE = None
    env = O.call("runs.list", {"mine": True})
    assert [r["name"] for r in env.data["runs"]] == ["old-run"]


def test_job_record_keeps_project_across_restart(tmp_path: Path) -> None:
    from nyshporka.core.jobs import JobBus

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    path = tmp_path / "jobs.json"

    async def go() -> None:
        bus = JobBus(path)
        job, _ = await bus.enqueue("read", title="справа")
        assert job.project == "alpha"
        again = JobBus(path)
        again.load()
        assert again.get(job.id).project == "alpha"         # type: ignore[union-attr]

    asyncio.run(go())


def test_cloud_run_state_old_record_stays_untagged(tmp_path: Path) -> None:
    from nyshporka.cloud import state as ST

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    ST.save(ST.RunState(run_id="old"))
    raw = json.loads(next((hub / "data" / "derived" / "cloud").glob("old*.json"))
                     .read_text(encoding="utf-8"))
    raw.pop("project", None)
    next((hub / "data" / "derived" / "cloud").glob("old*.json")).write_text(
        json.dumps(raw), encoding="utf-8")
    assert ST.load("old").project is None                    # type: ignore[union-attr]


def test_cloud_state_sums_spend_by_project(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from nyshporka.cloud import state as ST
    from nyshporka.cloud.cli import app

    hub = _hub(tmp_path)
    _project(hub, "alpha")
    W.use(W._build(hub, "test"))
    ST.save(ST.RunState(run_id="r-old", box={"spent_usd": 1.5}))
    ST.save(ST.RunState(run_id="r-alpha", project="alpha", box={"spent_usd": 0.25}))
    ST.save(ST.RunState(run_id="r-nop", project="alpha"))      # ціни немає
    out = CliRunner().invoke(app, ["state", "--all"])
    assert out.exit_code == 0, out.output
    assert "r-alpha" in out.output and "· alpha" in out.output
    assert "alpha $0.25 (+1 без ціни)" in out.output and ". $1.50" in out.output


def test_registry_builds_from_a_pure_hub(tmp_path: Path) -> None:
    """Хмарний наглядач збирає реєстр із кореня Майстерні — без проєкту."""
    from nyshporka.cases import db

    hub = _hub(tmp_path, hub_only=True)
    (hub / "data" / "raw").mkdir(parents=True)
    W.use(W._build(hub, "test"))
    db.build_index()
    assert db.index_path().is_file()


def test_cloud_go_signs_for_whom_it_was_ordered(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Захід хмари бере підпис «для кого»; оренди немає — `go` підмінено."""
    from nyshporka import ops as O
    from nyshporka.cloud import go as GO

    hub = _hub(tmp_path, hub_only=True)
    alpha = _project(hub, "alpha")
    _project(hub, "beta")
    W.use(W._build(alpha, "test"))
    seen: list[str] = []

    class _Res:
        verdict, why, launch = "dry_run", "", ""

        def as_dict(self) -> dict[str, object]:
            return {"verdict": self.verdict}

    def fake_go(*_a: object, **_kw: object) -> _Res:
        seen.append(P.tag())
        return _Res()

    monkeypatch.setattr(GO, "go", fake_go)
    assert O.call("cloud.go", {"case": ["x"]}).ok
    assert O.call("cloud.go", {"case": ["x"], "for_project": "beta"}).ok
    assert O.call("cloud.go", {"case": ["x"], "for_project": ""}).ok
    assert seen == ["alpha", "beta", ""]
    env = O.call("cloud.go", {"case": ["x"], "for_project": "nobody"})
    assert not env.ok and "nobody" in env.error and len(seen) == 3


def test_library_takes_sources_of_every_project_from_anywhere(tmp_path: Path) -> None:
    """Бібліотека — шар Майстерні: джерела всіх канонів, звідки її не збирай.

    З кореня чистої Майстерні збірка падала «вкажіть проєкт» (картки джерел
    читались лише з поточного проєкту).
    """
    from nyshporka import library as L
    from nyshporka.models import Source
    from nyshporka.storage.files import write_entity

    hub = _hub(tmp_path, hub_only=True)
    for pid, sid in (("alpha", "S_XYZ_F1_D2"), ("beta", "S_XYZ_F1_D3")):
        path = _project(hub, pid) / "data" / "canonical" / "sources" / f"{sid}.md"
        path.parent.mkdir(parents=True)
        write_entity(path, Source(id=sid, type="book", title=f"Книга {pid}"))
    for where in (hub, hub / W.PROJECTS_DIR / "alpha"):
        W.reset()
        W.use(W._build(where, "test"))
        titles = sorted(e.title for e in L.build_library())
        assert titles == ["Книга alpha", "Книга beta"], where


def test_library_opens_from_a_pure_hub_without_verdicts(tmp_path: Path) -> None:
    """Вердикт — під ціль проєкту; у корені Майстерні бібліотека без них, не відмова."""
    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    hub = _hub(tmp_path, hub_only=True)
    _project(hub, "alpha")
    W.use(W._build(hub, "test"))
    assert L.load_verdicts() == {}
    assert LY.fingerprint()[1] == ""
    W.reset()
    W.use(W._build(hub / W.PROJECTS_DIR / "alpha", "test"))
    assert LY.fingerprint()[1].endswith("case_verdicts.json")
