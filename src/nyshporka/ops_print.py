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
    args=PrintStatusArgs, agent=False, section=SECTION,
    next_hints=(("print.assemble", "зібрати роки з прочитаних номерів"),))
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
    args=PrintAdoptArgs, mutates=True, agent=False, section=SECTION,
    next_hints=(("print.assemble", "зібрати роки з прочитаних номерів"),))
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
    args=PrintAssembleArgs, mutates=True, agent=False, section=SECTION,
    next_hints=(("print.pack", "спакувати повні роки для Супряги"),))
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


class PrintPackArgs(BaseModel):
    vydannia: str = Field(description="код видання")
    year: int = Field(default=0, description="лише цей рік; 0 — усі повні")
    out: str = Field(default="", description="тека для пакетів; порожньо — вихідна пулу")
    dry_run: bool = Field(default=False, description="лише показати, нічого не писати")


@op("print.pack", summary="Спакувати повні роки видання для Супряги",
    args=PrintPackArgs, mutates=True, agent=False, section=SECTION,
    next_hints=(("print.publish", "віддати пакети в Супрягу"),))
def print_pack(a: PrintPackArgs) -> Envelope:
    """Кожен ПОВНИЙ рік — один пакет `VYD/<код>/<рік>` з переліком номерів."""
    from pathlib import Path

    from nyshporka import ops as O
    from nyshporka import print_edition as PE

    code = a.vydannia.strip().upper()
    rec = PE.load_record(code)
    if not rec:
        return fail(f"видання {code} не записано — спершу `nysh cloud go --print`")
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
        got = O.call("share.pack_print", {
            "src": str(y.run_dir), "vydannia": code, "year": y.year,
            "title": rec.get("title") or code, "ocr_by": PE.OCR_BY, "ocr_layer": "ocr",
            "page_unit": "page", "publisher_place": rec.get("city") or "",
            "issues": str(y.run_dir / "issues.json"),
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
    args=PrintPublishArgs, mutates=True, agent=False, section=SECTION)
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
