"""🛫 Захід однією командою — без мережі, без грошей і без плагіна оренди.

Машина тут та сама фейкова тека, що й у `test_cloud_run`, а бекенд — фейк із
`caps={"rent", "cancel"}`. Перевіряються не рушії, а рішення про гроші, і
кожне з них — про те, щоб машина не тарифікувалась даремно:

* сухий прогін і відмова на кошторисі не орендують;
* брак балансу важить більше за `--confirm`;
* машина гаситься на КОЖНОМУ шляху виходу, і на успішному — лише після звірки;
* повторний захід підхоплює живу машину, а не бере другу;
* хвіст доганяється на живій машині рівно один раз;
* збій обліку не перетворює прочитану справу на «захід не вдався».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_cloud_run import FakeBackend, FakeSession
from typer.testing import CliRunner

from nyshporka.cloud import go as GO
from nyshporka.cloud import money as M
from nyshporka.cloud import run as RUN
from nyshporka.cloud import state as ST
from nyshporka.cloud.base import Box, CloudError, Completed, Need

Image = pytest.importorskip("PIL.Image")

NAMES = ["0000", "0001", "0002"]
#: Свідомо не схоже на справжній ключ жодного провайдера.
KEY_TEXT = "k" + "-not-a-real-one-" + "1234567890"


class Box1(FakeSession):
    """Фейкова машина, яка ще й «читає»: що саме — каже сценарій тесту.

    `reads` — по переліку сторінок на кожен пуск роботи; порожній перелік
    лишає роботу живою (вона «ще йде»).
    """

    def __init__(self, root: Path, reads: list[list[str]], *, engine: bool = True,
                 meta_pages: bool = False, cuda: bool = True) -> None:
        super().__init__(root)
        self.reads = list(reads)
        self.engine = engine
        #: Чи БАЧИТЬ рушій карту. Окремо від `engine`: колесо torch не під ту
        #: CUDA ставиться й імпортується без помилок, просто читає процесором.
        self.cuda = cuda
        self.meta_pages = meta_pages
        self.cmds: list[str] = []
        self.prepared = False

    def run(self, cmd: str, *, timeout=None, on_line=None) -> Completed:
        self.cmds.append(cmd)
        if "import kraken" in cmd:
            ok = self.engine or self.prepared
            return Completed(rc=0, out=f"OK 2.4.0 {self.cuda}" if ok
                             else "No module named kraken")
        if " venv " in cmd:
            self.prepared = True
        if cmd.startswith("rm -f") and RUN.DONE_FLAG in cmd:
            (self._run_dir() / RUN.DONE_FLAG).unlink(missing_ok=True)
            return Completed(rc=0, out="")
        if "for t in curl wget" in cmd:
            return Completed(rc=0, out="have=python3")
        return super().run(cmd, timeout=timeout, on_line=on_line)

    def spawn(self, cmd: str, *, log: str, pidfile: str) -> int:
        pid = super().spawn(cmd, log=log, pidfile=pidfile)
        batch = self.reads.pop(0) if self.reads else []
        if batch:
            out = self._run_dir() / RUN.OUT_SUB
            have = {p.stem for p in out.glob("*.txt")} if out.is_dir() else set()
            self.pretend_read(sorted(have | set(batch)))
            if self.meta_pages:
                meta = out / "_htr_meta.json"
                data = json.loads(meta.read_text("utf-8"))
                data.update(model="model_v1.pt",
                            pages={f"{n}.jpg": {} for n in sorted(have | set(batch))})
                meta.write_text(json.dumps(data), encoding="utf-8")
        return pid


class Rent(FakeBackend):
    """Фейковий бекенд оренди з необов'язковими методами плагіна."""

    def __init__(self, root: Path, session: FakeSession, *, cost: float | None = 0.40,
                 balance: float | None = 25.0, empty: bool = False) -> None:
        super().__init__(root)
        self.session = session
        self.cost, self.balance, self.empty = cost, balance, empty
        self.needs: list[Need] = []
        self.estimates = 0
        self.keys: list[str] = []
        self.status_data: dict[str, Any] = {
            "ready": True, "problems": [], "balance_usd": 12.5, "api_key": True,
            "ssh_key": "", "burning": []}

    def acquire(self, need: Need, *, target: str = "") -> Box:
        self.needs.append(need)
        return super().acquire(need, target=target)

    def estimate(self, need: Need, *, target: str = "") -> dict[str, Any]:
        self.estimates += 1
        base: dict[str, Any] = {"empty": self.empty, "candidates": 0 if self.empty else 7,
                                "reason": "усе дорожче за стелю" if self.empty else "",
                                "balance_usd": self.balance}
        if self.empty or self.cost is None:
            return base
        return {**base, "gpu": "RTX 3090", "num_gpus": 1, "cores": 24.0,
                "price_usd_h": 0.10, "pages_per_hour": 900.0, "hours": 0.5,
                "cost_usd": self.cost, "usd_per_1000": 0.11}

    def status(self) -> dict[str, Any]:
        return dict(self.status_data)

    def login(self, api_key: str) -> dict[str, Any]:
        self.keys.append(api_key)
        return dict(self.status_data)


