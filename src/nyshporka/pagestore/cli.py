"""nysh pages / nysh records — агентський інтерфейс сховища сторінок.

Контракт для агентів: ПЕРЕД рендером сторінок — `nysh pages status CASE --json`
(скип сканів зі status=full), ПІСЛЯ перегляду — `nysh pages note-batch`.
`--json` → один компактний JSON на stdout і більше нічого; exit 0/1.
CASE — будь-який формат: «DAHMO/315/8433», «АРХІВ 123-1-456»,
«S_<АРХІВ>_F<фонд>_D<справа>», «data/raw/архів_123/spr-456».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.console import Console

from nyshporka.pagestore import query, store
from nyshporka.pagestore.models import Method, PageNote, PageStatus, PageType, Record
from nyshporka.pagestore.store import CaseRef

pages_app = typer.Typer(
    help="Анотації сторінок справ (тип/прізвища/географія) — щоб не дивитись двічі.",
    no_args_is_help=True,
)
records_app = typer.Typer(
    help="Структуровані записи джерел (метрики/сповідки/ревізії).",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _resolve(case: str) -> CaseRef:
    try:
        return store.resolve_case(case)
    except ValueError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


def _emit(data: dict[str, Any], as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    elif human is not None:
        console.print(human)


def _csv(value: str | None) -> list[str]:
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def _allowed(literal: Any) -> str:
    """Дозволені значення — З МОДЕЛІ, а не переписані в довідку рукою.

    🔴 Переписані розходяться. Тут це вже сталось: довідка `--method` називала
    чотири значення, а модель приймала п'ять — `text` («читав лише декод, оком
    не звірено») був невидимий саме для того, хто мав його ставити. Позначка
    методу вирішує, чи можна довіряти прочитанню, тож невидиме значення
    означало чужі помилки, успадковані під виглядом власного перегляду.
    """
    from typing import get_args

    return "/".join(str(x) for x in get_args(literal))


def _read_batch(file: Path | None) -> list[Any]:
    """JSON-масив або JSON-lines із файлу чи stdin."""
    text = file.read_text(encoding="utf-8") if file else sys.stdin.read()
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


# ── nysh pages ──────────────────────────────────────────────────────────────
@pages_app.command("status")
def pages_status(
    case: str = typer.Argument(..., help="Справа у будь-якому форматі."),
    scans: str = typer.Option(None, "--scans", help="Кома-список сканів для точкової перевірки."),
    as_json: bool = typer.Option(False, "--json", help="Компактний JSON на stdout."),
) -> None:
    """Гейт «чи рендерити?»: що вже оброблено, що ні."""
    ref = _resolve(case)
    st = store.case_status(ref, _csv(scans) or None)
    if as_json:
        _emit(st, True)
        return
    console.print(f"[bold]{st['shifra']}[/bold]  {st.get('title') or ''}")
    if "scans" in st:
        for s in st["scans"]:
            if s["noted"]:
                console.print(f"  ✅ {s['scan']}  {s['page_type']}/{s['status']}  "
                              f"прізвищ: {s['surnames_n']}  ({s['noted_date']})")
            else:
                console.print(f"  ▫️ {s['scan']}  не оброблено")
        return
    console.print(f"  на диску: {st['total_disk']}  анотовано: {st['noted']}  "
                  f"записів: {st['records']}  статуси: {st['by_status']}")
    if st.get("unnoted") is not None:
        console.print(f"  необроблені ({st['unnoted_count']}): " +
                      (", ".join(st["unnoted"]) or "—"))


@pages_app.command("note")
def pages_note(
    case: str = typer.Argument(...),
    scan: str = typer.Argument(..., help="Голе ім'я файлу скана: 0030.JPG / page_003."),
    page_type: str = typer.Option(..., "--type", help=_allowed(PageType)),
    surnames: str = typer.Option("", "--surnames", help="Кома-список ЯК У ДЖЕРЕЛІ."),
    places: str = typer.Option("", "--places"),
    years: str = typer.Option("", "--years", help="Кома-список років: 1858,1859."),
    sheet: str = typer.Option("", "--sheet", help="Архівний аркуш: 31зв–32."),
    status: str = typer.Option("full", "--status", help=_allowed(PageStatus)),
    method: str = typer.Option("visual", "--method", help=_allowed(Method)),
    comment: str = typer.Option("", "--comment"),
    agent: str = typer.Option("", "--agent"),
    replace: bool = typer.Option(False, "--replace", help="Замінити анотацію повністю (без merge)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Анотувати одну сторінку."""
    ref = _resolve(case)
    try:
        # 🔴 `type: ignore` тут свідомий і вузький. З командного рядка приходить
        # рядок, а модель хоче перелік — і перевіряти його мусить САМЕ модель:
        # вона єдине місце, де цей перелік визначено, і її повідомлення про
        # хибне значення показує всі допустимі. Продублювати перевірку тут
        # означало б завести другий перелік, який розійдеться з першим.
        note = PageNote(scan=scan, page_type=page_type,  # type: ignore[arg-type]
                        surnames=_csv(surnames),
                        places=_csv(places), years=[int(y) for y in _csv(years)],
                        sheet=sheet, status=status, method=method,  # type: ignore[arg-type]
                        comment=comment, agent=agent)
    except (ValidationError, ValueError) as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    report = store.annotate_pages(ref, [note], replace=replace)
    _emit(report.as_dict(), as_json,
          f"✅ {ref.shifra} {scan}: " +
          ("додано" if report.added else "замінено" if report.replaced else "домержено"))


