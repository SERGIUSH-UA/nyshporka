"""⚙️ Операції, доступні зараз.

Перелік навмисно короткий: сюди потрапляє лише те, чий домен уже в пакеті.
Дописувати операції «на майбутнє» не можна — tool, який відповідає «ще не
реалізовано», гірший за відсутній: агент витрачає на нього хід і довіру.

Імпорт цього модуля наповнює `core.ops.REGISTRY`, тож він має статись до
першого звернення до реєстру (див. `nyshporka.ops`).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

if TYPE_CHECKING:
    from nyshporka.sources.base import Source
    from nyshporka.sources.registry import Registry


# ── простір ──────────────────────────────────────────────────────────────────
@op("workspace.info", summary="Де лежить дослідження і що в ньому є")
def workspace_info(_: NoArgs) -> Envelope:
    from nyshporka.core import lock
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    holder = lock.read(ws.root)
    env = ok({
        "root": str(ws.root),
        "name": ws.name,
        "origin": ws.origin,
        "case_roots": [str(p) for p in ws.case_roots()],
        "exists": {"data": ws.data.is_dir(), "reports": ws.reports.is_dir()},
        "locked_by": holder.as_dict() if holder else None,
    })
    if not ws.data.is_dir():
        env.warn("empty_workspace",
                 "у просторі ще немає теки data — це новий простір")
    return env


# ── джерела ──────────────────────────────────────────────────────────────────
def _registry() -> Registry:
    """Реєстр джерел, прив'язаний до простору (там кеші й зібрані каталоги)."""
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.sources import load

    try:
        root = workspace().root
    except WorkspaceError:
        # Без простору мережеві джерела працюють обмежено (кешу немає), але
        # реєстр мусить збиратись: інакше `sources.list` мовчав би про них.
        root = None
    return load(root)


def _source(source_id: str) -> Source:
    from nyshporka.sources.base import SourceError

    reg = _registry()
    src = reg.get(source_id)
    if src is None:
        known = ", ".join(s.id for s in reg.all())
        raise SourceError(f"джерела {source_id!r} немає. Є: {known}")
    return src


@op("sources.list", summary="Звідки можна брати матеріал")
def sources_list(_: NoArgs) -> Envelope:
    reg = _registry()
    env = ok({"sources": [{"id": s.id, "label": s.label, "caps": sorted(s.caps)}
                          for s in reg.all()]})
    for name, why in reg.broken:
        # Зламаний плагін називається поіменно: «мого архіву немає в списку»
        # інакше не має пояснення, і причину шукатимуть у своїх налаштуваннях.
        env.warn("broken_source", f"джерело «{name}» не завантажилось: {why}")
    return env


class LookArgs(BaseModel):
    path: str = Field(description="тека зі сканами, PDF або тека з PDF")


@op("material.look", summary="Що це за матеріал: скільки кадрів, одна справа чи багато",
    args=LookArgs)
def material_look(a: LookArgs) -> Envelope:
    from nyshporka.sources.local import LocalSource, inspect

    shape = inspect(a.path)
    data = {"kind": shape.kind, "path": str(shape.path), "usable": shape.usable,
            "explain": shape.explain(), "images": shape.images,
            "pdfs": shape.pdfs, "pages": shape.pages,
            "cases": [{"ref": c.ref, "label": c.label, "frames": c.frames}
                      for c in shape.cases]}
    env = ok(data)
    if shape.kind == "cases":
        # 🔴 Це не помилка й не успіх: тека містить БАГАТО справ. Мовчазне
        # «усе гаразд» призвело б до прогону на нуль сторінок.
        env.warn("many_cases",
                 f"це не одна справа, а {len(shape.cases)} — оберіть потрібну")
        return env
    if not shape.usable:
        env.warn("not_usable", shape.explain())
        return env
    m = LocalSource().manifest(str(shape.path))
    data["frames"] = m.frames
    data["bytes"] = m.bytes_estimate
    return env


class CatalogSearchArgs(BaseModel):
    q: str = Field(description="назва села, прізвище чи слово із заголовка справи")
    source: str = Field(default="", description="одне джерело; порожньо = усі, що вміють шукати")
    limit: int = Field(default=30, ge=1, le=200)


@op("catalog.search", summary="Де взагалі є щось про моє село",
    args=CatalogSearchArgs, mutates=False)
