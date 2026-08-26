"""📂 Операції вибору шляху: гортач тек і системне вікно.

🔴 Усі чотири — `agent=False`, і це не економія місця в переліку tool'ів (хоч
воно й закінчилось). Агент не натисне кнопку в системному вікні й не подивиться
на список тек очима; для нього шлях — це аргумент, який він і так отримує від
людини. Дати йому право відкрити вікно на екрані дослідника посеред нічного
прогону — рівно та поведінка, від якої вже захищене читання справи.

🔴 Секція `core`, не `material`. Гортач годує і форму заведення справи, і поле
середовища рушіїв, тож вимкнена секція матеріалів гасила б вибір теки на
екранах, які до матеріалів не належать.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class PickCanArgs(BaseModel):
    deep: bool = Field(default=False,
                       description="перевірити створенням вікна (повільніше, чесніше)")


# `private=True`: відповідь називає теки на диску людини — розкладку її архіву.
# Це читання, але не публічне.
@op("pick.can", summary="Чи вміє ця машина відкрити системне вікно вибору",
    args=PickCanArgs, agent=False, private=True)
def pick_can(a: PickCanArgs) -> Envelope:
    """Спитати до того, як показати кнопку.

    🔴 Кнопка, яка не працює, читається як несправність застосунку, а не як межа
    середовища. А середовищ, де вікна не буває, більше, ніж здається: запуск по
    ssh, у контейнері, службою, на сервері без графічної оболонки.
    """
    from nyshporka.picker import native, roots

    able = native.probe(deep=a.deep)
    env = ok({
        "can": able.can,
        "why": able.why,
        "fix": able.fix,
        "display": able.display,
        "roots": [{"path": r.path, "label": r.label, "kind": r.kind, "gone": r.gone}
                  for r in roots()],
    })
    if not able.can:
        env.warn("no_native_dialog", able.why or "системного вікна тут немає")
    return env


class PickBrowseArgs(BaseModel):
    path: str = Field(default="", description="тека, яку показати; порожньо — простір")
    want: Literal["dirs", "files", "all"] = Field(
        default="all", description="що показувати: лише теки, лише файли, все")
    patterns: list[str] = Field(
        default_factory=list,
        description="маски файлів: [\"*.pdf\"]; теки не фільтруються ніколи")
    q: str = Field(default="", description="підрядок для дошуку в межах цієї теки")
    limit: int = Field(default=200, ge=1, le=2000, description="скільки рядків віддати")
    offset: int = Field(default=0, ge=0, le=1_000_000, description="з якого почати")
    show_hidden: bool = Field(default=False, description="показувати приховані")
    describe: bool = Field(
        default=True,
        description="підписувати теки шифрою справи з бібліотеки")


@op("pick.browse", summary="Гортач тек: що лежить у цій теці",
    args=PickBrowseArgs, agent=False, private=True)
def pick_browse(a: PickBrowseArgs) -> Envelope:
    """Вміст однієї теки — імена, лічильники й шлях назад.

    🔴 Підпис теки шифрою — головне, чим гортач кращий за системне вікно. Те
    показує самі назви, а тут видно, що `op3-spr-129` це «ДАХмО 230-3-129,
    виводи дворянства, 1836-1841» і що її вже читали Писарем. Без цього вибір
    справи означає заходити в кожну теку по черзі й дивитись навпомацки.

    ⚠ Гортач не звужений до простору навмисно: увесь його сенс у тому, щоб
    дійти до теки, якої застосунок ще не бачить. Межа стоїть на іншому — на
    тому, що звідси не виходить жодного байта вмісту файлів, лише імена.
    """
    from nyshporka.picker import browse as B

    got = B.listing(a.path or None, want=a.want, patterns=a.patterns, q=a.q,
                    limit=a.limit, offset=a.offset, show_hidden=a.show_hidden,
                    annotate=_describe if a.describe else None)
    env = ok(_as_dict(got))
    if got.error:
        env.warn("cannot_read", got.error)
    if got.truncated:
        env.warn("truncated",
                 f"показано {got.shown} з {got.total} — уточніть пошук у теці")
    if got.adopt:
        # Не помилка й не порада «полагодь»: тека справді видима очима й справді
        # невидима для реєстру. Сказати це треба до того, як людина заведе
        # справу й не знайде її в переліках.
        env.warn("outside_workspace",
                 "тека лежить поза простором: справа звідси не з'явиться ні в "
                 "бібліотеці, ні в пошуку, доки корінь не взято під облік")
    return env


def _describe(path: Path) -> str:
    """Підпис теки з бібліотеки: шифра, назва, роки.

    Довідка — прикраса, тож будь-яка її поламка гаситься тут: навігація
    важливіша за підпис і не сміє від нього залежати.
    """
    try:
        from nyshporka.library import describe_case

        case = describe_case(str(path))
    except Exception:
        return ""
    if not case:
        return ""
    bits = [str(case.get("shifra") or "").strip()]
    title = str(case.get("title") or "").strip()
    if title:
        bits.append(title if len(title) <= 60 else title[:57] + "…")
    yf, yt = case.get("year_from"), case.get("year_to")
    if yf and yt and yf != yt:
        bits.append(f"{yf}–{yt}")
    elif yf or yt:
        bits.append(str(yf or yt))
    return " · ".join(b for b in bits if b)


def _as_dict(got: Any) -> dict[str, Any]:
    return {
        "path": got.path,
        "parent": got.parent,
        "crumbs": [{"label": lbl, "path": p} for lbl, p in got.crumbs],
        "roots": [{"path": r.path, "label": r.label, "kind": r.kind, "gone": r.gone}
                  for r in got.roots],
        "entries": [{"name": e.name, "path": e.path, "kind": e.kind,
                     "frames": e.frames, "pdfs": e.pdfs, "subdirs": e.subdirs,
                     "size": e.size, "locked": e.locked, "why": e.why,
                     "note": e.note} for e in got.entries],
        "shown": got.shown, "total": got.total, "offset": got.offset,
        "truncated": got.truncated,
        "frames": got.frames, "pdfs": got.pdfs, "subdirs": got.subdirs,
        "in_space": got.in_space,
        "adopt": [{"path": p, "cases": n} for p, n in got.adopt],
        "error": got.error,
    }


class PickAskArgs(BaseModel):
    mode: Literal["dir", "file", "files", "save"] = Field(
        default="dir", description="що вибираємо: теку, файл, кілька файлів, куди зберегти")
    purpose: str = Field(
        default="",
        description="чиє це вікно: read.case_dir · roots.add · read.model")
    title: str = Field(default="", description="заголовок вікна")
    start: str = Field(default="", description="звідки почати")
    name: str = Field(default="", description="запропоноване ім'я файлу (для save)")
    patterns: list[str] = Field(
        default_factory=list, description="маски файлів: [\"*.mlmodel\", \"*.pt\"]")
    label: str = Field(default="файли", description="підпис фільтра у вікні")


# 🔴 `long=True` — не для зручності, а тому що інакше застосунок стає. Синхронна
# операція виконується на циклі подій демона, а системне вікно чекає людину:
# доки вона не відповість, не працює ні черга, ні інші вкладки, ні статика.
@op("pick.ask", summary="Відкрити системне вікно вибору — робота в черзі",
    args=PickAskArgs, agent=False, private=True, long=True)
def pick_ask(a: PickAskArgs) -> Envelope:
    """Показати системне вікно й дочекатись відповіді.

    🔴 «Нічого не вибрано» тут означає чотири різні речі, і кожна лікується
    інакше: людина скасувала (нічого не робимо) · вікна немає де показати
    (лишаємось у гортачі) · ніхто не відповів (найчастіше вікно сховалось за
    браузером — про це треба сказати) · Tk упав (треба назвати причину). Тому
    стан їде окремим полем, а не зводиться до порожнього шляху.

    ⚠ Таймаут повертає успіх із позначкою, а не відмову: невдача операції
    робить роботу червоною, а червона робота запрошує перезапустити. Тут
    перезапускати нічого — людина просто не відповіла.
    """
    from nyshporka.picker import native

    types: tuple[native.FileType, ...] = ()
    if a.patterns:
        types = (native.FileType(label=a.label or "файли", patterns=tuple(a.patterns)),)
    got = native.ask(a.mode, title=a.title, start=a.start or None, types=types,
                     name=a.name, slot=a.purpose or a.mode)
    env = ok({"state": got.state, "path": got.path, "paths": list(got.paths),
              "why": got.why, "took_s": round(got.took_s, 2),
              "purpose": a.purpose})
    if got.state == "timeout":
        env.warn("dialog_timeout", got.why)
    elif got.state == "unavailable":
        env.warn("no_native_dialog", got.why)
    elif got.state == "error":
        env.warn("dialog_failed", got.why)
    return env


class PickMkdirArgs(BaseModel):
    path: str = Field(description="де створити")
    name: str = Field(description="ім'я нової теки")


@op("pick.mkdir", summary="Створити теку, не виходячи з вибору шляху",
    args=PickMkdirArgs, agent=False, private=True, mutates=True)
def pick_mkdir(a: PickMkdirArgs) -> Envelope:
    """Нова тека там, куди зараз дивиться гортач.

    Потрібна там, де шлях ще не існує: вивантаження, тека під прочитаний текст.
    Змусити людину вийти в провідник заради одного `mkdir` означає обірвати
    роботу на середині.
    """
    name = a.name.strip().strip("/\\")
    if not name or name in {".", ".."} or any(c in name for c in '\\/:*?"<>|'):
        return fail("так теку не назвати: у назві не може бути / \\ : * ? \" < > |")
    parent = Path(a.path).expanduser()
    if not parent.is_dir():
        return fail(f"немає теки, у якій створювати: {parent}")
    here = parent / name
    if here.exists():
        return fail(f"«{name}» тут уже є")
    try:
        here.mkdir()
    except OSError as exc:
        return fail(f"не вийшло створити теку: {exc}")
    return ok({"path": str(here), "name": name})
