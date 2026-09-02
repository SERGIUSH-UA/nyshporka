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


@app.command("find")
def cmd_find(
    village: str = typer.Argument(..., help="назва села або містечка"),
    also: list[str] = typer.Option([], "--also",
                                   help="інше написання: історична назва, "
                                        "форма мови діловодства"),
    books: bool = typer.Option(True, "--books/--no-books",
                               help="одразу взяти книги кожної парафії"),
    limit: int = typer.Option(20, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
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
    parishes = data.get("parishes") or []
    typer.echo(f"\n⛪ парафій: {len(parishes)}")
    for p in parishes:
        typer.echo(f"  · {p.get('title')}")
        typer.echo(f"    книг {p.get('cases')}; "
                   f"теги {', '.join(p.get('tags') or []) or '—'}")
    for title, rows in (data.get("books") or {}).items():
        typer.echo(f"\n📕 {str(title)[:70]} → {len(rows)} справ")
        _cases(rows, limit)
    _notes(env)


@app.command("in-case")
def cmd_in_case(
    case: str = typer.Argument(..., help="повний код справи: архів-фонд-опис-справа"),
    match: list[str] = typer.Option([], "--match",
                                    help="село, яке шукаємо в переліку"),
    limit: int = typer.Option(30, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
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
    limit: int = typer.Option(25, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
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
    limit: int = typer.Option(25, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
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
    typer.echo(f"   згадок: {len(rows)}\n")
    _cases(rows, limit)
    _notes(env)
