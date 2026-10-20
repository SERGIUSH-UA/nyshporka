"""🖨 Операції друкованих видань: стан, збирання років, пакування, віддача.

Читає друк лише орендована машина (`nysh cloud go --print`): тут облік і текст,
а не розпізнавання. Повний шлях людини — `nysh print status` → (захід) →
`nysh print assemble` (наглядач кличе його сам після забору) → `nysh print
pack` → `nysh print publish`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "htr"


class PrintStatusArgs(BaseModel):
    vydannia: str = Field(default="", description="код видання; порожньо — усі")


# Операції друку — не в стартовому переліку агента (стеля 18): агент кличе їх
# через `nysh print …` / `nysh op`, а не першим кроком у новій розмові.
@op("print.status", summary="Друковані видання: роки, номери, прочитане, пропуски",
    args=PrintStatusArgs, section=SECTION,
    next_hints=(("print.assemble", "зібрати роки з прочитаних номерів"),),
    when="друковані видання: роки, номери, прочитане, пропуски")
def print_status(a: PrintStatusArgs) -> Envelope:
    """Що записано про видання й скільки з нього прочитано — нічого не пише."""
    from nyshporka import print_edition as PE

    got = PE.status(a.vydannia)
    env = ok({"editions": got})
    if not got:
        return env.warn("no_editions", "видань ще немає: їх записує `nysh cloud go "
                                       "--print <тека видання> --vydannia <КОД>`")
    for ed in got:
        if ed["unparsed"]:
            env.warn("unparsed", f"{ed['code']}: тек, що не розібрались як номер, "
                                 f"{len(ed['unparsed'])} — напр. {ed['unparsed'][0]}")
    return env


class PrintAdoptArgs(BaseModel):
    vydannia: str = Field(description="код видання латинкою (KOLSELO_PYR)")
    title: str = Field(default="", description="назва видання")
    city: str = Field(default="", description="місто видання")
    issues_root: str = Field(default="", description="де лежать теки номерів; "
                                                     "порожньо — derived/print/issues")


@op("print.adopt", summary="Записати видання з уже прочитаних номерів (кадри деінде)",
    args=PrintAdoptArgs, mutates=True, section=SECTION,
    next_hints=(("print.assemble", "зібрати роки з прочитаних номерів"),),
    when="друковане видання з уже прочитаних номерів, кадри деінде")
def print_adopt(a: PrintAdoptArgs) -> Envelope:
    """Видання, номери якого прочитано, а кадрів на цій машині немає.

    Звичайно видання записує `cloud go --print` із теки кадрів. Коли кадри лежать
    у чужому сховищі, а тексти номерів уже вдома, запис робиться з тек тексту:
    номер — за ім'ям прогону і `case_key` мети. Наскрізних номерів в імені прогону
    немає, тож пропуски номерів (`missing_numbers`) тут не рахуються.
    """
    from pathlib import Path

    from nyshporka import print_edition as PE

    try:
        got = PE.adopt(a.vydannia, title=a.title, city=a.city,
                       issues_root=Path(a.issues_root) if a.issues_root else None)
    except ValueError as exc:
        return fail(str(exc))
    env = ok({"record": str(got.path), "issues": got.issues, "years": got.years,
              "skipped": got.skipped[:50]})
    if not got.issues:
        return env.warn("nothing_adopted",
                        f"тек номерів {a.vydannia.lower()}_* з метою VYD/{a.vydannia.upper()}/… "
                        "не знайдено")
    env.warn("no_running_numbers", "наскрізних номерів в іменах прогонів немає — "
                                   "пропуски номерів у роках не рахуються")
    if got.skipped:
        env.warn("skipped", f"не розібрано як номер видання: {len(got.skipped)} тек, "
                            f"напр. {got.skipped[0]}")
    return env


class PrintAssembleArgs(BaseModel):
    vydannia: str = Field(default="", description="код видання; порожньо — усі")
    index: bool = Field(default=True, description="одразу покласти роки в текстовий стор")


@op("print.assemble", summary="Зібрати роки видання з прочитаних номерів",
    args=PrintAssembleArgs, mutates=True, section=SECTION,
    next_hints=(("print.pack", "спакувати повні роки для Супряги"),),
    when="зібрати роки газети чи видання з прочитаних номерів")
def print_assemble(a: PrintAssembleArgs) -> Envelope:
    """Роки `VYD/<код>/<рік>` із номерів — і одразу в пошук.

    Повторний виклик безпечний: рік збирається наново цілим каталогом.
    """
    from nyshporka import ops as O
    from nyshporka import print_edition as PE

    years = PE.assemble(a.vydannia)
    if not years:
        return fail("нема з чого збирати: видань із прочитаними номерами не знайдено "
                    "(`nysh print status`)")
    indexed: list[str] = []
    env = ok({"years": [y.as_dict() for y in years], "indexed": indexed})
    if a.index:
        for y in years:
            if not y.read:
                continue
            got = O.call("text.index", {"case": y.run_dir.name})
            if got.ok:
                indexed.append(y.run_dir.name)
            else:
                env.warn("index_failed", f"{y.run_dir.name}: {got.error}")
    for y in years:
        if not y.complete:
            env.warn("year_incomplete",
                     f"{y.key}: прочитано {y.read} з {y.pages} сторінок — рік у пошуку "
                     f"є, але пакуватиметься лише повним")
        if y.missing_numbers:
            env.warn("numbers_missing",
                     f"{y.key}: у зібранні немає номерів (наскрізні) "
                     f"{', '.join(y.missing_numbers[:12])}"
                     + ("…" if len(y.missing_numbers) > 12 else ""))
    return env


class PrintCardArgs(BaseModel):
    vydannia: str = Field(description="код видання")
    title: str | None = Field(default=None, description="назва з шапки, без року")
    city: str | None = Field(default=None, description="місто видання")
    doc_type: str | None = Field(default=None, description="newspaper | gazette | directory")
    holder: str | None = Field(default=None, description="де лежить підшивка, з якої скани")
    places: list[str] | None = Field(default=None, description="місця для пошуку: "
                                                               "район, область по роках")
    organ: list[str] | None = Field(default=None, description="чий орган: «1932–1937: Орган …»")
    frequency: str | None = Field(default=None, description="як часто виходила")
    scans_url: str | None = Field(default=None, description="посилання на скани підшивки")
    scans_label: str | None = Field(default=None, description="підпис посилання на скани")
    source_terms: str | None = Field(default=None, description="умови тримача сканів")
    note: str | None = Field(default=None, description="ще речення до опису кожного року")


@op("print.card", summary="Картка друкованого видання: що стоїть на картці в Супрязі",
    args=PrintCardArgs, mutates=True, section=SECTION,
    next_hints=(("print.pack", "спакувати повні роки для Супряги"),),
    skill="share-case",
    when="картка друкованого видання для Супряги")
def print_card(a: PrintCardArgs) -> Envelope:
    """Показати й дописати картку видання. Без аргументів — лише показати й назвати,
    чого бракує для пакування."""
    from nyshporka import print_edition as PE

    code = a.vydannia.strip().upper()
    fields = a.model_dump(exclude={"vydannia"})
    try:
        rec = (PE.set_card(code, **fields) if any(v is not None for v in fields.values())
               else PE.load_record(code))
    except ValueError as exc:
        return fail(str(exc))
    if not rec:
        return fail(f"видання {code} не записано — `nysh cloud go --print` або "
                    f"`nysh print adopt {code}`")
    card = {k: rec.get(k) for k in PE.CARD_FIELDS if rec.get(k)}
    gaps = PE.card_gaps(rec)
    env = ok({"code": code, "card": card, "gaps": gaps})
    for g in gaps:
        env.warn("card_gap", g)
    if not rec.get("scans_url"):
        env.warn("no_scans_link", "посилання на скани немає — у пулі не буде «Подивіться "
                                  "саму книгу» (--scans-url, якщо скани десь відкриті)")
    return env


class PrintPackArgs(BaseModel):
    vydannia: str = Field(description="код видання")
    year: int = Field(default=0, description="лише цей рік; 0 — усі повні")
    out: str = Field(default="", description="тека для пакетів; порожньо — вихідна пулу")
    dry_run: bool = Field(default=False, description="лише показати, нічого не писати")


@op("print.pack", summary="Спакувати повні роки видання для Супряги",
    args=PrintPackArgs, mutates=True, section=SECTION,
    next_hints=(("print.publish", "віддати пакети в Супрягу"),),
    skill="share-case",
    when="спакувати повні роки друкованого видання для Супряги")
def print_pack(a: PrintPackArgs) -> Envelope:
    """Кожен ПОВНИЙ рік — один пакет `VYD/<код>/<рік>` з переліком номерів.

    Картка (`nysh print card`) їде в кожен рік: місто й жанр — на картку в пулі,
    місця — у пошук, посилання на скани — «Подивіться саму книгу», а опис року
    (чий орган, скільки номерів, перший і останній, підшивка) — нотаткою.
    """
    import json
    from pathlib import Path

    from nyshporka import ops as O
    from nyshporka import print_edition as PE

    code = a.vydannia.strip().upper()
    rec = PE.load_record(code)
    if not rec:
        return fail(f"видання {code} не записано — спершу `nysh cloud go --print`")
    gaps = PE.card_gaps(rec)
    if gaps:
        # 🔴 Без картки рік у пулі — «Без назви», без міста, жанру й підшивки, і
        # виправляти це потім — по запиту модерації на кожен рік окремо.
        return fail(f"картка видання {code} неповна — спершу `nysh print card {code} …`:\n"
                    + "\n".join(f"  · {g}" for g in gaps))
    years = [y for y in PE.assemble(code) if not a.year or y.year == a.year]
    if not years:
        return fail(f"у видання {code} немає року {a.year}" if a.year
                    else f"у видання {code} ще немає зібраних років")
    packs: list[dict[str, Any]] = []
    skipped: list[str] = []
    env = ok({"packs": packs, "skipped": skipped})
    for y in years:
        if not y.complete:
            skipped.append(y.key)
            env.warn("year_incomplete", f"{y.key}: прочитано {y.read} з {y.pages} — "
                                        f"не пакую (сторінки зсунулись би в номерах)")
            continue
        rows_path = y.run_dir / "issues.json"
        try:
            rows = json.loads(rows_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        got = O.call("share.pack_print", {
            "src": str(y.run_dir), "vydannia": code, "year": y.year,
            "title": rec["title"], "ocr_by": PE.OCR_BY, "ocr_layer": "ocr",
            "page_unit": "page", "publisher_place": rec["city"],
            "place": PE.places_for(rec, y.year), "doc_type": rec["doc_type"],
            "scans_url": str(rec.get("scans_url") or ""),
            "scans_label": str(rec.get("scans_label") or ""),
            "source_terms": str(rec.get("source_terms") or ""),
            "note": PE.year_note(rec, y.year, rows, y.pages),
            "issues": str(rows_path),
            "out": str(Path(a.out) / f"vyd_{code.lower()}_{y.year}.nyshtext") if a.out else "",
            "dry_run": a.dry_run})
        if not got.ok:
            env.warn("pack_failed", f"{y.key}: {got.error}")
            skipped.append(y.key)
            continue
        packs.append({"key": y.key, "path": (got.data or {}).get("path"),
                      "pages": y.pages})
    return env


class PrintPublishArgs(BaseModel):
    vydannia: str = Field(description="код видання")
    year: int = Field(default=0, description="лише цей рік; 0 — усі повні")


# 🔴 `agent=False`, як і `share.publish`: віддати в пул — рішення людини.
@op("print.publish", summary="Віддати повні роки видання в Супрягу",
    args=PrintPublishArgs, mutates=True, section=SECTION,
    skill="share-case",
    when="віддати роки друкованого видання в Супрягу")
def print_publish(a: PrintPublishArgs) -> Envelope:
    """Спакувати повні роки й віддати кожен у пул."""
    from nyshporka import ops as O

    packed = O.call("print.pack", {"vydannia": a.vydannia, "year": a.year})
    if not packed.ok:
        return packed
    done: list[dict[str, Any]] = []
    env = ok({"published": done, "skipped": (packed.data or {}).get("skipped") or []})
    for p in (packed.data or {}).get("packs") or []:
        got = O.call("share.publish", {"path": str(p["path"])})
        if got.ok:
            done.append({"key": p["key"], **(got.data or {})})
        else:
            env.warn("publish_failed", f"{p['key']}: {got.error}")
    return env
