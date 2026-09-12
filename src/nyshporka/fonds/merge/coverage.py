"""📐 Покриття фонду: скільки справ знайдено проти того, скільки їх існує.

🔴 Без знаменника покриття не рахується взагалі, і це не обережність. Друкувати
«0/0 · немає 0» гірше, ніж не друкувати нічого: нулі читаються як «усе на
місці», тоді як насправді межі опису просто невідомі. Порожній результат тут
мусить звучати як прогалина.
"""
from __future__ import annotations

from typing import Any

from nyshporka.archives.pack import OpysBound


def classify(rows: list[dict[str, Any]], bounds: dict[str, OpysBound],
             guide_total: int | None = None) -> dict[str, Any]:
    """Тризначна класифікація кожного номера в межах опису.

    Три стани, і всі три потрібні окремо:
      · **present** — номер має рядок без літери, тобто саму справу;
      · **letter_family** — номер має рядок із літерою («24а»): книга існує, але
        це інша одиниця, і рахувати її замість основної не можна;
      · **absent** — номера немає ні там, ні там.

    ⚠ Номер може бути одночасно present і letter_family (справа 24 і 24а) — тоді
    він рахується в обох, і в absent не потрапляє.

    🔴 Рядок-група («29-35») покриває всі свої номери. Без цього опис, що пише
    справи групами, виглядав би дірявим рівно там, де він повний: ІР НБУВ ф.6
    записує так сотні справ, і всі вони пішли б у «відсутні».
    """
    out: dict[str, Any] = {}
    for opys, bound in bounds.items():
        present: set[int] = set()
        for r in rows:
            if r["opys"] != opys or r["spr_letter"]:
                continue
            n = int(r["spr_int"])
            present.add(n)
            to = str(r.get("spr_to") or "")
            # ⚠ Група обрізається межею опису: кінець, що виходить за неї, —
            # помилка набору, і без обрізання «присутніх» стало б більше за
            # номери опису, а 100% сховали б справжні пропуски.
            if to.isdigit() and int(to) > n:
                present.update(range(n + 1, min(int(to), bound.last) + 1))
        letters: dict[int, list[str]] = {}
        for r in rows:
            if r["opys"] == opys and r["spr_letter"]:
                letters.setdefault(int(r["spr_int"]), []).append(r["spr_letter"])
        absent = [n for n in range(1, bound.last + 1)
                  if n not in present and n not in letters]
        out[opys] = {
            "last_number": bound.last,
            "present": len(present),
            "letter_families": len(letters),
            "letter_rows": sum(len(v) for v in letters.values()),
            "absent": len(absent),
            "absent_sample": absent[:20],
        }

    tot_last = sum(v["last_number"] for v in out.values())
    tot_absent = sum(v["absent"] for v in out.values())
    tot_letters = sum(v["letter_rows"] for v in out.values())
    out["_total"] = {
        "sum_last_number": tot_last,
        "present": sum(v["present"] for v in out.values()),
        "letter_rows": tot_letters,
        "absent": tot_absent,
        # Розрахунок одиниць зберігання: усе в межах, мінус відсутнє, плюс
        # літерні книги — вони існують понад нумерацію.
        "computed_units": tot_last - tot_absent + tot_letters,
        "guide_total": guide_total,
    }
    return out
