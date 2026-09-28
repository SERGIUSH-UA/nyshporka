"""🌱 Засіяти порожній канон із GEDCOM — експорту MyHeritage, Geni, FamilySearch,
Трекера Роду чи будь-якої програми родоводу.

🔴 Лише в ПОРОЖНІЙ канон. Злиття з наявним тут немає й не буде: GEDCOM нумерує
осіб по-своєму, і повторний імпорт поверх правленого канону або перетер би
чужу працю, або наплодив би двійників, яких потім зводять руками. Засівання —
один раз; далі канон ведуть файлами.

🔴 Цитата на все одна — сам файл GEDCOM, рівень `indirect`: дерево, зібране в
іншій програмі, є переказом джерел, а не джерелом. Тому й статус факту за
замовчуванням `hypothesis`, а `confirmed` — лише коли імпорт явно попросили
вірити дереву (`trust_tree`).

Сам файл кладеться в `data/source/gedcom/` — цитата посилається на копію в
просторі, а не на завантаження, яке завтра зникне.

Потребує `ged4py` (`pip install nyshporka[gedcom]`).
"""
from __future__ import annotations

import io
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from nyshporka.ids import family_id, person_id, place_id
from nyshporka.models import (
    Citation,
    Fact,
    Family,
    GedDate,
    MediaRef,
    NameVariant,
    Person,
    Place,
    Source,
)
from nyshporka.models.common import LangCode
from nyshporka.models.fact import FactStatus, FactType
from nyshporka.storage.files import write_entity

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

#: Події особи: тег GEDCOM → тип факту канону.
_PERSON_EVENTS: dict[str, FactType] = {
    "BIRT": "birth", "DEAT": "death", "BAPM": "baptism", "CHR": "baptism",
    "BURI": "burial", "EMIG": "emigration", "RESI": "residence",
}
_PERSON_ATTRS: dict[str, FactType] = {
    "OCCU": "occupation", "RELI": "religion", "NATI": "nationality",
    "EDUC": "education", "EVEN": "other",
}
_FAMILY_EVENTS: dict[str, FactType] = {"MARR": "marriage", "DIV": "divorce"}


class GedcomError(ValueError):
    """Імпорт не почато — з поясненням, що зробити."""


@dataclass
class Options:
    source_id: str = "S_GEDCOM"
    source_title: str = ""
    authority: str = ""
    #: Префікс для ідентифікаторів записів у чужій програмі (`RIN`) — щоб
    #: зв'язок «ця картка = той запис» пережив імпорт.
    alias_prefix: str = "GED"
    #: Хто без дати смерті й народжений не раніше цього року, вважається живим.
    private_born_after: int = 1946
    #: Вірити дереву: факти з датою чи місцем — `confirmed`, а не `hypothesis`.
    trust_tree: bool = False


@dataclass
class ImportReport:
    persons: int = 0
    families: int = 0
    places: int = 0
    private: int = 0
    preprocess_fixes: int = 0
    source_id: str = ""
    copied_to: str = ""
    written: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"persons": self.persons, "families": self.families, "places": self.places,
                "private": self.private, "preprocess_fixes": self.preprocess_fixes,
                "source_id": self.source_id, "copied_to": self.copied_to,
                "written": self.written}


@dataclass
class _Ctx:
    person_map: dict[str, str]
    family_map: dict[str, str]
    places: dict[str, Place]
    citation: Citation
    opts: Options
    skipped_refs: list[str] = field(default_factory=list)


# ── передобробка ─────────────────────────────────────────────────────────────
_LEVEL = re.compile(rb"^\s*\d+ ")
_CONC = b"2 CONC "


