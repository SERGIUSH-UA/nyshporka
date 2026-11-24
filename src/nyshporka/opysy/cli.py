"""`nysh opys` — описи фондів: перевірити й спакувати опис для Супряги.

🔴 Монтується в `nysh` лише з увімкненим флагом `NYSH_OPYSY`
(`nyshporka.features`); без нього команди немає взагалі.

🔴 Назви справ і рядки опису — чужий текст: у друк лише через `untrusted`.
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import untrusted

app = typer.Typer(help="Описи фондів (Супряга): перевірити й спакувати опис.",
                  no_args_is_help=True)
console = brand.console()


def _e(value: Any) -> str:
    return untrusted(value)


def _print_verdict(d: dict[str, Any]) -> None:
    s = d.get("summary") or {}
    if s:
        console.print(f"сторінок прочитано [bold]{_e(s.get('pages_read'))}[/bold] з "
                      f"{_e(s.get('pages_total'))} · справ {_e(s.get('rows'))}, "
                      f"нормалізовано {_e(s.get('rows_normalized'))} · "
                      f"№: {_e(s.get('no_status'))}")
    v = d.get("verdict") or {}
    for r in v.get("refusals") or []:
        console.print(f"[red]✗[/red] {_e(r)}")
    for w in v.get("warnings") or []:
        console.print(f"[yellow]•[/yellow] {_e(w.get('text'))}")
    if v.get("passed"):
        console.print("[green]ворота пройдено[/green]")


@app.command("check")
def check_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Перевірити робочу теку опису воротами Супряги, нічого не пакуючи."""
    from nyshporka import ops as O

    env = O.call("opysy.check", {"dir": folder})
    if _answer(env, as_json):
        return
    _print_verdict(env.data or {})


