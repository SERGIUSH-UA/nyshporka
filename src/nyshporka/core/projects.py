"""📁 Проєкти Майстерні — рід чи замовлення в підтеці `projects/<ім'я>/`.

Матеріал (кадри, прочитане, реєстр справ) один на Майстерню; висновок (канон,
профіль, вердикти, журнал пошуку, звіти) належить проєкту. Простір, відкритий
у теці проєкту, бачить шар Майстерні цілком, а проєктний — лише свій
(`core.workspace`). Тут — перелік проєктів, відкриття сусіднього і
«підсвітка чужого»: де ще є збіг, без самого вмісту.

🔴 Реєстр проєктів — сама тека `projects/`. Окремого файла-переліку немає: два
джерела правди про те, які проєкти існують, розійшлися б при першому ж
перенесенні теки руками.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from nyshporka.core import workspace as W

#: Id кореня Майстерні старого типу, де проєкт лежить у самому корені.
ROOT_ID = "."

#: Ім'я проєкту — тека і ключ у спільних файлах (`cited_by` маніфесту доказів),
#: тому лише латиниця, цифри й дефіс: без пробілів, двокрапок і регістрових
#: двійників, що на Windows вказували б на ту саму теку.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")

KINDS = ("family", "order")

#: Колір проєкту в консолі (`[project] color`): лише `#rrggbb`.
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
#: Знак проєкту (`[project] glyph`): буква чи емодзі, не слово.
GLYPH_MAX = 2


class ProjectError(W.WorkspaceError):
    """Проєкту немає або ім'я непридатне."""


#: «Для кого» на час одного запуску (читання, хмара): підпис замовника, що
#: відрізняється від проєкту простору. `None` — не задано, діє простір.
_ORDERED_FOR: ContextVar[str | None] = ContextVar("nysh_ordered_for", default=None)


@dataclass(frozen=True)
class Project:
    id: str
    root: Path
    name: str
    kind: str
    archived: bool = False
    color: str = ""
    glyph: str = ""


def check_color(color: str) -> str:
    if color and not _COLOR.match(color):
        raise ProjectError(f"колір «{color}» — лише #rrggbb (напр. #8a5a2b)")
    return color


def check_glyph(glyph: str) -> str:
    if len(glyph.strip()) > GLYPH_MAX or glyph != glyph.strip():
        raise ProjectError(f"знак «{glyph}» — одна буква чи емодзі, до {GLYPH_MAX} символів")
    return glyph


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ProjectError(
            f"ім'я проєкту «{name}» не годиться: лише малі латинські літери, цифри "
            "й дефіс, до 48 знаків (напр. «rid-druzhyny», «order-2026-03»)")
    return name


def projects_dir(hub: Path) -> Path:
    return hub / W.PROJECTS_DIR


def _from_dir(path: Path) -> Project | None:
    tab = W.read_project_table(path)
    if tab is None:
        return None
    kind = str(tab.get("kind") or "family")
    # Вигляд — не дані: зіпсоване значення руками в маркері не валить перелік.
    color, glyph = str(tab.get("color") or ""), str(tab.get("glyph") or "")
    try:
        check_color(color)
    except ProjectError:
        color = ""
    try:
        check_glyph(glyph)
    except ProjectError:
        glyph = ""
    return Project(id=path.name, root=path, name=str(tab.get("name") or path.name),
                   kind=kind, archived=bool(tab.get("archived")), color=color, glyph=glyph)


