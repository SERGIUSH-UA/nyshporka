r"""`nysh cases` — центральний реєстр справ: збірка, фільтри, картка, зведення."""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

import typer
from rich.console import JustifyMethod
from rich.table import Table

from nyshporka import brand
from nyshporka.cases import db
from nyshporka.catalog import store as _store
from nyshporka.core.workspace import workspace as _workspace
from nyshporka.fonds import registry as _fonds

app = typer.Typer(help="Реєстр справ: що є, що декодовано, що прошукано, що бачило око.")
# Поза терміналом (пайп, лог, виклик з агента) Rich припускає 80 колонок і стискає
# праву частину таблиці — а саме там стан обробки, заради якого реєстр і потрібен.
console = brand.console()

_HTR_MARK = {"none": "—", "partial": "◐", "pysar": "П", "diak": "Д",
             "skryba": "С", "both": "П+Д"}
_FUZZY_MARK = {"none": "—", "scanned": "скан", "swept": "прочесано", "reviewed": "розібрано"}


def _warn_stale() -> None:
    """Попередити, якщо реєстр відстав від джерел.

    Друкуємо ПЕРЕД відповіддю, а не після: застарілий зріз читається як факт
    («декоду немає»), і побачити застереження треба до того, як число піде в
    рішення. Мовчазна відповідь на старих даних — те саме, що мовчазний нуль
    у пошуку.
    """
    try:
        st = db.staleness()
    except Exception:
        return
    if not st.get("stale"):
        return
    console.print(f"[warn]⚠ реєстр застарів[/warn] "
                  f"({'; '.join(st['reasons'][:3])}) — [bold]nysh cases build[/bold]")


def _place(row: dict[str, Any]) -> str:
    """Місце для списку: розібране, а якщо розбору не вийшло — сире, з міткою `?`.

    Мітка потрібна, бо порожня клітинка читалась би як «місце невідоме», хоч воно
    записане — просто в формі, якої парсер не знає.
    """
    sett, uezd = row.get("settlement") or "", row.get("uezd") or ""
    if sett and uezd:
        return f"{sett} · {uezd[:9]}"
    if sett or uezd:
        return sett or f"{uezd} пов."
    raw = (row.get("place_raw") or "").strip()
    return f"[muted]?[/muted] {raw}" if raw else ""


def _years(row: dict[str, Any]) -> str:
    yf, yt = row.get("year_from"), row.get("year_to")
    if yf and yt and yf != yt:
        return f"{yf}–{yt}"
    return str(yf or yt or "")


@app.command("build")
def cmd_build(
    rescan: bool = typer.Option(False, "--rescan",
                                help="Перебудувати ще й опис справ (скан диска)"),
) -> None:
    """Зібрати реєстр у `data/derived/case_index.sqlite`."""
    if rescan:
        from nyshporka.library import build_library, write_library
        entries = build_library()
        write_library(entries)
        console.print(f"[muted]бібліотеку перебудовано: {len(entries)} справ[/muted]")
    res = db.build_index()
    tail = (f" · свідомо нічиїх: {res['decided']}" if res.get("decided") else "")
    console.print(f"✅ реєстр: [bold]{res['cases']}[/bold] справ · "
                  f"нерозв'язаних прогонів: {res['orphans']}{tail} · {res['path']}")