def fix_orphan_continuations(data: bytes) -> tuple[bytes, int]:
    """Приклеїти рядки NOTE, які програма перенесла без `n CONC`.

    MyHeritage кладе в NOTE фрагменти HTML з голими переносами рядка; за
    GEDCOM 5.5.1 кожен рядок починається з рівня й тегу, і строгий парсер на
    такому падає. Лікується лише рядок одразу після NOTE/CONC/CONT — усе інше
    лишається помилкою файлу, а не нашою здогадкою.
    """
    lines = data.split(b"\n")
    fixes = 0
    for i, line in enumerate(lines):
        if not line.strip(b"\r") or _LEVEL.match(line) or line.startswith(b"\xef\xbb\xbf"):
            continue
        if i > 0 and _is_note_context(lines[i - 1]):
            lines[i] = _CONC + line
            fixes += 1
    return b"\n".join(lines), fixes


def _is_note_context(line: bytes) -> bool:
    if not _LEVEL.match(line):
        return False
    head = line.split(b" ", 2)
    return len(head) >= 2 and head[1] in (b"NOTE", b"CONC", b"CONT")


# ── імпорт ───────────────────────────────────────────────────────────────────
def canon_is_empty(canonical: Path) -> bool:
    return not any((canonical / k).glob("*.md")
                   for k in ("persons", "families") if (canonical / k).is_dir())


def import_file(root: Path, ged_path: Path, opts: Options | None = None, *,
                dry_run: bool = False) -> ImportReport:
    try:
        from ged4py.parser import GedcomReader
    except ImportError as exc:
        raise GedcomError("для імпорту потрібен ged4py: pip install nyshporka[gedcom]") from exc

    opts = opts or Options()
    canonical = root / "data" / "canonical"
    if not ged_path.is_file():
        raise GedcomError(f"файлу немає: {ged_path}")
    if not canon_is_empty(canonical):
        raise GedcomError(
            "канон у просторі вже є — імпорт лише засіває порожній. Злиття з "
            "наявним не робиться: воно перетерло б правлене або наплодило двійників")

    data, fixes = fix_orphan_continuations(ged_path.read_bytes())
    try:
        with GedcomReader(io.BytesIO(data)) as g:
            indi = list(g.records0("INDI"))
            fams = list(g.records0("FAM"))
    except Exception as exc:
        raise GedcomError(f"GEDCOM не читається: {type(exc).__name__}: {exc}") from exc
    if not indi:
        raise GedcomError("у файлі жодної особи (записів INDI) — це точно GEDCOM дерева?")

    dest = root / "data" / "source" / "gedcom" / ged_path.name
    source = Source(
        id=opts.source_id, type="gedcom",
        title=opts.source_title or f"GEDCOM-експорт дерева ({ged_path.name})",
        authority=opts.authority or None,
        raw_path=dest.relative_to(root).as_posix(),
        fetched=datetime.fromtimestamp(ged_path.stat().st_mtime, tz=UTC),
        notes="Засіяно командою `nysh canon import`. Дерево з іншої програми — "
              "переказ джерел, а не джерело: факти звідси чекають звірки.",
    )
    ctx = _Ctx(
        person_map={r.xref_id: person_id(i + 1) for i, r in enumerate(indi)},
        family_map={r.xref_id: family_id(i + 1) for i, r in enumerate(fams)},
        places=_collect_places([*indi, *fams]),
        citation=Citation(source_id=source.id, confidence="indirect", accessed=date.today(),
                          note=f"Перенесено з GEDCOM ({ged_path.name})."),
        opts=opts,
    )
    persons = [_person(r, ctx) for r in indi]
    families = [_family(r, ctx) for r in fams]

    rep = ImportReport(persons=len(persons), families=len(families),
                       places=len(ctx.places), private=sum(p.private for p in persons),
                       preprocess_fixes=fixes, source_id=source.id,
                       copied_to=dest.relative_to(root).as_posix())
    if dry_run:
        return rep

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(ged_path, dest)
    for kind, items in (("persons", persons), ("families", families),
                        ("places", list(ctx.places.values())), ("sources", [source])):
        for e in items:
            write_entity(canonical / kind / f"{e.id}.md", e)
    rep.written = True
    return rep


