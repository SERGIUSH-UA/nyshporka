"""Консенсус двох незалежних вичиток однієї справи.

Пілот 2026-07-26 показав, чому одного проходу мало: vision по тайлах дає
повнішу структуру (усі учасники, стани, місця, підсумки причту), але читає
прізвища гірше за старий Opus-декод — і, найгірше, подає помилку як упевнене
прочитання. «Аѳанасій» стало «Иоаннъ», «Ѳеодоръ Осаковскій» — «Тодоръ
Осадовскій», а восприємник «Дол[ищ…]» перетворився на «Гон[нрзб]», тобто
загубив хіт роду. Друга гілка при цьому помилялась в інших місцях.

Звідси правило: **у реєстр без ескалації йде тільки те, на чому дві незалежні
вичитки зійшлися.** Розбіжність не вирішується голосуванням і не ховається —
вона стає окремим завданням на третій прохід із зазначенням, куди дивитись.

Зіставлення йде по `(scan, row)` — номер акту в книзі є природним стабільним
ключем, і саме тому контракт вимагає його від кожного запису.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from nyshporka.pagestore.models import PageNote, Record, RecordPerson
from nyshporka.records import sanitize
from nyshporka.records.checksum import parse_row as _parse_row
from nyshporka.records.names import norm_given, norm_patronymic
from nyshporka.records.profile import Profile
from nyshporka.records.taxonomy import SKIP_ROLES, place_key
from nyshporka.utils.translit import normalize_archival

# поля учасника, які звіряються пооб'єктно
PERSON_FIELDS = ("name", "surname", "given", "patronymic", "estate", "place", "age", "sex")
# поля акту
RECORD_FIELDS = ("date", "date2", "sheet")

# маркери непевності — таке значення програє впевненому, а не конфліктує з ним
_UNSURE = ("[нрзб]", "[…]", "...", "?")

FUZZY_SAME_NAME = 88        # поріг «те саме ім'я, інакше написане»
NEAR_SCANS = 6              # у межах скількох аркушів акт із тим самим № — той самий
_SCAN_NUM = re.compile(r"(\d+)")

# Поля, розбіжність у яких на третій прохід НЕ йде:
# `name` — похідне від given/patronymic/surname, його конфлікт завжди дублює
# конфлікт складників; `sheet` — номер аркуша, а не факт про людину.
NO_ESCALATE_FIELDS = {"name", "sheet"}


def is_unsure(value: str | None) -> bool:
    return any(m in (value or "") for m in _UNSURE)


def same_reading(a: str, b: str, field_name: str = "",
                 fuzzy: int = FUZZY_SAME_NAME) -> bool:
    """Чи це те саме прочитання, лише інакше передане на письмі.

    «Мурлыка»/«Мурлика», «Афанасіевъ»/«Аѳанасіевъ», «Софрониевъ»/«Софроніевъ»,
    «села Ротмистровки»/«с. Ротмистровка» — гілки не розійшлися в тому, ЩО
    написано, лише в тому, як передати ы/и, ѳ/ф, і/и та відмінок. Ганяти такі
    пари на третій прохід — палити ресурс на орфографію; справжня розбіжність
    («Иоаннъ» проти «Аѳанасій», «Осадовскій» проти «Осаковскій») нормалізацію
    переживає й лишається конфліктом.
    """
    norm = {"place": place_key, "given": norm_given,
            "patronymic": norm_patronymic}.get(field_name, normalize_archival)
    na, nb = norm(a), norm(b)
    if not na:
        return False
    if na == nb:
        return True
    # Іменні поля міряємо ще й fuzzy: кирилиця XIX ст. пише те саме ім'я надто
    # багатьма способами, щоб перелічити всі («Татіана»/«Татіанна»,
    # «Яковлева»/«Іаковлева»). Поріг високий — справжні різночитання
    # («Иоаннъ» проти «Аѳанасій», «Гаврила» проти «Іоаннъ») лишаються далеко
    # внизу й на третій прохід усе одно потрапляють.
    if field_name in ("given", "patronymic", "surname"):
        return fuzz.ratio(na, nb) >= fuzzy
    return False


@dataclass
class Conflict:
    """Одне спірне поле — готове завдання для третього проходу."""

    scan: str
    row: str
    role: str
    field_name: str
    a: str
    b: str
    a_unsure: bool = False
    b_unsure: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"scan": self.scan, "row": self.row, "role": self.role,
                "field": self.field_name, "a": self.a, "b": self.b,
                "a_unsure": self.a_unsure, "b_unsure": self.b_unsure}


@dataclass(frozen=True)
class _Opts:
    """Розв'язані з профілю параметри звірки — щоб не тягти Profile крізь усе."""

    fuzzy_same_name: int = FUZZY_SAME_NAME
    near_scans: int = NEAR_SCANS
    no_escalate: frozenset[str] = frozenset(NO_ESCALATE_FIELDS)
    skip_roles: frozenset[str] = frozenset(SKIP_ROLES)


