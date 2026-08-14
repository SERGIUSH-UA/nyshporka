"""Командний рядок `nysh`.

Поки скелет: `--version` і `info`. Обидві команди навмисно НЕ порожні —
встановлюваність пакета доводиться тим, що консольний скрипт справді
запускається у чистому середовищі, а не тим, що `import` не впав.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from nyshporka import __version__

app = typer.Typer(
    name="nysh",
    help="Нишпорка — читання рукописних архівних справ і пошук прізвища в них.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """Версія пакета."""
    console.print(__version__)


@app.command()
def info() -> None:
    """Стан установки: що вже є, чого ще немає."""
    console.print(f"[bold]Нишпорка[/bold] {__version__}")
    console.print(f"  python  {platform.python_version()} ({sys.platform})")

    # Важкі extras перевіряються НАЯВНІСТЮ, а не імпортом у момент старту:
    # тягнути torch заради рядка «встановлено» коштувало б секунд на кожен запуск.
    from importlib.util import find_spec

    for label, module, extra in (
        ("консоль", "fastapi", "app"),
        ("архіви", "aiolimiter", "archives"),
        ("GEDCOM", "ged4py", "gedcom"),
        ("HTR", "torch", "htr"),
    ):
        have = find_spec(module) is not None
        # 🔴 `\[` — екранування для rich. Без нього `[app]` з'їдається як
        # розмітка, і порада перетворюється на «pip install nyshporka», тобто
        # рівно ту команду, яка extra НЕ ставить. Порада, що не працює, гірша
        # за відсутню: користувач виконує її і бачить той самий стан.
        mark = ("[green]є[/green]" if have
                else rf"[dim]немає — pip install 'nyshporka\[{extra}]'[/dim]")
        console.print(f"  {label:8s} {mark}")


@app.command()
def sources() -> None:
    """Звідки можна брати матеріал — і що кожне джерело вміє."""
    from nyshporka.sources import load

    reg = load()
    for src in reg.all():
        caps = ", ".join(sorted(src.caps)) or "—"
        console.print(f"  [bold]{src.id:<10}[/bold] {src.label}")
        console.print(f"  {'':<10} [dim]уміє: {caps}[/dim]")
    # 🔴 Зламані плагіни називаються поіменно: «мого архіву немає в списку»
    # інакше не має пояснення, і людина шукатиме причину в своїх налаштуваннях.
    for name, why in reg.broken:
        console.print(f"  [red]✗ {name}[/red] [dim]{why}[/dim]")


@app.command()
def look(path: str = typer.Argument(..., help="тека зі сканами, PDF або тека з PDF")) -> None:
    """Що це за матеріал: скільки кадрів, чи це одна справа, чи багато."""
    from nyshporka.sources.local import LocalSource, inspect

    shape = inspect(path)
    mark = "[green]✓[/green]" if shape.usable else "[yellow]![/yellow]"
    console.print(f"{mark} {shape.explain()}")
    if shape.kind == "cases":
        for node in shape.cases:
            console.print(f"    [dim]{node.frames:>6} кадрів[/dim]  {node.label}")
        console.print("\n[dim]Оберіть одну зі справ вище або поставте всі в чергу.[/dim]")
        raise typer.Exit(code=1)
    if not shape.usable:
        raise typer.Exit(code=1)
    m = LocalSource().manifest(str(shape.path))
    if m.bytes_estimate:
        console.print(f"  [dim]обсяг: {m.bytes_estimate / 1024 / 1024:.0f} МБ[/dim]")


@app.command("ops")
def ops_list(agent_only: bool = typer.Option(False, "--agent",
                                             help="лише те, що бачить агент")) -> None:
    """Перелік операцій — те саме, що доступне агентові й браузеру."""
    from nyshporka import ops as O

    for op in (O.for_agent() if agent_only else O.all_ops()):
        marks = "".join(("✎" if op.mutates else " ", "⏳" if op.long else " ",
                         "🤖" if op.agent else " "))
        console.print(f"  {marks} [bold]{op.name:<18}[/bold] {op.summary}")


@app.command("op")
def op_run(
    name: str = typer.Argument(..., help="ім'я операції, напр. workspace.info"),
    args: str = typer.Option("{}", "--args", help="аргументи як JSON"),
    as_json: bool = typer.Option(True, "--json/--human", help="формат виводу"),
) -> None:
    """Виконати операцію напряму.

    🔴 Це і є те, що робить командний рядок повним: КОЖНА операція доступна тут
    без окремої команди. Дружні команди (`look`, `sources`) — лише зручні
    обгортки над тими самими операціями, тож відстати від агента CLI не може.
    """
    import json as _json

    from nyshporka import ops as O

    try:
        payload = _json.loads(args)
    except ValueError as exc:
        console.print(f"[red]--args не є JSON:[/red] {exc}")
        raise typer.Exit(code=2) from None

    env = O.call(name, payload)
    if as_json:
        console.print_json(data=env.as_dict())
    else:
        note = env.as_agent_text()
        if note:
            console.print(note)
        console.print_json(data=env.data)
    raise typer.Exit(code=0 if env.ok else 1)


mcp_app = typer.Typer(help="Агентна поверхня (Claude Code, Codex).",
                      no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Підняти MCP-сервер по stdio (так його запускає агент)."""
    from nyshporka.mcp import serve

    raise typer.Exit(code=serve())


@mcp_app.command("tools")
def mcp_tools() -> None:
    """Що саме бачить агент."""
    from nyshporka.mcp import tool_definitions

    defs = tool_definitions()
    for d in defs:
        console.print(f"  [bold]{d['name']:<22}[/bold] {d['description']}")
    console.print(f"\n[dim]усього {len(defs)}[/dim]")


@mcp_app.command("install")
def mcp_install(
    target: str = typer.Option(".mcp.json", help="куди дописати конфіг"),
    show: bool = typer.Option(False, "--show", help="лише показати, не писати"),
) -> None:
    """Прописати сервер у `.mcp.json` проєкту."""
    import json as _json

    from nyshporka.mcp import mcp_config

    cfg = mcp_config()
    if show:
        console.print_json(data=cfg)
        return
    path = Path(target)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = _json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            console.print(f"[yellow]![/yellow] {path} не є JSON — не чіпаю його")
            raise typer.Exit(code=1) from None
    # Дописуємо, а не заміщаємо: у файлі можуть бути чужі сервери, і затерти їх
    # означало б зламати налаштування, які людина робила руками.
    servers = dict(existing.get("mcpServers") or {})
    servers.update(cfg["mcpServers"])
    existing["mcpServers"] = servers
    path.write_text(_json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    console.print(f"✓ {path}: додано сервер «nyshporka»")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
