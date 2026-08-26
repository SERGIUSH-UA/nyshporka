"""📄 Спільна робота з файлами `registry/*.tsv`.

Формат навмисно найпростіший: плаский TSV із шапкою. Його читає злиття реєстру,
і саме тому набір колонок кожного збирача — зобов'язання, а не деталь.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

#: Номер справи з літерою: «24а», «8534т».
#: 🔴 Літера пишеться злито з номером, і негативний lookahead тут не прикраса:
#: без нього «230-1-2640 Дзічковських» читається як справа «2640д» — фантом,
#: якого в описі немає, тоді як справжня справа лишається «без скана».
_CODE = re.compile(r"^(\d+)\s*([а-яіїєґa-z]?)(?![а-яіїєґa-z])", re.IGNORECASE)

#: Хвіст заголовка: «, 1786-1794, 51 арк.» — це поля, а не назва.
_TAIL = re.compile(r",\s*(\d{4})(?:\s*[-–]\s*(\d{4}))?\s*(?:рр?\.?)?"
                   r"(?:,\s*(\d+)\s*арк\.?)?\s*$")


def flat(s: str) -> str:
    """Один рядок без табуляцій — інакше TSV розпадеться посеред файла."""
    return " ".join((s or "").split())


#: Як переглядач архіву підписує номер: «Справа 12», «Спр. 12а», «№ 12».
_NUM_PREFIX = re.compile(r"^\s*(?:справа|спр\.?|№)\s*", re.IGNORECASE)


def case_number(raw: str) -> tuple[int, str] | None:
    """Номер справи з того, як його підписав сайт.

    🔴 Окремо від `split_code`, який лишається строгим: «Справа 1» — це формат
    конкретного переглядача, а не властивість номера. Заміряно на ЦДІАК ф.224:
    без зняття префікса збирач узяв 1525 рядків і не визнав ні одного справою.
    За числом отриманих рядків це виглядало б успіхом — і саме тому приймачем
    збирання є `quality`, а не їхня кількість.
    """
    return split_code(_NUM_PREFIX.sub("", raw or ""))


def split_code(code: str) -> tuple[int, str] | None:
    """«24а» → (24, "а"). `None` — це не номер справи."""
    m = _CODE.match((code or "").strip())
    if not m:
        return None
    return int(m.group(1)), (m.group(2) or "").lower()


def parse_title_tail(title: str) -> tuple[str, str, str, str]:
    """Заголовок → (назва, рік від, рік до, аркуші).

    ⚠ Роки й аркуші приходять хвостом того самого рядка, і лишити їх у назві
    означає, що фільтр за роками не побачить нічого, а сам заголовок у списку
    щоразу обривається на півслові.
    """
    t = flat(title)
    m = _TAIL.search(t)
    if not m:
        return t, "", "", ""
    name = t[:m.start()].rstrip(" ,;")
    y1, y2, folios = m.group(1) or "", m.group(2) or "", m.group(3) or ""
    return name, y1, (y2 or y1), folios


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Шапка й рядки. Немає файла — порожньо, це не помилка."""
    if not path.is_file():
        return [], []
    with path.open(encoding="utf-8", newline="") as fh:
        r = csv.DictReader(fh, delimiter="\t")
        return list(r.fieldnames or []), [dict(row) for row in r]


def write_tsv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Записати цілком, атомарно.

    Через `.part`: обірваний запис під правильним іменем наступний запуск
    прочитає як повний реєстр — і мовчки недорахує половину фонду.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields), delimiter="\t",
                           extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: flat(str(row.get(k, ""))) for k in fields})
    tmp.replace(path)


def sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    """Опис, номер, літера. ⚠ Опис буває нечисловий («Л2», «ОРП41»)."""
    try:
        num = int(str(row.get("spr_int") or 0))
    except (TypeError, ValueError):
        num = 0
    return (str(row.get("opys") or ""), num, str(row.get("spr_letter") or ""))


def merge_into(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]],
               *, touched: tuple[str, ...]) -> int:
    """Влити рядки, зберігши описи, яких цей запуск не чіпав.

    🔴 Без цього збирання одного опису знищує решту файла. Заміряно на живому
    фонді: запуск із `--opys 1` лишив у реєстрі один опис замість сімдесяти
    п'яти, і виглядало це як успішна робота — файл на місці, рядки в ньому є.

    Повертає, скільки чужих рядків збережено.
    """
    _, old = read_tsv(path)
    keep = [r for r in old if str(r.get("opys") or "") not in set(touched)]
    write_tsv(path, fields, sorted([*keep, *rows], key=sort_key))
    return len(keep)
