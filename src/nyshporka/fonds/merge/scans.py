"""🖼 Скани справи: зведення кількох файлів Commons в один обсяг.

🔴 одна справа — кілька файлів, і два випадки рахуються по-різному. Томи
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

#: 🔴 Маркер тому в назві файлу. Тільки за ним складаємо обсяг кількох файлів
#: однієї справи: його проставляє заливач явно («Частина 2», «Том 3», «Т1»),
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

    Сюди зведено єдине місце, де вирішується, що складати, а що ні: інакше
    правило розповзається між збирачем, консоллю і тестом — і розходиться з ними
    по-різному.

    ⚠ Рядки лишаються `dict`, а не стають dataclass: у `commons_parts` поле
    `sum` рахується як `p in summed`, тобто порівнянням за вмістом. На
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
        # Назва найбільшого файлу, не першого за абеткою: саме вона називає
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


# ── зведення джерел, що описують доступ до справи ────────────────────────────
#: Нижче якої частки найбільшого файлу дзеркало вважається обрізаним.
TRUNCATED_RATIO = 0.6

_RE_LIB_SPR = re.compile(r"^(\d+)\s*([а-яіїєґa-z]?)$", re.IGNORECASE)


def fuse_commons(reg: dict[Any, dict[str, Any]], rows: list[dict[str, str]],
                 unresolved: list[tuple[str, str]]) -> None:
    """Скани Commons: групуємо файли справи й зводимо обсяг.

    🔴 Скан, шифру якого не розібрано, не зникає мовчки: на ф.481 це два витяги,
    залиті без шифри в назві. Тихо викинути їх — те саме, що сказати «сканів
    немає».
    """
    from nyshporka.fonds.merge.text import key_of

    groups: dict[Any, list[dict[str, str]]] = {}
    for row in rows:
        key = key_of(row)
        if not key:
            unresolved.append(("commons", row.get("file", "")))
            continue
        reg.setdefault(key, _blank(key))["src"].add("commons")
        groups.setdefault(key, []).append(row)
    for key, parts in groups.items():
        reg[key].update(aggregate_commons(list(parts)))


def fuse_mirror(reg: dict[Any, dict[str, Any]], rows: list[dict[str, str]],
                unresolved: list[tuple[str, str]]) -> None:
    from nyshporka.fonds.merge.text import key_of

    for row in rows:
        key = key_of(row)
        if not key:
            unresolved.append(("mirror", row.get("file", "")))
            continue
        r = reg.setdefault(key, _blank(key))
        r["src"].add("mirror")
        if not r["mirror_url"]:
            r["mirror_url"] = row.get("url", "")
            r["mirror_size"] = row.get("size", "")


def disk_map(cases: list[dict[str, Any]], fond: str,
             repo: str | None = None) -> dict[Any, str]:
    """Мапа «справа → тека на диску» з бібліотеки.

    🔴 Ключ несе опис: номер справи сам по собі неунікальний між описами
    (спр.7 є і в оп.1, і в оп.2), і мапа по голому номеру приписала б скан
    чужому опису — 18 «наявних» при 11 реальних. І літеру: інакше справа «24»
    позначала б наявною ще й «24а» — окрему книгу, якої на диску немає.
    ⚠ Теки на диску звуться латинкою (`spr-24a`), а шифр в описі кирилицею —
    тому літера зводиться до одного письма.

    🔴 І архів: номери фондів між архівами колізують по-справжньому, не в
    теорії. Ф.904 є в трьох (ДАВіО, ДАОО, і той самий ДАВіО під другим кодом),
    тож одеська справа позначала наявною вінницьку. Звіряти код строго теж не
    можна — десять справ того самого архіву записані другим кодом і випали б;
    зводить їх пак, а не цей модуль.
    """
    from nyshporka.archives import active
    from nyshporka.fonds.merge.text import letter_cyr

    pack = active()
    out: dict[Any, str] = {}
    for c in cases:
        if str(c.get("fond")) != fond:
            continue
        if repo and not pack.same_archive(c.get("repo"), repo):
            continue
        opys = str(c.get("opys") or "1")
        m = _RE_LIB_SPR.match(str(c.get("spr") or ""))
        if not m:
            continue
        out[(opys, m.group(1), letter_cyr(m.group(2).lower()))] = str(c.get("path", ""))
    return out


def mark_disk_and_truncation(reg: dict[Any, dict[str, Any]],
                             on_disk: dict[Any, str]) -> None:
    """Обрізане дзеркало й наявність на диску.

    🔴 Обрізаність міряється проти найбільшого файлу, а не проти суми частин:
    дзеркало віддає справу одним файлом, тож у багатотомної справи сума завжди
    більша в рази — і кожен такий рядок хибно ставав би «обрізаним».
    """
    for r in reg.values():
        cs = r.get("commons_size_max") or r.get("commons_size") or ""
        ms = r.get("mirror_size") or ""
        r["truncated_mirror"] = ""
        if (str(cs).isdigit() and str(ms).isdigit() and int(cs) > 0
                and int(ms) < int(cs) * TRUNCATED_RATIO):
            r["truncated_mirror"] = "1"
        r["on_disk"] = on_disk.get((r["opys"], r["spr_int"], r["spr_letter"]), "")


def _blank(key: Any) -> dict[str, Any]:
    from nyshporka.fonds.merge.sources import blank_row

    return blank_row(key)