def catalog_search(a: CatalogSearchArgs) -> Envelope:
    """Пошук по каталогах джерел.

    🔴 Нуль тут ЗАВЖДИ зі знаменником. Джерело, яке не може шукати (каталог не
    зібрано, дерево не завантажене), не додає нуль до суми — воно потрапляє в
    `unavailable` з причиною й готовою командою. Інакше «0 знахідок у трьох
    архівах» означало б «дивились у трьох», хоча дивились в одному, і напрям
    пошуку закрився б висновком, якого ніхто не робив.
    """
    from nyshporka.sources.base import SourceError, supports

    reg = _registry()
    picked = [reg.get(a.source)] if a.source else reg.with_cap("search")
    if a.source and picked[0] is None:
        return fail(f"джерела {a.source!r} немає")
    hits: list[dict[str, object]] = []
    searched: list[str] = []
    unavailable: list[dict[str, str]] = []
    #: На чому саме шукали — вкладений зріз чи зібраний обходом, і від якої дати.
    basis: list[dict[str, Any]] = []
    for src in picked:
        if src is None or not supports(src, "search"):
            continue
        try:
            found = src.search(a.q, limit=a.limit)
        except SourceError as exc:
            unavailable.append({"source": src.id, "why": str(exc)})
            continue
        except Exception as exc:  # мережа, розмітка, побитий кеш
            unavailable.append({"source": src.id, "why": f"{type(exc).__name__}: {exc}"})
            continue
        searched.append(src.id)
        # 🔴 Чим саме шукали — частина знаменника. Вкладений зріз каталогу
        # СТАРІЄ: «не знайшлось» у ньому означає «не було на дату зрізу», а не
        # «не існує», і без дати ці два висновки не відрізнити.
        note = getattr(src, "catalog_source", None)
        if callable(note):
            kind, meta = note()
            if kind == "bundled":
                basis.append({"source": src.id, "kind": "вкладений зріз",
                              "taken": str(meta.get("taken") or ""),
                              "rows": meta.get("rows"),
                              "regions": meta.get("regions") or None})
            elif kind == "workspace":
                basis.append({"source": src.id, "kind": "зібраний на місці"})
        hits.extend({"source": h.source, "ref": h.ref, "title": h.title,
                     "years": h.years, "place": h.place, "shifra": h.shifra,
                     "frames": h.frames, "acquirable": h.acquirable, "note": h.note}
                    for h in found)
    env = ok({"q": a.q, "hits": hits[:a.limit],
              "coverage": {"searched": searched, "unavailable": unavailable,
                           "basis": basis}})
    for b in basis:
        if b.get("kind") != "вкладений зріз" or not b.get("taken"):
            continue
        where = ""
        if b.get("regions"):
            # 🔴 Покажчик плівок є НЕ ВСЮДИ: у більшості регіонів дзеркала
            # `folder_meta` це голий підпис теки. Не сказати, які регіони він
            # накриває, означало б видати «нема в покажчику» за «нема на плівках».
            where = f", накриває лише: {', '.join(b['regions'])}"
        env.warn("stale_catalog",
                 f"{b['source']}: шукали у ВКЛАДЕНОМУ зрізі від {b['taken']} "
                 f"({b.get('rows') or '?'} записів{where}). Відтоді могло "
                 f"додатись — свіже збирається на місці")
    for u in unavailable:
        env.warn("source_unavailable", f"{u['source']}: {u['why']}")
    if not searched:
        env.warn("no_denominator",
                 "жодне джерело не змогло шукати — цей нуль НІЧОГО не означає")
    return env


class BrowseArgs(BaseModel):
    source: str = Field(description="id джерела (`sources.list`)")
    ref: str = Field(default="", description="вузол; порожньо = верхній рівень")


@op("catalog.browse", summary="Що лежить у фонді, описі, теці", args=BrowseArgs,
    mutates=False)
def catalog_browse(a: BrowseArgs) -> Envelope:
    from nyshporka.sources.base import SourceError

    try:
        src = _source(a.source)
        nodes = src.browse(a.ref or None)
    except SourceError as exc:
        return fail(str(exc))
    return ok({"source": a.source, "ref": a.ref,
               "nodes": [{"ref": n.ref, "label": n.label, "kind": n.kind,
                          "frames": n.frames, "size": n.size} for n in nodes]})


class ManifestArgs(BaseModel):
    source: str = Field(description="id джерела")
    ref: str = Field(description="адреса справи чи плівки в цьому джерелі")


