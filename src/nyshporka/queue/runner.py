"""Виконавець черги: `nysh queue run`.

Один на простір (`state.own`). Бере справи по черзі й веде кожну етапами,
доки вона не дійде до кінця або не стане — тоді бере наступну: справа, що
чекає людину чи мережу, чергу не зупиняє.

🔴 Перед кожною дією стан «у роботі, етап X» лягає на диск. Але продовження
після вбитого процесу на цьому записі НЕ стоїть: наступний запуск просто йде
етапами знову, і кожен етап сам каже з диска, зроблений він чи ні. Запис
потрібен людині («на чому обірвалось»), а не відновленню.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from nyshporka.queue import stages as ST
from nyshporka.queue import state as Q

#: Через скільки секунд повторити етап після тимчасової відмови: 1-ша, 2-га, 3-тя.
BACKOFF = (300.0, 1800.0, 7200.0)
#: Як часто виконавець, що чекає (`--wait`), дивиться на прапор зупинки.
WAIT_POLL_SEC = 5.0
#: Не частіше за це пульс прогресу лягає на диск.
PULSE_EVERY_SEC = 2.0

Say = Callable[[str], None]


def heal() -> list[str]:
    """Прибрати сліди обірваного виконавця. Кличеться лише під `state.own`.

    Справа в стані «у роботі» без живого виконавця — обрив: вона повертається
    в чергу й піде з того етапу, якого диск ще не підтверджує.
    """
    back: list[str] = []
    with Q.edit() as q:
        q["stop"] = ""
        for it in q["items"]:
            if it.get("state") == Q.RUNNING:
                stage = ST.TITLES.get(str(it.get("stage") or ""), it.get("stage") or "")
                Q.settle(it, Q.QUEUED, stage=str(it.get("stage") or ""),
                         why=f"обірвано на етапі «{stage}» — продовжиться з нього")
                back.append(str(it["id"]))
    return back


def rejudge(ctx: ST.Ctx) -> list[str]:
    """Справи, що чекали людину: якщо вона вже полагодила — назад у чергу.

    Дивиться лише на етап, на якому справа стала: `nysh case --shifra …` чи
    покладені кадри видно з диска, і окремої команди «я полагодив» не треба.
    """
    todo = [(str(it["id"]), str(it.get("stage") or ""), dict(it))
            for it in Q.load()["items"] if it.get("state") == Q.BLOCKED]
    fixed: list[str] = []
    for item_id, stage_name, snap in todo:
        stage = next((s for s in ST.STAGES if s.name == stage_name), None)
        if stage is None:
            continue
        try:
            good = stage.done(snap, ctx)
        except Exception:
            good = False
        if good:
            fixed.append(item_id)
    if fixed:
        with Q.edit() as q:
            for it in q["items"]:
                if it["id"] in fixed and it.get("state") == Q.BLOCKED:
                    Q.settle(it, Q.QUEUED, stage=str(it.get("stage") or ""))
                    it["attempts"] = {}
    return fixed


def _pick(q: dict[str, Any]) -> dict[str, Any] | None:
    """Наступна справа: перша в черзі; з тих, що повторюються, — чий час настав."""
    t = time.time()
    for it in q["items"]:
        if it.get("state") == Q.QUEUED:
            return dict(it)
        if it.get("state") == Q.RETRY and Q.stamp(it.get("not_before") or "") <= t:
            return dict(it)
    return None


def _next_retry(q: dict[str, Any]) -> float:
    """Коли настане час найближчої справи, що повторюється; 0 — таких немає."""
    times = [Q.stamp(it.get("not_before") or "") for it in q["items"]
             if it.get("state") == Q.RETRY]
    return min(times) if times else 0.0


def _stop_flag() -> str:
    try:
        return str(Q.load().get("stop") or "")
    except Q.QueueError:
        return ""


def _item(q: dict[str, Any], item_id: str) -> dict[str, Any]:
    for it in q["items"]:
        if it["id"] == item_id and it.get("state") != Q.DROPPED:
            return it  # type: ignore[no-any-return]
    raise Q.QueueError(f"справу «{item_id}» знято з черги посеред роботи")


def _settle(item_id: str, state: str, *, attempts: dict[str, int] | None = None,
            evidence: dict[str, Any] | None = None, **fields: str) -> dict[str, Any]:
    """Записати стан справи транзакцією; повертає її свіжий зріз."""
    with Q.edit() as q:
        it = _item(q, item_id)
        Q.settle(it, state, **fields)
        if attempts is not None:
            it["attempts"] = attempts
        if evidence:
            it.setdefault("evidence", {}).update(evidence)
        return dict(it)


def process(item: dict[str, Any], *, say: Say, share_all: bool = False) -> str:
    """Провести одну справу етапами. Повертає її кінцевий стан."""
    item_id = str(item["id"])
    last_pulse = [0.0]
    stage_now = [""]

    def _progress(i: int, n: int, what: str) -> None:
        if time.monotonic() - last_pulse[0] < PULSE_EVERY_SEC and i < n:
            return
        last_pulse[0] = time.monotonic()
        Q.pulse(item=item_id, stage=stage_now[0], i=i, n=n, what=what)

    ctx = ST.Ctx(say=lambda t: say(f"    {t}"), progress=_progress,
                 should_stop=lambda: _stop_flag() == Q.STOP_NOW, share_all=share_all)

    for stage in ST.STAGES:
        name = stage.name
        if _stop_flag() == Q.STOP_NOW:
            _settle(item_id, Q.QUEUED, stage=name, why="зупинено на прохання")
            return Q.QUEUED
        if not stage.applies(item, ctx) or stage.done(item, ctx):
            continue
        stage_now[0] = name
        # 🔴 Запис ПЕРЕД дією: після вбитого процесу видно, на чому обірвалось.
        item = _settle(item_id, Q.RUNNING, stage=name)
        with Q.edit() as q:
            q["runner"] = {**(q.get("runner") or {}), "item": item_id, "stage": name,
                           "since": Q.now()}
        say(f"  → {stage.title}")
        t0 = time.monotonic()
        try:
            out = stage.run(item, ctx)
        except KeyboardInterrupt:
            _settle(item_id, Q.QUEUED, stage=name, why="зупинено з клавіатури")
            Q.journal(item=item_id, stage=name, outcome=ST.STOPPED,
                      sec=round(time.monotonic() - t0, 1))
            raise
        except Exception as exc:
            # Несподіваний збій етапу — не привід ні зупиняти чергу, ні крутити
            # його по колу: справа чекає людину з текстом збою.
            out = ST.blocked("crash", f"{type(exc).__name__}: {exc}",
                             f'nysh queue retry "{item_id}"')
        Q.journal(item=item_id, stage=name, outcome=out.kind, code=out.code,
                  why=out.why or out.note, sec=round(time.monotonic() - t0, 1))

        if out.kind == ST.OK:
            item = _settle(item_id, Q.RUNNING, stage=name, evidence=out.evidence)
            if out.note:
                say(f"    {out.note}")
            if not stage.done(item, ctx):
                # Етап сказав «зроблено», а диск цього не підтверджує: іти далі
                # означало б будувати наступні етапи на тому, чого немає.
                why = (f"етап «{stage.title}» завершився без помилки, але його "
                       f"результату на диску не видно")
                _settle(item_id, Q.BLOCKED, stage=name, code="not_confirmed", why=why,
                        fix=f'nysh queue retry "{item_id}"')
                say(f"  ⏸ {why}")
                return Q.BLOCKED
            continue

        if out.kind == ST.STOPPED:
            _settle(item_id, Q.QUEUED, stage=name, why=out.why)
            say(f"  ⏹ {out.why}")
            return Q.QUEUED

        if out.kind == ST.RETRY:
            tried = dict(item.get("attempts") or {})
            tries = int(tried.get(name) or 0) + (0 if out.patient else 1)
            if tries > len(BACKOFF):
                why = f"{out.why} (після {len(BACKOFF)} повторів)"
                _settle(item_id, Q.BLOCKED, stage=name, code=out.code, why=why,
                        fix=out.fix or f'nysh queue retry "{item_id}"')
                say(f"  ⏸ {why}")
                return Q.BLOCKED
            after = BACKOFF[max(0, tries - 1)] if out.after is None else out.after
            when = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() + after))
            _settle(item_id, Q.RETRY, stage=name, code=out.code, why=out.why, fix=out.fix,
                    not_before=when, attempts={**tried, name: tries})
            say(f"  ↻ {out.why} — повтор не раніше {when[11:16]}")
            return Q.RETRY

        state = Q.FAILED if out.kind == ST.FAILED else Q.BLOCKED
        _settle(item_id, state, stage=name, code=out.code, why=out.why, fix=out.fix)
        say(f"  {'✖' if state == Q.FAILED else '⏸'} {out.why}")
        if out.fix:
            say(f"    далі: {out.fix}")
        return state

    _settle(item_id, Q.DONE, attempts={})
    say("  ✓ зроблено")
    return Q.DONE


def run(*, stop_after_case: bool = False, wait: bool = False, share: bool = False,
        limit: int = 0, say: Say = print,
        sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Вести чергу, доки є що брати. Повертає підсумок заходу."""
    seen: list[dict[str, str]] = []
    stopped = ""
    with Q.own():
        back = heal()
        for item_id in back:
            say(f"обірвану справу повернуто в чергу: {item_id}")
        for item_id in rejudge(ST.Ctx(share_all=share)):
            say(f"полагоджено — знову в черзі: {item_id}")
        try:
            while True:
                q = Q.load()
                flag = str(q.get("stop") or "")
                if flag:
                    stopped = flag
                    break
                item = _pick(q)
                if item is None:
                    due = _next_retry(q)
                    if not (wait and due):
                        break
                    sleep(min(WAIT_POLL_SEC, max(0.0, due - time.time())))
                    continue
                say(f"{item['id']}")
                state = process(item, say=say, share_all=share)
                seen.append({"id": str(item["id"]), "state": state})
                if stop_after_case or (limit and len(seen) >= limit):
                    break
        except KeyboardInterrupt:
            stopped = Q.STOP_NOW
            say("зупинено з клавіатури — прочитане лишилось на диску")
        finally:
            with Q.edit() as q:
                q["stop"] = ""
    q = Q.load()
    due = _next_retry(q)
    return {
        "handled": seen,
        "stopped": stopped,
        "left": sum(1 for it in q["items"] if it.get("state") in Q.LIVE),
        "waiting": sum(1 for it in q["items"] if it.get("state") in Q.WAITING),
        "next_retry_at": (time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(due))
                          if due else ""),
    }
