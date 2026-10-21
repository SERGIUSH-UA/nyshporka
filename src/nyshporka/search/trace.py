"""🧾 Слід останнього свіпу: чим справу вже шукали й коли.

🔴 Навіщо. Пошук нічого про себе не пам'ятав, тож питання «цю справу вже
прочісували?» не мало відповіді — і наступна сесія починала з нуля або, гірше,
вважала прочісаним те, чого не чіпала.

🔴 **Ключ запису включає МОДЕЛІ прогонів.** Правило куплене заміром приватного
конвеєра: «обшукано» протухає мовчки, коли бойова модель обганяє ту, якою
шукали — та сама справа тим самим запитом дала +8 аркушів роду від самої лише
зміни моделі. Запис без моделі підтверджував би роботу, якої вже немає.

⚠ Живе в `derived/`, а не в сховищі прочитаного, і це рішення. Сховище
сторінок — те, що бачило ОКО; воно переживає перечитування й переїзди. Слід
свіпу відтворюється повторним запитом і нічого не доводить, тож класти його
поруч із доказами означало б змішати два різні за вагою роди записів.
Той самий шар уже тримає індекс декоду, який пошук так само пише сам.
"""
from __future__ import annotations

import contextlib
import json
import sys
import time
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import Any

FILE = "search_log.json"
#: Скільки останніх свіпів тримаємо на справу. Один — замало: свіп прізвищем і
#: свіп іменами відповідають на різні питання, і затирати перший другим означає
#: втратити половину відповіді.
KEEP = 5


#: Слід на один захід — див. `batch`.
_BATCH: ContextVar[dict[str, Any] | None] = ContextVar("trace_batch", default=None)


@contextlib.contextmanager
def batch() -> Iterator[None]:
    """Один захід — одне читання сліду й один запис наприкінці.

    🔴 Пошук по серії пише слід кожної справи окремо, і кожен запис
    перечитував і переписував увесь файл, а показ ще тричі читав його на
    справу: на 20 справах ф.224 — 5,3 с із 29 (замір 19.10.2026), на фонді
    з 1900 справ — квадрат від розміру файла. Тут файл читається раз, записи
    одразу видно в `of` цього ж заходу, а на диск вони лягають однією
    порцією під тим самим локом, поверх свіжого стану (чужі записи за цей час
    не губляться).
    """
    if _BATCH.get() is not None:
        yield
        return
    st: dict[str, Any] = {"data": None, "pending": []}
    tok = _BATCH.set(st)
    try:
        yield
    finally:
        _BATCH.reset(tok)
        if st["pending"]:
            _flush(st["pending"])


def _batch_data(st: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] | None = st["data"]
    if data is None:
        data = st["data"] = _read()
    return data


def _apply(data: dict[str, Any], key: str, row: dict[str, Any]) -> None:
    """Дописати рядок сліду справи: той самий запит тими самими моделями й
    каналами рядків не множить, а оновлює їх."""
    prev = [x for x in (data.get(key) or []) if isinstance(x, dict)]
    # Канали — частина ключа: свіп прізвищем і свіп з якорями відповідають на
    # різні питання, і другий не має затирати перший.
    same = (row["q"], tuple(row["models"]), tuple(row["channels"]))
    prev = [x for x in prev
            if (x.get("q"), tuple(x.get("models") or []),
                tuple(x.get("channels") or [])) != same]
    data[key] = [row, *prev][:KEEP]


def _flush(pending: list[tuple[str, dict[str, Any]]]) -> None:
    from nyshporka.pagestore.store import _lock

    p = path()
    try:
        with _lock(p):
            data = _read_for_write(p)
            if data is None:
                return
            for key, row in pending:
                _apply(data, key, row)
            _write(p, data)
    except OSError:
        pass  # слід — зручність, а не умова роботи (сюди ж — зайнятий лок)


def _write(p: Path, data: dict[str, Any]) -> None:
    """Слід — без відступу: з `indent` модуль `json` пише пітонячим енкодером,
    і файл на 2,8 МБ коштував 1,1 с на КОЖЕН пошук (замір 21.10.2026). Слід
    читає машина; людині його показує `nysh text whatis`."""
    from nyshporka.utils.atomic import write_json

    write_json(p, data, indent=None, newline="\n")


def path() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().project_derived / FILE