@op("catalog.manifest", summary="Що саме принесе завантаження — ДО того, як почалось",
    args=ManifestArgs, mutates=False)
def catalog_manifest(a: ManifestArgs) -> Envelope:
    from nyshporka.sources.base import SourceError

    try:
        m = _source(a.source).manifest(a.ref)
    except SourceError as exc:
        return fail(str(exc))
    env = ok({"source": m.source, "ref": m.ref, "title": m.title,
              "frames": m.frames, "bytes_estimate": m.bytes_estimate,
              "sheets": [{"from": s.frm, "to": s.to, "label": s.label}
                         for s in m.sheets],
              "meta": {k: v for k, v in m.meta.items() if k != "files"}})
    if not m.sheets and m.meta.get("meta_rows"):
        # Підписи теки є, а поаркушевого покажчика немає — і це різні речі.
        env.warn("no_sheet_index",
                 "покажчика аркушів у цій плівці немає, лише підпис теки — "
                 "яке село на якому кадрі, звідси не видно")
    return env


# ── мої справи ───────────────────────────────────────────────────────────────
class CasesArgs(BaseModel):
    q: str = Field(default="", description="підрядок: шифра, назва, місце")
    repo: str = ""
    htr: str = Field(default="", description="none | partial | pysar | diak | both")
    year: str = Field(default="", description="рік або діапазон «1840-1860»")
    place: str = ""
    limit: int = Field(default=60, ge=1, le=500)


@op("cases.list", summary="Мої справи: що є, що прочитано, що прошукано",
    args=CasesArgs, mutates=False)
def cases_list(a: CasesArgs) -> Envelope:
    """Реєстр справ із застереженням про свіжість.

    🔴 Застереження — не косметика. Реєстр це зріз п'яти сховищ, і будь-який
    прогін робить його старим за хвилини. Застарілий зріз небезпечніший за
    відсутній: він виглядає як відповідь («декоду немає») там, де декод зробили
    годину тому, — і саме по ньому вирішують, що гнати далі.
    """
    from nyshporka.cases import db

    try:
        rows = db.query_rows(q=a.q, repo=a.repo, htr=a.htr, year=a.year,
                             place=a.place, limit=a.limit)
    except Exception as exc:
        return fail(f"реєстр справ недоступний ({type(exc).__name__}: {exc}) — "
                    f"зберіть його командою `nysh cases build`")
    env = ok({"cases": rows, "shown": len(rows)})
    try:
        st = db.staleness()
    except Exception:
        st = {}
    if st.get("stale"):
        env.stale_because(st.get("reasons") or [], fix="nysh cases build")
    return env


# ── пошук по прочитаному ─────────────────────────────────────────────────────
class SearchArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    where: Literal["decode", "pages", "records"] = Field(
        default="decode",
        description="decode — тексти прогонів; pages — виписані прізвища; "
                    "records — учасники розібраних записів")
    case: str = Field(default="", description="обмежити однією справою")
    thresh: int = Field(default=80, ge=50, le=100)
    limit: int = Field(default=100, ge=1, le=500)


@op("search.run", summary="Знайти прізвище в тому, що вже прочитано",
    args=SearchArgs, mutates=False)
def search_run(a: SearchArgs) -> Envelope:
    """🔴 Нуль ЗАВЖДИ зі знаменником.

    Порожній результат від пошуку по декоду означає «в цих N прогонах не
    знайшлось», а не «цього немає»: декодовано завжди меншу частину того, що є
    на диску. Тому у відповіді йде `coverage` — по скількох прогонах і скількох
    сторінках шукали. Без цього числа нуль читається як вирок.
    """
    if a.where == "decode":
        from nyshporka import htr_store

        res = htr_store.search(a.q, name=a.case or None, thresh=a.thresh,
                               limit=a.limit)
        runs = htr_store.list_cases()
        pages = sum(int(c.get("pages") or 0) for c in runs)
        env = ok({"hits": res.get("hits") or [],
                  "coverage": {"runs": res.get("cases") or len(runs),
                               "pages": pages, "thresh": a.thresh}})
        if res.get("error"):
            env.warn("bad_query", str(res["error"]))
        if not (res.get("hits") or []):
            env.warn("zero_with_denominator",
                     f"не знайшлось у {res.get('cases') or len(runs)} прогонах "
                     f"({pages} сторінок). Це НЕ означає, що запису немає — "
                     f"означає, що його немає в прочитаному.")
        return env

    from nyshporka.pagestore import query

    if a.where == "pages":
        res = query.grep_surnames(a.q, thresh=a.thresh, case_key=a.case or None,
                                  limit=a.limit)
    else:
        res = query.grep_records(a.q, thresh=a.thresh, case_key=a.case or None,
                                 limit=a.limit)
    return ok(res)


