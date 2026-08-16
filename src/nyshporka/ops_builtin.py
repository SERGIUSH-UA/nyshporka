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


@op("sources.list", summary="Звідки можна брати матеріал", section="material")
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
    args=CatalogSearchArgs, mutates=False, section="material")
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
    mutates=False, section="material")
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
    args=ManifestArgs, mutates=False, section="material")
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
    except FileNotFoundError:
        # 🔴 «Реєстру ще немає» — це НОРМАЛЬНИЙ стан щойно створеного простору,
        # а не поламка. Відмова тут була першим, що бачив новачок, відкривши
        # «Мої справи»: червоне «Не вийшло» замість порожнього переліку. Гірше
        # того, екран на відмові не малювався взагалі — разом із кнопкою 🔄,
        # якою це й лікується, тобто вихід зникав саме тоді, коли був потрібен.
        env = ok({"cases": [], "shown": 0, "registry": False})
        env.warn("no_registry_yet",
                 "реєстру справ ще немає — його збирають після того, як у "
                 "просторі з'явиться перша справа")
        env.stale_because(["реєстр ще не збирали"], fix="nysh cases build")
        return env
    except Exception as exc:
        return fail(f"реєстр справ недоступний ({type(exc).__name__}: {exc}) — "
                    f"зберіть його командою `nysh cases build`")
    env = ok({"cases": rows, "shown": len(rows), "registry": True})
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
    args=SearchArgs, mutates=False, section="research")
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
        # 🔴 Ключ називається `pages_done`. Поки тут стояло `pages`, знаменник
        # був ТОТОЖНО НУЛЬОВИЙ: на просторі з 506 прогонами й 320 669
        # прочитаними сторінками відповідь звучала «не знайшлось у 506
        # прогонах (0 сторінок)». Це не описка у виводі, а зруйноване головне
        # правило: нуль подавався зі знаменником, який сам був нулем, тобто
        # читався як «нічого не прочитано» — і закривав напрям пошуку.
        pages = sum(int(c.get("pages_done") or c.get("pages") or 0) for c in runs)
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
    # 🔴 Знаменник тут ТАКИЙ САМИЙ обов'язковий, як у пошуку по декоду, — і
    # довго його не було саме тут, у гілці, найближчій до людини. «Не
    # знайшлось у виписаному» означає лише «серед того, що вже занесли оком»:
    # занесена завжди менша частина того, що на диску. Без цього числа нуль
    # читається як вирок про рід, а він про обсяг роботи.
    hits = res.get("hits") or []
    env = ok({"hits": hits, "total": res.get("total", len(hits)),
              "coverage": {"cases": res.get("cases") or 0,
                           "thresh": res.get("thresh", a.thresh),
                           "stems": res.get("stems") or []}})
    if res.get("error"):
        env.warn("bad_query", str(res["error"]))
    elif not hits:
        where = ("виписаних прізвищах" if a.where == "pages"
                 else "учасниках розібраних записів")
        env.warn("zero_with_denominator",
                 f"не знайшлось у {where}: переглянуто {res.get('cases') or 0} "
                 f"справ. Це НЕ означає, що запису немає — означає, що його "
                 f"немає в занесеному оком.")
    return env


# ── гортач ───────────────────────────────────────────────────────────────────
class PageArgs(BaseModel):
    run: str = Field(description="ім'я прогону (тека в reports/htr)")
    page: str = Field(default="", description="скан; порожньо = перелік сторінок")


@op("page.text", summary="Що прочитано на сторінці й де саме лежить кожен рядок",
    args=PageArgs, mutates=False, section="htr")
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
    # 🔴 Текст і геометрія — під РІЗНИМИ ключами. `read_page_text` віддає рядки
    # тексту саме як `lines`, і накладання геометрії тим самим ім'ям знищувало
    # прочитане: відповідь лишалась `ok`, але тексту в ній не було зовсім.
    # Гортач через це показував порожню сторінку — тобто головний екран
    # «подивитись, що прочитала машина» мовчки не показував нічого.
    text_lines = list(txt.get("lines") or [])
    env = ok({**txt, "lines": text_lines, "text": "\n".join(text_lines),
              "geometry": geo})
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
    mutates=False, section="htr")
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


