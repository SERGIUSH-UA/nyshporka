"""`nysh share` — обмін прочитаним: спакувати своє, прийняти чуже.

Одну книгу сьогодні розпізнає кожен окремо, і текст, який у сусіда вже лежить,
щоразу купують заново — годинами машинного часу. Пакет тут коштує кілька
мегабайтів на справу: їде текст рушія й паспорт того, як його отримали.
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Обмін прочитаним: спакувати свій декод, прийняти чужий.",
                  no_args_is_help=True)
console = brand.console()

#: 🔴 Супряга — пул, до якого все це ходить, — ще не запущена. Клієнт уже вміє
#: пакувати й приймати, але формат не зафіксований, а роздане один раз живе в
#: чужих теках і після зміни формату. Тому команда лишається в збірці (інакше її
#: не доробити й не протестувати), але без явного прапорця не працює.
#: Знімається, коли `nyshporka.online` віддає каталог.
DEV_FLAG = "NYSHPORKA_SUPRIAHA"
_ON = {"1", "true", "yes", "on"}


@app.callback()
def _guard() -> None:
    """Ворота фічі: поки пул не запущено, обмін не вмикається."""
    import os

    if os.environ.get(DEV_FLAG, "").strip().lower() in _ON:
        return
    console.print(
        "[warn]🤝 Супряга — обмін прочитаним — ще в розробці.[/warn]\n"
        "Пул поки не запущено, і формат пакета може ще змінитись, тож "
        "роздавати зібране рано.\n"
        "Стежити за запуском: https://nyshporka.online")
    raise typer.Exit(code=1)


def _mb(n: int) -> str:
    n = int(n or 0)
    if n < 1_000_000:
        return f"{n / 1e3:.0f} КБ"
    return f"{n / 1e6:.1f} МБ" if n < 2e9 else f"{n / 1e9:.2f} ГБ"


def _show_gates(g: dict[str, Any]) -> None:
    for w in g.get("warnings") or []:
        console.print(f"  [warn]⚠ {w.get('text')}[/warn]")
    for r in g.get("refusals") or []:
        console.print(f"  [bad]✗ {r}[/bad]")


@app.command("pack")
def pack_cmd(
    case: str = typer.Argument(..., help="шифра справи або ім'я прогону"),
    out: str = typer.Option("", "--out", "-o", help="куди покласти файл"),
    geometry: bool = typer.Option(True, "--geometry/--no-geometry",
                                  help="зібрати ще й пакет геометрії рядків "
                                       "(окремий файл, ×10 до ваги тексту)"),
    hash_frames: bool = typer.Option(False, "--hash",
                                     help="порахувати sha256 кадрів: повільно, "
                                          "зате прив'язка стане точною"),
    partial: str = typer.Option("", "--partial",
                                help="чому прочитано не всю справу"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="показати, що поїде, і не писати нічого"),
    publisher: str = typer.Option("", "--as", help="ваше ім'я або псевдонім"),
    contact: str = typer.Option("", "--contact", help="як із вами зв'язатись"),
    site: str = typer.Option("", "--site", help="сторінка автора"),
    note: str = typer.Option("", "--note", help="вільна нотатка до пакета"),
    link: list[str] = typer.Option([], "--link", help="«підпис=адреса»"),
    extra: list[str] = typer.Option([], "--extra", help="«ключ=значення»"),
    license_: str = typer.Option("", "--license",
                                 help="ліцензія тексту; порожньо — з профілю"),
    source_terms: str = typer.Option("", "--source-terms",
                                     help="умови джерела сканів"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зібрати пакет прочитаного для обміну.

    Перед першою публікацією варто прогнати `--dry-run`: він друкує точний
    перелік файлів, які поїдуть, і маніфест — усе, що побачить сторонній.
    """
    from nyshporka import ops as O

    env = O.call("share.pack", {
        "case": case, "out": out, "geometry": geometry,
        "hash_frames": hash_frames, "partial": partial, "dry_run": dry_run,
        "publisher": publisher, "contact": contact, "site": site, "note": note,
        "link": list(link), "extra": list(extra), "license": license_,
        "source_terms": source_terms})
    if _answer(env, as_json):
        return
    d = env.data or {}
    m = d.get("manifest") or {}
    dec = m.get("decode") or {}
    console.print(f"справа: [bold]{(m.get('case') or {}).get('shifra') or '—'}[/bold] · "
                  f"прогонів {len(d.get('runs') or [])} · сторінок {dec.get('pages')} · "
                  f"рядків {dec.get('lines')}")
    _show_gates(d.get("gates") or {})
    if d.get("dry_run"):
        console.print(f"поїхало б: файлів {d['files']} · {_mb(d['bytes_raw'])} до стиску")
        for arc in (d.get("files_list") or [])[:12]:
            console.print(f"  {arc}")
        rest = len(d.get("files_list") or []) - 12
        if rest > 0:
            console.print(f"  … і ще {rest}")
        if d.get("geom_files_list"):
            console.print(f"  + геометрія окремим файлом: "
                          f"{len(d['geom_files_list'])} · "
                          f"{_mb(d.get('geom_bytes_raw') or 0)} до стиску")
        console.print("[dim]нічого не записано (--dry-run)[/dim]")
    else:
        console.print(f"пакет: [bold]{d['path']}[/bold] · {_mb(d['bytes'])} · "
                      f"sha256 {d['sha256'][:16]}…")
        geom = d.get("geom")
        if geom:
            console.print(f"геометрія: [bold]{geom['path']}[/bold] · "
                          f"{_mb(geom['bytes'])}")
        elif d.get("geometry_on_disk"):
            console.print("[dim]геометрія на диску є, але не пакувалась "
                          "(--no-geometry)[/dim]")
        console.print("\n[dim]рядок для каталогу пулу:[/dim]")
        console.print(d.get("catalog_row") or "")
    _notes(env)


