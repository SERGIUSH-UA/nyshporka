"""💽 `nysh disk`: місце простору, чистка відтворюваного, зняття прочитаних кадрів."""
from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape as _e

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Місце на диску: що лишити, що прибрати, з яких справ зняти кадри.",
                  invoke_without_command=True)
console = brand.console()


def _gb(n: Any) -> str:
    if n is None:
        return "—"
    n = int(n)
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} ГБ"
    return f"{n / 1024 ** 2:.0f} МБ"


@app.callback()
def report_cmd(
    ctx: typer.Context,
    full: bool = typer.Option(False, "--full",
                              help="рахувати й розмір прочитаного (reports/htr) — довго"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що в просторі лишити, що відтворюване, з яких справ можна зняти кадри."""
    if ctx.invoked_subcommand is not None:
        return
    from nyshporka import ops as O

    env = O.call("disk.report", {"full": full})
    if _answer(env, as_json):
        return
    d = env.data or {}
    for klas, head in (("keep", "[bold]Лишити[/bold] — звідси відтворюється решта"),
                       ("rebuild", "[bold]Відтворюване[/bold] — можна прибрати "
                                   "(nysh disk clean)")):
        console.print(head)
        for it in d.get("items") or []:
            if it["class"] != klas:
                continue
            rozmir = "немає" if not it["exists"] else _gb(it["bytes"])
            console.print(f"  {rozmir:>9}  {_e(it['label'])} [muted]· {_e(it['why'])}[/muted]")
            console.print(f"             [muted]{_e(it['path'])}[/muted]")
    console.print(f"разом відтворюваного: [bold]{_gb(d.get('rebuildable_bytes'))}[/bold]")
    kand = d.get("offload_candidates") or []
    if kand:
        console.print(f"\n[bold]Де можна зняти кадри[/bold] — ваш текст є в Супрязі; "
                      f"знімається лише прочитане ({len(kand)}"
                      f"{'+' if len(kand) >= 20 else ''}):")
        for k in kand:
            console.print(f"  {_e(k['shifra'] or k['case_key'])} [muted]· {k['frames']} "
                          f"кадрів · {_e(k['dir'])}[/muted]")
        console.print("  [muted]nysh disk offload <тека справи> --restore «де копія» "
                      "--apply[/muted]")
    _notes(env)


@app.command("clean")
def clean_cmd(
    apply: bool = typer.Option(False, "--apply", help="справді видалити"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прибрати відтворюване. Без --apply — лише перелік того, що піде."""
    from nyshporka import ops as O

    env = O.call("disk.clean", {"apply": apply})
    if _answer(env, as_json):
        return
    d = env.data or {}
    for it in d.get("remove") or []:
        console.print(f"  {_gb(it['bytes']):>9}  {_e(it['path'])}")
    dia = "звільнено" if apply else "звільнить"
    console.print(f"{dia}: [bold]{_gb(d.get('bytes'))}[/bold]"
                  + ("" if apply else " · справді видалити: nysh disk clean --apply"))
    _notes(env)


@app.command("offload")
def offload_cmd(
    case: str = typer.Argument(..., help="тека справи (або шифра, якщо тека в неї одна)"),
    restore: str = typer.Option(..., "--restore", help="де лежить копія кадрів"),
    apply: bool = typer.Option(False, "--apply", help="справді зняти"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зняти прочитані кадри справи: лише ті, що прочитав власний прогін цієї теки."""
    from nyshporka import ops as O

    env = O.call("disk.offload", {"case": case, "restore": restore, "apply": apply})
    if _answer(env, as_json):
        return
    d = env.data or {}
    dia = "знято" if apply else "зніме"
    console.print(f"{_e(str(d.get('case_key') or ''))}: {dia} {d.get('frames')} прочитаних "
                  f"кадрів, {_gb(d.get('bytes'))} · копія: {_e(str(d.get('restore') or ''))}")
    if not apply:
        console.print("[muted]справді зняти: та сама команда з --apply[/muted]")
    _notes(env)
