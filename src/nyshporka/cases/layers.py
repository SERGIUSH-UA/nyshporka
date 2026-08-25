"""📚 Справа з усіма шарами роботи над нею — в одному рядку.

Про кожну справу говорять три різні сховища, і жодне з них не відповідає на
питання цілком:

  **опис**   (`case_library.json`) — що це за книга: шифра, роки, місце, кадри;
  **реєстр** (`case_index.sqlite`) — що з нею вже зробили: чим прочитана, чи
             прошукана, скільки аркушів занесено оком;
  **вердикт** (`case_verdicts.json`) — що ВИРІШИЛА людина, подивившись.

Модуль зшиває їх в один рядок і рахує фасети й зведення по ВСІХ рядках.

🔴 Вердикт людини перекриває машинний статус, і не застаріває. Скан застаріває
від зміни моделі, декод — від нового прогону, а «я переглянув цю справу очима,
роду немає» лишається правдою й через рік.

🔴🔴 «Реєстру немає» і «нічого не зроблено» — РІЗНІ відповіді, і зводити їх до
нуля найдорожче саме тут. «1331 справа без декоду» виглядає як факт про
роботу, тоді як означає «зріз не збирали». Тому шари без реєстру віддаються
як `None`, а не як `0`, і зведення про них мовчить.

🛑 Чого тут НЕМАЄ навмисно: «скан застарів проти бойової моделі» й «робоча
версія». Обидва тримаються на журналі прогонів і реєстрі моделей, яких у цьому
застосунку немає — і вигадати їх означало б показати впевнене число там, де
нічим міряти.
"""
from __future__ import annotations

import time
from typing import Any

#: Колонки реєстру, які їдуть у рядок. Беремо саме їх, а не весь запис:
#: решта — службові сліди збірки, і пропонувати рішення на їхній підставі
#: означало б показувати, як зріз себе зібрав, замість того що в ньому є.
LAYER_FIELDS: tuple[str, ...] = (
    "htr_stage", "htr_coverage", "htr_pages_max", "htr_runs", "htr_updated",
    "htr_pysar_model", "htr_diak_model", "htr_skryba_model",
    "fuzzy_stage", "fuzzy_hits", "fuzzy_reviewed", "fuzzy_scanned",
    "canon_facts", "canon_persons", "canon_scans",
    "pages_noted", "pages_full",
    "settlement", "uezd", "guberniya", "place_id", "kind", "state",
)

#: Скільки живе зібраний набір. Ключ нижче ловить усе, що робиться ЧЕРЕЗ
#: застосунок; тека, покладена в `data/raw` провідником, пульсу не б'є — і
#: саме цей випадок закриває стеля часу.
TTL = 10.0

_CACHE: tuple[tuple, float, list[dict[str, Any]]] | None = None
_LAYERS: tuple[tuple, dict[str, dict[str, Any]]] | None = None


def _stat(path: Any) -> tuple[int, int]:
    try:
        s = path.stat()
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return (-1, -1)


def fingerprint() -> tuple:
    """Дешевий відбиток усього, від чого залежить рядок.

    🔴 Перелічено не «що згадалось», а КОЖНЕ джерело, яке бере участь у
    складанні: опис, реєстр, вердикти й пульс простору. Пропустити тут джерело
    означає показувати старе під виглядом свіжого — а цього не видно ніяк.
    """
    from nyshporka.cases import db
    from nyshporka.library import LIBRARY_PATH, VERDICTS_PATH

    try:
        from nyshporka.core import pulse

        beat = pulse.seq()
    except Exception:
        beat = 0
    return (_stat(LIBRARY_PATH), _stat(VERDICTS_PATH), _stat(db.DB_PATH), beat)


def layers_by_key() -> dict[str, dict[str, Any]]:
    """Шари обробки за ключем справи. Порожньо, якщо реєстру ще немає.

    🔴 Порожній словник тут означає «не знаємо», і викликач мусить розрізнити
    це від «нічого не зроблено». Повернути нулі було б зручніше й неправдиво.
    """
    global _LAYERS
    fp = fingerprint()
    if _LAYERS is not None and _LAYERS[0] == fp:
        return _LAYERS[1]
    from nyshporka.cases import db

    try:
        rows = db.query_rows(limit=0)
    except Exception:
        rows = []
    out = {r["key"]: {k: r.get(k) for k in LAYER_FIELDS}
           for r in rows if r.get("key")}
    _LAYERS = (fp, out)
    return out


