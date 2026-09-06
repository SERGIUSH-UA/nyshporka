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


@app.command("cut")
def cut_cmd(
    run: str = typer.Argument(..., help="прогін (тека в reports/htr)"),
    name: str = typer.Option(..., "--name", metavar="НАБІР", help="ім’я набору"),
    pages: str = typer.Option("", "--pages", help="кома-список сторінок"),
    pick: int = typer.Option(0, "--pick", help="скільки сторінок відібрати автоматично"),
    title: str = typer.Option("", "--title"),
    domain: str = typer.Option("", "--domain", help="жанр: «сповідний розпис», «метрика»"),
    case: str = typer.Option("", "--case", help="шифра справи"),
    no_engine: bool = typer.Option(False, "--no-engine",
                                   help="різати полігоном, не кешем сегментації"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Нарізати кропи рядків із прогону в набір для розмітки.

    Кроп = рядок прогону; текст прогону стає першим голосом задарма.
    Кеш сегментації дає ті самі кропи, що бачив рушій; без нього — полігон.
    """
    from nyshporka import ops as O

    env = O.call("train.cut", {"run": run, "name": name, "pages": pages, "pick": pick,
                               "title": title, "domain": domain, "case": case,
                               "no_engine": no_engine})
    if _answer(env, as_json):
        return
    d = env.data
    for p in d["pages"]:
        mark = "✗" if p["error"] else ("✅" if p["source"] == "seg_cache" else "▫️")
        console.print(f"  {mark} {p['page']}: {p['n']} рядків "
                      f"[muted]{p['source'] or p['error']}[/muted]")
    console.print(f"набір [bold]{d['set']}[/bold]: {d['lines']} кропів у "
                  f"{d['stats']['n_pages']} сторінках")
    _notes(env)


@app.command("voices")
def voices_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    from_run: str = typer.Option("", "--from-run", help="сусідній прогін тієї самої справи"),
    models: str = typer.Option("", "--models", help="кома-список ваг Писаря (.pt)"),
    device: str = typer.Option("cuda:0", "--device"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Додати голос: текст сусіднього прогону або інфер вагами по кропах.

    Голос із прогону береться лише коли рядки збігаються з рамками набору на
    кожній сторінці — інакше арбітр читав би не той рядок.
    """
    from nyshporka import ops as O

    env = O.call("train.voices", {"name": name, "from_run": from_run,
                                  "models": models, "device": device})
    if _answer(env, as_json):
        return
    for g in env.data["added"]:
        console.print(f"  🎙 {g['voice']}: {g['lines']} рядків на {g['pages']} стор. "
                      f"[muted]({g['how']})[/muted]")
    console.print(f"голоси набору: {', '.join(env.data['voices'])}")
    _notes(env)