@pytest.fixture
def space(tmp_path: Path, monkeypatch):
    from nyshporka.core import workspace as W
    from nyshporka.setup import packs

    monkeypatch.setattr(W, "_override",
                        W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(packs, "target_dir", lambda kind: tmp_path / "_cache")
    return tmp_path


def _make_case(space: Path, *, px: tuple[int, int] = (40, 60)) -> Path:
    import os
    import time

    case = space / "sprava"
    case.mkdir()
    old = time.time() - 3600
    for n in NAMES:
        p = case / f"{n}.jpg"
        Image.new("L", px, 200).save(p, "JPEG")
        os.utime(p, (old, old))
    return case


def _wire(space: Path, monkeypatch, session: FakeSession, *, fake_books: bool = True,
          **kw: Any) -> tuple[Path, Rent, list[str]]:
    from nyshporka.htr import run as R

    case = _make_case(space)
    model = space / "data" / "spotter" / "models" / "model_v1.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"\0" * 16)
    monkeypatch.setattr(R, "pick_model", lambda script, second_voice=True: (model, None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("ARCH/1/2", "тест"))
    backend = Rent(space / "box", session, **kw)
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)
    booked: list[str] = []
    if fake_books:
        monkeypatch.setattr(GO, "bookkeeping", lambda run: booked.append(run) or [])
    ticks = {"n": 0}

    def no_sleep(_s: float) -> None:
        # Запобіжник самого тесту: нагляд без кінця мусить упасти, а не зависнути.
        ticks["n"] += 1
        if ticks["n"] > 500:
            raise AssertionError("нагляд не закінчується — фейкова робота вічно жива")

    monkeypatch.setattr(GO, "_sleep", no_sleep)
    return case, backend, booked


def _go(case: Path, **kw: Any) -> GO.GoResult:
    # Цей файл — про ТОНКИЙ шлях: ми самі тримаємо машину від оренди до
    # гасіння. Наглядацький (типовий) перевіряється в `test_cloud_supervised`.
    kw.setdefault("thin", True)
    kw.setdefault("backend", "fake")
    kw.setdefault("script", "cyrillic")
    kw.setdefault("tick_sec", 0.0)
    return GO.go(str(case), **kw)


# ── гроші: чиста арифметика ──────────────────────────────────────────────────
def test_fork_is_wider_when_density_is_unknown() -> None:
    """🔴 ×2 на невідомій щільності вже не вистачало: реальна ціна виходила ×1.96
    від прогнозу, і захід зупинявся на бюджеті за кілька сторінок до кінця."""
    assert M.budget_fork(1.00, density_known=True) == (1.00, 1.60)
    assert M.budget_fork(1.00, density_known=False) == (1.00, 2.60)
    assert M.budget_fork(0.30, density_known=True) == (0.30, 0.55), \
        "рівно 45 центів не округлюються до 50 через двійкову арифметику"
    assert M.budget_fork(0.01, density_known=False)[1] == 0.50, "не нижче пів долара"


def test_hours_ceiling_is_three_forecasts_plus_one_within_bounds() -> None:
    assert M.max_hours_for(0.2) == 4.0
    assert M.max_hours_for(2.0) == 7.0
    assert M.max_hours_for(40.0) == M.MAX_HOURS_CAP


def test_lack_of_credit_beats_everything_else() -> None:
    """🔴 Дозвіл людини знімає стелю автозапуску, а не арифметику: захід, на
    який грошей немає, обірветься посередині — з оплаченою заливкою й без тексту."""
    got = M.decide_launch(1.50, 1.00, 2.00, confirm=True)
    assert (got.launch, got.kind) == (False, "no_credit")

    assert M.decide_launch(1.50, 9.0, 2.00, confirm=False).launch is True
    over = M.decide_launch(3.50, 9.0, 2.00, confirm=False)
    assert (over.launch, over.kind) == (False, "needs_confirm")
    assert M.decide_launch(3.50, 9.0, 2.00, confirm=True).launch is True
    assert M.decide_launch(1.50, None, 2.00, confirm=False).launch is True, \
        "невідомий баланс — не нуль і не відмова"


def test_estimate_keeps_the_unknown_unknown() -> None:
    """🔴 Чого бекенд не сказав, те лишається `None` — і так і показується."""
    est = M.parse_estimate({"empty": False, "candidates": 3, "balance_usd": None})
    assert est.cost is None and est.price_usd_h is None
    assert "невідомо" in est.human()
    assert M.parse_estimate("сміття").cost is None
    priced = M.parse_estimate({"price_usd_h": 0.2, "hours": 3})
    assert priced.cost == pytest.approx(0.6), "ціна × години самого бекенда"


def test_the_autostart_ceiling_lives_next_to_the_hosts(space: Path) -> None:
    """Стеля лежить у тому самому файлі, що машини й сховище, — і жоден із
    трьох записів не стирає сусідів."""
    from nyshporka.cloud.ssh import Host, hosts_path, load_hosts, save_hosts

    assert M.autostart_ceiling() == M.DEFAULT_AUTOSTART_MAX_USD
    save_hosts([Host(name="дім", user="u", host="h.example")])
    assert M.set_autostart_ceiling(5) == 5.0
    save_hosts([*load_hosts(), Host(name="ще", user="u", host="h2.example")])
    data = json.loads(hosts_path().read_text("utf-8"))
    assert data["rent"] == {"autostart_max_usd": 5.0}
    assert len(data["hosts"]) == 2
    assert M.autostart_ceiling() == 5.0


# ── до оренди ────────────────────────────────────────────────────────────────
def test_dry_run_never_rents(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]))
    res = _go(case, dry_run=True)
    assert (res.verdict, res.exit_code) == ("dry_run", 0), res.why
    assert backend.acquired == 0 and backend.estimates == 1
    assert (res.fork_low, res.fork_high) == (0.40, 1.10)
    assert res.budget_usd == 1.10 and res.max_hours == 4.0
    assert res.rented is False and res.released is None


def test_over_the_ceiling_needs_a_human(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]), cost=3.0)
    res = _go(case)
    assert (res.verdict, res.exit_code) == ("needs_confirm", 10)
    assert backend.acquired == 0, "без дозволу людини — жодної оренди"


def test_no_credit_is_checked_before_the_ceiling(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]),
                             cost=3.0, balance=1.0)
    res = _go(case, confirm=True)
    assert (res.verdict, res.exit_code) == ("no_credit", 8)
    assert backend.acquired == 0