# ── завести справу руками ────────────────────────────────────────────────────
class CaseRegisterArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами")
    shifra: str = Field(default="",
                        description="«ДАХмО 315-1-8433», «ф.315 оп.1 спр.8433», "
                                    "«Ф. 211 Оп. 3 Д. 140»")
    title: str = Field(default="", description="назва справи, як в описі архіву")
    doc_type: str = Field(default="", description="метрична / сповідна / ревізька…")
    year_from: int | None = None
    year_to: int | None = None
    place: str = Field(default="", description="село, повіт, губернія")
    note: str = Field(default="", description="звідки взято, що незрозуміло")
    adopt: bool = Field(
        default=False,
        description="взяти теку під облік, якщо вона лежить ПОЗА простором: "
                    "оголосити її коренем справ у nyshporka.toml")
    reindex: bool = Field(
        default=True,
        description="перезібрати бібліотеку, щоб справа одразу з'явилась у переліках")


@op("case.register", summary="Завести або виправити справу: шифра, назва, роки",
    args=CaseRegisterArgs, mutates=True)
def case_register(a: CaseRegisterArgs) -> Envelope:
    """Зробити теку зі сканами СПРАВОЮ.

    🔴 Без шифри тека лишається купою файлів: у неї немає ключа, а отже ні
    обліку прочитаного, ні місця в реєстрі, ні можливості послатись на
    знахідку. Опис пишеться В ТЕКУ — вона переїжджає між дисками й потрапляє
    до колег, і опис мусить їхати з нею.

    🔴 Бібліотека перезбирається ОДРАЗУ. Інакше людина заводить справу, іде в
    «Мої справи» — і не бачить її там; виглядає це як «нічого не спрацювало»,
    хоча опис записаний. На великому просторі це коштує секунд двадцять, і це
    чесна ціна: система щойно дізналась про нову справу.
    """
    from nyshporka.cases.register import RegisterError, describe

    try:
        out = describe(a.case_dir, shifra=a.shifra, title=a.title,
                       doc_type=a.doc_type, year_from=a.year_from,
                       year_to=a.year_to, place=a.place, note=a.note)
    except RegisterError as exc:
        return fail(str(exc))
    env = ok({"case_dir": a.case_dir, "sidecar": out})
    # 🔴 Тека поза простором — мовчазна поразка всього подальшого. Опис у ній
    # запишеться, ✅ покажеться, а збірка бібліотеки її не побачить: сканується
    # лише `data/raw` (і оголошені корені справ). Далі кожен крок падав окремо
    # й не називав справжньої причини. Тому кажемо одразу і кажемо, куди класти.
    from nyshporka.cases.register import case_path, reachable

    here = case_path(a.case_dir)
    env.data["reachable"] = True
    if not reachable(here):
        from nyshporka.core.workspace import WorkspaceError, add_case_root

        if a.adopt:
            try:
                root = add_case_root(here)
            except WorkspaceError as exc:
                env.data["reachable"] = False
                env.warn("adopt_refused",
                         f"взяти теку під облік не вийшло: {exc}")
            else:
                env.data["adopted"] = str(root)
                env.warn("adopted",
                         f"теку взято під облік: {root}. Її оголошено в "
                         f"nyshporka.toml, тож вона лишиться видимою й після "
                         f"перезапуску — і поїде разом із простором.")
        else:
            env.data["reachable"] = False
            env.warn("outside_workspace",
                     "тека лежить поза простором, тож у переліках справа НЕ "
                     "з'явиться. Поставте позначку «взяти теку під облік» — "
                     "і вона буде видима там, де лежить, без перенесення "
                     "файлів.")
    if not out.get("title"):
        env.warn("no_title",
                 "назви немає — у переліках справа буде «без назви», і впізнати "
                 "її за рік стане важко")
    if a.reindex:
        try:
            from nyshporka.library import build_library, write_library

            entries = build_library()
            write_library(entries)
            env.data["library"] = len(entries)
        except Exception as exc:
            env.warn("reindex_failed",
                     f"опис записано, але бібліотеку не перезібрано "
                     f"({type(exc).__name__}: {exc}) — справа з'явиться в "
                     f"переліках після наступної перезбірки")
    return env