@app.command("list")
def cmd_list(
    q: str = typer.Option("", "--q", help="Підрядок: шифра, назва, місце, шлях"),
    repo: str = typer.Option("", "--repo", help="Архів: DAHMO / DAVO / ANRM …"),
    state: str = typer.Option("", "--state", help="ordered | partial | on_disk"),
    htr: str = typer.Option("", "--htr", help="none | partial | pysar | diak | both"),
    fuzzy: str = typer.Option("", "--fuzzy", help="none | scanned | swept | reviewed"),
    year: str = typer.Option("", "--year", help="Рік або діапазон: 1846 / 1840-1860"),
    place: str = typer.Option("", "--place", help="Будь-яке місце: село, повіт, губернія"),
    uezd: str = typer.Option("", "--uezd", help="Повіт: Ольгопільський / Olgopol"),
    settlement: str = typer.Option("", "--settlement", "--село",
                                   help="Поселення: М'ястківка / Miastkowka"),
    doc: str = typer.Option("", "--doc", help="Тип: метричні / сповідн / ревіз …"),
    verdict: str = typer.Option("", "--verdict", help="no_clan | clan_found | recheck"),
    curated: bool = typer.Option(False, "--curated", help="Лише курована черга"),
    kind: str = typer.Option("", "--kind",
                             help="case | bundle | unfiled (матеріал без шифри)"),
    limit: int = typer.Option(60, "--limit", help="0 — без обмеження"),
    as_json: bool = typer.Option(False, "--json", help="Машинний вивід"),
) -> None:
    """Перелік справ за фільтрами."""
    if not as_json:
        _warn_stale()
    rows = db.query_rows(q=q, repo=repo, state=state, htr=htr, fuzzy=fuzzy, year=year,
                         place=place, doc=doc, verdict=verdict, curated=curated,
                         kind=kind, uezd=uezd, settlement=settlement, limit=limit)
    if as_json:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        console.print("[warn]нічого не знайшлось за цими фільтрами[/warn]")
        return
    t = Table(show_lines=False, header_style="bold")
    # Ширини фіксовані, `no_wrap`: без цього довга назва справи розсипає рядок на
    # шість візуальних, і таблиця на 60 рядків перестає читатись.
    widths = {"шифра": 22, "назва": 38, "роки": 9, "місце": 18, "кадрів": 6,
              "HTR": 7, "стор.": 6, "пошук": 12, "канон": 5, "око": 4}
    for col, w in widths.items():
        t.add_column(col, max_width=w, no_wrap=True, overflow="ellipsis",
                     justify="right" if col in ("кадрів", "стор.", "канон", "око") else "left")
    for r in rows:
        cov = r.get("htr_coverage") or 0
        pages = str(r.get("htr_pages_max") or "")
        if r.get("htr_stage") == "partial" and pages:
            pages = f"[warn]{pages}[/warn]"
        # У матеріалу без шифри назви нема за визначенням — показуємо шлях,
        # інакше рядок порожній і незрозуміло, про яку теку йдеться.
        name = r.get("title") or ""
        if not name and r.get("kind") != "case":
            name = r.get("path") or ""
        t.add_row(
            r.get("shifra") or r.get("key"),
            name or "[muted]без назви[/muted]",
            _years(r), _place(r),
            str(r.get("frames") or 0),
            _HTR_MARK.get(r.get("htr_stage") or "none", "?")
            + (f" {cov:.0%}" if 0 < cov < 0.95 else ""),
            pages,
            _FUZZY_MARK.get(r.get("fuzzy_stage") or "none", "?")
            + (f" {r.get('fuzzy_hits')}" if r.get("fuzzy_hits") else ""),
            str(r.get("canon_facts") or ""),
            str(r.get("pages_noted") or ""),
        )
    console.print(t)
    console.print(f"[muted]показано {len(rows)}[/muted]")


@app.command("show")
def cmd_show(
    case: str = typer.Argument(..., help="Шифра, ключ або підрядок назви"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Картка справи: усі шари обробки разом."""
    if not as_json:
        _warn_stale()
    rows = db.query_rows(q=case, limit=0)
    exact = [r for r in rows if case.strip() in (r.get("key"), r.get("shifra"))]
    rows = exact or rows
    if not rows:
        console.print(f"[warn]не знайшов справу: {case}[/warn]")
        raise typer.Exit(1)
    if len(rows) > 1 and not exact:
        console.print(f"[warn]знайшлось {len(rows)}, показую першу:[/warn] "
                      + ", ".join(r.get("shifra") or "" for r in rows[:6]))
    r = rows[0]
    if as_json:
        typer.echo(_json.dumps(r, ensure_ascii=False, indent=1))
        return
    console.print(f"[bold]{r.get('shifra')}[/bold] · {r.get('title') or 'без назви'}")
    console.print(f"  роки: {_years(r) or '—'} · тип: {r.get('doc_type') or '—'}")
    geo = " · ".join(x for x in (
        ", ".join(r.get("settlements") or []),
        ", ".join(f"{u} пов." for u in (r.get("uezds") or [])),
        f"{r.get('guberniya')} губ." if r.get("guberniya") else "",
        f"[muted]{r.get('place_id')}[/muted]" if r.get("place_id") else "") if x)
    console.print(f"  місце: {geo or '—'}")
    if r.get("place_raw") and (r.get("place_raw") or "").strip() != geo:
        console.print(f"         [muted]як записано: {r.get('place_raw')}[/muted]")
    console.print(f"  диск: {r.get('state')} · кадрів {r.get('frames')} · {r.get('path') or '—'}")
    if r.get("extra_paths"):
        console.print(f"        + {len(r['extra_paths'])} додаткових тек")
    voices = []
    for voice, label in (("pysar", "Писар"), ("diak", "Дяк"), ("skryba", "Скриба")):
        if r.get(f"htr_{voice}"):
            voices.append(f"{label} {r.get(f'htr_{voice}_model')} "
                          f"({r.get(f'htr_{voice}_pages')} стор.)")
    console.print(f"  HTR: {'; '.join(voices) if voices else '—'}")
    if r.get("htr_runs"):
        cov = r.get("htr_coverage") or 0
        console.print(f"       покриття {cov:.0%} · прогони: {', '.join(r['htr_runs'])}")
    if r.get("fuzzy_scanned"):
        console.print(f"  пошук роду: {r.get('fuzzy_scanned')} ({r.get('fuzzy_model')}) · "
                      f"кандидатів {r.get('fuzzy_hits')}, розібрано {r.get('fuzzy_reviewed')}"
                      + (" · прочесано суцільно" if r.get("fuzzy_swept") else ""))
    else:
        console.print("  пошук роду: —")
    console.print(f"  канон: фактів {r.get('canon_facts')}, осіб {r.get('canon_persons')}, "
                  f"аркушів {r.get('canon_scans')}"
                  + (f" · {r.get('canon_source_id')}" if r.get("canon_source_id") else ""))
    console.print(f"  око: сторінок у сховищі {r.get('pages_noted')} "
                  f"(повних {r.get('pages_full')})")
    if r.get("verdict"):
        console.print(f"  вердикт: {r.get('verdict')} — {r.get('verdict_note') or ''}")
    if r.get("why"):
        console.print(f"  нащо: {r.get('why')}")


@app.command("orphans")
def cmd_orphans(as_json: bool = typer.Option(False, "--json")) -> None:
    """Прогони, які не прив'язались до жодної справи (їх декод «нічий»)."""
    rows = db.orphan_runs()
    if as_json:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=1))
        return
    # 🔴 «Нема до чого прив'язати» — теж рішення людини, і воно мусить виглядати
    # інакше за «ще не розібрались»: доти єдиний прогін зі свідомим `key: null`
    # (проба моделі по справі, якої немає ні на диску, ні в бібліотеці) лежав у
    # тому самому списку, тож нуль тут був недосяжний — а саме нуль і є приймачем.
    decided = [r for r in rows if (r.get("resolved_by") or "") == "override"]
    unresolved = [r for r in rows if (r.get("resolved_by") or "") != "override"]

    def _table(items: list[dict[str, Any]]) -> Table:
        t = Table(header_style="bold")
        for col in ("прогін", "сторінок", "модель", "звідки", "case_dir у меті"):
            t.add_column(col, overflow="fold",
                         justify="right" if col == "сторінок" else "left")
        for r in items:
            t.add_row(r["run"], str(r["pages"] or ""), r["model"] or "",
                      r["source"] or "", r["case_dir"] or "[muted]—[/muted]")
        return t

    if unresolved:
        console.print(_table(unresolved))
        console.print(f"[warn]нічиїх прогонів: {len(unresolved)}[/warn] — "
                      "прив'язати вручну можна у data/cases/overrides.json")
    else:
        console.print("✅ нерозв'язаних прогонів немає")
    if decided:
        console.print(f"\n[muted]свідомо нічиї (рішення людини у overrides, `key: null`): "
                      f"{len(decided)}[/muted]")
        for r in decided:
            console.print(f"  [muted]{r['run']} · {r['pages'] or 0} стор. — "
                          f"{r.get('note') or 'без пояснення'}[/muted]")


