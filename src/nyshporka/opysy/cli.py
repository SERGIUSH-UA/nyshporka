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


@app.command("push")
def push_cmd(
    file: str = typer.Argument(..., help="пакет .nyshopys"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Залити спакований опис у Супрягу: ворота тут, потім — на сервері наново."""
    from nyshporka import ops as O

    env = O.call("opysy.push", {"file": file, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    s = d.get("summary") or {}
    if d.get("duplicate"):
        console.print(f"{_e(d.get('shyfra'))}: той самий пакет уже в Супрязі "
                      f"(внесок {_e(d.get('vnesok'))})")
        return
    console.print(f"[green]прийнято[/green] {_e(d.get('shyfra'))} · внесок {_e(d.get('vnesok'))} · "
                  f"сторінок {_e(s.get('pages_read'))}/{_e(s.get('pages_total'))} · "
                  f"справ {_e(s.get('rows'))}")
    for w in d.get("warnings") or []:
        console.print(f"[yellow]•[/yellow] {_e(w.get('text'))}")


@app.command("search")
def search_cmd(
    q: list[str] = typer.Argument(..., help="що шукати"),
    repo: str = typer.Option("", "--repo", help="лише в цьому архіві"),
    fond: str = typer.Option("", "--fond", help="лише в цьому фонді"),
    limit: int = typer.Option(50, "--limit", help="скільки збігів показати"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Нечіткий пошук по описах фондів у Супрязі: справа, сторінка, посилання на скан."""
    from nyshporka import ops as O

    env = O.call("opysy.search", {"q": " ".join(q), "repo": repo, "fond": fond,
                                  "limit": limit, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    zbihy = d.get("zbihy")
    if zbihy is None:
        console.print(f"збігів {_e(d.get('zbihiv'))}: "
                      + ", ".join(f"{_e(k)} — {_e(v)}" for k, v in (d.get("za_opysamy") or {}).items()))
        console.print(_e(d.get("uviity") or ""))
        return
    if not zbihy:
        bez = d.get("bez_zbihu") or []
        if bez:
            console.print(f"у описах Супряги не знайшлось (немає ніде: {_e(', '.join(bez))})")
        elif len(" ".join(q).split()) > 1:
            # Кожне слово десь є, але не разом: голе «не знайшлось» тут збрехало б, що
            # слів немає, і людина закрила б напрям (перевірка на проді 22.11.2026).
            console.print("у описах Супряги кожне слово трапляється, але не разом на одній "
                          "сторінці чи в одній справі — спробуйте слова окремо")
        else:
            console.print("у описах Супряги не знайшлось")
        return
    for z in zbihy:
        mistse = f"кадр {_e(z.get('page'))}" + (
            "" if z.get("half") is None else (", ліва" if z.get("half") == 0 else ", права"))
        if z.get("riadok"):
            no = f"№ {_e(z.get('no'))}{_e(z.get('letter'))}" if z.get("no") is not None else "№ ?"
            zvir = " (звірити №)" if z.get("no_status") == "unconfirmed" else ""
            nazva = z.get("title_norm") or z.get("title_raw")
            console.print(f"[bold]{_e(z.get('shyfra'))}[/bold] {no}{zvir} — {_e(nazva)}")
        else:
            console.print(f"[bold]{_e(z.get('shyfra'))}[/bold] — збіг у тексті сторінки")
        console.print(f"   {mistse} · {_e(z.get('posylannia'))}")
