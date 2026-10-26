"""CLI парафій: `nysh parish find | in-case | near | mentions`.

Той самий шар операцій, що живить браузер і агента, — щоб відповідь на «де
книги мого села» не стала двома різними переліками залежно від входу.

🔑 Домен цих команд — прив'язка справи до **парафії**, якої немає в описі.
Опис знає, що справа існує; покажчик знає, чия вона церква, — і саме тому
питання «чи є моє село в цій книзі повіту» тут коштує один запит, а не прогін.
"""
from __future__ import annotations

from typing import Any

import typer

from nyshporka import ops as O
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Парафії села й що всередині зведеної книги.",
                  no_args_is_help=True)


def _cases(rows: list[dict[str, Any]], limit: int) -> None:
    for r in rows[:limit] if limit else rows:
        mark = "🌐" if r.get("online") else "  "
        typer.echo(f"  {mark} {r.get('shifra', ''):<20} {r.get('years', ''):<12} "
                   f"{str(r.get('title') or '')[:66]}")
        if r.get("info"):
            typer.echo(f"       ⓘ {str(r['info'])[:96]}")
    if limit and len(rows) > limit:
        typer.echo(f"   … ще {len(rows) - limit} (усі — у --json)")


def _gazetteer_line(data: dict) -> None:  # type: ignore[type-arg]
    """Які форми назви прийшли з газетирів — або що газетирів немає."""
    extra = data.get("forms_from_gazetteer") or []
    if extra:
        typer.echo(f"   з газетирів: {', '.join(extra)}")
    elif not data.get("gazetteers"):
        typer.echo("   газетирів на машині немає — інших форм назви не додано "
                   "(`nysh catalog install`)")


def _rk_block(data: dict) -> None:  # type: ignore[type-arg]
    """РК-парафії зі складу сіл — або що пака немає."""
    from nyshporka.geog.rkparish import dekanat_label, gubernia_uk

    if data.get("rk_installed") is None:
        typer.echo("\n   Пак РК-парафій є, але не читається — до якого костелу ходило "
                   "село, не перевірено (`nysh catalog verify`)")
        return
    if not data.get("rk_installed"):
        typer.echo("\n   РК-парафій (склад сіл) на машині немає — до якого костелу "
                   "ходило село, не перевірено")
        return
    rows = data.get("rk_parishes") or []
    typer.echo(f"\n⛪ РК-парафії (склад сіл за таблицями укладача): {len(rows)}")
    for p in rows:
        mark = "" if p.get("score") == 100 else f" · збіг {p.get('score')}"
        typer.echo(f"  · {p.get('name')} — село «{p.get('village')}»{mark}")
        typer.echo(f"    деканат {dekanat_label(p.get('dekanat') or '') or '—'} · "
                   f"{gubernia_uk(p.get('gubernia') or '')} губ. · {p.get('url')}")
        # усі книги, без обрізки: рядок короткий, а відсортовані вони за роком —
        # обрізка з'їла б саме пізні роки
        for b in p.get("books") or []:
            what = b.get("shifra") or b.get("shifry") or f"[як у джерелі: {b.get('raw')}]"
            typer.echo(f"    {b.get('years', ''):<12} {b.get('archive', ''):<8} "
                       f"{what:<16} {b.get('types', '')}")


