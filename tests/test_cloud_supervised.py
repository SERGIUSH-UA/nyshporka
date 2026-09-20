"""🛰 Наглядацький шлях — без мережі, без грошей і без справжнього наглядача.

Наглядач тут підроблений: маленький скрипт, який відповідає тими самими
формами, що й `gpurunner htr …`. Перевіряється не він, а те, що ми йому
віддаємо й що робимо з його відповіддю, — тобто рівно ті місця, кожне з яких
у дослідницькому конвеєрі вже одного разу коштувало грошей або роботи:

* архів ассетів іменується за ВМІСТОМ: інший раннер — інше ім'я;
* у плані, який поїде на машину, `case_dir` — ОРИГІНАЛЬНА тека кадрів;
* облік після забору дописуємо ми, бо наглядач не знає про наш простір;
* кошторис береться в того, хто орендуватиме, і рішення про гроші — наше;
* сухий прогін, брак балансу й стеля автозапуску не доходять до оренди;
* повторна команда при живому наглядачі не бере другої машини.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from test_cloud_go import Rent, _make_case
from test_cloud_run import FakeSession

from nyshporka.cloud import go as GO
from nyshporka.cloud import run as RUN
from nyshporka.cloud import state as ST
from nyshporka.cloud import supervised as SUP

pytest.importorskip("PIL.Image")

#: Підроблений наглядач: ті самі підкоманди й ті самі форми відповіді.
FAKE = r'''
import json, sys
from pathlib import Path

args = sys.argv[1:]
log = Path(sys.argv[0]).with_name("calls.jsonl")
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(args, ensure_ascii=False) + "\n")
cfg = json.loads(Path(sys.argv[0]).with_name("cfg.json").read_text("utf-8"))


def opt(name, default=""):
    return args[args.index(name) + 1] if name in args else default


if args[:2] == ["htr", "plan"]:
    out = Path(opt("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "cases": [{"case_dir": opt("--case"), "case_key": opt("--case-key"),
                   "name": opt("--name"), "out_dir": opt("--out-root")}],
        "model": opt("--model"), "voices": opt("--voices"),
        "assets": opt("--assets"), "disk_gb": opt("--disk"),
    }, ensure_ascii=False), encoding="utf-8")
    sys.exit(0)

if args[:2] == ["htr", "preflight"]:
    sys.exit(cfg.get("preflight_rc", 0))

if args[:2] == ["htr", "supervise"] and "--dry-run" in args:
    print(json.dumps(cfg["estimate"]))
    sys.exit(0)

if args[:2] == ["htr", "supervise"]:
    sys.exit(cfg.get("detach_rc", 0))

if args[:2] == ["htr", "state"]:
    state = cfg.get("state")
    if state is None:
        sys.exit(1)
    print(json.dumps(state, ensure_ascii=False, indent=1))
    sys.exit(0)

if args[:2] in (["htr", "stop"], ["htr", "wrap-up"]):
    print(cfg.get("stop_say") or "зупиняю")
    sys.exit(cfg.get("stop_rc", 0))

sys.exit(9)
'''

@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    """Простір дослідження — увесь у тимчасовій теці."""
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return tmp_path


ESTIMATE = {"credit": 25.0, "pages": 3, "lines_per_page": 24.0, "empty": False,
            "candidates": 7,
            "best": {"gpu": "RTX 3090", "num_gpus": 1, "dph": 0.10,
                     "pages_per_hour": 900, "hours": 0.5, "cost": 0.40,
                     "usd_per_1000": 0.11}}


@pytest.fixture
def fake_gpurunner(tmp_path: Path, monkeypatch):
    """Підроблений наглядач + спосіб міняти його відповіді з тесту."""
    home = tmp_path / "fake_gr"
    home.mkdir()
    script = home / "gr.py"
    script.write_text(FAKE, encoding="utf-8")
    cfg = home / "cfg.json"

    class Fake:
        def __init__(self) -> None:
            self.set(estimate=ESTIMATE)

        def set(self, **kw: Any) -> None:
            cfg.write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")

        @property
        def calls(self) -> list[list[str]]:
            log = home / "calls.jsonl"
            if not log.is_file():
                return []
            return [json.loads(x) for x in log.read_text("utf-8").splitlines() if x]

        def called(self, *head: str) -> list[list[str]]:
            return [c for c in self.calls if c[:len(head)] == list(head)]

    fake = Fake()
    monkeypatch.setattr(SUP, "gpurunner_cmd", lambda: [sys.executable, str(script)])
    return fake


def _wire(space: Path, monkeypatch, **kw: Any) -> tuple[Path, Rent]:
    """Справа, бойові ваги й бекенд, що «орендує», — усе фейкове."""
    from nyshporka.htr import run as R

    case = _make_case(space)
    model = space / "data" / "spotter" / "models" / "model_v1.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"\0" * 16)
    monkeypatch.setattr(R, "pick_model", lambda script, second_voice=True: (model, None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("ARCH/1/2", "тест"))
    backend = Rent(space / "box", FakeSession(space / "box"), **kw)
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)
    return case, backend


def _go(case: Path, **kw: Any) -> GO.GoResult:
    kw.setdefault("backend", "fake")
    kw.setdefault("script", "cyrillic")
    return GO.go(str(case), **kw)


def _plan_of(fake: Any) -> dict[str, Any]:
    call = fake.called("htr", "plan")[0]
    return json.loads(Path(call[call.index("--out") + 1]).read_text("utf-8"))


# ── архів ассетів ────────────────────────────────────────────────────────────
def test_assets_name_follows_content_not_version(tmp_path: Path) -> None:
    """🔴 Ім'я за вмістом: старий раннер на боксі колись зробив флот утричі
    повільнішим, і жодна версія моделі цього не показувала."""
    model = tmp_path / "model_v1.pt"
    model.write_bytes(b"\x01\x02")
    runner = tmp_path / "runner.py"
    runner.write_text("стара версія", encoding="utf-8")
    items = [("models/model_v1.pt", model), ("scripts/htr_case_run.py", runner)]
    first = SUP.assets_name(items, stem="model_v1")

    assert SUP.assets_name(items, stem="model_v1") == first, "той самий вміст — те саме ім'я"
    runner.write_text("нова версія", encoding="utf-8")
    assert SUP.assets_name(items, stem="model_v1") != first, \
        "інший раннер мусить дати інше ім'я — інакше на боксі опиниться старий"


def test_assets_built_once_and_reused(tmp_path: Path) -> None:
    model = tmp_path / "m.pt"
    model.write_bytes(b"1")
    items = [("models/m.pt", model)]
    dest = tmp_path / "out"
    first = SUP.build_assets(items, dest, stem="m")
    stamp = first.stat().st_mtime_ns
    again = SUP.build_assets(items, dest, stem="m")
    assert again == first and again.stat().st_mtime_ns == stamp, \
        "готовий архів не перезбирається"
    assert not list(dest.glob("*.part")), "недозбираних хвостів не лишається"


def test_missing_weights_are_named(tmp_path: Path) -> None:
    with pytest.raises(SUP.SupervisorMissing) as got:
        SUP.build_assets([("models/m.pt", tmp_path / "нема.pt")], tmp_path, stem="m")
    assert "нема.pt" in str(got.value)


# ── що саме віддаємо наглядачеві ─────────────────────────────────────────────
def test_detached_launch_hands_over_plan_and_remembers_session(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    res = _go(case)

    assert res.verdict == "detached" and res.exit_code == 0
    assert fake_gpurunner.called("htr", "preflight"), "передполіт — до оренди"
    launches = [c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c]
    assert len(launches) == 1, "рівно один пуск наглядача"
    assert "--budget" in launches[0] and "--max-hours" in launches[0], \
        "обидві стелі їдуть наглядачеві: без них він не спиниться ні на чому"

    st = ST.load(res.run_id)
    assert st is not None and st.supervisor, "захід записано як відчеплений"
    assert not st.box and not st.needs_release, \
        "машини в нашому записі немає — її бере й гасить наглядач"
    assert Path(st.supervisor_plan).is_file(), "план лишається на диску"


def test_plan_points_at_original_frames_and_carries_bookkeeping(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 `case_dir` — оригінал: кроп зі стиснутої копії вдвічі дрібніший, а
    дивиться на нього око. Облік дописуємо ми: наглядач про наш простір не знає."""
    case, _ = _wire(space, monkeypatch)
    monkeypatch.setattr(SUP, "nysh_exe", lambda: str(space / "nysh"))
    _go(case)

    plan = _plan_of(fake_gpurunner)
    assert plan["cases"][0]["case_dir"] == str(case.resolve())
    hooks = plan["post_fetch"]
    assert [h["cmd"][1:] for h in hooks] == [["cases", "build"],
                                             ["text", "index", "--case", case.name]]
    assert all(Path(h["cmd"][0]).is_absolute() for h in hooks), \
        "відчеплений процес не має ні нашого PATH, ні нашої робочої теки"


