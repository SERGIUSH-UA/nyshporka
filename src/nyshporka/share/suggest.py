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


#: Частка прочитаних сторінок від кадрів, з якої справа «готова» до
#: віддачі без `--partial` — той самий поріг, що у воротах знаменника
#: здебільшого перевищують із запасом.
GOTOVA_CHASTKA = 0.8

#: Статуси рядка переліку — у порядку, в якому їх варто віддавати.
GOTOVA = "готова"
BEZ_RAMOK = "у пулі без рамок"
NEPOVNA = "неповна"
BEZ_KADRIV = "без кадрів"
STATUSY = (GOTOVA, BEZ_RAMOK, NEPOVNA, BEZ_KADRIV)
#: Що можна віддати без `--partial` і без ручної роботи.
READY_STATUSES = (GOTOVA, BEZ_RAMOK)


def _u_puli(case_key: str) -> str | None:
    """Стан справи в зрізі пулу: `none | text | text+geom`; `None` — зрізу немає.

    🔴 Зріз — єдина правда про «опубліковано». Журнал знає лише «пакували»,
    а спакований пакет міг і не доїхати: так 22.09 десять справ стояли
    «відданими», хоч геометрія їхня в пул не пішла.
    """
    from nyshporka.share import pool

    if pool.meta() is None:
        return None
    try:
        from nyshporka.pagestore import resolve_case

        ref = resolve_case(case_key)
    except Exception:
        return "none"
    for repo in _synonimy(ref.repo):
        cell = pool.by_key(pool.quad_key(repo, ref.fond, ref.opys or "", ref.spr))
        if cell is not None and cell.mine is not False:
            return pool.state_of(cell)
    return "none"


def _synonimy(repo: str) -> list[str]:
    """Код архіву й усі коди того самого архіву (`same_as` в обидва боки).

    🔴 Пул пише Вінницький архів каноном пакета `DAVIO`, а дослідницький
    простір може лишатись на давньому `DAVO`. Без цього справа, що давно в
    пулі, показувалась «готовою» до віддачі.
    """
    out = [repo]
    try:
        from nyshporka.archives import active

        repos = active().repositories
    except Exception:
        return out
    same = getattr(repos.get(repo), "same_as", "") or ""
    for code, r in repos.items():
        if code != repo and (getattr(r, "same_as", "") == repo or code == same):
            out.append(code)
    return out


def _ye_ramky(run_name: str) -> bool:
    """Чи лежать рамки рядків у теці прогону. Один `glob` до першого збігу."""
    from nyshporka.core.workspace import workspace
    from nyshporka.share.bundle import PACKED_GEOMETRY

    if not run_name:
        return False
    d = workspace().htr_reports / run_name
    return d.is_dir() and next(d.glob(PACKED_GEOMETRY), None) is not None


def _status(pages: int, frames: int) -> str:
    if not frames:
        return BEZ_KADRIV
    return GOTOVA if pages >= GOTOVA_CHASTKA * frames else NEPOVNA


def nepodileni() -> list[dict[str, Any]]:
    """Прочитане своїми руками, чого ще немає в Супрязі.

    Три відсіви, і кожен має причину:

    * **без `case_key`** — прогін нічий: шифри немає, пакувати нема чого;
    * **`shared`** — чужий прогін, прийнятий від когось. Перепаковувати
      чуже не можна: людина віддала його один раз, і другий раз за неї
      ніхто не вирішує;
    * **без сторінок** — прогін, який нічого не прочитав.

    Що вже віддано, вирішує зріз пулу (`nysh share sync`), коли він є; без
    нього — журнал пакувань, і рядок `pool` тоді `None`: «не питали».
    """
    from nyshporka import htr_store as S
    from nyshporka.share import pool

    zriz = pool.meta() is not None
    vzhe = vidmovleni() | (set() if zriz else viddani())
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    vsi = S.list_cases()
    # Голоси однієї справи — окремі прогони, і рамки бувають не в кожному.
    progony: dict[str, list[str]] = {}
    for row in vsi:
        progony.setdefault(str(row.get("case_key") or ""), []).append(str(row.get("name") or ""))
    for row in vsi:
        key = str(row.get("case_key") or "")
        if not key or row.get("shared") or not row.get("pages_done"):
            continue
        shifra = str(row.get("shifra") or "")
        if key in vzhe or shifra in vzhe or key in seen:
            continue
        seen.add(key)
        stan = _u_puli(key) if zriz else None
        if stan == "text+geom":
            continue
        if stan == "text" and not any(_ye_ramky(n) for n in progony.get(key, [])):
            # Текст у пулі, а рамок на диску немає (старі прогони без
            # рамок) — довозити нічого, і рядок висів би тут вічно.
            continue
        pages = int(row.get("pages_done") or 0)
        frames = int(row.get("frames") or 0)
        out.append({
            "case_key": key,
            "shifra": shifra,
            "title": row.get("title") or "",
            "pages": pages,
            "frames": frames,
            "model": row.get("model") or "",
            "updated": row.get("updated") or "",
            "pool": stan,
            "status": BEZ_RAMOK if stan == "text" else _status(pages, frames),
        })
    out.sort(key=lambda r: str(r["updated"]), reverse=True)
    out.sort(key=lambda r: STATUSY.index(r["status"]))
    return out


def pidsumok(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Скільки чого в переліку — по статусах, у порядку `STATUSY`."""
    return {s: sum(1 for r in rows if r["status"] == s) for s in STATUSY}


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