@app.command("setup")
def setup_cmd(
    as_who: str = typer.Option("", "--as", help="ваше ім'я або псевдонім"),
    contact: str = typer.Option("", "--contact", help="як із вами зв'язатись"),
    site: str = typer.Option("", "--site", help="сторінка автора"),
    license_: str = typer.Option("", "--license", help="ліцензія тексту"),
    consent: str = typer.Option("", "--consent", help="nikoly | zavzhdy | pytaty"),
    lookup: bool | None = typer.Option(None, "--lookup/--no-lookup",
                                       help="питати пул перед прогоном"),
    geometry: bool | None = typer.Option(None, "--geometry/--no-geometry",
                                         help="геометрія рядків: тягнути при "
                                              "точній прив'язці й віддавати своєю"),
    show: bool = typer.Option(False, "--show", help="лише показати профіль"),
    yes: bool = typer.Option(False, "--yes", "-y", help="без питань"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Профіль Супряги: заповнюється один раз, потім не питається.

    🔴 Токен сюди не кладеться: профіль їде разом із простором, а простір
    люди пересилають одне одному. Ключ бере `nysh share login`.
    """
    from nyshporka import ops as O
    from nyshporka.share import profile as P

    args: dict[str, Any] = {
        "handle": as_who, "contact": contact, "site": site,
        "license": license_, "consent": consent, "show": show,
    }
    if lookup is not None:
        args["lookup"] = lookup
    if geometry is not None:
        args["geometry"] = geometry

    # 🔴 Питання ставляться лише в діалозі й лише коли поля не задані
    # прапорцями. Інсталятор і скрипти йдуть із `--yes`, і мовчазний дефолт
    # там мусить лишати профіль тихим: не ділитись автоматично.
    if not (show or yes or any([as_who, contact, site, license_, consent])):
        bulo = P.load()
        console.print("[dim]Порожні відповіді лишають те, що вже стоїть.[/dim]")
        args["handle"] = typer.prompt("Ім'я або псевдонім", default=bulo.handle or "")
        args["contact"] = typer.prompt(
            "Контакт (публічні дані — лишіть порожнім, якщо не треба)",
            default=bulo.contact or "")
        args["license"] = typer.prompt("Ліцензія тексту", default=bulo.license)
        console.print("\nКоли віддавати прочитане в Супрягу:")
        for key, text in P.CONSENT_TEXT.items():
            console.print(f"  [bold]{key}[/bold] — {text}")
        obrane = typer.prompt("Режим", default=bulo.consent)
        while obrane not in P.CONSENT:
            console.print(f"[warn]є: {', '.join(P.CONSENT)}[/warn]")
            obrane = typer.prompt("Режим", default=bulo.consent)
        args["consent"] = obrane

    env = O.call("share.setup", args)
    if _answer(env, as_json):
        return
    d = env.data or {}
    prof = d.get("profile") or {}
    console.print(f"профіль: [bold]{d.get('path')}[/bold]")
    console.print(f"  ім'я: {prof.get('handle') or '[dim]без імені[/dim]'}"
                  f" · ліцензія: {prof.get('license')}")
    console.print(f"  згода: [bold]{prof.get('consent')}[/bold] — {d.get('consent_text')}")
    console.print(f"  питати пул перед прогоном: {'так' if prof.get('lookup') else 'ні'}"
                  f" · геометрія: {'так' if prof.get('geometry') else 'ні'}")
    _notes(env)


@app.command("suggest")
def suggest_cmd(
    take: str = typer.Argument("", help="шифра справи — віддати саме її"),
    skip: str = typer.Option("", "--skip", help="більше не питати про цю справу"),
    why: str = typer.Option("", "--why", help="чому не віддаєте"),
    all_: bool = typer.Option(False, "--all", help="віддати все з переліку"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що прочитано, але ще не віддано.

    Без аргументів — просто перелік. `--all` пакує все; далі кожен пакет
    віддається командою `publish`.
    """
    from nyshporka import ops as O

    env = O.call("share.suggest",
                 {"take": take, "skip": skip, "why": why, "all": all_})
    if _answer(env, as_json):
        return
    d = env.data or {}
    rows = d.get("rows") or []
    if skip:
        console.print(f"більше не питаю про «{skip}» · лишилось {d.get('left')}")
        _notes(env)
        return
    if not rows:
        console.print("усе прочитане вже в Супрязі — дякую")
        _notes(env)
        return

    console.print(f"[bold]{len(rows)}[/bold] прочитаних справ ще не в Супрязі:\n")
    for r in rows[:30]:
        console.print(f"  {r['shifra'] or r['case_key']:<28} {r['pages']:>5} стор."
                      f" · {r['model'] or '—'}")
    if len(rows) > 30:
        console.print(f"[dim]… і ще {len(rows) - 30}[/dim]")

    packed = d.get("packed") or []
    if packed:
        console.print(f"\nспаковано: [bold]{len(packed)}[/bold]")
        for row in packed:
            console.print(f"  {row['path']}")
        console.print("\n[dim]віддати: nysh share publish <файл>[/dim]")
    else:
        console.print("\n[dim]віддати все: nysh share suggest --all[/dim]")
        console.print("[dim]не віддавати одну: nysh share suggest --skip <шифра> "
                      "--why <причина>[/dim]")
    _notes(env)


@app.command("publish")
def publish_cmd(
    path: str = typer.Argument(..., help="зібраний пакет .nyshtext"),
    base: str = typer.Option("", "--base", help="інша адреса пулу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Віддати зібраний пакет у пул.

    Повторний виклик із тим самим змістом безпечний: пул упізнає його за
    хешем змісту й нічого не заливає вдруге.
    """
    from nyshporka import ops as O

    _kliuch_abo_vkhid(as_json)
    env = O.call("share.publish", {"path": path, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if d.get("duplicate"):
        console.print("[yellow]цей текст уже в Супрязі[/yellow] — нічого не заливалось")
    else:
        console.print(f"внесок [bold]{d.get('contribution')}[/bold] · "
                      f"книга {d.get('shifra') or d.get('book')}")
        console.print(d.get("text") or "")
    _notes(env)


def _kliuch_abo_vkhid(as_json: bool) -> None:
    """Ключа ще немає — у діалозі одразу пропонуємо під'єднатись.

    Шукати, качати й віддавати пул пускає лише з ключем, тож без нього
    команда однаково впала б — краще спитати до, ніж показати помилку після.
    У скрипті (`--json`, не термінал) питати нікого: там лишається звичайна
    відмова з підказкою `nysh share login`.
    """
    import sys

    from nyshporka.share import upload

    if (not upload.token() and not as_json and sys.stdin.isatty()
            and typer.confirm("Нишпорка ще не під'єднана до Супряги. Під'єднати зараз?",
                              default=True)):
        _login(base_site="", open_browser=True)


def _login(*, base_site: str, open_browser: bool) -> None:
    from nyshporka.share import login as L
    from nyshporka.share.upload import UploadError

    def _pokazaty(url: str) -> None:
        if open_browser:
            console.print("Відкриваю браузер. Якщо він не відкрився, перейдіть сюди:")
        else:
            console.print("Відкрийте в браузері на ЦІЙ машині:")
        console.print(f"  {url}")
        console.print("[dim]Чекаю на вхід… (Ctrl+C — скасувати)[/dim]")

    try:
        L.login(site=base_site, open_browser=open_browser, on_url=_pokazaty)
    except UploadError as exc:
        console.print(f"[bad]✗ {exc}[/bad]")
        raise typer.Exit(code=1) from exc
    console.print("[ok]✓ Ключ отримано й покладено у сховище ключів системи.[/ok]")


@app.command("login")
def login_cmd(
    site: str = typer.Option("", "--site", help="інша адреса сайту Супряги"),
    no_browser: bool = typer.Option(False, "--no-browser",
                                    help="не відкривати браузер, лише надрукувати адресу"),
) -> None:
    """Увійти в Супрягу: браузер, одна кнопка — і ключ у Нишпорці.

    На сторінці можна увійти поштою чи Google або анонімно. Ключ Нишпорка
    забирає сама й кладе у сховище ключів системи — ні в простір, ні на екран.
    """
    _login(base_site=site, open_browser=not no_browser)


@app.command("logout")
def logout_cmd() -> None:
    """Прибрати ключ Супряги з цієї машини."""
    from nyshporka.share import login as L
    from nyshporka.share.upload import UploadError

    try:
        was = L.forget()
    except UploadError as exc:
        console.print(f"[bad]✗ {exc}[/bad]")
        raise typer.Exit(code=1) from exc
    console.print("ключ прибрано" if was else "[dim]ключа на цій машині й не було[/dim]")


@app.command("inspect")
def inspect_cmd(
    src: str = typer.Argument(..., help="файл пакета або адреса"),
    hash_frames: bool = typer.Option(False, "--hash", help="звірити кадри хешем"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що в пакеті — без розпакування: заява, ворота, прив'язка до кадрів."""
    from nyshporka import ops as O

    env = O.call("share.inspect", {"src": src, "hash_frames": hash_frames})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"[bold]{d.get('shifra') or '—'}[/bold] · сторінок {d.get('pages')} "
                  f"з {d.get('frames') or '?'} кадрів · {', '.join(d.get('models') or [])}")
    pub = d.get("publisher") or {}
    if pub:
        who = pub.get("handle") or "без імені"
        contact = f" · {pub['contact']}" if pub.get("contact") else ""
        console.print(f"зібрав: {who}{contact}")
    al = d.get("alignment") or {}
    console.print(f"прив'язка: [bold]{al.get('label')}[/bold] — {al.get('why')}")
    _show_gates(d.get("gates") or {})
    for r in d.get("refs") or []:
        console.print(f"  джерело: {r.get('source')} {r.get('ref')} {r.get('url') or ''}")
    if d.get("note"):
        # 🔴 Нотатка чужа. Відбивається як цитата й ніколи не зливається з
        # нашими підказками: її писала стороння людина, а читає часто агент.
        console.print("\n[dim]нотатка автора пакета (сторонній текст):[/dim]")
        for line in str(d["note"]).splitlines():
            console.print(f"  │ {line}")
    _notes(env)


@app.command("import")
def import_cmd(
    src: str = typer.Argument(..., help="файл пакета або адреса"),
    hash_frames: bool = typer.Option(False, "--hash", help="звірити кадри хешем"),
    force: bool = typer.Option(False, "--force",
                               help="прийняти попри ворота або поверх наявних прогонів"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прийняти чужий пакет: прогони лягають туди ж, де своє прочитане."""
    from nyshporka import ops as O

    env = O.call("share.import", {"src": src, "hash_frames": hash_frames,
                                  "force": force})
    if _answer(env, as_json):
        return
    d = env.data or {}
    al = d.get("alignment") or {}
    console.print(f"прийнято: [bold]{d.get('shifra') or '—'}[/bold] · "
                  f"сторінок {d.get('pages')} · прогонів {len(d.get('runs') or [])}")
    console.print(f"прив'язка до кадрів: [bold]{al.get('label')}[/bold] — {al.get('why')}")
    if d.get("proof"):
        console.print(f"пакет збережено як доказ: {d['proof']}")
    console.print("[dim]щоб пошук побачив прийняте: nysh text index[/dim]")
    _notes(env)


@app.command("geometry")
def geometry_cmd(
    src: str = typer.Argument(..., help="пакет .geom.nyshtext або адреса"),
    force: bool = typer.Option(False, "--force",
                               help="перезаписати геометрію, яка вже лежить"),
    reindex: bool = typer.Option(True, "--index/--no-index",
                                 help="одразу перебудувати стор"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Докласти геометрію рядків до вже прийнятого тексту.

    Другий файл того самого внеску: рамки рядків на аркушах. Має сенс лише
    тому, у кого ті самі кадри — тоді кроп ріже саме той рядок.
    """
    from nyshporka import ops as O

    env = O.call("share.geometry", {"src": src, "force": force,
                                    "reindex": reindex})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"геометрія: [bold]{d.get('shifra') or '—'}[/bold] · "
                  f"сторінок {d.get('pages')} · прогонів {len(d.get('runs') or [])}")
    if d.get("indexed"):
        console.print(f"стор оновлено: {', '.join(d['indexed'])}")
    else:
        console.print("[dim]щоб кроп побачив рамки: nysh text index[/dim]")
    _notes(env)


@app.command("pull")
def pull_cmd(
    query: str = typer.Argument(..., help="шифра, номер справи або назва місця"),
    base: str = typer.Option("", "--base", help="інша адреса каталогу"),
    take: bool = typer.Option(False, "--take",
                              help="прийняти, якщо збіг рівно один"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Знайти справу в каталозі пулу — і за потреби одразу прийняти."""
    from nyshporka import ops as O

    _kliuch_abo_vkhid(as_json)
    env = O.call("share.pull", {"query": query, "base": base, "take": take})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"каталог: {d.get('catalog')} · пакетів {d.get('of')} · "
                  f"збігів [bold]{d.get('count')}[/bold]")
    for r in (d.get("found") or [])[:20]:
        console.print(f"  {r.get('shifra'):<24} {r.get('pages'):>6} стор. · "
                      f"{r.get('models') or '—'} · {r.get('publisher') or '—'}")
    if d.get("imported"):
        i = d["imported"]
        console.print(f"\nприйнято: [bold]{i.get('shifra')}[/bold] · "
                      f"прив'язка {(i.get('alignment') or {}).get('label')}")
    if d.get("geometry"):
        g = d["geometry"]
        console.print(f"геометрія: сторінок {g.get('pages')} · кроп готовий")
    _notes(env)


@app.command("list")
def list_cmd(
    mine: bool = typer.Option(False, "--mine", help="лише спаковане мною"),
    shared: bool = typer.Option(False, "--shared", help="лише прийняте"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Журнал обміну: що звідки прийшло і що куди пішло."""
    from nyshporka import ops as O

    what = "mine" if mine and not shared else "shared" if shared and not mine else "all"
    env = O.call("share.list", {"what": what})
    if _answer(env, as_json):
        return
    d = env.data or {}
    rows = d.get("rows") or []
    if not rows:
        console.print("журнал порожній — нічого ще не пакували й не приймали")
        _notes(env)
        return
    for r in rows[:40]:
        mark = {"pack": "→", "import": "←", "geometry": "◆"}.get(
            str(r.get("event") or ""), "·")
        who = r.get("publisher") or ""
        tail = f" від {who}" if who else ""
        console.print(f"{mark} {str(r.get('at'))[:16]}  {r.get('shifra') or '—':<24} "
                      f"{r.get('pages') or 0:>6} стор.{tail}")
    if len(rows) > 40:
        console.print(f"[dim]… і ще {len(rows) - 40}[/dim]")
    _notes(env)


@app.command("stats")
def stats_cmd(
    catalog: bool = typer.Option(False, "--catalog", help="ще й зведення по пулу"),
    base: str = typer.Option("", "--base", help="інша адреса каталогу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Хто що коли: обмін цієї машини, а з `--catalog` — і весь пул."""
    from nyshporka import ops as O

    env = O.call("share.stats", {"catalog": catalog, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    loc = d.get("local") or {}
    p, i = loc.get("packed") or {}, loc.get("imported") or {}
    console.print(f"спаковано: справ [bold]{p.get('cases', 0)}[/bold] · "
                  f"сторінок {p.get('pages', 0)} · {_mb(p.get('bytes', 0))}")
    console.print(f"прийнято:  справ [bold]{i.get('cases', 0)}[/bold] · "
                  f"сторінок {i.get('pages', 0)} · {_mb(i.get('bytes', 0))}")
    for row in loc.get("from") or []:
        console.print(f"  від {row['publisher']}: справ {row['cases']}")
    cat = d.get("catalog")
    if cat:
        console.print(f"\nпул ({d.get('catalog_url')}): справ [bold]{cat['cases']}[/bold] · "
                      f"сторінок {cat['pages']}")
        for row in (cat.get("publishers") or [])[:10]:
            console.print(f"  {row['publisher']:<20} справ {row['cases']:>4} · "
                          f"сторінок {row['pages']}")
        for row in (cat.get("fonds") or [])[:10]:
            console.print(f"  {row['fond']:<20} справ {row['cases']}")
    _notes(env)


@app.command("sync")
def sync_cmd(
    fond: str = typer.Option("", "--fond", help="лише цей фонд (швидше)"),
    repo: str = typer.Option("", "--repo", help="лише цей архів"),
    base: str = typer.Option("", "--base", help="інша адреса пулу"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зняти зріз пулу, щоб реєстр опису показував, що вже прочитано.

    🔴 Це ЄДИНЕ місце, яким зріз потрапляє на диск, і єдине, що ходить у мережу
    заради колонки «пул». Самі таблиці (`cases fond`, `cases opys`) читають уже
    знятий зріз і не роблять жодного запиту — на цьому стоїть обіцянка, що
    Нишпорка не має фонової мережевої активності.

    Зріз не оновлюється сам і не протухає: він лежить, доки не знімеш новий, а
    його вік показується всюди, де показується «є / немає в пулі».
    """
    from nyshporka.share import pool as P

    _kliuch_abo_vkhid(as_json)
    try:
        got = P.sync(base, repo=repo, fond=fond)
    except RuntimeError as exc:
        console.print(f"[err]зріз не знято:[/err] {exc}")
        console.print("[muted]наявний зріз лишився недоторканим[/muted]")
        raise typer.Exit(code=1) from exc
    if as_json:
        import json as _json

        typer.echo(_json.dumps(got, ensure_ascii=False, indent=1))
        return
    console.print(f"[ok]зріз пулу знято:[/ok] книг [bold]{got['of']}[/bold] "
                  f"· {got['scope']}")
    if got["via"] == "search":
        # Повільний шлях має називатись: інакше він виглядає як поломка.
        console.print("[muted]через пошук — сервер ще не знає /v1/keys[/muted]")
    console.print("[muted]колонка «пул» у `nysh cases fond` тепер має що "
                  "показувати[/muted]")


@app.command("row")
def row_cmd(
    path: str = typer.Argument(..., help="зібраний пакет"),
    url: str = typer.Option("", "--url", help="адреса, за якою пакет лежатиме"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Рядок каталогу для пулу — його й подають у репозиторій каталогу."""
    from nyshporka import ops as O

    env = O.call("share.row", {"path": path, "url": url})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"[dim]{d.get('header')}[/dim]")
    console.print(d.get("row") or "")
    _notes(env)