# ── гортач ───────────────────────────────────────────────────────────────────
class PageArgs(BaseModel):
    run: str = Field(description="ім'я прогону (тека в reports/htr)")
    page: str = Field(default="", description="скан; порожньо = перелік сторінок")


@op("page.text", summary="Що прочитано на сторінці й де саме лежить кожен рядок",
    args=PageArgs, mutates=False)
def page_text(a: PageArgs) -> Envelope:
    from nyshporka import htr_store as S

    if not a.page:
        pages = S.case_pages(a.run)
        if pages is None:
            return fail(f"немає прогону «{a.run}»")
        return ok(pages)
    txt = S.read_page_text(a.run, a.page)
    if txt is None:
        return fail(f"немає сторінки «{a.page}» у прогоні «{a.run}»")
    geo = S.page_lines(a.run, a.page) or {}
    env = ok({**txt, "lines": geo})
    if not geo.get("has"):
        # Рамок немає — гортач покаже сторінку цілком. Це не помилка, але
        # мовчати не можна: перегляд рядка й перегляд сторінки коштують по-різному.
        env.warn("no_line_boxes",
                 "прогін не зберіг рамок рядків — показати окремий рядок "
                 "не вийде, лише сторінку цілком")
    return env


class ViewArgs(BaseModel):
    run: str = Field(description="ім'я прогону")
    page: str = Field(description="скан сторінки")
    line: int | None = Field(default=None, description="номер рядка з нуля")
    region: Literal["line", "page"] = Field(
        default="line",
        description="line — вирізка рядка (дешево); page — уся сторінка (дорого)")
    pad: int = Field(default=24, ge=0, le=200,
                     description="запас навколо рядка в пікселях")
    annotate: bool = Field(
        default=True,
        description="домалювати рамку рядка — без неї видно кілька рядків "
                    "і незрозуміло, який оцінюють")


@op("page.view", summary="Подивитись на рядок чи сторінку ОКОМ", args=ViewArgs,
    mutates=False)
def page_view(a: ViewArgs) -> Envelope:
    """🔴 Центральна операція звірки: виявити ≠ перевірити.

    Машина подає кандидата, вирішує око — і другий рушій тут не суддя, бо
    ознака в пікселях. Дефолт — РЯДОК: ціла сторінка коштує моделі вчетверо
    дорожче, а звірок за сеанс бувають десятки.
    """
    from nyshporka.htr.view import ViewError, shot

    try:
        s = shot(a.run, a.page, line=a.line, region=a.region, pad=a.pad,
                 annotate=a.annotate)
    except ViewError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")
    env = ok({**s.as_dict(), "image": s.data_url})
    if s.note:
        env.warn("view_fallback", s.note)
    return env


# ── експорт ──────────────────────────────────────────────────────────────────
class ExportArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    what: Literal["pages", "records"] = "records"


@op("export.case", summary="Викласти прочитане зі справи таблицею", args=ExportArgs,
    mutates=False)
def export_case(a: ExportArgs) -> Envelope:
    """Прочитане зі справи — у плаский вигляд, придатний до таблиці.

    🔴 Кожен рядок несе СКАН, а не лише текст. Виписка без посилання на аркуш —
    це переказ: перевірити його можна тільки перечитавши всю справу, тобто
    ніяк. Саме тому тут немає режиму «лише імена».
    """
    from nyshporka.pagestore import store

    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    cf = store.load_case(ref)
    if cf is None:
        return fail(f"по справі {ref.shifra} ще нічого не занесено")

    if a.what == "pages":
        rows = [{"scan": n.scan, "type": n.page_type, "status": n.status,
                 "sheet": n.sheet, "surnames": "; ".join(n.surnames),
                 "places": "; ".join(n.places),
                 "years": "; ".join(str(y) for y in n.years),
                 "method": n.method, "comment": n.comment}
                for n in cf.pages.values()]
    else:
        rows = []
        for rec in cf.records:
            for p in rec.persons:
                rows.append({
                    "rid": rec.rid, "type": rec.rtype,
                    "date": rec.date.value if rec.date else "",
                    "scans": "; ".join(rec.scans), "sheet": rec.sheet,
                    "row": rec.row, "role": p.role, "name": p.name,
                    "surname": p.surname or "", "patronymic": p.patronymic or "",
                    "sex": p.sex or "", "estate": p.estate or "",
                    "age": p.age or "", "place": p.place or ""})
    env = ok({"case": ref.key, "shifra": ref.shifra, "what": a.what,
              "columns": list(rows[0]) if rows else [], "rows": rows})
    if not rows:
        env.warn("empty_export",
                 f"у справі {ref.shifra} немає нічого типу «{a.what}» — "
                 f"це стан обліку, а не властивість справи")
    return env


