"""CLI газетира: `nysh geog build | find | card`.

Той самий модуль, що живить вкладку консолі, — щоб «скільки метрик у цього
села» не стало двома різними числами залежно від входу.
"""
from __future__ import annotations

import json as _json

import typer

from nyshporka.geog.gazetteer import (
    build_index,
    confusers,
    find_places,
    index_path,
    index_stale,
    place_card,
)

app = typer.Typer(help="Газетир ЦДІАК: де документи цього села (всі фонди).",
                  no_args_is_help=True)


def _warn() -> None:
    """Застарілий індекс — вголос і перед відповіддю.

    Той самий принцип, що в реєстрі справ: зріз, який виглядає як відповідь,
    небезпечніший за його відсутність. Тут ціна конкретна — «метрик села немає»
    може означати просто старий індекс.
    """
    why = index_stale()
    if why:
        typer.echo(f"⚠ індекс газетира застарів ({why}) — nysh geog build", err=True)


@app.command("build")
def cmd_build() -> None:
    """Зібрати `data/derived/geog.sqlite` з каталогу ЦДІАК."""
    n = build_index(verbose=True)
    typer.echo(f"   {n['places']} поселень · {n['cases']} справ → {index_path()}")


@app.command("find")
def cmd_find(
    q: str = typer.Argument("", help="назва села (укр або рос; фаззі)"),
    uezd: str = typer.Option("", "--uezd", help="повіт/губернія"),
    fond: str = typer.Option("", "--fond", help="лише де є справи цього фонду"),
    section: str = typer.Option("", "--section",
                                help="church | decanats | rabbinate "
                                     "(порожньо = всі конфесії)"),
    limit: int = typer.Option(20, "--limit", help="скільки показати"),
    json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Знайти поселення за назвою."""
    _warn()
    rows = find_places(q, limit=limit, uezd=uezd, fond=fond, section=section)
    if json:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        typer.echo("нічого не знайдено")
        return
    for r in rows:
        typer.echo(f"  {(r.get('institution') or '')[:18]:18s} "
                   f"{r['village_uk']:28s} {r['village_ru']:24s} "
                   f"{(r['uezd_gub'] or '')[:34]:34s} справ {r['n_cases']:4d}")


@app.command("card")
def cmd_card(
    card: str = typer.Argument(..., help="ідентифікатор картки (miak_003.xml) "
                                         "або назва села"),
    show_confusers: bool = typer.Option(
        True, "--confusers/--no-confusers",
        help="показати схожі назви, які нечіткий пошук плутає з цим селом"),
    json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Картка поселення: прив'язка, церква, усі справи + що з них у нас є."""
    _warn()
    if not card.endswith(".xml"):
        found = find_places(card, limit=1)
        if not found:
            typer.echo("поселення не знайдено")
            raise typer.Exit(1)
        card = found[0]["card"]
    data = place_card(card)
    if not data:
        typer.echo("картки немає")
        raise typer.Exit(1)
    if show_confusers:
        data["confusers"] = confusers(card)
    if json:
        typer.echo(_json.dumps(data, ensure_ascii=False, indent=1))
        return
    typer.echo(f"\n🗺 {data['village_uk']}  ({data['village_ru']})"
               f"   [{data.get('institution') or '—'}]")
    typer.echo(f"   до 1793: {data['hist_place']}")
    typer.echo(f"   після  : {data['uezd_gub']}")
    typer.echo(f"   нині   : {data['modern_place']}")
    if data.get("church"):
        typer.echo(f"   церква : {data['church']}")
    loc = data.get("location")
    if loc and loc.get("lat") is not None:
        amb = "  ⚠ однойменних кілька" if loc.get("how") == "ambiguous" else ""
        typer.echo(f"   точка  : {loc['lat']:.4f}, {loc['lng']:.4f}  "
                   f"[{loc['qid']}]{amb}")
    cases = data["cases"]
    # рядків каталогу буває більше за справи: одна справа містить метрики
    # кількох парафій, і кожна перелічена окремо (Лебедин: 499 проти 59)
    extra = (f" ({data['n_rows']} записів каталогу)"
             if data.get("n_rows", 0) > len(cases) else "")
    typer.echo(f"\n   справ у каталозі {len(cases)}{extra}, з них у нас "
               f"{data['n_on_disk']}:")
    for c in cases:
        mark = "✓" if c["on_disk"] else "·"
        yf, yt = c["year_from"], c["year_to"]
        years = f"{yf}" if yf and yf == yt else (f"{yf}–{yt}" if yf else "—")
        par = (f"{c['n_parishes']} парафій" if c.get("n_parishes", 0) > 1
               else (c.get("parish") or ""))
        typer.echo(f"     {mark} {c['shifra']:16s} {years:11s} "
                   f"{(c['doc_type'] or '')[:18]:18s} {par[:40]}")
    if data.get("siblings"):
        typer.echo("\n   🕍 те саме поселення в інших конфесіях:")
        for x in data["siblings"]:
            typer.echo(f"     {x['institution']:20s} {x['village_uk']:26s} "
                       f"справ {x['n_cases']:4d}  [{x['card']}]")
    if data.get("confusers"):
        typer.echo("\n   ⚠ схожі назви (fuzzy плутає їх із цим селом):")
        for x in data["confusers"]:
            typer.echo(f"     {x['score']:3d} {x['village_uk']:28s} "
                       f"{(x['uezd_gub'] or '')[:36]}")


@app.command("near")
def cmd_near(
    at: str = typer.Argument(..., help="картка (…xml), назва села або «широта,довгота»"),
    km: float = typer.Option(15.0, "--km", help="радіус кола"),
    section: str = typer.Option("", "--section",
                                help="church | decanats | rabbinate"),
    limit: int = typer.Option(100, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Сусідні села газетира в колі — одразу з числом справ."""
    from nyshporka import ops as O
    from nyshporka.cli_emit import answer as _answer
    from nyshporka.cli_emit import notes as _notes

    env = O.call("geog.near", {"at": at, "km": km, "section": section,
                               "limit": limit})
    if _answer(env, as_json):
        return
    data = env.data or {}
    c = data.get("center") or {}
    rows = data.get("places") or []
    typer.echo(f"📍 {c.get('how', '')} · {c.get('lat', 0):.4f}, {c.get('lng', 0):.4f}"
               f" · {km:g} км → сіл {len(rows)}, справ {data.get('n_cases', 0)}")
    for r in rows:
        amb = "?" if r.get("how") == "ambiguous" else " "
        typer.echo(f"  {r['km']:5.1f} км{amb} {r['village_uk']:28s} "
                   f"{(r.get('institution') or '')[:14]:14s} "
                   f"{(r.get('uezd_gub') or '')[:30]:30s} справ {r.get('n_cases') or 0:4d}"
                   f"  [{r['card']}]")
    _notes(env)


# ── ⛪ церкви ~1772: `nysh church find | card | near` ─────────────────────────
#
# Окрема група команд, а не прапорець газетира: питання інше. Газетир — «де
# лежать книги села», церкви — «чи була в селі парафія до поділів, чия й з
# якою присвятою». Гібрид у тому, що кожна знайдена церква приходить уже
# зшитою з поселенням газетира (і числом його справ), а кожен запит показує й
# поселення без церкви в базі 1772.

church_app = typer.Typer(help="Церкви ~1772 (база Шади): чи була парафія, чия, "
                              "і де тепер її книги.",
                         no_args_is_help=True)


def _church_line(r: dict, *, km: bool = False) -> str:
    dist = f"{r.get('km', 0):5.1f} км " if km else ""
    var = f" ({r['name_v']})" if r.get("name_v") else ""
    role = " ·допоміжна" if r.get("role") == "auxiliary" else ""
    return (f"  {dist}{r['ob_id']:5d} {r['name']}{var}{role}\n"
            f"        {r.get('voivodeship_uk') or r.get('voivodeship') or '—'} · "
            f"дек. {r.get('deanery') or '—'} · {r.get('title_uk') or r.get('title') or '—'}"
            f"{' · ' + r['patronage_uk'] if r.get('patronage_uk') else ''}"
            f"{' · ' + r['material_uk'] if r.get('material_uk') else ''}")


def _places_line(r: dict) -> str:
    places = r.get("places") or []
    if not places:
        return ""
    marks = {"mismatch": "⚠інше воєв. ", "far": "⚠далеко ", "near": "✓ "}
    return "        🗺 " + " · ".join(
        f"{marks.get(p.get('region') or '', '')}"
        f"{p['village_uk']} [{(p.get('uezd_gub') or '')[:30]}] справ {p.get('n_cases') or 0}"
        f" ({p.get('score')}{', ' + str(p['km']) + ' км' if p.get('km') is not None else ''})"
        for p in places)


@church_app.command("find")
def church_find(
    q: str = typer.Argument("", help="назва села — кирилицею чи польською; "
                                     "порожньо разом із --deanery дає весь деканат"),
    voivodeship: str = typer.Option("", "--voivodeship",
                                    help="brac | kij | pod | rus | woł | beł …"),
    deanery: str = typer.Option("", "--deanery", help="деканат (підрядок)"),
    confession: str = typer.Option("", "--confession",
                                   help="uniate | orthodox | latin"),
    link: bool = typer.Option(True, "--link/--no-link",
                              help="зшити з газетиром (поселення й справи)"),
    limit: int = typer.Option(20, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Чи була в селі церква ~1772, чия — і де тепер її книги."""
    from nyshporka import ops as O
    from nyshporka.cli_emit import answer as _answer
    from nyshporka.cli_emit import notes as _notes

    env = O.call("church.find", {"q": q, "voivodeship": voivodeship,
                                 "deanery": deanery, "confession": confession,
                                 "link": link, "limit": limit})
    if _answer(env, as_json):
        return
    data = env.data or {}
    rows = data.get("churches") or []
    typer.echo(f"⛪ «{q or '*'}» → церков ~1772: {len(rows)}"
               + (f", зшито з газетиром: {data.get('linked', 0)}" if link else ""))
    for r in rows:
        typer.echo(_church_line(r))
        pl = _places_line(r)
        if pl:
            typer.echo(pl)
    places = data.get("places") or []
    if places:
        typer.echo(f"\n🗺 поселення газетира за цим запитом: {len(places)}")
        for p in places:
            typer.echo(f"  {p['score']:3d} {p['village_uk']:26s} "
                       f"{(p.get('uezd_gub') or '')[:34]:34s} справ {p.get('n_cases') or 0:4d}"
                       f"  [{p['card']}]")
    _notes(env)


@church_app.command("card")
def church_card(
    ob_id: int = typer.Argument(..., help="ob_id церкви з `nysh church find`"),
    km: float = typer.Option(10.0, "--km", help="радіус кола сусідів"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Картка церкви: присвята, патрон, джерело, сусіди, книги села."""
    from nyshporka import ops as O
    from nyshporka.cli_emit import answer as _answer
    from nyshporka.cli_emit import notes as _notes

    env = O.call("church.card", {"ob_id": ob_id, "km": km})
    if _answer(env, as_json):
        return
    r = (env.data or {}).get("church")
    if not r:
        typer.echo("церкви немає")
        _notes(env)
        raise typer.Exit(1)
    typer.echo(f"\n⛪ {r['name']}" + (f" ({r['name_v']})" if r.get("name_v") else "")
               + f"   ob_id {r['ob_id']} · {r.get('place_type') or ''}")
    typer.echo(f"   присвята : {r.get('title_uk') or '—'}"
               + (f"   [{r['title']}]" if r.get("title") else ""))
    typer.echo(f"   конфесія : {r.get('confession') or '—'}"
               + (f" · {r['monastery']}" if r.get("monastery") else "")
               + (f" · допоміжна, парафія {r['parish_of']}" if r.get("parish_of") else ""))
    typer.echo(f"   патронат : {r.get('patronage_uk') or r.get('patronage') or '—'}"
               f" · {r.get('material_uk') or r.get('material') or '—'}")
    typer.echo(f"   деканат  : {r.get('deanery') or '—'} · "
               f"{r.get('voivodeship_uk') or r.get('voivodeship') or '—'} воєв. · "
               f"єпархія {r.get('diocese') or '—'}")
    typer.echo(f"   джерело  : {r.get('source') or '—'}")
    if r.get("lat") is not None:
        typer.echo(f"   точка    : {r['lat']:.4f}, {r['lng']:.4f}")
    if r.get("places"):
        typer.echo("\n   🗺 поселення газетира з цією назвою:")
        for p in r["places"]:
            typer.echo(f"     {p['score']:3d} {p['village_uk']:26s} "
                       f"{(p.get('uezd_gub') or '')[:34]:34s} справ {p.get('n_cases') or 0:4d}"
                       f"  [{p['card']}]")
    if r.get("nearby"):
        typer.echo(f"\n   ⛪ сусіди в колі {km:g} км:")
        for x in r["nearby"]:
            typer.echo(f"     {x['km']:5.1f} км  {x['ob_id']:5d} {x['name']:24s} "
                       f"дек. {(x.get('deanery') or '—')[:14]:14s} "
                       f"{(x.get('title_uk') or '')[:34]}")
    _notes(env)


@church_app.command("near")
def church_near(
    at: str = typer.Argument(..., help="ob_id, «широта,довгота» або назва села"),
    km: float = typer.Option(15.0, "--km", help="радіус кола"),
    confession: str = typer.Option("", "--confession",
                                   help="uniate | orthodox | latin"),
    link: bool = typer.Option(True, "--link/--no-link",
                              help="зшити кожну церкву з газетиром"),
    limit: int = typer.Option(60, "--limit", help="скільки показати"),
    as_json: bool = typer.Option(False, "--json", help="машинний вивід (JSON)"),
) -> None:
    """Коло церков ~1772 навколо села — з книгами кожного сусіда."""
    from nyshporka import ops as O
    from nyshporka.cli_emit import answer as _answer
    from nyshporka.cli_emit import notes as _notes

    env = O.call("church.near", {"at": at, "km": km, "confession": confession,
                                 "link": link, "limit": limit})
    if _answer(env, as_json):
        return
    data = env.data or {}
    c = data.get("center") or {}
    rows = data.get("churches") or []
    typer.echo(f"📍 {c.get('how', '')} · {c.get('lat', 0):.4f}, {c.get('lng', 0):.4f}"
               f" · {km:g} км → церков {len(rows)}"
               + (f", зшито з газетиром {data.get('linked', 0)}" if link else ""))
    dean = data.get("by_deanery") or {}
    if dean:
        typer.echo("   за деканатами: " + ", ".join(
            f"{k}={v}" for k, v in sorted(dean.items(), key=lambda kv: -kv[1])))
    for r in rows:
        typer.echo(_church_line(r, km=True))
        pl = _places_line(r)
        if pl:
            typer.echo(pl)
    _notes(env)
