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

import re
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
    variants: list[str] = Field(default_factory=list,
                                description="інші написання прізвища — у профіль "
                                            "як куски, за якими воно впізнається")
    color: str = Field(default="", description="колір проєкту в консолі: #rrggbb")
    glyph: str = Field(default="", description="знак проєкту: буква чи емодзі")
    icon: str = Field(default="", description="значок проєкту — мальований кружок "
                                              "(derevo, zamok, tserkva…; повний перелік — "
                                              "у відмові на невідомий)")


@op("project.new", summary="Завести проєкт у Майстерні (рід чи замовлення) з шаблону",
    args=ProjectNewArgs, mutates=True,
    when="завести новий проєкт у Майстерні: рід чи замовлення")
def project_new(a: ProjectNewArgs) -> Envelope:
    from nyshporka import project as T
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    hub = W.workspace().hub
    try:
        P.check_color(a.color)
        P.check_glyph(a.glyph)
        P.check_icon(a.icon)
        made = T.create(hub, a.name, kind=a.kind, title=a.title)
    except P.ProjectError as exc:
        return fail(str(exc))
    if a.color or a.glyph or a.icon:
        T.set_style(made.root, color=a.color, glyph=a.glyph, icon=a.icon)
    data: dict[str, Any] = {"root": str(made.root), "files": made.files, "profile": None}
    env = ok(data)
    if a.surname:
        from nyshporka.core.ops import REGISTRY

        # Профіль — тією самою операцією, що й `nysh profile init`, але в
        # теці щойно заведеного проєкту, а не там, звідки викликали.
        with W.using(W._build(made.root, "explicit")):
            got = REGISTRY.call("profile.set", {
                "display": a.surname,
                "substrings": [v.strip() for v in a.variants if v.strip()]})
        if got.ok:
            data["profile"] = got.data
        else:                              # проєкт заведено; профіль — окремим кроком
            env.warn("profile", f"профіль не заведено ({got.error}): "
                                f"nysh --project {a.name} profile init {a.surname}")
    for w in made.warnings:
        env.warn("hub_hooks", w)
    from nyshporka.core import vcs as V

    if V.auto_enabled(hub) and V.git_available():
        try:
            # Разом із теку проєкту — інструкції, які `create` поклав у корінь
            # Майстерні (`../../CLAUDE.md`, коли їх там ще не було).
            extra = [(made.root / f).resolve() for f in made.files if f.startswith("..")]
            V.save(W.workspace(), f"Проєкт «{a.name}» заведено", paths=[made.root, *extra])
        except V.VcsError as exc:
            env.warn("history", f"історію не збережено: {exc}")
    if not W._read_marker(hub / W.MARKER).get("hub_only") and             any((W.Workspace(root=hub).canonical / "persons").glob("*.md")):
        env.warn("legacy_root", "рід, що лежить у корені Майстерні, лишився там: щоб він "
                                "став проєктом поруч із новим — nysh project adopt <ім'я> "
                                "(спершу план, тоді --apply)")
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
                     "color": pr.color, "glyph": pr.glyph, "icon": pr.icon,
                     "persons": _count_persons(pr.root),
                     "hypotheses": _count_hypotheses(pr.root), "root": str(pr.root)})
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


class ProjectStyleArgs(ProjectNameArgs):
    title: str | None = Field(default=None, description="назва для людини («Рід Сидоруків»)")
    color: str | None = Field(default=None, description="#rrggbb; порожньо — зняти")
    glyph: str | None = Field(default=None, description="буква чи емодзі; порожньо — зняти")
    icon: str | None = Field(default=None, description="значок-кружок (derevo, zamok…); "
                                                       "порожньо — зняти")


@op("project.style", summary="Назва, колір і знак проєкту в консолі",
    args=ProjectStyleArgs, mutates=True, tier="rare",
    when="змінити назву, колір чи знак проєкту в перемикачі консолі")
