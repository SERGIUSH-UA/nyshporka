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
    basis = "; ".join(
        f"{b['source']}: {b['kind']}" + (f" від {b['taken']}" if b.get("taken") else "")
        for b in (cov.get("basis") or []))
    console.print(f"\n[dim]знайдено {len(hits)} · шукали в: "
                  f"{', '.join(cov.get('searched') or []) or '—'}"
                  + (f" ({basis})" if basis else "") + "[/dim]")
    # 🔴 ВСІ попередження конверта, а не лише про недоступні джерела. Саме тут
    # їде різниця між «не знайшлось» і «не знайшлось у зрізі піврічної давнини»,
    # і показувати її вибірково — те саме, що не показувати.
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


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


@app.command()
def read(
    case_dir: str = typer.Argument(..., help="ПЛАСКА тека зі сканами справи"),
    out: str = typer.Option("", "--out", help="куди класти текст"),
    script: str = typer.Option("", "--script", help="latin | cyrillic"),
    one_voice: bool = typer.Option(False, "--one-voice",
                                   help="без другого рушія (швидше, але сліпіше)"),
    case_key: str = typer.Option("", "--case-key", help="шифра справи у мету"),
    dry: bool = typer.Option(False, "--dry-run", help="лише показати план"),
) -> None:
    """Прочитати справу рукописним рушієм.

    🔴 Читає ПРЯМО тут, а не через застосунок — і це свідомо. Прогін ставлять
    на ніч, часто по ssh, і вимагати для цього піднятого браузера означало б
    зробити найдовшу роботу найкрихкішою.
    """
    import subprocess

    from nyshporka.core.progress import split
    from nyshporka.htr.run import ReadError
    from nyshporka.htr.run import plan as make_plan

    try:
        p = make_plan(case_dir, out_dir=out, script=script,
                      second_voice=not one_voice)
    except ReadError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[bold]{p.case_dir.name}[/bold] — {p.frames} кадрів · "
                  f"письмо {p.script} · {p.model.name}"
                  + (f" + {p.voice.name}" if p.voice else ""))
    console.print(f"  [dim]{p.out_dir}[/dim]")
    if dry:
        console.print("  [dim]" + " ".join(p.command(case_key=case_key)) + "[/dim]")
        return

    p.out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(p.command(case_key=case_key), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        ev, human = split(line.rstrip())
        if ev is not None and ev.n:
            console.print(f"  [dim]{ev.i}/{ev.n} ({ev.pct:.0f}%) {ev.item}[/dim]",
                          end="\r")
        elif human:
            console.print(f"  [dim]{human}[/dim]")
    rc = proc.wait()

    # 🔴 Приймач повноти — ДИСК, а не код повернення: при шардингу тиха втрата
    # сторінок дає rc=0 і порожній перелік збоїв.
    from nyshporka.htr.run import count_frames

    pages = len(list(p.out_dir.glob("*.txt")))
    missing = max(0, count_frames(p.case_dir) - pages)
    console.print(f"\n{'✅' if rc == 0 and not missing else '🔴'} "
                  f"сторінок з текстом: {pages} з {p.frames}"
                  + (f" · БЕЗ ТЕКСТУ: {missing}" if missing else ""))
    raise typer.Exit(code=0 if rc == 0 and not missing else 1)


@app.command("case")
def case_cmd(
    case_dir: str = typer.Argument(..., help="тека зі сканами"),
    shifra: str = typer.Option("", "--shifra", help="«ДАХмО 315-1-8433»"),
    title: str = typer.Option("", "--title", help="назва справи"),
    doc_type: str = typer.Option("", "--type", help="метрична / сповідна / ревізька"),
    year_from: int = typer.Option(0, "--from", help="рік початку"),
    year_to: int = typer.Option(0, "--to", help="рік кінця"),
    place: str = typer.Option("", "--place", help="село, повіт, губернія"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Завести або виправити справу: сказати, ЩО лежить у цій теці.

    🔴 Без шифри тека лишається купою файлів — ні ключа, ні обліку, ні
    можливості послатись на знахідку.
    """
    from nyshporka import ops as O

    env = O.call("case.register", {
        "case_dir": case_dir, "shifra": shifra, "title": title,
        "doc_type": doc_type, "place": place, "note": note,
        "year_from": year_from or None, "year_to": year_to or None})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    sc = env.data["sidecar"]
    console.print(f"✅ [bold]{sc['shifra']}[/bold] — {sc.get('title') or 'без назви'}")
    if sc.get("year_from") or sc.get("place"):
        console.print(f"   [dim]{sc.get('place') or ''} "
                      f"{sc.get('year_from') or ''}"
                      f"{'-' + str(sc['year_to']) if sc.get('year_to') else ''}[/dim]")
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


@app.command("archive")
def archive_cmd(
    repo: str = typer.Argument(..., help="код архіву: DAHMO, CDIAK, ANRM…"),
    fond: str = typer.Argument(..., help="номер фонду"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Що пак знає про фонд: губернія, опис у ключі, дефолти.

    🔴 Питати це треба ПЕРЕД тим, як складати ключ справи. У частині фондів
    опис входить у ключ, і без нього різні книги злипаються в одну — знайти
    це потім можна лише за чужими сторінками у своїй справі.
    """
    from nyshporka import ops as O

    env = O.call("archive.fond", {"repo": repo, "fond": fond})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    if as_json:
        console.print_json(data=env.data)
        return
    d = env.data
    console.print(f"[bold]{d['repo_label'] or d['repo']} ф.{d['fond']}[/bold] "
                  f"{d.get('name') or ''}")
    console.print(f"  губернія: {d.get('guberniya') or '—'} · опис у ключі: "
                  f"{'ТАК' if d.get('opys_in_key') else 'ні'} · опис за "
                  f"замовчуванням: {d.get('default_opys') or '—'}")
    if d.get("note"):
        console.print(f"  [dim]{d['note']}[/dim]")
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


@app.command("profile")
def profile_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """Чий рід шукаємо: форми прізвища, корені, парадигма.

    🔴 Перше, що варто спитати на чужому просторі. Без свого профілю пошук
    мовчки працює на прізвище того, хто налаштовував простір до вас, — і нуль
    у відповіді буде про чужий рід.
    """
    from nyshporka import ops as O

    env = O.call("profile.show", {})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        for w in env.warnings:
            console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")
        raise typer.Exit(code=1)
    if as_json:
        console.print_json(data=env.data)
        return
    d = env.data
    console.print(f"[bold]{d.get('display') or d.get('name')}[/bold] "
                  f"[dim]парадигма {d.get('paradigm') or '—'}[/dim]")
    console.print(f"  корені: {', '.join(d.get('roots') or []) or '—'}")
    console.print(f"  форми: {len(d.get('spellings') or [])} · "
                  f"самоперевірка: {d.get('selftest_mode')}")


@app.command("review")
def review_cmd(
    source: str = typer.Option("", "--source", help="лише з цього джерела"),
    min_score: float = typer.Option(0.0, "--min-score"),
) -> None:
    """Людський gate: перебрати кандидатів із зовнішніх джерел.

    🔴 Жоден кандидат не потрапляє в канон машиною. Це не обережність, а
    вимірювана вартість: збіг прізвища й десятиліття дає правдоподібну, але
    чужу особу, і виявляється це через покоління дерева.

    Кандидатів пишуть fetcher'и зовнішніх сайтів, яких у цій версії ще немає
    (правове питання ToS чужих сервісів), тож на щойно створеному просторі
    черга буде порожня — це стан, а не поламка.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.matching.review import review_loop

    review_loop(workspace().root, source=source or None, min_score=min_score,
                console=console)


cases_app = typer.Typer(help="Реєстр справ: що є, що прочитано, що прошукано.",
                        no_args_is_help=True)
app.add_typer(cases_app, name="cases")


@cases_app.command("build")
def cases_build(
    rescan: bool = typer.Option(True, "--rescan/--no-rescan",
                                help="перечитати ще й диск (нові теки)"),
) -> None:
    """Зібрати реєстр справ.

    🔴 Реєстр — це ЗРІЗ п'яти сховищ, а не сховище. Він старіє за хвилини, і
    застарілий зріз небезпечніший за відсутній: він виглядає як відповідь
    («декоду немає») там, де роботу зробили годину тому. Тому перезбирати його
    треба після кожного прогону, завантаження й занесення в облік — а команди
    для цього досі не існувало, хоч усі повідомлення на неї посилались.
    """
    from nyshporka.cases import db

    if rescan:
        from nyshporka.library import build_library, write_library

        entries = build_library()
        write_library(entries)
        console.print(f"[dim]бібліотеку перезібрано: {len(entries)} справ[/dim]")
    res = db.build_index()
    console.print(f"✅ реєстр: [bold]{res['cases']}[/bold] справ · "
                  f"нерозв'язаних прогонів: {res.get('orphans', 0)} · {res['path']}")


@cases_app.command("list")
def cases_list_cmd(
    q: str = typer.Option("", "--q", help="підрядок: шифра, назва, місце"),
    repo: str = typer.Option("", "--repo"),
    year: str = typer.Option("", "--year", help="рік або «1840-1860»"),
    limit: int = typer.Option(40, "--limit"),
) -> None:
    """Перелік справ із станом обробки."""
    from nyshporka import ops as O

    env = O.call("cases.list", {"q": q, "repo": repo, "year": year, "limit": limit})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    from rich.table import Table as _T

    t = _T(header_style="bold")
    for col in ("шифра", "назва", "кадрів", "читання"):
        t.add_column(col, max_width=44, no_wrap=True, overflow="ellipsis")
    for r in env.data.get("cases") or []:
        t.add_row(r.get("shifra") or r.get("key") or "",
                  (r.get("title") or "[dim]без назви[/dim]")[:60],
                  str(r.get("frames") or 0),
                  r.get("htr_stage") or "—")
    console.print(t)
    if env.stale and env.stale.is_stale:
        console.print(f"[yellow]⚠ зріз застарів[/yellow] [dim]"
                      f"{'; '.join(env.stale.reasons[:2])} — nysh cases build[/dim]")


pages_app = typer.Typer(help="Облік переглянутого оком.", no_args_is_help=True)
app.add_typer(pages_app, name="pages")


@pages_app.command("status")
def pages_status_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Що в цій справі вже дивились, а що ні — ПЕРЕД тим, як відкривати."""
    from nyshporka import ops as O

    env = O.call("pages.status", {"case": case})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    if as_json:
        console.print_json(data=env.data)
        return
    d = env.data
    console.print(f"[bold]{d['shifra']}[/bold] {d.get('title') or ''}")
    console.print(f"  на диску: {d.get('total_disk', 0)} · анотовано: {d['noted']} "
                  f"· записів: {d['records']} · статуси: {d.get('by_status') or {}}")
    if d.get("unnoted_count"):
        console.print(f"  [yellow]необроблених: {d['unnoted_count']}[/yellow]")


@pages_app.command("note")
def pages_note_cmd(
    case: str = typer.Argument(...),
    scan: str = typer.Argument(..., help="голе ім'я файлу: 0030.JPG"),
    page_type: str = typer.Option(..., "--type"),
    surnames: str = typer.Option("", "--surnames", help="кома-список ЯК У ДЖЕРЕЛІ"),
    places: str = typer.Option("", "--places"),
    years: str = typer.Option("", "--years"),
    sheet: str = typer.Option("", "--sheet"),
    status: str = typer.Option("full", "--status"),
    method: str = typer.Option("visual", "--method"),
    comment: str = typer.Option("", "--comment"),
) -> None:
    """Занести переглянуту сторінку.

    🔴 БЕЗ ВИНЯТКІВ: кожен скан, який реально відкривали, заноситься — навіть
    якщо він виявився пустишкою. Негативний результат коштує тих самих очей, а
    без запису наступна сесія перегляне той самий аркуш ще раз.
    """
    from nyshporka import ops as O

    env = O.call("pages.note", {
        "case": case, "scan": scan, "page_type": page_type,
        "surnames": surnames, "places": places, "years": years, "sheet": sheet,
        "status": status, "method": method, "comment": comment})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    console.print(f"✅ {env.data['shifra']} {scan}")
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


@pages_app.command("grep")
def pages_grep_cmd(
    q: str = typer.Argument(..., help="прізвище"),
    where: str = typer.Option("pages", "--where", help="pages | records | decode"),
    case: str = typer.Option("", "--case"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """Знайти прізвище в тому, що вже прочитано."""
    from nyshporka import ops as O

    env = O.call("search.run", {"q": q, "where": where, "case": case, "limit": limit})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    for h in (env.data.get("hits") or [])[:limit]:
        console.print(f"  [bold]{h.get('case') or h.get('key') or ''}[/bold] "
                      f"{h.get('scan') or h.get('page') or ''}  "
                      f"{str(h.get('surname') or h.get('line') or h.get('name') or '')[:80]}")
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


records_app = typer.Typer(help="Розібрані записи джерела: хто, коли, чиї.",
                          no_args_is_help=True)
app.add_typer(records_app, name="records")


@records_app.command("add")
def records_add_cmd(
    case: str = typer.Argument(..., help="справа у будь-якому форматі"),
    from_json: str = typer.Option("-", "--json",
                                  help="файл із масивом записів; «-» — stdin"),
) -> None:
    """Занести розібрані акти структурою, а не прозою.

    Проза не шукається за роллю: «хто був батьком» і «хто був восприємником» у
    ній однакові рядки. Невалідні елементи пропускаються зі звітом — не
    втрачати сорок розібраних актів через одруківку в сорок першому.
    """
    from nyshporka import ops as O

    payload = (sys.stdin.read() if from_json == "-"
               else Path(from_json).read_text(encoding="utf-8"))
    env = O.call("records.add", {"case": case, "records": payload})
    if not env.ok:
        console.print(f"[red]{env.error}[/red]")
        raise typer.Exit(code=1)
    d = env.data
    console.print(f"✅ [bold]{d.get('shifra') or d.get('case')}[/bold] "
                  f"додано: {d.get('added', 0)} · оновлено: {d.get('updated', 0)}")
    for w in env.warnings:
        console.print(f"[yellow]⚠[/yellow] [dim]{w.text}[/dim]")


@records_app.command("grep")
def records_grep_cmd(
    q: str = typer.Argument(..., help="прізвище"),
    case: str = typer.Option("", "--case"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """Знайти прізвище серед розібраних записів."""
    pages_grep_cmd(q=q, where="records", case=case, limit=limit)


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
