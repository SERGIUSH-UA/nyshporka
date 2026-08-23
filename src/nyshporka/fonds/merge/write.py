"""💾 Запис реєстру, черги розбіжностей і покриття.

⚠ Три речі тут визначають БАЙТИ файлів, і жодна не видна з логіки:
закінчення рядка, спосіб чистки клітинки й порядок колонок. Тест логіки їх не
побачить, а читач файлу — одразу.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from nyshporka.fonds.merge.sources import COLUMNS
from nyshporka.fonds.merge.text import opys_sort

CONFLICT_COLUMNS = ("opys", "spr", "field", "value_a", "src_a", "value_b",
                    "src_b", "score", "verdict", "note")
UNRESOLVED_COLUMNS = ("source", "file", "opys", "spr", "why")

_RE_CELL = re.compile(r"[\t\r\n]+")


def cell(value: Any) -> str:
    """Клітинка TSV: рве лише те, що ламає формат.

    🔴 Не спільна `flat()` зі збирачів: та схлопує БУДЬ-ЯКІ пробільні пробіги,
    а тут подвійні пробіли всередині заголовка лишаються — вони прийшли з опису
    й належать текстові. Різниця вилізе рівно на тих заголовках, де вона є.
    """
    return _RE_CELL.sub(" ", str(value))


def write_merged(path: Path, reg: dict[Any, dict[str, Any]]) -> int:
    """Реєстр фонду. Повертає кількість рядків."""
    rows = sorted(reg.values(),
                  key=lambda r: (opys_sort(r["opys"]), int(r["spr_int"]),
                                 r["spr_letter"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
        wr.writerow(COLUMNS)
        for r in rows:
            out = dict(r)
            out["sources"] = ",".join(sorted(r["src"]))
            out["title_alt"] = "; ".join(r["title_alt"])
            out["surnames"] = "; ".join(r["surnames"])
            wr.writerow([cell(out.get(c, "")) for c in COLUMNS])
    return len(rows)


def carry_verdicts(path: Path, conflicts: list[dict[str, str]]) -> int:
    """Перенести рішення людини в щойно зібрану чергу. Повертає, скільки.

    🔴 Черга будується з нуля щоразу, тож без цього все, що дослідник вписав у
    вердикт, зникало б із наступним прогоном — і та сама розбіжність поверталась
    би нерозібраною, скільки б разів її не закривали.

    Ключ навмисно ГРУБИЙ (опис, справа, поле): формулювання джерел міняється від
    скрейпу до скрейпу, а рішення стосується справи, а не рядка тексту.

    ⚠ Нотатка БЕЗ вердикту не переноситься. Вона буває й наша власна,
    авто-згенерована; перенести її означало б «зберегти рішення», якого не було.
    """
    if not path.is_file():
        return 0
    old: dict[tuple[str, str, str], tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            v = (row.get("verdict") or "").strip()
            if v:
                old[(row.get("opys", ""), row.get("spr", ""),
                     row.get("field", ""))] = (v, (row.get("note") or "").strip())
    kept = 0
    for c in conflicts:
        hit = old.get((c["opys"], c["spr"], c["field"]))
        if hit and not c["verdict"]:
            c["verdict"], c["note"] = hit
            kept += 1
    return kept


def write_conflicts(path: Path, conflicts: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
        wr.writerow(CONFLICT_COLUMNS)
        for c in conflicts:
            wr.writerow([cell(c.get(k, "")) for k in CONFLICT_COLUMNS])


def write_coverage(path: Path, coverage: dict[str, Any]) -> None:
    """Покриття фонду. 🔴 Кінці рядків задано ЯВНО.

    Без цього `write_text` перекладає перенос у `os.linesep`: на Windows
    покриття виходить із CRLF, а реєстр поруч — із LF. Наслідок не
    косметичний: у сховищі, що нормалізує кінці рядків, файл ставав
    «зміненим» після КОЖНОЇ перезбірки, хоч жодне число в ньому не
    рухалось, — і справжня зміна покриття тонула в цьому шумі.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _has_human_input(path: Path) -> bool:
    """Чи вписала людина в бланк хоч одну шифру."""
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return any((r.get("opys") or r.get("spr") or "").strip()
                       for r in csv.DictReader(fh, delimiter="	"))
    except OSError:
        return True          # прочитати не вдалось — не чіпати


def write_unresolved(path: Path, unresolved: list[tuple[str, str]]) -> bool:
    """Скани, шифру яких не розібрано. Повертає, чи файл записано.

    🔴 Порожні колонки тут навмисні: це БЛАНК для ручного заповнення. Шифру не
    вгадувати — вгадана вона виглядає як прочитана.
    """
    if not unresolved:
        # 🔴 Порожній перелік означає, що всі скани розібрались, — а файл із
        # минулої збірки лишався на місці й свідчив протилежне: черга ручного
        # розбору виглядала непорожньою тоді, коли розбирати вже нічого.
        # ⚠ Але прибирати можна лише БЛАНК: це файл для заповнення руками, і
        # вписана людиною шифра — єдина копія тієї роботи.
        if path.is_file() and not _has_human_input(path):
            path.unlink()
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
        wr.writerow(UNRESOLVED_COLUMNS)
        for source, name in unresolved:
            wr.writerow([source, name, "", "", ""])
    return True