@app.command("stats")
def cmd_stats(as_json: bool = typer.Option(False, "--json")) -> None:
    """Зведення: скільки завантажено, декодовано, прошукано, переглянуто."""
    s = db.stats()
    if as_json:
        typer.echo(_json.dumps(s, ensure_ascii=False, indent=1))
        return
    meta = db.index_meta()
    console.print(f"[bold]Реєстр справ[/bold] · зібрано {meta.get('built', '?')}")
    _warn_stale()
    console.print(f"  справ: {s['cases']} · кадрів на диску: {s['frames']:,}"
                  .replace(",", " "))
    console.print(f"  замовлено (картка без кадрів): {s['ordered']} · "
                  f"декод обірвано: {s['partial']}")
    console.print(f"  БЕЗ декоду: {s['htr_none']} справ / "
                  f"{s['htr_frames_left']:,} кадрів".replace(",", " "))
    console.print(f"  декодовано сторінок: {s['htr_pages']:,}".replace(",", " "))
    console.print(f"  без пошуку роду: {s['fuzzy_none']} справ · "
                  f"кандидатів чекає ока: {s['fuzzy_hits_open']}")
    console.print(f"  цитує канон: {s['canon_cases']} справ · "
                  f"сторінки заносив око: {s['eye_cases']}")
    if s.get("unfiled"):
        console.print(f"  [warn]без шифри справи: {s['unfiled']} тек / "
                      f"{s['unfiled_frames']:,} кадрів[/warn]".replace(",", " ")
                      + "  (nysh cases list --kind unfiled)")
    if s.get("bundles"):
        console.print(f"  збірки (не справи): {s['bundles']} · "
                      f"кадрів {s['bundle_frames']:,} · "
                      f"декодовано {s['bundle_pages']:,}".replace(",", " "))
    if s.get("orphan_runs"):
        console.print(f"  [warn]прогонів без справи: {s['orphan_runs']} "
                      f"({s['orphan_pages']:,} стор.)[/warn]".replace(",", " "))
    if s.get("decided_none_runs"):
        console.print(f"  [muted]свідомо нічиї (рішення людини): "
                      f"{s['decided_none_runs']}[/muted]")
    console.print(f"  географія: повіт розібрано у {s['geo_uezd']}, "
                  f"поселення у {s['geo_settlement']}, прив'язано до канону "
                  f"{s['geo_place_id']}"
                  + (f" · [warn]не розібрано: {s['geo_unparsed']}[/warn]"
                     if s.get("geo_unparsed") else "")
                  + f" · без місця взагалі: {s['geo_empty']}")
    if s.get("by_uezd"):
        tu = Table(header_style="bold", title="За повітами")
        for col in ("повіт", "справ", "кадрів", "без декоду"):
            tu.add_column(col, justify="right" if col != "повіт" else "left")
        for r in s["by_uezd"]:
            tu.add_row(r["uezd"], str(r["n"]), f"{r['frames']:,}".replace(",", " "),
                       str(r["no_htr"]))
        console.print(tu)
    t = Table(header_style="bold", title="За архівами")
    for col in ("архів", "справ", "кадрів", "без декоду", "кадрів без декоду"):
        t.add_column(col, justify="right" if col != "архів" else "left")
    for r in s["by_repo"]:
        t.add_row(r["repo"] or "?", str(r["n"]), f"{r['frames']:,}".replace(",", " "),
                  str(r["no_htr"]), f"{r['frames_left']:,}".replace(",", " "))
    console.print(t)