@pages_app.command("note-batch")
def pages_note_batch(
    case: str = typer.Argument(...),
    file: Path = typer.Option(None, "-f", "--file", help="JSON-масив PageNote (без -f — stdin)."),
    replace: bool = typer.Option(False, "--replace"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Головний bulk-шлях: масив анотацій із файлу або stdin.

    Невалідні елементи пропускаються зі звітом — валідні все одно лягають
    (не втрачати 40 сторінок через одну одруківку).
    """
    ref = _resolve(case)
    try:
        raw_items = _read_batch(file)
    except (OSError, json.JSONDecodeError) as e:
        err_console.print(f"[red]не JSON: {e}[/red]")
        raise typer.Exit(1) from None
    notes, errors = [], []
    for i, item in enumerate(raw_items):
        try:
            notes.append(PageNote.model_validate(item))
        except ValidationError as e:
            errors.append({"index": i, "scan": (item or {}).get("scan") if isinstance(item, dict) else None,
                           "error": str(e)})
    report = store.annotate_pages(ref, notes, replace=replace) if notes else \
        store.MergeReport(path="")
    report.errors = errors
    # 🔴 Ключ сторінки мусить збігатися з ІМЕНЕМ ФАЙЛУ на диску («0106.jpg»), бо
    # саме так `case_status` рахує unnoted. Ключ без розширення проходить
    # валідацію моделі, але зі сканами не матчиться — і сторінка, яку вже
    # дивилися оком, лишається в черзі на рендер (2026-08-16: так розійшлись
    # 62 ключі у 23 справах). Тека без зображень (справа з PDF, де конвенція
    # «page_003») дає порожній `disk` — там попередження не буде.
    disk = set(store._disk_scans(ref))
    off_disk = [n.scan for n in notes if n.scan not in disk] if disk else []
    out = {"key": ref.key, **report.as_dict(),
           "ok": len(notes), "failed": len(errors), "off_disk": off_disk}
    _emit(out, as_json,
          f"✅ {ref.shifra}: додано {len(report.added)}, домержено {len(report.merged)}, "
          f"замінено {len(report.replaced)}, помилок {len(errors)}")
    if off_disk and not as_json:
        err_console.print(
            f"[yellow]⚠ {len(off_disk)} сканів немає на диску теки справи "
            f"({', '.join(off_disk[:5])}{'…' if len(off_disk) > 5 else ''}) — "
            f"ключ має бути ІМЕНЕМ ФАЙЛУ («0106.jpg»), інакше `pages status` "
            f"рахуватиме сторінку непереглянутою[/yellow]")
    if errors and not as_json:
        # 🔴 Ім'я `e` тут НЕ перевикористовується. Python видаляє змінну винятку
        # на виході з `except`, і хоча цикл присвоює її заново (тобто працює),
        # перевіряч типів цього не доводить і мусить попереджати — а нам той
        # клас попереджень потрібен увімкненим: справжнє читання видаленої
        # змінної падає `NameError` уже в бойовому прогоні, посеред партії.
        for bad in errors:
            err_console.print(
                f"[yellow]#{bad['index']} ({bad['scan']}): {bad['error']}[/yellow]")
    if not notes:
        raise typer.Exit(1)


@pages_app.command("grep")
def pages_grep(
    q: str = typer.Argument(..., help="Прізвище (будь-яка писемність)."),
    thresh: int = typer.Option(80, "--thresh", help="Поріг fuzzy 50-100."),
    case: str = typer.Option(None, "--case", help="Обмежити однією справою."),
    places: bool = typer.Option(False, "--places", help="Шукати по місцях, не прізвищах."),
    limit: int = typer.Option(200, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Fuzzy-пошук по всіх збережених прізвищах (кирилиця↔латинка через нормалізацію)."""
    key = _resolve(case).key if case else None
    res = query.grep_surnames(q, thresh=max(50, min(100, thresh)), case_key=key,
                              places=places, limit=limit)
    if as_json:
        _emit(res, True)
        return
    if res.get("error"):
        err_console.print(f"[red]{res['error']}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{res['total']}[/bold] хітів у {res['cases']} справах "
                  f"(поріг {res['thresh']}, стеми {res['stems']})")
    for h in res["hits"]:
        console.print(f"  {h['score']:>3}  {h['shifra']}  {h['scan']}  "
                      f"«{h['matched']}»  [{h['page_type']}/{h['status']}]  {h['comment']}")


@pages_app.command("show")
def pages_show(
    case: str = typer.Argument(...),
    scan: str = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Дамп анотацій справи (або однієї сторінки)."""
    ref = _resolve(case)
    cf = store.load_case(ref)
    if cf is None:
        _emit({"key": ref.key, "pages": {}, "records": []}, as_json,
              f"{ref.shifra}: сховище порожнє")
        return
    if scan:
        note = cf.pages.get(scan)
        if note is None:
            err_console.print(f"[red]скан «{scan}» не анотовано[/red]")
            raise typer.Exit(1)
        _emit(note.model_dump(mode="json"), as_json,
              json.dumps(note.model_dump(mode="json"), ensure_ascii=False, indent=1))
        return
    dump = cf.model_dump(mode="json")
    _emit(dump, as_json, json.dumps(dump, ensure_ascii=False, indent=1))


# ── nysh records ────────────────────────────────────────────────────────────
@records_app.command("add")
def records_add(
    case: str = typer.Argument(...),
    file: Path = typer.Option(None, "-f", "--file", help="JSON-масив Record (без -f — stdin)."),
    replace: bool = typer.Option(False, "--replace", help="Стерти всі записи справи перед внесенням."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Внести структуровані записи (upsert по rid). Тільки batch — записи заскладні для прапорців."""
    ref = _resolve(case)
    try:
        raw_items = _read_batch(file)
    except (OSError, json.JSONDecodeError) as e:
        err_console.print(f"[red]не JSON: {e}[/red]")
        raise typer.Exit(1) from None
    recs, errors = [], []
    for i, item in enumerate(raw_items):
        try:
            recs.append(Record.model_validate(item))
        except ValidationError as e:
            errors.append({"index": i, "error": str(e)})
    report = store.add_records(ref, recs, replace=replace) if recs else \
        store.MergeReport(path="")
    report.errors = errors
    out = {"key": ref.key, **report.as_dict(),
           "rids": [r.rid for r in recs], "ok": len(recs), "failed": len(errors)}
    _emit(out, as_json,
          f"✅ {ref.shifra}: записів додано {len(report.added)}, оновлено {len(report.merged)}, "
          f"помилок {len(errors)}")
    if errors and not as_json:
        for bad in errors:
            err_console.print(f"[yellow]#{bad['index']}: {bad['error']}[/yellow]")
    if not recs:
        raise typer.Exit(1)


@records_app.command("grep")
def records_grep(
    q: str = typer.Argument(...),
    role: str = typer.Option(None, "--role", help="child/father/mother/godfather/…"),
    rtype: str = typer.Option(None, "--rtype", help="birth/marriage/death/…"),
    case: str = typer.Option(None, "--case"),
    thresh: int = typer.Option(80, "--thresh"),
    limit: int = typer.Option(200, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Fuzzy-пошук по учасниках записів."""
    key = _resolve(case).key if case else None
    res = query.grep_records(q, thresh=max(50, min(100, thresh)), case_key=key,
                             role=role, rtype=rtype, limit=limit)
    if as_json:
        _emit(res, True)
        return
    if res.get("error"):
        err_console.print(f"[red]{res['error']}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{res['total']}[/bold] хітів у {res['cases']} справах")
    for h in res["hits"]:
        console.print(f"  {h['score']:>3}  {h['shifra']}  {h['rtype']} {h['date'] or ''}  "
                      f"{h['role']}: «{h['name']}»  [{','.join(h['scans'])}]  rid={h['rid']}")


@records_app.command("show")
def records_show(
    case: str = typer.Argument(...),
    rid: str = typer.Option(None, "--rid"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Дамп записів справи (або одного за rid)."""
    ref = _resolve(case)
    cf = store.load_case(ref)
    recs = cf.records if cf else []
    if rid:
        recs = [r for r in recs if r.rid == rid]
        if not recs:
            err_console.print(f"[red]запису rid={rid} немає[/red]")
            raise typer.Exit(1)
    dump = [r.model_dump(mode="json") for r in recs]
    _emit({"key": ref.key, "records": dump}, as_json,
          json.dumps(dump, ensure_ascii=False, indent=1))
