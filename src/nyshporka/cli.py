"""Командний рядок `nysh`.

Поки скелет: `--version` і `info`. Обидві команди навмисно НЕ порожні —
встановлюваність пакета доводиться тим, що консольний скрипт справді
запускається у чистому середовищі, а не тим, що `import` не впав.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from nyshporka import __version__

app = typer.Typer(
    name="nysh",
    help="Нишпорка — читання рукописних архівних справ і пошук прізвища в них.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """Версія пакета."""
    console.print(__version__)


@app.command()
def info() -> None:
    """Стан установки: що вже є, чого ще немає."""
    console.print(f"[bold]Нишпорка[/bold] {__version__}")
    console.print(f"  python  {platform.python_version()} ({sys.platform})")

    # Важкі extras перевіряються НАЯВНІСТЮ, а не імпортом у момент старту:
    # тягнути torch заради рядка «встановлено» коштувало б секунд на кожен запуск.
    from importlib.util import find_spec

    for label, module, extra in (
        ("консоль", "fastapi", "app"),
        ("архіви", "aiolimiter", "archives"),
        ("GEDCOM", "ged4py", "gedcom"),
        ("HTR", "torch", "htr"),
    ):
        have = find_spec(module) is not None
        # 🔴 `\[` — екранування для rich. Без нього `[app]` з'їдається як
        # розмітка, і порада перетворюється на «pip install nyshporka», тобто
        # рівно ту команду, яка extra НЕ ставить. Порада, що не працює, гірша
        # за відсутню: користувач виконує її і бачить той самий стан.
        mark = ("[green]є[/green]" if have
                else rf"[dim]немає — pip install 'nyshporka\[{extra}]'[/dim]")
        console.print(f"  {label:8s} {mark}")


@app.command()
def sources() -> None:
    """Звідки можна брати матеріал — і що кожне джерело вміє."""
    reg = _sources_registry()
    for src in reg.all():
        caps = ", ".join(sorted(src.caps)) or "—"
        console.print(f"  [bold]{src.id:<10}[/bold] {src.label}")
        console.print(f"  {'':<10} [dim]уміє: {caps}[/dim]")
    # 🔴 Зламані плагіни називаються поіменно: «мого архіву немає в списку»
    # інакше не має пояснення, і людина шукатиме причину в своїх налаштуваннях.
    for name, why in reg.broken:
        console.print(f"  [red]✗ {name}[/red] [dim]{why}[/dim]")


@app.command()
def look(path: str = typer.Argument(..., help="тека зі сканами, PDF або тека з PDF")) -> None:
    """Що це за матеріал: скільки кадрів, чи це одна справа, чи багато."""
    from nyshporka.sources.local import LocalSource, inspect

    shape = inspect(path)
    mark = "[green]✓[/green]" if shape.usable else "[yellow]![/yellow]"
    console.print(f"{mark} {shape.explain()}")
    if shape.kind == "cases":
        for node in shape.cases:
            console.print(f"    [dim]{node.frames:>6} кадрів[/dim]  {node.label}")
        console.print("\n[dim]Оберіть одну зі справ вище або поставте всі в чергу.[/dim]")
        raise typer.Exit(code=1)
    if not shape.usable:
        raise typer.Exit(code=1)
    m = LocalSource().manifest(str(shape.path))
    if m.bytes_estimate:
        console.print(f"  [dim]обсяг: {m.bytes_estimate / 1024 / 1024:.0f} МБ[/dim]")


def _sources_registry() -> Any:
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.sources import load

    try:
        return load(workspace().root)
    except WorkspaceError:
        return load(None)


def _pick(source_id: str) -> Any:
    reg = _sources_registry()
    src = reg.get(source_id)
    if src is None:
        console.print(f"[red]немає джерела «{source_id}»[/red] — є: "
                      + ", ".join(s.id for s in reg.all()))
        raise typer.Exit(code=2)
    return src


@app.command()
def find(q: str = typer.Argument(..., help="село, прізвище чи слово із заголовка"),
         source: str = typer.Option("", "--source", help="лише це джерело"),
         limit: int = typer.Option(20, "--limit")) -> None:
    """Де взагалі є щось про моє село — пошук по каталогах джерел."""
    from nyshporka import ops as O

    env = O.call("catalog.search", {"q": q, "source": source, "limit": limit})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    hits = env.data.get("hits") or []
    for h in hits:
        head = " · ".join(x for x in (h.get("shifra"), h.get("years")) if x)
        console.print(f"  [bold]{h['source']}[/bold]  {h['title']}")
        console.print(f"  {'':<{len(h['source'])}}  [dim]{head}[/dim]")
        console.print(f"  {'':<{len(h['source'])}}  [dim]{h['ref']}[/dim]")
    cov = env.data.get("coverage") or {}
    # 🔴 Знаменник друкується ЗАВЖДИ, і найважливіший він саме тоді, коли
    # знахідок нуль: без нього «нічого не знайшлось» читається як «цього не
    # існує», хоча дивились в одному каталозі з трьох.
    console.print(f"\n[dim]знайдено {len(hits)} · шукали в: "
                  f"{', '.join(cov.get('searched') or []) or '—'}[/dim]")
    for u in cov.get("unavailable") or []:
        console.print(f"[yellow]⚠ {u['source']}[/yellow] [dim]{u['why']}[/dim]")


@app.command()
def browse(source: str = typer.Argument(..., help="id джерела (`nysh sources`)"),
           ref: str = typer.Argument("", help="вузол; порожньо = верхній рівень")) -> None:
    """Що лежить у фонді, описі, теці дзеркала."""
    from nyshporka.sources.base import SourceError

    src = _pick(source)
    try:
        nodes = src.browse(ref or None)
    except SourceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    for n in nodes:
        frames = f"{n.frames:>7} кадрів" if n.frames else " " * 14
        mark = "📄" if n.kind == "case" else "📁"
        console.print(f"  {mark} {frames}  {n.label}")
        console.print(f"     [dim]{n.ref}[/dim]")
    console.print(f"\n[dim]{len(nodes)} вузлів[/dim]")


@app.command()
def get(source: str = typer.Argument(..., help="id джерела"),
        ref: str = typer.Argument(..., help="адреса справи чи плівки"),
        out: Path = typer.Option(..., "--out", help="куди складати кадри"),
        frames: str = typer.Option("", "--frames",
                                   help="діапазон кадрів «12-80»; порожньо = всі")) -> None:
    """Завантажити справу або плівку.

    Спершу друкується МАНІФЕСТ і лише потім починається качання: справа буває
    на кілька гігабайтів, і питання «скільки це» мусить мати відповідь ДО, а не
    після — перервана закачка лишає теку в невизначеному стані.
    """
    from nyshporka.sources.base import SourceError

    src = _pick(source)
    rng: tuple[int, int] | None = None
    if frames:
        try:
            a, _, b = frames.partition("-")
            rng = (int(a), int(b or a))
        except ValueError:
            console.print("[red]--frames очікує «12-80»[/red]")
            raise typer.Exit(code=2) from None
    try:
        man = src.manifest(ref)
    except SourceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[bold]{man.title or ref}[/bold] — кадрів {man.frames}"
                  + (f", беремо {rng[0]}-{rng[1]}" if rng else ""))
    for s in man.sheets[:12]:
        console.print(f"  [dim]Л.{s.frm}-{s.to}  {s.label[:80]}[/dim]")
    if len(man.sheets) > 12:
        console.print(f"  [dim]…ще {len(man.sheets) - 12} записів покажчика[/dim]")

    state = {"last": -1}

    def progress(done: int = 0, total: int = 0, **_: Any) -> None:
        pct = int(done * 100 / total) if total else 0
        if pct != state["last"]:
            state["last"] = pct
            console.print(f"  [dim]{done}/{total} ({pct}%)[/dim]", end="\r")

    res = src.fetch(ref, out, frames=rng, on_progress=progress)
    console.print(f"\n✓ {res.frames} кадрів ({res.bytes / 1024 / 1024:.0f} МБ), "
                  f"пропущено {res.skipped} → {res.dest}")
    for e in res.errors[:5]:
        console.print(f"[yellow]⚠ {e}[/yellow]")
    if res.errors:
        raise typer.Exit(code=1)


@app.command()
def crawl(source: str = typer.Argument("archium", help="id джерела"),
          groups: str = typer.Option("", "--groups",
                                     help="групи фондів через кому; порожньо = давні акти"),
          fresh: bool = typer.Option(False, "--fresh",
                                     help="почати наново, а не продовжити")) -> None:
    """Зібрати каталог справ, по якому потім працює `nysh find`.

    🔴 Потрібне не всім джерелам, а тим, чий сайт не індексує заголовків справ.
    Для ARCHIUM без цього кроку пошук неможливий у принципі — і саме тому він
    відмовляється відповідати нулем.
    """
    src = _pick(source)
    if not hasattr(src, "crawl"):
        console.print(f"[yellow]джерело «{source}» не потребує обходу — "
                      f"його каталог доступний одразу[/yellow]")
        raise typer.Exit(code=0)

    def progress(done: int = 0, total: int = 0, note: str = "", **_: Any) -> None:
        console.print(f"  [dim]{done}/{total} фондів · {note}[/dim]", end="\r")

    stats = src.crawl(tuple(g.strip() for g in groups.split(",") if g.strip()) or None,
                      on_progress=progress, resume=not fresh)
    console.print(f"\n✓ фондів {stats['fonds']} (пропущено готових "
                  f"{stats['skipped']}) · описів {stats['inventories']} · "
                  f"справ {stats['cases']}")


@app.command()
def init(
    path: str = typer.Argument("", help="куди покласти простір; порожньо — запропоную"),
    name: str = typer.Option("", "--name", help="як зветься дослідження"),
    yes: bool = typer.Option(False, "--yes", "-y", help="без питань (для інсталятора)"),
) -> None:
    """Створити робочий простір — теку, де житиме дослідження.

    🔴 Мовчки простір не створюється ніколи: тека, що з'явилась сама, — це
    дослідження, яке потім не можуть знайти.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.setup import wizard

    try:
        p = wizard.plan(path or None)
    except WorkspaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    console.print(f"Простір: [bold]{p.root}[/bold]"
                  + ("" if p.creating else "  [dim](уже існує)[/dim]"))
    if p.warning:
        console.print(f"[yellow]⚠ {p.warning}[/yellow]")
    if p.creating and not yes and not typer.confirm("Створити?", default=True):
        raise typer.Exit(code=1)
    root = wizard.create(p.root, name=name)
    console.print(f"✅ готово: {root}")
    console.print("[dim]далі: `nysh look <тека зі сканами>` або `nysh serve`[/dim]")