# ── реєстр ОПИСУ фонду (що існує) ↔ реєстр СПРАВ (що ми з цим зробили) ────────
# Це різні сховища, і плутати їх дорого: опис знає 4885 справ ф.230, з яких на
# диску 11. `opys` дивиться в перший, решта команд — у другий.

# 🔴 Читання реєстру опису живе в `nyshporka.fonds.registry` — ОДИН фільтр на два
# входи (CLI і веб-консоль). Копія тут зробила б `cases fond --todo` і вкладку
# «🏛 Фонди» двома реалізаціями одного питання: перше ж розходження дало б два
# різні числа «скільки качати», і жодне не читалося б як помилка.
_REPO_SLUG = _fonds.REPO_SLUG


def _parse_key(key: str) -> tuple[str, str, str, str, str]:
    """`DAHMO/230/43` або `ДАХмО 230-1-43` → (repo, fond, opys, spr_int, letter)."""
    try:
        return _fonds.parse_key(key)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _opys_registry_row(repo: str, fond: str, opys: str, spr: str,
                       letter: str) -> tuple[dict[str, Any] | None, Path]:
    """Рядок реєстру опису ПЛЮС шлях реєстру — шлях потрібен у повідомленні.

    ⚠ Пара, а не самий рядок: коли справи в реєстрі немає, користувачу треба
    сказати, ДЕ саме її шукали, інакше «немає» не відрізнити від «реєстр
    цього фонду не зібраний».
    """
    return _fonds.registry_row(repo, fond, opys, spr, letter)


