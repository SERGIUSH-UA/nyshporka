"""📂 Гортач тек: що лежить у цій теці — щоб шлях не доводилось набирати руками.

🔴 жодного вмісту файлів. Модуль віддає імена, розміри й лічильники — і на цьому
зупиняється назавжди. Спокуса додати сюди прев'ю («покажемо перші рядки, щоб
було видно, що це за файл») виглядає невинно рівно доти, доки не помітиш, що
вона перетворює перелік імен на довільне читання будь-якого файлу машини по
HTTP. Приймач цього правила — тест, який шукає в цьому файлі `read_bytes`,
`read_text` і `open(`; він не про стиль, він про межу.

🔴 Гортач нерекурсивний, і саме тому безпечно ходить крізь junction'и. Одна тека
за виклик — циклу немає де закільцюватись. Той, хто захоче додати рекурсію,
мусить спершу вирішити задачу «data/raw/dahmo_196 веде на інший диск», яка зараз
просто не виникає.

Модуль нічого не знає про справи, шифри й бібліотеку: прикладну довідку до рядка
дописує викликач через `annotate`. Так той самий гортач обслуговує обидві морди,
не тягнучи у спільний шар домен жодної з них.
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from nyshporka.cases.frames import IMG_EXT

#: Скільки записів віддаємо за раз. Не стеля теки — стеля показу: знаменник їде
#: поруч, тож обрізання видно.
DEFAULT_LIMIT = 200
#: Понад це не піднімається навіть на явний запит: далі сторінка перестає бути
#: сторінкою, а браузер починає малювати десятки тисяч вузлів.
MAX_LIMIT = 2000
#: Скільки записів дозволено перебрати, рахуючи вміст підтек. Рахунок кадрів —
#: це `scandir` на кожну дитину, і на мережевому диску саме він, а не сам
#: перелік, робить відкриття вікна повільним.
COUNT_CAP = 4000

Kind = Literal["dir", "file"]
Want = Literal["dirs", "files", "all"]
RootKind = Literal["drive", "home", "workspace", "case_root"]


@dataclass(frozen=True)
class Root:
    """Місце, з якого починають гортати."""

    path: str
    label: str
    kind: RootKind
    #: Тека оголошена, але зараз недосяжна (від'єднаний диск). Показуємо все
    #: одно: зникнення кореня зі списку читається як поламка застосунку.
    gone: bool = False


@dataclass(frozen=True)
class Entry:
    """Рядок гортача."""

    name: str
    path: str
    kind: Kind
    #: Кадрів і PDF безпосередньо в теці. `None` — не рахували (велика тека).
    frames: int | None = None
    pdfs: int | None = None
    #: Скільки тек усередині.
    #:
    #: 🔴 Не косметика. Тека справи часто тримає кадри не в собі, а в підтеці
    #: (`op3-spr-3/pages/00001.jpg`), і сам лише лічильник кадрів показав би там
    #: «0» — тобто повна справа виглядала б порожньою, і людина пройшла б повз.
    #: Глибше одного рівня не лізе ніхто: це `scandir` на кожну дитину, і саме
    #: він робить відкриття вікна повільним.
    subdirs: int | None = None
    size: int = 0
    mtime: float = 0.0
    #: Запис Є, але зайти в нього не вийде.
    locked: bool = False
    #: Чому locked — або чому цю теку не можна оголосити коренем справ.
    why: str = ""
    #: Прикладна довідка від викликача: шифра, назва, роки, модель прогону.
    note: str = ""


@dataclass(frozen=True)
class Listing:
    """Одна тека — і чесний знаменник до неї."""

    path: str
    parent: str | None
    roots: tuple[Root, ...] = ()
    #: Хлібні крихти: (підпис, шлях) від кореня диска до поточної теки.
    crumbs: tuple[tuple[str, str], ...] = ()
    entries: tuple[Entry, ...] = ()
    shown: int = 0
    #: Скільки було до обрізання. Обрізаний список без знаменника виглядає як
    #: повна відповідь — та сама вада, що нуль без знаменника.
    total: int = 0
    offset: int = 0
    truncated: bool = False
    #: Кадрів, PDF і тек у самій цій теці — щоб підтвердження несло лічильник
    #: вмісту, а не саму лише назву.
    frames: int = 0
    pdfs: int = 0
    subdirs: int = 0
    #: Тека під одним із коренів справ — тобто застосунок її вже бачить.
    in_space: bool = False
    #: Предки, які варто оголосити коренем, із числом схожих на справи тек у
    #: кожному. Порожньо, коли тека вже видима.
    adopt: tuple[tuple[str, int], ...] = ()
    #: Чому теку не показано (немає прав, зникла). Порожньо — все гаразд.
    error: str = ""


# ── натуральний порядок ──────────────────────────────────────────────────────
_NUM = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[tuple[int, int, str], ...]:
    """Ключ, за яким `spr_2` стоїть перед `spr_10`.

    🔴 Архівні теки нумеровані, і лексикографічний порядок ставить їх у пам'ять
    людини задом наперед: справа 10 перед справою 2, кадр 0100 перед кадром 002.
    Перша редакція гортача сортувала саме так, і на теці сканів це неправильно з
    першого погляду.

    ⚠ Кортеж завжди триелементний. Мішати `int` і `str` у порівнянні не можна:
    перша ж тека з літерою після цифри дала б `TypeError` — тобто гортач падав
    би не на екзотиці, а на `spr_12a`.
    """
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t.casefold())
                 for t in _NUM.split(name) if t)


def _entry_key(e: Entry) -> tuple[int, tuple[tuple[int, int, str], ...]]:
    """Теки перші, далі файли; всередині кожної групи — натурально."""
    return (0 if e.kind == "dir" else 1, natural_key(e.name))


# ── диски й корені ───────────────────────────────────────────────────────────
def drives() -> list[str]:
    """Літери дисків на Windows; на решті — корінь файлової системи.

    🔴 Перебір 26 літер через `os.path.exists` — пастка, а не фолбек. Кожна
    перевірка неіснуючої мережевої літери впирається в таймаут SMB, і гортач
    відкривається десятки секунд без жодного натяку, чому. Тому драбина: рідний
    `os.listdrives` (3.12+), далі бітова маска ядра (нуль вводу-виводу, працює
    на 3.11 — нашому мінімумі), і лише як останній рубіж — перебір.
    """
    if os.name != "nt":
        return ["/"]
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        try:
            return [str(d) for d in listdrives()]
        except OSError:
            pass
    # ⚠ Перевірка саме `sys.platform`, а не `os.name`: інакше засіб перевірки
    # типів не знає, що `windll` тут існує, і вимагає позначки, яку інший засіб
    # тут же називає зайвою.
    mask = 0
    if sys.platform == "win32":
        try:
            import ctypes

            mask = int(ctypes.windll.kernel32.GetLogicalDrives())
        except Exception:
            mask = 0
    if mask:
        return [f"{chr(ord('A') + i)}:\\" for i in range(26) if mask >> i & 1]
    import string

    return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]


def _space() -> object | None:
    """Простір або `None`, якщо його ще немає. Гортач мусить працювати й без."""
    try:
        from nyshporka.core.workspace import WorkspaceError, workspace

        try:
            return workspace()
        except WorkspaceError:
            return None
    except Exception:  # pragma: no cover — простір недоступний як модуль
        return None


def roots() -> tuple[Root, ...]:
    """Звідки починати гортати — робочі місця, а не корінь диска.

    🔴 Порядок не випадковий: простір, оголошені корені, домівка, диски. Людина
    зі сканами на зовнішньому диску відкриває гортач десятки разів на день, і
    п'ять кліків від кореня диска до потрібної теки — це те, через що гортачем
    перестають користуватись і повертаються до копіювання шляху з провідника.

    🔴 Оголошені корені беруться з оголошеного переліку, а не з `case_roots()`:
    той віддає лише наявні теки, тож від'єднаний зовнішній диск зникав би зі
    списку — рівно там, де людині потрібна причина, вона бачила б порожнє місце.
    """
    out: list[Root] = []
    ws = _space()
    if ws is not None:
        raw = Path(str(getattr(ws, "raw", "")))
        out.append(Root(path=str(raw), label="простір", kind="workspace",
                        gone=not raw.is_dir()))
        for p in getattr(ws, "extra_case_roots", ()):
            here = Path(str(p))
            out.append(Root(path=str(here), label=here.name or str(here),
                            kind="case_root", gone=not here.is_dir()))
    home = Path.home()
    out.append(Root(path=str(home), label="домівка", kind="home", gone=not home.is_dir()))
    out += [Root(path=d, label=d.rstrip("\\/") or d, kind="drive") for d in drives()]
    return tuple(out)


# ── допоміжне ────────────────────────────────────────────────────────────────
def _hidden(entry: os.DirEntry[str]) -> bool:
    """Чи ховати запис.

    На Windows імені з крапки замало: `$RECYCLE.BIN` і `System Volume
    Information` крапки не мають, лізуть у кожен корінь диска й ще й як
    «замкнені», бо прав на них немає.
    """
    if entry.name.startswith("."):
        return True
    if os.name != "nt":
        return False
    try:
        # ⚠ `st_file_attributes` є лише у Windows-збірці `os.stat_result`, і
        # саме тому доступ іде через `getattr`, а не полем. Перевіряч, запущений
        # на Linux (CI), поля не бачить і валить прогін — а на машині розробника
        # під Windows видно рівно протилежне. Гілка й так недосяжна поза `nt`:
        # вище стоїть ранній вихід.
        attrs = int(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0))
    except (OSError, AttributeError):
        return False
    return bool(attrs & 0x2 or attrs & 0x4)   # HIDDEN | SYSTEM


def _count(d: Path) -> tuple[int, int, int]:
    """Скільки кадрів, PDF і тек лежить безпосередньо в цій теці."""
    imgs = pdfs = dirs = 0
    try:
        with os.scandir(d) as it:
            for p in it:
                try:
                    if p.is_dir():
                        dirs += 1
                        continue
                    if not p.is_file():
                        continue
                except OSError:
                    continue
                ext = os.path.splitext(p.name)[1].lower()
                if ext in IMG_EXT:
                    imgs += 1
                elif ext == ".pdf":
                    pdfs += 1
    except OSError:
        pass
    return imgs, pdfs, dirs


def _looks_like_case(d: Path) -> bool:
    """Чи схожа тека на справу — тобто чи є в ній кадри.

    ⚠ Дивиться лише прямий вміст. Справа, що тримає кадри в підтеці, сюди не
    порахується — і це свідома межа: рахувати глибше означало б обходити весь
    диск заради підказки, яка лише радить, який предок оголосити коренем.
    """
    imgs, pdfs, _ = _count(d)
    return bool(imgs or pdfs)


def _crumbs(p: Path) -> tuple[tuple[str, str], ...]:
    """Хлібні крихти від кореня диска до поточної теки."""
    out: list[tuple[str, str]] = []
    cur = p
    for _ in range(64):
        out.append((cur.name or str(cur), str(cur)))
        if cur.parent == cur:
            break
        cur = cur.parent
    return tuple(reversed(out))


def _why_not_root(p: Path) -> str:
    """Чому цю теку не можна оголосити коренем справ — або порожньо.

    🔴 Заборонену теку показуємо з причиною, а не ховаємо. Людина бачить диск у
    провіднику; якщо його немає тут, вона шукатиме поламку в застосунку.
    """
    try:
        from nyshporka.core.workspace import WorkspaceError, validate_root

        validate_root(p)
    except WorkspaceError as exc:
        return str(exc)
    except Exception:  # pragma: no cover — простір недоступний
        return ""
    return ""


def _in_space(p: Path) -> bool:
    """Чи бачить застосунок цю теку вже зараз.

    ⚠ Порівняння через `abspath`, не `resolve`: великі фонди підключені в
    простір junction'ами, і розкриття посилання зробило б їх «чужими».
    """
    ws = _space()
    if ws is None:
        return False
    try:
        known = ws.case_roots()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        return False
    here = os.path.normcase(os.path.abspath(p))
    for root in known:
        base = os.path.normcase(os.path.abspath(root))
        if here == base or here.startswith(base + os.sep):
            return True
    return False


def _adopt_chain(p: Path, depth: int = 3) -> tuple[tuple[str, int], ...]:
    """Предки, які варто оголосити коренем, із числом схожих на справи тек.

    🔴 Пропонуємо предка, а не саму обрану теку. Оголошувати коренем кожну
    окрему справу означає маркер простору на сотню рядків — і людину, яка
    повторює той самий рух після кожного завантаження.
    """
    out: list[tuple[str, int]] = []
    cur = p
    for _ in range(depth):
        if cur.parent == cur:
            break
        cur = cur.parent
        n = 0
        try:
            with os.scandir(cur) as it:
                for child in it:
                    try:
                        if child.is_dir() and _looks_like_case(Path(child.path)):
                            n += 1
                    except OSError:
                        continue
                    if n >= 99:
                        break
        except OSError:
            continue
        out.append((str(cur), n))
    return tuple(out)


def _matches(name: str, patterns: Sequence[str]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pat.lower()) for pat in patterns)


def _say_denied(exc: OSError) -> str:
    """Причина людською мовою.

    🔴 Голий текст ОС приходить мовою системи («Отказано в доступе») і без назви
    того, до чого не пустили. Той самий урок, що в пробнику середовища рушіїв:
    повідомлення мусить називати предмет.
    """
    if isinstance(exc, PermissionError):
        return "немає прав на цю теку"
    if isinstance(exc, FileNotFoundError):
        return "теки більше немає"
    if isinstance(exc, NotADirectoryError):
        return "це не тека"
    text = str(exc) or type(exc).__name__
    return f"система не пускає: {text}"


def _resolve(path: str | Path | None) -> Path:
    """Куди йти. Неіснуючий шлях підіймається до найближчого живого предка.

    ⚠ `abspath`, не `resolve`: `resolve` розкриває junction'и, а великі фонди
    підключені в простір саме ними. Шлях після розкриття перестає збігатися з
    тим, що показано людині, і гортач починає стрибати не туди, куди клацнули.
    """
    if path is None or not str(path).strip():
        ws = _space()
        if ws is not None:
            raw = Path(str(getattr(ws, "raw", "")))
            if raw.is_dir():
                return raw
        return Path.home()
    p = Path(os.path.abspath(Path(str(path)).expanduser()))
    if p.is_file():
        p = p.parent
    for _ in range(64):
        if p.is_dir() or p.parent == p:
            return p
        p = p.parent
    return p


def _scan(start: Path, *, want: Want, patterns: Sequence[str], q: str,
          show_hidden: bool) -> list[Entry]:
    out: list[Entry] = []
    low_q = q.casefold().strip()
    with os.scandir(start) as it:
        for de in it:
            if not show_hidden and _hidden(de):
                continue
            if low_q and low_q not in de.name.casefold():
                continue
            try:
                is_dir = de.is_dir()
            except OSError as exc:
                # 🔴 Запис лишається в переліку. Перша редакція гортача робила
                # тут `continue`, і тека, на яку немає прав, просто зникала: у
                # провіднику вона є, у застосунку її немає — і це читається як
                # поламка застосунку, а не як межа прав.
                out.append(Entry(name=de.name, path=de.path, kind="dir",
                                 locked=True, why=_say_denied(exc)))
                continue
            if is_dir:
                if want == "files":
                    continue
                out.append(Entry(name=de.name, path=de.path, kind="dir",
                                 why=_why_not_root(Path(de.path))))
                continue
            if want == "dirs":
                continue
            if patterns and not _matches(de.name, patterns):
                continue
            size = 0
            mtime = 0.0
            try:
                st = de.stat()
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                pass
            out.append(Entry(name=de.name, path=de.path, kind="file",
                             size=size, mtime=mtime))
    return out


def _counted(e: Entry) -> Entry:
    if e.kind != "dir" or e.locked:
        return e
    imgs, pdfs, dirs = _count(Path(e.path))
    return replace(e, frames=imgs, pdfs=pdfs, subdirs=dirs)


def _noted(e: Entry, annotate: Callable[[Path], str]) -> Entry:
    try:
        note = annotate(Path(e.path))
    except Exception:
        # Довідка — прикраса. Її поламка не сміє забирати в людини навігацію.
        return e
    return replace(e, note=note) if note else e


# ── головне ──────────────────────────────────────────────────────────────────
def listing(path: str | Path | None = None, *,
            want: Want = "all",
            patterns: Sequence[str] = (),
            q: str = "",
            limit: int = DEFAULT_LIMIT,
            offset: int = 0,
            show_hidden: bool = False,
            count_children: bool = True,
            annotate: Callable[[Path], str] | None = None) -> Listing:
    """Вміст однієї теки: підтеки, файли, знаменник і шлях назад.

    `patterns` — маски файлів (`("*.pdf",)`); теки не фільтруються ніколи, бо
    інакше крізь них не пройти. `q` — підрядок для дошуку в межах теки, і
    рахується він тут, на сервері: на теці з тисячами записів фіксована пачка в
    пам'яті браузера мовчки ховає більшість.

    `annotate` дописує рядку прикладну довідку й кличеться лише для записів, що
    справді потрапили у видиме вікно.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    start = _resolve(path)
    parent = str(start.parent) if start.parent != start else None
    base = Listing(path=str(start), parent=parent, roots=roots(),
                   crumbs=_crumbs(start), in_space=_in_space(start))

    try:
        found = _scan(start, want=want, patterns=patterns, q=q, show_hidden=show_hidden)
    except OSError as exc:
        # 🔴 Тека, у яку не пускають, — це відповідь, а не поламка. `parent`
        # лишається заповненим, тож із глухого кута є чим піднятись угору.
        return replace(base, error=_say_denied(exc))

    found.sort(key=_entry_key)
    total = len(found)
    window = found[offset:offset + limit]

    # Рахунок вмісту — лише для видимих записів. У першій редакції він робився
    # для кожної підтеки, і на теці з 500 дітьми це 500 обходів каталогу на одне
    # відкриття вікна.
    if count_children and total <= COUNT_CAP:
        window = [_counted(e) for e in window]
    if annotate is not None:
        window = [_noted(e, annotate) for e in window]

    imgs, pdfs, dirs = _count(start)
    return replace(base, entries=tuple(window), shown=len(window), total=total,
                   offset=offset, truncated=total > offset + len(window),
                   frames=imgs, pdfs=pdfs, subdirs=dirs,
                   adopt=() if base.in_space else _adopt_chain(start))


__all__ = ["COUNT_CAP", "DEFAULT_LIMIT", "MAX_LIMIT", "Entry", "Kind", "Listing",
           "Root", "RootKind", "Want", "drives", "listing", "natural_key", "roots"]