def _metric_rows(m: dict, limit: int) -> None:  # type: ignore[type-arg]
    """Записи покажчика метрик: місце, джерело, справи за типом, сусіди, нотатник."""
    from collections import OrderedDict

    from nyshporka.geog.metrics import compact, years_span

    rows = m.get("rows") or []
    for r in rows[:limit] if limit else rows:
        povit = r.get("povit") or ""
        if povit and not any(w in povit for w in ("р-н", "район", "пов", "округ")):
            povit = f"{povit} пов."
        place = r.get("place") or "—"
        if r.get("place_alt"):
            place += f" ({r['place_alt']})"
        where = ", ".join(x for x in (place, r.get("volost") and f"{r['volost']} вол.",
                                      povit, r.get("sotnya") and f"{r['sotnya']} сотні") if x)
        page = f", с. {r['page']}" if r.get("page") else ""
        typer.echo(f"\n  ▸ {r.get('archive') or '?'} · {r.get('how')} · {str(r.get('church') or '')[:110]}")
        typer.echo(f"    {where} · {r.get('gub') or ''} · {r.get('conf') or '?'} · "
                   f"{r.get('source') or r.get('vol')}{page}")
        if r.get("note"):
            typer.echo(f"    примітка: {str(r['note'])[:200]}")
        if r.get("attached"):
            typer.echo(f"    приписні: {', '.join(r['attached'])}")
        by_kind: OrderedDict[str, list] = OrderedDict()  # type: ignore[type-arg]
        for ref in r.get("refs") or []:
            by_kind.setdefault(" + ".join(ref.get("kinds") or []) or "?", []).append(ref)
        for kind, refs in by_kind.items():
            items = compact(refs)
            typer.echo(f"    {kind} ({years_span(refs)}, справ {len(items)}): "
                       + "; ".join(items[:12])
                       + (f"; … ще {len(items) - 12}" if len(items) > 12 else ""))
        if r.get("siblings"):
            typer.echo(f"    ті самі книги ведуть і: {'; '.join(r['siblings'])}")
        for n in r.get("case_notes") or []:
            typer.echo(f"    📝 {n['shifra']} [{n['kind']}]: {str(n['text'])[:220]}")
    if limit and len(rows) > limit:
        typer.echo(f"\n  … ще {len(rows) - limit} (`nysh parish metrics`)")


def _metrics_block(data: dict, limit: int = 0) -> None:  # type: ignore[type-arg]
    """Покажчик метрик за селом — або що пака немає."""
    if data.get("metrics_installed") is None:
        typer.echo("\n   Пак покажчика метрик є, але не читається — книги за "
                   "каталогами архівів не перевірено (`nysh catalog verify`)")
        return
    if not data.get("metrics_installed"):
        typer.echo("\n   Покажчика метрик (metrics) на машині немає — книги за "
                   "каталогами архівів не перевірено")
        return
    m = data.get("metrics") or {}
    rows = m.get("rows") or []
    typer.echo(f"\n📚 Покажчик метрик (каталоги архівів): {len(rows)}")
    _metric_rows(m, limit)


def _court_block(data: dict) -> None:  # type: ignore[type-arg]
    """Згадки села в гродських книгах XVII–XVIII ст. — або що пака немає."""
    if data.get("court_installed") is None:
        typer.echo("\n   Пак гродських книг є, але не читається — згадки села в "
                   "XVII–XVIII ст. не перевірено (`nysh catalog verify`)")
        return
    if not data.get("court_installed"):
        typer.echo("\n   Покажчиків гродських книг (courtbooks) на машині немає — "
                   "згадки села в XVII–XVIII ст. не перевірено")
        return
    rows = data.get("court_places") or []
    typer.echo(f"\n📜 Гродські книги XVII–XVIII ст. (покажчик М. Коваля): {len(rows)}")
    for r in rows:
        mark = "" if r.get("score") == 100 else f" · збіг {r.get('score')}"
        sig = r.get("sig") or ""
        where = (f"ЦДІАК {sig}" if r.get("book_kind") != "lost"
                 else f"{sig} (загублена, за описом)")
        typer.echo(f"  · {r.get('name')}{mark} — {where} · {r.get('book_years') or ''}")
        if r.get("descr"):
            typer.echo(f"    {str(r['descr'])[:160]}")
        links = r.get("act_links") or []
        with_url = [x for x in links if x.get("url")]
        if with_url:
            for x in with_url[:6]:
                typer.echo(f"    акт {x['akt']}: {x['url']}")
            if len(with_url) > 6:
                typer.echo(f"    … ще {len(with_url) - 6} актів")
        else:
            typer.echo(f"    акти {r.get('acts') or '—'} · {r.get('book_url') or ''}")


