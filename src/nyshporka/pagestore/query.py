"""Fuzzy-пошук по сховищу сторінок — без SQLite.

Скоринг усе одно O(N) через rapidfuzz, тож індекс — просто нормалізовані рядки
в пам'яті з інвалідацією по mtime файлу справи (ідіома htr_store._case_index).
Нормалізація — спільна з HTR-пошуком (`translit.normalize_archival`), тому
«Сікорскій» знаходиться по «Sikorski» і навпаки. Поріг за замовчуванням 80:
дані тут людино-куровані, а не CER-30% OCR, тож шуму як у HTR (55-65) немає.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from rapidfuzz import fuzz

from nyshporka.pagestore import store
from nyshporka.records import names
from nyshporka.utils.translit import normalize_archival

_TOKEN_RE = re.compile(r"[^\s.,;:()\[\]{}/\\|«»\"'’—–-]+")

# path(str) → (mtime_ns, index-dict)
_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}


def _iter_files(case_key: str | None = None) -> Iterator[Path]:
    root = store.PAGES_ROOT
    if not root.is_dir():
        return
    for p in sorted(root.glob("*/*.json")):
        if p.name.endswith(".tmp"):
            continue
        if case_key is not None:
            idx = _index(p)
            if idx and idx["key"] == case_key:
                yield p
        else:
            yield p


def _index(path: Path) -> dict[str, Any] | None:
    """Індекс одного файлу справи: сирі + нормалізовані рядки для скорингу."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pages = data.get("pages") or {}
    surnames, places = [], []
    for scan, note in pages.items():
        for s in note.get("surnames") or []:
            surnames.append((scan, s, normalize_archival(s)))
        for s in note.get("places") or []:
            places.append((scan, s, normalize_archival(s)))
    persons = []
    # 🗺 Місце в акті — окрема вісь пошуку, не підмножина прізвищ. Питання «хто з
    # цього села трапляється в чужих книгах» без неї не ставиться взагалі: формула
    # «мѣстечка Мястковки крестьянинъ» лежить у `place` учасника, а індексувалося
    # досі саме лише прізвище. Місце тримається і на записі (`Record.places` —
    # де відбулась подія), і на учаснику (`RecordPerson.place` — звідки він),
    # і плутати їх не можна: у шлюбі наречений і наречена якраз із різних сіл.
    rec_places = []
    for rec in data.get("records") or []:
        for s in rec.get("places") or []:
            rec_places.append((rec, None, s, normalize_archival(s)))
        for p in rec.get("persons") or []:
            if p.get("place"):
                rec_places.append((rec, p, p["place"], normalize_archival(p["place"])))
            # прізвище явне, або останній токен повного імені як fallback
            raw = p.get("surname")
            if not raw:
                toks = (p.get("name") or "").split()
                raw = toks[-1] if toks else ""
            if not raw:
                continue
            persons.append((rec, p, raw, normalize_archival(raw)))
    idx = {"key": data.get("key") or "", "shifra": data.get("shifra") or "",
           "pages": pages, "surnames": surnames, "places": places,
           "persons": persons, "rec_places": rec_places}
    _CACHE[str(path)] = (mtime, idx)
    return idx


def _stems(q: str, *, given: bool = True, folk: bool = False,
           ) -> tuple[list[str], dict[str, str]]:
    """Стеми запиту й звідки кожен узявся.

    🔴 Розширення тут те саме, що в пошуку по декоду, і кличеться з того самого
    місця (`records.names.expand_stems`). Друга копія правила розійшлася б із
    першою тихо, і три сховища почали б відповідати по-різному на те саме
    питання — залежно від того, в яке з них спитали.
    """
    raw = [normalize_archival(w) for w in _TOKEN_RE.findall(q) if len(w) >= 3]
    raw = [s for s in raw if len(s) >= 3]
    if not raw:
        return [], {}
    if not (given or folk):
        return raw, dict.fromkeys(raw, names.ORIGIN_QUERY)
    return names.expand_stems(raw, given=given, folk=folk)


def _asked(origin: dict[str, str]) -> list[str]:
    """Те, що набрала людина, — окремим числом від того, чим шукали насправді."""
    return [s for s, why in origin.items() if why == names.ORIGIN_QUERY]


def _added(origin: dict[str, str]) -> list[str]:
    return [s for s, why in origin.items() if why != names.ORIGIN_QUERY]