# `agent=False` — це питання про МАШИНУ, а не про дослідження: агентові
# середовище описує `htr.env`, а решту він бачить у відмовах операцій.
@op("setup.check", summary="Чи готова ця машина читати рукопис", agent=False)
def setup_check(_: NoArgs) -> Envelope:
    """🔴 Найважливіше питання аматора — і до нього не було входу з екрана.

    Людина, яка щойно поставила застосунок, має дізнатись, чи все складеться,
    ДО того, як вкладе три тисячі сканів і чекатиме ніч. Ця перевірка була
    лише в командному рядку (`nysh doctor`), а на екрані картка «показати на
    прикладі» віддавала сирий JSON про середовище рушіїв — тобто відповідала
    не на те питання й не тими словами.
    """
    from nyshporka.setup.doctor import run

    checks = [{"name": c.name, "level": c.level, "detail": c.detail, "fix": c.fix}
              for c in run()]
    worst = ("fail" if any(c["level"] == "fail" for c in checks)
             else "warn" if any(c["level"] == "warn" for c in checks) else "ok")
    env = ok({"checks": checks, "level": worst,
              "ready": worst == "ok",
              # 🔴 Названо окремим полем, бо це не поламка машини, а межа
              # версії: сказати «не готово» без цієї різниці означало б
              # послати людину лагодити те, що справне.
              "sample_case": False})
    if worst != "ok":
        env.warn("not_ready",
                 "читання рукопису на цій машині поки не запуститься — нижче "
                 "написано, чого бракує і чим це ставиться")
    return env


class CasesBuildArgs(BaseModel):
    rescan: bool = Field(default=True,
                         description="перечитати ще й диск — потрібно, коли "
                                     "з'явились нові теки, а не лише новий декод")


# `agent=False`: агент дізнається про застарілий зріз із поля `stale` в конверті
# й має пораду в ньому ж; окремий tool на це з'їдав би місце в переліку.
@op("cases.build", summary="Перезібрати реєстр справ", args=CasesBuildArgs,
    mutates=True, long=True, agent=False)
def cases_build(a: CasesBuildArgs) -> Envelope:
    """🔴 Кнопка, на яку посилались тексти, якої не було.

    Реєстр — зріз п'яти сховищ, і будь-який прогін робить його старим за
    хвилини. Про це чесно попереджав кожен перелік — і відсилав по виправлення
    в командний рядок. Для того, хто працює формами, це те саме, що не мати
    виправлення взагалі.

    Виконує роботу застосунок: на просторі в тисячу справ перезбірка триває
    десятки секунд, і синхронна відповідь означала б завислу вкладку.
    """
    return fail("перезбірку веде застосунок — підніміть його командою "
                "`nysh serve` або скористайтесь `nysh cases build`")


class CaseShowArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами")


# `agent=False` — це підживлення форми, а не дія дослідження: агент читає опис
# через `cases.list` і `pages.status`, де він іде разом зі станом обробки.
@op("case.show", summary="Поточний опис теки — щоб правити, а не передруковувати",
    args=CaseShowArgs, agent=False)