def _read() -> dict[str, Any]:
    """Для ПОКАЗУ: побитий чи зайнятий файл — порожньо, пошук не падає.

    ⚠ Писати поверх цього не можна: див. `_read_for_write`.
    """
    try:
        got = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _read_for_write(p: Path) -> dict[str, Any] | None:
    """Прочитати слід під запис. `None` — цього разу не писати.

    🔴 Аудит 29.09.2026: `note` читав через `_read`, а той на будь-якій помилці
    віддавав `{}` — і запис одного свіпу перезаписував слід УСІХ справ. Досить
    було антивіруса, що тримав файл у мить читання (PermissionError на Windows).
    Тому розводимо два випадки:

    * файл не ЧИТАЄТЬСЯ (зайнятий, немає прав) — він, найпевніше, цілий, тож
      пропускаємо запис: слід — зручність, а втратити всі інші гірше, ніж
      недописати один;
    * файл читається, але не РОЗБИРАЄТЬСЯ — відновлювати нема з чого. Відсуваємо
      його вбік `.corrupt-<час>` (руками ще можна дістати рядки) і починаємо
      заново, сказавши про це вголос.
    """
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        got = read_json(p, default={})
    except CorruptFileError as e:
        if isinstance(e.__cause__, OSError):
            print(f"⚠ слід свіпу не записано: {e.__cause__}", file=sys.stderr)
            return None
        aside = p.with_name(f"{p.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            p.replace(aside)
        except OSError as exc:
            print(f"⚠ слід свіпу побитий і не відсувається ({exc}); не записано",
                  file=sys.stderr)
            return None
        print(f"⚠ слід свіпу {p} не розбирався — відсунуто в {aside.name}, "
              f"починаю новий", file=sys.stderr)
        return {}
    if not isinstance(got, dict):
        aside = p.with_name(f"{p.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            p.replace(aside)
        except OSError:
            return None
        print(f"⚠ слід свіпу {p} — не об'єкт; відсунуто в {aside.name}",
              file=sys.stderr)
        return {}
    return got


def note(key: str, *, q: str, thresh: int, hits: int, pages: int,
         models: list[str], channels: list[str]) -> None:
    """Записати, чим саме прочісували цю справу. Без ключа — не пишемо нічого."""
    if not key:
        return
    from nyshporka.core import legacy_key

    # Один ключ на справу: старий рядок з пам'яті агента — та сама справа.
    key = legacy_key.current_key(key) or key
    row = {"q": q, "thresh": thresh, "hits": hits, "pages": pages,
           "models": sorted(set(models)), "channels": list(channels),
           "when": date.today().isoformat()}
    st = _BATCH.get()
    if st is not None:
        _apply(_batch_data(st), key, row)
        st["pending"].append((key, row))
        return
    from nyshporka.pagestore.store import _lock

    p = path()
    # Лок на все «прочитати → дописати → замінити» (аудит 29.09.2026): два
    # паралельні свіпи інакше читали той самий стан, і другий затирав запис
    # першого. Лок — той самий, що береже сховище сторінок.
    try:
        with _lock(p):
            data = _read_for_write(p)
            if data is None:
                return
            _apply(data, key, row)
            _write(p, data)
    except OSError:
        pass  # слід — зручність, а не умова роботи (сюди ж — зайнятий лок)


def searched() -> dict[str, str]:
    """Усі справи, які цей проєкт уже шукав: ключ → дата останнього свіпу."""
    from nyshporka.core import legacy_key

    out: dict[str, str] = {}
    for key, rows in _read().items():
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        k = legacy_key.current_key(key) or key
        when = str(rows[0].get("when") or "")
        out[k] = max(out.get(k, ""), when)
    return out


def of(key: str) -> list[dict[str, Any]]:
    """Чим цю справу вже шукали, від найсвіжішого."""
    from nyshporka.core import legacy_key

    st = _BATCH.get()
    got = legacy_key.get(_batch_data(st) if st is not None else _read(), key) or []
    return [dict(x) for x in got if isinstance(x, dict)]


def stale(key: str, models: list[str]) -> list[dict[str, Any]]:
    """Записи, зроблені ІНШИМИ моделями, ніж ті, що в справі зараз.

    🔴 Саме вони найнебезпечніші: виглядають як зроблена робота, а зроблені
    гіршим рушієм. Показувати їх треба окремо від свіжих, а не в одному списку.
    """
    now = set(models)
    return [x for x in of(key) if set(x.get("models") or []) != now]
