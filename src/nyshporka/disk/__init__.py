"""💽 Місце на диску: що в просторі можна прибрати, а що — ніколи.

Людина, якій закінчується диск, питала агента, що видалити, і дістала перелік
тек із розмірами — без відповіді, котра з них незамінна. Частина простору
відтворюється однією командою, частина — ні, і вгадувати це за назвою теки не
можна.

Три класи:

* **лишити** — прочитане (`reports/htr`), стор тексту, журнал обміну й прийняті
  пакети, сховище сторінок, канон;
* **відтворюване** — стиснуті кадри й асети хмари, тимчасове заходів, власні
  пакети в `outbox`;
* **кадри справи** — знімаються лише ті, що прочитано власним прогоном саме
  цієї теки, і лише коли справа є в Супрязі вашим внеском.

🔴 Правило всього модуля: **за сумніву — лишити.** Кожна перевірка, що не
змогла відповісти (стан заходів не читається, тека за лінком, прогону не
знайдено), веде до «не чіпаю» з причиною, а не до видалення. Рев'ю 18.10.2026
знайшло, як попередня версія зносила кадри на архівному диску (junction вище
теки справи), непрочитану теку справи з двома теками і вміст цілі junction'а
`outbox` — кожен такий шлях тепер закритий явною перевіркою й тестом.
"""
from __future__ import annotations

import contextlib
import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Позначка знятих кадрів — та сама, яку читають бібліотека й реєстр справ
#: (`cases.collect.OFFLOAD_MARKER`, `library._OFFLOAD_MARKER`).
OFFLOAD_MARKER = "_offloaded.json"
#: Паспорти теки справи (`cases.collect._where_from_passport`).
PASPORTY = ("_source.json", "source.json", "meta.json")
#: Пакет у `outbox`, свіжіший за це, може ще заливатись сусідньою пачкою.
OUTBOX_FRESH_SEC = 3600

LYSHYTY = "keep"
VIDTVORIUVANE = "rebuild"

#: Тип пункту чистки — полем, а не за частинами шляху: слово «outbox» чи
#: «cloud» вище простору (`X:/outbox/prostir`) інакше міняло б правила.
KHMARA = "cloud"
OUTBOX = "outbox"


class DiskError(RuntimeError):
    """Дію не виконано — з причиною для людини."""


@dataclass
class Item:
    """Одна тека чи файл простору в звіті."""

    klas: str
    label: str
    path: str
    why: str
    kind: str = ""
    bytes: int | None = None
    files: int | None = None
    exists: bool = True

    def as_json(self) -> dict[str, Any]:
        return {"class": self.klas, "label": self.label, "path": self.path, "why": self.why,
                "bytes": self.bytes, "files": self.files, "exists": self.exists}


@dataclass
class Plan:
    """Що прибере чистка: шляхи, байти, і чому щось лишилось."""

    remove: list[Item] = field(default_factory=list)
    kept: list[dict[str, str]] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(i.bytes or 0 for i in self.remove)


# ── лінки ────────────────────────────────────────────────────────────────────