def test_an_empty_market_is_its_own_verdict(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]), empty=True)
    res = _go(case)
    assert (res.verdict, res.exit_code) == ("market_empty", 6)
    assert backend.acquired == 0


def test_without_an_estimate_the_human_names_the_budget(space: Path, monkeypatch) -> None:
    """🔴 Кошторису немає — суми не вгадуємо: або `--budget`, або відмова."""
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]), cost=None)
    res = _go(case, dry_run=True)
    assert res.verdict == "refused" and "--budget" in res.why

    named = _go(case, dry_run=True, budget=1.5)
    assert named.verdict == "dry_run"
    assert (named.fork_high, named.budget_usd) == (None, 1.5)
    assert backend.acquired == 0


def test_broken_frames_stop_the_run_before_any_money(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]))
    whole = (case / "0001.jpg").read_bytes()
    (case / "0001.jpg").write_bytes(whole[: len(whole) // 2])
    import os
    import time
    os.utime(case / "0001.jpg", (time.time() - 3600,) * 2)

    res = _go(case)
    assert res.verdict == "refused" and "0001.jpg" in res.why
    assert backend.estimates == 0 and backend.acquired == 0


def test_a_case_already_read_by_this_model_is_refused(space: Path, monkeypatch) -> None:
    """🔴 Орендувати машину під уже прочитану справу — найдурніший спосіб
    витратити гроші, і саме він уже траплявся."""
    from nyshporka.core.workspace import workspace

    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]))
    out = workspace().htr_reports / case.name
    out.mkdir(parents=True)
    (out / "_htr_meta.json").write_text(json.dumps({
        "model": "model_v1.pt", "started": "2026-01-01",
        "pages": {f"{n}.jpg": {} for n in NAMES}}), encoding="utf-8")

    res = _go(case)
    assert res.verdict == "refused" and "уже прочитано" in res.why
    assert backend.acquired == 0
    assert _go(case, rerun=True, dry_run=True).verdict == "dry_run"


def test_a_backend_that_does_not_rent_is_sent_elsewhere(space: Path, monkeypatch) -> None:
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES]))
    monkeypatch.setattr(type(backend), "caps", frozenset())
    res = _go(case)
    assert res.verdict == "refused" and "nysh cloud start" in res.why


# ── захід ────────────────────────────────────────────────────────────────────
def test_full_run_releases_only_after_verification(space: Path, monkeypatch) -> None:
    """🔴 Порядок `fetch → verify → release` автономний захід виконує сам."""
    session = Box1(space / "box", [NAMES])
    case, backend, booked = _wire(space, monkeypatch, session)

    seen: list[str] = []
    original = backend.release

    def watched(box: Box, *, why: str = "") -> None:
        st = ST.load(_state_id())
        seen.append(st.verdict if st else "")
        original(box, why=why)

    def _state_id() -> str:
        return ST.all_runs()[0].run_id

    monkeypatch.setattr(backend, "release", watched)
    events: list[str] = []
    res = _go(case, on_event=lambda kind, text, **_: events.append(kind))

    assert (res.verdict, res.exit_code) == ("ok", 0)
    assert (res.pages_done, res.pages_total) == (3, 3)
    assert backend.acquired == 1 and backend.released == ["ok"]
    assert seen == ["ok"], "на мить гасіння вирок уже записано"
    assert res.released is True and res.spent_usd is not None
    assert events.index("verify") < events.index("release")
    assert booked == [case.name], "облік після забору"
    assert events.index("release") < events.index("done")

    need = backend.needs[0]
    assert (need.budget_usd, need.max_hours) == (1.10, 4.0), "стелі їдуть у Need"
    st = ST.load(res.run_id)
    assert st is not None and st.released and not st.needs_release
    assert (st.fork_low, st.fork_high, st.budget_usd) == (0.40, 1.10, 1.10)


def test_the_engine_is_prepared_inside_the_run_not_refused(space: Path, monkeypatch) -> None:
    """🔴 Орендований бокс свіжий за побудовою: середовища рушіїв на ньому немає
    НІКОЛИ. Відмова «зберіть окремою командою» тут одразу йшла б в обробник, який
    гасить машину, — «орендував → погасив» на кожному старті."""
    session = Box1(space / "box", [[]], engine=False)
    case, backend, _ = _wire(space, monkeypatch, session)
    from nyshporka.cloud import plan as PL

    plan = PL.build(case, backend="fake", script="cyrillic")
    st = RUN.start(plan)
    assert session.prepared is True, "середовище зібрано в межах заходу"
    assert backend.released == [], "машину не гасили"
    assert st.phase == "running" and st.pid == 4242


def test_own_machine_is_still_refused_without_an_engine(space: Path, monkeypatch) -> None:
    """На своїй машині гігабайти пакетів мовчки не ставляться."""
    session = Box1(space / "box", [[]], engine=False)
    case, backend, _ = _wire(space, monkeypatch, session)
    monkeypatch.setattr(type(backend), "caps", frozenset())
    from nyshporka.cloud import plan as PL

    with pytest.raises(RUN.RunError, match="nysh cloud prepare"):
        RUN.start(PL.build(case, backend="fake", script="cyrillic"))
    assert session.prepared is False