def project_style(a: ProjectStyleArgs) -> Envelope:
    from nyshporka import project as T
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    hub = W.workspace().hub
    if a.name == P.ROOT_ID:
        return fail("корінь старого типу не має маркера проєкту — колір лише в підтеки")
    try:
        root = P.project_dir(hub, a.name)
        P.check_color(a.color or "")
        P.check_glyph(a.glyph or "")
        P.check_icon(a.icon or "")
    except P.ProjectError as exc:
        return fail(str(exc))
    # 🔴 Назва — для людини: перенесення роду в проєкт (`project adopt`) лишало
    # в ній id, і консоль скрізь показувала id проєкту (22.10.2026).
    T.set_style(root, color=a.color, glyph=a.glyph, title=a.title, icon=a.icon)
    pr = P._from_dir(root)
    return ok({"name": a.name, "title": pr.name if pr else "", "color": pr.color if pr else "",
               "glyph": pr.glyph if pr else "", "icon": pr.icon if pr else ""})


class ProjectAdoptArgs(ProjectNameArgs):
    apply: bool = Field(default=False, description="виконати переїзд (без цього — лише план)")
    archive: str = Field(default="", description="тека для zip-архіву поза Майстернею; "
                                                 "порожньо — тека-сусідка <хаб>-adopt")
    rollback: bool = Field(default=False, description="повернути останній переїзд")
    stamp: str = Field(default="", description="мітка переїзду для відкату")
    title: str = Field(default="", description="назва проєкту людською мовою («Рід Іваненків»)")
    via: str = Field(default="", description="хто запустив: console — кнопка консолі")


@op("project.adopt", summary="Корінь старого типу → Майстерня + проєкт: план, переїзд, відкат",
    args=ProjectAdoptArgs, mutates=True, tier="rare",
    when="перетворити простір, де рід лежить у корені, на Майстерню з проєктом роду")
def project_adopt(a: ProjectAdoptArgs) -> Envelope:
    """🔴 Без `apply` нічого не змінює. Архів — поза Майстернею, з sha256 і
    звіркою кожного члена, до першого переносу. План відмовляє, коли в шляхах
    переїзду хтось пише просто зараз."""
    from pathlib import Path

    from nyshporka.core import workspace as W
    from nyshporka.daemon import app as D
    from nyshporka.project import adopt as A

    hub = W.workspace().hub
    if D.LAUNCH and (a.apply or a.rollback):
        # 🔴 Консоль сама тримає Майстерню: переносити теки з-під живого сервера
        # не можна. З консолі — `project.adopt_restart` (закрити, перенести, відкрити).
        return fail("з консолі рід переносять кнопкою «Перенести» на екрані «Перенести рід "
                    "у проєкт»: консоль закриється, перенесе й відкриється знову")
    try:
        if a.rollback:
            return ok(A.rollback(hub, a.stamp or None))
        archive = Path(a.archive) if a.archive else None
        if not a.apply:
            pl = A.plan(hub, a.name, archive=archive)
            return ok({**pl.as_dict(), "report": A.report(pl)})
        got = A.apply(hub, a.name, archive=archive, title=a.title, via=a.via)
    except (A.AdoptError, W.WorkspaceError) as exc:
        return fail(str(exc))
    if a.via == "console":
        # Людина переносила сама: пам'ять і інструкції помічника ще не розкладено.
        # Міграція 0.37 знову «не пройдена» — помічник дійде до кроку adopt-after.
        from nyshporka import migrate as M

        M.reopen(hub, "0.37.0", why="рід перенесено в проєкт кнопкою консолі")
    return ok(got)


#: Покрокова інструкція переносу на порталі — на неї ведуть консоль і помічник.
ADOPT_GUIDE = "https://nyshporka.online/onovlennia/nyshporka-0-37-0-proiekty"


def _adopt_home() -> Path:
    """Тека журналу помічника переносу — поруч із журналом оновлення."""
    import tempfile

    from nyshporka.core.workspace import _state_path

    return (_state_path() or Path(tempfile.gettempdir()) / "state.json").parent / "adopt"


def _console_refusal() -> str:
    """Чому з цієї консолі не можна перенести рід; «» — можна."""
    from nyshporka.daemon import app as D

    if not D.LAUNCH:
        return "з консолі (nysh serve) — кнопкою; у терміналі — nysh project adopt <ім'я>"
    busy = D.running_jobs()
    if busy:
        return (f"зараз іде робіт: {busy} — консоль закриється на час переносу, тож спершу "
                "дочекайтесь їх або зупиніть")
    return ""


@op("project.adopt_state", summary="Чи рід лежить у корені і чим скінчився останній перенос",
    private=True, tier="rare",
    when="екран консолі «Перенести рід у проєкт»: що показати, що підставити")