def _is_link(p: Path | str) -> bool:
    """Симлінк, junction чи точка монтування. `Path.is_junction` є лише з 3.12,
    тож — атрибутом reparse point."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(
        getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _real(p: Path | str) -> str:
    return os.path.normcase(os.path.realpath(p))


def _za_linkom(p: Path, base: Path) -> str:
    """Лінк на шляху від `base` (не включно) до `p` (включно); «» — немає.

    🔴 Саме весь шлях, а не останній компонент. `derived` чи `share/outbox` —
    junction на інший диск, і будь-яка тека під ними фізично лежить там: її
    видалення зносить ціль, хоч сам шлях виглядає своїм.
    """
    try:
        rel = Path(os.path.relpath(_norm(p), _norm(base)))
    except ValueError:
        return str(p)
    if rel.parts and rel.parts[0] == "..":
        return str(p)
    cur = base
    for part in rel.parts:
        cur = cur / part
        if _is_link(cur):
            return str(cur)
    return ""


# ── розміри й видалення ──────────────────────────────────────────────────────

def size_of(p: Path) -> tuple[int, int]:
    """(байти, файли) теки чи файла. Лінки не переходяться й не рахуються."""
    if _is_link(p):
        return 0, 0
    if p.is_file():
        try:
            return p.stat().st_size, 1
        except OSError:
            return 0, 0
    total = n = 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if _is_link(e.path):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            n += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, n


def _newest_mtime(p: Path) -> float:
    """Найсвіжіший mtime теки чи файла з усім вмістом. Дописаний файл не
    оновлює mtime теки-предка, тож дивитись лише на саму теку не можна."""
    try:
        best = os.lstat(p).st_mtime
    except OSError:
        return time.time()
    if _is_link(p) or not p.is_dir():
        return best
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        best = max(best, e.stat(follow_symlinks=False).st_mtime)
                        if e.is_dir(follow_symlinks=False) and not _is_link(e.path):
                            stack.append(Path(e.path))
                    except OSError:
                        return time.time()
        except OSError:
            return time.time()
    return best


def _remove(p: Path) -> None:
    """Видалити теку чи файл; лінк — лише сам лінк, без цілі.

    Свій обхід, а не `shutil.rmtree`: тут видно кожне рішення «заходити чи ні».
    """
    if _is_link(p):
        _unlink_link(p)
        return
    if not p.is_dir():
        if p.exists():
            _unlink_file(p)
        return
    _open_dir(p)
    with os.scandir(p) as it:
        dity = list(it)
    for e in dity:
        child = Path(e.path)
        if _is_link(child):
            _unlink_link(child)
        elif e.is_dir(follow_symlinks=False):
            _remove(child)
        else:
            _unlink_file(child)
    _rmdir(p)


def _open_dir(p: Path) -> None:
    """Тека під видалення — читати, писати й заходити власникові.

    На POSIX вміст видаляють права ТЕКИ (запис і вхід), а не файлу: тека
    `r--` перелічується, але жодного імені з неї не прибрати. На Windows
    `chmod` знімає лише атрибут «тільки читання», і цей крок нешкідливий.
    """
    mode = p.stat().st_mode
    if mode & stat.S_IRWXU != stat.S_IRWXU:
        os.chmod(p, mode | stat.S_IRWXU)


def _unlink_link(p: Path) -> None:
    # `rmdir` знімає junction (точку з'єднання), `unlink` — симлінк; ціль лишається.
    try:
        os.unlink(p)
    except OSError:
        os.rmdir(p)


def _unlink_file(p: Path) -> None:
    try:
        os.unlink(p)
    except PermissionError:
        # Файл лише для читання на Windows — зняти атрибут і ще раз.
        os.chmod(p, stat.S_IWRITE)
        os.unlink(p)


def _rmdir(p: Path) -> None:
    try:
        os.rmdir(p)
    except PermissionError:
        os.chmod(p, stat.S_IWRITE)
        os.rmdir(p)


# ── класи простору ───────────────────────────────────────────────────────────

def _store_file() -> Path:
    from nyshporka.search import store

    return store.path()


def _rebuildable() -> list[Item]:
    """Відтворюване. 🔴 Не тут: `cloud/supervised/runs` (план заходу — єдине, чим
    розібрати осиротілу машину) і `train/tmp` (забір ваг живого трену)."""
    from nyshporka.core.workspace import workspace

    ws = workspace()
    d = ws.derived
    return [
        Item(VIDTVORIUVANE, "стиснуті кадри для хмари", str(d / "cloud" / "frames"),
             "копії оригіналів перед орендою; кропи ріжуться з оригіналів", KHMARA),
        Item(VIDTVORIUVANE, "асети хмарних заходів", str(d / "cloud" / "supervised" / "assets"),
             "наступний захід збирає асети заново", KHMARA),
        Item(VIDTVORIUVANE, "тимчасове хмарних заходів", str(d / "cloud" / "tmp"),
             "архіви засіву й забору, розпаковані в прогони", KHMARA),
        Item(VIDTVORIUVANE, "власні пакети для Супряги", str(ws.share / "outbox"),
             "`share pack` збере їх знову з прочитаного; журнал лишається", OUTBOX),
    ]


def _keep() -> list[Item]:
    from nyshporka.core.workspace import workspace

    ws = workspace()
    return [
        Item(LYSHYTY, "прочитане (декоди й рамки рядків)", str(ws.htr_reports),
             "з нього відтворюється стор тексту й пакуються справи"),
        Item(LYSHYTY, "стор тексту", str(_store_file()),
             "пошук; відтворюється з прочитаного (`nysh text index`), але годинами"),
        Item(LYSHYTY, "журнал обміну", str(ws.share / "journal.jsonl"),
             "походження всього відданого й прийнятого"),
        Item(LYSHYTY, "прийняті пакети", str(ws.share / "inbox"),
             "доказ-файли чужого тексту"),
        Item(LYSHYTY, "сховище сторінок", str(ws.pages), "що переглянуто й що знайдено"),
        Item(LYSHYTY, "канон", str(ws.canonical), "картки осіб і доказ"),
    ]


#: Теки «лишити», які не обходяться заради розміру без прохання: `reports/htr`
#: — мільйони дрібних файлів, і обхід NTFS коштує десятки хвилин.
_DOVHI = {"прочитане (декоди й рамки рядків)"}


def report(*, full: bool = False) -> dict[str, Any]:
    """Звіт про простір: класи, розміри, кандидати на зняття кадрів. Не видаляє."""
    items: list[Item] = []
    for it in _keep() + _rebuildable():
        p = Path(it.path)
        it.exists = p.exists()
        if it.exists and (full or it.label not in _DOVHI):
            it.bytes, it.files = size_of(p)
        items.append(it)
    live = _live_runs()
    return {
        "items": [i.as_json() for i in items],
        "rebuildable_bytes": sum(i.bytes or 0 for i in items if i.klas == VIDTVORIUVANE),
        "offload_candidates": offload_candidates(),
        "live_runs": None if live is None else [s.run_id for s in live],
    }


def _live_runs() -> list[Any] | None:
    """Живі хмарні заходи. `None` — стан не прочитався, і тоді живими
    вважаються всі: закритий при збої, а не відкритий."""
    from nyshporka.cloud import state as ST

    try:
        d = ST.runs_dir()
        files = list(d.glob("*.json")) if d.is_dir() else []
        runs = ST.all_runs()
    except Exception:
        return None
    if len(runs) != len(files):
        return None  # якийсь стан не прочитався — про нього нічого не знаємо
    return [s for s in runs if s.phase not in ("done", "failed") or s.needs_release]


# ── чистка ───────────────────────────────────────────────────────────────────

def clean_plan(*, now: float | None = None) -> Plan:
    """Що прибере `disk clean`: відтворюване, крім того, що зараз у роботі."""
    from nyshporka.core.workspace import workspace

    t = time.time() if now is None else now
    root = workspace().root
    plan = Plan()
    live = _live_runs()
    for it in _rebuildable():
        p = Path(it.path)
        if not p.exists() and not _is_link(p):
            continue
        link = _za_linkom(p, root)
        if link:
            plan.kept.append({"path": it.path, "why": f"на шляху лінк ({link}): тека фізично "
                              f"лежить деінде — не чіпаю"})
            continue
        if it.kind == OUTBOX:
            _outbox(plan, it, p, t)
            continue
        if it.kind == KHMARA and live is None:
            plan.kept.append({"path": it.path, "why": "стан хмарних заходів не прочитався — "
                              "не чіпаю (`nysh cloud status`)"})
            continue
        if it.kind == KHMARA and live:
            ids = ", ".join(s.run_id for s in live[:5])
            plan.kept.append({"path": it.path, "why": f"живі хмарні заходи: {ids} — "
                              f"спершу забрати або закрити (`nysh cloud status`)"})
            continue
        it.bytes, it.files = size_of(p)
        if it.files or _neporozhnia(p):
            plan.remove.append(it)
    return plan


def _neporozhnia(p: Path) -> bool:
    try:
        with os.scandir(p) as it:
            return next(it, None) is not None
    except OSError:
        return False


def _outbox(plan: Plan, it: Item, p: Path, now: float) -> None:
    """Пакети `outbox` — поштучно: свіжий може ще заливатись іншою пачкою.

    Вік теки сегментів — за найсвіжішим файлом усередині, не за самою текою.
    """
    try:
        entries = list(p.iterdir())
    except OSError:
        return
    svizhi = 0
    for e in entries:
        if now - _newest_mtime(e) < OUTBOX_FRESH_SEC:
            svizhi += 1
            continue
        b, n = size_of(e)
        plan.remove.append(Item(VIDTVORIUVANE, e.name, str(e), it.why, OUTBOX, b, n))
    if svizhi:
        plan.kept.append({"path": str(p), "why": f"{svizhi} пакетів свіжіші за годину — "
                          f"можуть ще заливатись"})


def clean(*, apply: bool = False) -> dict[str, Any]:
    plan = clean_plan()
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    if apply:
        for it in plan.remove:
            try:
                _remove(Path(it.path))
                removed.append(it.path)
            except OSError as exc:
                errors.append({"path": it.path, "error": str(exc)})
    return {"applied": apply, "remove": [i.as_json() for i in plan.remove],
            "bytes": plan.bytes, "kept": plan.kept, "removed": removed, "errors": errors}


# ── кадри справи ─────────────────────────────────────────────────────────────

def _read_frames(d: Path, key: str) -> tuple[dict[str, float], list[str]]:
    """Кадри теки `d`, прочитані ВЛАСНИМ прогоном цієї теки й цієї справи:
    `{ім'я: коли прочитано (epoch)}` і імена прогонів.

    🔴 Кожна умова — закрита знахідка рев'ю (18.10.2026):
    * тека — з МЕТИ прогону, не з переліку й не за ключем справи (в одного
      ключа буває кілька тек; знімали непрочитану);
    * ключ справи прогону — той самий, що в теки, з НАЗВАНИМ описом в обох;
      прогін без ключа чи з невідомим описом (`_`) не рахується: стейджинг
      перевикористовують під іншу справу з тими самими іменами `0001…`, а
      «сумісний» невідомий опис пропустив би іншу книгу того ж фонду;
    * сторінка не в `failed`, без `error`, з рядками й часом прочитання:
      сторінка з нулем рядків — темний кадр чи хибна орієнтація, а без часу
      не перевірити, чи кадр не замінили після прочитання.
    """
    from nyshporka import htr_store as S
    from nyshporka.core.casekey import parse

    mine = S.frames_dir_key(str(d))
    kk = parse(key)
    if not mine or kk is None or not kk.opys_known:
        return {}, []
    read: dict[str, float] = {}
    runs: list[str] = []
    for row in S.list_cases():
        if row.get("shared"):
            continue
        meta = S.load_meta(str(row.get("name") or "")) or {}
        if S.frames_dir_key(str(meta.get("case_dir") or "")) != mine:
            continue
        rk = parse(S._canon_case_key(str(meta.get("case_key") or "").strip()))
        if rk is None or not rk.opys_known or rk != kk:
            continue
        failed = {str(x) for x in meta.get("failed") or []}
        got = 0
        for name, info in (meta.get("pages") or {}).items():
            if str(name) in failed or not isinstance(info, dict) or info.get("error"):
                continue
            at = info.get("at")
            if not isinstance(at, (int, float)) or not int(info.get("lines") or 0):
                continue
            read[str(name)] = max(read.get(str(name), 0.0), float(at))
            got += 1
        if got:
            runs.append(str(row.get("name") or ""))
    return read, runs


def _miy_vnesok(case_key: str, n: int) -> str:
    """«» — ваш текст цієї справи є в Супрязі й покриває не менше `n` сторінок;
    інакше причина."""
    from nyshporka.share import pool as P
    from nyshporka.share import suggest as SG

    if P.meta() is None:
        return "зрізу пулу немає — чи віддано, невідомо (`nysh share sync`)"
    if SG._pool_key(case_key) is None:
        return "шифра справи не розібралась для пулу"
    cell = SG._komirka(case_key)
    if cell is None:
        return "у Супрязі цієї справи немає"
    if cell.mine is not True:
        return "у Супрязі немає ВАШОГО тексту цієї справи"
    if int(getattr(cell, "pages", 0) or 0) < n:
        return (f"у Супрязі {getattr(cell, 'pages', 0)} сторінок цієї справи, а знімати — {n}: "
                f"віддайте прочитане (`nysh share push`)")
    return ""


def offload_candidates(limit: int = 20) -> list[dict[str, Any]]:
    """Підказка для звіту: теки справ із вашим текстом у Супрязі. Остаточне
    рішення — у `offload`, покадрово; тут лише «куди дивитись»."""
    from nyshporka import htr_store as S
    from nyshporka.share import pool as P

    if P.meta() is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in S.list_cases():
        key = str(row.get("case_key") or "")
        cd = str(row.get("case_dir") or "")
        if not key or not cd or row.get("shared") or cd in seen:
            continue
        seen.add(cd)
        if not Path(cd).is_absolute() or not Path(cd).is_dir() or _miy_vnesok(key, 0):
            continue
        out.append({"case_key": key, "shifra": row.get("shifra") or "", "dir": cd,
                    "frames": int(row.get("frames") or 0)})
        if len(out) >= limit:
            break
    return out


def _korinni() -> tuple[list[str], list[str]]:
    """(корені, що самі справою не є; межі, всередині яких мусить лежати справа)."""
    from nyshporka.core.workspace import workspace

    ws = workspace()
    roots = [ws.root, ws.data, ws.raw]
    with contextlib.suppress(Exception):
        roots += list(ws.case_roots())
    norm = [_norm(p) for p in roots]
    bounds = [_norm(ws.raw)] + [_norm(p) for p in roots[3:]]
    return norm, bounds


def _vseredyni(p: str, base: str) -> bool:
    try:
        return os.path.commonpath([p, base]) == base and p != base
    except ValueError:
        return False


def _folder(case: str) -> tuple[str, Path]:
    """Тека справи — лише однозначна, абсолютна, справжня й своя.

    🔴 Кожна перевірка — закрита знахідка рев'ю:
    * відносний шлях — від кореня простору, а не від поточної теки: інакше
      прочитане рахувалось по одному простору, а видалялось в іншому;
    * шлях до файла — відмова (людина назвала кадр, а не справу);
    * junction будь-де на шляху (data/raw → архівний диск) — відмова: кадри
      фізично лежать на тій копії, яку людина назвала копією;
    * поза data/raw і оголошеними коренями, корінь, тека з підтеками кадрів
      (архів, плівка з кількома справами) — відмова;
    * без паспорта — відмова: без нього справа зникає з реєстру.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.library import ROOT, load_library
    from nyshporka.pagestore import store

    root = workspace().root
    given = Path(case)
    shliakh = given if given.is_absolute() else root / given
    if shliakh.is_file():
        raise DiskError(f"{case} — файл; назвіть теку справи")
    if shliakh.is_dir():
        d = Path(os.path.abspath(shliakh))
        try:
            key = store.resolve_case(str(d)).key
        except ValueError as exc:
            raise DiskError(f"тека {d} не розібралась як справа: {exc}") from exc
    else:
        try:
            key = store.resolve_case(case).key
        except ValueError as exc:
            raise DiskError(f"справу «{case}» не розібрано: {exc}") from exc
        teky = sorted({str(e.get("path") or "") for e in load_library()
                       if e.get("key") == key and e.get("path")})
        if len(teky) != 1:
            pokaz = "; ".join(teky[:5]) or "жодної"
            raise DiskError(f"{key}: тек кадрів {len(teky)} ({pokaz}) — назвіть теку шляхом")
        d = Path(os.path.abspath(ROOT / teky[0]))
    if not d.is_dir():
        raise DiskError(f"{key}: {d} — не тека кадрів (файл або немає на диску)")
    if _real(d) != _norm(d):
        raise DiskError(f"{key}: тека {d} фізично лежить у {os.path.realpath(d)} (лінк на "
                        f"шляху). Кадри там — це і є копія; тут місця не звільнити")
    roots, bounds = _korinni()
    if _norm(d) in roots:
        raise DiskError(f"{d} — корінь, а не тека справи")
    if not any(_vseredyni(_norm(d), b) for b in bounds):
        raise DiskError(f"{key}: тека {d} поза data/raw і оголошеними коренями справ")
    from nyshporka.cases.walk import READ_EXT

    for sub in d.iterdir():
        if sub.is_dir() and not _is_link(sub) and sub.name != "pages" and any(
                f.suffix.lower() in READ_EXT for f in sub.iterdir() if f.is_file()):
            raise DiskError(f"{key}: у теці {d} є підтека з кадрами ({sub.name}) — це схоже на "
                            f"теку кількох справ; назвіть теку однієї справи")
    pasport = d.parent if d.name == "pages" else d
    if not any((pasport / n).is_file() for n in PASPORTY):
        raise DiskError(f"{key}: у теці {pasport} немає паспорта ({', '.join(PASPORTY)}) — без "
                        f"нього справа після зняття кадрів зникне з реєстру")
    return key, d