def _score(norm: str, stems: list[str]) -> tuple[int, str]:
    """Найкращий бал і СТЕМ, яким його взято — щоб хіт умів назвати написання."""
    # 0.0, а не 0: rapidfuzz рахує у float, і ціле тут лише прикидалося б типом.
    best = 0.0
    by = ""
    for stem in stems:
        # закороткий рядок не може легітимно матчити довгий стем (гард htr_store)
        if len(norm) < max(4, int(len(stem) * 0.6)):
            continue
        sc = fuzz.ratio(norm, stem)
        if len(norm) >= len(stem):
            sc = max(sc, fuzz.partial_ratio(norm, stem))  # відмінкові хвости
        if sc > best:
            best, by = sc, stem
    return round(best), by


def grep_surnames(q: str, thresh: int = 80, case_key: str | None = None,
                  places: bool = False, limit: int = 200, *,
                  given: bool = True, folk: bool = False) -> dict[str, Any]:
    """Fuzzy по всіх збережених прізвищах (або місцях) усіх справ.

    ⚠ Гніздо імен розкривається і для осі МІСЦЯ теж, і це свідомо: назва села
    поділяє з іменем ту саму нормалізацію, а зайвий стем там просто нічого не
    знаходить. Окремий вимикач на вісь був би ручкою, яку ніхто не крутить.
    """
    stems, origin = _stems(q, given=given, folk=folk)
    if not stems:
        return {"hits": [], "cases": 0, "error": "закороткий запит"}
    hits, scanned = [], 0
    for path in _iter_files(case_key):
        idx = _index(path)
        if not idx:
            continue
        scanned += 1
        for scan, raw, norm in idx["places" if places else "surnames"]:
            sc, by = _score(norm, stems)
            if sc >= thresh:
                note = idx["pages"].get(scan) or {}
                hits.append({"key": idx["key"], "shifra": idx["shifra"], "scan": scan,
                             "page_type": note.get("page_type") or "",
                             "status": note.get("status") or "",
                             "matched": raw, "score": sc,
                             "stem": by,
                             "stem_origin": origin.get(by, names.ORIGIN_QUERY),
                             "comment": note.get("comment") or ""})
    hits.sort(key=lambda h: -h["score"])
    return {"hits": hits[:limit], "total": len(hits), "cases": scanned,
            "stems": stems, "stems_asked": _asked(origin),
            "stems_added": _added(origin), "folk": bool(folk),
            "thresh": thresh}


def grep_records(q: str, thresh: int = 80, case_key: str | None = None,
                 role: str | None = None, rtype: str | None = None,
                 place: bool = False, limit: int = 200, *,
                 given: bool = True, folk: bool = False) -> dict[str, Any]:
    """Fuzzy по учасниках записів; `place=True` — шукати по місцю, а не прізвищу.

    Пошук по місцю відповідає на питання, якого прізвищевий не бере: «які акти
    згадують це поселення» — байдуже, під яким прізвищем. Саме так шукають
    односельців у книгах чужих парафій.
    """
    stems, origin = _stems(q, given=given, folk=folk)
    if not stems:
        return {"hits": [], "cases": 0, "error": "закороткий запит"}
    hits, scanned = [], 0
    for path in _iter_files(case_key):
        idx = _index(path)
        if not idx:
            continue
        scanned += 1
        for rec, person, raw, norm in idx["rec_places" if place else "persons"]:
            # Місце з рівня запису учасника не має — тоді фільтр ролі не звужує,
            # а знищував би вибірку, тож застосовуємо його лише там, де є особа.
            if role and person is not None and person.get("role") != role:
                continue
            if role and person is None:
                continue
            if rtype and rec.get("rtype") != rtype:
                continue
            sc, by = _score(norm, stems)
            if sc >= thresh:
                d = rec.get("date") or {}
                hits.append({"key": idx["key"], "shifra": idx["shifra"],
                             "rid": rec.get("rid") or "", "rtype": rec.get("rtype") or "",
                             "date": d.get("value") if isinstance(d, dict) else "",
                             "scans": rec.get("scans") or [],
                             "role": (person or {}).get("role") or "",
                             "name": (person or {}).get("name") or "",
                             "place": raw if place else (person or {}).get("place") or "",
                             "stem": by,
                             "stem_origin": origin.get(by, names.ORIGIN_QUERY),
                             "score": sc})
    hits.sort(key=lambda h: -h["score"])
    return {"hits": hits[:limit], "total": len(hits), "cases": scanned,
            "stems": stems, "stems_asked": _asked(origin),
            "stems_added": _added(origin), "folk": bool(folk),
            "thresh": thresh}