@dataclass
class MergeResult:
    records: list[Record] = field(default_factory=list)
    notes: list[PageNote] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    agreed_fields: int = 0
    filled_from_a: int = 0
    filled_from_b: int = 0
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)


def load_branch(path: Path) -> tuple[list[Record], list[PageNote], list[str]]:
    """Прочитати гілку: тека з JSON-виводами агентів або один файл."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    records, notes, errors = [], [], []
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{f.name}: {e}")
            continue
        payload = sanitize.clean_payload(payload)
        for item in payload.get("pages") or []:
            try:
                notes.append(PageNote.model_validate(item))
            except Exception as e:      # звітуємо про биті елементи, не валимо гілку
                errors.append(f"{f.name} page: {str(e)[:200]}")
        for item in payload.get("records") or []:
            try:
                records.append(Record.model_validate(item))
            except Exception as e:
                errors.append(f"{f.name} record: {str(e)[:200]}")
    return records, notes, errors


def _key(rec: Record) -> tuple[str, str, str, str]:
    """Природний ключ книги: секція + рік + номер акту.

    Спершу ключем був скан, і це ламалось: гілки по-різному приписують акт до
    аркуша (конвертація MD віднесла всі шлюби 0461–0463 до першого скана, а
    vision розклала по своїх) — жоден із 18 шлюбних актів не зіставився.
    Але номер акту унікальний у межах року й секції за побудовою книги, тож
    скан — це деталь розміщення, а не ідентичності.

    `rtype` для підсумків не бере участі: tally зіставляється за періодом.
    """
    if rec.rtype == "tally":
        d = rec.date2 or rec.date
        return ("tally", (d.value if d else ""), "", "")
    d = rec.date2 or rec.date
    year = (d.value[:4] if d and d.value else "")
    row = (rec.row or "").strip().lower()
    lane, num = "", row
    parsed = _parse_row(row)
    if parsed:
        lane, n = parsed
        num = str(n)
    return (rec.rtype, year, lane, num)


def _dval(v: Any) -> str:
    return (v.value if v is not None and hasattr(v, "value") else "") or ""


def _pick(a: str, b: str, prefer_a: bool) -> tuple[str, str | None]:
    """Обрати значення поля з двох гілок. Другим — звідки взято ('a'/'b'/None=збіг)."""
    if a == b:
        return a, None
    if not a:
        return b, "b"
    if not b:
        return a, "a"
    # впевнене прочитання перемагає позначене як непевне без ескалації:
    # «Пушкарь» проти «Пушкарь?» — це не дві версії, це одна з різною сміливістю
    if is_unsure(a) and not is_unsure(b):
        return b, "b"
    if is_unsure(b) and not is_unsure(a):
        return a, "a"
    # «Гончаръ/Ганчаръ» проти «Гончаръ» — це не дві версії, а розмита й точна
    # форма однієї: агент, що вагався, лишив обидва варіанти через скісну.
    # Конкретніша перемагає незалежно від переваги гілки.
    pa, pb = {x.strip() for x in a.split("/")}, {x.strip() for x in b.split("/")}
    if len(pa) > 1 and pb & pa and len(pb) == 1:
        return b, "b"
    if len(pb) > 1 and pa & pb and len(pa) == 1:
        return a, "a"
    return (a, "a") if prefer_a else (b, "b")


def merge(records_a: list[Record], records_b: list[Record],
          notes_a: list[PageNote], notes_b: list[PageNote],
          prefer_a: bool = True, profile: Profile | None = None) -> MergeResult:
    """Звести дві гілки: збіги — в реєстр, розбіжності — в чергу ескалації.

    Акт, який бачила лише одна гілка, береться цілком: це не конфлікт, а
    просто те, що другий прохід пропустив (часто — підсумки причту, яких
    старий декод не фіксував узагалі).
    """
    cfg = (profile.consensus if profile else {}) or {}
    opts = _Opts(
        fuzzy_same_name=cfg.get("fuzzy_same_name", FUZZY_SAME_NAME),
        near_scans=cfg.get("near_scans", NEAR_SCANS),
        no_escalate=frozenset(cfg.get("no_escalate_fields", NO_ESCALATE_FIELDS)),
        skip_roles=frozenset(((profile.reconstitute if profile else {}) or {}).get(
            "skip_roles", SKIP_ROLES)),
    )
    res = MergeResult()
    ia = {_key(r): r for r in records_a}
    ib = {_key(r): r for r in records_b}

    pairs: list[tuple[Record, Record]] = []
    for key in set(ia) & set(ib):
        pairs.append((ia.pop(key), ib.pop(key)))
    pairs += _match_leftovers(ia, ib, opts.near_scans)

    for ra, rb in sorted(pairs, key=lambda p: str(_key(p[0]))):
        res.records.append(_merge_record(ra, rb, prefer_a, res, opts))
    for rec in ia.values():
        res.records.append(rec)
        res.only_a.append(f"{rec.scans[0] if rec.scans else '?'}/{rec.row or '?'}")
    for rec in ib.values():
        res.records.append(rec)
        res.only_b.append(f"{rec.scans[0] if rec.scans else '?'}/{rec.row or '?'}")

    res.notes = _merge_notes(notes_a, notes_b)
    return res


def _scan_no(rec: Record) -> int | None:
    m = _SCAN_NUM.search(rec.scans[0]) if rec.scans else None
    return int(m.group(1)) if m else None


def _match_leftovers(ia: dict[tuple[str, str, str, str], Record],
                     ib: dict[tuple[str, str, str, str], Record],
                     near_scans: int = NEAR_SCANS) -> list[tuple[Record, Record]]:
    """Другий етап: зіставити те, що розійшлося через нечитабельний рік.

    Коли агент не зміг розібрати останню цифру в бланку «186_», рік потрапляє
    в ключ як «186X» і акт не знаходить свою пару, хоча це очевидно той самий
    запис: та сама секція, той самий номер, сусідній аркуш. Тому залишки
    доматчуємо за (секція, лічильник, №) з вимогою, щоб скани були поруч —
    номер акту унікальний у межах року, і на дистанції кількох аркушів
    зіткнення двох різних років неможливе.
    """
    def loose(rec: Record) -> tuple[str, str, str]:
        k = _key(rec)
        return (k[0], k[2], k[3])

    by_loose: dict[tuple[str, str, str], list[tuple[Any, Record]]] = \
        defaultdict(list)
    for key, rec in ib.items():
        by_loose[loose(rec)].append((key, rec))

    out = []
    for key_a in list(ia):
        rec_a = ia[key_a]
        cands = by_loose.get(loose(rec_a)) or []
        na = _scan_no(rec_a)
        for key_b, rec_b in cands:
            if key_b not in ib:
                continue
            nb = _scan_no(rec_b)
            if na is not None and nb is not None and abs(na - nb) > near_scans:
                continue
            out.append((ia.pop(key_a), ib.pop(key_b)))
            break
    return out


def _merge_record(ra: Record, rb: Record, prefer_a: bool, res: MergeResult,
                  opts: _Opts | None = None) -> Record:
    opts = opts or _Opts()
    base = ra.model_copy(deep=True)
    scan = (ra.scans or rb.scans or ["?"])[0]
    row = ra.row or rb.row or "?"

    for fname in RECORD_FIELDS:
        va, vb = getattr(ra, fname), getattr(rb, fname)
        sa, sb = (_dval(va), _dval(vb)) if fname.startswith("date") else (va or "", vb or "")
        value, src = _pick(sa, sb, prefer_a)
        if src is None:
            res.agreed_fields += 1
            continue
        if (fname not in opts.no_escalate
                and sa and sb and sa != sb and not (is_unsure(sa) or is_unsure(sb))
                and not same_reading(sa, sb, fname, opts.fuzzy_same_name)):
            res.conflicts.append(Conflict(scan, row, "—", fname, sa, sb,
                                          is_unsure(sa), is_unsure(sb)))
        if fname.startswith("date"):
            setattr(base, fname, va if value == sa else vb)
        else:
            setattr(base, fname, value)
        res.filled_from_a += src == "a"
        res.filled_from_b += src == "b"

    # учасники зіставляються за роллю; однойменних ролей в акті буває кілька
    # (двоє восприємників), тому беремо позиційно всередині ролі
    by_role_a: dict[str, list[RecordPerson]] = defaultdict(list)
    by_role_b: dict[str, list[RecordPerson]] = defaultdict(list)
    for p in ra.persons:
        by_role_a[p.role].append(p)
    for p in rb.persons:
        by_role_b[p.role].append(p)

    merged_persons: list[RecordPerson] = []
    for role in sorted(set(by_role_a) | set(by_role_b)):
        # причт однаковий під кожним актом і в реєстр не входить — розбіжність
        # у ньому не варта третього проходу (у пілоті це були 3 конфлікти з 39)
        escalate_role = role not in opts.skip_roles
        la, lb = by_role_a.get(role, []), by_role_b.get(role, [])
        for i in range(max(len(la), len(lb))):
            pa = la[i] if i < len(la) else None
            pb = lb[i] if i < len(lb) else None
            if pa is None or pb is None:
                found = pa or pb
                if found is not None:
                    merged_persons.append(found)
                continue
            person = pa.model_copy(deep=True)
            marks = []
            for fname in PERSON_FIELDS:
                va, vb = getattr(pa, fname) or "", getattr(pb, fname) or ""
                value, src = _pick(va, vb, prefer_a)
                if src is None:
                    res.agreed_fields += 1
                    continue
                setattr(person, fname, value or None)
                res.filled_from_a += src == "a"
                res.filled_from_b += src == "b"
                # `name` ескалюємо лише коли складників нема в жодній гілці —
                # інакше він мовчить, а говорять given/patronymic/surname
                bare = not any(getattr(p, f) for p in (pa, pb)
                               for f in ("given", "surname"))
                escalate_field = fname not in opts.no_escalate or (
                    fname == "name" and bare)
                if (escalate_role and escalate_field
                        and va and vb and va != vb
                        and not (is_unsure(va) or is_unsure(vb))
                        and not same_reading(va, vb, fname, opts.fuzzy_same_name)):
                    res.conflicts.append(
                        Conflict(scan, row, role, fname, va, vb,
                                 is_unsure(va), is_unsure(vb)))
                    marks.append(f"{fname}: A«{va}» ≠ B«{vb}»")
            if marks:
                person.note = " ⟂ ".join(
                    x for x in [person.note, "⚠ розбіжність вичиток — " + "; ".join(marks)]
                    if x)[:600]
            merged_persons.append(person)
    base.persons = merged_persons
    if not base.counts and rb.counts:
        base.counts = dict(rb.counts)
    return base


def _merge_notes(a: list[PageNote], b: list[PageNote]) -> list[PageNote]:
    """Анотації сторінок об'єднуються union'ом — сховище все одно домержить."""
    by_scan: dict[str, PageNote] = {}
    for note in [*a, *b]:
        old = by_scan.get(note.scan)
        if old is None:
            by_scan[note.scan] = note.model_copy(deep=True)
            continue
        for s in note.surnames:
            if s not in old.surnames:
                old.surnames.append(s)
        for pl in note.places:
            if pl not in old.places:
                old.places.append(pl)
        for y in note.years:
            if y not in old.years:
                old.years.append(y)
    return list(by_scan.values())


def conflict_tasks(conflicts: list[Conflict], tile_root: Path,
                   case_key: str) -> list[dict[str, Any]]:
    """Згрупувати розбіжності по сканах — одне завдання ескалації на скан."""
    by_scan: dict[str, list[Conflict]] = defaultdict(list)
    for c in conflicts:
        by_scan[c.scan].append(c)
    out = []
    for scan, items in sorted(by_scan.items()):
        stem = Path(scan).stem
        out.append({
            "scan": scan,
            "tiles": str(tile_root / case_key.replace("/", "_") / stem),
            "n": len(items),
            "conflicts": [c.as_dict() for c in items],
        })
    return out