def test_the_budget_ceiling_stops_fetches_and_releases(space: Path, monkeypatch) -> None:
    """🔴 Стеля грошей: роботу зупинено, прочитане ЗАБРАНО, машину погашено —
    і вердикт окремий від збою, бо текст на диску справжній."""
    session = Box1(space / "box", [["0000", "0001"]])
    case, backend, _ = _wire(space, monkeypatch, session)
    # Робота «ще йде»: сторінки є, прапорця завершення немає.
    real_spawn = session.spawn

    def spawn(cmd: str, *, log: str, pidfile: str) -> int:
        pid = real_spawn(cmd, log=log, pidfile=pidfile)
        (session._run_dir() / RUN.DONE_FLAG).unlink(missing_ok=True)
        session.alive_flag = True
        return pid

    monkeypatch.setattr(session, "spawn", spawn)
    import time as _t

    monkeypatch.setattr(GO, "_now", lambda: _t.time() + 100 * 3600)   # $10 при $0.10/год

    res = _go(case, max_hours=1000.0)
    assert (res.verdict, res.exit_code) == ("budget_stop", 5)
    assert session.killed is True, "роботу зупинено за pid"
    assert res.pages_done == 2, "прочитане привезено"
    assert sorted(p.stem for p in Path(res.out_dir).glob("*.txt")) == ["0000", "0001"]
    assert backend.released == ["budget_stop"]


def test_the_clock_is_a_ceiling_too(space: Path, monkeypatch) -> None:
    session = Box1(space / "box", [["0000"]])
    case, backend, _ = _wire(space, monkeypatch, session)
    real_spawn = session.spawn

    def spawn(cmd: str, *, log: str, pidfile: str) -> int:
        pid = real_spawn(cmd, log=log, pidfile=pidfile)
        (session._run_dir() / RUN.DONE_FLAG).unlink(missing_ok=True)
        session.alive_flag = True
        return pid

    monkeypatch.setattr(session, "spawn", spawn)
    import time as _t

    monkeypatch.setattr(GO, "_now", lambda: _t.time() + 5 * 3600)
    res = _go(case, budget=20.0, confirm=True)
    assert (res.verdict, res.exit_code) == ("deadline", 7), res.why
    assert backend.released == ["deadline"]


def test_a_failure_during_upload_still_releases(space: Path, monkeypatch) -> None:
    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)

    def boom(*a: Any, **k: Any) -> None:
        raise CloudError("канал обірвався посеред заливки")

    monkeypatch.setattr(RUN, "_upload_frames", boom)
    res = _go(case)
    assert (res.verdict, res.exit_code) == ("failed", 3)
    assert backend.released == ["failed:uploading"]
    assert res.released is True


def test_a_failure_while_running_salvages_then_releases(space: Path, monkeypatch) -> None:
    """Виняток посеред нагляду: спершу спроба забрати, що є, потім гасіння."""
    session = Box1(space / "box", [["0000"]])
    case, backend, _ = _wire(space, monkeypatch, session)
    calls = {"n": 0}
    real_poll = RUN.poll

    def poll(st: ST.RunState) -> RUN.Pulse:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("несподіване")
        return real_poll(st)

    monkeypatch.setattr(RUN, "poll", poll)
    res = _go(case)
    assert res.verdict == "failed" and "несподіване" in res.why
    assert res.pages_done == 1, "забрано те, що встигло прочитатись"
    assert backend.released == ["failed:RuntimeError"]


def test_a_release_that_fails_is_shouted_and_has_its_own_exit_code(
        space: Path, monkeypatch) -> None:
    """🔴 Єдиний випадок, коли гроші горять без нагляду. Нуль на виході тут
    означав би «все гаразд» при лічильнику, який іде."""
    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)

    def stuck(box: Box, *, why: str = "") -> None:
        raise CloudError("інстанс живий, погасити не вдалось")

    monkeypatch.setattr(backend, "release", stuck)
    res = _go(case)
    assert res.verdict == "ok" and res.released is False
    assert res.exit_code == 9
    assert any("НЕ ВДАЛОСЬ ПОГАСИТИ" in n and "rent status" in n for n in res.notes)


def test_second_go_adopts_the_live_run(space: Path, monkeypatch) -> None:
    """🔴 Стійкість до обриву термінала: повтор тієї самої команди підхоплює
    живу машину разом зі стелями, а не орендує другу."""
    from nyshporka.cloud import plan as PL

    session = Box1(space / "box", [[]])
    case, backend, _ = _wire(space, monkeypatch, session)
    plan = PL.build(case, backend="fake", script="cyrillic", budget_usd=1.1,
                    max_hours=4.0)
    RUN.start(plan)                       # «перший `go`», чий термінал закрили
    assert backend.acquired == 1
    session.pretend_read(NAMES)           # робота тим часом дочиталась

    res = _go(case)
    assert backend.acquired == 1, "другої машини не беремо"
    assert backend.estimates == 0, "і кошторису не питаємо — рішення вже ухвалено"
    assert res.adopted is True and res.verdict == "ok"
    assert res.budget_usd == 1.1, "стелі підхоплено зі стану"
    assert backend.released == ["ok"]


def test_an_orphan_box_is_released_before_any_new_rent(space: Path, monkeypatch) -> None:
    """Машина є, роботи на ній немає (процес убито посеред підготовки): гасимо
    ДО кошторису — відмова на ньому лишила б сироту тарифікуватись далі."""
    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session, cost=3.0)
    from nyshporka.cloud import plan as PL

    run_id = PL.build(case, backend="fake", script="cyrillic").run_id
    st = ST.RunState(run_id=run_id, case_dir=str(case), backend="fake",
                     bills=True, phase="uploading",
                     box=Box(id="box-0", backend="fake").as_dict())
    ST.save(st)

    res = _go(case)                       # кошторис $3 → потрібен --confirm
    assert res.verdict == "needs_confirm"
    assert backend.released == ["failed:orphaned"]
    assert ST.load(run_id).released is True


