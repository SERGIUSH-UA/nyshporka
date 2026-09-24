"""`nysh share` — обмін прочитаним: спакувати своє, прийняти чуже.

Одну книгу сьогодні розпізнає кожен окремо, і текст, який у сусіда вже лежить,
щоразу купують заново — годинами машинного часу. Пакет тут коштує кілька
мегабайтів на справу: їде текст рушія й паспорт того, як його отримали.

🔴 Усе, що друкується тут, крім наших власних слів, — дані від сторонніх
людей: псевдоніми, нотатки, назви справ, рядки каталогу. Вони йдуть у друк
лише через `_e` (екранування розмітки rich).
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Обмін прочитаним (Супряга): спакувати свій декод, прийняти чужий.",
                  no_args_is_help=True)
console = brand.console()


def _e(value: Any) -> str:
    """Чужий текст для друку через rich — з екранованою розміткою.

    🔴 Псевдонім, нотатка, назва справи й рядки каталогу приходять від
    сторонніх людей. Без екранування `[/i]` у псевдонімі валив `share pull`
    і `share list` у кожного, чий пошук знаходив цей пакет (`MarkupError`),
    `[link=…]` ховав справжню адресу, а `[sic]` у назві просто зникав.
    """
    from rich.markup import escape

    return escape(str(value if value is not None else ""))


def _mb(n: int) -> str:
    n = int(n or 0)
    if n < 1_000_000:
        return f"{n / 1e3:.0f} КБ"
    return f"{n / 1e6:.1f} МБ" if n < 2e9 else f"{n / 1e9:.2f} ГБ"


def _show_gates(g: dict[str, Any]) -> None:
    for w in g.get("warnings") or []:
        console.print(f"  [warn]⚠ {_e(w.get('text'))}[/warn]")
    for r in g.get("refusals") or []:
        console.print(f"  [bad]✗ {_e(r)}[/bad]")


def _show_card(card: dict[str, Any], indent: str = "  ") -> None:
    if not card:
        return
    if card.get("title"):
        console.print(f"{indent}назва: {_e(card['title'])}")
    if card.get("years"):
        y = card["years"]
        console.print(f"{indent}роки: {_e(y[0] if y[0] == y[-1] else f'{y[0]}–{y[-1]}')}")
    if card.get("places"):
        console.print(f"{indent}місця: {_e('; '.join(card['places']))}")
    if card.get("doc_type"):
        console.print(f"{indent}жанр: {_e(card['doc_type'])}")


# Прапорці картки однакові в `pack`, `suggest` і `card` — одна довідка.
_TITLE_HELP = "назва справи для картки в пулі (запам'ятовується для наступних пакувань)"
_YEARS_HELP = "роки справи: «1795» або «1795-1797»"
_PLACE_HELP = "місце, яке охоплює справа (можна кілька разів)"
_GENRE_HELP = "жанр: birth, marriage, death, confession, revision, clergy_list, other…"


def _card_args(title: str | None, years: str | None, place: list[str] | None,
               genre: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if title is not None:
        out["title"] = title
    if years is not None:
        out["years"] = years
    if place:
        out["place"] = list(place)
    if genre is not None:
        out["genre"] = genre
    return out


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
    contact: str = typer.Option("", "--contact",
                                help="як із вами зв'язатись (публічно); без "
                                     "прапорця — з профілю, «-» — не вказувати"),
    site: str = typer.Option("", "--site", help="сторінка автора"),
    note: str = typer.Option("", "--note", help="вільна нотатка до пакета"),
    link: list[str] = typer.Option([], "--link", help="«підпис=адреса» або голе посилання"),
    extra: list[str] = typer.Option([], "--extra", help="«ключ=значення»"),
    license_: str = typer.Option("", "--license",
                                 help="ліцензія тексту; порожньо — з профілю"),
    source_terms: str = typer.Option("", "--source-terms",
                                     help="умови джерела сканів"),
    archive_name: str = typer.Option("", "--archive-name",
                                     help="повна назва архіву, якщо його немає "
                                          "в довіднику (шифра тоді — латинським "
                                          "кодом: KOD/фонд-опис/справа)"),
    title: str | None = typer.Option(None, "--title", help=_TITLE_HELP),
    years: str | None = typer.Option(None, "--years", help=_YEARS_HELP),
    place: list[str] = typer.Option([], "--place", help=_PLACE_HELP),
    genre: str | None = typer.Option(None, "--genre", help=_GENRE_HELP),
    skip_run: list[str] = typer.Option([], "--skip-run",
                                       help="прогін, який НЕ пакувати (можна кілька)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Зібрати пакет прочитаного для обміну.

    Перед першою публікацією варто прогнати `--dry-run`: він друкує точний
    перелік файлів, які поїдуть, і маніфест — усе, що побачить сторонній.
    Назву, роки, місця й жанр картки можна задати тут же (`--title` …); вони
    запам'ятовуються й діють на всі наступні пакування цієї справи.
    """
    from nyshporka import ops as O

    env = O.call("share.pack", {
        "case": case, "out": out, "geometry": geometry,
        "hash_frames": hash_frames, "partial": partial, "dry_run": dry_run,
        "publisher": publisher, "contact": contact, "site": site, "note": note,
        "link": list(link), "extra": list(extra), "license": license_,
        "source_terms": source_terms, "archive_name": archive_name,
        "skip_run": list(skip_run), **_card_args(title, years, place, genre)})
    if _answer(env, as_json):
        return
    d = env.data or {}
    m = d.get("manifest") or {}
    dec = m.get("decode") or {}
    mcase = m.get("case") or {}
    console.print(f"справа: [bold]{_e(mcase.get('shifra') or '—')}[/bold] · "
                  f"прогонів {len(d.get('runs') or [])} · сторінок {_e(dec.get('pages'))} · "
                  f"рядків {_e(dec.get('lines'))}")
    if mcase.get("title"):
        console.print(f"  назва в картці: {_e(mcase['title'])}")
    for s in d.get("skipped_runs") or []:
        console.print(f"  [muted]не їде: {_e(s.get('run'))} — {_e(s.get('why'))}[/muted]")
    _show_gates(d.get("gates") or {})
    if d.get("dry_run"):
        console.print(f"поїхало б: файлів {d['files']} · {_mb(d['bytes_raw'])} до стиску")
        for arc in (d.get("files_list") or [])[:12]:
            console.print(f"  {_e(arc)}")
        rest = len(d.get("files_list") or []) - 12
        if rest > 0:
            console.print(f"  … і ще {rest}")
        if d.get("geom_files_list"):
            console.print(f"  + геометрія окремим файлом: "
                          f"{len(d['geom_files_list'])} · "
                          f"{_mb(d.get('geom_bytes_raw') or 0)} до стиску")
        console.print("[dim]нічого не записано (--dry-run)[/dim]")
    else:
        console.print(f"пакет: [bold]{_e(d['path'])}[/bold] · {_mb(d['bytes'])} · "
                      f"sha256 {d['sha256'][:16]}…")
        geom = d.get("geom")
        if geom:
            console.print(f"геометрія: [bold]{_e(geom['path'])}[/bold] · "
                          f"{_mb(geom['bytes'])}")
        elif d.get("geometry_on_disk"):
            console.print("[dim]геометрія на диску є, але не пакувалась "
                          "(--no-geometry)[/dim]")
        if d.get("card_saved"):
            console.print("[dim]картку запам'ятовано для наступних пакувань "
                          "(nysh share card)[/dim]")
        console.print("\n[dim]віддати: nysh share publish <файл>[/dim]")
    _notes(env)


