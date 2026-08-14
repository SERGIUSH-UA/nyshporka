"""⚙️ Операції, доступні зараз.

Перелік навмисно короткий: сюди потрапляє лише те, чий домен уже в пакеті.
Дописувати операції «на майбутнє» не можна — tool, який відповідає «ще не
реалізовано», гірший за відсутній: агент витрачає на нього хід і довіру.

Імпорт цього модуля наповнює `core.ops.REGISTRY`, тож він має статись до
першого звернення до реєстру (див. `nyshporka.ops`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


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
@op("sources.list", summary="Звідки можна брати матеріал")
def sources_list(_: NoArgs) -> Envelope:
    from nyshporka.sources import load

    reg = load()
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
