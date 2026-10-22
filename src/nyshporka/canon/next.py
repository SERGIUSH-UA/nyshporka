"""🧭 Що людині вирішити першим: ранжування відкритих гіпотез.

Список не ведуть руками, його рахують із карток гіпотез. Зведення в нотатках
застаріває за тиждень (було: таблиця «що відкрите», за два місяці вісім рядків
із неї вже були закриті), а картку, що бреше, ловить `canon check`.

Порядок:
1. `awaiting` вище за `open`: там уже є на що дивитись.
2. Сильний хіт вище за слабкий.
3. Вага: скільки фактів канону чекає на цю гіпотезу, плюс скільки осіб і
   родин вона зачіпає. Гіпотеза, від якої залежить гілка, стоїть вище за
   побічну.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.canon.check import Canon, _facts, load


@dataclass
class Decision:
    id: str
    claim: str
    status: str
    decides: str
    weight: int
    facts: list[str] = field(default_factory=list)
    hits: list[dict[str, Any]] = field(default_factory=list)
    versus: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "claim": self.claim, "status": self.status,
                "decides": self.decides, "weight": self.weight, "facts": self.facts,
                "hits": self.hits, "versus": self.versus}


def _crop_cmd(case: str, scan: str, line: int | None) -> str:
    if line is None:
        return ""
    return f'nysh text crop "{case}" {scan} {line}'


def rank(canon: Canon, *, closed: bool = False) -> list[Decision]:
    """Відкриті за порядком рішення; `closed` — закриті теж, у кінці за ID."""
    linked: dict[str, list[str]] = {}
    for owner, f in _facts(canon):
        if f.hypothesis:
            linked.setdefault(f.hypothesis, []).append(f"{owner}:{f.type}")
    out: list[Decision] = []
    for hid, h in canon.hypotheses.items():
        if h.status == "closed" and not closed:
            continue
        hits = sorted(h.hits, key=lambda x: (x.strength != "strong", not x.eye))
        out.append(Decision(
            id=hid, claim=h.claim, status=h.status, decides=h.decides,
            weight=len(linked.get(hid, [])) + len(h.about),
            facts=linked.get(hid, []), versus=list(h.versus),
            hits=[{"case": x.case, "scan": x.scan, "line": x.line, "reading": x.reading,
                   "strength": x.strength, "eye": x.eye,
                   "crop": _crop_cmd(x.case, x.scan, x.line)} for x in hits]))
    out.sort(key=lambda d: (
        d.status == "closed",
        d.status != "awaiting",
        not any(x["strength"] == "strong" for x in d.hits),
        -d.weight,
        d.id,
    ))
    return out


def next_decisions(root: Path, limit: int = 3, *, canon: Canon | None = None) -> dict[str, Any]:
    """`canon` — уже прочитаний (консоль бере його з `canon.memo`)."""
    canon = canon if canon is not None else load(root)
    ranked = rank(canon)
    return {
        "open": sum(1 for h in canon.hypotheses.values() if h.status == "open"),
        "awaiting": sum(1 for h in canon.hypotheses.values() if h.status == "awaiting"),
        "closed": sum(1 for h in canon.hypotheses.values() if h.status == "closed"),
        "next": [d.as_dict() for d in ranked[:max(limit, 0)]],
    }
