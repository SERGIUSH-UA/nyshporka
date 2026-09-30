"""Що саме охопив пошук: який простір, яка тека прогонів, які корені справ.

Знаменник пошуку каже «прочесано N прогонів» — і не каже, ЗВІДКИ ці N.
Прогони беруться з однієї теки одного простору; тека зі сканами поза коренями
справ, справа, якої ще не читали, корінь на від'єднаному диску — усе це поза
пошуком і в знаменник не входить. Відповідь «не знайшлось» при цьому виглядає
так само, як якби прочесали все.

🔴 Привід — звіт користувача 29.09.2026: теки поза зареєстрованими коренями у
відбір не входили, і жодне число в відповіді цього не казало.

Рахується дешево й раз на виклик: два числа з реєстру справ одним запитом,
перелік коренів із простору. Диск не обходиться.
"""
from __future__ import annotations

from typing import Any


def reach(runs: int) -> dict[str, Any]:
    """Блок «охоплено» для відповіді пошуку по всьому простору.

    `runs` — скільки прогонів лежить у теці прогонів (той самий перелік, з
    якого пошук бере область). `cases` і `cases_unread` — `None`, коли реєстру
    справ немає: «не знаємо» і «нуль» тут різні відповіді.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError:
        return {}
    declared = [ws.raw, *ws.extra_case_roots]
    out: dict[str, Any] = {
        "workspace": str(ws.root),
        "runs_root": str(ws.htr_reports),
        "runs": int(runs),
        "case_roots": [str(p) for p in declared if p.is_dir()],
        "roots_gone": [str(p) for p in ws.extra_case_roots if not p.is_dir()],
        "cases": None,
        "cases_unread": None,
    }
    try:
        from nyshporka.cases import db as CDB

        got = CDB.read_counts()
    except (FileNotFoundError, OSError):
        return out
    out["cases"], out["cases_unread"] = got["cases"], got["unread"]
    return out


def line(r: dict[str, Any]) -> str:
    """Один рядок для людини. Порожньо — простору немає, казати нічого."""
    if not r:
        return ""
    parts = [f"простір {r['workspace']}", f"прогонів у ньому {r['runs']}"]
    if r.get("cases") is not None:
        unread = int(r.get("cases_unread") or 0)
        parts.append(f"справ у реєстрі {r['cases']}"
                     + (f", із них без жодного прогону {unread}" if unread else ""))
    else:
        parts.append("реєстру справ немає — скільки справ не читано, невідомо")
    roots = r.get("case_roots") or []
    if len(roots) > 1:
        parts.append(f"коренів справ {len(roots)}")
    text = "охоплено: " + " · ".join(parts)
    gone = r.get("roots_gone") or []
    if gone:
        text += f" · недосяжні корені: {', '.join(gone)}"
    return text + " · поза цим пошук не дивився"