def case_show(a: CaseShowArgs) -> Envelope:
    """🔴 Правити наосліп — не правка.

    Форма без поточних значень змушує передруковувати весь опис заново, аби
    змінити одне слово; напівзаповнена форма при цьому виглядає як повний опис.
    Тому «змінити» починається з показу того, що вже записано.
    """
    import json

    from nyshporka.cases.register import SIDECAR, case_path

    d = case_path(a.case_dir)
    if not d.is_dir():
        return fail(f"теки немає: {d}")
    sc: dict[str, Any] = {}
    path = d / SIDECAR
    if path.is_file():
        try:
            sc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return fail(f"опис пошкоджено ({exc}) — виправте {path} або "
                        f"видаліть його й заведіть справу наново")
    scans = sum(1 for p in d.iterdir()
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"})
    env = ok({"case_dir": str(d), "described": bool(sc), "scans": scans,
              "sidecar": sc})
    if not sc:
        env.warn("not_described",
                 "тека ще не справа: без шифри в неї немає ключа, а отже ні "
                 "обліку прочитаного, ні місця в реєстрі")
    elif not scans:
        env.warn("no_scans",
                 "опис є, а зображень у теці немає — можливо, скани лежать "
                 "у підтеці, і читання їх не побачить")
    return env


# ── облік прочитаного ────────────────────────────────────────────────────────
class PagesStatusArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    scans: str = Field(default="", description="кома-список сканів для точкової перевірки")


@op("pages.status", summary="Що в цій справі вже дивились оком, а що ні",
    args=PagesStatusArgs, mutates=False, section="research")
def pages_status(a: PagesStatusArgs) -> Envelope:
    """🔴 Гейт ПЕРЕД переглядом, а не звіт після.

    Найдорожча помилка в довгій справі — передивитись ті самі аркуші вдруге:
    тисяча сторінок коштує вечора, і другий вечір на них не додає нічого. Тому
    питання «що вже бачили» ставиться до того, як щось відкривати.
    """
    from nyshporka.pagestore import store

    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    scans = [s.strip() for s in a.scans.split(",") if s.strip()]
    st = store.case_status(ref, scans or None)
    env = ok(st)
    if not st.get("case_dir_known", True):
        # 🔴 «0 на диску» тут читалось би як «скани зникли». Насправді реєстр
        # просто ще не знає, де лежить справа, — і це лікується одним кроком.
        env.warn("case_dir_unknown",
                 "теки зі сканами цієї справи реєстр не знає, тож «на диску» "
                 "нижче — не нуль, а «невідомо». Заведіть справу "
                 "(`nysh case <тека> --shifra …`) або перезберіть реєстр")
    left = st.get("unnoted_count")
    if left:
        env.suggest("pages.note",
                    f"{left} сторінок ще ніхто не заносив — переглянуте без "
                    f"запису наступна сесія перегляне заново")
    return env


class PageNoteArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    scan: str = Field(description="голе ім'я файлу скана: 0030.JPG")
    # 🔴 Перелік значень, а не вільний рядок з «…» у поясненні. Приймається
    # рівно чотирнадцять слів, і поки схема мовчала про це, форма показувала
    # порожнє поле: людина писала «метрична» й діставала відмову переліком
    # англійських літералів. Оголошений перелік доїжджає в `/api/ops`, тож
    # вибір будується сам — і в консолі, і в будь-якого читача схеми.
    page_type: Literal[
        "birth", "marriage", "death", "confession", "revision", "census",
        "index", "title", "cover", "flyleaf", "blank", "illegible", "mixed",
        "other"] = Field(description="що це за сторінка")
    surnames: str = Field(default="", description="кома-список ЯК НАПИСАНО в джерелі")
    places: str = Field(default="")
    years: str = Field(default="", description="кома-список років: 1858,1859")
    sheet: str = Field(default="", description="архівний аркуш: 31зв-32")
    status: Literal["full", "partial", "skipped", "unreadable"] = Field(
        default="full", description="наскільки повно виписано")
    method: Literal["visual", "htr", "ocr", "hybrid", "text"] = Field(
        default="visual", description="чим читали")
    comment: str = Field(default="")
    agent: str = Field(default="", description="хто заносив")


@op("pages.note", summary="Занести переглянуту сторінку в облік", args=PageNoteArgs,
    mutates=True, section="research")
def pages_note(a: PageNoteArgs) -> Envelope:
    """🔴 БЕЗ ВИНЯТКІВ: кожен скан, який реально відкривали, заноситься.

    Навіть якщо він виявився пустишкою. Негативний результат коштує тих самих
    очей, що й позитивний, і без запису наступна сесія перегляне той самий
    аркуш ще раз. У коментарі варто писати, ЧОМУ це не те.

    ⚠ `status=full` ставиться, ЛИШЕ якщо виписано ВСІ прізвища сторінки —
    інакше `partial`. Від цього залежить, чи можна довіряти нулю по цій справі.
    """
    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import PageNote

    def _csv(v: str) -> list[str]:
        return [x.strip() for x in v.split(",") if x.strip()]

    try:
        ref = store.resolve_case(a.case)
        note = PageNote(
            scan=a.scan, page_type=a.page_type,
            surnames=_csv(a.surnames), places=_csv(a.places),
            years=[int(y) for y in _csv(a.years)], sheet=a.sheet,
            status=a.status, method=a.method,
            comment=a.comment, agent=a.agent)
    except (ValidationError, ValueError) as exc:
        return fail(str(exc))
    report = store.annotate_pages(ref, [note])
    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict()})
    if a.status == "full" and not note.surnames:
        env.warn("full_without_surnames",
                 "status=full означає «виписано ВСІ прізвища сторінки», а їх "
                 "тут жодного. Якщо сторінка не порожня — це має бути partial")
    if a.method in ("htr", "text"):
        env.warn("not_eye_verified",
                 "метод каже, що читали ДЕКОД, а не зображення — така гілка "
                 "успадковує чужі помилки; у коментарі варто позначити «оком не звірено»")
    return env


class RecordsAddArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    records: str = Field(description="JSON-масив записів (Record)")


@op("records.add", summary="Занести розібрані записи джерела", args=RecordsAddArgs,
    mutates=True, section="research")
def records_add(a: RecordsAddArgs) -> Envelope:
    """Хто/коли/батьки/восприємники — структурою, а не прозою.

    Невалідні елементи пропускаються зі звітом, валідні лягають: не втрачати
    сорок розібраних актів через одну одруківку в сорок першому.
    """
    import json as _json

    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import Record

    try:
        raw = _json.loads(a.records)
    except ValueError as exc:
        return fail(f"records не є JSON: {exc}")
    if not isinstance(raw, list):
        raw = [raw]
    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    recs, errors = [], []
    for i, item in enumerate(raw):
        try:
            recs.append(Record.model_validate(item))
        except ValidationError as exc:
            errors.append({"index": i, "error": str(exc)[:400]})
    report = store.add_records(ref, recs) if recs else store.MergeReport(path="")
    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict(),
              "ok": len(recs), "failed": len(errors), "errors": errors})
    if errors:
        env.warn("some_records_refused",
                 f"{len(errors)} записів не пройшли перевірку — решта {len(recs)} "
                 f"занесені; виправте й додайте окремо")
    return env


# ── експорт ──────────────────────────────────────────────────────────────────
class ExportArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    what: Literal["pages", "records"] = "records"


@op("export.case", summary="Викласти прочитане зі справи таблицею", args=ExportArgs,
    mutates=False, section="research")
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


# `agent=False`: план рахує й сам `read.start`, а людині він потрібен ОКРЕМО —
# щоб побачити його до того, як натисне «читати». Агентові двох tool'ів на
# одну дію не треба.
@op("read.plan", summary="Чим і як читатимемо цю справу — ДО запуску",
    args=ReadArgs, mutates=False, agent=False, section="htr")
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
    mutates=True, long=True, section="htr")
def read_start(a: ReadArgs) -> Envelope:
    """Ставить читання в чергу; саму роботу веде застосунок.

    Викликана поза застосунком, операція чесно каже, що черги немає, — замість
    того щоб тихо нічого не зробити.
    """
    return fail("читання веде застосунок — підніміть його командою "
                "`nysh serve` або запустіть `nysh read <тека>`")


@op("acquire.start", summary="Завантажити справу або плівку", args=AcquireArgs,
    mutates=True, long=True, section="material")
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
# `agent=False` — це конфіг дослідження, а не дія. Читається файлом.
@op("profile.show", summary="Чий рід шукаємо: форми, корені, парадигма",
    agent=False)
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


# `agent=False` — довідка про фонд: потрібна раз на дослідження й читається
# з паку архівів. У переліку tool'ів вона з'їдала б місце, яке модель мусить
# дочитати до кінця.
@op("archive.fond", summary="Що відомо про фонд: губернія, опис у ключі, дефолти",
    args=FondArgs, agent=False, section="material")
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


# 🔴 `agent=False` — діагностика. У агента для неї є `nysh doctor`, який каже
# більше й одним викликом; тримати її ще й окремим tool'ом означає з'їдати
# місце в переліку, який модель мусить дочитати до кінця.
@op("htr.env", summary="Чи готове середовище рушіїв читання", args=EnvArgs,
    agent=False, section="htr")
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