def _collect_places(records: Iterable[Any]) -> dict[str, Place]:
    names: list[str] = []
    for record in records:
        for sub in record.sub_records:
            for sub2 in sub.sub_records:
                if sub2.tag == "PLAC" and isinstance(sub2.value, str) and sub2.value \
                        and sub2.value not in names:
                    names.append(sub2.value)
    out: dict[str, Place] = {}
    for i, raw in enumerate(names):
        # GEDCOM PLAC іде від найвужчого (село) до країни; `admin` канону — навпаки.
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        name = parts[0] if parts else raw
        out[raw] = Place(id=place_id(i + 1), name=name,
                         name_variants={_guess_lang(name): name}, admin=list(reversed(parts)))
    return out


def _sub(record: Any, tag: str) -> Any:
    for s in record.sub_records:
        if s.tag == tag:
            return s.value
    return None


def _status(has_data: bool, opts: Options) -> FactStatus:
    return "confirmed" if (has_data and opts.trust_tree) else "hypothesis"


def _event(kind: FactType, sub: Any, ctx: _Ctx) -> Fact:
    dv = _sub(sub, "DATE")
    raw_place = _sub(sub, "PLAC")
    when = _convert_date(dv) if dv is not None else None
    where = ctx.places[raw_place].id if isinstance(raw_place, str) and raw_place in ctx.places else None
    return Fact(type=kind, date=when, place_id=where, citations=[ctx.citation],
                status=_status(bool(when or where), ctx.opts))


def _attr(kind: FactType, sub: Any, ctx: _Ctx) -> Fact:
    value = sub.value if isinstance(sub.value, str) and sub.value else None
    if kind == "other":
        subtype = _sub(sub, "TYPE")
        if isinstance(subtype, str) and subtype:
            value = f"{subtype}: {value}" if value else subtype
    dv = _sub(sub, "DATE")
    return Fact(type=kind, value=value, date=_convert_date(dv) if dv is not None else None,
                citations=[ctx.citation], status=_status(bool(value), ctx.opts))


def _aliases(record: Any, ctx: _Ctx) -> list[str]:
    rin = _sub(record, "RIN")
    return [f"{ctx.opts.alias_prefix}:{rin}"] if isinstance(rin, str) and rin else []


def _ref(xref: Any, table: dict[str, str], ctx: _Ctx) -> str | None:
    """Посилання на запис, якого у файлі немає, — пропуск, а не падіння імпорту."""
    if not isinstance(xref, str) or not xref:
        return None
    if xref not in table:
        ctx.skipped_refs.append(xref)
        return None
    return table[xref]


def _person(record: Any, ctx: _Ctx) -> Person:
    facts: list[Fact] = []
    media: list[MediaRef] = []
    spouse_families: list[str] = []
    for sub in record.sub_records:
        if sub.tag in _PERSON_EVENTS:
            facts.append(_event(_PERSON_EVENTS[sub.tag], sub, ctx))
        elif sub.tag in _PERSON_ATTRS:
            facts.append(_attr(_PERSON_ATTRS[sub.tag], sub, ctx))
        elif sub.tag == "OBJE":
            ref = _media(sub)
            if ref is not None:
                media.append(ref)
        elif sub.tag == "FAMS":
            fid = _ref(sub.value, ctx.family_map, ctx)
            if fid:
                spouse_families.append(fid)
    sex = _sub(record, "SEX")
    return Person(
        id=ctx.person_map[record.xref_id],
        names=_names(record),
        sex=sex if sex in ("M", "F") else "U",
        private=_is_private(facts, ctx.opts.private_born_after),
        parent_family=_ref(_sub(record, "FAMC"), ctx.family_map, ctx),
        spouse_families=spouse_families,
        aliases=_aliases(record, ctx),
        facts=facts,
        media=media,
    )


def _family(record: Any, ctx: _Ctx) -> Family:
    facts = [_event(_FAMILY_EVENTS[s.tag], s, ctx)
             for s in record.sub_records if s.tag in _FAMILY_EVENTS]
    children = [c for c in (_ref(s.value, ctx.person_map, ctx)
                            for s in record.sub_records if s.tag == "CHIL") if c]
    return Family(
        id=ctx.family_map[record.xref_id],
        husband=_ref(_sub(record, "HUSB"), ctx.person_map, ctx),
        wife=_ref(_sub(record, "WIFE"), ctx.person_map, ctx),
        children=children,
        facts=facts,
        aliases=_aliases(record, ctx),
    )


