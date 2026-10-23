"""▶ Що читається зараз — усе разом: ця машина, черга, хмара — і як це спинити.

🔴 Доти кожен екран знав свою частину. «Прогони» показували «читається зараз»
без жодної кнопки, «Хмара» — «нічого не крутиться», коли справа читалась на
цій машині, а «Черга» не бачила прогону, запущеного з термінала чи помічником.
Людина бачила поступ, але не мала як ним керувати й не знала, хто його
запустив (дослідник, 23.10.2026: «найгірше — не зв'язаність запуску читання з
чергою й контролем»).

Тут одна відповідь на «що зараз читається»: де (ця машина / хмара), хто
запустив (черга / консоль / термінал чи помічник), скільки прочитано й чим
спинити. Екрани Читання показують її однаково.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


def _queue_runner() -> tuple[int, dict[str, Any]]:
    """PID живого виконавця черги і його пульс; `(0, {})` — черга стоїть."""
    try:
        from nyshporka.queue import state as Q

        q = Q.load()
        pid = int((q.get("runner") or {}).get("pid") or 0)
        if pid and Q.runner_alive():
            return pid, Q.read_pulse()
    except Exception:
        pass
    return 0, {}


def _ancestors(pid: int) -> set[int]:
    """Предки процесу — щоб сказати, хто запустив читання."""
    out: set[int] = set()
    with contextlib.suppress(Exception):
        import psutil

        out = {p.pid for p in psutil.Process(pid).parents()}
    return out


def _via(pids: list[int], queue_pid: int) -> str:
    """queue · console · terminal: чий це прогін."""
    me = os.getpid()
    for pid in pids:
        up = _ancestors(pid)
        if queue_pid and queue_pid in up:
            return "queue"
        if me in up:
            return "console"
    return "terminal"


def _run_of(case: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Прогін, що читає цю теку справи: недочитаний, найсвіжіший."""
    mine = [r for r in rows if Path(str(r.get("case_dir") or "")).name == case]
    if not mine:
        return {}
    return max(mine, key=lambda r: (not r.get("done"), str(r.get("updated") or "")))


def local_items() -> list[dict[str, Any]]:
    """Живі читання на цій машині, по справі (шарди однієї справи — один рядок)."""
    from nyshporka import htr_store as S
    from nyshporka.htr import runs as LIVE

    live = LIVE.alive()
    if not live:
        return []
    try:
        rows = S.list_cases()
    except Exception:
        rows = []
    queue_pid, pulse = _queue_runner()
    by: dict[str, list[Any]] = {}
    for r in live:
        if r.case:
            by.setdefault(r.case, []).append(r)
    out: list[dict[str, Any]] = []
    for case, parts in by.items():
        run = _run_of(case, rows)
        pids = [p.pid for p in parts]
        out.append({
            "where": "local", "case": case,
            "case_key": parts[0].case_key or str(run.get("case_key") or ""),
            "shifra": str(run.get("shifra") or ""), "title": str(run.get("title") or ""),
            "run": str(run.get("name") or ""), "model": str(run.get("model") or ""),
            "done": int(run.get("pages_done") or 0), "total": int(run.get("frames") or 0),
            "shards": len(parts), "minutes": max(p.minutes for p in parts),
            "via": _via(pids, queue_pid),
            "queue_item": str(pulse.get("item") or "") if queue_pid else "",
        })
    return out


def cloud_items() -> list[dict[str, Any]]:
    """Живі хмарні заходи — з тим самим набором полів, що й місцеві."""
    try:
        from nyshporka.cloud import state as CST

        runs = [s for s in CST.all_runs() if CST.is_live(s)]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for s in runs:
        out.append({
            "where": "cloud", "case": Path(s.case_dir).name if s.case_dir else "",
            "case_key": s.case_key, "shifra": "", "title": "", "run": s.run_id,
            "model": "", "done": int(s.pages_done or 0), "total": int(s.frames_total or 0),
            "shards": 0, "minutes": 0, "via": "cloud", "phase": s.human_phase(),
            "queue_item": "",
        })
    return out


@op("reading.now", summary="Що читається зараз: ця машина, черга, хмара",
    mutates=False, section="htr", tier="rare",
    when="що зараз читається, де й хто запустив — і як спинити")
def reading_now(_: NoArgs) -> Envelope:
    """Усі живі читання одним переліком — для панелі на екранах Читання."""
    items = local_items() + cloud_items()
    queue_pid, _pulse = _queue_runner()
    return ok({"items": items, "queue_running": bool(queue_pid)})


class ReadStopArgs(BaseModel):
    case: str = Field(description="тека справи, що читається на цій машині (як у reading.now)")


@op("read.stop", summary="Спинити читання справи на цій машині",
    args=ReadStopArgs, mutates=True, section="htr", tier="rare",
    when="спинити читання, запущене на цій машині (терміналом, помічником чи консоллю)")
def read_stop(a: ReadStopArgs) -> Envelope:
    """Погасити процеси читання цієї справи — усі шарди й їхніх нащадків.

    🔴 Гаситься лише той процес, що записаний у реєстрі живих читань і чий час
    старту збігся: PID, який ОС уже віддала іншій програмі, не чіпається.
    Прочитане лишається, справу можна дочитати («Дочитати» на Прогонах).
    """
    from nyshporka.core.lock import process_alive
    from nyshporka.htr import runs as LIVE
    from nyshporka.htr.session import kill_tree

    parts = [r for r in LIVE.alive() if r.case == a.case]
    if not parts:
        return fail(f"справа «{a.case}» на цій машині зараз не читається")
    stopped: list[int] = []
    survived: list[int] = []
    for r in parts:
        if process_alive(r.pid, r.created) is not True:
            continue
        left = kill_tree(r.pid)
        (survived if left else stopped).append(r.pid)
        if not left:
            LIVE.drop(r.pid)
    env = ok({"case": a.case, "stopped": stopped, "survived": survived})
    if survived:
        env.warn("survived", f"процеси не зупинились: {', '.join(map(str, survived))}")
    return env