def entries() -> list[dict[str, Any]]:
    """Усі справи: опис ∪ шари обробки ∪ вердикт людини.

    ⏱ Набір збирається РАЗ на зміну джерел. Складання читає тисячі записів і
    робить сотні `stat`; платити це на кожен натиск фільтра й кожне
    перегортання сторінки не було б за що — фасети й зведення рахуються по
    ВСІХ рядках за побудовою, тож урізати роботу до сторінки не можна.
    """
    global _CACHE
    fp, now = fingerprint(), time.monotonic()
    if _CACHE is not None and _CACHE[0] == fp and now - _CACHE[1] < TTL:
        return _CACHE[2]

    from nyshporka import library as L

    verdicts = L.load_verdicts()
    layers = layers_by_key()
    out: list[dict[str, Any]] = []
    for case in L.load_library():
        if not isinstance(case, dict):
            continue
        key = case.get("key") or ""
        row = dict(case)
        # 🔴 Немає реєстру — поля відсутні, а не нульові. Нуль сказав би
        # «перевірили, декоду немає».
        #
        # ⚠ Але те, що опис знає САМ, не затирається порожнечею реєстру:
        # кілька полів (місце, повіт) бувають в обох, і замінивши їх на `None`,
        # ми зробили б фільтр за повітом мовчки безрезультатним там, де відповідь
        # лежить у самому описі. Реєстр сильніший — але лише коли він є.
        got = layers.get(key) or {}
        for k in LAYER_FIELDS:
            v = got.get(k)
            if v is None and row.get(k) is not None:
                continue
            row[k] = v
        v = verdicts.get(key) or {}
        row["verdict"] = v.get("verdict") or ""
        row["verdict_note"] = v.get("note") or ""
        row["verdict_date"] = v.get("date") or ""
        row["verdict_pages"] = v.get("pages")
        out.append(row)
    _CACHE = (fp, now, out)
    return out


def has_layers() -> bool:
    """Чи є зріз обробки взагалі. Без нього колонки показують «?», а не «—»."""
    return bool(layers_by_key())


def status_of(row: dict[str, Any]) -> str:
    """Стан справи одним словом — для фільтра, не для показу.

    🔴 Вердикт людини перекриває все: «роду немає» знімає справу з черги на
    перепрогін, скільки б моделей відтоді не змінилось.
    """
    if row.get("verdict"):
        return str(row["verdict"])
    if not row.get("on_disk"):
        return "missing"
    stage = row.get("htr_stage")
    if stage is None:
        return "on_disk"          # реєстру немає — більше сказати нічого
    if stage in ("", "none"):
        return "unread"
    if stage == "partial":
        return "partial"
    return "read"


def facets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Значення фільтрів із лічильниками — по ВСІХ рядках, не по видачі.

    🔴 Фасет, зібраний із відфільтрованого, схлопується до одного пункту після
    першого ж вибору: решта архівів зникає зі списку, і повернутись до них
    нема чим — екран починає брехати про діючий фільтр.
    """
    def count(field: str, many: bool = False) -> list[dict[str, Any]]:
        got: dict[str, int] = {}
        for r in rows:
            vals = r.get(field) or ([] if many else "")
            for v in (vals if many else [vals]):
                v = str(v or "").strip()
                if v:
                    got[v] = got.get(v, 0) + 1
        return [{"code": k, "n": n}
                for k, n in sorted(got.items(), key=lambda x: (-x[1], x[0]))]

    return {"repos": count("repo"), "record_types": count("record_types", True),
            "uezds": count("uezd"), "doc_types": count("doc_type")}


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Зведення по всій бібліотеці.

    🔴 Числа шарів — `None`, коли реєстру немає. «0 без декоду» читалось би як
    досягнення, а означало б, що зріз не збирали.
    """
    got = has_layers()
    n = len(rows)
    out: dict[str, Any] = {
        "all": n,
        "on_disk": sum(1 for r in rows if r.get("on_disk")),
        "named": sum(1 for r in rows if r.get("title")),
        "curated": sum(1 for r in rows if r.get("curated")),
        "frames": sum(int(r.get("frames") or 0) for r in rows),
        "verdict_any": sum(1 for r in rows if r.get("verdict")),
        "no_clan": sum(1 for r in rows if r.get("verdict") == "no_clan"),
        "has_layers": got,
    }
    if not got:
        out.update({"no_htr": None, "no_fuzzy": None, "hits_open": None,
                    "read": None})
        return out
    out.update({
        "no_htr": sum(1 for r in rows
                      if (r.get("htr_stage") or "none") in ("", "none")),
        "read": sum(1 for r in rows
                    if (r.get("htr_stage") or "none") not in ("", "none")),
        "no_fuzzy": sum(1 for r in rows
                        if (r.get("fuzzy_stage") or "none") in ("", "none")),
        # Скільки кандидатів чекає ока: саме це число каже, де робота людини,
        # а не машини.
        "hits_open": sum(max(int(r.get("fuzzy_hits") or 0)
                             - int(r.get("fuzzy_reviewed") or 0), 0)
                         for r in rows),
    })
    return out


def staleness() -> dict[str, Any]:
    """Чи відстав зріз обробки від своїх джерел."""
    from nyshporka.cases import db

    try:
        return db.staleness(quick=True)
    except Exception:
        return {}


def reset() -> None:
    """Скинути кеші — для тестів і після перезбірки."""
    global _CACHE, _LAYERS
    _CACHE = None
    _LAYERS = None