def test_the_tail_is_caught_up_once_on_the_live_box(space: Path, monkeypatch) -> None:
    """Малий хвіст доганяється на ЖИВІЙ машині, одним процесом і рівно раз."""
    import os
    import time

    names = [f"{i:04d}" for i in range(60)]
    session = Box1(space / "box", [names[:-1], names[-1:]])
    case, backend, _ = _wire(space, monkeypatch, session)
    old = time.time() - 3600
    for n in names:
        p = case / f"{n}.jpg"
        if not p.exists():
            Image.new("L", (40, 60), 200).save(p, "JPEG")
            os.utime(p, (old, old))

    res = _go(case)
    assert res.verdict == "ok" and res.pages_done == 60
    assert len(session.spawned) == 2, "основний прохід і один догін"
    assert backend.acquired == 1 and backend.released == ["ok"]
    assert any(".before-catchup" in c for c in session.cmds), \
        "карантин відкладено вбік — інакше догін пропустив би саме ці сторінки"
    go_sh = (session._run_dir() / RUN.GO_SCRIPT).read_text("utf-8")
    assert "--shard" not in go_sh, "догін іде одним процесом"


def test_catch_up_happens_once_then_the_run_is_incomplete(space: Path, monkeypatch) -> None:
    import os
    import time

    names = [f"{i:04d}" for i in range(60)]
    session = Box1(space / "box", [names[:-1], []])
    case, backend, _ = _wire(space, monkeypatch, session)
    old = time.time() - 3600
    for n in names:
        p = case / f"{n}.jpg"
        if not p.exists():
            Image.new("L", (40, 60), 200).save(p, "JPEG")
            os.utime(p, (old, old))
    real_spawn = session.spawn

    def spawn(cmd: str, *, log: str, pidfile: str) -> int:
        pid = real_spawn(cmd, log=log, pidfile=pidfile)
        if len(session.spawned) == 2:          # догін нічого не дочитав
            (session._run_dir() / RUN.DONE_FLAG).write_text("")
            session.alive_flag = False
        return pid

    monkeypatch.setattr(session, "spawn", spawn)
    res = _go(case)
    assert (res.verdict, res.exit_code) == ("incomplete", 4)
    assert len(session.spawned) == 2, "третьої спроби немає"
    assert backend.released == ["failed:incomplete"]


def test_bookkeeping_failure_does_not_fail_the_run(space: Path, monkeypatch) -> None:
    """🔴 Текст на диску, машина погашена — «захід не вдався» через зайнятий
    файл індексу було б неправдою, яка ще й спонукає перечитати за гроші."""
    session = Box1(space / "box", [NAMES])
    case, _backend, _ = _wire(space, monkeypatch, session, fake_books=False)

    from nyshporka import ops as O
    from nyshporka.cases import db

    called: list[str] = []

    def broken_rebuild(**kw: Any) -> dict[str, Any]:
        called.append("cases")
        raise OSError("файл реєстру зайнятий")

    def fake_call(name: str, args: dict[str, Any]) -> Any:
        called.append(name)

        class Env:
            ok = False
            error = "стор зайнятий"

        return Env()

    monkeypatch.setattr(db, "rebuild", broken_rebuild)
    monkeypatch.setattr(O, "call", fake_call)

    res = _go(case)
    assert (res.verdict, res.exit_code) == ("ok", 0)
    assert called == ["cases", "text.index"], "обидва кроки обліку викликано"
    assert any("nysh cases build" in n for n in res.notes)
    assert any("nysh text index" in n for n in res.notes)


def test_heavy_frames_travel_shrunk_but_the_meta_names_the_originals(
        space: Path, monkeypatch) -> None:
    """🔴 На машину їде стиснута копія, а в мету лягає тека ОРИГІНАЛІВ: кроп зі
    стиснутого кадру вдвічі дрібніший, а знахідку звіряють саме кропом."""
    from nyshporka.cloud import frames as F

    session = Box1(space / "box", [NAMES])
    case, _backend, _ = _wire(space, monkeypatch, session)
    monkeypatch.setattr(F, "SHRINK_MEDIAN_MB", -1.0)

    res = _go(case)
    assert res.verdict == "ok"
    shrunk = F.shrink_dir_for(case)
    assert sorted(p.name for p in shrunk.glob("*.jpg")) == [f"{n}.jpg" for n in NAMES]
    st = ST.load(res.run_id)
    assert st is not None
    assert Path(st.case_dir) == shrunk.resolve() and Path(st.source_dir) == case.resolve()
    meta = json.loads((Path(res.out_dir) / "_htr_meta.json").read_text("utf-8"))
    assert Path(meta["case_dir"]) == case.resolve()
    assert Path(res.out_dir).name == case.name, "ім'я прогону — ім'я справи"


def test_what_is_already_read_travels_to_the_box(space: Path, monkeypatch) -> None:
    """🔴 Захід, зупинений на стелі, при повторі не платить за прочитане вдруге:
    готове їде на машину, раннер його пропускає, а на ринок іде лише решта."""
    from nyshporka.core.workspace import workspace

    session = Box1(space / "box", [["0002"]], meta_pages=True)
    case, backend, _ = _wire(space, monkeypatch, session)
    out = workspace().htr_reports / case.name
    out.mkdir(parents=True)
    for n in ("0000", "0001"):
        (out / f"{n}.txt").write_text("раніше прочитане", encoding="utf-8")
    (out / "_htr_meta.json").write_text(json.dumps({
        "model": "model_v1.pt", "frames_total": 3,
        "pages": {"0000.jpg": {}, "0001.jpg": {}}}), encoding="utf-8")
    (out / "_htr_quarantine.json").write_text(
        json.dumps({"version": 1, "pages": {"0002.jpg": {"reason": "OOM"}}}),
        encoding="utf-8")

    res = _go(case)
    assert res.verdict == "ok" and res.pages_done == 3
    assert backend.needs[0].pages == 1, "на ринок пішла лише решта"
    assert any("tar -xf seed.tar" in c for c in session.cmds), "готове поїхало на машину"
    assert not (Path(res.out_dir) / "_htr_quarantine.json").exists(), \
        "карантин, якого на машині вже немає, локально не переживає забір"
    st = ST.load(res.run_id)
    assert st is not None and st.pages_seeded == 2