def test_case_key_and_run_name_go_to_the_supervisor(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """Без шифри прогін стає «нічиїм», а без імені — лягає в теку з іншої теки."""
    case, _ = _wire(space, monkeypatch)
    res = _go(case)

    call = fake_gpurunner.called("htr", "plan")[0]
    assert call[call.index("--case-key") + 1] == "ARCH/1/2"
    assert call[call.index("--name") + 1] == Path(res.out_dir).name
    assert Path(call[call.index("--out-root") + 1]) == Path(res.out_dir).parent
    # 🔴 Планка ядер — 16, а не типові для наглядача 64: машини на 64 ядра на
    # ринку може не бути взагалі, і захід стоїть у марному чеканні.
    assert float(call[call.index("--prefer-cores") + 1]) == 16.0
    assert call[call.index("--expect-script") + 1].startswith(SUP.RUNNER_ARCNAME + "="), \
        "раннер в архіві звіряється з локальним побайтно"


# ── гроші: рішення наше, кошторис — того, хто орендує ────────────────────────
def test_dry_run_never_reaches_the_supervisor(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    res = _go(case, dry_run=True)

    assert res.verdict == "dry_run" and res.exit_code == 0
    assert res.fork_low == 0.40, "вилка порахована з кошторису наглядача"
    assert not [c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c], "сухий прогін не орендує"


def test_above_ceiling_waits_for_a_human(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    fake_gpurunner.set(estimate={**ESTIMATE,
                                 "best": {**ESTIMATE["best"], "cost": 4.0}})
    res = _go(case)

    assert res.verdict == "needs_confirm" and res.exit_code == 10
    assert not [c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c]

    res2 = _go(case, confirm=True)
    assert res2.verdict == "detached", "дозвіл людини знімає стелю автозапуску"


def test_no_credit_stops_before_rent(space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    fake_gpurunner.set(estimate={**ESTIMATE, "credit": 0.10})
    res = _go(case, confirm=True)

    assert res.verdict == "no_credit" and res.exit_code == 8
    assert not [c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c], "на порожній рахунок машини не беруть"


def test_empty_market_is_not_a_crash(space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    fake_gpurunner.set(estimate={"empty": True, "reason": "усе дорожче за стелю",
                                 "credit": 25.0})
    res = _go(case)

    assert res.verdict == "market_empty" and res.exit_code == 6
    assert "дорожче" in res.why


def test_preflight_failure_stops_before_rent(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    fake_gpurunner.set(estimate=ESTIMATE, preflight_rc=1)
    res = _go(case)

    assert res.verdict == "refused" and res.exit_code == 2
    assert not fake_gpurunner.called("htr", "supervise"), \
        "після провального передполіту навіть кошторису не питають"


def test_unclear_detach_leaves_the_run_accountable(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 «Не стартував» означає лише, що наглядач не доповів вчасно, — процес
    при цьому може бути живий і піти орендувати машину. Видалений запис зробив
    би таку оренду невидимою для `state`, `stop` і наступного `go`."""
    case, _ = _wire(space, monkeypatch)
    fake_gpurunner.set(estimate=ESTIMATE, detach_rc=3)
    res = _go(case)

    assert res.verdict == "refused"
    assert "rent status" in res.why, "людині сказано, чим перевірити машину"
    st = ST.load(res.run_id)
    assert st is not None and st.supervisor, "захід лишається підзвітним"
    assert st.phase == "failed"
    assert any(i.get("kind") == "detach_unclear" for i in st.incidents)


# ── повторний виклик і стан ──────────────────────────────────────────────────
def test_second_call_does_not_rent_a_second_machine(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Повторити команду після обриву термінала — звична дія. Друга машина
    під ту саму справу коштує рівно стільки ж, скільки перша."""
    case, _ = _wire(space, monkeypatch)
    first = _go(case)
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": "s", "phase": "running", "why": "читає"})

    second = _go(case)
    assert second.verdict == "refused"
    assert "наглядач" in second.why
    assert len([c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c]) == 1
    assert ST.load(first.run_id) is not None


def test_finished_supervisor_frees_the_case(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    first = _go(case)
    was = ST.load(first.run_id)
    assert was is not None
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": "s", "phase": "done", "verdict": "ok",
                              "why": "готово"})

    # Спершу — сам розбір: завершений наглядач мусить закрити НАШ запис, інакше
    # він вічно виглядав би як «читає» в кожному `nysh cloud state`.
    assert SUP.find_live([first.run_id]) is None
    closed = ST.load(first.run_id)
    assert closed is not None and closed.phase == "done"

    second = _go(case, rerun=True)
    assert second.verdict == "detached", "завершений захід більше не тримає справу"
    now = ST.load(second.run_id)
    assert now is not None and now.supervisor != was.supervisor, \
        "це вже інший наглядач, а не підхоплений старий"


def test_state_and_stop_ask_the_supervisor(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    res = _go(case)
    st = ST.load(res.run_id)
    assert st is not None

    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": st.supervisor, "phase": "running",
                              "why": "читає", "budget": {"spent_usd": 0.03,
                                                         "budget_usd": 0.60}})
    data = SUP.state_of(st)
    assert data["phase"] == "running", "багаторядковий JSON наглядача теж читається"

    got = SUP.stop(st)
    assert got.ok and "зупиняю" in got.said
    assert fake_gpurunner.called("htr", "wrap-up"), "згортає саме наглядач"


def test_cli_state_shows_what_the_supervisor_says(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Прохання наглядача до людини мусить бути видно ОДРАЗУ: поки воно
    лежить у журналі, машина тарифікується."""
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C

    case, _ = _wire(space, monkeypatch)
    res = _go(case)
    fake_gpurunner.set(estimate=ESTIMATE, state={
        "session": "s", "phase": "running", "why": "читає",
        "budget": {"cap_usd": 0.5, "spent_usd": 0.03, "max_hours": 4.0,
                   "elapsed_h": 0.2},
        "cases": [{"case": "c", "pages_done": 3, "n_pages_expected": 5,
                   "pages_per_hour": 640.0, "status": "running"}],
        "box": {"gpu": "RTX 3060", "label": "nysh-1"},
        "human_action_required": True, "human_action": "поповнити баланс"})

    got = CliRunner().invoke(C.app, ["state", res.run_id])
    assert got.exit_code == 0, got.output
    assert "3 з 5" in got.output and "RTX 3060" in got.output
    assert "$0.03 з $0.50" in got.output
    assert "потрібна людина" in got.output and "поповнити баланс" in got.output


def test_thin_path_stays_available(space: Path, monkeypatch, fake_gpurunner) -> None:
    """`--thin` не ходить до наглядача взагалі — інакше своя машина по SSH
    вимагала б пакета оренди."""
    case, backend = _wire(space, monkeypatch, cost=None, balance=None)
    res = _go(case, thin=True, dry_run=True)

    assert res.verdict != "detached"
    assert not fake_gpurunner.calls, "тонкий шлях наглядача не турбує"
    assert backend.estimates == 1, "кошторис для нього питається в бекенда"


def test_prepare_refuses_to_rent_a_machine(space: Path, monkeypatch) -> None:
    """🔴 `acquire` на орендному бекенді — це ОРЕНДА, а гасити її в `prepare`
    нічим: команда закінчується, а лічильник іде."""
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C
    from nyshporka.cloud import registry as REG

    backend = Rent(space / "box", FakeSession(space / "box"))
    backend.id = "vast"
    monkeypatch.setattr(REG, "load", lambda: REG.Registry(backends={"vast": backend}))
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)

    got = CliRunner().invoke(C.app, ["prepare", "будь-яка", "-b", "vast"])
    assert got.exit_code == 2, got.output
    assert backend.acquired == 0, "машини навіть не торкнулись"
    assert "cloud go" in got.output, "людині сказано, як зробити те, що вона хотіла"


# ── згортання відчепленого заходу ────────────────────────────────────────────
def test_stop_asks_the_supervisor_to_finish_not_to_die(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Убити наглядача — означає лишити машину горіти без нікого, хто її
    погасить: гасити її нам нічим, бо в нашому записі її немає. Тому типово ми
    спиняємо РОБОТУ, а захід він доводить до кінця сам."""
    case, _ = _wire(space, monkeypatch)
    res = _go(case)
    st = ST.load(res.run_id)
    assert st is not None
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": st.supervisor, "phase": "running",
                              "box": {"instance_id": "777"}})

    got = SUP.stop(st)
    assert got.ok and not got.killed
    assert fake_gpurunner.called("htr", "wrap-up"), \
        "просимо ЗГОРНУТИ захід, а не вбити наглядача"
    assert not fake_gpurunner.called("htr", "stop")
    assert got.machine == "777", "машину треба назвати людині"

    forced = SUP.stop(st, force=True)
    assert forced.ok and forced.killed
    assert fake_gpurunner.called("htr", "stop")


def test_stop_does_not_swallow_the_warning_about_a_live_machine(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Попередження наглядача багаторядкове, і останнім рядком у ньому йде
    порада про чекпоінти — зрізання хвоста викидало саме те речення, заради
    якого команду й читають."""
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C

    case, _ = _wire(space, monkeypatch)
    res = _go(case)
    st = ST.load(res.run_id)
    assert st is not None
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": st.supervisor, "phase": "running",
                              "box": {"instance_id": "777"}},
                       stop_say="⚠ бокс machine 42 міг лишитись живим\n"
                                "  gpurunner htr fetch-ckpt --plan <план>")

    got = CliRunner().invoke(C.app, ["stop", res.run_id, "--force"])
    assert "міг лишитись живим" in got.output, "попередження мусить дійти цілим"
    assert "rent status" in got.output, "людині сказано, чим перевірити"
    assert "777" in got.output, "і який саме інстанс шукати"


def test_fetch_and_verify_refuse_on_a_detached_run(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 `verify` поверх живого відчепленого заходу ставив йому вирок
    `incomplete` → фаза `failed` → захід зникав з усіх переліків, і наступний
    `go` брав ДРУГУ машину під ту саму справу."""
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C

    case, _ = _wire(space, monkeypatch)
    res = _go(case)
    runner = CliRunner()

    for cmd in (["verify", res.run_id], ["fetch", res.run_id]):
        got = runner.invoke(C.app, cmd)
        assert got.exit_code == 2, got.output
        assert "наглядач" in got.output

    st = ST.load(res.run_id)
    assert st is not None and st.phase == "running", \
        "захід лишається живим — інакше наступний go візьме другу машину"


def test_silent_supervisor_is_not_taken_for_an_absent_one(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Мовчання не означає «заходу немає»: наглядач міг саме перезаписувати
    стан, а машина працює. Друга оренда коштує рівно стільки ж, що й перша."""
    case, _ = _wire(space, monkeypatch)
    first = _go(case)
    fake_gpurunner.set(estimate=ESTIMATE)      # `state` немає → наглядач мовчить

    second = _go(case, rerun=True)
    assert second.verdict == "refused"
    assert "мовчить" in second.why and "rent status" in second.why
    assert len([c for c in fake_gpurunner.called("htr", "supervise")
                if "--detach" in c]) == 1, "другої машини не взято"
    assert ST.load(first.run_id) is not None


def test_our_detached_machine_is_not_reported_as_a_stranger(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Машини відчепленого заходу в нашому записі немає — її тримає
    наглядач. Доти вона звітувала як «не з заходів цього простору», тобто
    власний живий захід виглядав чужою забутою орендою — найгірша з можливих
    неправд у команді, яку читають саме щоб вирішити, що гасити."""
    from typer.testing import CliRunner

    from nyshporka.cloud import cli as C
    from nyshporka.cloud import registry as REG

    case, backend = _wire(space, monkeypatch)
    backend.id = "vast"
    monkeypatch.setattr(REG, "load", lambda: REG.Registry(backends={"vast": backend}))
    res = _go(case)
    st = ST.load(res.run_id)
    assert st is not None
    fake_gpurunner.set(estimate=ESTIMATE,
                       state={"session": st.supervisor, "phase": "running",
                              "box": {"instance_id": "777"}})
    backend.status_data["burning"] = [{"instance_id": "777", "dph_total": 0.16,
                                       "label": "htr_case", "gpu_name": "V100",
                                       "status": "running"}]

    got = CliRunner().invoke(C.app, ["rent", "status"])
    assert "НЕ з заходів цього простору" not in got.output, got.output
    assert res.run_id in got.output, "машина названа своїм заходом"
    assert got.exit_code == 0, "своя машина — не привід для тривоги"