@app.command("pack")
def pack_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    out: str = typer.Option(..., "--out", help="файл .nyshopys або тека для нього"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Спакувати опис у `.nyshopys` — лише якщо ворота пропускають."""
    from nyshporka import ops as O

    env = O.call("opysy.pack", {"dir": folder, "out": out})
    if _answer(env, as_json):
        return
    d = env.data or {}
    _print_verdict(d)
    if d.get("file"):
        console.print(f"пакет: {_e(d['file'])} · {_e(d.get('bytes'))} байт · "
                      f"sha256 {_e(str(d.get('sha256'))[:16])}…")


@app.command("policy")
def policy_cmd(
    repo: str = typer.Argument(..., help="архів: ЦДІАК, ДАОО…"),
    fond: str = typer.Argument(..., help="фонд"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чи приймає Супряга описи цього фонду — до прогону."""
    from nyshporka import ops as O

    env = O.call("opysy.policy", {"repo": repo, "fond": fond})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if d.get("open"):
        console.print(f"{_e(d.get('repo'))} ф.{_e(d.get('fond'))}: описи приймаються")
    else:
        console.print(f"[red]{_e(d.get('repo'))} ф.{_e(d.get('fond'))}[/red]: {_e(d.get('why'))}")


@app.command("push")
def push_cmd(
    file: str = typer.Argument(..., help="робоча тека опису (`nysh opys read`) або пакет .nyshopys"),
    norm_model: str = typer.Option("", "--norm-model",
                                   help="модель, що нормалізувала назви (один раз; далі пам'ятається)"),
    znovu: bool = typer.Option(False, "--znovu", help="залити, навіть якщо цей самий пакет уже залито"),
    na_obmin: bool = typer.Option(False, "--na-obmin",
                                  help="віддати нормалізацію назв на обмін: опис приймається без неї"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Віддати опис у Супрягу. Тека — усе за раз: відповіді нормалізації, пакет, ворота, заливка."""
    from nyshporka import ops as O

    env = O.call("opysy.push", {"file": file, "norm_model": norm_model, "znovu": znovu,
                                "na_obmin": na_obmin, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    s = d.get("summary") or {}
    if d.get("duplicate"):
        console.print(f"{_e(d.get('shyfra'))}: той самий пакет уже в Супрязі "
                      f"(внесок {_e(d.get('vnesok'))})" + (f" — {_e(d['text'])}" if d.get("text") else ""))
        return
    console.print(f"[green]прийнято[/green] {_e(d.get('shyfra'))} · внесок {_e(d.get('vnesok'))} · "
                  f"сторінок {_e(s.get('pages_read'))}/{_e(s.get('pages_total'))} · "
                  f"справ {_e(s.get('rows'))}")
    for w in d.get("warnings") or []:
        console.print(f"[yellow]•[/yellow] {_e(w.get('text'))}")


@app.command("search")
def search_cmd(
    q: list[str] = typer.Argument(..., help="що шукати"),
    repo: str = typer.Option("", "--repo", help="лише в цьому архіві"),
    fond: str = typer.Option("", "--fond", help="лише в цьому фонді"),
    limit: int = typer.Option(50, "--limit", help="скільки збігів показати"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Нечіткий пошук по описах фондів у Супрязі: справа, сторінка, посилання на скан."""
    from nyshporka import ops as O

    env = O.call("opysy.search", {"q": " ".join(q), "repo": repo, "fond": fond,
                                  "limit": limit, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    zbihy = d.get("zbihy")
    if zbihy is None:
        console.print(f"збігів {_skilky(d)}: "
                      + ", ".join(f"{_e(k)} — {_e(v)}" for k, v in (d.get("za_opysamy") or {}).items()))
        _nepovno(d)
        console.print(_e(d.get("uviity") or ""))
        return
    if not zbihy:
        _nepovno(d)
        bez = d.get("bez_zbihu") or []
        if bez:
            console.print(f"у описах Супряги не знайшлось (немає ніде: {_e(', '.join(bez))})")
        elif len(" ".join(q).split()) > 1:
            # Кожне слово десь є, але не разом: голе «не знайшлось» тут збрехало б, що
            # слів немає, і людина закрила б напрям (перевірка на проді 22.11.2026).
            console.print("у описах Супряги кожне слово трапляється, але не разом на одній "
                          "сторінці чи в одній справі — спробуйте слова окремо")
        else:
            console.print("у описах Супряги не знайшлось")
        return
    console.print(f"збігів {_skilky(d)} · сторінка {_e(d.get('storinka'))} з {_e(d.get('storinok'))}")
    _nepovno(d)
    for z in zbihy:
        mistse = f"кадр {_e(z.get('page'))}" + (
            "" if z.get("half") is None else (", ліва" if z.get("half") == 0 else ", права"))
        if z.get("riadok"):
            no = f"№ {_e(z.get('no'))}{_e(z.get('letter'))}" if z.get("no") is not None else "№ ?"
            zvir = " (звірити №)" if z.get("no_status") == "unconfirmed" else ""
            if z.get("no_span"):
                zvir = f" (рядок охоплює №{_e(z.get('no_span'))} — звірте номер)"
            nazva = z.get("title_norm") or z.get("title_raw")
            console.print(f"[bold]{_e(z.get('shyfra'))}[/bold] {no}{zvir} — {_e(nazva)}")
        else:
            console.print(f"[bold]{_e(z.get('shyfra'))}[/bold] — збіг у тексті сторінки")
        console.print(f"   {mistse} · {_e(z.get('posylannia'))}")
        for p in z.get("pravyla") or []:
            console.print(f"   [dim]за правилом: {_e(p)}[/dim]")
    inshi = d.get("inshi_chytannia") or {}
    if inshi:
        # Опис у видачі — одним читанням (найсвіжішим зі збігом); інші читання того самого
        # опису теж мають збіг, і людина має знати, що їх можна відкрити на картці опису.
        console.print("ще в інших читаннях того самого опису: "
                      + ", ".join(f"{_e(k)} — {_e(v)}" for k, v in inshi.items()))


def _skilky(d: dict[str, Any]) -> str:
    """Скільки збігів. Понад стелю сервер рахує лише перші знайдені, тож число — «понад N»,
    а не точне (1000 на частому слові читалось як «рівно тисяча»)."""
    if d.get("nepovno"):
        return f"понад {_e(d.get('stelia'))}"
    return _e(d.get("zbihiv"))


def _nepovno(d: dict[str, Any]) -> None:
    """Видача неповна: що саме неповне і що з цим робити. Плюс «ще індексується» — описи,
    яких пошук ще не бачить (індексація на сервері — у фоні після заливки)."""
    n = int(d.get("indeksuietsia") or 0)
    if n:
        console.print(f"[yellow]•[/yellow] ще індексується описів: {n} — їх у видачі немає, "
                      "повторіть пошук за хвилину")
    if not d.get("nepovno"):
        return
    de = d.get("nepovno_de")
    if de == "riadky":
        console.print("[yellow]•[/yellow] справ-збігів понад стелю: показано перші знайдені, а не "
                      "найближчі; видача не гортається, текст сторінок не шукався")
    elif de == "rozghortannia":
        console.print("[yellow]•[/yellow] коротке часте слово: узято лише найближчі написання, "
                      "далекі в видачу не ввійшли — обмежте --fond (у фонді пошук повний)")
    else:
        console.print("[yellow]•[/yellow] сторінок-збігів понад стелю: справи — усі, сторінки "
                      "не перелічено")
    chasti = d.get("chasti") or []
    if chasti:
        console.print(f"[yellow]•[/yellow] надто часті слова: {_e(', '.join(chasti))} — "
                      "уточніть запит (прізвище, село) або обмежте --repo / --fond")


@app.command("names")
def names_cmd(
    repo: str = typer.Argument(..., help="архів: ЦДІАК, ДАОО…"),
    fond: str = typer.Argument(..., help="фонд"),
    opys: str = typer.Option("", "--opys", help="лише цей опис"),
    q: str = typer.Option("", "--q", help="лише назви, що містять це"),
    page: int = typer.Option(1, "--page", help="сторінка словника"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Словник власних назв фонду: написання, сусіди-підказки, правило, rk для доказу."""
    from nyshporka import ops as O

    env = O.call("opysy.names", {"repo": repo, "fond": fond, "opys": opys, "q": q,
                                 "page": page, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"назв {_e(d.get('usioho'))} · сторінка {_e(d.get('storinka'))} з "
                  f"{_e(d.get('storinok'))}")
    for k in d.get("klastery") or []:
        napys = ", ".join(f"{_e(s)} ×{_e(n)}" for s, n in k.get("napysannia") or [])
        console.print(f"[bold]{_e(k.get('kliuch'))}[/bold] ({_e(k.get('usioho'))}): {napys}")
        if k.get("susidy"):
            console.print(f"   поруч: {_e(', '.join(k['susidy']))}")
        p = k.get("pravylo")
        if p:
            console.print(f"   правило №{_e(p.get('id'))} ({_e(p.get('stan'))}): "
                          f"{_e(', '.join(p.get('z') or []))} → {_e(p.get('na'))}")
        for x in k.get("pryklady") or []:
            console.print(f"   [dim]{_e(x.get('shyfra'))} № {_e(x.get('no'))} · кадр "
                          f"{_e(x.get('page'))} · rk {_e(x.get('rk'))}[/dim] "
                          f"{_e(x.get('title_norm'))}")


rule_app = typer.Typer(help="Правила підстановки власних назв в описах фонду.",
                       no_args_is_help=True)
app.add_typer(rule_app, name="rule")


def _print_rule(p: dict[str, Any]) -> None:
    mezha = f"{_e(p.get('repo'))} {_e(p.get('fond') or '*')}" + (
        f"-{_e(p.get('opys'))}" if p.get("opys") else "")
    # Стан — у круглих дужках: квадратні Rich читає як тег розмітки й мовчки ковтає
    # («[diie]» зникав із друку — живий прогін 23.11.2026).
    console.print(f"№{_e(p.get('id'))} ({_e(p.get('stan'))}) {mezha}: "
                  f"{_e(', '.join(p.get('z') or []))} → [bold]{_e(p.get('na'))}[/bold]")


@rule_app.command("add")
def rule_add_cmd(
    repo: str = typer.Argument(..., help="архів"),
    fond: str = typer.Argument(..., help="фонд"),
    variants: list[str] = typer.Option(..., "--from", help="спотворене написання (можна кілька)"),
    to: str = typer.Option(..., "--to", help="певне написання"),
    evidence: str = typer.Option(..., "--evidence", help="rk рядка з певним написанням"),
    opys: str = typer.Option("", "--opys", help="лише в цьому описі"),
    kind: str = typer.Option("prizvyshche", "--kind",
                             help="prizvyshche / mistse / posadovets / inshe"),
    reason: str = typer.Option("", "--reason", help="чому певно"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Звести варіанти до певного написання. Сирий текст не змінюється — лише пошук."""
    from nyshporka import ops as O

    env = O.call("opysy.rule_add", {"repo": repo, "fond": fond, "variants": variants, "to": to,
                                    "evidence": evidence, "opys": opys, "kind": kind,
                                    "reason": reason, "base": base})
    if _answer(env, as_json):
        return
    p = env.data or {}
    _print_rule(p)
    if p.get("stan") == "zapyt":
        console.print("[yellow]•[/yellow] у межі є чужі внески — правило чекає рішення")


@rule_app.command("list")
def rule_list_cmd(
    repo: str = typer.Argument(..., help="архів"),
    fond: str = typer.Argument("", help="фонд; порожньо — усі правила архіву"),
    state: str = typer.Option("", "--state", help="diie / zapyt / vidkhyleno / vidkocheno"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Правила підстановки фонду: що зведено, що чекає рішення."""
    from nyshporka import ops as O

    env = O.call("opysy.rules", {"repo": repo, "fond": fond, "state": state, "base": base})
    if _answer(env, as_json):
        return
    ps = (env.data or {}).get("pravyla") or []
    if not ps:
        console.print("правил немає")
    for p in ps:
        _print_rule(p)


@rule_app.command("undo")
def rule_undo_cmd(
    rule_id: int = typer.Argument(..., help="номер правила"),
    reason: str = typer.Option("", "--reason", help="чому скасовано"),
    base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Скасувати правило: пошук знову без нього (сирий текст і не змінювався)."""
    from nyshporka import ops as O

    env = O.call("opysy.rule_undo", {"id": rule_id, "reason": reason, "base": base})
    if _answer(env, as_json):
        return
    _print_rule(env.data or {})


# ── Читання опису: init → pages → (nysh read) → table → norm → build → pack → push ─────────


def _next(d: dict[str, Any]) -> None:
    if d.get("next"):
        console.print(f"далі: [bold]{_e(d['next'])}[/bold]")


@app.command("read")
def read_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису (повтор — продовжує з місця)"),
    pdf: str = typer.Option("", "--pdf", help="PDF опису — той самий файл, що опубліковано"),
    repo: str = typer.Option("", "--repo", help="архів: ЦДІАК, ДАОО…"),
    fond: str = typer.Option("", "--fond", help="фонд"),
    opys: str = typer.Option("", "--opys", help="номер опису"),
    url: str = typer.Option("", "--url", help="де файл опубліковано: сайт архіву чи Commons"),
    published: str = typer.Option("", "--published", help="оригінал за адресою (напр. djvu), "
                                                          "якщо PDF — перетворення"),
    title: str = typer.Option("", "--title", help="установа фонду (для нормалізації)"),
    years: str = typer.Option("", "--years", help="роки фонду (для нормалізації)"),
    language: str = typer.Option("", "--language", help="мова опису; порожньо — з тексту"),
    script: str = typer.Option("", "--script", help="latin / cyrillic; порожньо — як вирішить читання"),
    form: str = typer.Option("hand_ruled", "--form", help="hand_ruled (рукопис) · typed (машинопис)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Прочитати опис фонду одним кроком: паспорт, сторінки, читання, таблиця справ, пачки
    нормалізації. Перервалось — та сама команда продовжить."""
    from nyshporka import ops as O

    env = O.call("opysy.read", {"dir": folder, "pdf": pdf, "repo": repo, "fond": fond,
                                "opys": opys, "url": url, "published": published, "title": title,
                                "years": years, "language": language, "script": script,
                                "form": form})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"[green]прочитано[/green] {_e(d.get('dir'))} · сторінок {_e(d.get('storinok'))} · "
                  f"справ {_e(d.get('sprav'))} · номерів підтверджено "
                  f"{_e(d.get('pidtverdzheno_nomeriv'))} · пачок нормалізації "
                  f"{_e(d.get('pachok_normalizatsii'))}")
    if d.get("pachok_normalizatsii"):
        console.print(f"  [muted]{_e(d.get('how'))}[/muted]")
    _next(d)


@app.command("init")
def init_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису (буде створена)"),
    pdf: str = typer.Option(..., "--pdf", help="PDF опису — той самий файл, що опубліковано"),
    repo: str = typer.Option(..., "--repo", help="архів: ЦДІАК, ДАОО…"),
    fond: str = typer.Option(..., "--fond", help="фонд"),
    opys: str = typer.Option(..., "--opys", help="номер опису"),
    url: str = typer.Option(..., "--url", help="де файл опубліковано: сайт архіву чи Commons"),
    kind: str = typer.Option("", "--kind", help="commons / archive_site / public_other; "
                                                "порожньо — з адреси"),
    page_link: str = typer.Option("", "--page-link", help="шаблон посилання на сторінку з {page}"),
    title: str = typer.Option("", "--title", help="установа фонду (для нормалізації)"),
    years: str = typer.Option("", "--years", help="роки фонду (для нормалізації)"),
    language: str = typer.Option("", "--language", help="мова опису; порожньо — з тексту"),
    published: str = typer.Option("", "--published", help="оригінал за адресою (напр. djvu), "
                                                          "якщо PDF — перетворення"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Завести робочу теку опису: паспорт джерела (sha256 PDF, сторінки, адреса публікації)."""
    from nyshporka import ops as O

    env = O.call("opysy.init", {"dir": folder, "pdf": pdf, "repo": repo, "fond": fond,
                                "opys": opys, "url": url, "kind": kind, "page_link": page_link,
                                "title": title, "years": years, "language": language,
                                "published": published})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"тека {_e(d.get('dir'))} · сторінок {_e(d.get('pages'))} · "
                  f"джерело {_e((d.get('source') or {}).get('url'))}")
    _next(d)


@app.command("pages")
def pages_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    force: bool = typer.Option(False, "--force", help="перерендерити готові сторінки"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Сторінки опису з PDF у JPEG під читання цілими сторінками."""
    from nyshporka import ops as O

    env = O.call("opysy.pages", {"dir": folder, "force": force})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"сторінок {_e(d.get('pages'))} → {_e(d.get('dir'))}"
                  + (f" ({_e(d['skip'])})" if d.get("skip") else ""))
    _next(d)


@app.command("table")
def table_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    title_starts: bool = typer.Option(True, "--title-starts/--no-title-starts",
                                      help="початок справи ще й за словом «Дело», «Тоже»"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Таблиця справ опису з прочитаних цілих сторінок."""
    from nyshporka import ops as O

    env = O.call("opysy.table", {"dir": folder, "title_starts": title_starts})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"сторінок {_e(d.get('pages'))} (битих {_e(d.get('bad_pages'))}) · справ "
                  f"{_e(d.get('cases'))} · № прочитано {_e(d.get('read'))}, підтверджено "
                  f"{_e(d.get('confirmed'))} → {_e(d.get('file'))}")
    _next(d)


@app.command("norm")
def norm_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    collect: bool = typer.Option(False, "--collect", help="прийняти відповіді batch_NNN.out.txt"),
    language: str = typer.Option("", "--language", help="ru чи uk; порожньо — з паспорта"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Нормалізація назв: пачки запитів для агента або прийом його відповідей."""
    from nyshporka import ops as O

    env = O.call("opysy.norm", {"dir": folder, "collect": collect, "language": language})
    if _answer(env, as_json):
        return
    d = env.data or {}
    if collect:
        console.print(f"нормалізовано {_e(d.get('rows'))} назв → {_e(d.get('file'))}")
    else:
        console.print(f"пачок {_e(len(d.get('batches') or []))} у {_e(d.get('dir'))}")
        console.print(_e(d.get("how")))
    _next(d)


@app.command("build")
def build_cmd(
    folder: str = typer.Argument(..., help="робоча тека опису"),
    norm_model: str = typer.Option("", "--norm-model", help="модель, що нормалізувала назви"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Робоча тека пакета з прочитаного, таблиці й нормалізації — під `nysh opys pack`."""
    from nyshporka import ops as O

    env = O.call("opysy.build", {"dir": folder, "norm_model": norm_model})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"сторінок {_e(d.get('pages'))} · справ {_e(d.get('rows'))}, нормалізовано "
                  f"{_e(d.get('normalized'))} · голоси {_e(', '.join(d.get('engines') or []))} → "
                  f"{_e(d.get('dir'))}")
    _next(d)


# ── обмін нормалізацією ──────────────────────────────────────────────────────


@app.command("obmin")
def obmin_cmd(base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
              as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Описи, нормалізацію яких автори віддали на обмін: що чекає й що в роботі."""
    from nyshporka import ops as O

    env = O.call("opysy.obmin", {"base": base})
    if _answer(env, as_json):
        return
    for x in (env.data or {}).get("opysy") or []:
        console.print(f"{_e(x.get('shyfra'))} · справ {_e(x.get('spravy'))} · "
                      f"нормалізовано {_e(x.get('normalizovano'))} · {_e(x.get('stan'))} "
                      f"[muted](внесок {_e(x.get('vnesok'))})[/muted]")
    console.print("узяти: [bold]nysh opys vziaty <тека> [--vnesok N][/bold]")


@app.command("vziaty")
def vziaty_cmd(folder: str = typer.Argument(..., help="тека, куди покласти пачки запитів"),
               vnesok: int = typer.Option(0, "--vnesok", help="який опис (внесок); 0 — найстаріший"),
               base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
               as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Узяти опис на нормалізацію (48 год, повтор — продовження): тека з пачками для агента."""
    from nyshporka import ops as O

    env = O.call("opysy.vziaty", {"dir": folder, "vnesok": vnesok or None, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"узято {_e(d.get('shyfra'))} до {_e(d.get('do'))} · назв {_e(d.get('nazv'))} · "
                  f"пачок {_e(d.get('pachok'))}")
    console.print(f"  [muted]{_e(d.get('how'))}[/muted]")
    _next(d)


@app.command("viddaty")
def viddaty_cmd(folder: str = typer.Argument(..., help="тека, взята `nysh opys vziaty`"),
                model: str = typer.Option(..., "--model", help="модель, що нормалізувала"),
                base: str = typer.Option("", "--base", help="адреса пулу; порожньо — типова"),
                as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)")) -> None:
    """Віддати нормалізацію взятого опису: пачки з відповіддю; можна по ходу, кілька разів."""
    from nyshporka import ops as O

    env = O.call("opysy.viddaty", {"dir": folder, "model": model, "base": base})
    if _answer(env, as_json):
        return
    d = env.data or {}
    console.print(f"[green]прийнято[/green] {_e(d.get('pryiniato'))} назв · {_e(d.get('shyfra'))} "
                  f"нормалізовано {_e(d.get('normalizovano'))}/{_e(d.get('spravy'))} · "
                  f"{_e(d.get('stan'))} · пачок без відповіді {_e(d.get('pachok_bez_vidpovidi'))}")
    for p in d.get("poznachky") or []:
        console.print(f"[yellow]•[/yellow] {_e(p)}")
