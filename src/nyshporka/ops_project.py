"""⚙️📁 Проєкти Майстерні: завести, перелічити, де я, сховати, відкрити.

Проєкт — підтека `projects/<ім'я>/` зі своїм каноном, профілем, вердиктами й
звітами (`core.projects`). Матеріал Майстерні спільний.

🔴 `project.status --agent` — точка доставки контексту агентові: його кличе
хук старту сесії в теці проєкту. Бюджет хука ~10 тис. знаків ділиться між
станом проєкту (≤ 2 тис.), картою ядра команд (≤ 3 тис., `core.routemap`) і
пам'яттю Майстерні, що бере залишок. `--no-memory` — для кореня старого типу,
де Майстерня й проєкт в одному корені: там Claude Code вантажить `MEMORY.md`
сам, і друге друкування лише з'їло б контекст.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

#: Межі виводу для агента (знаків).
AGENT_BUDGET = 10_000
STATE_BUDGET = 2_000
#: Карта ядра команд (`core.routemap`); пам'ять Майстерні бере залишок.
MAP_BUDGET = 3_000


class ProjectNewArgs(BaseModel):
    name: str = Field(description="ім'я теки: малі латинські літери, цифри, дефіс")
    kind: str = Field(default="family", description="family — рід, order — замовлення клієнта")
    title: str = Field(default="", description="назва для людини; порожньо — як ім'я")
    surname: str = Field(default="", description="прізвище роду — одразу завести профіль")


@op("project.new", summary="Завести проєкт у Майстерні (рід чи замовлення) з шаблону",
    args=ProjectNewArgs, mutates=True,
    when="завести новий проєкт у Майстерні: рід чи замовлення")
def project_new(a: ProjectNewArgs) -> Envelope:
    from nyshporka import project as T
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    hub = W.workspace().hub
    try:
        made = T.create(hub, a.name, kind=a.kind, title=a.title)
    except P.ProjectError as exc:
        return fail(str(exc))
    data: dict[str, Any] = {"root": str(made.root), "files": made.files, "profile": None}
    env = ok(data)
    if a.surname:
        from nyshporka.core.ops import REGISTRY

        # Профіль — тією самою операцією, що й `nysh profile init`, але в
        # теці щойно заведеного проєкту, а не там, звідки викликали.
        with W.using(W._build(made.root, "explicit")):
            got = REGISTRY.call("profile.set", {"display": a.surname})
        if got.ok:
            data["profile"] = got.data
        else:                              # проєкт заведено; профіль — окремим кроком
            env.warn("profile", f"профіль не заведено ({got.error}): "
                                f"nysh --project {a.name} profile init {a.surname}")
    for w in made.warnings:
        env.warn("hub_hooks", w)
    env.suggest("project.open", f"відкрити агента в проєкті: nysh project open {a.name}")
    return env


@op("project.list", summary="Проєкти Майстерні: вид, канон, профіль, архівні",
    when="які проєкти є в Майстерні")
def project_list(_: NoArgs) -> Envelope:
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    ws = W.workspace()
    here = P.current_id(ws)
    rows = []
    for pr in P.list_projects(ws.hub, archived=True):
        rows.append({"id": pr.id, "name": pr.name, "kind": pr.kind,
                     "archived": pr.archived, "here": pr.id == here,
                     "persons": _count_persons(pr.root), "root": str(pr.root)})
    return ok({"hub": str(ws.hub), "here": here, "projects": rows})


class ProjectStatusArgs(BaseModel):
    agent: bool = Field(default=False,
                        description="для хука старту сесії: стисло + карта команд + "
                                    "індекс пам'яті Майстерні")
    no_memory: bool = Field(default=False,
                            description="без індексу пам'яті: корінь, де агент і так "
                                        "вантажить її сам")


@op("project.status", summary="Де я: Майстерня, проєкт, рід, канон, відкрите, інші проєкти",
    args=ProjectStatusArgs,
    scope="mixed",
    when="де я: Майстерня, проєкт, рід, що відкрите")
def project_status(a: ProjectStatusArgs) -> Envelope:
    from nyshporka.core import workspace as W

    ws = W.workspace()
    state = _state(ws)
    text = _state_text(state)[:STATE_BUDGET]
    if a.agent:
        from nyshporka.core import routemap as M

        text += "\n\n" + M.agent_map(MAP_BUDGET)
        mem = "" if a.no_memory else _hub_memory(ws.hub)
        if mem:
            room = AGENT_BUDGET - len(text) - 80
            body = mem if len(mem) <= room else (
                mem[:max(room, 0)] + "\n… (індекс пам'яті обрізано)")
            text += "\n\n── Пам'ять Майстерні (індекс) ──\n" + body
        text = text[:AGENT_BUDGET]
    return ok({**state, "text": text})


class ProjectNameArgs(BaseModel):
    name: str = Field(description="ім'я проєкту")


class ProjectArchiveArgs(ProjectNameArgs):
    undo: bool = Field(default=False, description="повернути з архіву")


@op("project.archive", summary="Сховати проєкт із переліку й підсвітки (файли лишаються)",
    args=ProjectArchiveArgs, mutates=True,
    tier="rare")
def project_archive(a: ProjectArchiveArgs) -> Envelope:
    from nyshporka import project as T
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    hub = W.workspace().hub
    if a.name == P.ROOT_ID:
        return fail("корінь простору не архівується — це сама Майстерня")
    try:
        root = P.project_dir(hub, a.name)
    except P.ProjectError as exc:
        return fail(str(exc))
    T.set_archived(root, not a.undo)
    return ok({"name": a.name, "archived": not a.undo, "root": str(root)})


class ProjectAdoptArgs(ProjectNameArgs):
    apply: bool = Field(default=False, description="виконати переїзд (без цього — лише план)")
    archive: str = Field(default="", description="тека для zip-архіву, поза Майстернею "
                                                 "(обов'язкова з apply)")
    rollback: bool = Field(default=False, description="повернути останній переїзд")
    stamp: str = Field(default="", description="мітка переїзду для відкату")


@op("project.adopt", summary="Корінь старого типу → Майстерня + проєкт: план, переїзд, відкат",
    args=ProjectAdoptArgs, mutates=True, gui=False, tier="rare",
    when="перетворити простір, де рід лежить у корені, на Майстерню з проєктом роду")
def project_adopt(a: ProjectAdoptArgs) -> Envelope:
    """🔴 Без `apply` нічого не змінює. Архів — поза Майстернею, з sha256 і
    перевіркою розпакуванням, до першого переносу."""
    from pathlib import Path

    from nyshporka.core import workspace as W
    from nyshporka.project import adopt as A

    hub = W.workspace().hub
    try:
        if a.rollback:
            return ok(A.rollback(hub, a.stamp or None))
        pl = A.plan(hub, a.name)
        if not a.apply:
            env = ok({**pl.as_dict(), "report": A.report(pl)})
            return env
        if not a.archive:
            return fail("переїзд без архіву не починаю: --archive <тека поза Майстернею>")
        return ok(A.apply(hub, a.name, archive=Path(a.archive)))
    except (A.AdoptError, W.WorkspaceError) as exc:
        return fail(str(exc))


class ProjectOpenArgs(ProjectNameArgs):
    agent: str = Field(default="", description="claude | codex — одразу запустити агента")


@op("project.open", summary="Новий термінал у теці проєкту (за потреби — з агентом)",
    args=ProjectOpenArgs, gui=False,
    when="відкрити термінал чи агента в теці іншого проєкту")
def project_open(a: ProjectOpenArgs) -> Envelope:
    """🔴 Перемкнути проєкт посеред сесії агента не можна: інструкції й пам'ять
    вантажаться на старті. Тому «перейти в проєкт» = нова сесія в його теці."""
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    if a.agent and a.agent not in ("claude", "codex"):
        return fail(f"агент «{a.agent}»: є claude або codex")
    try:
        root = P.project_dir(W.workspace().hub, a.name)
    except P.ProjectError as exc:
        return fail(str(exc))
    cmd = _terminal_cmd(root, a.agent)
    if cmd is None:
        env = ok({"root": str(root), "started": False})
        env.warn("no_terminal", f"термінал звідси не відкрити — перейдіть руками: cd \"{root}\""
                                + (f" && {a.agent}" if a.agent else ""))
        return env
    subprocess.Popen(cmd, cwd=str(root))
    return ok({"root": str(root), "started": True, "agent": a.agent or None})


# ── допоміжне ────────────────────────────────────────────────────────────────
def _terminal_cmd(root: Path, agent: str) -> list[str] | None:
    import shutil

    if sys.platform == "win32":
        tail = [agent] if agent else []
        if shutil.which("wt"):
            return ["wt", "-d", str(root), *(tail or [])]
        return ["cmd", "/c", "start", "", "cmd", "/k", *(tail or ["cd"])]
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole"):
        if shutil.which(term):
            return [term] + (["-e", agent] if agent else [])
    if sys.platform == "darwin":
        return ["open", "-a", "Terminal", str(root)]
    return None


def _count_persons(root: Path) -> int:
    from nyshporka.core.workspace import Workspace

    d = Workspace(root=root).canonical / "persons"
    return sum(1 for _ in d.glob("*.md")) if d.is_dir() else 0


def _state(ws: Any) -> dict[str, Any]:
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    pid = P.current_id(ws)
    out: dict[str, Any] = {"hub": str(ws.hub), "project": pid, "name": ws.name,
                           "mode": W.mode_label(ws), "readonly": ws.readonly,
                           "others": [{"id": p.id, "name": p.name} for p in P.others(ws)]}
    if pid is None:
        out["kind"] = "hub"
        return out
    tab = W.read_project_table(ws.root) or {}
    out["kind"] = str(tab.get("kind") or "family")
    out["persons"] = _count_persons(ws.root)
    try:
        from nyshporka.core import profile as PROF

        prof = PROF.active()
        out["surname"] = prof.display or prof.name
    except Exception:
        out["surname"] = ""
    try:
        from nyshporka.canon.next import next_decisions

        nd = next_decisions(ws.root, limit=3)
        out["hypotheses"] = {k: nd[k] for k in ("open", "awaiting", "closed")}
        out["next"] = [f"{d['id']}: {d['claim']}" for d in nd["next"]]
    except Exception:
        out["hypotheses"], out["next"] = {}, []
    return out


def _state_text(s: dict[str, Any]) -> str:
    from nyshporka.project import KIND_LABEL

    others = ", ".join(o["id"] for o in s["others"]) or "немає"
    if s["project"] is None:
        return (f"🏛 Корінь Майстерні {s['hub']} — режим Майстерні, проєкту немає.\n"
                f"Проєкти: {others}. Робота над родом — сесія в теці проєкту "
                "(nysh project open <ім'я>); команди проєктного шару звідси — з --project.")
    lines = [f"📁 Проєкт «{s['project']}» ({s['name']}, "
             f"{KIND_LABEL.get(s['kind'], s['kind'])}) · {s['mode']}"]
    lines.append(f"Рід: {s.get('surname') or 'профіль не задано (nysh profile init <Прізвище>)'}"
                 f" · у каноні осіб: {s.get('persons', 0)}")
    hyp = s.get("hypotheses") or {}
    if hyp:
        lines.append(f"Гіпотези: відкрито {hyp.get('open', 0)}, чекають вердикту "
                     f"{hyp.get('awaiting', 0)}, закрито {hyp.get('closed', 0)}")
    for n in s.get("next") or []:
        lines.append(f"  • {n}")
    lines.append(f"Інші проєкти: {others} — їхні висновки сюди не завантажуються; "
                 "чужих тек не читати, міжпроєктне — з кореня Майстерні.")
    return "\n".join(lines)


def _hub_memory(hub: Path) -> str:
    from nyshporka.project import memory_dir

    try:
        return (memory_dir(hub) / "MEMORY.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