# ── кілька заходів одночасно ─────────────────────────────────────────────────
class Fleet(Rent):
    """Бекенд, у якого кожна оренда — окремий бокс зі своєю текою й сесією."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, Box1(root / "unused", []))
        import threading

        self._lock = threading.Lock()
        self.sessions: dict[str, Box1] = {}
        self.released_ids: list[str] = []

    def acquire(self, need: Need, *, target: str = "") -> Box:
        with self._lock:
            self.acquired += 1
            box_id = f"box-{self.acquired}"
            self.sessions[box_id] = Box1(self.root / box_id, [NAMES])
        return Box(id=box_id, backend=self.id, label=box_id, cores=16, vram_gb=8,
                   gpus=1, price_usd_h=0.10,
                   meta={"host": {"host": "fake", "user": "root",
                                  "workdir": str(self.root / box_id / "work")}})

    def connect(self, box: Box) -> FakeSession:
        return self.sessions[box.id]

    def release(self, box: Box, *, why: str = "") -> None:
        with self._lock:
            self.released.append(why)
            self.released_ids.append(box.id)


def test_two_runs_of_different_cases_do_not_touch_each_other(
        space: Path, monkeypatch) -> None:
    """🔴 Заходи різних справ ідуть одночасно з різних терміналів. Кожен — свій
    `run_id`, свій файл стану, свій бокс; спільне — лише облік, і він під замком."""
    import os
    import threading
    import time

    from nyshporka.htr import run as R

    model = space / "data" / "spotter" / "models" / "model_v1.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"\0" * 16)
    monkeypatch.setattr(R, "pick_model", lambda script, second_voice=True: (model, None))
    monkeypatch.setattr(R, "case_key_for", lambda d: (f"ARCH/1/{Path(d).name}", "тест"))
    fleet = Fleet(space / "fleet")
    monkeypatch.setattr(RUN, "_backend", lambda name: fleet)
    monkeypatch.setattr(GO, "_sleep", lambda _s: None)

    inside = {"now": 0, "max": 0}
    booked: list[str] = []

    def books(run_name: str) -> list[str]:
        inside["now"] += 1
        inside["max"] = max(inside["max"], inside["now"])
        time.sleep(0.05)
        booked.append(run_name)
        inside["now"] -= 1
        return []

    monkeypatch.setattr(GO, "_bookkeeping", books)

    cases = []
    old = time.time() - 3600
    for name in ("sprava-a", "sprava-b"):
        d = space / name
        d.mkdir()
        for n in NAMES:
            Image.new("L", (40, 60), 200).save(d / f"{n}.jpg", "JPEG")
            os.utime(d / f"{n}.jpg", (old, old))
        cases.append(d)

    results: dict[str, GO.GoResult] = {}

    def work(d: Path) -> None:
        results[d.name] = _go(d)

    threads = [threading.Thread(target=work, args=(d,)) for d in cases]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert {r.verdict for r in results.values()} == {"ok"}, \
        {k: r.why for k, r in results.items()}
    assert fleet.acquired == 2
    assert sorted(fleet.released_ids) == ["box-1", "box-2"], "кожен погасив СВІЙ бокс"
    assert fleet.released == ["ok", "ok"]
    a, b = (results[d.name] for d in cases)
    assert a.run_id != b.run_id and a.out_dir != b.out_dir
    for d, r in zip(cases, (a, b), strict=True):
        st = ST.load(r.run_id)
        assert st is not None and Path(st.case_dir) == d.resolve()
        assert st.released and st.verdict == "ok"
        assert st.case_key == f"ARCH/1/{d.name}", "стани не перемішались"
        assert sorted(p.stem for p in Path(r.out_dir).glob("*.txt")) == NAMES
    assert st.box["id"] != ST.load(a.run_id).box["id"]
    assert sorted(booked) == ["sprava-a", "sprava-b"]
    assert inside["max"] == 1, "дві перебудови обліку не йдуть одночасно"


def test_go_adopts_only_its_own_run_never_just_the_latest(space: Path, monkeypatch) -> None:
    """🔴 Живий захід ІНШОЇ справи — не наш: підхопити його означало б забрати
    чужий результат і погасити чужу машину."""
    from nyshporka.cloud import plan as PL

    session = Box1(space / "box", [[], NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)
    other = space / "інша-справа"
    other.mkdir()
    (other / "0000.jpg").write_bytes((case / "0000.jpg").read_bytes())
    RUN.start(PL.build(other, backend="fake", script="cyrillic"))   # живе й читає
    assert backend.acquired == 1

    res = _go(case, dry_run=True)
    assert res.verdict == "dry_run" and res.adopted is False
    real = _go(case)
    assert real.verdict == "ok" and real.adopted is False
    assert backend.acquired == 2, "своя справа — своя машина"


def test_two_runs_into_one_folder_are_refused(space: Path, monkeypatch) -> None:
    """Та сама справа іншим письмом пише в ту саму теку виходу: два прогони
    перетирали б тексти один одного без жодної помилки."""
    from nyshporka.cloud import plan as PL

    session = Box1(space / "box", [[]])
    case, backend, _ = _wire(space, monkeypatch, session)
    RUN.start(PL.build(case, backend="fake", script="latin"))
    res = _go(case)                     # те саме, але кирилицею
    assert res.verdict == "refused" and "пише інший захід" in res.why
    assert backend.acquired == 1


def test_known_hosts_gets_a_line_appended_not_the_file_rewritten(tmp_path: Path) -> None:
    """🔴 Два заходи знайомляться з двома свіжими боксами одночасно. Штатна
    політика paramiko переписує файл зі своєї пам'яті — і той, хто пише другим,
    стирає відбиток першого."""
    import types

    from nyshporka.cloud.ssh import _append_policy

    # Сам paramiko тут не потрібен: перевіряється, що робить політика з файлом.
    paramiko = types.SimpleNamespace(MissingHostKeyPolicy=object)
    added: list[tuple[str, str]] = []

    known = tmp_path / "known_hosts"
    known.write_text("[1.2.3.4]:4001 ssh-ed25519 AAAAчужий-рядок\n", encoding="utf-8")

    class Key:
        def get_name(self) -> str:
            return "ssh-ed25519"

        def get_base64(self) -> str:
            return "AAAAнаш"

    class Keys:
        def add(self, host: str, kind: str, key: object) -> None:
            added.append((host, kind))

    class Client:
        _host_keys = Keys()

    _append_policy(paramiko, known).missing_host_key(Client(), "[5.6.7.8]:4002", Key())
    assert added == [("[5.6.7.8]:4002", "ssh-ed25519")], "і в пам'ять сеансу теж"
    lines = known.read_text("utf-8").splitlines()
    assert lines == ["[1.2.3.4]:4001 ssh-ed25519 AAAAчужий-рядок",
                     "[5.6.7.8]:4002 ssh-ed25519 AAAAнаш"]


def test_running_boxes_are_mentioned_but_never_a_reason_to_refuse(
        space: Path, monkeypatch) -> None:
    session = Box1(space / "box", [NAMES])
    case, backend, _ = _wire(space, monkeypatch, session)
    backend.status_data["burning"] = [{"instance_id": "1", "dph_total": 0.2},
                                      {"instance_id": "2", "dph_total": 0.15}]
    events: list[str] = []
    res = _go(case, on_event=lambda kind, text, **_: events.append(text))
    assert res.verdict == "ok"
    assert any("вже тарифікується 2 боксів ($0.350/год)" in e for e in events)


def test_measured_tempo_is_reported_only_when_it_was_measured() -> None:
    """Темп іде бекенду в `why` і стає записом у його реєстрі машин — тож або
    виміряне число, або нічого."""
    st = ST.RunState(run_id="x", run_started=1000.0, pages_done=110, pages_seeded=10)
    assert GO.measured_pph(st, 1000.0 + 3600) == 100
    assert GO.measured_pph(st, 1000.0 + 120) is None, "дві хвилини — не замір"
    st.run_started = 0.0
    assert GO.measured_pph(st, 5000.0) is None


def test_the_uv_installer_is_fetched_with_whatever_the_box_has() -> None:
    """🔴 Образ орендованого боксу — під обчислення: `curl` у ньому не даність."""
    assert RUN.uv_install_command("have=curl\nhave=wget").startswith("curl ")
    assert RUN.uv_install_command("have=wget\nhave=python3").startswith("wget -qO- ")
    via_py = RUN.uv_install_command("щось від motd\nhave=python3")
    assert via_py.startswith("python3 -c ") and "urllib.request" in via_py
    assert via_py.endswith("| sh")
    with pytest.raises(RUN.RunError, match="curl"):
        RUN.uv_install_command("")


# ── командний рядок ──────────────────────────────────────────────────────────
@pytest.fixture
def cli(space: Path, monkeypatch):
    from nyshporka.cloud import cli as C
    from nyshporka.cloud import registry as REG

    backend = Rent(space / "box", Box1(space / "box", [NAMES]))
    backend.id = "vast"
    reg = REG.Registry(backends={"vast": backend})
    monkeypatch.setattr(REG, "load", lambda: reg)
    return CliRunner(), C.app, backend


def test_rent_status_shows_what_is_burning(cli) -> None:
    runner, app, backend = cli
    backend.status_data["burning"] = [{"instance_id": "777", "dph_total": 0.21,
                                       "label": "nysh-rent-ab12", "gpu_name": "RTX 3090",
                                       "status": "running"}]
    got = runner.invoke(app, ["rent", "status"])
    assert "777" in got.output and "тарифікується зараз: 1" in got.output
    assert "НЕ з заходів цього простору" in got.output
    assert got.exit_code == 3, "чужа машина на акаунті — не нуль"

    backend.status_data["burning"] = []
    clean = runner.invoke(app, ["rent", "status"])
    assert clean.exit_code == 0 and "нічого" in clean.output


def test_unknown_burning_is_not_shown_as_nothing(cli) -> None:
    """🔴 `None` = «спитати не вдалось», `[]` = «нічого не горить». Показане як
    «нічого» невдале питання — відповідь, після якої машина горить тиждень."""
    runner, app, backend = cli
    backend.status_data["burning"] = None
    got = runner.invoke(app, ["rent", "status"])
    assert "НЕВІДОМО" in got.output and "нічого ✅" not in got.output
    assert got.exit_code == 3

    as_json = runner.invoke(app, ["rent", "status", "--json"])
    assert json.loads(as_json.output)["burning"] is None


def test_login_hands_the_key_over_and_never_prints_it(cli, monkeypatch) -> None:
    runner, app, backend = cli
    got = runner.invoke(app, ["rent", "login", "--key", KEY_TEXT])
    assert got.exit_code == 0 and backend.keys == [KEY_TEXT]
    assert KEY_TEXT not in got.output

    monkeypatch.setenv("NYSHPORKA_RENT_KEY", KEY_TEXT + "-env")
    runner.invoke(app, ["rent", "login"])
    assert backend.keys[-1] == KEY_TEXT + "-env"

    monkeypatch.delenv("NYSHPORKA_RENT_KEY")
    monkeypatch.delenv("VAST_API_KEY", raising=False)
    asked = runner.invoke(app, ["rent", "login"], input=KEY_TEXT + "-typed\n")
    assert backend.keys[-1] == KEY_TEXT + "-typed"
    assert KEY_TEXT not in asked.output, "прихований запит нічого не відлунює"


def test_a_key_the_provider_rejected_is_a_failed_login(cli) -> None:
    """🔴 Бекенд зберігає й відхилений ключ, а відмову кладе в `problems`: «метод
    не кинув» ще не означає «увійшли»."""
    runner, app, backend = cli
    backend.status_data.update(ready=False,
                               problems=[f"провайдер відхилив ключ {KEY_TEXT}"])
    got = runner.invoke(app, ["rent", "login", "--key", KEY_TEXT])
    assert got.exit_code == 1 and "увійти не вдалось" in got.output
    assert KEY_TEXT not in got.output, "ключ вирізано навіть із чужого тексту"


def test_the_key_never_reaches_the_workspace(cli, space: Path) -> None:
    runner, app, _ = cli
    runner.invoke(app, ["rent", "login", "--key", KEY_TEXT])
    leaked = [p for p in space.rglob("*") if p.is_file()
              and KEY_TEXT.encode() in p.read_bytes()]
    assert leaked == []


def test_a_missing_rent_plugin_says_how_to_get_one(space: Path, monkeypatch) -> None:
    from nyshporka.cloud import cli as C

    got = CliRunner().invoke(C.app, ["rent", "status", "--backend", "нема-такого"])
    assert got.exit_code == 1 and "nyshporka[rent]" in got.output


def test_plan_shows_the_market_and_never_rents(cli, space: Path, monkeypatch) -> None:
    """🔴 `acquire` у бекенда з орендою — це й Є оренда. План її не кличе ніколи,
    з `--host` чи без."""
    from nyshporka.htr import run as R

    runner, app, backend = cli
    case = _make_case(space)
    monkeypatch.setattr(R, "pick_model",
                        lambda script, second_voice=True: (space / "m.pt", None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("ARCH/1/2", "тест"))
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)

    for extra in ([], ["--host", "12345"]):
        got = runner.invoke(app, ["plan", str(case), "--backend", "vast",
                                  "--script", "cyrillic", "--budget", "1.5", *extra])
        assert got.exit_code == 0, got.output
        assert "RTX 3090" in got.output and "вилка" in got.output
    assert backend.acquired == 0 and backend.estimates == 2

    backend.cost = None
    unknown = runner.invoke(app, ["plan", str(case), "--backend", "vast",
                                  "--script", "cyrillic"])
    assert "невідомо" in unknown.output


def test_go_json_prints_one_object_last(cli, space: Path, monkeypatch) -> None:
    from nyshporka.htr import run as R

    runner, app, backend = cli
    case = _make_case(space)
    monkeypatch.setattr(R, "pick_model",
                        lambda script, second_voice=True: (space / "m.pt", None))
    monkeypatch.setattr(R, "case_key_for", lambda d: ("ARCH/1/2", "тест"))
    monkeypatch.setattr(RUN, "_backend", lambda name: backend)

    got = runner.invoke(app, ["go", str(case), "--script", "cyrillic",
                              "--thin", "--dry-run", "--json"])
    assert got.exit_code == 0, got.output
    last = json.loads(got.output.strip().splitlines()[-1])
    assert last["verdict"] == "dry_run" and last["rented"] is False
    assert last["fork_usd"] == [0.4, 1.1]
    assert backend.acquired == 0


# ── доктор ───────────────────────────────────────────────────────────────────
def test_doctor_reports_rent_without_touching_the_network(monkeypatch) -> None:
    from nyshporka.cloud import registry as REG
    from nyshporka.setup import doctor as D

    monkeypatch.delenv("VAST_API_KEY", raising=False)
    monkeypatch.setattr(REG, "_from_entry_points", lambda: ([], []))
    none = D._rent()
    assert none.level == "ok" and "немає плагіна" in none.detail
    assert "nyshporka[rent]" in none.fix

    class Vast(FakeBackend):
        id = "vast"

        def status(self) -> dict[str, Any]:            # pragma: no cover
            raise AssertionError("доктор не ходить у мережу")

    monkeypatch.setattr(REG, "_from_entry_points", lambda: ([Vast(Path("."))], []))
    unknown = D._rent()
    assert "невідомо" in unknown.detail and "rent status" in unknown.fix

    monkeypatch.setenv("VAST_API_KEY", "є")
    assert "готовий" in D._rent().detail

    monkeypatch.delenv("VAST_API_KEY")
    monkeypatch.setattr(Vast, "configured", lambda self: False, raising=False)
    no_key = D._rent()
    assert no_key.level == "warn" and "немає ключа" in no_key.detail

    monkeypatch.setattr(REG, "_from_entry_points",
                        lambda: ([], [("vast", "ImportError: немає vastai")]))
    broken = D._rent()
    assert broken.level == "warn" and "зламані 1" in broken.detail


def test_engine_that_cannot_see_the_card_is_a_failure(space: Path, monkeypatch) -> None:
    """🔴 Машина з картою, а рушій її не бачить — збій, а не «готово».

    Колесо torch не під ту CUDA ставиться без помилки й імпортується так само,
    а читає процесором: та сама оплачувана година дає вдесятеро менше сторінок,
    і помітно це лише за темпом, коли гроші вже витрачено.
    """
    case, backend, _ = _wire(space, monkeypatch, Box1(space / "box", [NAMES], cuda=False))

    res = _go(case)

    assert res.verdict == "failed"
    assert "не бачить карти" in res.why
    assert res.released is True, "машину погашено — платити за неї нема за що"
