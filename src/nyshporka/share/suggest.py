"""📋 Що прочитано, але ще не віддано.

У режимі `pytaty` після прогону не питається НІЧОГО. Замість цього клієнт
веде список і раз на тиждень друкує один рядок: «7 прочитаних справ ще не в
Супрязі — `nysh share suggest`». Команда показує перелік і віддає все одним
підтвердженням.

Чому дайджест, а не питання після кожного прогону: питання дратує на третій
раз, а на п'ятий його клацають не читаючи. Дайджест іще й ефективніший —
людина віддає пачкою, коли сама до цього готова.

🔴 Відмова запам'ятовується ПОШТУЧНО. Сказав «цю не віддам» — більше про неї
не питають ніколи. Без цього список щотижня показував би те саме, і людина
перестала б його читати — тобто механізм зламався б тихо, лишаючись
формально справним.

🔴 Рахунок суто локальний. `PRIVACY.md` обіцяє, що фонової активності в
мережі немає, і ця обіцянка дорожча за зручність: у пул `suggest` іде лише
на явну дію людини.
"""
from __future__ import annotations

import time
from typing import Any

from nyshporka.share import journal

#: Подія журналу: «цю справу віддавати не буду».
DECLINED = "decline"

#: Ключ у стані користувача: коли востаннє показували рядок-нагадування.
#: 🔴 У стані, а не в просторі: «коли я бачив підказку» — факт про цю
#: машину, а простір їздить між машинами.
STATE_NUDGED = "share_nudged"

#: Як часто нагадувати. Тиждень — не менше: рядок, який зʼявляється щодня,
#: перестають читати, і тоді він не працює й тоді, коли справді потрібен.
NUDGE_DAYS = 7

#: Скільки неподіленого треба, щоб нагадати раніше строку.
NUDGE_THRESHOLD = 10


def _kliuch(row: dict[str, Any]) -> str:
    """Чим ототожнюємо справу в журналі.

    Той самий порядок, що в `journal.stats`: шифра, потім локальний ключ.
    Розійтись вони не можуть, бо обидва беруться з одного маніфесту.
    """
    return str(row.get("shifra") or row.get("case_key") or "")


def vidmovleni() -> set[str]:
    """Справи, про які більше не питають."""
    return {_kliuch(e) for e in journal.read(DECLINED) if _kliuch(e)}


def viddani() -> set[str]:
    """Справи, які вже пакували."""
    return {_kliuch(e) for e in journal.read(journal.PACKED) if _kliuch(e)}


def vidmovyty(case_key: str, shifra: str = "", why: str = "") -> dict[str, Any]:
    """Запамʼятати відмову.

    🔴 `why` не косметика: рішення людини сильніше за будь-який автомат, і
    через півроку має бути видно, на чому воно стояло. Те саме правило, що
    в `cases.resolve.bind_run` — прив'язка без підстави є вигадкою.
    """
    return journal.record(DECLINED, case_key=case_key, shifra=shifra,
                          why=why or "без пояснення")


def nepodileni() -> list[dict[str, Any]]:
    """Прочитане своїми руками, чого ще немає в Супрязі.

    Три відсіви, і кожен має причину:

    * **без `case_key`** — прогін нічий: шифри немає, пакувати нема чого;
    * **`shared`** — чужий прогін, прийнятий від когось. Перепаковувати
      чуже не можна: людина віддала його один раз, і другий раз за неї
      ніхто не вирішує;
    * **без сторінок** — прогін, який нічого не прочитав.
    """
    from nyshporka import htr_store as S

    vzhe = viddani() | vidmovleni()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in S.list_cases():
        key = str(row.get("case_key") or "")
        if not key or row.get("shared") or not row.get("pages_done"):
            continue
        shifra = str(row.get("shifra") or "")
        if key in vzhe or shifra in vzhe or key in seen:
            continue
        seen.add(key)
        out.append({
            "case_key": key,
            "shifra": shifra,
            "title": row.get("title") or "",
            "pages": int(row.get("pages_done") or 0),
            "frames": int(row.get("frames") or 0),
            "model": row.get("model") or "",
            "updated": row.get("updated") or "",
        })
    out.sort(key=lambda r: str(r["updated"]), reverse=True)
    return out


def _days_since_nudge() -> int | None:
    """Скільки днів тому нагадували; `None` — не нагадували жодного разу.

    🔴 Третій стан обовʼязковий, і це той самий висновок, що в
    `setup/update.days_since_check`: «не нагадували» і «нагадували, все
    віддано» — різні відповіді, і звести їх в одну означає показати спокій
    там, де його ніхто не перевіряв.
    """
    from nyshporka.core.workspace import state_all

    got = state_all().get(STATE_NUDGED)
    try:
        when = float(got)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, int((time.time() - when) / 86400))


def mark_nudged() -> None:
    from nyshporka.core.workspace import state_set

    state_set(**{STATE_NUDGED: time.time()})


def nudge() -> str:
    """Рядок-нагадування або порожньо.

    Викликається перед командами й мусить бути дешевим і мовчазним: усе, що
    він робить, — читає журнал і перелік прогонів із кеша. У мережу не
    ходить ніколи.
    """
    from nyshporka.share.profile import PYTATY, load

    if load().consent != PYTATY:
        return ""

    days = _days_since_nudge()
    try:
        skilky = len(nepodileni())
    except Exception:
        # Нагадування — зручність, а не умова роботи. Якщо перелік прогонів
        # не прочитався, команда людини має виконатись однаково.
        return ""
    if not skilky:
        return ""
    # Нагадуємо за строком або коли назбиралось помітно багато — щоб
    # людина, яка читає щодня, не чекала тижня.
    if days is not None and days < NUDGE_DAYS and skilky < NUDGE_THRESHOLD:
        return ""

    mark_nudged()
    slovo = "справа" if skilky == 1 else ("справи" if 2 <= skilky <= 4 else "справ")
    return (f"{skilky} прочитаних {slovo} ще не в Супрязі — "
            f"подивитись: nysh share suggest")