# ── завантаження як довга робота ─────────────────────────────────────────────
class AcquireArgs(BaseModel):
    source: str = Field(description="id джерела")
    ref: str = Field(description="адреса справи чи плівки")
    dest: str = Field(default="", description="куди класти; порожньо = у простір")
    frames: str = Field(default="", description="діапазон «12-80»; порожньо = всі")


class ReadArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами (ПЛАСКА, без підтек)")
    out_dir: str = Field(default="", description="куди класти текст; порожньо = у простір")
    script: Literal["", "latin", "cyrillic"] = Field(
        default="", description="письмо; порожньо = вгадати з імені теки")
    second_voice: bool = Field(
        default=True,
        description="читати ще й другим рушієм — він помиляється ІНАКШЕ")
    case_key: str = Field(default="", description="шифра справи у мету прогону")


@op("read.plan", summary="Чим і як читатимемо цю справу — ДО запуску",
    args=ReadArgs, mutates=False)
def read_plan(a: ReadArgs) -> Envelope:
    """Скільки кадрів, яке письмо, яка модель, куди ляже текст.

    🔴 Окрема операція, а не крок усередині запуску. Справа читається годинами;
    дізнатись «модель не та» або «кадрів не двадцять, а три тисячі» після
    старту означає втратити ніч. Той самий поділ, що `manifest` перед `fetch`.
    """
    from nyshporka.htr.run import ReadError, plan

    try:
        p = plan(a.case_dir, out_dir=a.out_dir, script=a.script,
                 second_voice=a.second_voice)
    except ReadError as exc:
        return fail(str(exc))
    env = ok({"plan": p.as_dict()})
    if not a.script:
        # Здогад про письмо слабкий за побудовою — з імені теки нічого не
        # видно. Мовчазний здогад тут дав би тихе сміття.
        env.warn("script_guessed",
                 f"письмо «{p.script}» ВГАДАНО з імені теки. Помилка тут дає "
                 f"не збій, а осмислене на вигляд сміття — звірте перші "
                 f"сторінки або вкажіть письмо явно")
    if p.voice is None and p.script == "cyrillic":
        env.warn("single_voice",
                 "другого голосу немає — читатиме один рушій. Другий помиляється "
                 "ІНАКШЕ й витягує те, де перший підставив правдоподібне слово")
    return env


@op("read.start", summary="Прочитати справу рукописним рушієм", args=ReadArgs,
    mutates=True, long=True)
def read_start(a: ReadArgs) -> Envelope:
    """Ставить читання в чергу; саму роботу веде застосунок.

    Викликана поза застосунком, операція чесно каже, що черги немає, — замість
    того щоб тихо нічого не зробити.
    """
    return fail("читання веде застосунок — підніміть його командою "
                "`nysh serve` або запустіть `nysh read <тека>`")


@op("acquire.start", summary="Завантажити справу або плівку", args=AcquireArgs,
    mutates=True, long=True)
def acquire_start(a: AcquireArgs) -> Envelope:
    """Ставить у чергу; сама робота йде у застосунку.

    🔴 Синхронно цього робити не можна навіть у CLI-подібному вигляді: справа
    буває на кілька гігабайтів, тобто на годину. Відповідь мусить бути
    посиланням на завдання, а не очікуванням.
    """
    return fail("завантаження виконує застосунок — підніміть його командою "
                "`nysh serve` або скористайтесь `nysh get`")


# ── завдання ─────────────────────────────────────────────────────────────────
class JobArgs(BaseModel):
    action: Literal["list", "status", "wait", "cancel"] = "list"
    job_id: str = ""
    timeout_s: int = Field(default=30, ge=0, le=120,
                           description="скільки чекати зміни (для action=wait)")
    since: int = Field(default=0, description="курсор: віддати лише новіше за нього")


