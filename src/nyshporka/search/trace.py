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

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

FILE = "search_log.json"
#: Скільки останніх свіпів тримаємо на справу. Один — замало: свіп прізвищем і
#: свіп іменами відповідають на різні питання, і затирати перший другим означає
#: втратити половину відповіді.
KEEP = 5


def path() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().derived / FILE


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
    row = {"q": q, "thresh": thresh, "hits": hits, "pages": pages,
           "models": sorted(set(models)), "channels": channels,
           "when": date.today().isoformat()}
    from nyshporka.pagestore.store import _lock
    from nyshporka.utils.atomic import write_json

    p = path()
    # Лок на все «прочитати → дописати → замінити» (аудит 29.09.2026): два
    # паралельні свіпи інакше читали той самий стан, і другий затирав запис
    # першого. Лок — той самий, що береже сховище сторінок.
    try:
        with _lock(p):
            data = _read_for_write(p)
            if data is None:
                return
            prev = [x for x in (data.get(key) or []) if isinstance(x, dict)]
            # Той самий запит тими самими моделями не множить рядків — він їх
            # оновлює. Канали — частина ключа: свіп прізвищем і свіп з якорями
            # відповідають на різні питання, і другий не має затирати перший.
            same = (q, tuple(sorted(set(models))), tuple(channels))
            prev = [x for x in prev
                    if (x.get("q"), tuple(x.get("models") or []),
                        tuple(x.get("channels") or [])) != same]
            data[key] = [row, *prev][:KEEP]
            write_json(p, data, indent=1, newline="\n")
    except OSError:
        pass  # слід — зручність, а не умова роботи (сюди ж — зайнятий лок)


def of(key: str) -> list[dict[str, Any]]:
    """Чим цю справу вже шукали, від найсвіжішого."""
    got = _read().get(key) or []
    return [x for x in got if isinstance(x, dict)]


def stale(key: str, models: list[str]) -> list[dict[str, Any]]:
    """Записи, зроблені ІНШИМИ моделями, ніж ті, що в справі зараз.

    🔴 Саме вони найнебезпечніші: виглядають як зроблена робота, а зроблені
    гіршим рушієм. Показувати їх треба окремо від свіжих, а не в одному списку.
    """
    now = set(models)
    return [x for x in of(key) if set(x.get("models") or []) != now]