def list_projects(hub: Path, *, archived: bool = False) -> list[Project]:
    """Проєкти Майстерні за іменем. Корінь старого типу — першим, з id «.».

    Корінь хаба без `hub_only` — це теж проєкт: рід, що жив у просторі ще до
    Майстерні. Його висновки існують, і «підсвітка чужого» мусить їх бачити.
    """
    out: list[Project] = []
    cfg = W._read_marker(hub / W.MARKER)
    if not cfg.get("hub_only"):
        out.append(Project(id=ROOT_ID, root=hub, name=str(cfg.get("name") or hub.name),
                           kind="family"))
    pdir = projects_dir(hub)
    if pdir.is_dir():
        for child in sorted(pdir.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            pr = _from_dir(child)
            if pr is not None and (archived or not pr.archived):
                out.append(pr)
    return out


def current_id(ws: W.Workspace) -> str | None:
    """Id проєкту простору: ім'я теки, «.» для кореня старого типу, `None` у чистому хабі."""
    if ws.project is not None:
        return ws.project
    return None if ws.hub_only else ROOT_ID


def tag(ws: W.Workspace | None = None) -> str:
    """Позначка «хто замовив» для спільних записів Майстерні: прогонів, черги, джобів.

    Ім'я проєкту, «.» для кореня старого типу, порожньо — з кореня чистої
    Майстерні (міжпроєктний режим, замовник — сама Майстерня).
    """
    if ws is None and (who := _ORDERED_FOR.get()) is not None:
        return who
    return current_id(ws or W.workspace()) or ""


def ordered_for_id(value: str | None, ws: W.Workspace | None = None) -> str | None:
    """Перевірене «для кого»: `None` — проєкт простору, `""` — сама Майстерня.

    Лише проєкт, що є в цій Майстерні: підпис прогону іменем, якого немає,
    зробив би прогін нічиїм — фільтр «моє» не знайшов би його ніде.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return ""
    ws = ws or W.workspace()
    known = {tag_of(p.id) for p in list_projects(ws.hub)}
    if value not in known:
        raise ProjectError(f"«для кого»: проєкту «{value}» у цій Майстерні немає. "
                           f"Є: {', '.join(sorted(known)) or 'жодного'}")
    return value


@contextmanager
def ordered_for(value: str | None) -> Iterator[None]:
    """Підписувати спільні записи цього запуску (робота, прогін, захід хмари)
    іменем `value`, а не проєктом простору. `None` — нічого не міняти.

    Підпис — хто замовив, а не замок: шукати в прочитаному зможуть усі проєкти.
    """
    if value is None:
        yield
        return
    token = _ORDERED_FOR.set(value)
    try:
        yield
    finally:
        _ORDERED_FOR.reset(token)


@lru_cache(maxsize=8)
def _legacy_for(marker: str, _stamp: tuple[int, int] | None) -> str:
    return str(W._read_marker(Path(marker)).get("legacy_project") or "")


def legacy_project(hub: Path) -> str:
    """Проєкт, у який переїхав корінь старого типу (`[workspace] legacy_project`).

    Порожньо — переїзду не було. Записи з позначкою «.» (прогони, черга,
    роботи, хмара) належать тоді цьому проєкту: переписувати тисячі файлів
    заради нової позначки — ризик більший за користь.
    """
    marker = hub / W.MARKER
    return _legacy_for(str(marker), W._stamp_of(marker))


def _legacy_here() -> str:
    try:
        return legacy_project(W.workspace().hub)
    except Exception:  # простору немає — старих записів теж нема до кого вести
        return ""


def tag_of(value: object) -> str:
    """Позначка запису. Записи до хвилі проєктів її не мають — це корінь старого типу.

    Після переїзду кореня (`legacy_project`) «.» читається як ім'я проєкту.
    """
    got = ROOT_ID if value is None else str(value)
    if got == ROOT_ID:
        return _legacy_here() or ROOT_ID
    return got


def is_mine(value: object, ws: W.Workspace | None = None) -> bool:
    return tag_of(value) == tag(ws)


def project_dir(hub: Path, pid: str) -> Path:
    if pid == ROOT_ID and legacy_project(hub):
        pid = legacy_project(hub)
    if pid == ROOT_ID:
        if W._read_marker(hub / W.MARKER).get("hub_only"):
            raise ProjectError("у цій Майстерні корінь не є проєктом (hub_only)")
        return hub
    path = projects_dir(hub) / check_name(pid)
    if _from_dir(path) is None:
        known = ", ".join(p.id for p in list_projects(hub, archived=True)) or "жодного"
        raise ProjectError(f"проєкту «{pid}» немає в {projects_dir(hub)}. Є: {known}")
    return path


def open_project(pid: str, base: W.Workspace | None = None) -> W.Workspace:
    """Простір проєкту `pid` тієї самої Майстерні.

    🔴 Сусідній проєкт, відкритий із сесії в ІНШОМУ проєкті, — лише для
    читання. Агент у роді А може за прямим проханням людини подивитись рід Б,
    але записати туди вердикт чи особу — ні: так знахідка з одного роду не
    падає випадково в канон іншого. З кореня Майстерні (міжпроєктний режим)
    запис дозволено — там людина свідомо працює з кількома проєктами.
    """
    base = base or W.workspace()
    here = current_id(base)
    readonly = base.project is not None and here != pid
    return replace(W._build(project_dir(base.hub, pid), base.origin), readonly=readonly)


def others(ws: W.Workspace) -> list[Project]:
    """Інші (неархівні) проєкти тієї самої Майстерні."""
    here = current_id(ws)
    return [p for p in list_projects(ws.hub) if p.id != here]


def searched_by(ws: W.Workspace) -> dict[str, dict[str, str]]:
    """Ключ справи → {проєкт: дата останнього свіпу} по всіх проєктах Майстерні.

    Справи спільні, а «прошукано» — проєктне: той самий рукопис для одного
    роду вичесано, для іншого ні. Тому зріз бере слід КОЖНОГО проєкту, а не
    лише поточного, — інакше в Майстерні не видно, хто що шукав, а в проєкті
    не видно, що сусідній рід цю книгу вже пройшов. Лише читання: N файлів
    сліду, без обходу тек.
    """
    from nyshporka.search import trace

    out: dict[str, dict[str, str]] = {}
    for pr in list_projects(ws.hub):
        pid = tag_of(pr.id)
        for key, when in trace.searched(W.Workspace(root=pr.root)).items():
            got = out.setdefault(key, {})
            got[pid] = max(got.get(pid, ""), when)
    return out


# ── підсвітка чужого ─────────────────────────────────────────────────────────
#: Шари проєкту, у яких шукає підсвітка: канон, нотатки й погляд на сторінки
#: (коментарі). Решта шарів — Майстерня, вони й так спільні.
PEEK_LAYERS = ("canon", "notes", "pages")

#: Рядок погляду у файлі справи чи погляду (`indent=1`: поле на рядок).
_VIEW_LINE = re.compile(r'^\s*"(comment|agent)"\s*:')


def _layer_files(root: Path, layer: str, *, inline: bool = False) -> Iterator[Path]:
    if layer == "pages":
        # Погляд кореня старого типу (`inline`) вбудований у файли справ Майстерні.
        ws = W.Workspace(root=root)
        base = ws.pages if inline else ws.views
        if base.is_dir():
            yield from base.glob("*/*.json")
    elif layer == "canon":
        base = W.Workspace(root=root).canonical
        if base.is_dir():
            yield from base.rglob("*.md")
    elif layer == "notes":
        base = W.Workspace(root=root).reports
        if base.is_dir():
            yield from base.glob("*.md")
            for sub in base.iterdir():
                if sub.is_dir() and sub.name != "htr":
                    yield from sub.rglob("*.md")


def peek(ws: W.Workspace, regex: re.Pattern[str],
         layers: tuple[str, ...] = PEEK_LAYERS) -> list[dict[str, object]]:
    """Скільки рядків збігається в шарах інших проєктів — лише лічильник.

    🔴 Вміст не повертається свідомо. Агент у проєкті має знати, що «у роді Б
    теж є Сидоруки» — і сказати про це людині, але самі Сидоруки іншого роду в
    його контекст не потрапляють: він сплутав би одну родину з іншою.
    """
    out: list[dict[str, object]] = []
    for pr in others(ws):
        for layer in layers:
            count = 0
            for f in _layer_files(pr.root, layer, inline=pr.id == ROOT_ID):
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                count += sum(1 for line in text.splitlines() if regex.search(line)
                             and (layer != "pages" or _VIEW_LINE.match(line)))
            if count:
                out.append({"project": pr.id, "name": pr.name, "layer": layer,
                            "count": count})
    return out
