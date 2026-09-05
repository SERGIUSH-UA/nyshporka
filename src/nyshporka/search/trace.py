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
import os
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
    try:
        got = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def note(key: str, *, q: str, thresh: int, hits: int, pages: int,
         models: list[str], channels: list[str]) -> None:
    """Записати, чим саме прочісували цю справу. Без ключа — не пишемо нічого."""
    if not key:
        return
    row = {"q": q, "thresh": thresh, "hits": hits, "pages": pages,
           "models": sorted(set(models)), "channels": channels,
           "when": date.today().isoformat()}
    data = _read()
    prev = [x for x in (data.get(key) or []) if isinstance(x, dict)]
    # Той самий запит тими самими моделями не множить рядків — він їх оновлює.
    same = (q, tuple(sorted(set(models))))
    prev = [x for x in prev
            if (x.get("q"), tuple(x.get("models") or [])) != same]
    data[key] = [row, *prev][:KEEP]
    p = path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8", newline="\n")
        tmp.replace(p)
    except OSError:
        pass  # слід — зручність, а не умова роботи


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