def project_adopt_state(_: NoArgs) -> Envelope:
    """Для екрана переносу: чи є що переносити, підказка імені, останній результат."""
    from nyshporka.core import profile as PF
    from nyshporka.core import workspace as W
    from nyshporka.daemon import restart as RS
    from nyshporka.project import adopt as A

    hub = W.workspace().hub
    leg = A.legacy(hub)
    surname = ""
    if leg["legacy"]:
        try:
            surname = PF.active().display
        except Exception:
            surname = ""
    return ok({**leg, "surname": surname, "hub": str(hub),
               "archive": str(A.default_archive(hub)), "guide": ADOPT_GUIDE,
               "last": A.last_result(hub), "helper": RS.last_result(_adopt_home()),
               "refusal": _console_refusal()})


class ProjectAdoptRestartArgs(ProjectNameArgs):
    title: str = Field(default="", description="назва проєкту людською мовою")
    archive: str = Field(default="", description="тека для архіву; порожньо — сусідка <хаб>-adopt")
    rollback: bool = Field(default=False, description="повернути останній переїзд")


@op("project.adopt_restart", summary="Перенести рід у проєкт з консолі (консоль перезапуститься)",
    args=ProjectAdoptRestartArgs, mutates=True, tier="rare",
    when="людина переносить рід у проєкт сама, кнопкою консолі")
def project_adopt_restart(a: ProjectAdoptRestartArgs) -> Envelope:
    """🧳 Перенос із консолі: помічник чекає, доки консоль закриється, переносить
    (`nysh project adopt … --apply`) і відкриває її знову.

    🔴 Консоль сама тримає Майстерню (`adopt.apply` відмовляє, поки вона жива),
    тож напряму звідси переносити не можна — так само, як оновлюватись
    (`update.apply`). Перешкоди плану перевіряються ДО закриття консолі: інакше
    людина дивилась би на перезапуск, щоб дізнатись те, що можна було сказати
    одразу.
    """
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W
    from nyshporka.daemon import app as D
    from nyshporka.daemon import restart as RS
    from nyshporka.project import adopt as A

    why = _console_refusal()
    if why:
        return fail(why)
    hub = W.workspace().hub
    tail = ["project", "adopt", a.name]
    if a.rollback:
        last = A.last_result(hub)
        if not last or last["state"] != "done":
            return fail("повертати нічого: останнього завершеного переносу немає")
        tail += ["--rollback", "--stamp", str(last["stamp"])]
        title, done = (f"повернення переносу «{a.name}»",
                       ["✅ перенос повернуто", "❌ перенос не повернуто"])
    else:
        try:
            pl = A.plan(hub, a.name, archive=Path(a.archive) if a.archive else None)
        except (A.AdoptError, W.WorkspaceError, P.ProjectError) as exc:
            return fail(str(exc))
        if pl.problems:
            env = fail("перенос не починаю: " + "; ".join(pl.problems))
            env.data = {"codes": pl.codes}
            return env
        tail += ["--apply", "--via", "console"]
        if a.title.strip():
            tail += ["--title", a.title.strip()]
        if a.archive:
            tail += ["--archive", a.archive]
        title, done = (f"перенос роду в проєкт «{a.name}»",
                       ["✅ рід перенесено в проєкт", "❌ рід не перенесено — усе повернуто"])
    cmd = RS.launcher(list(D.LAUNCH.get("argv") or [])) + tail
    task = RS.task_for(cmd, _adopt_home(), cwd=str(hub), title=title,
                       extra={"done_text": done, "project": a.name, "rollback": a.rollback})
    RS.run_after_exit(task)
    return ok({"restarting": True, "project": a.name, "rollback": a.rollback,
               "log": task["log"]})


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
# ── звіти досліджень ─────────────────────────────────────────────────────────
#: Більший звіт консоль не відкриває: це вже не нотатка, а вивантаження.
REPORT_MAX_BYTES = 1_000_000
#: Скільки рядків від початку шукати заголовок `# `.
TITLE_LINES = 40


def _report_title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = [fh.readline() for _ in range(TITLE_LINES)]
    except OSError:
        return path.stem
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


@op("reports.list", summary="Звіти досліджень проєкту: назва, тека, коли змінено",
    section="research", tier="situational", scope="project",
    when="які звіти досліджень є в проєкті — перелік із назвами")
