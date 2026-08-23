"""🖼 Скани справи: зведення кількох файлів Commons в один обсяг.

🔴 ОДНА СПРАВА — КІЛЬКА ФАЙЛІВ, і два випадки рахуються по-різному. Томи
(«Частина 1..3», «Т1/Т2») складаються: спр.7864 це 1217+1313+1242 = 3772 стор.
А витяг однієї парафії чи повторна заливка — ні: вони показують ті самі аркуші
вдруге (спр.7345: витяг села на 30 стор. лежить біля тому на 3291; спр.6694
сумою дав би 534 замість 524).

Сумувати наосліп означає замінити обсяг справи вигаданим числом — і воно
виглядатиме правдоподібно.
"""
from __future__ import annotations

import json
import re
from typing import Any

#: 🔴 Маркер ТОМУ в назві файлу. Тільки за ним складаємо обсяг кількох файлів
#: однієї справи: його проставляє заливач ЯВНО («Частина 2», «Том 3», «Т1»),
#: тоді як витяг парафії чи повторна заливка маркера не мають — і їхні сторінки
#: не додаються до справи, а повторюють уже полічені.
_RE_VOLUME = re.compile(r"(?:частина|частин[аи]|том|part|ч)[\s._]*\d+|[\s._]Т\d+\b",
                        re.IGNORECASE)


def is_volume(name: str) -> bool:
    """Чи несе назва файлу явний маркер тому."""
    return bool(_RE_VOLUME.search(name or ""))


def _int(v: Any) -> int:
    return int(v) if str(v).isdigit() else 0


def aggregate_commons(parts: list[dict[str, Any]]) -> dict[str, str]:
    """Кілька файлів однієї справи → обсяг справи + її склад.

    Сюди зведено ЄДИНЕ місце, де вирішується, що складати, а що ні: інакше
    правило розповзається між збирачем, консоллю і тестом — і розходиться з ними
    по-різному.

    ⚠ Рядки лишаються `dict`, а не стають dataclass: у `commons_parts` поле
    `sum` рахується як `p in summed`, тобто порівнянням ЗА ВМІСТОМ. На
    dataclass семантика інша, і склад тому змінився б мовчки.
    """
    parts = sorted(parts, key=lambda p: -_int(p.get("size")))
    vols = [p for p in parts if is_volume(str(p.get("file", "")))]
    # Один марковий том серед немаркованих сумою не вважається: маркер має сенс
    # лише тоді, коли їх кілька.
    summed = vols if len(vols) > 1 else parts[:1]
    biggest = parts[0]
    return {
        "commons_url": str(biggest.get("url", "")),
        # Назва НАЙБІЛЬШОГО файлу, не першого за абеткою: саме вона називає
        # справу, а витяг парафії назвав би її селом витягу.
        "commons_title": str(biggest.get("file", "")),
        "commons_files": str(len(parts)),
        "commons_size_max": str(_int(biggest.get("size")) or ""),
        "commons_kind": ("volumes" if len(vols) > 1
                         else ("variants" if len(parts) > 1 else "")),
        "commons_size": str(sum(_int(p.get("size")) for p in summed) or ""),
        "commons_pages": str(sum(_int(p.get("pagecount")) for p in summed) or ""),
        "commons_parts": (json.dumps(
            [{"file": p.get("file", ""), "size": _int(p.get("size")),
              "pages": _int(p.get("pagecount")), "url": p.get("url", ""),
              "sum": p in summed} for p in parts], ensure_ascii=False)
            if len(parts) > 1 else ""),
    }
