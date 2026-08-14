"""Командний рядок `nysh`.

Поки скелет: `--version` і `info`. Обидві команди навмисно НЕ порожні —
встановлюваність пакета доводиться тим, що консольний скрипт справді
запускається у чистому середовищі, а не тим, що `import` не впав.
"""
from __future__ import annotations

import platform
import sys

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