def reports_list(_: NoArgs) -> Envelope:
    from nyshporka.archives import active
    from nyshporka.core import workspace as W
    from nyshporka.search.textops import layer_files

    rep = W.workspace().reports
    files, _cuts = layer_files("notes")
    arch = active()
    labels: dict[str, str] = {}

    def archive_of(kind: str) -> str:
        # Тека на ім'я архіву (`dahmo`, `davo`) — його скороченням, «ДАХмО», а
        # не «Dahmo»; дві теки одного архіву (`davo`, `davio`) — одним іменем,
        # тож консоль кладе їх в одну групу.
        if kind not in labels:
            code = arch.resolve_code(kind) if kind else ""
            labels[kind] = arch.repo_label(code) if code else ""
        return labels[kind]

    rows: list[dict[str, Any]] = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        rel = f.relative_to(rep)
        kind = rel.parts[0] if len(rel.parts) > 1 else ""
        rows.append({"path": rel.as_posix(), "title": _report_title(f),
                     "kind": kind, "archive": archive_of(kind),
                     "mtime": st.st_mtime, "size": st.st_size})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return ok({"root": str(rep), "rows": rows})


class ReportReadArgs(BaseModel):
    path: str = Field(description="звіт від теки reports/ проєкту, як у reports.list")


@op("reports.read", summary="Текст одного звіту дослідження",
    args=ReportReadArgs, section="research", tier="rare", scope="project",
    when="прочитати звіт дослідження з переліку reports.list")
def reports_read(a: ReportReadArgs) -> Envelope:
    from nyshporka.core import workspace as W

    rep = W.workspace().reports.resolve()
    raw = Path(a.path)
    if raw.is_absolute():
        return fail("шлях — від теки reports/ проєкту, не абсолютний")
    path = (rep / raw).resolve()
    # 🔴 Шлях приходить із браузера: `../` вивів би за межі проєкту, а `htr/`
    # — у мільйон файлів прочитаного, яких ця операція не обслуговує.
    try:
        rel = path.relative_to(rep)
    except ValueError:
        return fail("шлях виходить за межі теки reports/ проєкту")
    if not rel.parts or rel.parts[0] == "htr" or path.suffix != ".md":
        return fail("звіт — це файл .md у reports/ поза htr/")
    if not path.is_file():
        return fail(f"звіту «{rel.as_posix()}» немає")
    size = path.stat().st_size
    if size > REPORT_MAX_BYTES:
        return fail(f"звіт завеликий для консолі ({size // 1000} КБ): {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    # Імена для `[[I9012]]` у звіті — як у картках канону. Канону може не бути.
    refs: dict[str, str] = {}
    try:
        from nyshporka.ops_canon import _loaded, _refs

        refs = _refs(_loaded()[1], text)
    except Exception:
        refs = {}
    return ok({"path": rel.as_posix(), "title": _report_title(path), "text": text, "refs": refs})


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


_STATUS = re.compile(r"^status:\s*['\"]?(open|awaiting|closed)", re.M)


def _count_hypotheses(root: Path) -> dict[str, int]:
    """Стани гіпотез із шапок карток — без повного читання канону (картка проєкту)."""
    from nyshporka.core.workspace import Workspace

    out = {"open": 0, "awaiting": 0, "closed": 0}
    d = Workspace(root=root).canonical / "hypotheses"
    for f in d.glob("*.md") if d.is_dir() else ():
        head = f.read_text(encoding="utf-8", errors="replace")[:2000]
        m = _STATUS.search(head)
        if m:
            out[m.group(1)] += 1
    return out


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
    out["color"] = str(tab.get("color") or "")
    out["glyph"] = str(tab.get("glyph") or "")
    icon = str(tab.get("icon") or "")
    out["icon"] = icon if icon in P.ICONS else ""
    out["persons"] = _count_persons(ws.root)
    try:
        from nyshporka.core import profile as PROF

        prof = PROF.active()
        out["surname"] = prof.display or prof.name
    except Exception:
        out["surname"] = ""
    try:
        from nyshporka.canon import memo
        from nyshporka.canon.next import next_decisions

        nd = next_decisions(ws.root, limit=3, canon=memo.canon(ws.root))
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