@app.command()
def doctor(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Перевірити те, що ламається ТИХО: карта, хмарна тека, місце, рушії."""

    from nyshporka.setup import doctor as doc

    checks = doc.run()
    if as_json:
        console.print_json(data=[{"name": c.name, "level": c.level,
                                  "detail": c.detail, "fix": c.fix}
                                 for c in checks])
        raise typer.Exit(code=0 if all(c.level != "fail" for c in checks) else 1)
    for c in checks:
        console.print(f"{c.mark} [bold]{c.name}[/bold]  {c.detail}")
        if c.fix and c.level != "ok":
            console.print(f"   [dim]{c.fix}[/dim]")
    bad = [c for c in checks if c.level == "fail"]
    raise typer.Exit(code=1 if bad else 0)


htr_app = typer.Typer(help="Рушії читання рукопису.", no_args_is_help=True)
app.add_typer(htr_app, name="htr")


@htr_app.command("install")
def htr_install(
    no_cuda: bool = typer.Option(False, "--no-cuda", help="не чіпати torch"),
) -> None:
    """Зібрати середовище рушіїв — ОКРЕМИЙ інтерпретатор поруч із простором.

    🔴 Окремий не для краси: сегментація йде на `kraken==7.0.2` з двома
    патчами приватних функцій, доведеними рівними оригіналу саме на цій версії.
    Інша версія дала б ТИХУ розбіжність — ті самі скани, інші полігони рядків,
    інший текст, без помилки в лозі. Тримати такий пін в основному середовищі
    означало б нав'язати його всьому, що там є.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    try:
        venv = doc.engine_venv()
    except WorkspaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    rep = E.setup(venv, with_cuda=not no_cuda)
    console.print(f"\npython : {rep.python or '—'}")
    console.print(f"kraken : {rep.kraken or '—'}")
    console.print(f"torch  : {rep.torch or '—'}  cuda={rep.cuda} "
                  f"capability={rep.capability or '—'}")
    for p in rep.problems:
        console.print(f"[yellow]⚠ {p}[/yellow]")
    if rep.missing:
        console.print(f"[red]🔴 бракує: {', '.join(rep.missing)}[/red]")
    raise typer.Exit(code=0 if rep.ok else 1)


models_app = typer.Typer(help="Ваги моделей письма.", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list() -> None:
    """Що є, чого немає, що зіпсоване."""
    from nyshporka.setup import packs

    state = packs.as_dict()
    mark = {"ok": "✅", "absent": "▫️", "broken": "🔴"}
    for p in state["packs"]:
        size = f"{p['size'] / 2**20:.0f} МБ" if p["size"] else "?"
        console.print(f"  {mark.get(p['state'], '?')} [bold]{p['label']}[/bold] "
                      f"[dim]{p['script']}/{p['engine']} · {size}[/dim]")
    console.print(f"[dim]тека: {state['dir']}[/dim]")


@models_app.command("get")
def models_get(
    which: str = typer.Argument("", help="id пака; порожньо — усі, яких бракує"),
) -> None:
    """Завантажити ваги. sha256 звіряється завжди."""
    from nyshporka.setup import packs

    want = [p for p in packs.catalog() if not which or p.id == which]
    want = [p for p in want if not packs.verify(p)]
    if not want:
        console.print("✅ усе на місці")
        return
    for p in want:
        console.print(f"⬇ {p.label} …")
        try:
            dst = packs.fetch(p)
        except Exception as exc:
            console.print(f"[red]✗ {p.id}: {exc}[/red]")
            raise typer.Exit(code=1) from None
        console.print(f"  ✅ {dst}")


@app.command()
def serve(
    port: int = typer.Option(8788, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser",
                                    help="не відкривати вкладку самому"),
) -> None:
    """Підняти застосунок у браузері.

    🔴 Слухає ЛИШЕ 127.0.0.1, і опції це змінити немає. Тут архів однієї
    людини — канон про живих родичів, скани, нотатки; прапорець «слухати всюди»
    рано чи пізно вмикають «на хвилинку» й лишають.
    """
    try:
        from nyshporka.daemon import serve as _serve
    except (ImportError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        console.print(r"[dim]pip install 'nyshporka\[app]'[/dim]")
        raise typer.Exit(code=1) from None
    _serve(port=port, open_browser=not no_browser)


@app.command("ops")
def ops_list(agent_only: bool = typer.Option(False, "--agent",
                                             help="лише те, що бачить агент")) -> None:
    """Перелік операцій — те саме, що доступне агентові й браузеру."""
    from nyshporka import ops as O

    for op in (O.for_agent() if agent_only else O.all_ops()):
        marks = "".join(("✎" if op.mutates else " ", "⏳" if op.long else " ",
                         "🤖" if op.agent else " "))
        console.print(f"  {marks} [bold]{op.name:<18}[/bold] {op.summary}")


@app.command("op")
def op_run(
    name: str = typer.Argument(..., help="ім'я операції, напр. workspace.info"),
    args: str = typer.Option("{}", "--args", help="аргументи як JSON"),
    as_json: bool = typer.Option(True, "--json/--human", help="формат виводу"),
) -> None:
    """Виконати операцію напряму.

    🔴 Це і є те, що робить командний рядок повним: КОЖНА операція доступна тут
    без окремої команди. Дружні команди (`look`, `sources`) — лише зручні
    обгортки над тими самими операціями, тож відстати від агента CLI не може.
    """
    import json as _json

    from nyshporka import ops as O

    try:
        payload = _json.loads(args)
    except ValueError as exc:
        console.print(f"[red]--args не є JSON:[/red] {exc}")
        raise typer.Exit(code=2) from None

    env = O.call(name, payload)
    if as_json:
        console.print_json(data=env.as_dict())
    else:
        note = env.as_agent_text()
        if note:
            console.print(note)
        console.print_json(data=env.data)
    raise typer.Exit(code=0 if env.ok else 1)


mcp_app = typer.Typer(help="Агентна поверхня (Claude Code, Codex).",
                      no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Підняти MCP-сервер по stdio (так його запускає агент)."""
    from nyshporka.mcp import serve

    raise typer.Exit(code=serve())


@mcp_app.command("tools")
def mcp_tools() -> None:
    """Що саме бачить агент."""
    from nyshporka.mcp import tool_definitions

    defs = tool_definitions()
    for d in defs:
        console.print(f"  [bold]{d['name']:<22}[/bold] {d['description']}")
    console.print(f"\n[dim]усього {len(defs)}[/dim]")


@mcp_app.command("install")
def mcp_install(
    target: str = typer.Option(".mcp.json", help="куди дописати конфіг"),
    show: bool = typer.Option(False, "--show", help="лише показати, не писати"),
) -> None:
    """Прописати сервер у `.mcp.json` проєкту."""
    import json as _json

    from nyshporka.mcp import mcp_config

    cfg = mcp_config()
    if show:
        console.print_json(data=cfg)
        return
    path = Path(target)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = _json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            console.print(f"[yellow]![/yellow] {path} не є JSON — не чіпаю його")
            raise typer.Exit(code=1) from None
    # Дописуємо, а не заміщаємо: у файлі можуть бути чужі сервери, і затерти їх
    # означало б зламати налаштування, які людина робила руками.
    servers = dict(existing.get("mcpServers") or {})
    servers.update(cfg["mcpServers"])
    existing["mcpServers"] = servers
    path.write_text(_json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    console.print(f"✓ {path}: додано сервер «nyshporka»")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
