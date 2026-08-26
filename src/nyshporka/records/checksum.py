"""Доказ повноти вичитки — на власних чексумах книги, а не на самозвіті агента.

Метрична книга XIX ст. надлишкова за конструкцією, і цим треба користуватись:

1. **Наскрізна нумерація за статтю.** Народження й смерті нумеруються двома
   незалежними лічильниками (мужеска / женска) від 1 до кінця року. Діра в
   послідовності = пропущений акт, і видно її без жодного повторного рендеру.
2. **Підсумки причту.** Наприкінці кожного місяця й року книга сама себе
   рахує: «родилось дѣтей мужеска пола пять № 5, а женска четыре № 4».
   Записані як `rtype="tally"` з `counts`, вони дають очікуване число, з яким
   звіряється фактично вичитане.

Тому «справу вичитано» — це не «агент сказав, що все», а «жодної діри в двох
лічильниках і всі підсумки зійшлися». Пор. memory
`negative-result-requires-coverage-denominator`.

Окремий випадок — у справі ≥2 примірники (парафіяльний і консисторський).
Один і той самий акт тоді законно трапляється двічі під тим самим номером;
`duplicates` розрізняє це (ті самі особи) від справжнього конфлікту (різні).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from nyshporka.models.common import GedDate
from nyshporka.pagestore.models import CaseFile, Record
from nyshporka.records.profile import Profile
from nyshporka.utils.translit import normalize_archival

# «м38» / «ж36» / «ч12» / «m5» / «38» — лічильник + номер
_ROW_RE = re.compile(r"^\s*([мМmчЧжЖfF]?)\s*[.\-–№]?\s*(\d+)")
_LANE = {"м": "m", "m": "m", "ч": "m", "ж": "f", "f": "f"}
# у підсумку шлюбів лічильник один, і агенти називають його по-різному —
# зводимо до того самого «наскрізного» лічильника, що й у самих актах
_TALLY_LANE_ALIAS = {"total": "", "all": "", "n": "", "count": "", "браков": "",
                     "marriages": "", "sum": ""}

EVENT_TYPES = ("birth", "marriage", "death")


def parse_row(row: str) -> tuple[str, int] | None:
    """'ж36' → ('f', 36). Без префікса — наскрізний лічильник (''), як у шлюбах."""
    m = _ROW_RE.match(row or "")
    if not m:
        return None
    return _LANE.get(m.group(1).lower(), ""), int(m.group(2))


def _booked(rec: Record, numbering_by: str = "rite") -> GedDate | None:
    """Дата, за якою акт лежить у книзі.

    У метриці номер присвоюється при внесенні, тобто за датою ОБРЯДУ: дитина,
    народжена 24 листопада і хрещена 5 грудня, потрапляє в грудневу нумерацію
    і в грудневий підсумок. Звіряти чексуми за датою народження означало б
    бачити фальшиві розбіжності на кожній межі місяця.

    Але це властивість типу книги, а не всесвітня: у сповідному розписі чи
    ревізькій казці порядковий номер прив'язаний до самої події (двору, сім'ї),
    тож профіль може перемкнути на `numbering_by: event`.
    """
    return (rec.date or rec.date2) if numbering_by == "event" else (rec.date2 or rec.date)


def _year(rec: Record, numbering_by: str = "rite") -> int | None:
    for d in (_booked(rec, numbering_by), rec.date):
        if d and d.value and len(d.value) >= 4 and d.value[:4].isdigit():
            return int(d.value[:4])
    return None


def _period(rec: Record, numbering_by: str = "rite") -> str:
    """Ключ періоду підсумку: 'YYYY-MM' для місячного, 'YYYY' для річного."""
    d = _booked(rec, numbering_by)
    if not d or not d.value:
        return ""
    return d.value[:7] if getattr(d, "precision", "") in ("month", "day") else d.value[:4]


def _person_key(rec: Record) -> str:
    """Груба підпис-сигнатура учасників — щоб відрізнити другий примірник від конфлікту."""
    names = sorted(normalize_archival(p.name or "") for p in rec.persons)
    return "|".join(n for n in names if n)


@dataclass
class LaneReport:
    """Стан одного лічильника (мужеска / женска / наскрізний) за рік."""

    lane: str
    seen: list[int] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)
    duplicated: list[int] = field(default_factory=list)
    min_num: int = 0
    max_num: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"lane": self.lane, "count": len(set(self.seen)),
                "min": self.min_num, "max": self.max_num,
                "missing": self.missing, "duplicated": self.duplicated,
                "below_start": max(0, self.min_num - 1)}


def _lane_report(lane: str, nums: list[int]) -> LaneReport:
    """Діри рахуємо ЛИШЕ між вичитаними номерами.

    Під час поступової вичитки початок року ще не прочитано, і відлік від 1
    робив би «дірою» всю нечитану частину — звіт тонув би в шумі й переставав
    показувати справжні пропуски. Скільки лишилось до початку року, видно
    окремим `below_start`.
    """
    uniq = sorted(set(nums))
    rep = LaneReport(lane=lane, seen=uniq,
                     min_num=uniq[0] if uniq else 0,
                     max_num=uniq[-1] if uniq else 0)
    seen_once: dict[int, int] = defaultdict(int)
    for n in nums:
        seen_once[n] += 1
    rep.duplicated = sorted(n for n, c in seen_once.items() if c > 1)
    if uniq:
        rep.missing = [n for n in range(rep.min_num, rep.max_num + 1)
                       if n not in seen_once]
    return rep


def audit(cf: CaseFile, profile: Profile | None = None) -> dict[str, Any]:
    """Повний звіт повноти: лічильники, підсумки, дублі, сторінки без записів."""
    numbering_by = ((profile.book if profile else {}) or {}).get("numbering_by", "rite")
    events = [r for r in cf.records if r.rtype in EVENT_TYPES]
    tallies = [r for r in cf.records if r.rtype == "tally"]

    # ── лічильники за (рік, тип) ─────────────────────────────────────────────
    lanes: dict[tuple[int | None, str, str], list[int]] = defaultdict(list)
    unnumbered: list[str] = []
    for rec in events:
        parsed = parse_row(rec.row)
        if parsed is None:
            unnumbered.append(rec.rid)
            continue
        lane, num = parsed
        lanes[(_year(rec, numbering_by), rec.rtype, lane)].append(num)

    by_year: dict[tuple[int | None, str], list[LaneReport]] = defaultdict(list)
    for (year, rtype, lane), nums in sorted(lanes.items(), key=lambda kv: str(kv[0])):
        by_year[(year, rtype)].append(_lane_report(lane, nums))

    # ── підсумки книги проти фактично вичитаного ─────────────────────────────
    actual: dict[tuple[str, str, str], int] = defaultdict(int)
    for rec in events:
        p = _period(rec, numbering_by)
        parsed = parse_row(rec.row)
        lane = parsed[0] if parsed else ""
        actual[(p, rec.rtype, lane)] += 1
        if len(p) == 7:                       # місячний факт зараховується і в річний
            actual[(p[:4], rec.rtype, lane)] += 1

    tally_checks: list[dict[str, Any]] = []
    for t in tallies:
        p = _period(t, numbering_by)
        exp = {_TALLY_LANE_ALIAS.get(k.strip().lower(), _LANE.get(k.strip().lower(), k)): v
               for k, v in (t.counts or {}).items()}
        rt = _dominant_rtype(events, p, t, cf.pages, numbering_by)
        got = {lane: actual.get((p, rt, lane), 0) for lane in exp}
        tally_checks.append({
            "period": p, "rtype": rt, "scans": t.scans,
            "expected": exp, "actual": got,
            "ok": all(got.get(k) == v for k, v in exp.items()),
        })

    # ── дублі: другий примірник vs справжній конфлікт ────────────────────────
    groups: dict[tuple[int | None, str, str, int], list[Record]] = defaultdict(list)
    for rec in events:
        parsed = parse_row(rec.row)
        if parsed:
            groups[(_year(rec, numbering_by), rec.rtype, parsed[0], parsed[1])].append(rec)
    duplicates: list[dict[str, Any]] = []
    for (year, rtype, lane, num), recs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(recs) < 2:
            continue
        keys = {_person_key(r) for r in recs}
        duplicates.append({
            "year": year, "rtype": rtype, "row": f"{lane}{num}",
            "scans": [s for r in recs for s in r.scans],
            "rids": [r.rid for r in recs],
            "same_persons": len(keys) == 1,
            "verdict": "другий примірник" if len(keys) == 1 else "⚠ конфлікт прочитання",
        })

    # ── сторінки, що мали б дати записи, але не дали ─────────────────────────
    silent = sorted(
        scan for scan, note in cf.pages.items()
        if note.page_type in EVENT_TYPES
        and not any(scan in r.scans for r in cf.records)
    )

    problems: list[str] = []
    for (year, rtype), reps in sorted(by_year.items(), key=lambda kv: str(kv[0])):
        for rep in reps:
            if rep.missing:
                problems.append(
                    f"{year} {rtype} лічильник «{rep.lane or '—'}»: діри "
                    f"{compact(rep.missing)} у вичитаному {rep.min_num}–{rep.max_num}")
    for chk in tally_checks:
        if not chk["ok"]:
            problems.append(
                f"{chk['period']} {chk['rtype']}: книга рахує {fmt_counts(chk['expected'])}, "
                f"вичитано {fmt_counts(chk['actual'])} "
                f"(скан {','.join(chk['scans'] or [])})")
    for d in duplicates:
        if not d["same_persons"]:
            problems.append(
                f"{d['year']} {d['rtype']} №{d['row']}: той самий номер, "
                f"різні особи ({', '.join(d['scans'])})")
    if unnumbered:
        problems.append(f"{len(unnumbered)} записів без № — лічильник їх не бачить")
    # рік — друга половина ключа: номер акту наскрізний саме в межах року, тож
    # запис без року утворює власну примарну групу й ховає справжні діри
    undated = [r.rid for r in events if _year(r, numbering_by) is None]
    if undated:
        problems.append(
            f"{len(undated)} записів без року — номер акту без року не працює; "
            f"проставити з сусідніх сканів секції ({', '.join(undated[:6])})")
    if silent:
        problems.append(f"{len(silent)} сторінок типу подій без жодного запису: "
                        f"{', '.join(silent[:10])}{' …' if len(silent) > 10 else ''}")

    return {
        "key": cf.key, "shifra": cf.shifra,
        "pages_noted": len(cf.pages), "records": len(cf.records),
        "events": len(events), "tallies": len(tallies),
        "years": [
            {"year": year, "rtype": rtype, "lanes": [r.as_dict() for r in reps]}
            for (year, rtype), reps in sorted(by_year.items(), key=lambda kv: str(kv[0]))
        ],
        "tally_checks": tally_checks,
        "duplicates": duplicates,
        "unnumbered": unnumbered,
        "silent_pages": silent,
        "problems": problems,
        "clean": not problems,
    }


def _dominant_rtype(events: list[Record], period: str, tally: Record,
                    pages: dict[str, Any], numbering_by: str = "rite") -> str:
    """Тип секції, до якої належить підсумок: у самому tally він не написаний.

    Спершу за подіями того ж періоду, потім за подіями того ж року. Якщо і там
    порожньо (місяць без жодного акту — цілком звичайна річ у сільській
    парафії), питаємо сторінку, на якій підсумок стоїть. Раніше в цьому місці
    стояло глухе «birth», і підсумок шлюбів за порожній місяць звірявся з
    народженнями, даючи фальшиву розбіжність.
    """
    for scope in (period, period[:4]):
        counts: dict[str, int] = defaultdict(int)
        for r in events:
            p = _period(r, numbering_by)
            if p and scope and (p.startswith(scope) or scope.startswith(p)):
                counts[r.rtype] += 1
        if counts:
            return str(max(counts, key=lambda k: counts[k]))
    for scan in tally.scans:
        note = pages.get(scan)
        if note is not None and note.page_type in EVENT_TYPES:
            return str(note.page_type)
    return "birth"


def fmt_counts(counts: dict[str, int]) -> str:
    """{'m': 5, 'f': 4} → 'м5 · ж4' — щоб у звіті не світився пітонівський repr."""
    label = {"m": "м", "f": "ж", "": "№"}
    return " · ".join(f"{label.get(k, k)}{v}" for k, v in sorted(counts.items())) or "—"


def compact(nums: list[int]) -> str:
    """[3,4,5,9] → '3–5, 9'."""
    if not nums:
        return "—"
    out, run = [], [nums[0]]
    for n in nums[1:]:
        if n == run[-1] + 1:
            run.append(n)
        else:
            out.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
            run = [n]
    out.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
    return ", ".join(out)