def _frames(d: Path) -> list[Path]:
    """Читабельні кадри САМЕ теки `d`, без підтек і лінків. Прогін читав одну
    теку; `pages/` поруч — інша тека зі своїм прогоном, і однакові імена там
    не означають однакових кадрів. TIFF/WebP рушій не читає — це майстри."""
    from nyshporka.cases.walk import READ_EXT

    return [e for e in d.iterdir()
            if e.suffix.lower() in READ_EXT and not _is_link(e) and e.is_file()]


def _u_zhyvomu_zakhodi(d: Path) -> str:
    from nyshporka import htr_store as S

    live = _live_runs()
    if live is None:
        return "стан хмарних заходів не прочитався"
    mine = S.frames_dir_key(str(d))
    for s in live:
        for p in (s.case_dir, s.source_dir):
            if p and S.frames_dir_key(str(p)) == mine:
                return f"справу читає живий захід {s.run_id}"
    return ""


def _marker(d: Path) -> dict[str, Any]:
    f = d / OFFLOAD_MARKER
    if not f.is_file():
        return {}
    try:
        got = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiskError(f"позначка {f} не читається ({exc}) — не перезаписую") from exc
    return got if isinstance(got, dict) else {}


def offload(case: str, *, restore: str, apply: bool = False) -> dict[str, Any]:
    """Зняти з диска прочитані кадри справи, лишивши паспорт і адресу копії.

    Кадр видаляється, лише якщо його ім'я — серед прочитаних сторінок власного
    прогону цієї теки й цієї справи, і файл не змінювався після прочитання.
    Ім'я звіряється й за основою, коли розширення різне (`_za_osnovoiu`).
    Решта лишається й називається у відповіді. Обходу перевірок немає свідомо.
    """
    restore = " ".join(str(restore or "").split())
    if not restore:
        raise DiskError("назвіть, де лежить копія кадрів (--restore «зовнішній диск …»): "
                        "без адреси справу не повернути")
    key, d = _folder(case)
    staryi = _marker(d)
    if staryi.get("restore") and staryi["restore"] != restore:
        raise DiskError(f"{key}: копію цієї теки вже названо — «{staryi['restore']}». Друга "
                        f"адреса загубила б першу; знімайте з тією самою")
    zhyvyi = _u_zhyvomu_zakhodi(d)
    if zhyvyi:
        raise DiskError(f"{key}: кадри не знімаю — {zhyvyi}")
    prochytani, runs = _read_frames(d, key)
    if not runs:
        raise DiskError(f"{key}: жоден власний прогін цієї справи не читав саме теку {d}")
    kadry = _frames(d)
    za_osnovoiu = _za_osnovoiu(prochytani, kadry)
    znyaty: list[Path] = []
    zamineni: list[str] = []
    lyshaiutsia: list[str] = []
    for f in kadry:
        at = prochytani.get(f.name)
        if at is None:
            at = za_osnovoiu.get(f.stem)
        if at is None:
            lyshaiutsia.append(f.name)
        elif _zminenyi(f) > at:
            zamineni.append(f.name)   # кадр замінили (докачали) після прочитання
        else:
            znyaty.append(f)
    if not znyaty:
        if lyshaiutsia and prochytani and not zamineni:
            raise DiskError(
                f"{key}: у теці {d} кадрів {len(kadry)}, прочитаних сторінок "
                f"{len(prochytani)}, але жодне ім'я не зіставилось (тека: "
                f"{sorted(lyshaiutsia)[0]}, прогін: {sorted(prochytani)[0]})")
        raise DiskError(f"{key}: прочитаних кадрів, які можна зняти, у теці {d} немає")
    why = _miy_vnesok(key, len(znyaty))
    if why:
        raise DiskError(f"{key}: кадри не знімаю — {why}")
    total = sum(f.stat().st_size for f in znyaty)
    out: dict[str, Any] = {"case_key": key, "dir": str(d), "frames": len(znyaty),
                           "bytes": total, "restore": restore, "applied": apply,
                           "runs": runs, "unread_kept": sorted(lyshaiutsia)[:50],
                           "unread_kept_n": len(lyshaiutsia),
                           "changed_after_read": sorted(zamineni)[:50], "errors": []}
    if not apply:
        return out
    poperedni = int(staryi.get("frames") or 0)
    marker: dict[str, Any] = {
        "restore": restore, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "frames": poperedni, "bytes": int(staryi.get("bytes") or 0),
        "runs": sorted(set(staryi.get("runs") or []) | set(runs)),
        "by": "nysh disk offload", "in_progress": True}
    # Позначка — ДО видалення (обрив лишає адресу копії), підсумок — ПІСЛЯ:
    # число в ній мусить бути знятим, а не задуманим.
    _write_marker(d, marker)
    znyato = 0
    for f in znyaty:
        try:
            b = f.stat().st_size
            _unlink_file(f)
            znyato += 1
            marker["bytes"] += b
        except OSError as exc:
            out["errors"].append({"path": str(f), "error": str(exc)})
    marker.update(frames=poperedni + znyato, unread_kept=len(lyshaiutsia) + len(zamineni))
    marker.pop("in_progress")
    try:
        _write_marker(d, marker)
    except DiskError as exc:
        # Кадри вже знято; лишилась позначка з адресою копії й `in_progress`.
        out["errors"].append({"path": str(d / OFFLOAD_MARKER), "error": str(exc)})
    out["frames"] = znyato
    return out