@app.command("card")
def card_cmd(
    case: str = typer.Argument(..., help="шифра або ключ справи"),
    title: str | None = typer.Option(None, "--title", help=_TITLE_HELP),
    years: str | None = typer.Option(None, "--years", help=_YEARS_HELP),
    place: list[str] = typer.Option([], "--place", help=_PLACE_HELP),
    genre: str | None = typer.Option(None, "--genre", help=_GENRE_HELP),
    clear: bool = typer.Option(False, "--clear", help="прибрати картку цілком"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Картка справи для пулу: назва, роки, місця, жанр — задані вами.

    Без прапорців — показати, що задано. Порожнє значення (`--title ""`)
    стирає одне поле, `--clear` — усю картку. Задане діє на кожне наступне
    пакування: `pack`, `suggest --all`, автовіддачу після прогону.
    """
    from nyshporka import ops as O

    env = O.call("share.card", {"case": case, "clear": clear,
                                **_card_args(title, years, place, genre)})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"справа: [bold]{_e(d.get('shifra') or d.get('case_key'))}[/bold]")
    if d.get("card"):
        _show_card(d["card"])
    else:
        console.print("  [muted]картки немає — назву й решту пакувальник бере з "
                      "паспорта теки й реєстру опису[/muted]")
    _notes(env)


@app.command("setup")
def setup_cmd(
    as_who: str = typer.Option("", "--as", help="ваше ім'я або псевдонім"),
    contact: str = typer.Option("", "--contact",
                                help="як із вами зв'язатись (публічні дані); «-» — прибрати"),
    site: str = typer.Option("", "--site", help="сторінка автора; «-» — прибрати"),
    license_: str = typer.Option("", "--license", help="ліцензія тексту"),
    consent: str = typer.Option("", "--consent", help="nikoly | zavzhdy | pytaty"),
    lookup: bool | None = typer.Option(None, "--lookup/--no-lookup",
                                       help="питати пул перед прогоном (шле шифру "
                                            "справи; типово — ні)"),
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
    import sys

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

    # 🔴 Питання ставляться лише в діалозі й лише коли людина не задала
    # НІЧОГО. Будь-який прапорець — включно з `--no-lookup` і `--json` —
    # означає «зроби це й не питай»: доти `setup --no-lookup` у скрипті
    # закінчувався `Aborted`, і налаштування не зберігалось.
    zadano = any([as_who, contact, site, license_, consent]) or \
        lookup is not None or geometry is not None
    if not (show or yes or as_json or zadano) and sys.stdin.isatty():
        bulo = P.load()
        console.print("[dim]Порожні відповіді лишають те, що вже стоїть; "
                      "«-» прибирає поле.[/dim]")
        args["handle"] = typer.prompt("Ім'я або псевдонім", default=bulo.handle or "")
        args["contact"] = typer.prompt(
            "Контакт (публічні дані; «-» — не вказувати)",
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
        args["lookup"] = typer.confirm(
            "Питати пул перед кожним прогоном, чи справу вже прочитали? "
            "(сервер бачитиме шифру справи)", default=bulo.lookup)
    elif not (show or yes or as_json or zadano):
        args["show"] = True

    env = O.call("share.setup", args)
    if _answer(env, as_json):
        return
    d = env.data or {}
    prof = d.get("profile") or {}
    console.print(f"профіль: [bold]{_e(d.get('path'))}[/bold]")
    console.print(f"  ім'я: {_e(prof.get('handle')) or '[dim]без імені[/dim]'}"
                  f" · ліцензія: {_e(prof.get('license'))}")
    console.print(f"  контакт: {_e(prof.get('contact')) or '[dim]не вказано[/dim]'}")
    console.print(f"  згода: [bold]{_e(prof.get('consent'))}[/bold] — {_e(d.get('consent_text'))}")
    console.print(f"  питати пул перед прогоном: {'так' if prof.get('lookup') else 'ні'}"
                  f" · геометрія: {'так' if prof.get('geometry') else 'ні'}")
    _notes(env)


@app.command("suggest")
def suggest_cmd(
    take: str = typer.Argument("", help="шифра справи — віддати саме її"),
    skip: str = typer.Option("", "--skip", help="більше не питати про цю справу"),
    why: str = typer.Option("", "--why", help="чому не віддаєте"),
    all_: bool = typer.Option(False, "--all", help="спакувати все з переліку"),
    ready: bool = typer.Option(False, "--ready",
                               help="лише готові до віддачі й ті, де в пулі бракує "
                                    "рамок (разом із --all пакує лише їх)"),
    title: str | None = typer.Option(None, "--title",
                                     help=_TITLE_HELP + " — лише разом зі справою"),
    years: str | None = typer.Option(None, "--years", help=_YEARS_HELP),
    place: list[str] = typer.Option([], "--place", help=_PLACE_HELP),
    genre: str | None = typer.Option(None, "--genre", help=_GENRE_HELP),
    limit: int = typer.Option(30, "--limit", help="скільки рядків показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що прочитано, але ще не віддано.

    Без аргументів — перелік зі статусами: готова, у пулі без рамок,
    неповна, без кадрів. Що вже віддано, вирішує зріз пулу
    (`nysh share sync`); без зрізу — журнал пакувань. `--all` пакує все;
    далі кожен пакет віддається командою `publish`.
    """
    from nyshporka import ops as O

    env = O.call("share.suggest",
                 {"take": take, "skip": skip, "why": why, "all": all_, "ready": ready,
                  **_card_args(title, years, place, genre)})
    if _answer(env, as_json):
        return
    d = env.data or {}
    rows = d.get("rows") or []
    if skip:
        console.print(f"більше не питаю про «{_e(skip)}» · лишилось {d.get('left')}")
        _notes(env)
        return
    if not rows:
        # 🔴 «Нічого не лишилось» — не те саме, що «усе в Супрязі»: справа
        # могла бути лише спакована локально або відкладена відмовою.
        console.print("неподіленого не лишилось: усе прочитане або віддане, або "
                      "спаковане, або ви відмовились його віддавати "
                      "([dim]nysh share list[/dim])")
        _notes(env)
        return

    zriz = d.get("pool_snapshot")
    pidsumok = " · ".join(f"{k} {v}" for k, v in (d.get("summary") or {}).items() if v)
    console.print(f"[bold]{len(rows)}[/bold] прочитаних справ ще не в Супрязі · {pidsumok}")
    console.print("[dim]" + (f"звірено зі зрізом пулу від {_e(zriz)}" if zriz else
                             "зрізу пулу немає — звірено лише з журналом пакувань; "
                             "точніше: nysh share sync") + "[/dim]\n")
    from nyshporka.share.suggest import READY_STATUSES

    shown = [r for r in rows if not ready or r.get("status") in READY_STATUSES]
    for r in shown[:limit]:
        console.print(f"  {_e(r.get('status', '')):<17} "
                      f"{_e(r['shifra'] or r['case_key']):<28} "
                      f"{r['pages']:>5}/{r['frames'] or '—':<5} · {_e(r['model'] or '—')}")
        if r.get("title"):
            console.print(f"  {'':<17} [dim]{_e(r['title'])}[/dim]")
    if len(shown) > limit:
        console.print(f"[dim]… і ще {len(shown) - limit} (--limit N)[/dim]")

    packed = d.get("packed") or []
    if packed:
        console.print(f"\nспаковано: [bold]{len(packed)}[/bold]")
        for row in packed:
            console.print(f"  {_e(row['path'])}")
        console.print("\n[dim]віддати: nysh share publish <файл>[/dim]")
    else:
        console.print("\n[dim]спакувати все: nysh share suggest --all[/dim]")
        console.print("[dim]назва для картки: nysh share card <шифра> --title …[/dim]")
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
    from nyshporka.share.upload import OUTCOME_TEXT, VIDDANO, VZHE_Ye

    _kliuch_abo_vkhid(as_json)
    env = O.call("share.publish", {"path": path, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    vyhid = str(d.get("outcome") or "")
    if d.get("geometry_attached"):
        console.print(f"текст уже в Супрязі — [bold]дозалито геометрію[/bold] "
                      f"до внеску {_e(d.get('contribution'))}")
    elif vyhid == VIDDANO:
        console.print(f"внесок [bold]{_e(d.get('contribution'))}[/bold] · "
                      f"книга {_e(d.get('shifra') or d.get('book'))}")
        if d.get("text"):
            console.print(_e(d["text"]))
    elif vyhid == VZHE_Ye:
        console.print(f"[muted]{OUTCOME_TEXT[vyhid]}[/muted] — нічого не заливалось")
    else:
        console.print(f"[warn]{OUTCOME_TEXT.get(vyhid, vyhid)}[/warn]")
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
        console.print(f"  {_e(url)}")
        console.print("[dim]Чекаю на вхід… (Ctrl+C — скасувати)[/dim]")

    try:
        L.login(site=base_site, open_browser=open_browser, on_url=_pokazaty)
    except UploadError as exc:
        console.print(f"[bad]✗ {_e(exc)}[/bad]")
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
        console.print(f"[bad]✗ {_e(exc)}[/bad]")
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
    console.print(f"[bold]{_e(d.get('shifra') or '—')}[/bold] · сторінок {_e(d.get('pages'))} "
                  f"з {_e(d.get('frames') or '?')} кадрів · "
                  f"{_e(', '.join(str(x) for x in d.get('models') or []))}")
    pub = d.get("publisher") or {}
    if pub:
        who = pub.get("handle") or "без імені"
        contact = f" · {pub['contact']}" if pub.get("contact") else ""
        console.print(f"зібрав: {_e(who)}{_e(contact)}")
    al = d.get("alignment") or {}
    console.print(f"прив'язка: [bold]{_e(al.get('label'))}[/bold] — {_e(al.get('why'))}")
    _show_gates(d.get("gates") or {})
    for r in d.get("refs") or []:
        console.print(f"  джерело: {_e(r.get('source'))} {_e(r.get('ref'))} "
                      f"{_e(r.get('url') or '')}")
    for x in d.get("links") or []:
        console.print(f"  посилання: {_e(x.get('label') or '')} {_e(x.get('url') or '')}")
    if d.get("note"):
        # 🔴 Нотатка чужа. Відбивається як цитата й ніколи не зливається з
        # нашими підказками: її писала стороння людина, а читає часто агент.
        console.print("\n[dim]нотатка автора пакета (сторонній текст):[/dim]")
        for line in str(d["note"]).splitlines():
            console.print(f"  │ {_e(line)}")
    _notes(env)


@app.command("import")
def import_cmd(
    src: str = typer.Argument(..., help="файл пакета або адреса"),
    hash_frames: bool = typer.Option(False, "--hash", help="звірити кадри хешем"),
    force: bool = typer.Option(False, "--force",
                               help="прийняти попри ворота або замінити раніше "
                                    "прийнятий пакет (своє прочитання не "
                                    "перезаписується ніколи)"),
    sha256: str = typer.Option("", "--sha256",
                               help="очікуваний sha256 (з рядка каталогу): "
                                    "підмінений файл не приймається"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прийняти чужий пакет: прогони лягають туди ж, де своє прочитане."""
    from nyshporka import ops as O

    env = O.call("share.import", {"src": src, "hash_frames": hash_frames,
                                  "force": force, "sha256": sha256})
    if _answer(env, as_json):
        return
    d = env.data or {}
    al = d.get("alignment") or {}
    console.print(f"прийнято: [bold]{_e(d.get('shifra') or '—')}[/bold] · "
                  f"сторінок {_e(d.get('pages'))} · прогонів {len(d.get('runs') or [])}")
    console.print(f"прив'язка до кадрів: [bold]{_e(al.get('label'))}[/bold] — "
                  f"{_e(al.get('why'))}")
    if d.get("proof"):
        console.print(f"пакет збережено як доказ: {_e(d['proof'])}")
    console.print("[dim]щоб пошук побачив прийняте: nysh text index[/dim]")
    _notes(env)


@app.command("geometry")
def geometry_cmd(
    src: str = typer.Argument(..., help="пакет .geom.nyshtext або адреса"),
    force: bool = typer.Option(False, "--force",
                               help="перезаписати наявну геометрію або покласти її "
                                    "попри неточну прив'язку кадрів"),
    reindex: bool = typer.Option(True, "--index/--no-index",
                                 help="одразу перебудувати стор"),
    sha256: str = typer.Option("", "--sha256", help="очікуваний sha256 пакета"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Докласти геометрію рядків до вже прийнятого тексту.

    Другий файл того самого внеску: рамки рядків на аркушах. Має сенс лише
    тому, у кого ті самі кадри — тоді кроп ріже саме той рядок.
    """
    from nyshporka import ops as O

    env = O.call("share.geometry", {"src": src, "force": force,
                                    "reindex": reindex, "sha256": sha256})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"геометрія: [bold]{_e(d.get('shifra') or '—')}[/bold] · "
                  f"сторінок {_e(d.get('pages'))} · прогонів {len(d.get('runs') or [])}")
    if d.get("indexed"):
        console.print(f"стор оновлено: {_e(', '.join(d['indexed']))}")
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
    console.print(f"каталог: {_e(d.get('catalog'))} · пакетів {_e(d.get('of'))} · "
                  f"збігів [bold]{_e(d.get('count'))}[/bold]")
    for r in (d.get("found") or [])[:20]:
        console.print(f"  {_e(r.get('shifra')):<24} {_e(r.get('pages')):>6} стор. · "
                      f"{_e(r.get('models') or '—')} · {_e(r.get('publisher') or '—')}")
    if d.get("imported"):
        i = d["imported"]
        console.print(f"\nприйнято: [bold]{_e(i.get('shifra'))}[/bold] · "
                      f"прив'язка {_e((i.get('alignment') or {}).get('label'))}")
    if d.get("geometry"):
        g = d["geometry"]
        console.print(f"геометрія: сторінок {_e(g.get('pages'))} · кроп готовий")
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
        tail = f" від {_e(who)}" if who else ""
        console.print(f"{mark} {_e(str(r.get('at'))[:16])}  "
                      f"{_e(r.get('shifra') or '—'):<24} "
                      f"{_e(r.get('pages') or 0):>6} стор.{tail}")
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
        console.print(f"  від {_e(row['publisher'])}: справ {row['cases']}")
    cat = d.get("catalog")
    if cat:
        console.print(f"\nпул ({_e(d.get('catalog_url'))}): справ "
                      f"[bold]{_e(cat.get('cases'))}[/bold] · сторінок {_e(cat.get('pages'))}")
        for row in (cat.get("publishers") or [])[:10]:
            console.print(f"  {_e(row.get('publisher')):<20} справ {_e(row.get('cases')):>4} · "
                          f"сторінок {_e(row.get('pages'))}")
        for row in (cat.get("fonds") or [])[:10]:
            console.print(f"  {_e(row.get('fond')):<20} справ {_e(row.get('cases'))}")
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

    Зріз одного фонду (`--fond`, `--repo`) дописується до наявного, а не
    замінює його: решта фондів лишається такою, як була знята.
    """
    from nyshporka import ops as O

    _kliuch_abo_vkhid(as_json)
    env = O.call("share.sync", {"fond": fond, "repo": repo, "base": base})
    if as_json:
        _answer(env, as_json)
        return
    if not env.ok:
        console.print(f"[err]зріз не знято:[/err] {_e(env.error)}")
        console.print("[muted]наявний зріз лишився недоторканим[/muted]")
        raise typer.Exit(code=1)
    got = env.data or {}
    console.print(f"[ok]зріз пулу знято:[/ok] книг [bold]{got['of']}[/bold] "
                  f"· {_e(got['scope'])} · у зрізі всього {got.get('total', got['of'])}")
    if got["via"] == "search":
        # Повільний шлях має називатись: інакше він виглядає як поломка.
        console.print("[muted]через пошук — сервер ще не знає /keys[/muted]")
    console.print("[muted]колонка «пул» у `nysh cases fond` тепер має що "
                  "показувати[/muted]")
    _notes(env)


@app.command("row")
def row_cmd(
    path: str = typer.Argument(..., help="зібраний пакет"),
    url: str = typer.Option("", "--url", help="адреса, за якою пакет лежатиме"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Рядок каталогу для пулу — для свого дзеркала чи офлайн-копії."""
    from nyshporka import ops as O

    env = O.call("share.row", {"path": path, "url": url})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"[dim]{_e(d.get('header'))}[/dim]")
    console.print(_e(d.get("row") or ""))
    _notes(env)
