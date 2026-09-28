"""🔢 Наступний вільний ID для нової картки канону.

🔴 ID не вгадують. Агент, що рахує «останній, здається, був такий-то», рано
чи пізно видає ID, який уже зайнятий, і `write` мовчки перетирає чужу картку:
на канон, де сотні осіб, це не помітно до першого розриву в дереві.

Береться максимум + 1, а дірки не займаються: ID, що зник, міг лишитися
посиланням у нотатках, звітах чи чужих копіях, і нова особа під ним
підхопила б чужі згадки.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from nyshporka import ids as ID

Kind = Literal["person", "family", "place"]

#: Тип → (тека канону, префікс, формувач ID).
_KINDS = {
    "person": ("persons", "I", ID.person_id),
    "family": ("families", "F", ID.family_id),
    "place": ("places", "PL", ID.place_id),
}


def new_id(canonical: Path, kind: Kind) -> str:
    folder, prefix, make = _KINDS[kind]
    pattern = re.compile(rf"^{prefix}(\d+)$")
    top = 0
    d = canonical / folder
    if d.is_dir():
        for p in d.glob("*.md"):
            m = pattern.match(p.stem)
            if m:
                top = max(top, int(m.group(1)))
    return make(top + 1)
