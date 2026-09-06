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
        role = "🎯 holdout" if r["role"] == "holdout" else "трен"
        crops = (f"{r['n_crops']} кропів / {r['n_pages']} стор." if r["crops_present"]
                 else "[err]кропів немає[/err]")
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
    console.print(f"{'✅' if d['engine_present'] else '▫️'} середовище рушіїв: {d['engine_venv']}")
    gpu = d.get("gpu")
    console.print(f"{'✅' if gpu else '▫️'} карта: {(gpu or {}).get('name') or '—'}"
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
    name: str = typer.Option(..., "--name", metavar="НАБІР", help="ім'я набору"),
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


@app.command("glossary")
def glossary_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    add: str = typer.Option("", "--add", help="кома-список власних назв"),
    why: str = typer.Option("", "--why", help="звідки взято"),
    remove: str = typer.Option("", "--remove", help="кома-список назв, які прибрати"),
    show: bool = typer.Option(False, "--show", help="лише показати"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Словник справи для арбітрів: власні назви, звірені оком.

    Словник обмежує, а не підказує: у завдання він іде з правилом «не
    перебиває голоси». Показати людині перед експортом — `--show`.
    """
    from nyshporka import ops as O

    env = O.call("train.glossary", {"name": name, "add": "" if show else add,
                                    "why": why, "remove": "" if show else remove})
    if _answer(env, as_json):
        return
    for term, note in env.data["glossary"].items():
        console.print(f"  • {term}" + (f"  [muted]{note}[/muted]" if note else ""))
    if not env.data["glossary"]:
        console.print("[muted]словник порожній[/muted]")
    _notes(env)


@app.command("export")
def export_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    pages: str = typer.Option("", "--pages", help="кома-список сторінок"),
    pages_per_file: int = typer.Option(3, "--pages-per-file", help="сторінок на файл"),
    only_missing: bool = typer.Option(False, "--only-missing", help="лише рядки без злиття"),
    drafts: str = typer.Option("", "--drafts", help="кома-список голосів"),
    out: str = typer.Option("", "--out", help="куди класти завдання"),
    no_sheets: bool = typer.Option(False, "--no-sheets", help="без аркушів із рамками"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Завдання арбітрам: голоси по сторінках + аркуші з рамками.

    Ріже по МЕЖАХ СТОРІНОК: розірваний між двома арбітрами аркуш дає два
    написання одного прізвища.
    """
    from nyshporka import ops as O

    env = O.call("train.export", {"name": name, "pages": pages,
                                  "pages_per_file": pages_per_file,
                                  "only_missing": only_missing, "drafts": drafts,
                                  "out": out, "no_sheets": no_sheets})
    if _answer(env, as_json):
        return
    d = env.data
    for f in d["files"]:
        console.print(f"  📄 {f}")
    console.print(f"{d['rows']} рядків на {len(d['pages'])} стор. → {len(d['files'])} файлів "
                  f"у {d['out']}")
    _notes(env)


@app.command("import")
def import_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    tasks: str = typer.Option("", "--tasks", help="тека з *.answer.json"),
    keep_old: bool = typer.Option(False, "--keep-old", help="попереднє злиття → merge_old"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Забрати відповіді арбітрів у злиття і прогнати ворота.

    Часткові файли законні. Понижене до low лишається видимим — у корпус не йде.
    """
    from nyshporka import ops as O

    env = O.call("train.import", {"name": name, "tasks": tasks, "keep_old": keep_old})
    if _answer(env, as_json):
        return
    d = env.data
    c = d["conf"]
    console.print(f"імпортовано {d['rows']} рядків із {d['files']} файлів "
                  f"(high {c['high']} · med {c['med']} · low {c['low']}); "
                  f"сторінки: {', '.join(d['pages'])}")
    _notes(env)


@app.command("gates")
def gates_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    suspects: bool = typer.Option(False, "--suspects", help="рядки на очі людині"),
    gt: bool = typer.Option(False, "--gt", help="якір ручних міток"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Ворота окремо: підозрілі рядки злиття, якір ручних міток."""
    from nyshporka import ops as O

    env = O.call("train.gates", {"name": name, "suspects": suspects, "gt": gt})
    if _answer(env, as_json):
        return
    for s in env.data.get("suspects", [])[:60]:
        console.print(f"  ? {s['page']}:{s['idx']}  {s['text']}  [muted]{s['why']}[/muted]")
    for s in env.data.get("gt_shifted", []):
        console.print(f"  🔴 {s['page']}:{s['idx']} якір на {s['shift']:+d} | {s['draft']}")
    _notes(env)


@app.command("sheets")
def sheets_cmd(
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    pages: str = typer.Option("", "--pages", help="кома-список сторінок"),
    out: str = typer.Option("", "--out"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Аркуші сторінок із пронумерованими рамками рядків."""
    from nyshporka import ops as O

    env = O.call("train.sheets", {"name": name, "pages": pages, "out": out})
    if _answer(env, as_json):
        return
    for pg, files in env.data["pages"].items():
        console.print(f"  🗺 {pg}: {', '.join(files)}  "
                      f"[muted]{env.data['notes'].get(pg, '')}[/muted]")
    console.print(f"[muted]тека: {env.data['out']}[/muted]")
    _notes(env)


@app.command("view")
def view_cmd(
    mode: str = typer.Argument("strip", help="strip | zoom | ctx"),
    name: str = typer.Option(..., "--set", metavar="НАБІР"),
    page: str = typer.Option(..., "--page"),
    lines: str = typer.Option("", "--lines", help="strip: «6-10,15»"),
    line: int = typer.Option(0, "--line", help="zoom/ctx: індекс рядка"),
    frm: float = typer.Option(0.0, "--from", help="zoom: початок, частка ширини"),
    to: float = typer.Option(1.0, "--to", help="zoom: кінець, частка ширини"),
    k: float = typer.Option(1.0, "--k", help="кратність збільшення (zoom типово 4)"),
    pad: int = typer.Option(200, "--pad", help="ctx: поле навколо рамки"),
    out: str = typer.Option(..., "--out", help="куди записати PNG"),
) -> None:
    """Картинка кропів для ока: смужка кількох, зум на слово, рядок зі сторінки з полями."""
    from nyshporka import ops as O

    env = O.call("train.view", {"name": name, "page": page, "mode": mode, "lines": lines,
                                "line": line, "frm": frm, "to": to, "k": k, "pad": pad,
                                "out": out})
    if _answer(env, False):
        return
    console.print(f"{env.data['file']} {env.data['width']}×{env.data['height']} — "
                  f"{env.data['note']}")