@app.command("opys")
def cmd_opys(key: str = typer.Argument(..., help="DAHMO/230/43 або DAHMO/230/1/43"),
             as_json: bool = typer.Option(False, "--json")) -> None:
    """Що реєстр ОПИСУ знає про справу — ПЕРШИЙ крок перед будь-якою роботою.

    Відповідає на три питання, кожне з яких змінює дію: звідки качати (Commons чи
    обрізане дзеркало), чи можна вірити номеру справи, і наскільки надійний заголовок.
    """
    repo, fond, opys, spr, letter = _parse_key(key)
    row, path = _opys_registry_row(repo, fond, opys, spr, letter)
    if row is None:
        console.print(f"[warn]у реєстрі опису немає {repo} {fond}-{opys}-{spr}{letter}"
                      f"[/warn]  ({path})")
        # ⚠ Порада в порожнє гірша за відсутність поради: людина виконує її,
        # бачить «немає такого файлу» й вирішує, що зламався застосунок. Тому
        # обидва шляхи названо, і саме в цьому порядку: взяти готовий пак
        # дешевше, ніж зібрати фонд самому.
        console.print("  реєстр опису цього фонду не встановлено: "
                      f"[bold]nysh catalog install --from <zip>[/bold]  "
                      f"[muted]({_store.RELEASES_URL})[/muted]")
        console.print(f"  або зібрати самому: [bold]nysh registry collect …[/bold] "
                      f"→ [bold]nysh registry merge --repo {repo} --fond {fond}"
                      f"[/bold]")
        raise typer.Exit(1)
    if as_json:
        typer.echo(_json.dumps(row, ensure_ascii=False, indent=1))
        return

    console.print(f"[bold]{repo} {fond}-{opys}-{spr}{letter}[/bold]  "
                  f"{row.get('title') or '[muted](без заголовка)[/muted]'}")
    if row.get("title_src"):
        console.print(f"  заголовок з: {row['title_src']}"
                      + (f"  [warn]альт.: {row['title_alt']}[/warn]"
                         if row.get("title_alt") else ""))
    if row.get("commons_title"):
        console.print(f"  [muted]назва на Commons:[/muted] {row['commons_title']}")
    yrs = "–".join(x for x in (row.get("year_from"), row.get("year_to")) if x)
    console.print(f"  роки: {yrs or '?'} · аркушів: {row.get('folios') or '?'}"
                  + (f" · д/в №: {row['dv_no']}" if row.get("dv_no") else ""))

    # 🔴 те, заради чого команда існує: чи можна вірити номеру й звідки качати
    if row.get("num_src") == "interp":
        console.print("[err]  🔴 номер справи ВІДНОВЛЕНО між якорями, а не прочитано[/err]"
                      f" — звірити оком сторінку опису {row.get('src_page') or '?'}")
    if row.get("page_quality") == "lo":
        console.print("[warn]  ⚠ рядок опису зі сторінки ~100 dpi — дані слабкі"
                      "[/warn]")
    cs = row.get("commons_size")
    ms = row.get("mirror_size")
    # 🏛 ARCHIUM першим, бо саме ним справу й візьмуть: переглядач архіву віддає
    # готові посторінкові JPG (спр.1056 ф.224 — 54 кадри за 4 с), тоді як решта
    # каналів вимагає або файла на сотні МБ, або обходу дзеркала плівок.
    arch = (row.get("archium_url") or "").strip()
    if arch:
        console.print(f"  [ok]ARCHIUM:[/ok] посторінкові скани — {arch}")
    if cs and str(cs).isdigit():
        console.print(f"  [ok]Commons:[/ok] {int(cs) / 2**20:.0f} МБ, "
                      f"{row.get('commons_pages') or '?'} стор.")
    if ms and str(ms).isdigit():
        mark = " [err](ОБРІЗАНО — не качати звідси)[/err]" if row.get(
            "truncated_mirror") else ""
        console.print(f"  дзеркало: {int(ms) / 2**20:.0f} МБ{mark}")
    # 🎞 FS — третій канал доступу, і для метричних фондів головний. Без цієї
    # гілки картка радила «замовлення в архіві» про справи з живою плівкою:
    # ЦДІАК ф.224 має DGS у 1827 справах (колонка «Посилання на FamilySearch»
    # у таблиці опису), а Commons — лише в 42. Саме так метрики с. Слюсарева
    # (224-1-1190, DGS 110032617) числились недоступними.
    film = (row.get("fs_film") or row.get("fs_dgs") or "").strip()
    if film:
        console.print(f"  [ok]FamilySearch:[/ok] DGS {film}"
                      + (f" · {row['fs_frames']} кадрів" if row.get("fs_frames") else ""))
        console.print("    https://www.familysearch.org/records/images/"
                      f"search-results?imageGroupNumbers={film}")
    if not cs and not ms and not film and not arch:
        console.print("  [warn]сканів онлайн немає — замовлення в архіві[/warn]")
    console.print(f"  на диску: {row.get('on_disk') or '[muted]—[/muted]'}")

    # 🔴 РОЗБІЖНОСТІ ДЖЕРЕЛ — тут, а не «десь у TSV». Ця команда названа першим
    # кроком перед будь-якою роботою, тож саме вона мусить сказати, що голоси
    # про справу не сходяться, і що з цього приводу вже вирішила людина.
    # Заміряно на ДАВіО 904-24-178: каталог архіву каже «Вільшанка, 1908-1909»,
    # а файл на Commons — «євреї М'ясківка» і виявився дублем справи 174; без
    # цього блоку картка мовчки радила б працювати з чужою книгою.
    try:
        fid = _fonds.fond_id_of(repo, fond)
        confl = [c for c in (_fonds.load_conflicts(fid) or [])
                 if (c.get("opys") or "") == str(opys)
                 and (c.get("spr") or "") == f"{spr}{letter}"]
    except Exception:
        confl = []
    for c in confl:
        verdict = (c.get("verdict") or "").strip()
        head = (f"[ok]✔ вердикт: {verdict}[/ok]" if verdict
                else "[warn]⚠ розбіжність джерел, вердикту ще немає[/warn]")
        console.print(f"  {head}  [muted]({c.get('field')})[/muted]")
        console.print(f"    {c.get('src_a')}: {c.get('value_a')}")
        console.print(f"    {c.get('src_b')}: {c.get('value_b')}")
        if c.get("note"):
            console.print(f"    [muted]{c['note']}[/muted]")

    console.print(f"  [muted]джерела рядка: {row.get('sources')}[/muted]")
    if not row.get("on_disk") and cs:
        # 🔴 `take` і `show` живуть ЛИШЕ в megen CLI (`nysh cases` має build/list),
        # тож підказка з `nysh` обривала роботу на «No such command 'take'».
        console.print(f"\n  взяти в роботу: [bold]uv run megen cases take "
                      f"{repo}/{fond}/{opys}/{spr}{letter}[/bold]")


