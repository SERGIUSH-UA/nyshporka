"""📋 `nysh form`: бланки поклітинно — замір проти звіреного оком."""
from __future__ import annotations

import typer
from rich.markup import escape as _e

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer

app = typer.Typer(help="Бланки: замір читання поклітинно.", no_args_is_help=True)
console = brand.console()


@app.command("bench")
def bench_cmd(
    case: str = typer.Argument(..., help="справа: ключ, шифра або тека кадрів"),
    truth: str = typer.Option("", "--truth", help="файл {сторінка: [слова]}; порожньо — "
                                                 "нотатник справи"),
    voice: list[str] = typer.Option([], "--voice", help="ще тека голосу (проба)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Частка звірених оком слів, видних у кожному голосі справи й у всіх разом."""
    from nyshporka import ops as O

    env = O.call("form.bench", {"case": case, "truth": truth, "voices": voice})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"слів-істин {d['words']} на {d['pages']} сторінках · істина: {_e(d['truth'])}")
    for v in d["voices"]:
        console.print(f"  {v['pct']:5.1f} %  {_e(v['name'])}  [muted](сторінок {v['pages']})[/muted]")
    console.print(f"  [bold]{d['together']['pct']:5.1f} %  разом[/bold]")


@app.command("extract")
def extract_cmd(
    case: str = typer.Argument(..., help="справа: ключ, шифра або тека кадрів"),
    template: str = typer.Option("", "--template", help="ім'я шаблону; порожньо — за написом"),
    run: str = typer.Option("", "--run", help="тека голосу клітинок; порожньо — `-cells` справи"),
    apply: bool = typer.Option(False, "--apply", help="записати в сховище сторінок"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Бланк → записи з ролями: клітинки голосу `-cells` за шаблоном (машинне, не звірене)."""
    from nyshporka import ops as O

    env = O.call("form.extract", {"case": case, "template": template, "run": run,
                                  "apply": apply})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"{_e(d['run'])}: сторінок {d['pages']}, бланків {d['matched']}, "
                  f"записів {d['records']}" + (" — записано" if d["applied"] else ""))
    for k, n in d["filled"].items():
        console.print(f"  [muted]{n:5d}  {_e(k)}[/muted]")
