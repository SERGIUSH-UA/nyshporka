"""🗂 `nysh catalog` — довідники, які їдуть у комплекті.

Каталог оновлюється НЕ разом із кодом: архів виклав новий опис — оновлюється
каталог; полагодили ваду — оновлюється код. Тому окрема команда, а не крок
установлення.
"""
from __future__ import annotations

import json as _json
import shutil
import tempfile
import zipfile
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


@app.command("list")
def cmd_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """Що встановлено, якого зрізу й чи ціле."""
    packs = store.installed()
    if as_json:
        typer.echo(_json.dumps(
            [{"pack_id": p.pack_id, "domain": p.domain, "taken": p.taken,
              "rows": p.rows, "size": p.size, "state": "ok" if p.ok else "broken",
              "problem": p.problem, "path": str(p.path)} for p in packs],
            ensure_ascii=False, indent=1))
        return
    if not packs:
        typer.echo(f"каталог порожній: {store.catalog_dir()}")
        typer.echo("поставити: nysh catalog install --from <тека|zip>")
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
                             help="тека, .zip або .sqlite-пак (офлайн)"),
    domain: str = typer.Option("", "--domain", help="лише цього домену"),
) -> None:
    """Покласти паки в каталог із теки чи файла.

    ⚠ Завантаження з релізу тут поки немає навмисно: маніфест іще не має
    контрольних сум зібраного релізу, а качати без звірки не можна — обірваний
    файл виглядав би як пак. Офлайн-шлях (`--from`) працює вже зараз, і саме ним
    інсталятор кладе довідники в комплекті.
    """
    if src is None:
        typer.echo("вкажіть --from <тека|файл>: завантаження з релізу ще не "
                   "складено, а брати пак без звірки не можна")
        raise typer.Exit(code=2)
    dst = store.catalog_dir()
    dst.mkdir(parents=True, exist_ok=True)

    # zip приймається нарівні з текою: саме так довідники їдуть з інсталятором,
    # і змушувати людину розпаковувати вручну означало б зайвий крок там, де
    # його легко зробити самим
    tmpdir: tempfile.TemporaryDirectory[str] | None = None
    if src.is_file() and src.suffix.lower() == ".zip":
        tmpdir = tempfile.TemporaryDirectory(prefix="nysh-catalog-")
        with zipfile.ZipFile(src) as zf:
            zf.extractall(tmpdir.name)
        src = Path(tmpdir.name)

    files = ([src] if src.is_file() else
             sorted(p for p in src.rglob("*.sqlite") if p.is_file()))
    if not files:
        typer.echo(f"у {src} немає жодного .sqlite")
        raise typer.Exit(code=1)
    n = 0
    for f in files:
        meta = store._read_meta(f)
        if domain and meta.get("domain") != domain:
            continue
        target = dst / f.name
        # через сусідній тимчасовий: обрив копіювання не має лишати
        # напівфабрикату під бойовим іменем
        tmp = target.with_name(target.name + ".part")
        shutil.copy2(f, tmp)
        tmp.replace(target)
        n += 1
        typer.echo(f"✅ {f.name} → {target}")
    if tmpdir is not None:
        tmpdir.cleanup()
    store.invalidate()
    typer.echo(f"поставлено паків: {n}")


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
