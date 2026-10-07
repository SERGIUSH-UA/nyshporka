"""🚚 Партія на кілька машин (`nysh cloud go … --boxes N`) — без мережі й грошей.

01.10.2026 агент, якому людина дала одне рішення на 33 справи й $20, не мав
у пакеті спільної стелі на кілька машин і написав власний диспетчер оренд:
13 робочих оренд там, де вистачило б трьох, і свій облік загальної суми.

* поділ рівний за ОБСЯГОМ роботи, а не за кількістю справ;
* рішення про гроші ОДНЕ на партію, і дозвіл людини теж один;
* загальна стеля ділиться так, що кожна черга дістає щонайменше свій прогноз;
* зайнята справа в черзі випадає, а не валить чергу;
* черга, що не стартувала, не гасить пущених;
* стан і згортання партії йдуть до кожного наглядача.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_cloud_supervised as _S
from test_cloud_supervised import ESTIMATE, _go, _second_case, _wire

from nyshporka.cloud import batch as BT
from nyshporka.cloud import money as M
from nyshporka.cloud import state as ST
from nyshporka.cloud import supervised as SUP

pytest.importorskip("PIL.Image")

# Фікстури наглядача — ті самі, що в його тестах.
space = _S.space
fake_gpurunner = _S.fake_gpurunner


def _leg(name: str, frames: int, lines: float | None = None,
         left: int | None = None) -> Any:
    plan = SimpleNamespace(frames=frames, pages_left=left, lines_per_page=lines)
    return SimpleNamespace(name=name, plan=plan)


def _cases(space: Path, monkeypatch, n: int) -> list[str]:
    first, _ = _wire(space, monkeypatch)
    return [str(first), *(str(_second_case(space, f"справа-{i}")) for i in range(1, n))]


def _detached(fake: Any) -> list[list[str]]:
    return [c for c in fake.called("htr", "supervise") if "--detach" in c]


# ── поділ ────────────────────────────────────────────────────────────────────
def test_split_balances_work_not_case_count() -> None:
    """Три тонкі справи важать як одна товста: машина з «трьома справами» інакше
    читала б утричі довше за сусідку, а платили б ми за її хвіст."""
    legs = [_leg("товста", 3000), _leg("a", 1000), _leg("b", 1000), _leg("c", 1000)]
    queues = BT.split(legs, 2)
    loads = sorted(sum(leg.plan.frames for leg in q) for q in queues)
    assert loads == [3000, 3000]


def test_split_weighs_density_and_keeps_named_order() -> None:
    """Сторінка сповідки коштує вдвічі більше за метрику; невідома щільність
    береться медіаною відомих. Усередині черги — порядок команди."""
    legs = [_leg("густа", 1000, 80), _leg("x", 1000, 40), _leg("y", 1000, 40),
            _leg("z", 1000, None)]
    queues = BT.split(legs, 2)
    # густа (80k) ≈ x+y (40k+40k); z (40k за медіаною) — у будь-яку з рівних
    assert [leg.name for leg in queues[0]] == ["густа", "z"]
    assert [leg.name for leg in queues[1]] == ["x", "y"]
    weights = BT.weights(legs)
    assert weights[3] == 1000 * 40, "невідома щільність — медіана відомих"


def test_split_never_makes_empty_queues() -> None:
    assert len(BT.split([_leg("a", 10), _leg("b", 10)], 5)) == 2


def test_split_counts_only_pages_left() -> None:
    """Дочитка: важить те, що машина справді читатиме."""
    w = BT.weights([_leg("a", 2000, 30, left=100)])
    assert w == [100 * 30]


def test_share_budget_gives_every_queue_its_forecast_first() -> None:
    """🔴 Черга, якій дали менше за прогноз, спиниться на грошах посеред
    роботи — з оплаченою заливкою й недочитаною справою."""
    forks = [(1.0, 2.5), (0.2, 0.5), (0.4, 0.7)]
    shares = BT.share_budget(2.0, forks)
    assert all(s >= low for s, (low, _h) in zip(shares, forks, strict=True))
    assert abs(sum(shares) - 2.0) < 0.02


# ── рішення про гроші ────────────────────────────────────────────────────────
def test_batch_under_one_ceiling_needs_one_confirm(space: Path, monkeypatch,
                                                   fake_gpurunner) -> None:
    """🔴 Кожна черга окремо — під стелею автозапуску, партія — понад неї.
    Рішення по чергах пустило б партію без людини шматками; тут воно одне."""
    cases = _cases(space, monkeypatch, 3)
    _low, high = M.budget_fork(ESTIMATE["best"]["cost"], density_known=True)
    assert high <= M.DEFAULT_AUTOSTART_MAX_USD < 3 * high, "передумова тесту"

    got = _go(cases, boxes=3)
    assert (got.verdict, got.exit_code) == ("needs_confirm", 10), got.why
    assert not _detached(fake_gpurunner), "жодна черга не стартує без людини"
    assert len(fake_gpurunner.called("htr", "plan")) == 3, "порахована вся партія"
    assert got.fork_high == pytest.approx(3 * high)

    ok = _go(cases, boxes=3, confirm=True)
    assert ok.verdict == "detached", ok.why
    assert len(_detached(fake_gpurunner)) == 3, "один дозвіл — усі черги"


def test_batch_dry_run_rents_nothing_and_shows_queues(space: Path, monkeypatch,
                                                      fake_gpurunner) -> None:
    cases = _cases(space, monkeypatch, 4)
    got = _go(cases, boxes=2, dry_run=True)
    assert got.verdict == "dry_run", got.why
    assert not _detached(fake_gpurunner)
    assert len(got.queues) == 2
    assert sorted(len(q["cases"]) for q in got.queues) == [2, 2]
    assert got.as_dict()["queues"] == got.queues
    assert not BT.all_batches(), "сухий прогін партії не пише"


def test_total_budget_is_split_and_too_small_is_refused(space: Path, monkeypatch,
                                                        fake_gpurunner) -> None:
    cases = _cases(space, monkeypatch, 2)
    low, _high = M.budget_fork(ESTIMATE["best"]["cost"], density_known=True)

    poor = _go(cases, boxes=2, budget=low * 2 - 0.1, confirm=True)
    assert poor.verdict == "refused" and "бракує" in poor.why, poor.why
    assert not _detached(fake_gpurunner)

    got = _go(cases, boxes=2, budget=1.5, confirm=True)
    assert got.verdict == "detached", got.why
    budgets = [float(c[c.index("--budget") + 1]) for c in _detached(fake_gpurunner)]
    assert sum(budgets) == pytest.approx(1.5, abs=0.02)
    assert all(b >= low for b in budgets)


def test_batch_record_and_every_case_know_the_batch(space: Path, monkeypatch,
                                                    fake_gpurunner) -> None:
    cases = _cases(space, monkeypatch, 3)
    got = _go(cases, boxes=2, confirm=True)
    assert got.batch_id
    rec = BT.load(got.batch_id)
    assert rec is not None and len(rec.queues) == 2
    assert all(q["started"] and q["session"] for q in rec.queues)
    runs = ST.all_runs()
    assert len(runs) == 3 and all(s.batch == got.batch_id for s in runs)
    # сусіди — лише в межах своєї черги: наглядачі й машини в черг різні
    for s in runs:
        queue = next(q for q in rec.queues if s.run_id in q["run_ids"])
        assert sorted(s.siblings) == sorted(i for i in queue["run_ids"] if i != s.run_id)
    assert len({s.supervisor for s in runs}) == 2


def test_one_box_keeps_the_single_queue(space: Path, monkeypatch,
                                        fake_gpurunner) -> None:
    """`--boxes 1` (типове) — рівно та сама черга, що й до партій."""
    cases = _cases(space, monkeypatch, 3)
    got = _go(cases, dry_run=True)
    assert not got.queues and not got.batch_id
    assert len(fake_gpurunner.called("htr", "plan")) == 1


def test_queue_that_would_hit_the_hours_ceiling_is_refused(space: Path, monkeypatch,
                                                           fake_gpurunner) -> None:
    cases = _cases(space, monkeypatch, 2)
    fake_gpurunner.set(estimate={**ESTIMATE, "best": {**ESTIMATE["best"], "hours": 11.0}})
    got = _go(cases, boxes=2, confirm=True)
    assert got.verdict == "refused" and "--boxes 3" in got.why, got.why
    assert not _detached(fake_gpurunner)


# ── збої ─────────────────────────────────────────────────────────────────────
def test_a_failed_queue_does_not_kill_the_started_ones(space: Path, monkeypatch,
                                                       fake_gpurunner) -> None:
    """🔴 Пущену чергу веде наглядач; гасити її тому, що сусідня не стартувала,
    — значить лишити оплачену машину без господаря або вбити живу роботу."""
    from nyshporka.cloud.go import GoRefused

    cases = _cases(space, monkeypatch, 2)
    real = SUP.start
    calls = {"n": 0}

    def flaky(*a: Any, **kw: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise GoRefused("наглядач не доповів про старт")
        real(*a, **kw)

    monkeypatch.setattr(SUP, "start", flaky)
    got = _go(cases, boxes=2, confirm=True)
    assert (got.verdict, got.exit_code) == ("partial_start", 11), got.why
    assert [q["started"] for q in got.queues] == [True, False]
    assert "не доповів" in got.queues[1]["why"]
    rec = BT.load(got.batch_id)
    assert rec is not None and [q["started"] for q in rec.queues] == [True, False]
    assert not fake_gpurunner.called("htr", "stop")
    assert not fake_gpurunner.called("htr", "wrap-up")


def test_busy_case_drops_out_of_a_queue(space: Path, monkeypatch,
                                        fake_gpurunner) -> None:
    """Зайнята справа випадає з черги, решта їде. Доти вона валила всю чергу,
    і довга черга не їхала через одну справу."""
    cases = _cases(space, monkeypatch, 3)
    first = _go(cases[0])
    assert first.verdict == "detached", first.why
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": "s", "phase": "running", "why": "читає"})

    got = _go(cases, dry_run=True)
    assert got.verdict == "dry_run", got.why
    assert [c.case_dir for c in got.cases] == cases[1:]
    assert any(first.run_id in n for n in got.notes), "причина названа: який захід її веде"


def test_all_busy_is_still_a_refusal(space: Path, monkeypatch, fake_gpurunner) -> None:
    cases = _cases(space, monkeypatch, 2)
    first = _go(cases)
    assert first.verdict == "detached", first.why
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": "s", "phase": "running", "why": "читає"})
    again = _go(cases)
    assert (again.verdict, again.exit_code) == ("refused", 2), again.why
    assert len(_detached(fake_gpurunner)) == 1, "другої машини не беруть"


# ── стан і згортання ─────────────────────────────────────────────────────────
def test_state_and_stop_reach_every_queue(space: Path, monkeypatch,
                                          fake_gpurunner) -> None:
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C

    cases = _cases(space, monkeypatch, 3)
    got = _go(cases, boxes=2, confirm=True)
    fake_gpurunner.set(estimate=ESTIMATE, state={
        "session": "s", "phase": "running",
        "budget": {"spent_usd": 0.25},
        "cases": [{"case": "x", "pages_done": 3}]})

    shown = CliRunner().invoke(C.app, ["state", "--batch", got.batch_id, "--json"])
    assert shown.exit_code == 0, shown.output
    data = json.loads(shown.output)
    assert data["summary"]["spent_usd"] == pytest.approx(0.5)
    assert data["summary"]["live"] == 2

    stopped = CliRunner().invoke(C.app, ["stop", "--batch", got.batch_id])
    assert stopped.exit_code == 0, stopped.output
    assert len(fake_gpurunner.called("htr", "wrap-up")) == 2


def test_unknown_batch_is_named(space: Path, fake_gpurunner) -> None:
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C

    got = CliRunner().invoke(C.app, ["state", "--batch", "batch-нема"])
    assert got.exit_code == 2 and "немає" in got.output


def test_a_retry_does_not_rewrite_the_old_batch(space: Path, monkeypatch,
                                                fake_gpurunner) -> None:
    """🔴 Повторний захід тих самих справ переписує `supervisor` у записі справи
    (ідентифікатор детермінований). 06.10.2026 стара партія після retry почала
    показувати 607 кадрів НОВОЇ сесії при своїх нулі — витрати й сторінки
    склалися б двічі. Наглядача питаємо за сесією, записаною в партії."""
    cases = _cases(space, monkeypatch, 3)
    got = _go(cases, boxes=2, confirm=True)
    rec = BT.load(got.batch_id)
    assert rec is not None
    first = rec.queues[0]["session"]
    st = ST.load(rec.queues[0]["run_ids"][0])
    assert st is not None
    st.supervisor = "htr-retry-session"          # як після повторного запуску
    ST.save(st)
    asked: list[str] = []
    monkeypatch.setattr(SUP, "state_of_session",
                        lambda s: asked.append(s) or {"session": s, "phase": "finished"})

    rows = BT.queue_states(rec)
    assert asked[0] == first, "стару партію спитали про чужу сесію"
    assert "htr-retry-session" not in asked
    assert rows[0][1]["retried_by"] == "htr-retry-session"