@app.command("fond")
def cmd_fond(
    fond: str = typer.Option(..., "--fond", help="номер фонду, напр. 230"),
    repo: str = typer.Option("DAHMO", "--repo"),
    opys: str = typer.Option(None, "--opys", help="лише цей опис"),
    q: str = typer.Option(None, "--q", help="підрядок у заголовку (без регістру)"),
    surname: str = typer.Option(None, "--surname",
                                help="прізвище роду з алфавітки фонду (корінь)"),
    year: str = typer.Option(None, "--year", help="рік або діапазон 1800-1810"),
    uezd: str = typer.Option(None, "--uezd", help="повіт у заголовку"),
    scan: bool = typer.Option(False, "--scan", help="лише ті, що мають скан онлайн"),
    on_disk: bool = typer.Option(False, "--on-disk", help="лише завантажені"),
    todo: bool = typer.Option(False, "--todo", help="скан є, а на диску немає"),
    order: bool = typer.Option(False, "--order",
                               help="існує за каталогом, вільного каналу НЕМА — замовлення"),
    village: str = typer.Option("", "--village", "--село",
                                help="поселення: своє село парафії або ПРИПИСНЕ"),
    fs: bool = typer.Option(False, "--fs", help="лише ті, що мають плівку FamilySearch"),
    limit: int = typer.Option(40, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Список справ із реєстру ОПИСУ фонду — «що взагалі існує», з фільтрами.

    🔴 Це НЕ реєстр справ. Реєстр справ (`nysh cases list`) означає «що ми
    зробили», і 4885 рядків опису без кадрів зіпсували б там кожен знаменник —
    насамперед чергу завантаження. Тому реєстр опису лишається окремим сховищем,
    а сюди виведений лише читальний доступ.
    """
    fond_id = _fonds.fond_id_of(repo, fond)
    path = _fonds.fond_path(fond_id)
    if not path.exists():
        console.print(f"[warn]реєстру опису немає: {path}[/warn]")
        console.print("  встановити довідники: "
                      f"[bold]nysh catalog install --from <zip>[/bold]  "
                      f"[muted]({_store.RELEASES_URL})[/muted]")
        raise typer.Exit(1)
    rows = _fonds.load_rows(fond_id)
    live = _fonds.live_on_disk(repo.upper(), fond)
    frames_live = _fonds.live_frames(repo.upper(), fond)
    sel = _fonds.filter_rows(rows, opys=opys or "", q=q or "", surname=surname or "",
                             year=year or "", uezd=uezd or "", scan=scan,
                             on_disk=on_disk, todo=todo, fs=fs, live=live,
                             village=village or "", order=order)
    if as_json:
        # 🔴 `--limit 0` означає «без обмеження» (як в інших командах), а не
        # «нуль рядків»: доти `sel[:0]` віддавав ПОРОЖНІЙ масив, і машинний
        # споживач читав повний реєстр як «нічого не знайдено».
        typer.echo(_json.dumps(sel if limit <= 0 else sel[:limit],
                               ensure_ascii=False, indent=1))
        return

    t = Table(header_style="bold",
              title=f"{repo.upper()} ф.{fond} — реєстр опису ({len(sel)} з {len(rows)})")
    cols: tuple[tuple[str, JustifyMethod], ...] = (
        ("шифра", "left"), ("назва", "left"), ("роки", "left"),
        ("арк.", "right"), ("скан", "left"), ("FS", "left"),
        ("село / літери", "left"), ("тип", "left"), ("диск", "left"), ("№", "left"))
    for col, just in cols:
        t.add_column(col, justify=just)
    for r in sel[:limit]:
        # Розмір із Commons приходить і числом, і рядком, і None — тому спершу
        # зводимо до рядка, і лише перевіривши, беремо число. Порядок важливий:
        # `int(None)` тут упав би посеред друку таблиці.
        cs = str(r.get("commons_size") or "")
        scan_mark = ""
        # 🏛 ARCHIUM попереду Commons, бо це той канал, яким справу візьмуть:
        # готові посторінкові JPG проти файла на сотні МБ. Колонка має радити
        # найшвидший шлях, а не найдавніше реалізований.
        if r.get("archium_file"):
            scan_mark = "[ok]A[/ok]"
        elif cs.isdigit() and int(cs):
            scan_mark = f"C {int(cs) / 2**20:.0f}М"
        elif r.get("mirror_url"):
            scan_mark = "[warn]дзерк.[/warn]"
        if r.get("truncated_mirror"):
            scan_mark += " ✂"
        # для іменних справ роду заголовок в описі — саме прізвище, і воно з
        # алфавітки надійніше, ніж з OCR («ТОЖЕ Гродецких» → `TONE`, `TCEE`)
        title = (r.get("title") or "")[:52]
        if surname or (not title and r.get("surnames")):
            title = (r.get("surnames") or title)[:52]
        # диск — ЖИВИЙ стан бібліотеки, не колонка TSV: та рахувалась на момент
        # останнього merge і після завантаження справи бреше
        st = _fonds.row_status(r, live, {}, frames_live)
        disk = "✓" if st["on_disk_live"] else ("✓?" if r.get("on_disk") else "")
        if st["disk_mismatch"]:
            disk += " [warn]⚠[/warn]"
        # 🔴 Обірване завантаження виглядає точно як ціле, якщо не сказати
        # інакше: показуємо ЧАСТКУ взятих кадрів, а не саму галочку.
        if "partial" in st["flags"]:
            key = (r.get("opys") or "", r.get("spr_int") or "", r.get("spr_letter") or "")
            disk = (f"[err]{frames_live.get(key, 0)}/"
                    f"{_fonds.expected_frames(r)}[/err]")
        # 🎞 плівка: показуємо DGS — саме його вводять у FamilySearch, щоб
        # відкрити справу; кадри поруч кажуть, чи том узагалі підйомний
        dgs = str(r.get("fs_dgs") or "").strip()
        frames = str(r.get("fs_frames") or "").strip()
        fs_mark = (f"{dgs}" + (f" ·{frames}" if frames else "")) if dgs else ""
        # 👁 прочитане оком з обкладинки: для збірного тому — діапазон абетки,
        # для книги одного села — сама назва. Це те, чого немає в каталогах.
        cov = (r.get("cover_place") or "").strip()
        letters = (r.get("cover_letters") or "").strip()
        cover_mark = f"[bold]{letters}[/bold]" if letters else cov[:26]
        # …а де оком не дивились (а це переважна більшість справ), село бере
        # ДРУКОВАНИЙ каталог архіву. Позначаємо 👁 проти прочитаного, щоб два
        # джерела різної сили не злилися в одну колонку без сліду.
        if cover_mark:
            cover_mark = f"👁 {cover_mark}"
        elif r.get("cat_place"):
            cover_mark = f"[muted]{str(r.get('cat_place'))[:26]}[/muted]"
        t.add_row(r.get("shifra") or f"{fond}-{r.get('opys')}-{r.get('spr')}",
                  title,
                  "–".join(x for x in (r.get("year_from"), r.get("year_to")) if x)[:9],
                  r.get("folios") or "",
                  scan_mark,
                  fs_mark,
                  cover_mark,
                  str(r.get("record_types") or ""),
                  disk,
                  "[err]~[/err]" if r.get("num_src") == "interp" else "")
    console.print(t)
    if len(sel) > limit:
        console.print(f"[muted]показано {limit} з {len(sel)} — --limit більше[/muted]")
    console.print("[muted]скан: A = ARCHIUM, переглядач архіву (найшвидший канал) · "
                  "C = Commons (повний) · ✂ дзеркало обрізане · "
                  "FS = DGS плівки FamilySearch ·кадрів · "
                  "село: 👁 = прочитане ОКОМ з обкладинки (жирним — діапазон абетки "
                  "збірного тому), сірим — з друкованого каталогу архіву · "
                  "тип: Н народження · Ш шлюб · Р розлучення · С смерть · "
                  "Д дошлюбні · СП сповідальні · "
                  "№ «~» = номер справи відновлено, звіряти оком[/muted]")


@app.command("take")
def cmd_take(key: str = typer.Argument(..., help="DAHMO/230/43 або DAHMO/230/1/43"),
             dry_run: bool = typer.Option(False, "--dry-run"),
             force: bool = typer.Option(False, "--force"),
             skip_build: bool = typer.Option(False, "--skip-build",
                                             help="не перебудовувати реєстри")) -> None:
    """Взяти справу в роботу: завантажити з ПОВНОГО джерела й зареєструвати.

    Один крок замість чотирьох ручних, бо саме тут народжуються теки без
    `meta.json` — а така справа невидима для бібліотеки, тобто для всього
    конвеєра. Рахує sha256 і кількість сторінок ІЗ ФАЙЛА, пише `meta.json`,
    перебудовує бібліотеку й реєстр.

    🔴 КАНАЛ ВИБИРАЄТЬСЯ ЗА ШВИДКІСТЮ, а не за тим, який перевіряється першим у
    коді. ARCHIUM — переглядач самого архіву — віддає готові посторінкові JPG
    (спр.1056 ф.224: 54 кадри за 4 с), Commons — один файл на сотні МБ,
    дзеркало обрізає великі справи, плівка FS вимагає обходу дзеркала. Доки
    перевірявся лише Commons, ЦДІАК ф.224 виглядав фондом майже без сканів
    (42 справи з 2950) і 1058 справ стояли в черзі «замовлення в архіві»,
    лежачи при цьому онлайн.
    """
    repo, fond, opys, spr, letter = _parse_key(key)
    row, path = _opys_registry_row(repo, fond, opys, spr, letter)
    if row is None:
        console.print(f"[err]у реєстрі опису немає {repo} {fond}-{opys}-{spr}{letter}"
                      f"[/err] ({path})")
        raise typer.Exit(1)
    if not (row.get("archium_url") or row.get("commons_url")):
        console.print(f"[warn]{repo} {fond}-{opys}-{spr}{letter}: сканів на Commons "
                      "немає[/warn]")
        if row.get("mirror_url"):
            console.print(f"  на дзеркалі є ({int(row.get('mirror_size') or 0) / 2**20:.0f}"
                          " МБ), але воно обрізає великі справи — качати руками свідомо:")
            console.print(f"  {row['mirror_url']}")
        # 🎞 Плівка FS — раніше цю гілку не перевіряли, і команда радила
        #    «замовлення в архіві» про справи, які лежать онлайн. Для метричних
        #    фондів це типовий випадок: ЦДІАК ф.224 має DGS у 1827 справах
        #    проти 42 сканів на Commons.
        film = (row.get("fs_film") or row.get("fs_dgs") or "").strip()
        if film:
            console.print(f"  [ok]але є плівка FamilySearch — DGS {film}[/ok]")
            console.print("    перегляд: https://www.familysearch.org/records/images/"
                          f"search-results?imageGroupNumbers={film}")
            # 🔴 Порада мусить вести туди, що є В ЦЬОМУ пакеті. Дзеркало плівок
            # — звичайне джерело (`nysh sources`), тож качається тим самим
            # `nysh get`, що й решта. Радити тут скрипт із дослідницького репо
            # означало б дати команду, якої в людини на машині немає, — а це
            # читається як поламаний застосунок, не як відсутня можливість.
            console.print("    завантаження (поза `take`, бо це не Commons):")
            console.print(f"      nysh browse fsfilm {film}"
                          "        [muted]що лежить на плівці[/muted]")
            console.print(f"      nysh get fsfilm {film} --out <тека>"
                          "  [muted]забрати кадри[/muted]")
        elif not row.get("mirror_url"):
            console.print("  → замовлення в архіві; шифра: "
                          f"{repo} ф.{fond} оп.{opys} спр.{spr}{letter}")
        raise typer.Exit(2)

    ws = _workspace()
    slug = f"{_REPO_SLUG.get(repo, repo.lower())}_{fond}"
    case_dir = ws.root / "data" / "raw" / slug / f"spr-{spr}{letter}"

    # 🔴 КАНАЛ ОБИРАЄТЬСЯ ЗА ШВИДКІСТЮ, а не за тим, який перевіряється першим
    # у коді. Переглядач архіву віддає готові посторінкові JPG, Commons — один
    # файл на сотні мегабайтів. Доки перевірявся лише Commons, ЦДІАК ф.224
    # виглядав фондом майже без сканів (42 справи з 2950), і понад тисяча справ
    # стояла в черзі «замовлення в архіві», лежачи при цьому онлайн.
    #
    # 🔴 І те, й те качається В ЦЬОМУ ПРОЦЕСІ. Досі тут запускались файли з
    # дослідницького репозиторію за шляхом усередині простору, тобто публічний
    # пакет залежав від приватного за адресою на диску: на чужій машині тієї
    # теки немає, і команда падала з «файл не знайдено» — виглядало це як
    # поламаний застосунок, а не як відсутня можливість.
    from nyshporka.cases import acquire as A

    archium = str(row.get("archium_url") or "").strip()
    name = str(row.get("commons_title") or "").strip()
    channel = "ARCHIUM" if archium else ("Commons" if name else "")
    if not channel:
        console.print("[err]у реєстрі немає ні адреси переглядача "
                      "(`archium_url`), ні назви файлу на Commons "
                      "(`commons_title`) — качати нічого[/err]")
        console.print(f"[muted]зібрати: nysh registry collect archium "
                      f"--repo {repo} --fond {fond}[/muted]")
        raise typer.Exit(2)

    console.print(f"[muted]канал: {channel}[/muted]")
    if dry_run:
        console.print(f"[muted]узяв би: {archium or name}[/muted]")
        console.print(f"[muted]у теку : {case_dir}[/muted]")
        return

    shifra = f"{spr}{letter}"
    title_ = str(row.get("title") or "")
    year_ = str(row.get("year_from") or "")
    try:
        if archium:
            got = A.from_archium(case_dir, archium, archive=repo, fond=fond,
                                 opys=opys, spr=shifra, repo=repo,
                                 title=title_, year=year_)
        else:
            got = A.from_commons(case_dir, name, archive=repo, fond=fond,
                                 opys=opys, spr=shifra, title=title_, year=year_)
    except A.AcquireError as exc:
        console.print(f"[err]{exc}[/err]")
        raise typer.Exit(1) from None
    console.print(f"[ok]✓[/ok] {got.pages} стор., "
                  f"{got.bytes / 2**20:.0f} МБ → {got.case_dir}")
    if skip_build:
        return

    # Приймач — ДИСК: справа має з'явитись у бібліотеці, інакше решта конвеєра її
    # не побачить, а прогін ляже «нічиїм». Викликаємо ті самі функції, що й
    # `nysh cases build --rescan` (пакет не має `__main__`, тож `-m nyshporka` не піде).
    from nyshporka.library import build_library, write_library
    entries = build_library()
    write_library(entries)
    res = db.build_index()
    console.print(f"[muted]бібліотека: {len(entries)} справ · реєстр: {res['cases']}[/muted]")

    # 🔴 Приймач — БІБЛІОТЕКА (свіжозібрана), а не реєстр опису: у реєстрі опису
    # колонка `on_disk` оновиться лише наступним `fond_registry_merge`, тож
    # перевірка по ньому завжди кричала б «не видима» одразу після завантаження.
    seen = any(str(e.fond) == fond and str(e.spr) == f"{spr}{letter}"
               and (e.repo or "").upper() == repo for e in entries)
    if seen:
        console.print(f"[muted]бібліотека бачить {repo} {fond}-{opys}-{spr}{letter}[/muted]")
    else:
        console.print("[warn]⚠ справи НЕ видно в бібліотеці — перевір теку й "
                      "meta.json[/warn]")

    console.print(f"\n[ok]✅ {repo} {fond}-{opys}-{spr}{letter} у роботі.[/ok] Далі:")
    console.print(f"  1. [bold]megen cases show {repo}/{fond}/{spr}{letter}[/bold] — картка")
    if row.get("num_src") == "interp":
        console.print("  2. [err]звірити ШИФРУ оком[/err] — номер відновлено, "
                      "див. meta.json → shifra_needs_eye")
    console.print("  3. HTR-прогін (письмо за жанром: родовідні 1802 — латинка/Скриба)")
