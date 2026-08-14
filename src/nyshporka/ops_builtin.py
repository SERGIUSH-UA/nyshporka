"""⚙️ Операції, доступні зараз.

Перелік навмисно короткий: сюди потрапляє лише те, чий домен уже в пакеті.
Дописувати операції «на майбутнє» не можна — tool, який відповідає «ще не
реалізовано», гірший за відсутній: агент витрачає на нього хід і довіру.

Імпорт цього модуля наповнює `core.ops.REGISTRY`, тож він має статись до
першого звернення до реєстру (див. `nyshporka.ops`).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
        hits.extend({"source": h.source, "ref": h.ref, "title": h.title,
                     "years": h.years, "place": h.place, "shifra": h.shifra,
                     "frames": h.frames, "acquirable": h.acquirable, "note": h.note}
                    for h in found)
    env = ok({"q": a.q, "hits": hits[:a.limit],
              "coverage": {"searched": searched, "unavailable": unavailable}})
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
