"""`nysh opys` — описи фондів: перевірити й спакувати опис для Супряги.

🔴 Монтується в `nysh` лише з увімкненим флагом `NYSH_OPYSY`
(`nyshporka.features`); без нього команди немає взагалі.

🔴 Назви справ і рядки опису — чужий текст: у друк лише через `untrusted`.
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import untrusted

app = typer.Typer(help="Описи фондів (Супряга): перевірити й спакувати опис.",
                  no_args_is_help=True)
console = brand.console()


def _e(value: Any) -> str:
    return untrusted(value)


def _print_verdict(d: dict[str, Any]) -> None:
    s = d.get("summary") or {}
    if s:
        console.print(f"сторінок прочитано [bold]{_e(s.get('pages_read'))}[/bold] з "
                      f"{_e(s.get('pages_total'))} · справ {_e(s.get('rows'))}, "
                      f"нормалізовано {_e(s.get('rows_normalized'))} · "
                      f"№: {_e(s.get('no_status'))}")
    v = d.get("verdict") or {}
    for r in v.get("refusals") or []:
        console.print(f"[red]✗[/red] {_e(r)}")
    for w in v.get("warnings") or []:
        console.print(f"[yellow]•[/yellow] {_e(w.get('text'))}")
    if v.get("passed"):
        console.print("[green]ворота пройдено[/green]")


@app.command("check")
def check_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перевірити робочу теку опису воротами Супряги, нічого не пакуючи."""
    from nyshporka import ops as O

    env = O.call("opysy.check", {"dir": folder})
    if _answer(env, as_json):
        return
    _print_verdict(env.data or {})


@app.command("pack")
def pack_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    out: str = typer.Option(..., "--out", help="файл .nyshopys або тека для нього"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Спакувати опис у `.nyshopys` — лише якщо ворота пропускають."""
    from nyshporka import ops as O

    env = O.call("opysy.pack", {"dir": folder, "out": out})
    if _answer(env, as_json):
        return
    d = env.data or {}
    _print_verdict(d)
    if d.get("file"):
        console.print(f"пакет: {_e(d['file'])} · {_e(d.get('bytes'))} байт · "
                      f"sha256 {_e(str(d.get('sha256'))[:16])}…")


@app.command("policy")
def policy_cmd(
    repo: str = typer.Argument(..., help="архів: ЦДІАК, ДАОО…"),
    fond: str = typer.Argument(..., help="фонд"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чи приймає Супряга описи цього фонду — до прогону."""
    from nyshporka import ops as O

    env = O.call("opysy.policy", {"repo": repo, "fond": fond})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if d.get("open"):
        console.print(f"{_e(d.get('repo'))} ф.{_e(d.get('fond'))}: описи приймаються")
    else:
        console.print(f"[red]{_e(d.get('repo'))} ф.{_e(d.get('fond'))}[/red]: {_e(d.get('why'))}")
