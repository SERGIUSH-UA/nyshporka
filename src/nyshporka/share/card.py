"""🏷 Картка справи для пулу: назва, роки, місця й жанр, задані людиною чи агентом.

Картку в пулі пакувальник складає сам — з паспорта теки, реєстру опису й
бібліотеки (`share/opys.py`). Цього не завжди досить: паспорт тримає робочу
назву, реєстр — OCR опису, а безіменна справа не має назви зовсім. Тоді її
пише той, хто заливає, — прапорцями `nysh share pack --title …` або наперед
командою `nysh share card <справа> --title …`.

🔴 Задане ЗАПАМ'ЯТОВУЄТЬСЯ, а не діє на одне пакування. Справу пакують
знову й знову — автовіддача після прогону, `suggest --all`, перепакування
після дочитування новою моделлю, — і назва, виправлена руками один раз,
інакше мовчки поверталась би до робочої нотатки паспорта при кожному
наступному пакуванні.

🔴 Лежить у `data/share/cards.json`, поруч із журналом обміну, а не в
паспорті теки. Паспорт — робочий файл дослідження, і писати в нього з
пакувальника означало б змішати опис для чужих з нотатками для себе. А в
`derived` картці не місце: вона нічим не відтворюється.

Ключ — ключ справи на ЦІЙ машині. Картка описує, що людина хоче показати
про свою справу, і за межі машини вона їде лише всередині маніфесту.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CARDS_NAME = "cards.json"

#: Поля картки, які можна задати. Кожне лягає в `case` маніфесту.
FIELDS = ("title", "years", "places", "doc_type")

#: Стеля довжини назви: картка — не місце для абзацу.
MAX_TITLE = 300
MAX_PLACES = 20
MAX_PLACE = 120

_YEARS = re.compile(r"^\s*(\d{3,4})\s*(?:[-–—.]+\s*(\d{3,4}))?\s*$")


class CardError(ValueError):
    """Поле картки не прийнято — з названою причиною."""


def cards_path() -> Path:
    from nyshporka.share import journal

    return journal.share_dir() / CARDS_NAME


def _load_all() -> dict[str, dict[str, Any]]:
    from nyshporka.utils.atomic import CorruptFileError, read_json

    try:
        raw = read_json(cards_path(), default={})
    except CorruptFileError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def get(case_key: str) -> dict[str, Any]:
    """Картка справи — або порожньо, якщо її не задавали."""
    if not case_key:
        return {}
    return dict(_load_all().get(case_key) or {})


def genres() -> dict[str, str]:
    """Коди жанрів картки з довідника архівів: `birth` → «народження»."""
    try:
        from nyshporka.archives import active

        return dict(active().record_type_labels or {})
    except Exception:
        return {}


def parse_years(raw: str) -> list[int]:
    """«1795-1797», «1795», «1795–1797» → `[1795, 1797]`."""
    m = _YEARS.match(str(raw or ""))
    if not m:
        raise CardError(f"роки «{raw}» не розібрано — пишіть «1795» або «1795-1797»")
    a = int(m.group(1))
    b = int(m.group(2) or a)
    lo, hi = min(a, b), max(a, b)
    if lo < 1300 or hi > 2100:
        raise CardError(f"роки «{raw}» поза межами 1300–2100")
    return [lo, hi]


def normalize(*, title: str | None = None, years: str | None = None,
              places: list[str] | None = None,
              doc_type: str | None = None) -> dict[str, Any]:
    """Перевірити поля картки. `None` — поле не задавали; `""`/`[]` — стерти."""
    out: dict[str, Any] = {}
    if title is not None:
        t = " ".join(str(title).split())
        if len(t) > MAX_TITLE:
            raise CardError(f"назва довша за {MAX_TITLE} символів")
        if "[[" in t:
            raise CardError("у назві посилання на особу дерева (`[[…]]`) — "
                            "це нотатка дослідження, а не назва справи")
        out["title"] = t
    if years is not None:
        out["years"] = parse_years(years) if str(years).strip() else []
    if places is not None:
        clean = [" ".join(str(p).split()) for p in places]
        clean = [p for p in clean if p]
        if len(clean) > MAX_PLACES:
            raise CardError(f"місць більше за {MAX_PLACES}")
        if any(len(p) > MAX_PLACE for p in clean):
            raise CardError(f"назва місця довша за {MAX_PLACE} символів")
        out["places"] = clean
    if doc_type is not None:
        code = str(doc_type).strip()
        known = genres()
        if code and known and code not in known:
            # Людина могла написати підпис замість коду: «сповідні».
            by_label = {v: k for k, v in known.items()}
            code = by_label.get(code, code)
            if code not in known:
                raise CardError(f"жанр «{doc_type}» невідомий; є: "
                                + ", ".join(f"{k} ({v})" for k, v in known.items()))
        out["doc_type"] = code
    return out


def set_fields(case_key: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Дописати поля в картку справи. Порожнє значення стирає поле."""
    from nyshporka.utils.atomic import write_json

    if not case_key:
        raise CardError("не названо справу")
    allc = _load_all()
    card = dict(allc.get(case_key) or {})
    for k, v in fields.items():
        if k not in FIELDS:
            continue
        if v in ("", [], None):
            card.pop(k, None)
        else:
            card[k] = v
    if card:
        allc[case_key] = card
    else:
        allc.pop(case_key, None)
    path = cards_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, allc)
    return card


def clear(case_key: str) -> bool:
    """Прибрати картку справи цілком. Повертає, чи вона була."""
    from nyshporka.utils.atomic import write_json

    allc = _load_all()
    if case_key not in allc:
        return False
    allc.pop(case_key)
    write_json(cards_path(), allc)
    return True


def apply(case: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Покласти картку поверх зібраного опису справи.

    Жанр, заданий людиною, витісняє здогад за назвою разом із переліком
    типів записів: інакше картка несла б код одного жанру й перелік іншого.
    """
    out = dict(case)
    if card.get("title"):
        out["title"] = card["title"]
    if card.get("years"):
        out["years"] = list(card["years"])
    if card.get("places"):
        out["places"] = list(card["places"])
    if card.get("doc_type"):
        out["doc_type"] = card["doc_type"]
        out["record_types"] = [card["doc_type"]]
    return out
