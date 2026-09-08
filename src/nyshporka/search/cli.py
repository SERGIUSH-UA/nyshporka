r"""`nysh text` — текстовий стор: стан, збірка, регекс по прочитаному.

🔴 Замість `rg` по теці прогонів. Та тека лежить у `.gitignore` (ripgrep мовчки
віддає нуль) і тримає понад мільйон дрібних файлів (обхід — хвилини). Стор
відповідає на те саме питання з одного файлу.
"""
from __future__ import annotations

import typer

from nyshporka import brand
from nyshporka.cli_emit import answer as _answer
from nyshporka.cli_emit import notes as _notes

app = typer.Typer(help="Текстовий стор: усе прочитане в одному файлі — стан, збірка, регекс.",
                  no_args_is_help=True)
console = brand.console()


def _mb(n: int) -> str:
    return f"{n / 1e6:.0f} МБ" if n < 2e9 else f"{n / 1e9:.1f} ГБ"


@app.command("state")
def state_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """Скільки прогонів у сторі, скільки застаріло, скільки важить."""
    from nyshporka import ops as O

    env = O.call("text.state", {})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"стор: {d['file']}")
    console.print(f"прогонів у сторі [bold]{d['indexed']}[/bold] із {d['runs']} · "
                  f"застаріло [bold]{d['stale']}[/bold] · сторінок {d['pages']} "
                  f"(з геометрією {d['geo']}) · рядків {d['lines']} · {_mb(d['bytes'])}")
    _notes(env)


