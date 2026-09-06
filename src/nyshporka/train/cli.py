"""🧪 `nysh train …` — командний рядок лабораторії.

Кожна команда — тонка обгортка над операцією реєстру (`ops_train`): CLI не
має власної логіки, лише друкує конверт людині. Це та сама угода, що й для
решти `nysh`, і її перевіряє `test_triptych_parity`.
"""
from __future__ import annotations

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

console = brand.console()

app = typer.Typer(help="Лабораторія: розмітка рядків і навчання Писаря.",
                  no_args_is_help=True)


@app.command("sets")
def sets_cmd(
    name: str = typer.Option("", "--set", metavar="НАБІР", help="лише цей набір"),
    show_all: bool = typer.Option(False, "--all", help="і приховані"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Набори: сторінки, кропи на диску, мітки, покриття злиття.

    Числа тут — з диска, а не з самозвіту: саме ця команда каже, чи набір
    узагалі потрапить у корпус.
    """
    from nyshporka import ops as O

    env = O.call("train.sets", {"name": name, "all": show_all})
    if _answer(env, as_json):
        return
    rows = env.data["sets"]
    if not rows:
        console.print(f"[muted]наборів немає — {env.data['root']}[/muted]")
    for r in rows:
        role = "🎯 holdout" if r["role"] == "holdout" else "tren"
        crops = f"{r['n_crops']} кропів / {r['n_pages']} стор." if r["crops_present"] \
            else "[err]кропів немає[/err]"
        st = r["by_status"]
        merged = (f" · злиття {r['n_merged']} "
                  f"(h{r['merge']['high']}/m{r['merge']['med']}/l{r['merge']['low']})"
                  if r["merge"] else "")
        voices = ", ".join(r["voices"]) or "—"
        console.print(f"  [bold]{r['name']}[/bold] [muted]{role}[/muted] {crops} · "
                      f"мітки {r['n_marked']} (ok {st['ok']}, ? {st['unsure']}, "
                      f"skip {st['skip']}){merged} · голоси: {voices}")
        if r["title"]:
            console.print(f"    [muted]{r['title']}[/muted]")
    _notes(env)


@app.command("doctor")
def doctor_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """Що на цій машині є для розмітки й трену.

    Середовище рушіїв, карта, gpurunner на шляху, SSH-хости, набори зі
    знаменниками. Загальну готовність машини каже `nysh doctor`.
    """
    from nyshporka import ops as O

    env = O.call("train.doctor", {})
    if _answer(env, as_json):
        return
    d = env.data
    mark = "✅" if d["engine_present"] else "▫️"
    console.print(f"{mark} середовище рушіїв: {d['engine_venv']}")
    gpu = d.get("gpu")
    console.print(f"{'✅' if gpu else '▫️'} карта: "
                  f"{(gpu or {}).get('name') or '—'}"
                  + (f" · compute {gpu['capability']}" if gpu and gpu.get("capability") else ""))
    console.print(f"{'✅' if d['gpurunner'] else '▫️'} gpurunner: {d['gpurunner'] or '—'}")
    hosts = d["ssh_hosts"]
    console.print(f"{'✅' if hosts else '▫️'} SSH-хости: {', '.join(hosts) or '—'}")
    s = d["sets"]
    console.print(f"🗃 наборів {s['n']} · міток {s['marked']} (ok {s['ok']}) · "
                  f"кропів {s['crops']} · holdout: {', '.join(s['holdout']) or '—'}")
    if s["without_crops"]:
        console.print(f"  [err]мітки без кропів: {', '.join(s['without_crops'])}[/err]")
    console.print(f"[muted]тека: {d['root']}[/muted]")
    _notes(env)
