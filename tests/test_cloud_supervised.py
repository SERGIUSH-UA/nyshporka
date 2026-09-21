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


def opts(name):
    """УСІ входження прапорця, у порядку: справи й параметри йдуть списками."""
    return [args[i + 1] for i, a in enumerate(args) if a == name and i + 1 < len(args)]


if args[:2] == ["htr", "plan"]:
    out = Path(opt("--out"))
    out.parent.mkdir(parents=True, exist_ok=True)
    cases, keys = opts("--case"), opts("--case-key")
    names, seeds = opts("--name"), opts("--seed-seg")
    # 🔴 Фейк відмовляє там само, де справжній наглядач: інакше тест на
    # порядок списків пройшов би на дублі, який цього правила не знає.
    for label, got in (("--case-key", keys), ("--name", names), ("--seed-seg", seeds)):
        if got and len(got) != len(cases):
            print(f"{label}: {len(got)} проти {len(cases)} справ", file=sys.stderr)
            sys.exit(2)
    if any(seeds) and opt("--transport", "auto") == "box":
        print("--seed-seg потребує сховища: склад на машині з'являється "
              "аж після оренди", file=sys.stderr)
        sys.exit(2)
    out.write_text(json.dumps({
        "cases": [{"case_dir": c,
                   "case_key": keys[i] if keys else "",
                   "name": names[i] if names else "",
                   "seed_seg": seeds[i] if seeds else "",
                   "out_dir": opt("--out-root")} for i, c in enumerate(cases)],
        "model": opt("--model"), "voices": opt("--voices"),
        "assets": opt("--assets"), "disk_gb": opt("--disk"),
        "transport": opt("--transport", "auto"), "params": opts("-p"),
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


def _go(case: Path | str | list[str], **kw: Any) -> GO.GoResult:
    kw.setdefault("backend", "fake")
    kw.setdefault("script", "cyrillic")
    if isinstance(case, (str, Path)):
        return GO.go(str(case), **kw)
    return GO.go([str(c) for c in case], **kw)


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


# ── параметри роботи, які їдуть на машину ────────────────────────────────────
def test_the_script_of_the_plan_always_reaches_the_box(space: Path, monkeypatch,
                                                       fake_gpurunner) -> None:
    """🔴 Письмо доїжджає до машини, а не лишається вдома.

    Раннер на боксі бере письмо з параметра роботи, і без нього чесно ставить
    «cyrillic». Тобто `--script latin` мінявся лише в нашому плані: на машину
    їхали правильні ваги, а в меті прогону писалось не те письмо — і на цю
    мету дивиться і розмітка, і відбір корпусу, і людина, що потім гадає, чому
    латинська справа позначена кирилицею. Знайдено 21.09.2026 при перенесенні.
    """
    case, _ = _wire(space, monkeypatch)
    _go(case, script="latin", dry_run=True)
    assert "script=latin" in _plan_of(fake_gpurunner)["params"]


def test_a_user_param_overrides_the_one_we_computed(space: Path, monkeypatch,
                                                    fake_gpurunner) -> None:
    """Наш параметр — здогад, людський — рішення. Наглядач збирає `-p` у
    словник, тож переможе останній: наші йдуть першими, і саме тому людський
    їх перекриває, а не навпаки."""
    case, _ = _wire(space, monkeypatch)
    _go(case, script="cyrillic", dry_run=True, params=["script=mixed", "shards=6"])
    params = _plan_of(fake_gpurunner)["params"]
    assert params == ["script=mixed", "shards=6"], (
        "обчислений параметр не сміє дублювати людський: у словнику виграв би "
        "один із них, і який саме — залежало б від порядку")


def test_params_travel_in_the_order_they_were_given(space: Path, monkeypatch,
                                                    fake_gpurunner) -> None:
    case, _ = _wire(space, monkeypatch)
    _go(case, script="cyrillic", dry_run=True,
        params=["shards=6", "max_endpoints=600", "vram_gb_per_shard=3.0"])
    params = _plan_of(fake_gpurunner)["params"]
    assert params[0] == "script=cyrillic"
    assert params[1:] == ["shards=6", "max_endpoints=600", "vram_gb_per_shard=3.0"]


# ── перечитування через хмару: засів сегментації ─────────────────────────────
def _seed_ready(space: Path, case: Path, *, covered: int | None = None) -> Path:
    """Кеш сегментації першого прогону — придатний до засіву."""
    import gzip

    from nyshporka.htr import seg as SEG
    from nyshporka.htr.run import seg_cache_dir

    frames = SEG.frames_of(case)
    d = seg_cache_dir(case, space / "data" / "derived")
    d.mkdir(parents=True, exist_ok=True)
    for f in frames[:covered if covered is not None else len(frames)]:
        with gzip.open(d / f"{f.stem}.c400.seg.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"key": dict(SEG.EXPECTED_KEY), "lines": []}, fh)
    return d


def _named_model(space: Path, monkeypatch, name: str = "skryba_f792_v6.mlmodel") -> Path:
    from nyshporka.htr import run as R

    weights = space / "data" / "spotter" / "models" / name
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(b"\0" * 16)
    monkeypatch.setattr(R, "resolve_model", lambda spec: (weights, "latin"))
    return weights


def test_a_reread_hands_the_ready_segmentation_to_the_box(space: Path, monkeypatch,
                                                          fake_gpurunner) -> None:
    """💰 Сегментація — найдорожча частина сторінки. Коли вона вже порахована,
    везти її на машину означає читати вдвічі дешевше (18.4 → 9.1 с/стор).

    🔴 Засів їде ПЕРШИМ ЧЕКПОІНТОМ, а чекпоінти живуть у сховищі, тож транспорт
    тут мусить бути названий явно: на самій машині складу ще немає, бо немає
    машини.
    """
    case, _ = _wire(space, monkeypatch)
    _named_model(space, monkeypatch)
    seed = _seed_ready(space, case)

    _go(case, model="skryba_f792_v6.mlmodel", dry_run=True)
    plan = _plan_of(fake_gpurunner)
    assert plan["cases"][0]["seed_seg"] == str(seed)
    assert plan["transport"] == "r2"
    assert plan["cases"][0]["name"].endswith("-skryba_v6"), (
        "перечитування мусить лягти у СВОЮ теку: у теці першого прогону вже "
        "лежать тексти, і забір їх не перезаписує")


def test_a_full_cache_makes_the_fleet_denser(space: Path, monkeypatch,
                                             fake_gpurunner) -> None:
    """Шард без геометрії й sato бере вдвічі менше ядер — але тільки якщо
    сегментація є майже на всіх сторінках."""
    from nyshporka.htr import seg as SEG

    case, _ = _wire(space, monkeypatch)
    _named_model(space, monkeypatch)
    _seed_ready(space, case)

    _go(case, model="skryba_f792_v6.mlmodel", dry_run=True)
    params = _plan_of(fake_gpurunner)["params"]
    assert f"cores_per_shard={SEG.CORES_PER_SHARD_SEEDED}" in params
    assert f"vram_gb_per_shard={SEG.GB_PER_SHARD_SEEDED}" in params


def test_a_thin_cache_never_makes_the_fleet_denser(space: Path, monkeypatch,
                                                   fake_gpurunner) -> None:
    """🔴 Сторінка, якої в кеші немає, рахує геометрію повністю. Щільний флот
    на рідкому кеші душив би сам себе — тобто ми платили б за повільніше."""
    case, _ = _wire(space, monkeypatch)
    _named_model(space, monkeypatch)
    _seed_ready(space, case, covered=1)          # 1 із 3 — 33%

    _go(case, model="skryba_f792_v6.mlmodel", dry_run=True)
    params = _plan_of(fake_gpurunner)["params"]
    assert not [p for p in params if p.startswith("cores_per_shard=")]
    assert _plan_of(fake_gpurunner)["cases"][0]["seed_seg"], "сам засів лишається"


def test_without_a_bucket_the_reread_goes_unseeded_and_says_the_price(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Сховища немає — це не привід відмовляти, але й не привід мовчати.

    Засів без сховища неможливий за побудовою, тож захід їде без нього — і
    мусить сказати ЦІНУ: сторінка коштуватиме ще й сегментацію. Мовчазний
    відкат виглядав би як «усе гаразд», а рахунок прийшов би вдвічі більший.
    """
    case, _ = _wire(space, monkeypatch)
    _named_model(space, monkeypatch)
    _seed_ready(space, case)

    got = _go(case, model="skryba_f792_v6.mlmodel", dry_run=True, transport="box")
    assert got.verdict == "dry_run", got.why
    plan = _plan_of(fake_gpurunner)
    assert not plan["cases"][0]["seed_seg"]
    assert any("без засіву" in n for n in got.notes), got.notes


# ── черга справ на одній машині ──────────────────────────────────────────────
def _second_case(space: Path, name: str = "друга") -> Path:
    """Ще одна справа поруч із першою — з власним іменем теки."""
    import os
    import time

    from PIL import Image

    case = space / name
    case.mkdir(parents=True, exist_ok=True)
    old = time.time() - 3600
    for i in range(3):
        p = case / f"{i:04d}.jpg"
        Image.new("L", (40, 60), 200).save(p, "JPEG")
        os.utime(p, (old, old))
    return case


def test_a_batch_travels_as_one_plan_to_one_supervisor(space: Path, monkeypatch,
                                                       fake_gpurunner) -> None:
    """💰 Черга справ на одній машині дешевша за чергу машин: холодний старт —
    ~5 хвилин оренди плюс час на ринку, і платити його двічі немає за що.

    🔴 Ключ, ім'я прогону й засів зв'язуються зі справою ЛИШЕ за позицією, тож
    порядок списків перевіряється тут: зсув на одну позицію дав би справі чужу
    шифру, і виглядало б це як прочитана книга не тієї парафії.
    """
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)

    got = _go([str(first), str(second)], dry_run=True)
    assert got.verdict == "dry_run", got.why

    plan = _plan_of(fake_gpurunner)
    assert [c["case_dir"] for c in plan["cases"]] == [str(first), str(second)]
    assert [c["name"] for c in plan["cases"]] == [first.name, second.name]
    assert all(c["case_key"] == "ARCH/1/2" for c in plan["cases"])
    # один виклик плану, один наглядач, одна машина
    assert len(fake_gpurunner.called("htr", "plan")) == 1
    assert len(fake_gpurunner.called("htr", "supervise")) == 1


def test_a_batch_reports_every_case_and_leaves_the_top_fields_empty(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Верхні `run_id`/`out_dir` на партії ПОРОЖНІ.

    «Перша справа» на їхньому місці читається як відповідь про весь захід:
    агент подивився б в одну теку й вирішив, що решта загубилась. Порожнє поле
    ламається голосно й одразу, а правда лежить у `cases[]`.
    """
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)

    got = _go([str(first), str(second)], dry_run=True)
    assert (got.run_id, got.out_dir, got.case_dir, got.case_key) == ("", "", "", "")
    assert [c.case_dir for c in got.cases] == [str(first), str(second)]
    assert all(c.run_id for c in got.cases), "кожна справа має свій ідентифікатор"
    assert len({c.run_id for c in got.cases}) == 2
    assert got.pages_total == 6, "сторінки заходу — сума по справах"
    payload = got.as_dict()
    assert payload["run_ids"] == [c.run_id for c in got.cases]


def test_one_case_keeps_the_answer_it_always_had(space: Path, monkeypatch,
                                                 fake_gpurunner) -> None:
    """🔴 Одна справа мусить відповідати рівно так, як до появи партій.

    На ці поля спирається і скіл у пакеті, і пам'ять агентів, і
    `nysh cloud state <run_id>`. Партія — додавання, а не зміна.
    """
    case, _ = _wire(space, monkeypatch)
    got = _go(case, dry_run=True)
    assert got.run_id and got.out_dir and got.case_dir
    assert len(got.cases) == 1
    one = got.cases[0]
    assert (one.run_id, one.out_dir, one.case_dir) == (got.run_id, got.out_dir,
                                                       got.case_dir)


def test_two_cases_with_the_same_folder_name_are_refused_before_shrinking(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Колізія імен НЕ падає сама собою: вона тихо зливає кадри в один
    префікс сховища й перезаписує чужий декод.

    Наглядач її теж ловить — але вже після заливки, а на партії з тисяч кадрів
    це чверть години стискання й доставки перед відмовою. Тому перевірка тут,
    до першого байта.
    """
    first, _ = _wire(space, monkeypatch)
    twin = _second_case(space / "інший-архів", first.name)

    got = _go([str(first), str(twin)], dry_run=True)
    # Відмова, а не збій: помилку людини ми вміємо назвати, і вердикт має
    # казати саме це (`refused`, код 2).
    assert (got.verdict, got.exit_code) == ("refused", 2), got.why
    assert "спільне ім'я прогону" in got.why or "спільну теку" in got.why
    assert not fake_gpurunner.called("htr", "plan"), "плану не складали — і не везли"


def test_an_already_read_case_drops_out_and_the_rest_still_go(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """💰 Прочитана справа випадає з черги, а не валить захід.

    🔴 Відмовити всій партії тут було б пасткою: агент, який дістав «відмова»
    на черзі з трьох справ, де готова одна, майже напевно повторить команду з
    `--rerun` — і перечитає прочитане за гроші.
    """
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)
    from nyshporka.core.workspace import workspace

    done = workspace().htr_reports / first.name
    done.mkdir(parents=True, exist_ok=True)
    (done / "_htr_meta.json").write_text(json.dumps({
        "model": "model_v1.pt",
        "pages": {f"{i:04d}.jpg": {"lines": 20} for i in range(3)}}),
        encoding="utf-8")

    got = _go([str(first), str(second)], dry_run=True)
    assert got.verdict == "dry_run", got.why
    assert [c.case_dir for c in got.cases] == [str(second)]
    assert any("уже прочитано" in n for n in got.notes), got.notes


def test_a_batch_where_everything_is_already_read_is_refused(
        space: Path, monkeypatch, fake_gpurunner) -> None:
    """Коли випали всі — це відмова заходу, а не мовчазний успіх."""
    from nyshporka.core.workspace import workspace

    case, _ = _wire(space, monkeypatch)
    done = workspace().htr_reports / case.name
    done.mkdir(parents=True, exist_ok=True)
    (done / "_htr_meta.json").write_text(json.dumps({
        "model": "model_v1.pt",
        "pages": {f"{i:04d}.jpg": {"lines": 20} for i in range(3)}}),
        encoding="utf-8")
    second = _second_case(space)
    done2 = workspace().htr_reports / second.name
    done2.mkdir(parents=True, exist_ok=True)
    (done2 / "_htr_meta.json").write_text(json.dumps({
        "model": "model_v1.pt",
        "pages": {f"{i:04d}.jpg": {"lines": 20} for i in range(3)}}),
        encoding="utf-8")

    got = _go([str(case), str(second)], dry_run=True)
    assert (got.verdict, got.exit_code) == ("refused", 2)
    assert not fake_gpurunner.called("htr", "plan")


def test_the_thin_path_refuses_more_than_one_case(space: Path, monkeypatch,
                                                  fake_gpurunner) -> None:
    """🔴 Тонкий шлях тримає ОДНЕ з'єднання, один віддалений каталог і один
    pid. Відмова безплатна: оренди ще не було."""
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)

    got = _go([str(first), str(second)], dry_run=True, thin=True)
    assert (got.verdict, got.exit_code) == ("refused", 2)
    assert "одну справу" in got.why


def test_every_case_of_a_batch_knows_its_siblings(space: Path, monkeypatch,
                                                  fake_gpurunner) -> None:
    """🔴 Наглядач і машина в партії одні на всіх: спинивши «цю справу», людина
    спиняє всю чергу. Запис мусить це знати, інакше сказати правду нічим."""
    from nyshporka.cloud import state as ST

    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)
    _go([str(first), str(second)])

    runs = {s.run_id: s for s in ST.all_runs()}
    assert len(runs) == 2
    for run_id, st in runs.items():
        assert st.siblings == [i for i in runs if i != run_id]
        assert st.supervisor, "у кожної справи той самий наглядач"
    assert len({s.supervisor for s in runs.values()}) == 1


def test_the_plan_gets_every_original_frames_dir(space: Path, monkeypatch,
                                                 fake_gpurunner) -> None:
    """🔴 `case_dir` у меті — ОРИГІНАЛ кожної справи. Підставити один оригінал
    усій партії означало б різати кропи з чужої книги."""
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)
    _go([str(first), str(second)], dry_run=True)

    plan = _plan_of(fake_gpurunner)
    assert [c["case_dir"] for c in plan["cases"]] == [str(first), str(second)]


def test_bookkeeping_indexes_every_case_and_rebuilds_once(space: Path, monkeypatch,
                                                          fake_gpurunner) -> None:
    """Пропущена справа партії — це «декоду немає» про щойно прочитану книгу,
    тобто рівно той хибний нуль, проти якого гачки й написані."""
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)
    _go([str(first), str(second)], dry_run=True)

    hooks = _plan_of(fake_gpurunner).get("post_fetch") or []
    if not hooks:                      # `nysh` поруч немає — гачків не буває
        pytest.skip("у цьому середовищі немає програми nysh")
    builds = [h for h in hooks if h["cmd"][1:] == ["cases", "build"]]
    indexes = [h["cmd"][-1] for h in hooks if "index" in h["cmd"]]
    assert len(builds) == 1
    assert indexes == [first.name, second.name]


def test_absorb_takes_this_cases_row_not_the_largest(space: Path, monkeypatch) -> None:
    """🔴 Запис справи мусить показувати ЇЇ поступ.

    Доти сюди йшов `max(pages_done)` по всіх справах наглядача. На одній справі
    це те саме число, а на черзі запис справи A показував би сторінки справи C —
    і людина забирала б результат за чужим лічильником.
    """
    from nyshporka.cloud import state as ST

    st = ST.RunState(run_id="r1", case_dir=str(space / "перша"),
                     out_dir=str(space / "out" / "перша"), backend="fake",
                     supervisor="htr-q2", frames_total=100)
    data = {"verdict": "ok", "cases": [
        {"case": "чужа", "out_dir": str(space / "out" / "чужа"), "pages_done": 900},
        {"case": "перша", "out_dir": str(space / "out" / "перша"), "pages_done": 12},
    ]}
    got = SUP.absorb(st, data)
    assert got.pages_done == 12, "узято чужий лічильник"


def test_the_script_survives_the_shrink(space: Path, monkeypatch, fake_gpurunner) -> None:
    """🔴 Письмо визначається ОДИН раз — по теці з описом справи.

    Спіймано 21.09.2026 на живому заході: кадри стискаються в робочу теку, де
    жодного опису немає, і другий здогад чесно казав «не знаю» — справа падала
    вже ПІСЛЯ стискання, хоч письмо було відоме з першого разу. На партії це
    виглядало як «справа випала», на одній — як відмова після чверті години
    роботи.
    """
    case, _ = _wire(space, monkeypatch)
    # робимо кадри «важкими», щоб захід пішов через стискання
    monkeypatch.setattr(F := __import__("nyshporka.cloud.frames", fromlist=["x"]),
                        "SHRINK_MEDIAN_MB", 0.0)
    calls: list[str] = []
    real = F.check_frames

    def heavy(d, **kw):
        rep = real(d, **kw)
        calls.append(str(d))
        return rep

    monkeypatch.setattr(F, "check_frames", heavy)

    got = _go(case, script="latin", dry_run=True)
    assert got.verdict == "dry_run", got.why
    assert "script=latin" in _plan_of(fake_gpurunner)["params"], (
        "письмо не доїхало: другий здогад по стиснутій копії його загубив")


def test_an_explicit_supervisor_path_wins(monkeypatch, tmp_path: Path) -> None:
    """⚙ Коли Нишпорку кличуть із чужого простору, адресу наглядача знає лише
    той, хто кличе: там він живе у власному середовищі поруч, а не в нашому."""
    monkeypatch.setenv("NYSH_GPURUNNER", str(tmp_path / "gr.exe"))
    assert SUP.gpurunner_cmd() == [str(tmp_path / "gr.exe")]
    monkeypatch.delenv("NYSH_GPURUNNER")
    assert SUP.gpurunner_cmd() != [str(tmp_path / "gr.exe")]


def test_a_dropped_seed_takes_the_dense_fleet_with_it(space: Path, monkeypatch,
                                                      fake_gpurunner) -> None:
    """🔴🔴 Найдорожча помилка з можливих: машина читає з ПОВНОЮ сегментацією,
    а флот їй дали як для готової.

    Щільніший флот (0.5 ядра на шард) правдивий рівно доти, доки сегментація
    справді їде. Коли засів знято — людина назвала `--transport box` або
    сховища немає, — сторінка знову рахує геометрію повністю, і шарди душаться
    на вдвічі менших ядрах. Платимо за це погодинно.

    Знайдено рев'ю 21.09.2026 на двох шляхах одразу: параметри складались
    окремо від рішення про засів.
    """
    case, _ = _wire(space, monkeypatch)
    _named_model(space, monkeypatch)
    _seed_ready(space, case)

    _go(case, model="skryba_f792_v6.mlmodel", dry_run=True, transport="box")
    plan = _plan_of(fake_gpurunner)
    assert not plan["cases"][0]["seed_seg"], "засів мав бути знятий"
    assert not [p for p in plan["params"] if p.startswith(("cores_per_shard=",
                                                           "vram_gb_per_shard="))], (
        "флот лишився щільним без засіву: машина читатиме з повною "
        "сегментацією на вдвічі менших ядрах — і це оплачувані години")


def test_a_params_flag_with_thin_is_refused(space: Path, monkeypatch,
                                            fake_gpurunner) -> None:
    """🔴 Тонкий шлях складає команду раннера сам і каналу для параметрів не
    має. Прийняти `-p` і не передати означало б дати людині думати, що вона
    керує прогоном, який іде з дефолтами."""
    case, _ = _wire(space, monkeypatch)
    got = _go(case, thin=True, dry_run=True, params=["shards=6"])
    assert (got.verdict, got.exit_code) == ("refused", 2)
    assert "-p" in got.why


def test_a_case_key_with_a_batch_is_refused(space: Path, monkeypatch,
                                            fake_gpurunner) -> None:
    """Шифра — властивість ОДНІЄЇ справи. Мовчки відкинути те, що людина щойно
    набрала, не можна; підписати нею всю чергу — тим паче."""
    first, _ = _wire(space, monkeypatch)
    second = _second_case(space)
    got = _go([str(first), str(second)], dry_run=True, case_key="ARCH/1/9")
    assert (got.verdict, got.exit_code) == ("refused", 2)
    assert "--case-key" in got.why


def test_one_case_result_tells_the_truth_after_the_run(space: Path, monkeypatch,
                                                       fake_gpurunner) -> None:
    """🔴 `cases[]` — не знімок до роботи, а підсумок. Скіл учить агента читати
    саме його, і «0 сторінок, вердикту немає» при `ok` угорі читалося б як
    непочатий захід."""
    case, _ = _wire(space, monkeypatch)
    got = _go(case, dry_run=True)
    assert len(got.cases) == 1
    assert got.cases[0].verdict == got.verdict == "dry_run"