@op("job.query", summary="Стан довгих робіт: перелік, очікування, скасування",
    args=JobArgs, mutates=False)
def job_query(a: JobArgs) -> Envelope:
    # Черга живе в демоні; без нього відповідаємо чесно, а не порожнім списком.
    from nyshporka.runtime import current_bus

    bus = current_bus()
    if bus is None:
        return fail("черга недоступна: застосунок не запущено. "
                    "Підніміть його командою `nysh serve`")
    if a.action == "list":
        return ok({"jobs": [j.as_dict() for j in bus.jobs()], "seq": bus.seq})
    if a.action in ("status", "cancel") and not a.job_id:
        return fail(f"для action={a.action} потрібен job_id")
    if a.action == "status":
        job = bus.get(a.job_id)
        return ok(job.as_dict()) if job else fail(f"немає завдання {a.job_id}")
    return fail(f"дія «{a.action}» доступна лише в запущеному застосунку")


# ── профіль дослідження ──────────────────────────────────────────────────────
@op("profile.show", summary="Чий рід шукаємо: форми, корені, парадигма")
def profile_show(_: NoArgs) -> Envelope:
    from nyshporka.core.profile import ProfileError, active
    from nyshporka.core.workspace import WorkspaceError

    try:
        p = active()
    # 🔴 `WorkspaceError` теж: профіль лежить у просторі, тож «немає простору»
    # приходить сюди З-ПІД читання профілю, а не окремо. Перша редакція ловила
    # лише `ProfileError`, і виклик падав винятком замість чесної відповіді.
    except (ProfileError, WorkspaceError) as exc:
        env = fail(str(exc))
        env.warn("no_profile",
                 "без профілю пошук працюватиме на прізвище чужого дослідження")
        return env
    return ok({"name": p.name, "display": p.display, "paradigm": p.paradigm_id,
               "stems": p.stems, "roots": [r for r, _ in p.roots],
               "spellings": p.all_spellings(),
               "selftest_mode": (p.selftest or {}).get("mode", "strict")})


# ── архіви ───────────────────────────────────────────────────────────────────
class FondArgs(BaseModel):
    repo: str = Field(description="код архіву, напр. DAHMO")
    fond: str = Field(description="номер фонду")


@op("archive.fond", summary="Що відомо про фонд: губернія, опис у ключі, дефолти",
    args=FondArgs)
def archive_fond(a: FondArgs) -> Envelope:
    from nyshporka.archives import active

    pk = active()
    f = pk.fonds.get((a.repo.upper(), a.fond))
    data = {"repo": a.repo.upper(), "repo_label": pk.repo_label(a.repo),
            "fond": a.fond, "known": f is not None,
            "name": f.name if f else "", "guberniya": pk.guberniya(a.repo, a.fond),
            "default_opys": pk.default_opys(a.repo, a.fond),
            "opys_in_key": pk.opys_in_key(a.repo, a.fond),
            "note": f.note if f else ""}
    env = ok(data)
    if f is None:
        env.warn("unknown_fond",
                 f"фонд {a.repo.upper()} {a.fond} невідомий паку — правила за "
                 f"замовчуванням можуть не підійти")
    elif f.opys_in_key:
        env.warn("opys_in_key",
                 "у цьому фонді ОПИС входить у ключ справи: без нього різні "
                 "книги злипаються в одну")
    return env


# ── рушії читання ────────────────────────────────────────────────────────────
class EnvArgs(BaseModel):
    venv: str = Field(default="", description="тека середовища рушіїв; "
                                              "порожньо — узяти з простору")


@op("htr.env", summary="Чи готове середовище рушіїв читання", args=EnvArgs)
def htr_env(a: EnvArgs) -> Envelope:
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.htr import env as E

    if a.venv:
        venv = Path(a.venv)
    else:
        try:
            venv = workspace().root / ".venv_htr"
        except WorkspaceError as exc:
            return fail(str(exc))
    rep = E.inspect(venv)
    env = ok({"ok": rep.ok, "python": str(rep.python or ""), "kraken": rep.kraken,
              "torch": rep.torch, "cuda": rep.cuda, "capability": rep.capability,
              "missing": list(rep.missing)})
    for p in rep.problems:
        env.warn("engine_problem", p)
    if rep.missing:
        env.warn("engine_incomplete",
                 f"бракує: {', '.join(rep.missing)} — рушій із цими залежностями "
                 f"не запуститься")
    return env
