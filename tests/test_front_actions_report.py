"""Кожна дія консолі, що пише, каже людині, чим скінчилось: тост, помилка, робота чи вікно.

Доти частина дій (черга, зупинка хмари, вердикт, профіль Супряги) мовчала після
успіху, і кнопка виглядала такою, що нічого не робить (прохід провтиків 22.10.2026).
"""
from __future__ import annotations

import re

from _front import FRONT_DIR

from nyshporka import ops as O

#: Чим дія може відповісти людині: тост, помилка в блоці, картка роботи, вікно,
#: перемальовка, власний помічник екрана, що сам кличе тост (`queueAfter`).
TOLD = re.compile(r"toast\(|boxError\(|watchHere\(|onJob\(|jobChip\(|failure\(|renderWarnings\("
                  r"|innerHTML|confirmAct|openModal|setView\(|queueAfter\(")


def _handlers() -> list[tuple[str, str, str]]:
    out = []
    for f in sorted((FRONT_DIR / "screens").glob("*.js")) + sorted((FRONT_DIR / "core").glob("*.js")):
        s = f.read_text(encoding="utf-8")
        # Тіло обробника — від його ключа до наступного ключа того самого рівня:
        # однорядковий обробник інакше «склеювався» з наступним і ховав його.
        keys = list(re.finditer(r"\n  '([a-z0-9.\-]+)': (?:async )?\([^)]*\) =>", s))
        for i, m in enumerate(keys):
            end = keys[i + 1].start() if i + 1 < len(keys) else len(s)
            out.append((f.name, m.group(1), s[m.end():end]))
    return out


def test_every_writing_action_reports_its_outcome() -> None:
    silent = []
    for fname, name, body in _handlers():
        for op in re.findall(r"callOp\('([a-z0-9._]+)'", body):
            o = O.get(op)
            if o is not None and o.mutates and not TOLD.search(body):
                silent.append(f"{fname}: {name} → {op}")
    assert not silent, f"дія пише й мовчить: {silent}"


def test_the_check_sees_the_actions() -> None:
    """Сам розбір не порожній: інакше зелений тест нічого б не доводив."""
    names = {n for _, n, _ in _handlers()}
    assert {"queue.start", "give.go", "hist.save"} <= names and len(names) > 80
