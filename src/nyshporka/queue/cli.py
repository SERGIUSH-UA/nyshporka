"""`nysh queue` — черга справ у командному рядку."""
from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape as _e

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Черга справ: кадри → паспорт → каталог → пул → читання → "
                       "облік → віддача, з продовженням після зупинки",
                  invoke_without_command=True, no_args_is_help=False)
console = brand.console()

_MARK = {"queued": "·", "running": "▶", "retry": "↻", "blocked": "⏸",
         "failed": "✖", "done": "✓", "dropped": "—"}
_STAGE_MARK = {"done": "✓", "todo": "·", "skip": "–"}


def _eta(sec: float | None) -> str:
    if sec is None:
        return "темп цієї машини ще не міряно"
    h, m = divmod(int(sec) // 60, 60)
    return f"≈ {h} год {m:02d} хв" if h else f"≈ {m} хв"


def _show(d: dict[str, Any]) -> None:
    rows = d.get("rows") or []
    runner = d.get("runner") or {}
    left = d.get("left") or {}
    if not rows:
        console.print("черга порожня · додати: [bold]nysh queue add <ключ або тека>[/bold]")
        return
    summary = " · ".join(f"{k} {v}" for k, v in (
        ("у черзі", (d.get("summary") or {}).get("queued")),
        ("у роботі", (d.get("summary") or {}).get("running")),
        ("повторить сама", (d.get("summary") or {}).get("retry")),
        ("чекає вас", (d.get("summary") or {}).get("blocked")),
        ("відмова", (d.get("summary") or {}).get("failed")),
        ("зроблено", (d.get("summary") or {}).get("done"))) if v)
    console.print(f"[bold]{summary}[/bold]")
    if left.get("cases"):
        bez = (f" (без {left['unknown']} справ, чиїх кадрів ще не взято)"
               if left.get("unknown") else "")
        console.print(f"[muted]лишилось: справ {left['cases']}, сторінок "
                      f"{left.get('pages', 0)}{bez} · {_eta(left.get('eta_sec'))}[/muted]")
    if runner.get("alive"):
        pulse = runner.get("pulse") or {}
        hid = (f" · {pulse.get('what', '')} {pulse.get('i')}/{pulse.get('n')}"
               if pulse.get("n") else "")
        console.print(f"[muted]виконавець: процес {runner.get('pid')}{_e(hid)}"
                      + (f" · зупинка: {d['stop']}" if d.get("stop") else "") + "[/muted]")
    else:
        console.print("[muted]чергу зараз ніхто не веде — nysh queue run[/muted]")
    console.print()
    for r in rows:
        stages = "".join(_STAGE_MARK.get(s["state"], "?") for s in r.get("stages") or [])
        obsiah = (f"{r.get('pages', 0)}/{r.get('frames') or '—'}"
                  if "frames" in r else "")
        console.print(f" {_MARK.get(r['state'], '?')} {_e(str(r['id'])):<32} "
                      f"{_e(r['state_text']):<15} {stages:<8} "
                      f"{_e(r.get('stage_text') or ''):<9} {obsiah}")
        if r.get("why"):
            console.print(f"     [warn]{_e(r['why'])}[/warn]")
        if r.get("fix") and r["state"] in ("blocked", "failed", "retry"):
            console.print(f"     [muted]далі: {_e(r['fix'])}[/muted]")
        if r["state"] == "retry" and r.get("not_before"):
            console.print(f"     [muted]повтор не раніше {_e(r['not_before'][11:16])}[/muted]")
    console.print("\n[muted]етапи: кадри · паспорт · каталог · пул · читання · облік · "
                  "віддача (✓ зроблено, · попереду, – не стосується)[/muted]")


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    all_: bool = typer.Option(False, "--all", help="разом зі зробленими й знятими"),
    journal: int = typer.Option(0, "--journal", help="останні N рядків журналу етапів"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що в черзі, на якому етапі кожна справа й що лишилось."""
    if ctx.invoked_subcommand is not None:
        return
    from nyshporka import ops as O

    env = O.call("queue.status", {"all": all_, "journal": journal})
    if _answer(env, as_json):
        return
    _show(env.data or {})
    for row in (env.data or {}).get("journal") or []:
        console.print(f"  [muted]{_e(str(row.get('at', ''))[11:19])} "
                      f"{_e(str(row.get('item', '')))} · {_e(str(row.get('stage', '')))} · "
                      f"{_e(str(row.get('outcome', '')))} · {row.get('sec', '')} с "
                      f"{_e(str(row.get('why', '')))}[/muted]")
    _notes(env)


@app.command("add")
def add(
    refs: list[str] = typer.Argument(..., help="ключ із реєстру опису або тека з кадрами"),
    share: bool = typer.Option(False, "--share", help="після читання віддати в Супрягу"),
    pool: str = typer.Option("", "--pool", help="auto | take | read; порожньо — як у профілі"),
    script: str = typer.Option("", "--script", help="письмо: latin | cyrillic"),
    one_voice: bool = typer.Option(False, "--one-voice", help="без другого рушія"),
    with_: list[str] = typer.Option([], "--with", help="ще голос тим самим проходом"),
    workers: int = typer.Option(1, "--workers", help="процесів читання на карті"),
    first: bool = typer.Option(False, "--first", help="на початок черги"),
    dry: bool = typer.Option(False, "--dry-run", help="лише показати, що було б додано"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Поставити справи в чергу."""
    from nyshporka import ops as O

    env = O.call("queue.add", {"refs": refs, "share": share, "pool": pool,
                               "script": script, "one_voice": one_voice, "with": with_,
                               "workers": workers, "first": first, "dry_run": dry})
    if _answer(env, as_json):
        return
    for r in (env.data or {}).get("rows") or []:
        if "id" not in r:
            continue                    # причину друкує попередження нижче
        if not r["added"] and r.get("why"):
            console.print(f" · {_e(r['id'])}: {_e(r['why'])}")
            continue
        console.print(f" {'+' if r['added'] else '?'} [bold]{_e(r['id'])}[/bold]"
                      + (f" — {_e(r['title'])}" if r.get("title") else ""))
        if r.get("opys_clash"):
            console.print(f"     [warn]{_e(r['opys_clash'])}[/warn]")
        elif r.get("kind") == "key" and r.get("frames_on_disk"):
            console.print(f"     [muted]кадри вже на диску: {r['frames_on_disk']} · "
                          f"{_e(r.get('case_dir') or '')}[/muted]")
        elif r.get("kind") == "key":
            console.print(f"     [muted]кадри: {_e(r.get('channel_why') or '')} → "
                          f"{_e(r.get('case_dir') or '')}[/muted]")
        if r.get("opys_assumed"):
            console.print(f"     [warn]опис у ключі не названо — узято опис "
                          f"{_e(str(r.get('opys') or '?'))}; якщо мали на увазі інший, "
                          f"це інша справа з тим самим номером[/warn]")
        if r.get("shifra_needs_eye"):
            console.print("     [warn]номер справи в реєстрі опису відновлено "
                          "інтерполяцією — шифру треба звірити оком[/warn]")
        elif r.get("link_why"):
            console.print(f"     [warn]{_e(r['link_why'])}[/warn] "
                          f"[muted]{_e(r.get('fix') or '')}[/muted]")
        p = r.get("pool") or {}
        if p:
            chyie = "ваше" if p.get("mine") else (", ".join(p.get("publishers") or [])
                                                  or "без підпису")
            console.print(f"     [muted]у зрізі пулу вже є: {p['pages']} стор."
                          + (f" із {p['frames']} кадрів" if p.get("frames") else "")
                          + f" · {_e(chyie)}[/muted]")
        if r.get("pool_mode") == "read" and not pool:
            console.print("     [muted]пул перед читанням не питається (так у профілі "
                          "обміну); питати: --pool auto[/muted]")
    _notes(env)


@app.command("run")
def run(
    stop_after_case: bool = typer.Option(False, "--stop-after-case",
                                         help="провести одну справу й вийти"),
    wait: bool = typer.Option(False, "--wait",
                              help="чекати справ, що повторюються, а не виходити"),
    share: bool = typer.Option(False, "--share", help="віддавати кожну справу цього заходу"),
    limit: int = typer.Option(0, "--limit", help="не більше N справ за захід"),
) -> None:
    """Вести чергу: справа за справою, етап за етапом.

    🔴 Працює прямо тут, а не через застосунок — як `nysh read`: таку роботу
    ставлять на ніч, часто по ssh. Зупинити після поточної справи —
    `nysh queue stop` з іншого термінала; зупинити зараз — Ctrl+C (прочитане
    лишається, наступний запуск продовжить).
    """
    from nyshporka.queue import runner as R
    from nyshporka.queue import state as Q

    try:
        got = R.run(stop_after_case=stop_after_case, wait=wait, share=share, limit=limit,
                    say=lambda t: console.print(_e(t)))
    except Q.QueueError as exc:
        console.print(f"[err]{_e(str(exc))}[/err]")
        raise typer.Exit(code=1) from None
    console.print(f"\nпроведено справ: {len(got['handled'])} · у черзі лишилось "
                  f"{got['left']} · чекає вас {got['waiting']}")
    if got.get("next_retry_at"):
        console.print(f"[muted]найближчий повтор не раніше {got['next_retry_at'][11:16]} — "
                      f"nysh queue run ще раз або одразу з --wait[/muted]")
    if got["waiting"]:
        console.print("[muted]що саме чекає й яка команда — nysh queue[/muted]")


@app.command("start")
def start(
    share: bool = typer.Option(False, "--share", help="віддавати кожну справу цього заходу"),
    wait: bool = typer.Option(False, "--wait", help="чекати справ, що повторюються"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Запустити виконавця у фоні: переживає закритий термінал."""
    from nyshporka import ops as O

    env = O.call("queue.start", {"share": share, "wait": wait})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if d.get("started"):
        console.print(f"виконавця запущено: процес {d['pid']} · вивід: {_e(d['log'])}")
    _notes(env)


@app.command("stop")
def stop(
    now: bool = typer.Option(False, "--now", help="погасити читання зараз; прочитане лишається"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зупинити чергу: після поточної справи або зараз."""
    from nyshporka import ops as O

    env = O.call("queue.stop", {"now": now})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if d.get("runner_alive"):
        console.print("зупиняю зараз: читання гаситься, прочитане лишається" if now
                      else "поточна справа доробиться, наступна не візьметься")
    _notes(env)


@app.command("retry")
def retry(
    ref: str = typer.Argument("", help="справа: ключ, тека або її ім'я"),
    all_: bool = typer.Option(False, "--all", help="усі, що чекають або стали"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Повернути в чергу справу, що стала."""
    from nyshporka import ops as O

    env = O.call("queue.retry", {"ref": ref, "all": all_})
    if _answer(env, as_json):
        return
    console.print(f"знову в черзі: {len((env.data or {}).get('queued') or [])}")
    _notes(env)


@app.command("set")
def set_(
    ref: str = typer.Argument(..., help="справа: ключ, тека або її ім'я"),
    pool: str = typer.Option("", "--pool", help="auto | take | read"),
    partial: str = typer.Option("", "--partial",
                                help="прийняти неповне читання як уривок — причина"),
    share: bool | None = typer.Option(None, "--share/--no-share",
                                      help="віддавати після читання"),
    script: str = typer.Option("", "--script", help="письмо: latin | cyrillic"),
    shifra_ok: bool = typer.Option(False, "--shifra-ok",
                                   help="шифру з реєстру опису звірено оком"),
    workers: int = typer.Option(0, "--workers", help="процесів читання на карті"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Рішення по справі: пул, уривок, письмо, віддача."""
    from nyshporka import ops as O

    env = O.call("queue.set", {"ref": ref, "pool": pool, "partial": partial,
                               "share": share, "script": script, "shifra_ok": shifra_ok,
                               "workers": workers})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"{_e(str(d.get('id')))}: записано · стан — {_e(str(d.get('state')))}")
    _notes(env)


@app.command("drop")
def drop(
    ref: str = typer.Argument(..., help="справа: ключ, тека або її ім'я"),
    why: str = typer.Option("", "--why", help="чому знято"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зняти справу з черги; з диска нічого не видаляється."""
    from nyshporka import ops as O

    env = O.call("queue.drop", {"ref": ref, "why": why})
    if _answer(env, as_json):
        return
    console.print(f"знято з черги: {_e(str((env.data or {}).get('dropped')))}")
    _notes(env)
