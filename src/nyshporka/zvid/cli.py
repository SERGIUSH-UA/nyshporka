"""📜 `nysh zvid …` — Звід: пакет розмітки рядків для іншої машини.

Тонкі обгортки над операціями `ops_zvid` (парність перевіряє
`test_triptych_parity`).
"""
from __future__ import annotations

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

console = brand.console()

app = typer.Typer(help="Звід: віддати зведення рядків на іншу машину і прийняти назад.",
                  no_args_is_help=True)


@app.command("pack")
def pack_cmd(
    sets: str = typer.Option(..., "--sets", metavar="НАБОРИ", help="кома-список наборів"),
    out: str = typer.Option(..., "--out", metavar="ТЕКА", help="куди покласти .zvid"),
    procedure: str = typer.Option("arbiter", "--procedure",
                                  help="arbiter | crop-read (кожен рядок по кропу)"),
    context: str = typer.Option("", "--context", metavar="ФАЙЛ",
                                help="context.md: справа, рука, правопис, причт"),
    control: str = typer.Option("", "--control", metavar="НАБОРИ",
                                help="контрольні (уже звірені) набори — замір CER помічника"),
    pages_per_file: int = typer.Option(1, "--pages-per-file", help="сторінок на завдання"),
    note: str = typer.Option("", "--note", help="примітка до пакета"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Спакувати набори: кропи, сторінки, голоси, людські джерела, контекст."""
    from nyshporka import ops as O

    env = O.call("zvid.pack", {"sets": sets, "out": out, "procedure": procedure,
                               "context": context, "control": control,
                               "pages_per_file": pages_per_file, "note": note})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"📦 {d['file']}  ({d['mb']} МБ, {d['pages']} стор., {d['crops']} рядків)")
    for a, n in d["sets"].items():
        console.print(f"  {a} ← {n}" + ("  [muted](контрольний)[/muted]"
                                         if a in d["control"] else ""))
    console.print(f"[muted]книга пакетів: {d['ledger']}[/muted]")
    _notes(env)


@app.command("take")
def take_cmd(
    file: str = typer.Argument("", metavar="[ПАКЕТ.zvid]"),
    pack_id: str = typer.Option("", "--id", help="з порталу: саме цей пакет"),
    fresh: bool = typer.Option(False, "--fresh", help="розпакувати наново, ЗАТЕРТИ зведене"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Взяти пакет: з файла або, без файла, наступний із черги порталу.

    Розпаковує в пісочницю й робить завдання. Повторний виклик продовжує, а не
    перезаписує.
    """
    from nyshporka import ops as O

    env = O.call("zvid.take", {"file": file, "id": pack_id, "fresh": fresh})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"📜 пакет {d['id']} ({d['procedure']}) — "
                  f"{'продовження' if d['resumed'] else 'розпаковано'}: {d['root']}")
    if d["context"]:
        console.print(f"  контекст справи: {d['context']}")
    for f in d["tasks"]:
        console.print(f"  📄 {f}")
    console.print(f"{d['rows']} рядків у {len(d['tasks'])} завданнях")
    for k, c in d["commands"].items():
        console.print(f"  [muted]{k}:[/muted] {c}")
    _notes(env)


@app.command("status")
def status_cmd(
    pack_id: str = typer.Argument("", metavar="[ID]"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що взято й скільки зведено."""
    from nyshporka import ops as O

    env = O.call("zvid.status", {"id": pack_id})
    if _answer(env, as_json):
        return
    if not env.data["packs"]:
        console.print(f"[muted]взятих пакетів немає — {env.data['base']}[/muted]")
    for p in env.data["packs"]:
        given = f", віддано {p['given']}" if p["given"] else ""
        console.print(f"📜 {p['id']} ({p['procedure']}): зведено {p['done']} з {p['rows']}"
                      f"{given} — {p['root']}")
        for t in p["tasks"]:
            mark = "✅" if t["rows"] and t["done"] == t["rows"] else "…"
            console.print(f"  {mark} {t['task']}: {t['done']}/{t['rows']}")
    _notes(env)


@app.command("give")
def give_cmd(
    pack_id: str = typer.Argument(..., metavar="ID"),
    model: str = typer.Option(..., "--model", help="модель, що зводила"),
    agents: int = typer.Option(0, "--agents", help="скільки агентів працювало паралельно"),
    note: str = typer.Option("", "--note", help="примітка власникові"),
    out: str = typer.Option("", "--out", metavar="ТЕКА", help="куди покласти .answer.zvid"),
    partial: bool = typer.Option(False, "--partial", help="віддати, хоч зведено не все"),
    no_upload: bool = typer.Option(False, "--no-upload",
                                   help="пакет із порталу, але відповідь лише файлом"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перевірити відповіді й зібрати .answer.zvid; пакет із порталу — й залити."""
    from nyshporka import ops as O

    env = O.call("zvid.give", {"id": pack_id, "model": model, "agents": agents,
                               "note": note, "out": out, "partial": partial,
                               "no_upload": no_upload})
    if _answer(env, as_json):
        return
    d = env.data
    c = d["conf"]
    console.print(f"📤 {d['file']}")
    console.print(f"зведено {d['answered']} з {d['rows']} (h{c['high']}/m{c['med']}/l{c['low']})"
                  + (" — залито на портал, власник забере сам" if d["uploaded"]
                     else " — передай файл власникові"))
    _notes(env)


@app.command("collect")
def collect_cmd(
    file: str = typer.Argument(..., metavar="ВІДПОВІДЬ.answer.zvid"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прийняти відповідь: робочі набори — у злиття через ворота, контрольні — замір."""
    from nyshporka import ops as O

    env = O.call("zvid.collect", {"file": file})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"📥 пакет {d['id']}, модель {d['model'] or '—'}")
    for n, v in d["imported"].items():
        c = v["conf"]
        console.print(f"  {n}: {v['rows']} рядків (h{c['high']}/m{c['med']}/l{c['low']}), "
                      f"підозрілих {v['suspects']}")
    for n, v in d["control"].items():
        console.print(f"  🎯 контрольний {n}: CER {v['cer']:.1%} на {v['lines']} з {v['of']} "
                      "рядків еталона")
    _notes(env)


@app.command("publish")
def publish_cmd(
    file: str = typer.Argument(..., metavar="ПАКЕТ.zvid"),
    kind: str = typer.Option("", "--kind", help="клас пакета; типово — за голосами"),
    note: str = typer.Option("", "--note", help="примітка для помічника"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Покласти пакет у чергу порталу (власник)."""
    from nyshporka import ops as O

    env = O.call("zvid.publish", {"file": file, "kind": kind, "note": note})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"📮 {d['id']} [{d['kind']}] — {d['status']}, {d['size'] / 2**20:.1f} МБ")
    _notes(env)


@app.command("queue")
def queue_cmd(
    status: str = typer.Option("", "--status", help="vilnyi | vzhato | povernuto | pryiniato"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Черга порталу: пакети, у кого вони, помічники (власник)."""
    from nyshporka import ops as O

    env = O.call("zvid.queue", {"status": status})
    if _answer(env, as_json):
        return
    for h in env.data.get("helpers") or []:
        console.print(f"{'✓' if h['active'] else '✗'} {h['email']}: {', '.join(h['kinds'])} "
                      f"· до {h['max_open']}")
    for p in env.data.get("packs") or []:
        until = f" до {p['lease_until'][:16]}" if p.get("lease_until") else ""
        console.print(f"  {p['id']} [{p['kind']}] {p['status']}{until} · "
                      f"{(p.get('opys') or {}).get('pages', '?')} стор.")
    _notes(env)


@app.command("fetch")
def fetch_cmd(
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Забрати всі повернуті відповіді з порталу в набори (власник)."""
    from nyshporka import ops as O

    env = O.call("zvid.fetch", {})
    if _answer(env, as_json):
        return
    if not env.data["accepted"]:
        console.print("[muted]повернутих відповідей немає[/muted]")
    for g in env.data["accepted"]:
        rows = sum(g["imported"].values())
        console.print(f"📥 {g['id']} ({g['model'] or '—'}): {rows} рядків у "
                      f"{len(g['imported'])} наборах, підозрілих {g['suspects']}")
        for n, v in g["control"].items():
            console.print(f"   🎯 контрольний {n}: CER {v['cer']:.1%} на {v['lines']} рядках")
    _notes(env)


@app.command("drop")
def drop_cmd(
    pack_id: str = typer.Argument(..., metavar="ID"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Повернути взятий пакет у чергу порталу, не зводячи."""
    from nyshporka import ops as O

    env = O.call("zvid.drop", {"id": pack_id})
    if _answer(env, as_json):
        return
    console.print(f"↩ {env.data['id']} повернуто в чергу")
    _notes(env)
