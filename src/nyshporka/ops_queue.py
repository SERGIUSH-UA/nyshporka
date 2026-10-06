"""Операції черги справ: подивитись, додати, вирішити, зупинити, запустити.

🔴 Усі — `agent=False`: стартовий перелік агента тримається коротким, а
агентові вистачає командного рядка (`nysh queue …`).

Сам виконавець операцією не є: `nysh queue run` — довга робота в терміналі,
як `nysh read`. Операції лише читають і правлять файл черги.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "htr"


def _rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рядки черги для показу: стан із файла, етапи й сторінки — з диска."""
    from nyshporka.queue import stages as ST
    from nyshporka.queue import state as Q

    # Один знімок прогонів на всю відповідь (`stages.one_moment`): без нього
    # кожен етап кожної справи будував мапу прогонів наново. Знімок — лише
    # коли є кого перечитувати з диска: зроблені й зняті його не питають.
    live = any(it.get("state") not in (Q.DONE, Q.DROPPED) for it in items)
    with ST.one_moment() if live else nullcontext():
        return _rows_now(items)


def _rows_now(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from nyshporka.cloud.verify import texts_in
    from nyshporka.queue import stages as ST
    from nyshporka.queue import state as Q

    out = []
    for it in items:
        row: dict[str, Any] = {
            "id": it["id"], "state": it.get("state"), "state_text": Q.NAZVY.get(
                str(it.get("state")), str(it.get("state"))),
            "stage": it.get("stage") or "",
            "stage_text": ST.TITLES.get(str(it.get("stage") or ""), ""),
            "code": it.get("code") or "", "why": it.get("why") or "",
            "fix": it.get("fix") or "", "not_before": it.get("not_before") or "",
            "opts": it.get("opts") or {}, "added": it.get("added") or "",
        }
        if it.get("state") not in (Q.DONE, Q.DROPPED):
            # Зроблені й зняті з диска не перечитуються: їхній стан уже остаточний.
            w = ST.where(it)
            out_dir = ST._own_out(w)
            row["frames"] = w.frames
            row["pages"] = texts_in(out_dir) if out_dir is not None else 0
            row["case_dir"] = str(w.case_dir or "")
            row["stages"] = ST.progress_of(it)
        out.append(row)
    return out


def _sec_per_page() -> float | None:
    """Темп читання на ЦІЙ машині — медіана власних прогонів; `None` — ще не міряно."""
    from statistics import median

    from nyshporka import htr_store as S

    secs = [float(r["sec_median"]) for r in S.list_cases()
            if r.get("sec_median") and not r.get("shared")]
    return float(median(secs)) if secs else None


class QueueStatusArgs(BaseModel):
    all: bool = Field(default=False, description="разом зі зробленими й знятими")
    journal: int = Field(default=0, ge=0, le=200,
                         description="скільки останніх рядків журналу етапів віддати")


@op("queue.status", summary="Черга справ: що на якому етапі й що лишилось",
    args=QueueStatusArgs, agent=False, section=SECTION)
def queue_status(a: QueueStatusArgs) -> Envelope:
    """Справи черги зі станом, етапом, причиною зупинки й командою «що далі».

    Етап і число прочитаних сторінок беруться з диска в мить запиту, а не з
    файла черги: файл пам'ятає лише, що замовлено й чому справа стоїть.
    """
    from nyshporka.queue import state as Q

    try:
        q = Q.load()
    except Q.QueueError as exc:
        return fail(str(exc))
    items = [it for it in q["items"]
             if a.all or it.get("state") not in (Q.DONE, Q.DROPPED)]
    rows = _rows(items)
    live = [r for r in rows if r["state"] in Q.LIVE]
    pages_left = sum(max(0, int(r.get("frames") or 0) - int(r.get("pages") or 0))
                     for r in live)
    sec = _sec_per_page()
    alive = Q.runner_alive()
    data: dict[str, Any] = {
        "rows": rows, "count": len(rows),
        "summary": {name: sum(1 for it in q["items"] if it.get("state") == name)
                    for name in Q.NAZVY},
        # Справи, чиїх кадрів ще немає на диску: скільки в них сторінок, невідомо,
        # і нуль на їхньому місці читався б як «майже все зроблено».
        "left": {"cases": len(live), "pages": pages_left,
                 "unknown": sum(1 for r in live if not r.get("frames")),
                 "sec_per_page": sec,
                 "eta_sec": round(pages_left * sec) if sec is not None else None},
        "runner": {**(q.get("runner") or {}), "alive": alive,
                   "pulse": Q.read_pulse() if alive else {}},
        "stop": q.get("stop") or "",
    }
    if a.journal:
        data["journal"] = Q.read_journal(a.journal)
    env = ok(data)
    stale = [r["id"] for r in rows if r["state"] == Q.RUNNING]
    if stale and not alive:
        env.warn("runner_gone",
                 f"справа «{stale[0]}» позначена «у роботі», а виконавця немає — "
                 f"його обірвано. Продовжити: nysh queue run")
    waiting = [r for r in rows if r["state"] in Q.WAITING]
    if waiting:
        env.warn("needs_you", f"справ чекає вашого рішення: {len(waiting)} — "
                              f"причина й команда в кожному рядку")
    return env


class QueueAddArgs(BaseModel):
    refs: list[str] = Field(description="справи: ключ із реєстру опису "
                                        "(«DAHMO/315/1/8433») або тека з кадрами")
    share: bool = Field(default=False, description="після читання віддати в Супрягу")
    pool: str = Field(default="", description="пул перед читанням: auto — брати лише "
                                              "певне, take — узяти, що є, read — не питати; "
                                              "порожньо — як у профілі обміну")
    script: str = Field(default="", description="письмо: latin | cyrillic")
    one_voice: bool = Field(default=False, description="без другого рушія")
    with_: list[str] = Field(default_factory=list, alias="with",
                             description="ще голос тим самим проходом (latin або ім'я ваг)")
    workers: int = Field(default=1, ge=1, le=8, description="процесів читання на карті")
    first: bool = Field(default=False, description="поставити на початок черги")
    dry_run: bool = Field(default=False, description="лише показати, що було б додано")

    model_config = {"populate_by_name": True}


def _resolve(ref: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Що людина назвала: `(id, ref, відомості)`; відмова — `QueueError`."""
    from nyshporka.cases import chain as C
    from nyshporka.cases import span as SP
    from nyshporka.cases import take
    from nyshporka.cases.register import case_path
    from nyshporka.queue.state import QueueError

    raw = str(ref or "").strip()
    if not raw:
        raise QueueError("порожня назва справи")
    d = case_path(raw)
    if d.is_dir():
        zbirna = SP.of_dir(d)
        if zbirna is not None:
            raise QueueError(f"«{raw}» — збірна тека: {zbirna.why}. {SP.fix(raw)}")
        C._forget_caches()
        lanka = C.judge(d)
        return (lanka.key or lanka.path, {"dir": lanka.path},
                {"kind": "dir", "case_dir": lanka.path, "link": lanka.link,
                 "link_why": lanka.why, "fix": lanka.fix})
    try:
        plan = take.plan(raw)
    except take.TakeError as exc:
        raise QueueError(
            f"«{raw}» — не тека з кадрами і не справа з реєстру опису ({exc})") from None
    from pathlib import Path as _P

    from nyshporka.htr.run import count_frames
    from nyshporka.share import align

    teka = _P(plan["case_dir"])
    kadry = align._frames_dir(teka) if teka.is_dir() else None
    adresa = str(plan["key"])
    return (adresa, {"key": adresa},
            {"kind": "key", "case_dir": plan["case_dir"], "channel": plan["channel"],
             "channel_why": plan["why"], "title": plan["title"],
             # Кадри вже лежать — черга їх не качатиме, і каналу їй не треба.
             "frames_on_disk": count_frames(kadry) if kadry else 0,
             "opys": plan.get("opys") or "",
             "opys_assumed": bool(plan.get("opys_assumed")),
             "shifra_needs_eye": bool(plan.get("shifra_needs_eye"))})


def _pool_note(key: str) -> dict[str, Any]:
    """Що про справу каже наявний зріз пулу — без мережі."""
    try:
        from nyshporka.share.suggest import _komirka

        cell = _komirka(key) if key else None
    except Exception:
        cell = None
    if cell is None or not cell.pages:
        return {}
    return {"pages": cell.pages, "frames": cell.frames, "coverage": cell.coverage,
            "mine": cell.mine, "publishers": list(cell.publishers)}


@op("queue.add", summary="Поставити справи в чергу",
    args=QueueAddArgs, mutates=True, agent=False, section=SECTION)
def queue_add(a: QueueAddArgs) -> Envelope:
    """Справа з реєстру опису (черга сама візьме кадри) або тека, що вже на диску.

    Збірну теку — кадри кількох справ під одним іменем — черга не бере.
    """
    from nyshporka.queue import stages as ST
    from nyshporka.queue import state as Q

    if a.pool and a.pool not in ST.POOL_MODES:
        return fail(f"--pool «{a.pool}»: чекаю auto, take або read")
    opts: dict[str, Any] = {k: v for k, v in (
        ("share", a.share), ("pool", a.pool), ("script", a.script),
        ("one_voice", a.one_voice), ("with", list(a.with_)),
        ("workers", a.workers if a.workers > 1 else 0)) if v}
    rows: list[dict[str, Any]] = []
    fresh: list[dict[str, Any]] = []
    try:
        q0 = Q.load()
    except Q.QueueError as exc:
        return fail(str(exc))
    for raw in a.refs:
        try:
            item_id, ref, info = _resolve(raw)
        except Q.QueueError as exc:
            rows.append({"asked": raw, "added": False, "why": str(exc)})
            continue
        have = Q.find(q0, item_id) or next((r for r in fresh if r["id"] == item_id), None)
        if have is not None:
            rows.append({"asked": raw, "id": item_id, "added": False,
                         "why": f"уже в черзі ({Q.NAZVY.get(str(have.get('state')), '')})"})
            continue
        item = Q.new_item(item_id, ref, dict(opts))
        fresh.append(item)
        rows.append({"asked": raw, "id": item_id, "added": not a.dry_run, **info,
                     "pool": _pool_note(item_id), "pool_mode": ST.pool_mode(item),
                     "stages": ST.progress_of(item)})
    if fresh and not a.dry_run:
        try:
            with Q.edit() as q:
                q["items"] = (fresh + q["items"]) if a.first else (q["items"] + fresh)
        except Q.QueueError as exc:
            return fail(str(exc))
    env = ok({"rows": rows, "added": 0 if a.dry_run else len(fresh),
              "dry_run": a.dry_run})
    for r in rows:
        if "id" not in r:
            env.warn("not_added", str(r["why"]))
    if fresh and not a.dry_run and not Q.runner_alive():
        env.suggest("queue.start", "чергу зараз ніхто не веде — запустити: nysh queue run")
    return env


class QueueRefArgs(BaseModel):
    ref: str = Field(default="", description="справа: ключ, тека або її ім'я")
    all: bool = Field(default=False, description="усі справи, що чекають або стали")


@op("queue.retry", summary="Повернути в чергу справу, що стала",
    args=QueueRefArgs, mutates=True, agent=False, section=SECTION)
def queue_retry(a: QueueRefArgs) -> Envelope:
    """Справи «чекає вас», «відмова» й «повторить сама» — знову в чергу, спроби з нуля."""
    from nyshporka.queue import state as Q

    if not (a.ref or a.all):
        return fail("яку справу повторити: назвіть її або --all")
    try:
        with Q.edit() as q:
            picked = ([it for it in q["items"] if it.get("state") in (*Q.WAITING, Q.RETRY)]
                      if a.all else [Q.need(q, a.ref)])
            back = []
            for it in picked:
                if it.get("state") == Q.RUNNING:
                    continue
                Q.settle(it, Q.QUEUED, stage=str(it.get("stage") or ""))
                it["attempts"] = {}
                back.append(it["id"])
    except Q.QueueError as exc:
        return fail(str(exc))
    return ok({"queued": back})


class QueueSetArgs(BaseModel):
    ref: str = Field(description="справа: ключ, тека або її ім'я")
    pool: str = Field(default="", description="auto | take | read")
    partial: str = Field(default="", description="прийняти неповне читання як уривок — "
                                                 "причина; «-» — зняти")
    share: bool | None = Field(default=None, description="віддавати після читання")
    script: str = Field(default="", description="письмо: latin | cyrillic")
    shifra_ok: bool = Field(default=False, description="шифру з реєстру опису звірено оком")
    workers: int = Field(default=0, ge=0, le=8, description="процесів читання на карті")


@op("queue.set", summary="Рішення по справі черги: пул, уривок, письмо, віддача",
    args=QueueSetArgs, mutates=True, agent=False, section=SECTION)
def queue_set(a: QueueSetArgs) -> Envelope:
    """Записати рішення людини по справі; справа, що стала, повертається в чергу."""
    from nyshporka.queue import stages as ST
    from nyshporka.queue import state as Q

    if a.pool and a.pool not in ST.POOL_MODES:
        return fail(f"--pool «{a.pool}»: чекаю auto, take або read")
    if a.script and a.script not in ("latin", "cyrillic"):
        return fail(f"--script «{a.script}»: чекаю latin або cyrillic")
    try:
        with Q.edit() as q:
            it = Q.need(q, a.ref)
            opts = it.setdefault("opts", {})
            if a.pool:
                opts["pool"] = a.pool
            if a.partial == "-":
                opts.pop("partial_why", None)
            elif a.partial:
                opts["partial_why"] = a.partial
            if a.share is not None:
                opts["share"] = a.share
            if a.script:
                opts["script"] = a.script
            if a.shifra_ok:
                opts["shifra_ok"] = True
            if a.workers:
                opts["workers"] = a.workers
            if it.get("state") in (*Q.WAITING, Q.RETRY):
                Q.settle(it, Q.QUEUED, stage=str(it.get("stage") or ""))
                it["attempts"] = {}
            snap = dict(it)
    except Q.QueueError as exc:
        return fail(str(exc))
    return ok({"id": snap["id"], "state": snap["state"], "opts": snap["opts"]})


class QueueDropArgs(BaseModel):
    ref: str = Field(description="справа: ключ, тека або її ім'я")
    why: str = Field(default="", description="чому знято — лишається в черзі й журналі")


@op("queue.drop", summary="Зняти справу з черги",
    args=QueueDropArgs, mutates=True, agent=False, section=SECTION)
def queue_drop(a: QueueDropArgs) -> Envelope:
    """Зняти справу з черги. З диска нічого не видаляється: кадри й прочитане лишаються."""
    from nyshporka.queue import state as Q

    try:
        with Q.edit() as q:
            it = Q.need(q, a.ref)
            if it.get("state") == Q.RUNNING and Q.runner_alive():
                return fail(f"справу «{it['id']}» зараз веде виконавець — спершу "
                            f"зупиніть: nysh queue stop --now")
            Q.settle(it, Q.DROPPED, stage=str(it.get("stage") or ""), why=a.why)
            item_id = str(it["id"])
    except Q.QueueError as exc:
        return fail(str(exc))
    Q.journal(item=item_id, outcome="dropped", why=a.why)
    return ok({"dropped": item_id})


class QueueStopArgs(BaseModel):
    now: bool = Field(default=False,
                      description="погасити читання зараз (прочитане лишається); "
                                  "без цього — доробити поточну справу й не брати наступну")


@op("queue.stop", summary="Зупинити чергу: після поточної справи або зараз",
    args=QueueStopArgs, mutates=True, agent=False, section=SECTION)
def queue_stop(a: QueueStopArgs) -> Envelope:
    """Поставити прапор зупинки. Виконавець бачить його між справами, а `now` —
    раз на дві секунди посеред читання."""
    from nyshporka.queue import state as Q

    if not Q.runner_alive():
        env = ok({"stop": "", "runner_alive": False})
        env.warn("no_runner", "чергу зараз ніхто не веде — зупиняти нічого")
        return env
    try:
        with Q.edit() as q:
            q["stop"] = Q.STOP_NOW if a.now else Q.STOP_AFTER_CASE
            flag = q["stop"]
    except Q.QueueError as exc:
        return fail(str(exc))
    return ok({"stop": flag, "runner_alive": True})


class QueueStartArgs(BaseModel):
    share: bool = Field(default=False, description="віддавати кожну справу цього заходу")
    wait: bool = Field(default=False, description="чекати справ, що повторюються, а не виходити")


@op("queue.start", summary="Запустити виконавця черги у фоні",
    args=QueueStartArgs, mutates=True, agent=False, section=SECTION)
def queue_start(a: QueueStartArgs) -> Envelope:
    """Підняти `nysh queue run` відчепленим процесом: він переживає і термінал, і
    застосунок. Вивід — у `data/queue/run.log`. Без фону — `nysh queue run`."""
    import os
    import subprocess
    import sys

    from nyshporka.core.workspace import workspace
    from nyshporka.queue import state as Q

    try:
        q = Q.load()
    except Q.QueueError as exc:
        return fail(str(exc))
    if Q.runner_alive():
        pid = int((q.get("runner") or {}).get("pid") or 0)
        env = ok({"started": False, "pid": pid})
        env.warn("already_running", f"чергу вже веде процес {pid or '—'}")
        return env
    if not any(it.get("state") in Q.LIVE for it in q["items"]):
        return fail("у черзі немає справ, які можна вести: додайте — nysh queue add <справа>")
    cmd = [sys.executable, "-m", "nyshporka", "queue", "run"]
    if a.share:
        cmd.append("--share")
    if a.wait:
        cmd.append("--wait")
    log = Q.home() / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    kw: dict[str, Any] = {"cwd": str(workspace().root), "stdin": subprocess.DEVNULL,
                          "env": {**os.environ, "PYTHONIOENCODING": "utf-8",
                                  "PYTHONUTF8": "1"}}
    if os.name == "nt":
        # getattr: обидва прапорці є лише у Windows, і mypy на Linux
        # відмовляє на самому імені.
        kw["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                               | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        kw["start_new_session"] = True
    with log.open("ab") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, **kw)
    return ok({"started": True, "pid": proc.pid, "log": str(Path(log))})
