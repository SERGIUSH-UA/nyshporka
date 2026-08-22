"""🧾 `nysh registry` — скласти перелік справ фонду.

⚠ Не `nysh crawl`, хоч обидва обходять чужий сайт. `crawl` збирає каталог на
ВЕСЬ простір, без фонду й без ключа опису, і живить `nysh find`. Тут інший
знаменник («усе, що існує в ЦЬОМУ фонді») і інший вихід — файл у `registry/`,
ключований шифрою. Одна команда на два виходи означала б, що людина не знає
заздалегідь, який файл змінить її запуск.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from nyshporka import ops as O

app = typer.Typer(help="Реєстр опису: скласти перелік справ фонду.",
                  no_args_is_help=True)
console = Console()


def _fail(env: object) -> None:
    console.print(f"[red]{getattr(env, 'error', '') or 'не вдалось'}[/red]")
    raise typer.Exit(code=1)


@app.command("sources")
def cmd_sources() -> None:
    """Які збирачі є і що кожен уміє."""
    env = O.call("registry.collectors", {})
    if not env.ok:
        _fail(env)
    rows = (env.data or {}).get("collectors") or []
    if not rows:
        console.print("[yellow]жодного збирача[/yellow]")
    for c in rows:
        console.print(f"  [bold]{c['id']:<10}[/bold] {c['label']}")
        console.print(f"             уміє: {', '.join(c['caps'])} → {c['file']}"
                      + (f" · качає: {c['source']}" if c["source"] else ""))
    for w in env.warnings:
        console.print(f"[yellow]⚠ {w.text}[/yellow]")


@app.command("plan")
def cmd_plan(
    collector: str = typer.Argument(..., help="archium | commons | duck"),
    fond: str = typer.Option(..., "--fond"),
    repo: str = typer.Option("DAHMO", "--repo", help="код або назва архіву"),
    opys: str = typer.Option("", "--opys", help="описи через кому"),
) -> None:
    """Скільки коштуватиме збирання — ДО того, як воно почалось."""
    env = O.call("registry.plan", {"collector": collector, "repo": repo,
                                   "fond": fond, "opys": opys})
    if not env.ok:
        _fail(env)
    d = env.data or {}
    console.print(f"  збирач : [bold]{d.get('collector')}[/bold]")
    console.print(f"  готовий: {'так' if d.get('ready') else '[red]ні[/red]'}")
    if d.get("why"):
        console.print(f"  {d['why']}")
    if d.get("opys"):
        console.print(f"  описи  : {', '.join(d['opys'])}")
    if d.get("requests") is not None:
        eta = d.get("eta_sec") or 0
        console.print(f"  запитів: {d['requests']}"
                      + (f" · орієнтовно {eta / 60:.0f} хв" if eta > 90 else ""))
    for k, v in (d.get("needs") or {}).items():
        console.print(f"  [yellow]бракує {k}: {v}[/yellow]")


@app.command("collect")
def cmd_collect(
    collector: str = typer.Argument(..., help="archium | commons | duck"),
    fond: str = typer.Option(..., "--fond"),
    repo: str = typer.Option("DAHMO", "--repo", help="код або назва архіву"),
    opys: str = typer.Option("", "--opys", help="описи через кому"),
    refresh: bool = typer.Option(False, "--refresh", help="не читати кеш"),
    dry_run: bool = typer.Option(False, "--dry-run", help="нічого не писати"),
    fond_id: str = typer.Option("", "--fond-id",
                                help="внутрішній номер фонду на сайті архіву"),
) -> None:
    """Зібрати перелік справ фонду в `registry/<збирач>.tsv`."""
    env = O.call("registry.collect", {"collector": collector, "repo": repo,
                                      "fond": fond, "opys": opys,
                                      "refresh": refresh, "dry_run": dry_run,
                                      "fond_id": fond_id})
    if not env.ok:
        _fail(env)
    d = env.data or {}
    console.print(f"[green]✓[/green] {d.get('rows')} справ → {d.get('out')}")

    seen, got = d.get("opys_seen") or [], d.get("opys_collected") or []
    if seen:
        console.print(f"  описів: показано {len(seen)}, зібрано {len(got)}")
    q = d.get("quality") or {}
    if q and d.get("rows"):
        total = int(d["rows"]) or 1
        parts = [f"{name} {n} ({n * 100 // total}%)" for name, n in sorted(q.items())]
        console.print("  " + " · ".join(parts))
    if d.get("kept"):
        console.print(f"  [dim]♻ долучено {d['kept']} рядків описів, "
                      f"яких цей запуск не чіпав[/dim]")
    for w in env.warnings:
        console.print(f"[yellow]⚠ {w.text}[/yellow]")


@app.command("show")
def cmd_show(fond_id: str = typer.Option(..., "--fond-id",
                                         help="тека фонду: cdiak_224")) -> None:
    """Що вже зібрано в цьому фонді: файли, рядки, дати."""
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.fonds.registry import registry_dir

    try:
        d = workspace().root / registry_dir(fond_id)
    except WorkspaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    if not d.is_dir():
        console.print(f"[yellow]нічого не зібрано: {d}[/yellow]")
        return
    t = Table(box=None)
    t.add_column("файл")
    t.add_column("рядків", justify="right")
    t.add_column("оновлено")
    import datetime as _dt

    for p in sorted(d.glob("*.tsv")):
        n = max(0, sum(1 for _ in p.open(encoding="utf-8")) - 1)
        when = _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        t.add_row(p.name, str(n), when)
    console.print(t)


@app.command("rate")
def cmd_rate(
    key: str = typer.Option("duck-inspector", "--key", help="ключ черги запитів"),
    max_events: int = typer.Option(5, "--max"),
    window: float = typer.Option(10.0, "--window"),
    last: float = typer.Option(0.0, "--last", help="лише останні N секунд"),
) -> None:
    """Чи витримали темп — за ЖУРНАЛОМ фактичних відправок, а не за наміром."""
    import time

    from nyshporka.core import xrate

    audit = xrate.default_state_dir() / f"{key}.audit.jsonl"
    if not audit.exists():
        console.print(f"[yellow]журналу немає: {audit}[/yellow]")
        console.print("[dim]жодного запиту цим ключем ще не робили[/dim]")
        return
    res = xrate.verify(audit, max_events, window,
                       time.time() - last if last else None)
    console.print(f"  {key}: {res['events']} запитів від {res['pids']} процесів, "
                  f"розтяг {res['span']:.1f} с")
    mark = "[green]✅ ок[/green]" if res["ok"] else "[red]❌ ПЕРЕВИЩЕНО[/red]"
    console.print(f"  максимум у вікні {window:g} с: {res['worst']} "
                  f"(ліміт {max_events}) — {mark}")
    raise typer.Exit(code=0 if res["ok"] else 1)