@app.command("index")
def index_cmd(
    case: str = typer.Option("", "--case", help="лише ця справа або прогін"),
    rebuild: bool = typer.Option(False, "--rebuild", help="перебудувати й свіже"),
    accept_rules: bool = typer.Option(False, "--accept-rules",
                                      help="прийняти чинний відбиток правил без перебудови"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Догнати стор по прогонах. Перша збірка корпусу — десятки хвилин, далі
    лише те, що перечитали."""
    from nyshporka import ops as O

    env = O.call("text.index", {"case": case, "rebuild": rebuild, "accept_rules": accept_rules})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"пройдено прогонів {d['asked']}, у сторі свіжих {d['indexed']} із "
                  f"{d['runs']} · сторінок {d['pages']} · {_mb(d['bytes'])}")
    _notes(env)


@app.command("grep")
def grep_cmd(
    pattern: str = typer.Argument(..., help="регекс Python, кирилиця як у тексті"),
    case: str = typer.Option("", "--case", help="лише ця справа або прогін"),
    context: int = typer.Option(1, "--context", help="рядків сусідства"),
    limit: int = typer.Option(100, "--limit"),
    case_sensitive: bool = typer.Option(False, "--case-sensitive"),
    where: str = typer.Option("decode", "--where",
                              help="decode | canon | opys | notes | all, або через кому"),
    extra: list[str] = typer.Option([], "--dir", help="ще тека або файл для шару notes"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Регекс по прочитаному, канону, описах і нотатках — один запит замість
    грепу по чотирьох схованках.

    Декод іде через стор (літерали регексу звужують корпус через індекс); канон,
    описи й нотатки — файлами, їх сотні. Нуль друкується зі знаменником.
    """
    from nyshporka import ops as O

    env = O.call("text.grep", {"pattern": pattern, "case": case, "context": context,
                               "limit": limit, "ignore_case": not case_sensitive,
                               "where": where, "extra": ";".join(extra)})
    if _answer(env, as_json):
        return
    layered = env.data.get("layers")
    if env.data.get("coverage", {}).get("scope") == "layers":
        layered = {"hits": env.data.get("hits") or [], "total": env.data.get("total"),
                   "coverage": env.data["coverage"]["layers"]}
        env.data["hits"] = []
    if layered:
        for h in layered["hits"]:
            console.print(f"[bold]{h['layer']}[/bold] · {h['file']}:{h['line_no']}")
            for b in h.get("before") or []:
                console.print(f"      [muted]↑ {b}[/muted]")
            console.print(f"    [warn]»[/warn] {h['line']}")
            for a in h.get("after") or []:
                console.print(f"      [muted]↓ {a}[/muted]")
        cov = layered["coverage"]
        console.print("[muted]шари: " + " · ".join(
            f"{k}: {v['hits']} хітів у {v['files']} файлах" for k, v in cov.items()) + "[/muted]")
    hits = env.data.get("hits") or []
    for h in hits:
        head = f"{h.get('name')} · {h.get('page')} · рядок {h.get('line_no')}"
        if h.get("shifra"):
            head = f"{h['shifra']} · {head}"
        console.print(f"[bold]{head}[/bold]")
        for b in h.get("before") or []:
            console.print(f"      [muted]↑ {b}[/muted]")
        console.print(f"    [warn]»[/warn] {h.get('line')}")
        for a in h.get("after") or []:
            console.print(f"      [muted]↓ {a}[/muted]")
    cov = env.data.get("coverage") or {}
    _notes(env)
    if cov.get("scope") != "layers":
        # Із літералом FTS звужує до сторінок-кандидатів, і регекс іде лише по
        # них; без нього регекс проходить усі сторінки області.
        how = ("сторінок-кандидатів за літералом (решта відсіяна індексом)"
               if cov.get("literals") else "сторінок прочесано регексом")
        console.print(f"[muted]декод: показано {len(hits)} із {env.data.get('total', len(hits))} · "
                      f"прогонів {cov.get('runs')} · {how} "
                      f"{cov.get('pages_scanned')} із {cov.get('pages')}[/muted]")


# ── етап 2: контекст, кроп, голоси, покриття, картка ─────────────────────────
@app.command("ctx")
def ctx_cmd(
    case: str = typer.Argument(..., help="справа, шифра або назва прогону"),
    page: str = typer.Argument(..., help="скан: «73», «0073», «Image00073.jpg»"),
    line: int = typer.Option(0, "--line", help="рядок з одиниці; 0 — уся сторінка"),
    window: int = typer.Option(4, "--window", help="рядків з кожного боку"),
    full: bool = typer.Option(False, "--full", help="уся сторінка"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Контекст рядка: сторінка, усі голоси, сусіди за геометрією, роки, око."""
    from nyshporka import ops as O

    env = O.call("text.ctx", {"case": case, "page": page, "line": line or None,
                              "window": window, "full": full})
    if _answer(env, as_json):
        return
    d = env.data
    head = f"{d.get('shifra') or d.get('case_key') or case} · {d['page']} · рядків {d['lines_total']}"
    if d.get("years") and any(d["years"]):
        head += f" · роки {d['years'][0] or '?'}–{d['years'][1] or '?'}"
    console.print(f"[bold]{head}[/bold]")
    console.print(f"[muted]голоси: {', '.join(v['voice'] for v in d['voices'])}[/muted]")
    if d.get("eye"):
        e = d["eye"]
        console.print(f"[muted]око: {'дивилось' if e.get('noted') else 'не дивилось'}"
                      f"{' · ' + str(e.get('status')) if e.get('noted') else ''}[/muted]")
    for it in d["window"]:
        mark = "[warn]»[/warn]" if it.get("mark") else " "
        geo = ""
        if it.get("geo_next"):
            geo += f" [accent]⇣{it['geo_next']}[/accent]"
        if it.get("geo_prev"):
            geo += f" [accent]⇡{it['geo_prev']}[/accent]"
        console.print(f"{mark} {it['no']:3}  {it['text']}{geo}")
        for voice, text in (it.get("voices") or {}).items():
            console.print(f"       [muted]{voice}: {text}[/muted]")
    _notes(env)


@app.command("crop")
def crop_cmd(
    case: str = typer.Argument(..., help="справа, шифра або назва прогону"),
    page: str = typer.Argument(..., help="скан"),
    line: int = typer.Argument(..., help="рядок з одиниці"),
    with_next: bool = typer.Option(True, "--next/--no-next", help="разом із наступним рядком"),
    with_prev: bool = typer.Option(False, "--prev", help="разом із попереднім рядком "
                                                       "(хвіст після переносу)"),
    wide: bool = typer.Option(False, "--wide", help="на всю ширину сторінки"),
    pad: int = typer.Option(12, "--pad"),
    scale: float = typer.Option(1.0, "--scale"),
    out: str = typer.Option("", "--out", help="куди зберегти PNG"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Кроп рядка з кадру за рамкою рушія — з поворотом і масштабом, як бачив рушій."""
    from nyshporka import ops as O

    env = O.call("text.crop", {"case": case, "page": page, "line": line,
                               "with_next": with_next, "with_prev": with_prev,
                               "wide": wide, "pad": pad, "scale": scale, "out": out})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['out']}[/bold]  {d['width']}×{d['height']}")
    zoom = f" · збільшення ×{d['scale']}" if d.get("scale") not in (None, 1, 1.0) else ""
    console.print(f"[muted]{d['run']} · {d['page']} · рядок "
                  f"{str(d['prev']) + ' + ' if d.get('prev') else ''}{d['line']}"
                  f"{' + ' + str(d['next']) if d.get('next') else ''} · кадр {d['frame']} · "
                  f"поворот {d['orient']} · масштаб кадру до рамок {d['scale_k']}{zoom}[/muted]")
    if d.get("prev_text"):
        console.print(f"      [muted]↑ {d['prev_text']}[/muted]")
    console.print(f"    [warn]»[/warn] {d['text']}")
    if d.get("next_text"):
        console.print(f"      [muted]↓ {d['next_text']}[/muted]")
    _notes(env)


@app.command("voices")
def voices_cmd(
    case: str = typer.Argument(..., help="справа, шифра або назва прогону"),
    page: str = typer.Argument(..., help="скан"),
    lines: str = typer.Option("", "--lines", help="діапазон «10-30»"),
    only_diff: bool = typer.Option(False, "--diff", help="лише рядки, де голоси розійшлись"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Два голоси рядок до рядка: де зійшлись, де ні."""
    from nyshporka import ops as O

    env = O.call("text.voices", {"case": case, "page": page, "lines": lines})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d.get('case_key') or case} · {d['page']}[/bold] · голоси "
                  f"{' / '.join(d['voices'])} · зійшлись {d['agree']} · розійшлись {d['disagree']}")
    for it in d["lines"]:
        if only_diff and it.get("agree"):
            continue
        sim = f"{it['sim']:5.1f}" if it.get("sim") is not None else "  —  "
        flag = "[muted]=[/muted]" if it.get("agree") else "[warn]≠[/warn]"
        console.print(f"{flag} {it['no']:3} {sim}")
        for v in d["voices"]:
            console.print(f"        [muted]{v}:[/muted] {it.get(v, '')}")
    _notes(env)


@app.command("coverage")
def coverage_cmd(
    case: str = typer.Option("", "--case", help="справа, фонд або порожньо — усе"),
    unsearched: bool = typer.Option(False, "--unsearched", help="лише прочитані, але не шукані"),
    limit: int = typer.Option(300, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Кадри → прочитано → у сторі → чим шукали → скільки бачило око."""
    from rich.table import Table

    from nyshporka import ops as O

    env = O.call("text.coverage", {"case": case, "unsearched": unsearched, "limit": limit})
    if _answer(env, as_json):
        return
    d = env.data
    t = Table(show_header=True, header_style="bold")
    for col in ("справа", "кадрів", "прочитано", "у сторі", "шукали", "око"):
        t.add_column(col, justify="right" if col != "справа" else "left")
    for c in d["cases"]:
        searched = c["searched"][0]["when"] if c["searched"] else (c["fuzzy_stage"] or "—")
        t.add_row(c["shifra"] or c["key"], str(c["frames"]), str(c["decoded"]),
                  f"{c['in_store']}/{c['runs']}", str(searched),
                  f"{c['eye_noted']}" + (f" ({c['eye_full']} повн.)" if c["eye_full"] else ""))
    console.print(t)
    tot = d["total"]
    console.print(f"[muted]справ {tot['cases']} · кадрів {tot['frames']} · прочитано "
                  f"{tot['decoded']} стор. · з прогонами {tot['with_runs']} · у сторі повністю "
                  f"{tot['in_store']} · шукали {tot['searched']} · око торкалось "
                  f"{tot['eye_touched']}[/muted]")
    _notes(env)


@app.command("whatis")
def whatis_cmd(
    case: str = typer.Argument(..., help="справа, шифра або назва прогону"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Картка справи: реєстр, паспорт, прогони, слід пошуку, око, найчастіші слова."""
    from nyshporka import ops as O

    env = O.call("text.whatis", {"case": case})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d.get('shifra') or d.get('case_key') or case}[/bold]  {d.get('title') or ''}")
    yrs = d.get("years") or [None, None]
    console.print(f"[muted]роки {yrs[0] or '?'}–{yrs[1] or '?'} · {d.get('place') or '—'} · "
                  f"{d.get('doc_type') or '—'} · кадрів {d.get('frames') or '?'}[/muted]")
    src = d.get("source") or {}
    if src:
        console.print("[muted]паспорт: " + " · ".join(
            f"{k}={v}" for k, v in src.items()
            if k in ("archive", "record_type", "place", "script", "downloaded_via")) + "[/muted]")
    for r in d.get("runs") or []:
        if r.get("in_store"):
            console.print(f"  прогін {r['run']}: {r['model']} · {r['script'] or '?'} · "
                          f"стор. {r['pages']} · рядків {r['lines']} · з геометрією {r['geo']}"
                          f" · фантомів {d['phantom_pages'].get(r['run'], 0)}")
        else:
            console.print(f"  прогін {r['run']}: [warn]поза стором[/warn]")
    for s in (d.get("searched") or [])[:3]:
        console.print(f"  шукали: «{s.get('q')}» {s.get('when')} · {', '.join(s.get('channels') or [])}")
    eye = d.get("eye") or {}
    if eye:
        console.print(f"  око: занотовано {eye.get('noted', 0)} · {eye.get('by_status') or {}}")
    if d.get("top_words"):
        console.print("  слова: " + ", ".join(f"{w} ({n})" for w, n in d["top_words"]))
    _notes(env)



# ── етап 3: find ─────────────────────────────────────────────────────────────
@app.command("find")
def find_cmd(
    q: str = typer.Argument(..., help="прізвище або слово"),
    case: str = typer.Option("", "--case", help="справа, шифра або прогін; порожньо — усе"),
    thresh: int = typer.Option(78, "--thresh"),
    limit: int = typer.Option(40, "--limit"),
    context: int = typer.Option(1, "--context"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Знайти рід усіма каналами разом. Нуль друкується лише з журналом заходу."""
    from nyshporka import ops as O

    env = O.call("text.find", {"q": q, "case": case, "thresh": thresh, "limit": limit,
                               "context": context})
    if _answer(env, as_json):
        return
    d = env.data
    for h in d.get("hits") or []:
        head = f"{h.get('name')} · {h.get('page')} · рядок {h.get('line_no')}"
        why = str(h.get("stem_origin") or "q")
        if why != "q":
            label = {"folk": "побутове", "given": "довідник імен",
                     "profile": "профіль"}.get(why, why)
            head += f" · [warn]{label}: {h.get('stem')}[/warn]"
        if h.get("rank_why"):
            head += f" · [muted]↓ {h['rank_why']}[/muted]"
        console.print(f"[bold]{h.get('score')}[/bold]  {head}")
        for b in (h.get("context") or {}).get("before") or []:
            console.print(f"      [muted]↑ {b}[/muted]")
        console.print(f"    [warn]»[/warn] {h.get('line')}")
        for a in (h.get("context") or {}).get("after") or []:
            console.print(f"      [muted]↓ {a}[/muted]")
        if h.get("alt"):
            console.print(f"      [accent]2-й голос:[/accent] [muted]{h['alt']['line']}[/muted]")
    for h in (d.get("anchor") or {}).get("hits") or []:
        console.print(f"[accent]⚓[/accent]  {h.get('name')} · {h.get('page')} · рядок "
                      f"{h.get('line_no')} · [warn]{h.get('matched')}[/warn]")
        console.print(f"    [muted]{h.get('line')}[/muted]")
    led = d["ledger"]
    console.print("")
    console.print(f"[bold]знаменник:[/bold] кадрів {led.get('frames') if led.get('frames') is not None else '?'} · "
                  f"прочитано {led.get('decoded') if led.get('decoded') is not None else '?'} · "
                  f"у сторі прогонів {led['in_store']} із {led['runs']} · "
                  f"сторінок без дублів голосів {led.get('pages_scoped')} · "
                  f"голоси: {', '.join(led.get('voices') or []) or '—'} · письмо: "
                  f"{', '.join(led.get('scripts') or []) or '?'}")
    cache = led.get("cache") or {}
    if cache:
        console.print(f"[muted]свіп: з кешу стору {cache.get('runs', 0)} прогонів, "
                      f"пораховано зараз {cache.get('computed', 0)}[/muted]")
    parts = []
    for ch in led["channels"]:
        if ch["ran"]:
            nums = ""
            if "hits" in ch:
                nums = f" {ch['hits']}"
                if ch.get("pages"):
                    nums += f"/{ch['pages']} стор."
                elif ch["id"] == "surname" and ch["hits"]:
                    nums += " (сторінок не лічено: показ обрізаний)"
            if ch["id"] == "selfcheck":
                nums = f" око {ch['eye']} · знайдено {ch['found']} · подано {ch['shown']}"
                if ch.get("missed"):
                    nums += f" · [warn]пропущено {len(ch['missed'])}[/warn]"
            parts.append(f"[bold]{ch['id']}[/bold] ✓{nums}")
        else:
            parts.append(f"[muted]{ch['id']} ✗[/muted]")
    console.print("[bold]канали:[/bold] " + " · ".join(parts))
    if d.get("stems_dropped"):
        console.print(f"[muted]фрагменти профілю не шукались окремо (склейки в кандидатах): "
                      f"{', '.join(d['stems_dropped'])}[/muted]")
    before = led.get("searched_before") or []
    if before:
        console.print("[muted]раніше: " + "; ".join(
            f"«{x.get('q')}» {x.get('when')} ({', '.join(x.get('channels') or [])})"
            for x in before[:3]) + "[/muted]")
    _notes(env)
    console.print(f"[muted]показано {len(d.get('hits') or [])} із {d.get('total')}[/muted]")



# ── етап 4: гортач і вердикти ────────────────────────────────────────────────
@app.command("sheet")
def sheet_cmd(
    q: str = typer.Argument(..., help="прізвище або слово"),
    case: str = typer.Option(..., "--case", help="справа, шифра або прогін"),
    thresh: int = typer.Option(78, "--thresh"),
    limit: int = typer.Option(60, "--limit", help="кандидатів у гортачі"),
    crops: int = typer.Option(40, "--crops", help="скільком верхнім дати кроп"),
    out: str = typer.Option("", "--out", help="куди покласти HTML"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """HTML-гортач: кандидати з контекстом, другим голосом, кропом і полем вердикту.

    Вердикт «наш рід» виносить людина. Кнопка в гортачі збирає вердикти в JSON;
    далі `nysh text verdicts <файл> --case <справа>`.
    """
    from nyshporka import ops as O

    env = O.call("text.sheet", {"q": q, "case": case, "thresh": thresh, "limit": limit,
                                "crops": crops, "out": out})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d['out']}[/bold]")
    console.print(f"[muted]карток {d['cards']} із {d.get('total')} · кропів {d['crops']} · "
                  f"уже з вердиктом {d.get('known_verdicts', 0)}[/muted]")
    _notes(env)


@app.command("verdicts")
def verdicts_cmd(
    path: str = typer.Argument(..., help="JSON із гортача"),
    case: str = typer.Option(..., "--case", help="справа, шифра або прогін"),
    q: str = typer.Option("", "--q", help="який запит судили"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Занести вердикти гортача у сховище сторінок — і негативні теж."""
    from nyshporka import ops as O

    env = O.call("text.verdicts", {"path": path, "case": case, "q": q})
    if _answer(env, as_json):
        return
    d = env.data
    console.print(f"[bold]{d.get('shifra') or d['case_key']}[/bold]: занесено {d['imported']} "
                  f"вердиктів · аркушів додано {d['pages_added']}, домержено {d['pages_merged']}")
    console.print(f"[muted]{d.get('by_verdict')}[/muted]")
    _notes(env)