def _names(record: Any) -> list[NameVariant]:
    names: list[NameVariant] = []
    for sub in record.sub_records:
        if sub.tag != "NAME":
            continue
        given, surname = _split_name(sub)
        form = " ".join(p for p in (given, surname) if p) or "—"
        names.append(NameVariant(form=form, lang=_guess_lang(form), primary=not names,
                                 given=given, surname=surname))
    return names or [NameVariant(form="—", primary=True)]


def _split_name(sub: Any) -> tuple[str | None, str | None]:
    """(ім'я, прізвище) з NAME. Дочірні GIVN/SURN надійніші за кортеж значення."""
    given: str | None = None
    surname: str | None = None
    val = sub.value
    if isinstance(val, tuple) and val:
        given = val[0] or None
        surname = val[1] if len(val) > 1 and val[1] else None
    for s in sub.sub_records:
        if s.tag == "GIVN" and isinstance(s.value, str) and s.value:
            given = s.value
        elif s.tag == "SURN" and isinstance(s.value, str) and s.value:
            surname = s.value
    return given, surname


def _media(sub: Any) -> MediaRef | None:
    url = caption = None
    for s in sub.sub_records:
        if s.tag == "FILE" and isinstance(s.value, str):
            url = s.value
        elif s.tag == "TITL" and isinstance(s.value, str):
            caption = s.value
    return MediaRef(url=url, caption=caption, type="photo") if url else None


def _is_private(facts: Iterable[Fact], born_after: int) -> bool:
    """Живий, поки не доведено протилежне: без смерті й без року народження — теж."""
    birth_year: int | None = None
    for f in facts:
        if f.type == "death":
            return False
        if f.type == "birth" and f.date and f.date.value[:4].isdigit():
            birth_year = int(f.date.value[:4])
    return birth_year is None or birth_year >= born_after


def _convert_date(dv: Any) -> GedDate | None:
    """ged4py DateValue → GedDate."""
    cls = type(dv).__name__

    def value(cal: Any) -> tuple[str, str]:
        y = cal.year
        m = _MONTHS.get(str(cal.month).upper()) if cal.month else None
        d = cal.day
        if y and m and d:
            return f"{y:04d}-{m:02d}-{d:02d}", "day"
        if y and m:
            return f"{y:04d}-{m:02d}", "month"
        return (f"{y:04d}", "year") if y else (str(cal), "year")

    simple = {"DateValueSimple": "exact", "DateValueAbout": "about",
              "DateValueBefore": "before", "DateValueAfter": "after",
              "DateValueEstimated": "estimated", "DateValueInterpreted": "estimated",
              "DateValueCalculated": "calculated"}
    if cls in simple:
        v, p = value(dv.date)
        return GedDate(value=v, precision=p, qualifier=simple[cls])  # type: ignore[arg-type]
    if cls in ("DateValueRange", "DateValuePeriod"):
        d1 = getattr(dv, "date1", None) or getattr(dv, "from_date", None)
        d2 = getattr(dv, "date2", None) or getattr(dv, "to_date", None)
        if d1 and d2:
            v1, p = value(d1)
            v2, _ = value(d2)
            return GedDate(value=v1, precision=p, qualifier="between",  # type: ignore[arg-type]
                           range_end=v2)
        if d1:
            v, p = value(d1)
            return GedDate(value=v, precision=p, qualifier="after")  # type: ignore[arg-type]
        if d2:
            v, p = value(d2)
            return GedDate(value=v, precision=p, qualifier="before")  # type: ignore[arg-type]
    return None


def _guess_lang(s: str) -> LangCode:
    """Грубо: ї/є/і/ґ → uk; інша кирилиця → ru; латиниця → en."""
    if any(ch in s for ch in "їєіІЇЄҐґ"):
        return "uk"
    if any("Ѐ" <= ch <= "ӿ" for ch in s):
        return "ru"
    return "en"