# ── секції застосунку ────────────────────────────────────────────────────────
# 🔴 Обидві `agent=False`, і це рішення, а не недогляд. Перелік агентських
# tool'ів має стелю (див. `tests/test_reference_tabs`): далі модель перестає
# дочитувати описи й починає вгадувати. Переналаштування самого застосунку —
# не та річ, заради якої її рухати; для цього в агента є командний рядок.
class SectionsSetArgs(BaseModel):
    preset: str = Field("", description="пресет: amateur | researcher | lab")
    enable: list[str] = Field(default_factory=list, description="увімкнути секції")
    disable: list[str] = Field(default_factory=list, description="вимкнути секції")


def _sections_payload() -> dict[str, Any]:
    from nyshporka.core import sections as S
    from nyshporka.core.ops import REGISTRY
    from nyshporka.core.workspace import workspace

    active = workspace().sections
    in_use = REGISTRY.sections_in_use()
    rows = []
    for sec in S.all_sections():
        n = sum(1 for o in REGISTRY.all() if o.section == sec.id)
        rows.append({
            "id": sec.id, "label": sec.label(), "label_en": sec.label_en,
            "why": sec.why(), "why_en": sec.why_en,
            "required": sec.required, "active": sec.id in active,
            "ops": n,
            # Порожня секція не показується: вкладка без вмісту — обіцянка без входу.
            "visible": sec.id in in_use,
            "screens": list(S.screens_of(sec.id)),
        })
    return {"sections": rows, "preset": S.preset_of(active),
            "presets": {n: sorted(s) for n, s in S.PRESETS.items()},
            "screens": dict(S.SCREENS)}


@op("sections.show", summary="Які частини застосунку ввімкнено", agent=False)
def sections_show(_: NoArgs) -> Envelope:
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    env = ok(_sections_payload())
    problem = ws.profile[2]
    if problem:
        env.warn("sections_profile",
                 f"профіль секцій у {ws.marker.name} не прочитано "
                 f"({problem}) — діє набір за замовчуванням")
    return env


@op("sections.set", summary="Увімкнути або вимкнути частини застосунку",
    args=SectionsSetArgs, mutates=True, agent=False)
def sections_set(a: SectionsSetArgs) -> Envelope:
    from nyshporka.core import sections as S
    from nyshporka.core.workspace import WorkspaceError, set_sections, workspace

    try:
        current = workspace().sections
    except WorkspaceError as exc:
        return fail(str(exc))

    if a.preset:
        try:
            target = set(S.preset_sections(a.preset))
        except S.SectionError as exc:
            return fail(str(exc))
    else:
        target = set(current)
    bad = S.unknown([*a.enable, *a.disable])
    if bad:
        return fail(f"невідомі секції: {', '.join(bad)}. "
                    f"Є: {', '.join(sorted(S.ids()))}")
    target |= set(a.enable)
    # 🔴 Обов'язкову секцію не знімаємо навіть на пряме прохання: без неї
    # лишається шапка без жодного екрана, до якого можна дійти.
    refused = sorted(set(a.disable) & S.required_ids())
    target -= set(a.disable) - S.required_ids()

    try:
        active = set_sections(target)
    except (S.SectionError, WorkspaceError, OSError) as exc:
        return fail(f"не вдалось записати профіль: {exc}")

    env = ok(_sections_payload())
    for sid in refused:
        sec = S.get(sid)
        env.warn("section_required",
                 f"секцію «{sec.label() if sec else sid}» вимкнути не можна — "
                 f"без неї застосунок лишається без жодного екрана")
    # Порожню секцію вмикати не заборонено — але сказати про це треба, інакше
    # людина ввімкне «Лабораторію» й шукатиме, чому в шапці нічого не додалось.
    from nyshporka.core.ops import REGISTRY

    for sid in sorted((active - S.required_ids()) - REGISTRY.sections_in_use()):
        sec = S.get(sid)
        env.warn("section_empty",
                 f"секція «{sec.label() if sec else sid}» ще порожня — "
                 f"операцій у ній немає, тож в UI вона не з'явиться")
    return env
