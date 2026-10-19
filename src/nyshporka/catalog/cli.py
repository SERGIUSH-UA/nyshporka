"""🗂 `nysh catalog` — довідники, які їдуть у комплекті.

Каталог оновлюється не разом із кодом: архів виклав новий опис — оновлюється
каталог; полагодили ваду — оновлюється код. Тому окрема команда, а не крок
установлення.
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import typer

from nyshporka.catalog import store

app = typer.Typer(help="Довідники: газетир, реєстри описів фондів.",
                  no_args_is_help=True)


def _fmt_size(n: int) -> str:
    return f"{n / 1e6:.1f} МБ" if n else "?"


@app.command("where")
def cmd_where() -> None:
    """Надрукувати теку каталогу (для підтримки й для перенесення)."""
    typer.echo(str(store.catalog_dir()))
    own = store.own_path()
    if own is not None:
        state = "є" if own.is_file() else "немає"
        typer.echo(f"власні дані: {own} ({state})")


@app.command("origin")
def cmd_origin() -> None:
    """Надрукувати, з якого пака стоять каталоги (порожньо — невідомо)."""
    typer.echo(store.origin())


@app.command("list")
def cmd_list(as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Що встановлено, якого зрізу й чи ціле."""
    packs = store.installed()
    if as_json:
        typer.echo(_json.dumps(
            [{"pack_id": p.pack_id, "domain": p.domain, "taken": p.taken,
              "rows": p.rows, "size": p.size, "state": "ok" if p.ok else "broken",
              "problem": p.problem, "path": str(p.path),
              # 🔴 Межі пака — частина відповіді «що встановлено»: без них нуль
              # газетира чи бази церков поза їхнім регіоном читається звичайним.
              "note": p.note, "scope": store.scope_of(p) if p.ok else []}
             for p in packs],
            ensure_ascii=False, indent=1))
        return
    if not packs:
        typer.echo(f"каталог порожній: {store.catalog_dir()}")
        # 🔴 Порада мусить казати, звідки взяти, а не лише «поставте».
        # «--from <тека|zip>» без адреси — половина поради: людина знає команду
        # й не знає, що в неї підставити, а довідники на місці не збираються.
        typer.echo(f"довідники беруть тут: {store.RELEASES_URL}")
        typer.echo("далі: nysh catalog install --from <завантажений zip>")
        return
    for p in packs:
        mark = "✅" if p.ok else "🔴"
        taken = f"зріз {p.taken}" if p.taken else "зріз невідомий"
        typer.echo(f"{mark} {p.pack_id:<28} {p.domain:<6} {taken:<20} "
                   f"{p.rows:>8} рядків  {_fmt_size(p.size)}")
        if p.note:
            typer.echo(f"     {p.note}")
        if p.problem:
            typer.echo(f"     🔴 {p.problem}")


@app.command("verify")
def cmd_verify() -> None:
    """Перечитати всі паки — приймач проти тихого псування.

    Обірваний файл виглядає як пак: він на місці, має ім'я, відкривається. Вада
    проявиться аж у відповіді — неповним переліком, який ніхто не відрізнить від
    повного. Тому перевірка окремою командою, а не «якось саме помітиться».
    """
    packs = store.installed()
    if not packs:
        typer.echo("каталог порожній — перевіряти нічого")
        raise typer.Exit(code=1)
    bad = 0
    for p in packs:
        problem = p.problem
        if not problem:
            import sqlite3
            try:
                con = sqlite3.connect(f"file:{p.path}?mode=ro", uri=True)
                res = con.execute("PRAGMA quick_check").fetchone()
                con.close()
                if res and str(res[0]).lower() != "ok":
                    problem = f"quick_check: {res[0]}"
            except sqlite3.Error as exc:
                problem = f"не читається: {exc}"
        if problem:
            bad += 1
            typer.echo(f"🔴 {p.pack_id}: {problem}")
        else:
            typer.echo(f"✅ {p.pack_id}")
    if bad:
        typer.echo(f"\nзіпсованих паків: {bad} — перевстановити: nysh catalog install")
        raise typer.Exit(code=1)


@app.command("install")
def cmd_install(
    src: Path = typer.Option(None, "--from", exists=True,
                             help="тека, .zip або .sqlite-пак (офлайн); без нього — свіжий реліз"),
    domain: str = typer.Option("", "--domain", help="лише цього домену"),
    origin: str = typer.Option("", "--origin",
                               help="ім'я пака (zip-зрізу); той самий уже стоїть — пропустити"),
) -> None:
    """Покласти паки в каталог: з теки чи файла (`--from`) або з релізу `catalog-*`.

    Без `--from` качає найновіший архів каталогу й ставить лише після звірки
    sha256 і розміру з тими, що назвав GitHub (`catalog.remote`).
    """
    from nyshporka.catalog import remote

    if src is None:
        if domain:
            typer.echo("--domain діє лише з --from: реліз ставиться цілим архівом")
            raise typer.Exit(code=2)
        _update(apply=True, force=True)
        return
    if origin and not domain and store.origin() == origin.strip():
        typer.echo(f"✓ каталоги вже з цього пака ({origin}) — не перезаписую")
        return
    done = remote.install_from(src, domain=domain, origin=origin)
    if not done:
        typer.echo(f"у {src} немає жодного .sqlite" + (f" домену {domain}" if domain else ""))
        raise typer.Exit(code=1)
    for f in done:
        typer.echo(f"✅ {f.name} → {f}")
    typer.echo(f"поставлено паків: {len(done)}")


def _update(*, apply: bool, force: bool = False) -> str:
    """Свіжий каталог із релізу. → стан (`current`, `installed`, …).

    `force` — поставити, навіть якщо позначка каже, що цей зріз уже стоїть.
    """
    from nyshporka.catalog import remote

    rel = remote.latest()
    if not rel.known:
        typer.echo(f"каталог довідників: не перевірено — {rel.why}")
        return "unknown"
    if force:
        store.set_origin("")
    try:
        res = remote.update(apply=apply, rel=rel)
    except remote.CatalogFetchError as exc:
        typer.echo(f"🔴 каталог довідників: {exc}")
        raise typer.Exit(code=1) from None
    if res.state == "current":
        typer.echo(f"✓ каталог довідників свіжий ({rel.tag})")
    elif res.state == "would-install":
        typer.echo(f"каталог довідників: є новіший {rel.tag} ({rel.size / 1e6:.1f} МБ) — "
                   f"поставить `nysh catalog update`")
    else:
        typer.echo(f"✅ каталог довідників {rel.tag}: поставлено паків {len(res.installed)}")
    return res.state


@app.command("update")
def cmd_update(
    check: bool = typer.Option(False, "--check", help="лише подивитись, не ставити"),
) -> None:
    """Поставити найновіший каталог довідників із релізу, якщо стоїть не він.

    Той самий крок робить `nysh update` (вимкнути — `--no-catalog` чи
    `NYSH_NO_CATALOG=1`).
    """
    _update(apply=not check)


@app.command("remove")
def cmd_remove(pack_id: str = typer.Argument(..., help="id пака зі `list`")) -> None:
    """Зняти пак із каталогу."""
    for p in store.installed():
        if p.pack_id == pack_id:
            p.path.unlink(missing_ok=True)
            store.invalidate()
            typer.echo(f"знято: {pack_id}")
            return
    typer.echo(f"пака «{pack_id}» немає — подивитись: nysh catalog list")
    raise typer.Exit(code=1)