@app.command("find")
def cmd_find(
    village: str = typer.Argument(..., help="назва села або містечка"),
    also: list[str] = typer.Option([], "--also",
                                   help="інше написання, якого немає в газетирах: "
                                        "історична назва, форма мови діловодства"),
    books: bool = typer.Option(True, "--books/--no-books",
                               help="одразу взяти книги кожної парафії"),
    limit: int = typer.Option(20, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чиї парафії в цьому селі — і які книги кожної з них.

    🕍 Три конфесії одного містечка — три окремі парафії, і книги їхні лежать у
    різних справах.
    """
    env = O.call("parish.find", {"q": village, "also": list(also), "books": books})
    # 🔴 Єдиний вихід команди: у машинному режимі конверт віддається
    #    ЦІЛИМ (з попередженнями й покриттям), а відмова — теж відповідь.
    if _answer(env, as_json):
        return
    data = env.data or {}
    typer.echo(f"🏘 {village} — шукали як: {', '.join(data.get('forms') or [])}")
    _gazetteer_line(data)
    parishes = data.get("parishes") or []
    typer.echo(f"\n⛪ парафій: {len(parishes)}")
    for p in parishes:
        typer.echo(f"  · {p.get('title')}")
        typer.echo(f"    книг {p.get('cases')}; "
                   f"теги {', '.join(p.get('tags') or []) or '—'}")
    szady = data.get("szady") or []
    if szady:
        typer.echo(f"\n🏛 база Шади (~1772): {len(szady)}")
        for c in szady:
            alt = f" (вар. {c['name_v']})" if c.get("name_v") else ""
            typer.echo(f"  · {c['name']}{alt} · деканат {c.get('deanery') or '—'}"
                       f" · `nysh church card {c['ob_id']}`")
    _rk_block(data)
    _metrics_block(data)
    _court_block(data)
    for title, rows in (data.get("books") or {}).items():
        typer.echo(f"\n📕 {str(title)[:70]} → {len(rows)} справ")
        _cases(rows, limit)
    _notes(env)


@app.command("metrics")
def cmd_metrics(
    village: str = typer.Argument(..., help="«село» або «село, повіт»"),
    also: list[str] = typer.Option([], "--also",
                                   help="інше написання: історична назва, польська форма"),
    limit: int = typer.Option(20, "--limit", help="скільки записів показати (0 — усі)"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Які метричні книги є про село — за каталогами й описами архівів (без мережі).

    Те, що колись давали Рідні: церкви, костели, синагоги, сільради й групи сіл
    РАЦС, до яких належало село, і справи за типом запису. Прогалини всередині
    книги — з нотатника справи (`nysh note add --kind about`).
    """
    env = O.call("parish.metrics", {"q": village, "also": list(also)})
    if _answer(env, as_json):
        return
    m = env.data or {}
    rows = m.get("rows") or []
    typer.echo(f"📚 «{village}» — записів покажчика: {len(rows)}")
    if m.get("other_povit"):
        typer.echo(f"   ⚠ відсіяно однойменних з інших повітів: {m['other_povit']}")
    if rows and "," not in village and len({(r.get("povit"), r.get("gub")) for r in rows}) > 1:
        typer.echo(f"   ⚠ запит без повіту: книги однойменних сіл змішані — «{village}, <повіт>»")
    if m.get("alt_names"):
        typer.echo(f"   шукали й як: {', '.join(m['alt_names'])}")
    _metric_rows(m, limit)
    if not rows:
        typer.echo("\n0 — у каталогах книг під цією назвою немає. Перед «немає»: сучасна й "
                   "історична назва, повіт, покажчик (`nysh parish find`).")
        if m.get("similar"):
            typer.echo(f"   схожі назви (перевірити написання): {', '.join(m['similar'])}")
    _notes(env)


@app.command("in-case")
def cmd_in_case(
    case: str = typer.Argument(..., help="повний код справи: архів-фонд-опис-справа"),
    match: list[str] = typer.Option([], "--match",
                                    help="село, яке шукаємо в переліку"),
    limit: int = typer.Option(30, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Які села всередині цієї книги — ДО того, як її читати.

    Три різні відповіді: збіг є — книга вгору черги; збігу немає, але парафії
    перелічені — вниз черги; парафій нуль — знаменника немає й висновку теж.
    """
    env = O.call("parish.in_case", {"case": case, "match": list(match)})
    # 🔴 Єдиний вихід команди: у машинному режимі конверт віддається
    #    ЦІЛИМ (з попередженнями й покриттям), а відмова — теж відповідь.
    if _answer(env, as_json):
        return
    data = env.data or {}
    card = data.get("case") or {}
    typer.echo(f"📕 {card.get('code')} · {card.get('years') or '—'} · "
               f"{str(card.get('title') or '')[:64]}")
    parishes = data.get("parishes") or []
    typer.echo(f"   парафій у книзі: {len(parishes)}")
    matched = data.get("matched") or []
    if match:
        typer.echo(f"\n🎯 збігів: {len(matched)}")
        for p in matched:
            typer.echo(f"   · {p.get('title')}")
    else:
        for p in parishes[:limit]:
            typer.echo(f"   · {str(p.get('title'))[:92]}")
        if len(parishes) > limit:
            typer.echo(f"   … ще {len(parishes) - limit}")
    copies = data.get("copies") or []
    typer.echo(f"\n🌐 онлайн-копій: {len(copies)}")
    for c in copies[:8]:
        typer.echo(f"   [{c.get('availability', ''):<7} {c.get('checked', '')}] "
                   f"{c.get('url')}")
    _notes(env)


@app.command("near")
def cmd_near(
    lat: float = typer.Argument(..., help="широта центра"),
    lng: float = typer.Argument(..., help="довгота центра"),
    km: float = typer.Option(15.0, "--km", help="радіус кола"),
    tags: list[str] = typer.Option([], "--tag",
                                   help="тип документа; можна кілька"),
    years: str = typer.Option("", "--years", help="1780-1830 або 1802"),
    offline_only: bool = typer.Option(False, "--offline",
                                      help="лише неоцифровані — черга замовлення"),
    limit: int = typer.Option(25, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Що є по сусідніх селах — коло одразу справами, а не топонімами."""
    y1, _, y2 = years.partition("-")
    env = O.call("parish.near",
                {"lat": lat, "lng": lng, "km": km, "tags": list(tags),
                 "year_from": y1.strip(), "year_to": (y2 or y1).strip(),
                 "offline_only": offline_only})
    # 🔴 Єдиний вихід команди: у машинному режимі конверт віддається
    #    ЦІЛИМ (з попередженнями й покриттям), а відмова — теж відповідь.
    if _answer(env, as_json):
        return
    data = env.data or {}
    rows = data.get("cases") or []
    typer.echo(f"📍 {lat}, {lng} · {km} км → {len(rows)} справ")
    by_fond = data.get("by_fond") or {}
    top = sorted(by_fond.items(), key=lambda kv: -kv[1])[:12]
    typer.echo("   за фондами: " + (", ".join(f"{k}={v}" for k, v in top) or "—"))
    typer.echo("")
    _cases(rows, limit)
    _notes(env)


@app.command("mentions")
def cmd_mentions(
    village: str = typer.Argument(..., help="назва села"),
    also: list[str] = typer.Option([], "--also", help="інше написання"),
    limit: int = typer.Option(25, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Справи, де село згадане в АНОТАЦІЇ, а не в назві: суд, поліція, управа.

    Заголовок такої справи про село не каже нічого, тож пошуком по назві вона
    не знаходиться ніколи — а в анотації стоять і село, і прізвища учасників.
    """
    env = O.call("parish.mentions", {"q": village, "also": list(also)})
    # 🔴 Єдиний вихід команди: у машинному режимі конверт віддається
    #    ЦІЛИМ (з попередженнями й покриттям), а відмова — теж відповідь.
    if _answer(env, as_json):
        return
    data = env.data or {}
    rows = data.get("cases") or []
    typer.echo(f"🗂 {village} — шукали як: {', '.join(data.get('forms') or [])}")
    _gazetteer_line(data)
    typer.echo(f"   згадок: {len(rows)}\n")
    _cases(rows, limit)
    _notes(env)
