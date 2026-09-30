"""Збірна тека: кадри кількох справ під одним іменем.

Тека `RGIA_592_25_926_929` несе справи 926–929, а розбір шифри брав з неї
перше число: текст чотирьох книг лягав у каталог і в пул під шифрою однієї.
Тут — лише розпізнавання; ключів воно не міняє й меж справ не вгадує.

Два рівні певності, і вони не змішуються:

* **названо** — діапазон стоїть у шифрі паспорта («RGIA 592-25-926-929»).
  Це слова людини чи джерела про теку, тож на них можна відмовляти;
* **схоже** — діапазон видно лише в імені теки чи прогону. 🔴 Замір на живому
  просторі: чотири числа поспіль мають 563 імені прогонів, і майже всі —
  не діапазон («621-1-14_1868» — рік, «anrm_211_11_27_2233036» — номер
  плівки). Тому ім'я читається лише у вузькій формі `<архів>_ф_оп_спр_спр`, і
  знімає його паспорт із `one_case`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nyshporka import library as L

#: Ширший «діапазон» справ в одній теці — уже не діапазон, а збіг чисел
#: (рік, номер плівки, кадр).
SPAN_MAX = 99

#: Поле паспорта: людина сказала, що тека — одна справа, хоч ім'я схоже на діапазон.
ONE_CASE = "one_case"
#: Поле паспорта: остання справа діапазону, названого в шифрі.
SPR_TO = "spr_to"

_DECLARED_RE = re.compile(
    rf"(?<![\w-]){L.FOND_TOKEN}\s*[-–]\s*\d+\s*[-–]\s*(\d+)\s*[-–_]\s*(\d+)(?![\w-])",
    re.IGNORECASE)
_NAME_RE = re.compile(r"^[^\W\d_]+_\d+_\d+_(\d+)_(\d+)$")


@dataclass(frozen=True)
class Span:
    """Діапазон справ у теці."""

    spr_from: int
    spr_to: int
    declared: bool      # названо в шифрі паспорта; False — лише схоже з імені
    source: str         # рядок, у якому його видно

    @property
    def label(self) -> str:
        return f"{self.spr_from}–{self.spr_to}"

    @property
    def count(self) -> int:
        return self.spr_to - self.spr_from + 1

    @property
    def why(self) -> str:
        if self.declared:
            return (f"шифра «{self.source}» називає справи {self.label} — у теці "
                    f"кадри {self.count} справ, а не однієї")
        return (f"ім'я «{self.source}» схоже на діапазон справ {self.label} — "
                f"у теці, ймовірно, кадри {self.count} справ")

    def as_json(self) -> dict[str, Any]:
        return {"from": self.spr_from, "to": self.spr_to,
                "declared": self.declared, "source": self.source}


def _span(a: str, b: str, *, declared: bool, source: str) -> Span | None:
    lo, hi = int(a), int(b)
    if not lo < hi <= lo + SPAN_MAX:
        return None
    return Span(lo, hi, declared, source)


def in_shifra(text: str) -> Span | None:
    """Діапазон, названий у шифрі: «592-25-926-929», «592-25-926–929», «…926_929»."""
    raw = (text or "").strip()
    m = _DECLARED_RE.search(raw)
    return _span(m.group(1), m.group(2), declared=True, source=raw) if m else None


def in_name(name: str) -> Span | None:
    """Діапазон, схожий з імені теки чи прогону: лише `<архів>_ф_оп_спр_спр`."""
    leaf = Path(str(name or "").replace("\\", "/")).name
    m = _NAME_RE.match(leaf)
    return _span(m.group(1), m.group(2), declared=False, source=leaf) if m else None


def of_passport(meta: dict[str, Any], *names: str) -> Span | None:
    """Діапазон теки за її паспортом і іменами, під якими вона ходить."""
    if meta.get("split_into"):
        return None             # уже розкладено на справи
    got = in_shifra(str(meta.get("shifra") or ""))
    if got is not None:
        return got
    # `nysh case --shifra "…926-929"` зводить шифру до першої справи, а хвіст
    # діапазону кладе окремим полем: інакше він губився б у мить запису.
    if str(meta.get(SPR_TO) or "").isdigit() and str(meta.get("spr") or "").isdigit():
        got = _span(str(meta["spr"]), str(meta[SPR_TO]), declared=True,
                    source=f"{meta.get('shifra') or ''}–{meta[SPR_TO]}")
        if got is not None:
            return got
    if meta.get(ONE_CASE):
        return None
    for name in names:
        got = in_name(name)
        if got is not None:
            return got
    return None


def of_dir(case_dir: Path, *names: str) -> Span | None:
    """Діапазон теки на диску; `names` — ще імена, під якими вона ходить (прогони)."""
    from nyshporka.cases.chain import sidecar_of

    d = Path(case_dir)
    _, meta = sidecar_of(d)
    # ARCHIUM кладе кадри в `pages/`: ім'я справи несе батько.
    return of_passport(meta, d.name, d.parent.name if d.name == "pages" else "", *names)


def fix(path: str) -> str:
    """Що робити зі збірною текою."""
    return (f'розкласти на справи: nysh cases split "{path}" --dry-run '
            f'--part "<справа>=<перший файл>..<останній файл>" …; '
            f'якщо це одна справа: nysh case "{path}" --one-case')
