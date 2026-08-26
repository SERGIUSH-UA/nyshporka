"""📈 Журнал спостережень — як дослідження росло в часі.

**Навіщо.** Реєстр справ, канон і прогони відповідають на питання «скільки в
мене зараз». Питання «а скільки було в червні» не відповідає ніхто: усі похідні
бази перезбираються цілком, і кожна перезбірка стирає попередній стан. Пульс
(`core.pulse`) знає лише, що *щось* змінилось, і має рівно одну комірку пам'яті.

Тут — плаский журнал зрізів. Один рядок JSON на рядок файла:

    {"at": "2026-08-26T14:44:53", "by": "cases.build", "src": "live",
     "cases": 1, "frames": 3, "htr_pages": 3, "canon_facts": 0, ...}

🔴 **Журнал записує спостереження, а не кожну зміну.** Дірка в графіку означає
«ніхто не дивився й нічого не перезбирав», а не «нічого не відбувалось». Та
сама межа, що в `core.pulse`, і назвати її треба так само вголос: лінія тут має
право сказати «виросло тоді-то», але ніколи — «раніше не росло».

Причина такої межі не в ліні. Порахувати зріз означає сходити в реєстр справ,
у канон і в перелік прогонів; вішати це на кожну мутацію значило б платити за
графік там, де на нього ніхто не дивиться. Тому пишуть двоє:

* `cases.db.rebuild()` — після перезбірки реєстру (числа вже в руках);
* операція дашборда — щоразу, коли на головну заходять.

Обидва пишуть безумовно, а відсіює однакове сам `record()` — за числами.
Звірятися натомість із пульсом було б дешевше, але неправильно: пульс б'є й на
операціях, які жодного з цих лічильників не міняють (справу перейменували,
вердикт зняли), тобто ставив би точку там, де на кривій нічого не зрушило.

**Чому JSONL, а не таблиця в SQLite.** Усі бази в `data/derived` — похідні й
перезбираються з нуля. Журнал єдиний, чого відтворити неможливо: минуле не
перечитується з диска. Окремий файл, який ніхто не має права знести під час
перезбірки, — це і є та відмінність, виражена розкладкою.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

#: Ім'я файла в `data/derived`. Без крапки на початку — на відміну від пульсу
#: це не службовий стан, а дані дослідження, які людина має право відкрити.
HISTORY_NAME = "history.jsonl"

#: Лічильники, що складають зріз. Порядок — для читабельності файла очима.
#: 🔴 Рядки порівнюються тільки за цими ключами: `at`/`by`/`src` міняються
#: щоразу, і якби вони входили в порівняння, дедуп не спрацював би жодного разу.
FIELDS = (
    "cases", "frames", "ordered",
    "htr_pages", "htr_none", "runs",
    "canon_persons", "canon_facts", "canon_sources",
    "pages_noted", "hits_open", "no_fuzzy",
)

#: Скільки рядків тримати максимум. Далеко над реальним ужитком: при щоденному
#: спостереженні це 13 років, а стеля тут — запобіжник від циклу, що збожеволів.
MAX_LINES = 5000

#: Понад стільки днів лишається по одному рядку на добу.
DENSE_DAYS = 90


def history_path() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / HISTORY_NAME


def _counts_of(row: dict[str, Any]) -> tuple[Any, ...]:
    """Зріз як кортеж — для порівняння сусідніх рядків."""
    return tuple(row.get(k) for k in FIELDS)


def read(path: Path | None = None) -> list[dict[str, Any]]:
    """Журнал рядками, найстаріші спершу.

    🔴 Битий рядок пропускається, а не валить читання. Файл дописується
    конкурентно — консоль, командний рядок і агентська сесія пишуть у нього
    незалежно, — тож обірваний рядок на хвості це очікуваний стан, а не поламка.
    Панель, яка гасне цілком через півтори тисячі байтів на кінці файла,
    втрачає всю історію заради одного зіпсованого дня.
    """
    p = path or _safe_path()
    if p is None:
        return []
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("at"):
            out.append(row)
    out.sort(key=lambda r: str(r.get("at") or ""))
    return out


def _safe_path() -> Path | None:
    try:
        return history_path()
    except Exception:
        return None


def record(counts: dict[str, Any], *, by: str, src: str = "live",
           at: str = "") -> bool:
    """Дописати зріз. Повертає, чи справді дописали.

    🔴 Рядок пишеться лише якщо числа відрізняються від останнього. Інакше файл
    ріс би на кожне відкриття головної сторінки, а графік перетворився б на
    щільну пряму з тисячі однакових точок — тобто коштував би дорожче й
    показував би менше.

    Невдача запису не є помилкою виклику, як і в пульсу: журнал — надбудова,
    і застосунок мусить працювати без нього. Але тоді він мовчить, а не показує хибне:
    точки просто не з'являється.
    """
    p = _safe_path()
    if p is None:
        return False
    row: dict[str, Any] = {
        "at": at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "by": str(by),
        "src": src,
    }
    for k in FIELDS:
        v = counts.get(k)
        if v is not None:
            row[k] = v
    prev = read(p)
    if prev and _counts_of(prev[-1]) == _counts_of(row):
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return False
    if len(prev) + 1 > MAX_LINES:
        compact(p)
    return True


def compact(path: Path | None = None) -> int:
    """Проріділи старе: понад `DENSE_DAYS` — по одному рядку на добу.

    Повертає, скільки рядків лишилось. Прорідження бере останній рядок доби, а
    не перший: зріз доби — це те, чим вона закінчилась.
    """
    p = path or _safe_path()
    if p is None:
        return 0
    rows = read(p)
    if not rows:
        return 0
    cutoff = time.strftime("%Y-%m-%d",
                           time.localtime(time.time() - DENSE_DAYS * 86400))
    by_day: dict[str, dict[str, Any]] = {}
    keep: list[dict[str, Any]] = []
    for r in rows:
        day = str(r.get("at") or "")[:10]
        if day >= cutoff:
            keep.append(r)
        else:
            by_day[day] = r          # останній у добі витісняє попередній
    merged = sorted([*by_day.values(), *keep], key=lambda r: str(r.get("at")))
    if len(merged) > MAX_LINES:
        merged = merged[-MAX_LINES:]
    if len(merged) == len(rows):
        return len(rows)
    _rewrite(p, merged)
    return len(merged)


def _rewrite(path: Path, rows: list[dict[str, Any]]) -> None:
    """Переписати журнал цілком — через тимчасовий файл і `replace`.

    Прямий перезапис лишав би читача з половиною журналу рівно в той момент,
    коли інша вкладка малює графік.
    """
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


# ── бекфіл ───────────────────────────────────────────────────────────────────
def backfill(*, limit_days: int = 730) -> dict[str, Any]:
    """Відновити рідкі точки за минуле з міток, які вже лежать на диску.

    Без цього графік починався б у день, коли модуль з'явився, — тобто нове
    вміння показувало б порожнечу саме тому, що воно нове.

    🔴 Рядки бекфілу мають `src="backfill"` і малюються пунктиром. Вони
    реконструйовані: мітка каже, коли файл востаннє чіпали, а не коли число
    стало таким. Видати їх за виміряні означало б збрехати рівно тим графіком,
    який заводимо заради довіри.

    Бекфіл не чіпає наявних рядків і не пише поверх живих спостережень: він
    дозаписує лише ті дні, яких у журналі ще немає.
    """
    have = {str(r.get("at") or "")[:10] for r in read()}
    days: dict[str, dict[str, Any]] = {}

    def bump(day: str, key: str, value: int) -> None:
        if not day or len(day) < 10:
            return
        slot = days.setdefault(day, {})
        slot[key] = max(int(slot.get(key) or 0), int(value))

    for day, pages, runs in _runs_timeline():
        bump(day, "htr_pages", pages)
        bump(day, "runs", runs)
    for day, noted in _eye_timeline():
        bump(day, "pages_noted", noted)
    for day, persons in _canon_timeline():
        bump(day, "canon_persons", persons)

    # ⚠ Вікно затискається: `time.localtime()` на від'ємній мітці кидає
    # `OSError` на Windows, тож надто щедре число тут валило б бекфіл замість
    # того, щоб просто взяти все.
    back = min(max(int(limit_days), 0), 36_500) * 86400
    cutoff = time.strftime("%Y-%m-%d", time.localtime(max(time.time() - back, 0)))
    # 🔴 Один прохід і один запис, а не `record()` на кожну добу: той щоразу
    # перечитує весь журнал, тож двісті днів бекфілу коштували б двохсот
    # читань файла. Дедуп тут не потрібен — ми й так пишемо лише ті дні, яких
    # у журналі ще немає.
    fresh: list[dict[str, Any]] = []
    for day in sorted(days):
        if day < cutoff or day in have:
            continue
        # Опівдні, а не опівночі: точка означає «десь у цей день», і полудень
        # не вдає, ніби ми знаємо годину.
        row: dict[str, Any] = {"at": f"{day}T12:00:00", "by": "backfill",
                               "src": "backfill"}
        row.update({k: v for k, v in days[day].items() if k in FIELDS})
        fresh.append(row)
    if fresh:
        _merge_in(fresh)
    return {"days": len(days), "written": len(fresh),
            "from": min(days) if days else "", "to": max(days) if days else ""}


def _merge_in(rows: list[dict[str, Any]]) -> None:
    """Вставити рядки в журнал, зберігши хронологію.

    Бекфіл дає старі дати, тож простим дописуванням у хвіст файл перестав би
    бути відсортованим — а `read()` сортує щоразу, тобто ціна безладу лягла б
    на кожне читання. Дешевше впорядкувати один раз тут.
    """
    p = _safe_path()
    if p is None:
        return
    merged = sorted([*read(p), *rows], key=lambda r: str(r.get("at") or ""))
    if len(merged) > MAX_LINES:
        merged = merged[-MAX_LINES:]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    _rewrite(p, merged)


def _runs_timeline() -> list[tuple[str, int, int]]:
    """(день, накопичено сторінок, накопичено прогонів) — із мет прогонів.

    🔴 Сторінки накопичуються так само, як їх рахує `htr_store.unique_pages`:
    по кожній справі береться найповніший прогін, а не сума всіх. Два голоси
    (Писар кирилицю, Скриба латинку) проходять ті самі аркуші, тож сума дала б
    рівно подвійне «прочитано» на кожній справі, гнаній обома, — і крива росту
    показувала б роботу, якої не було.

    ⚠ Групи ведуться інкрементально, а не перерахунком `unique_pages()` на
    кожному кроці: тисяча прогонів у просторі — звичайна річ, і квадрат від неї
    перетворив би бекфіл на секунди очікування рівно там, де він разовий.
    """
    try:
        from nyshporka import htr_store

        rows = htr_store.list_cases()
    except Exception:
        return []
    dated = sorted(
        (r for r in rows if str(r.get("updated") or "")),
        key=lambda r: str(r.get("updated")))
    groups: dict[str, int] = {}
    total = 0
    out: list[tuple[str, int, int]] = []
    for i, r in enumerate(dated, start=1):
        key = (r.get("case_key") or "").strip()
        if not key:
            case_dir = (r.get("case_dir") or "").strip()
            key = f"dir:{case_dir}" if case_dir else f"run:{r.get('name')}"
        pages = int(r.get("pages_done") or 0)
        was = groups.get(key, 0)
        if pages > was:
            groups[key] = pages
            total += pages - was
        out.append((str(r.get("updated"))[:10], total, i))
    return out


def _eye_timeline() -> list[tuple[str, int]]:
    """(день, накопичено занесених аркушів) — із дат у самих замітках.

    🔴 Дата береться з поля `noted` замітки, а не з `mtime` файла: файл
    переписується цілком на кожне занесення, тож його час зміни каже лише про
    останній дотик до справи, а не про день, коли аркуш дивились оком.
    """
    try:
        from nyshporka.core.workspace import workspace

        pages_dir = workspace().pages
    except Exception:
        return []
    if not pages_dir.is_dir():
        return []
    per_day: dict[str, int] = {}
    for path in sorted(pages_dir.glob("*/*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for note in (raw.get("pages") or {}).values():
            if not isinstance(note, dict):
                continue
            day = str(note.get("noted") or "")[:10]
            if len(day) == 10:
                per_day[day] = per_day.get(day, 0) + 1
    total = 0
    out: list[tuple[str, int]] = []
    for day in sorted(per_day):
        total += per_day[day]
        out.append((day, total))
    return out


def _canon_timeline() -> list[tuple[str, int]]:
    """(день, карток осіб у каноні) — із git-історії `data/canonical/persons`.

    🔴 Джерело необов'язкове. Простір Нишпорки не зобов'язаний бути
    репозиторієм, а тека канону — відстежуватись. Немає git, немає теки,
    команда впала чи затяглась — повертається порожньо, і графік лишається без
    цієї кривої. Падати тут означало б зробити git залежністю застосунку, який
    ставлять подвійним кліком.

    🔴 Рахуються картки осіб (один файл на особу), і лягають вони саме в
    `canon_persons`. Фактів у комітах не видно — вони всередині файлів, — а
    підставити число осіб під підпис «фактів» означало б назвати одну величину
    іменем іншої там, де обидві є на тому самому графіку.
    """
    import subprocess

    try:
        from nyshporka.core.workspace import workspace

        ws = workspace()
    except Exception:
        return []
    if not (ws.root / ".git").exists() or not ws.canonical.is_dir():
        return []
    try:
        res = subprocess.run(
            ["git", "-C", str(ws.root), "log", "--reverse",
             "--format=%cI", "--name-status", "--", "data/canonical/persons"],
            capture_output=True, text=True, timeout=20, check=False,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    alive: set[str] = set()
    out: list[tuple[str, int]] = []
    day = ""
    for line in res.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line[:1].isdigit() and "T" in line[:20]:
            if day:
                out.append((day, len(alive)))
            day = line[:10]
            continue
        parts = line.split("\t")
        status, paths = parts[0][:1], parts[1:]
        if not paths:
            continue
        if status == "D":
            alive.discard(paths[-1])
        else:
            # ⚠ Перейменування (`R100 стара нова`) веде два шляхи. Забувши
            # стару назву, ми лишили б у наборі привида, і кожна нормалізація
            # імен файлів канону виглядала б як приплив нових осіб.
            if status == "R" and len(paths) > 1:
                alive.discard(paths[0])
            alive.add(paths[-1])
    if day:
        out.append((day, len(alive)))
    # Один рядок на добу — останній стан доби.
    per_day: dict[str, int] = {}
    for d, n in out:
        per_day[d] = n
    return sorted(per_day.items())
