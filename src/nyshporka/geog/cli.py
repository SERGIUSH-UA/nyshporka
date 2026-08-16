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
    """Застарілий індекс — вголос і ПЕРЕД відповіддю.

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
    limit: int = typer.Option(20, "--limit"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Знайти поселення за назвою."""
    _warn()
    rows = find_places(q, limit=limit, uezd=uezd, fond=fond)
    if json:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        typer.echo("нічого не знайдено")
        return
    for r in rows:
        typer.echo(f"  {r['village_uk']:30s} {r['village_ru']:26s} "
                   f"{(r['uezd_gub'] or '')[:38]:38s} справ {r['n_cases']:4d}  "
                   f"[{r['card']}]")


@app.command("card")
def cmd_card(
    card: str = typer.Argument(..., help="ідентифікатор картки (miak_003.xml) "
                                         "або назва села"),
    show_confusers: bool = typer.Option(True, "--confusers/--no-confusers"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Картка поселення: прив'язка, церква, УСІ справи + що з них у нас є."""
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
    typer.echo(f"\n🗺 {data['village_uk']}  ({data['village_ru']})")
    typer.echo(f"   до 1793: {data['hist_place']}")
    typer.echo(f"   після  : {data['uezd_gub']}")
    typer.echo(f"   нині   : {data['modern_place']}")
    if data.get("church"):
        typer.echo(f"   церква : {data['church']}")
    cases = data["cases"]
    typer.echo(f"\n   справ у каталозі {len(cases)}, з них у нас "
               f"{data['n_on_disk']}:")
    for c in cases:
        mark = "✓" if c["on_disk"] else "·"
        years = (f"{c['year_from']}–{c['year_to']}"
                 if c["year_from"] else "—        ")
        typer.echo(f"     {mark} {c['shifra']:16s} {years:11s} "
                   f"{(c['doc_type'] or '')[:18]:18s} {(c['parish'] or '')[:34]}")
    if data.get("confusers"):
        typer.echo("\n   ⚠ схожі назви (fuzzy плутає їх із цим селом):")
        for x in data["confusers"]:
            typer.echo(f"     {x['score']:3d} {x['village_uk']:28s} "
                       f"{(x['uezd_gub'] or '')[:36]}")