def _za_osnovoiu(prochytani: dict[str, float], kadry: list[Path]) -> dict[str, float]:
    """`{основа імені: коли прочитано}` для кадрів, чиє розширення в теці й у
    меті прогону різне: стискання перед хмарою дає `.jpg`, а розпакований ZIP
    лишає `.jpeg` (чи `.png`).

    Лише однозначні основи: дві сторінки прогону чи два кадри теки з однією
    основою (`0001.jpg` і `0001.png`) за основою не зіставляються — котрий
    із двох прочитано, тут не видно. Час зміни кадру `offload` перевіряє
    однаково."""
    po_prohonu: dict[str, list[str]] = {}
    for name in prochytani:
        po_prohonu.setdefault(Path(name).stem, []).append(name)
    po_tetsi: dict[str, int] = {}
    for f in kadry:
        po_tetsi[f.stem] = po_tetsi.get(f.stem, 0) + 1
    return {stem: prochytani[names[0]] for stem, names in po_prohonu.items()
            if len(names) == 1 and po_tetsi.get(stem) == 1}


def _zminenyi(f: Path) -> float:
    """Коли файл кадру востаннє з'явився чи змінився. Не лише mtime: розпаковка
    архіву й `copy2` відновлюють стару дату зміни, а новий файл однаково
    дістає свіжий `st_ctime` — на Windows це час створення, на POSIX час
    зміни метаданих (його оновлює й створення, й відновлення дати). Що
    `st_ctime` на POSIX зсувається ще й від chmod чи перейменування, лише
    лишає кадр на диску — помилка в безпечний бік."""
    st = f.stat()
    return max(st.st_mtime, st.st_ctime,
               float(getattr(st, "st_birthtime", 0.0) or 0.0))


def _write_marker(d: Path, data: dict[str, Any]) -> None:
    f = d / OFFLOAD_MARKER
    part = f.with_name(f.name + ".part")
    try:
        part.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        part.replace(f)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise DiskError(f"позначку {f} не записано ({exc}) — кадри не знімаю") from exc
