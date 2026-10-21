"""⚙️☁️ Хмара як операції: що крутиться, захід двома кроками, спинити, забрати.

Друковані команди (`nysh cloud state|go|stop|fetch`) лишаються людською
формою цих операцій (`@route(op=…)`), а консоль кличе їх напряму: екран
«Хмара» і вікно «У хмару» з кошторисом.

🔴 `cloud.go` без `run=true` — лише сухий прогін (`GO.go(dry_run=True)`):
план, кошторис вилкою, рішення про автозапуск, і жодної оренди. Гроші
витрачає тільки другий виклик, який консоль робить після підтвердження
людини. Окремої «кнопки, що одразу орендує», немає.
"""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.cloud.state import RunState
from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

#: Скільки останніх подій заходу віддавати (повний журнал — у файлі заходу).
INCIDENTS = 5


def _row(st: RunState, now: float) -> dict[str, Any]:
    d = st.as_dict()
    d["incidents"] = d["incidents"][-INCIDENTS:]
    d.update(phase_human=st.human_phase(), price_usd_h=st.price_usd_h,
             rent_hours=round(st.rent_hours(now), 3), spent_usd=st.spent_usd(now),
             needs_release=st.needs_release)
    return d


class StateArgs(BaseModel):
    run_id: str = Field(default="", description="ім'я заходу; порожньо — живі й останні")
    limit: int = Field(default=20, ge=1, le=500, description="скільки останніх заходів")


@op("cloud.state", summary="Що крутиться в хмарі, скільки витрачено, чи забрано результат",
    args=StateArgs, section="htr", tier="core", skill="run-case-remote",
    when="що крутиться в хмарі, скільки витрачено, чи забрано результат")
def cloud_state(a: StateArgs) -> Envelope:
    from nyshporka.cloud import state as ST

    now = time.time()
    if a.run_id:
        st = ST.load(a.run_id)
        if st is None:
            return fail(f"немає заходу «{a.run_id}»")
        is_live = any(s.run_id == st.run_id for s in ST.live())
        return ok({"runs": [_row(st, now)], "live": int(is_live)})
    runs = ST.all_runs()
    alive = {s.run_id for s in ST.live()}
    # Живі — завжди, навіть старі: машина, що горить, не може випасти за межу.
    shown = [s for s in runs if s.run_id in alive]
    shown += [s for s in runs if s.run_id not in alive][:max(0, a.limit - len(shown))]
    env = ok({"runs": [_row(s, now) for s in shown], "live": len(alive),
              "total": len(runs)})
    if any(s.needs_release for s in shown):
        env.warn("needs_release", "є машина, яку ще не відпущено: оренда тече — "
                                  "nysh cloud stop або nysh cloud rent status")
    return env


class GoArgs(BaseModel):
    case: list[str] = Field(description="справа або кілька: теки кадрів чи шифри з "
                                        "бібліотеки; кілька — однією чергою")
    run: bool = Field(default=False, description="справді орендувати; без цього — "
                                                 "сухий прогін: план, кошторис, рішення")
    confirm: bool = Field(default=False, description="дозвіл ЛЮДИНИ на захід понад "
                                                     "стелю автозапуску")
    backend: str = Field(default="vast", description="бекенд оренди")
    budget: float | None = Field(default=None, description="стеля витрат, $; без неї — "
                                                           "верх вилки кошторису")
    max_hours: float | None = Field(default=None, description="стеля тривалості, годин")
    max_price: float | None = Field(default=None, description="стеля ціни машини, $/год")
    script: str = Field(default="", description="письмо: latin | cyrillic; порожньо — "
                                                "визначити самому")
    model: str = Field(default="", description="перечитати іншою моделлю (ім'я ваг)")
    rerun: bool = Field(default=False, description="справу вже прочитано цією моделлю — "
                                                   "перечитати")
    for_project: str | None = Field(
        default=None, description="для кого захід (підпис запису й прогону): ім'я "
                                  "проєкту, порожньо — сама Майстерня; без поля — поточний")


@op("cloud.go", summary="Хмарний прогін: спершу кошторис і рішення, тоді оренда",
    args=GoArgs, section="htr", mutates=True, long=True, tier="core",
    skill="run-case-remote",
    when="хмарний прогін: велика справа (понад ~500 сторінок) на орендованій карті")
def cloud_go(a: GoArgs) -> Envelope:
    from nyshporka.cloud import go as GO
    from nyshporka.core import progress

    def on_event(kind: str, text: str, **_data: object) -> None:
        progress.report(0, 0, text)

    from nyshporka.core import projects as P

    try:
        who = P.ordered_for_id(a.for_project)
    except P.ProjectError as exc:
        return fail(str(exc))
    with P.ordered_for(who):
        res = GO.go(a.case, backend=a.backend, budget=a.budget, max_hours=a.max_hours,
                    max_price=a.max_price, confirm=a.confirm, dry_run=not a.run,
                    script=a.script, model=a.model, rerun=a.rerun, on_event=on_event)
    data = res.as_dict()
    if res.verdict in ("dry_run", "ok", "detached"):
        env = ok(data)
        if res.verdict == "dry_run":
            env.suggest("cloud.go", "запустити той самий захід: run=true"
                        + (" і confirm=true (понад стелю автозапуску)"
                           if res.launch == "needs_confirm" else ""))
        return env
    return Envelope(ok=False, data=data, error=f"{res.verdict}: {res.why}".rstrip(": "))


class RunArgs(BaseModel):
    run_id: str = Field(default="", description="ім'я заходу; порожньо — єдиний незавершений")


class StopArgs(RunArgs):
    force: bool = Field(default=False, description="кинути захід, не звіряючи")


@op("cloud.stop", summary="Зупинити хмарний прогін: погасити оренду, відпустити машину",
    args=StopArgs, section="htr", mutates=True, skill="run-case-remote",
    when="зупинити хмарний прогін: погасити оренду, відпустити машину")
def cloud_stop(a: StopArgs) -> Envelope:
    from nyshporka.cloud import control as CTL
    from nyshporka.cloud.base import CloudError

    try:
        st = CTL.need_run(a.run_id)
        res = CTL.stop(st, force=a.force)
    except (CTL.NoRun, CloudError) as exc:
        return fail(str(exc))
    data = {"run_id": st.run_id, **res.as_dict()}
    if not res.ok:
        return Envelope(ok=False, data=data,
                        error=f"наглядача {st.supervisor} спинити не вдалось")
    env = ok(data)
    if res.killed:
        # 🔴 Єдине, що стоїть між живою машиною й рахунком, — людина.
        env.warn("machine_alive", "наглядача вбито: машину нікому гасити — перевірте "
                                  "зараз `nysh cloud rent status`"
                                  + (f" (інстанс {res.machine})" if res.machine else ""))
    return env


@op("cloud.fetch", summary="Забрати результат хмарного прогону; повтор докачує",
    args=RunArgs, section="htr", mutates=True, long=True, skill="run-case-remote",
    when="забрати результат хмарного прогону; повтор докачує")
def cloud_fetch(a: RunArgs) -> Envelope:
    from nyshporka.cloud import control as CTL
    from nyshporka.cloud.base import CloudError
    from nyshporka.core import progress

    try:
        st = CTL.need_run(a.run_id)
        out = CTL.fetch(st, on_line=lambda s: progress.report(0, 0, s))
    except (CTL.NoRun, CloudError) as exc:
        return fail(str(exc))
    env = ok({"run_id": st.run_id, "out": str(out)})
    env.suggest("cloud.state", f"далі звірка: nysh cloud verify {st.run_id}")
    return env
