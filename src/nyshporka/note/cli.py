"""`nysh note` — нотатник справи: звірене оком, опис, помилки опису, копії.

Записи лежать у тому самому файлі сховища сторінок, що й переглянуті аркуші
(`data/pages/<архів>/<справа>.json`, секція `notes`). Загальне знання про
справу їде в пул окремо від тексту (`note push`), особисте не їде ніколи.
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Нотатник справи: звірене оком, опис справи, помилки опису, копії.",
                  no_args_is_help=True)
console = brand.console()

_KIND_MARK = {"about": "📄", "catalog-error": "⚠", "copy": "🔁", "reading": "👁", "note": "🔒"}


def _line(n: dict[str, Any]) -> str:
    """Один запис одним рядком: позначка, uid, що саме, хто й коли."""
    kind = n["kind"]
    head = f"{_KIND_MARK.get(kind, '·')} [bold]{n['uid'][:8]}[/bold] {kind}"
    if n.get("share"):
        head += " [ok]→ пул[/ok]"
    if n.get("origin"):
        o = n["origin"]
        head += f" [muted](з пулу: {o.get('by') or '?'}, {o.get('alignment')})[/muted]"
    if kind == "reading":
        ln = n.get("line") or {}
        body = f"{n.get('page')} р.{ln.get('line_no', '?')}: {n.get('text', '')}"
        if (n.get("was") or {}).get("text"):
            body += f"  [muted](рушій: {n['was']['text']})[/muted]"
    elif kind == "catalog-error":
        body = (f"{n.get('field')}: в описі «{n.get('archive_says', '')}» → "
                f"насправді «{n.get('actually', '')}» {n.get('text', '')}").rstrip()
    elif kind == "copy":
        body = f"{n.get('relation') or 'copy'}: {n.get('other')} {n.get('text', '')}".rstrip()
    else:
        body = n.get("text", "")
    who = n.get("author") or n.get("reader") or ""
    when = str(n.get("created", ""))[:10]
    return f"{head}  {body}  [muted]{who} {when}[/muted]"


def _done(env: Any, as_json: bool) -> None:
    if _answer(env, as_json):
        return
    d = env.data
    for n in d.get("notes") or []:
        console.print(f"✅ {_line(n)}")
    if d.get("merged"):
        console.print(f"[muted]уже були: {len(d['merged'])}[/muted]")
    _notes(env)


@app.command("add")
def add_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    kind: str = typer.Option(..., "--kind",
                             help="about — опис справи; catalog-error — помилка опису "
                                  "архіву; copy — копія деінде; note — особисте"),
    text: str = typer.Option("", "--text", help="текст запису"),
    field: str = typer.Option("", "--field", help="catalog-error: title|years|shifra|extent|other"),
    archive_says: str = typer.Option("", "--archive-says", help="catalog-error: як в описі"),
    actually: str = typer.Option("", "--actually", help="catalog-error: як насправді"),
    other: str = typer.Option("", "--other", help="copy: шифра іншої справи"),
    relation: str = typer.Option("", "--relation",
                                 help="copy: copy|draft|duplicate|continuation|original|other"),
    page: str = typer.Option("", "--page", help="сторінка, якщо запис про неї"),
    share: bool = typer.Option(False, "--share", help="позначити до віддачі в пул"),
    reader: str = typer.Option("agent", "--reader", help="agent | human | agent+human"),
    model: str = typer.Option("", "--model", help="модель агента"),
    author: str = typer.Option("", "--author", help="хто записав (у пул не їде)"),
    supersedes: str = typer.Option("", "--supersedes", help="uid запису, який цей замінює"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Дописати запис про справу.

    🔴 Особисте — «тут жив мій дід» — лише `--kind note`: воно не їде в пул навіть
    із `--share`. У пул — те, що корисне кожному, хто відкриє цю справу.
    """
    from nyshporka import ops as O

    _done(O.call("note.add", {
        "case": case, "kind": kind, "text": text, "field": field,
        "archive_says": archive_says, "actually": actually, "other": other,
        "relation": relation, "page": page, "share": share, "reader": reader,
        "model": model, "author": author, "supersedes": supersedes}), as_json)


