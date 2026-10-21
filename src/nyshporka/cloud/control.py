"""☁️🎛 Керування заходом без друку: знайти, спинити, забрати.

Спільне для `nysh cloud …` і операцій консолі (`cloud.ops`): командний рядок
друкує відповідь людині, консоль показує її у вікні, а рішення — який захід,
чи можна спиняти, хто гасить машину — приймаються тут один раз.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nyshporka.cloud.state import RunState


class NoRun(ValueError):
    """Захід не знайдено; `code` — код виходу командного рядка."""

    def __init__(self, text: str, code: int = 1) -> None:
        super().__init__(text)
        self.code = code


def need_run(run_id: str) -> RunState:
    """Захід за іменем, або єдиний незавершений.

    🔴 Коли незавершених кілька — відмова з переліком, а не «візьму перший».
    Мовчазний вибір тут означав би забрати результат одного заходу й погасити
    машину іншого.
    """
    from nyshporka.cloud import state as ST

    if run_id:
        st = ST.load(run_id)
        if st is None:
            raise NoRun(f"немає заходу «{run_id}»", code=2)
        return st
    alive = ST.live()
    if not alive:
        recent = ST.all_runs()
        if not recent:
            raise NoRun("жодного заходу ще не було")
        return recent[0]
    if len(alive) > 1:
        names = ", ".join(s.run_id for s in alive)
        raise NoRun(f"незавершених заходів кілька: {names}. Назвіть потрібний явно", code=2)
    return alive[0]


def detached_refusal(st: RunState, what: str) -> str | None:
    """Чому `what` не має сенсу для відчепленого заходу; `None` — має.

    🔴 Не косметика. `verify` без наглядача записав би вирок `incomplete` живому
    заходу — а вирок ставить фазу `failed`, після чого ні перелік живих, ні
    пошук чужого заходу його вже не бачать, і наступний `go` спокійно бере
    ДРУГУ машину під ту саму справу. `fetch` так само: забирати нема звідки,
    бо машини в нашому записі немає.
    """
    if not st.supervisor:
        return None
    return (f"{what} тут нічого не дасть: захід веде наглядач {st.supervisor}, і "
            f"машина в нього, а не в нас. Забір, звірку й гасіння він робить сам.")


def close_if_silent(st: RunState) -> None:
    """Закрити запис, наглядач якого так і не озвався, — після `--force`.

    🔴 Запис невдалого старту лишається відкритим, щоб наступний `go` не взяв
    другої машини. Але якщо наглядача насправді не було, питати про стан
    нікого, і без цього виходу справа трималась би ним вічно. `--force` — це
    рішення людини, якій щойно сказано перевірити `rent status`; поки наглядач
    відповідає, запис закриє його власний підсумок, а не ми.
    """
    from nyshporka.cloud import supervised as SUP

    try:
        silent = not SUP.state_of(st)
    except SUP.SupervisorMissing:
        return
    if silent and st.phase not in ("done", "failed"):
        st.note("closed_by_human", f"наглядач {st.supervisor} мовчить; "
                                   f"запис закрито `stop --force`")
        st.enter("failed", why="закрито людиною: наглядач мовчав")


@dataclass
class Stopped:
    ok: bool
    detached: bool
    #: Чи вбито наглядача (тоді машину нікому гасити).
    killed: bool = False
    machine: str = ""
    said: str = ""
    #: Інші справи тієї самої черги — згорнуто разом із цією.
    siblings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def stop(st: RunState, *, force: bool = False, on_line: Any = None) -> Stopped:
    """Згорнути захід. Відчеплений — просимо наглядача, свій — відпускаємо самі.

    `CloudError` власного заходу (роботу не звірено) летить далі: це відмова,
    яку людина мусить прочитати, а не збій.
    """
    if st.supervisor:
        from nyshporka.cloud import supervised as SUP

        res = SUP.stop(st, force=force)
        if force:
            close_if_silent(st)
        return Stopped(ok=res.ok, detached=True, killed=res.killed, machine=res.machine,
                       said=res.said, siblings=list(st.siblings))
    from nyshporka.cloud import run as RUN

    RUN.release(st, force=force, on_line=on_line)
    return Stopped(ok=True, detached=False)


def fetch(st: RunState, *, on_line: Any = None) -> Path:
    """Забрати результат свого заходу. Повтор докачує."""
    from nyshporka.cloud import run as RUN

    if (why := detached_refusal(st, "забір")) is not None:
        raise NoRun(why, code=2)
    return RUN.fetch(st, on_line=on_line)