@app.command("read")
def read_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    page: str = typer.Argument(..., help="сторінка прогону: 0031, p0531"),
    line: int = typer.Option(..., "--line", help="номер рядка з 1, як у `text ctx`"),
    text: str = typer.Option(..., "--text", help="звірене читання рядка, дослівно"),
    run: str = typer.Option("", "--run", help="прогін; порожньо — перший прогін справи"),
    confidence: str = typer.Option("", "--confidence", help="high | medium | low"),
    uncertain: str = typer.Option("", "--uncertain", help="кома-список непевних слів"),
    share: bool = typer.Option(False, "--share", help="позначити до віддачі в пул"),
    reader: str = typer.Option("agent", "--reader", help="agent | human | agent+human"),
    model: str = typer.Option("", "--model", help="модель агента"),
    author: str = typer.Option("", "--author", help="хто записав (у пул не їде)"),
    supersedes: str = typer.Option("", "--supersedes", help="uid запису, який цей замінює"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Записати звірене оком читання рядка: прогін, рамка й читання рушія — самі.

    Кроп для звірки — `nysh text crop <справа> <сторінка> <рядок>`.
    """
    from nyshporka import ops as O

    _done(O.call("note.read", {
        "case": case, "page": page, "line": line, "text": text, "run": run,
        "confidence": confidence, "uncertain": uncertain, "share": share,
        "reader": reader, "model": model, "author": author,
        "supersedes": supersedes}), as_json)


@app.command("list")
def list_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    kind: str = typer.Option("", "--kind", help="лише цей тип"),
    shared: bool = typer.Option(False, "--shared", help="лише позначене до віддачі"),
    pool: str = typer.Option("all", "--from", help="all | own | pool"),
    history: bool = typer.Option(False, "--history", help="з заміненими й відкликаними"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що в нотатнику справи: чинні записи, хто й коли, що позначено до пулу."""
    from nyshporka import ops as O

    env = O.call("note.list", {"case": case, "kind": kind, "shared": shared,
                               "pool": pool, "history": history})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['shifra'] or d['case']}[/bold] · записів {d['shown']} "
                  f"(у журналі {d['total']}) · переглянутих аркушів {d['pages_noted']}")
    for n in d["notes"]:
        console.print(f"  {_line(n)}")
    _notes(env)


@app.command("share")
def share_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    uids: list[str] = typer.Argument(..., help="uid записів (досить 8 знаків)"),
    back: bool = typer.Option(False, "--home", help="повернути додому, а не позначити"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Позначити записи до віддачі в пул (або `--home` — повернути додому)."""
    from nyshporka import ops as O

    _done(O.call("note.share", {"case": case, "uids": uids, "share": not back}), as_json)


@app.command("retract")
def retract_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    uids: list[str] = typer.Argument(..., help="uid записів (досить 8 знаків)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Відкликати записи; віддане пул прибере після `note push`."""
    from nyshporka import ops as O

    _done(O.call("note.retract", {"case": case, "uids": uids}), as_json)


@app.command("push")
def push_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    pages: bool = typer.Option(True, "--pages/--no-pages",
                               help="віддати й зведення переглянутих аркушів"),
    dry_run: bool = typer.Option(False, "--dry-run", help="показати, що поїде"),
    base: str = typer.Option("", "--base", help="інша домівка пулу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Віддати загальне знання про справу в нотатник книги в Супрязі.

    Їдуть записи, позначені `--share` / `note share`, і переглянуті аркуші без
    коментарів. Особисте, автор запису й ім'я сесії не їдуть ніколи.
    """
    from nyshporka import ops as O

    env = O.call("note.push", {"case": case, "pages": pages, "dry_run": dry_run,
                               "base": base})
    if _answer(env, as_json):
        return
    d = env.data
    verb = "поїде" if d["dry_run"] else "віддано"
    console.print(f"{d['shifra'] or d['case']}: {verb} записів {d['entries']}, "
                  f"аркушів {d['pages']}; ворота не пустили {len(d['refused'])}")
    if d["dry_run"]:
        for w in d["body"]["entries"]:
            label = (w.get("retracts") and f"відкликання {w['retracts'][:8]}") \
                or f"{w['uid'][:8]} {w['kind']}"
            console.print(f"  → {label}")
    pool = d.get("pool") or {}
    if pool.get("book"):
        console.print(f"[muted]книга в пулі: {pool['book']}[/muted]")
    _notes(env)


@app.command("pull")
def pull_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    base: str = typer.Option("", "--base", help="інша домівка пулу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Забрати чужі записи нотатника справи з Супряги (лише для читання)."""
    from nyshporka import ops as O

    env = O.call("note.pull", {"case": case, "base": base})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"{d['shifra'] or d['case']}: у пулі записів {d['received']}, "
                  f"нових {len(d['added'])}")
    _notes(env)


@app.command("import-eye")
def import_eye_cmd(
    folder: str = typer.Argument(..., help="тека `<прогін>-claude_eye`"),
    case: str = typer.Option("", "--case", help="справа; порожньо — з мети прогону"),
    reader: str = typer.Option("agent", "--reader", help="agent | human | agent+human"),
    model: str = typer.Option("", "--model", help="модель, яка звіряла"),
    base_run: str = typer.Option("", "--base-run", help="базовий прогін"),
    dry_run: bool = typer.Option(False, "--dry-run", help="показати й нічого не писати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перенести вільну теку звірки оком у нотатник: усе лягає домашнім."""
    from nyshporka import ops as O

    env = O.call("note.import_eye", {"folder": folder, "case": case, "reader": reader,
                                     "model": model, "base_run": base_run,
                                     "dry_run": dry_run})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"{d['shifra'] or d['case']}: файлів {d['files']}, читань рядка "
                  f"{d['readings']}, особистих приміток {d['private']}"
                  + ("" if d["dry_run"] else f"; нових {d.get('added', 0)}"))
    for name, rows in (d.get("skipped") or {}).items():
        console.print(f"  [warn]{name}: не розпізнано {len(rows)} рядків[/warn]")
    _notes(env)
