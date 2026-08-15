"""Reindex: canonical/ → derived/nyshporka.sqlite + graph.json + places.geojson.

Sync (через stdlib `sqlite3`), бо це batch-операція без HTTP. Async aiosqlite
лишаємо для fetcher'ів, де є реальна потреба паралелити з httpx.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from nyshporka.models import (
    Citation,
    Fact,
    Family,
    Person,
    Place,
    RegionRegistry,
    Source,
    load_regions,
)
from nyshporka.storage.files import read_family, read_person, read_place, read_source

# `build_tree_graph` живе в окремому модулі (нова multi-pane візуалізація).
# Імпорт — у функції `reindex` нижче (відкладений, бо tree_graph.py імпортує
# звідси приватні `_compute_lived_all` тощо — звичайний top-level імпорт дав би
# циклічну залежність).

_SCHEMA = """
CREATE TABLE persons (
    id TEXT PRIMARY KEY,
    primary_name TEXT NOT NULL,
    sex TEXT NOT NULL,
    private INTEGER NOT NULL,
    parent_family TEXT,
    hypothetical_parent_family TEXT,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE name_variants (
    person_id TEXT NOT NULL REFERENCES persons(id),
    form TEXT NOT NULL,
    lang TEXT NOT NULL,
    is_primary INTEGER NOT NULL,
    given TEXT,
    surname TEXT
);
CREATE INDEX idx_name_variants_person ON name_variants(person_id);
CREATE INDEX idx_name_variants_surname ON name_variants(surname);

CREATE TABLE families (
    id TEXT PRIMARY KEY,
    husband TEXT REFERENCES persons(id),
    wife TEXT REFERENCES persons(id),
    hypothetical_husband TEXT REFERENCES persons(id),
    hypothetical_wife TEXT REFERENCES persons(id),
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE family_children (
    family_id TEXT NOT NULL REFERENCES families(id),
    person_id TEXT NOT NULL REFERENCES persons(id),
    hypothetical INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (family_id, person_id)
);
CREATE INDEX idx_family_children_person ON family_children(person_id);

CREATE TABLE spouse_links (
    person_id TEXT NOT NULL REFERENCES persons(id),
    family_id TEXT NOT NULL REFERENCES families(id),
    hypothetical INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (person_id, family_id)
);
CREATE INDEX idx_spouse_links_family ON spouse_links(family_id);

CREATE TABLE places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    osm_id INTEGER,
    lat REAL,
    lon REAL,
    admin_json TEXT NOT NULL,
    period_notes TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    authority TEXT,
    url TEXT,
    repository_ref TEXT,
    raw_path TEXT,
    fetched TEXT,
    coverage_json TEXT,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT REFERENCES persons(id),
    family_id TEXT REFERENCES families(id),
    type TEXT NOT NULL,
    date_value TEXT,
    date_precision TEXT,
    date_qualifier TEXT,
    date_range_end TEXT,
    place_id TEXT REFERENCES places(id),
    value TEXT,
    status TEXT NOT NULL
);
CREATE INDEX idx_facts_person ON facts(person_id);
CREATE INDEX idx_facts_family ON facts(family_id);
CREATE INDEX idx_facts_type ON facts(type);

CREATE TABLE citations (
    fact_id INTEGER NOT NULL REFERENCES facts(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    page TEXT,
    quote TEXT,
    confidence TEXT NOT NULL,
    accessed TEXT NOT NULL,
    note TEXT
);
CREATE INDEX idx_citations_fact ON citations(fact_id);
CREATE INDEX idx_citations_source ON citations(source_id);

CREATE TABLE media (
    person_id TEXT NOT NULL REFERENCES persons(id),
    sha256 TEXT,
    path TEXT,
    url TEXT,
    caption TEXT,
    type TEXT NOT NULL
);
CREATE INDEX idx_media_person ON media(person_id);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class ReindexReport:
    persons: int = 0
    families: int = 0
    places: int = 0
    sources: int = 0
    facts: int = 0
    sqlite_path: Path | None = None
    graph_path: Path | None = None
    geojson_path: Path | None = None
    tree_path: Path | None = None
    coverage_path: Path | None = None


def reindex(project_root: Path) -> ReindexReport:
    canonical = project_root / "data" / "canonical"
    derived = project_root / "data" / "derived"
    derived.mkdir(parents=True, exist_ok=True)

    persons = sorted(
        (read_person(p) for p in (canonical / "persons").glob("*.md")),
        key=lambda x: x.id,
    )
    families = sorted(
        (read_family(p) for p in (canonical / "families").glob("*.md")),
        key=lambda x: x.id,
    )
    places = sorted(
        (read_place(p) for p in (canonical / "places").glob("*.md")),
        key=lambda x: x.id,
    )
    sources = sorted(
        (read_source(p) for p in (canonical / "sources").glob("*.md")),
        key=lambda x: x.id,
    )

    sqlite_path = derived / "nyshporka.sqlite"
    if sqlite_path.exists():
        sqlite_path.unlink()

    facts_count = 0
    with sqlite3.connect(sqlite_path) as conn:
        conn.executescript(_SCHEMA)
        facts_count = _write_sqlite(conn, persons, families, places, sources)
        conn.commit()

    graph_path = derived / "graph.json"
    graph_path.write_text(
        json.dumps(_build_graph(persons, families), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Нова tree.json для multi-pane візуалізації (sugiyama-DAG, фото, generation).
    from nyshporka.storage.tree_graph import build_tree_graph

    tree_path = derived / "tree.json"
    tree_path.write_text(
        json.dumps(build_tree_graph(persons, families), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    geojson_path = derived / "places.geojson"
    lived_map = _compute_lived_all(persons, families)
    geojson_path.write_text(
        json.dumps(
            _build_geojson(places, persons, lived_map),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    registry = load_regions(project_root)
    coverage_path = derived / "coverage.json"
    coverage_path.write_text(
        json.dumps(_build_coverage(sources, registry), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return ReindexReport(
        persons=len(persons),
        families=len(families),
        places=len(places),
        sources=len(sources),
        facts=facts_count,
        sqlite_path=sqlite_path,
        graph_path=graph_path,
        geojson_path=geojson_path,
        tree_path=tree_path,
        coverage_path=coverage_path,
    )


# ----- Карта покриття джерел --------------------------------------------------

_COVERAGE_STATUSES = [
    {"id": "negative", "label": "Наших немає", "rank": 0},
    {"id": "known", "label": "У довідниках", "rank": 1},
    {"id": "ordered", "label": "Замовлено", "rank": 2},
    {"id": "downloaded", "label": "Отримано", "rank": 3},
    {"id": "decoded", "label": "Прочитано", "rank": 4},
    {"id": "exhausted", "label": "Відпрацьовано", "rank": 5},
]

_COVERAGE_RECORD_TYPES = [
    {"id": "birth", "label": "Народження"},
    {"id": "marriage", "label": "Шлюби"},
    {"id": "death", "label": "Смерті"},
    {"id": "confession", "label": "Сповідні"},
    {"id": "revision", "label": "Ревізії"},
    {"id": "gazette", "label": "Єпарх. відомості"},
    {"id": "clergy_list", "label": "Клірові"},
    {"id": "finding_aid", "label": "Описи/каталоги"},
    {"id": "other", "label": "Інше"},
]


def _build_coverage(sources: list[Source], registry: RegionRegistry) -> dict[str, Any]:
    """coverage.json: реєстр регіонів + сирі спани джерел (rollup рахує клієнт)."""
    valid_codes = registry.codes()
    bad: list[str] = []
    out_sources = []
    for s in sources:
        if not s.coverage:
            continue
        for span in s.coverage:
            if span.region not in valid_codes:
                bad.append(f"{s.id}: невідомий region-код '{span.region}'")
        out_sources.append(
            {
                "id": s.id,
                "title": s.title,
                "type": s.type,
                "spans": [span.model_dump(mode="json") for span in s.coverage],
            }
        )
    if bad:
        raise ValueError(
            "Coverage-спани посилаються на коди, відсутні у data/canonical/regions.yml:\n"
            + "\n".join(bad)
        )
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "year_min": registry.year_min,
        "year_max": registry.year_max,
        "statuses": _COVERAGE_STATUSES,
        "record_types": _COVERAGE_RECORD_TYPES,
        "governorates": [g.model_dump(mode="json") for g in registry.governorates],
        "sources": out_sources,
    }


# ----- SQLite ----------------------------------------------------------------


def _write_sqlite(
    conn: sqlite3.Connection,
    persons: list[Person],
    families: list[Family],
    places: list[Place],
    sources: list[Source],
) -> int:
    cur = conn.cursor()

    # sources перші — на них посилається foreign key citations.source_id.
    for s in sources:
        cur.execute(
            "INSERT INTO sources "
            "(id, type, title, authority, url, repository_ref, raw_path, fetched, coverage_json, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                s.id,
                s.type,
                s.title,
                s.authority,
                s.url,
                s.repository_ref,
                s.raw_path,
                s.fetched.isoformat() if s.fetched else None,
                json.dumps(
                    [span.model_dump(mode="json") for span in s.coverage],
                    ensure_ascii=False,
                )
                if s.coverage
                else None,
                s.notes,
            ),
        )

    for pl in places:
        cur.execute(
            "INSERT INTO places (id, name, osm_id, lat, lon, admin_json, period_notes, notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                pl.id,
                pl.name,
                pl.osm_id,
                pl.coords[0] if pl.coords else None,
                pl.coords[1] if pl.coords else None,
                json.dumps(pl.admin, ensure_ascii=False),
                pl.period_notes,
                pl.notes,
            ),
        )

    for p in persons:
        cur.execute(
            "INSERT INTO persons "
            "(id, primary_name, sex, private, parent_family, hypothetical_parent_family, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                p.id,
                p.primary_name,
                p.sex,
                int(p.private),
                p.parent_family,
                p.hypothetical_parent_family,
                p.notes,
            ),
        )
        for n in p.names:
            cur.execute(
                "INSERT INTO name_variants (person_id, form, lang, is_primary, given, surname) "
                "VALUES (?,?,?,?,?,?)",
                (p.id, n.form, n.lang, int(n.primary), n.given, n.surname),
            )
        for m in p.media:
            cur.execute(
                "INSERT INTO media (person_id, sha256, path, url, caption, type) "
                "VALUES (?,?,?,?,?,?)",
                (p.id, m.sha256, m.path, m.url, m.caption, m.type),
            )

    for f in families:
        cur.execute(
            "INSERT INTO families "
            "(id, husband, wife, hypothetical_husband, hypothetical_wife, notes) "
            "VALUES (?,?,?,?,?,?)",
            (
                f.id,
                f.husband,
                f.wife,
                f.hypothetical_husband,
                f.hypothetical_wife,
                f.notes,
            ),
        )
        for child in f.children:
            cur.execute(
                "INSERT INTO family_children (family_id, person_id, hypothetical) "
                "VALUES (?,?,0)",
                (f.id, child),
            )
        for child in f.hypothetical_children:
            if child in f.children:
                continue  # уже у підтверджених
            cur.execute(
                "INSERT INTO family_children (family_id, person_id, hypothetical) "
                "VALUES (?,?,1)",
                (f.id, child),
            )

    for p in persons:
        for fid in p.spouse_families:
            cur.execute(
                "INSERT INTO spouse_links (person_id, family_id, hypothetical) "
                "VALUES (?,?,0)",
                (p.id, fid),
            )
        for fid in p.hypothetical_spouse_families:
            if fid in p.spouse_families:
                continue
            cur.execute(
                "INSERT INTO spouse_links (person_id, family_id, hypothetical) "
                "VALUES (?,?,1)",
                (p.id, fid),
            )

    facts_count = 0
    # `fid` вище — це ID РОДИНИ (рядок), а тут rowid вставленого факту (число).
    # Різні сутності під одним іменем в одній функції; окреме ім'я коштує нічого.
    for p in persons:
        for fact in p.facts:
            fact_row = _insert_fact(cur, fact, person_id=p.id)
            _insert_citations(cur, fact_row, fact.citations)
            facts_count += 1
    for fam in families:
        for fact in fam.facts:
            fact_row = _insert_fact(cur, fact, family_id=fam.id)
            _insert_citations(cur, fact_row, fact.citations)
            facts_count += 1

    return facts_count


def _insert_fact(cur: sqlite3.Cursor, fact: Fact, *, person_id: str | None = None,
                 family_id: str | None = None) -> int:
    date = fact.date
    cur.execute(
        "INSERT INTO facts ("
        "person_id, family_id, type, date_value, date_precision, date_qualifier, "
        "date_range_end, place_id, value, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            person_id,
            family_id,
            fact.type,
            date.value if date else None,
            date.precision if date else None,
            date.qualifier if date else None,
            date.range_end if date else None,
            fact.place_id,
            fact.value,
            fact.status,
        ),
    )
    return cur.lastrowid  # type: ignore[return-value]


def _insert_citations(cur: sqlite3.Cursor, fact_id: int,
                      citations: list[Citation]) -> None:
    for c in citations:
        cur.execute(
            "INSERT INTO citations "
            "(fact_id, source_id, page, quote, confidence, accessed, note) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                fact_id,
                c.source_id,
                c.page,
                c.quote,
                c.confidence,
                c.accessed.isoformat(),
                c.note,
            ),
        )


# ----- graph.json (для d3 force-directed family graph) -----------------------

_CONF_WEIGHT = {
    "direct": 4,
    "indirect": 3,
    "circumstantial": 2,
    "speculative": 1,
    "negative": 0,
}


def _weakest_confidence(confs: Sequence[str]) -> str | None:
    """Найслабша confidence зі списку (за _CONF_WEIGHT). None якщо порожньо."""
    if not confs:
        return None
    return str(min(confs, key=lambda c: _CONF_WEIGHT.get(c, 99)))


def _year_of(fact_type: str, facts: list[Any]) -> str | None:
    for f in facts:
        if f.type == fact_type and f.date and f.date.value[:4].isdigit():
            return str(f.date.value[:4])
    return None


def _decade_of(year: str | None) -> str | None:
    if not year or not year.isdigit():
        return None
    return f"{int(year) // 10 * 10}s"


def _person_confidences(p: Person) -> list[str]:
    return [c.confidence for f in p.facts for c in f.citations]


def _has_disputed(facts: list[Any]) -> bool:
    return any(f.status == "disputed" for f in facts)


def _marriage_fact(family: Family) -> Fact | None:
    for f in family.facts:
        if f.type == "marriage":
            return f
    return None


def _spouse_attrs(marriage_fact: Fact | None) -> dict[str, Any]:
    """status + confidence для spouse-ребра.

    `Family.husband + wife` — структурне твердження «вони подружжя» (з GEDCOM
    або ручного запису). `marriage.status: hypothesis` зазвичай означає лише
    «дата/місце шлюбу як події невідомі», не «ми сумніваємось, що вони
    подружжя». Тому пунктирним spouse-link робимо тільки коли:
      - marriage fact явно `disputed` (= сумнів у самій парі)
      - або найслабша confidence цитат — `speculative`
        (= спекулятивне виведення пари з непрямих джерел)
    В інших випадках — `confirmed`.
    """
    if marriage_fact is None:
        return {"status": "confirmed", "confidence": None}
    confs = [c.confidence for c in marriage_fact.citations]
    weakest = _weakest_confidence(confs)
    if marriage_fact.status == "disputed":
        status = "disputed"
    elif weakest == "speculative":
        status = "hypothesis"
    else:
        status = "confirmed"
    return {"status": status, "confidence": weakest}


def _parent_attrs(marriage_fact: Fact | None) -> dict[str, Any]:
    """status + confidence для parent-ребра.

    Структурне твердження «X — дитина цих батьків» (з Family.children)
    лишається confirmed незалежно від статусу шлюбу. Hypothesis на marriage
    означає лише «дата/місце шлюбу нам невідомі», а не «батьки під сумнівом».

    Якщо ж сам marriage fact позначений disputed (рідкісний випадок — означає
    «ми не впевнені що це справді ці батьки»), то і parent-link disputed.
    Confidence передається з marriage fact для товщини лінії.
    """
    if marriage_fact is None:
        return {"status": "confirmed", "confidence": None}
    confs = [c.confidence for c in marriage_fact.citations]
    status = "disputed" if marriage_fact.status == "disputed" else "confirmed"
    return {"status": status, "confidence": _weakest_confidence(confs)}


def _connected_components(
    persons: list[Person], families: list[Family]
) -> dict[str, str]:
    """Union-find по parent ∪ spouse зв'язках. Повертає person_id → branch_id (корінь)."""
    parent_of: dict[str, str] = {p.id: p.id for p in persons}

    def find(x: str) -> str:
        while parent_of[x] != x:
            parent_of[x] = parent_of[parent_of[x]]
            x = parent_of[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent_of[ra] = rb

    person_ids = {p.id for p in persons}
    for fam in families:
        members = [
            m
            for m in (
                fam.husband,
                fam.wife,
                fam.hypothetical_husband,
                fam.hypothetical_wife,
                *fam.children,
                *fam.hypothetical_children,
            )
            if m in person_ids
        ]
        for i in range(1, len(members)):
            union(members[0], members[i])

    # Для кожного компонента — обрати «корінь» (найстарша особа без батьків,
    # або найрання дата народження, або найменший id як fallback).
    components: dict[str, list[Person]] = {}
    for p in persons:
        root = find(p.id)
        components.setdefault(root, []).append(p)

    branch_of: dict[str, str] = {}
    # Ім'я `members` вище вже зайняте списком ІДЕНТИФІКАТОРІВ, а тут це список
    # осіб. Одне ім'я на дві різні речі в одній функції — саме те, через що
    # перевіряч не міг довести жодного доступу до поля, і саме те, що людина
    # читає неправильно.
    for people in components.values():
        rootless = [p for p in people if not p.parent_family]
        candidates = rootless or people

        def sort_key(p: Person) -> tuple[str, str]:
            birth = _year_of("birth", p.facts) or "9999"
            return (birth, p.id)

        chosen = min(candidates, key=sort_key)
        for m in people:
            branch_of[m.id] = chosen.id

    return branch_of


_EVENT_FACT_TYPES = {"emigration", "military", "education", "occupation", "baptism"}
_EVENT_LABELS = {
    "emigration": "Еміграція",
    "military": "Військова служба",
    "education": "Освіта",
    "occupation": "Посада",
    "baptism": "Хрещення",
    "death": "Смерть",
    "marriage": "Шлюб",
}


def _build_events(persons: list[Person], families: list[Family]) -> list[dict[str, Any]]:
    """Зібрати ключові події роду з фактів — для timeline під графом."""
    events: list[dict[str, Any]] = []
    for p in persons:
        for f in p.facts:
            if f.type not in _EVENT_FACT_TYPES and f.status != "disputed":
                continue
            year = f.date.value[:4] if f.date and f.date.value[:4].isdigit() else None
            if not year:
                continue
            label_kind = _EVENT_LABELS.get(f.type, f.type)
            label = f"{label_kind} — {p.primary_name}"
            if f.value:
                label += f" ({f.value})"
            events.append(
                {
                    "year": int(year),
                    "label": label,
                    "person_id": p.id,
                    "fact_type": f.type,
                    "status": f.status,
                }
            )
    for fam in families:
        for f in fam.facts:
            if f.type != "marriage" or f.status == "confirmed":
                continue
            year = f.date.value[:4] if f.date and f.date.value[:4].isdigit() else None
            if not year:
                continue
            events.append(
                {
                    "year": int(year),
                    "label": f"Шлюб (гіпотеза) — {fam.id}",
                    "person_id": fam.husband or fam.wife,
                    "fact_type": "marriage",
                    "status": f.status,
                }
            )
    events.sort(key=lambda e: e["year"])
    return events


_DATED_LIFE_FACTS = {
    "occupation", "education", "residence", "religion",
    "baptism", "burial", "military", "emigration", "nationality",
}
_PARENT_AGE_MIN = 15
_PARENT_AGE_MAX = 50
_TYPICAL_LIFESPAN = 80
_MAX_LIFESPAN = 90
# Clamp обчислених lived_to у майбутньому: ніхто не житиме до 2229.
# Для приватних (можуть бути живі) — допускаємо до сьогодні + 80.
# Для неприватних — до сьогодні (помер хоча б).
_CURRENT_YEAR = datetime.now().year
_MAX_FUTURE_PRIVATE = _CURRENT_YEAR + 80
_MAX_FUTURE_PUBLIC = _CURRENT_YEAR


def _exact_year_with_q(fact_type: str, facts: list[Any]) -> tuple[int | None, str | None]:
    """Перший факт типу + його qualifier ('exact'/'about'/...)."""
    for f in facts:
        if f.type == fact_type and f.date and f.date.value[:4].isdigit():
            return int(f.date.value[:4]), (f.date.qualifier or "exact")
    return None, None


def _life_fact_year_range(facts: list[Any]) -> tuple[int | None, int | None]:
    """Min/max рік серед датованих life-фактів (occupation, education...).
    Враховує range_end, ігнорує birth/death."""
    years: list[int] = []
    for f in facts:
        if f.type not in _DATED_LIFE_FACTS:
            continue
        if not f.date:
            continue
        v = f.date.value[:4]
        if v.isdigit():
            years.append(int(v))
        if f.date.range_end:
            r = f.date.range_end[:4]
            if r.isdigit():
                years.append(int(r))
    if not years:
        return None, None
    return min(years), max(years)


def _compute_own_lived(p: Person) -> dict[str, Any]:
    """lived_from/to з власних даних особи (без родичів).
    Повертає {'from': int|None, 'to': int|None, 'certainty': str, 'method': str}."""
    if p.floruit:
        return {
            "from": p.floruit.from_year,
            "to": p.floruit.to_year,
            "certainty": "approximate",
            "method": "floruit",
        }

    birth, bq = _exact_year_with_q("birth", p.facts)
    death, dq = _exact_year_with_q("death", p.facts)

    if birth is not None and death is not None:
        cert = "exact" if (bq == "exact" and dq == "exact") else "approximate"
        return {"from": birth, "to": death, "certainty": cert, "method": "dates"}
    if birth is not None:
        return {
            "from": birth,
            "to": birth + _MAX_LIFESPAN,
            "certainty": "approximate",
            "method": "dates",
        }
    if death is not None:
        return {
            "from": death - _MAX_LIFESPAN,
            "to": death,
            "certainty": "approximate",
            "method": "dates",
        }

    earliest, latest = _life_fact_year_range(p.facts)
    if earliest is not None and latest is not None:
        # earliest згадка зазвичай у дорослому віці — віднімаємо ~20р до народження.
        # latest згадка — типово ще ~30р до смерті.
        return {
            "from": earliest - 20,
            "to": latest + 30,
            "certainty": "inferred",
            "method": "facts",
        }

    return {"from": None, "to": None, "certainty": "unknown", "method": "none"}


def _build_family_graph_index(
    families: list[Family],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """parents_of[child_id] = {parent_ids}, children_of[parent_id] = {child_ids},
    spouses_of[person_id] = {spouse_ids}.
    Включає гіпотетичні зв'язки — для оцінки lived достатньо м'якого зв'язку."""
    parents_of: dict[str, set[str]] = {}
    children_of: dict[str, set[str]] = {}
    spouses_of: dict[str, set[str]] = {}
    for fam in families:
        parent_ids: list[str] = []
        if fam.husband:
            parent_ids.append(fam.husband)
        if fam.wife:
            parent_ids.append(fam.wife)
        if (
            fam.hypothetical_husband
            and fam.hypothetical_husband != fam.husband
        ):
            parent_ids.append(fam.hypothetical_husband)
        if fam.hypothetical_wife and fam.hypothetical_wife != fam.wife:
            parent_ids.append(fam.hypothetical_wife)
        child_ids: list[str] = list(fam.children)
        for c in fam.hypothetical_children:
            if c not in fam.children:
                child_ids.append(c)
        for c in child_ids:
            parents_of.setdefault(c, set()).update(parent_ids)
        for par in parent_ids:
            children_of.setdefault(par, set()).update(child_ids)
        # spouse-зв'язки (для оцінки дат через подружжя):
        for a in parent_ids:
            for b in parent_ids:
                if a != b:
                    spouses_of.setdefault(a, set()).add(b)
    return parents_of, children_of, spouses_of


def _compute_lived_all(
    persons: list[Person], families: list[Family]
) -> dict[str, dict[str, Any]]:
    """Повна карта person_id → {from, to, certainty, method}.
    Pass 1: власні факти. Pass 2+: поширення через generation gap і spouse."""
    lived: dict[str, dict[str, Any]] = {p.id: _compute_own_lived(p) for p in persons}
    parents_of, children_of, spouses_of = _build_family_graph_index(families)
    by_id = {p.id: p for p in persons}

    # Кілька проходів для зведення фіксованої точки. У реальній базі вистачає 2-3.
    for _ in range(4):
        changed = False
        for p in persons:
            if lived[p.id]["certainty"] != "unknown":
                continue
            est_froms: list[int] = []
            est_tos: list[int] = []
            for cid in children_of.get(p.id, set()):
                cl = lived.get(cid)
                if not cl or cl["from"] is None:
                    continue
                # Як батько: lived_from = child.from - max_gap, lived_to = child.from + типове залишкове життя.
                est_froms.append(cl["from"] - _PARENT_AGE_MAX)
                est_tos.append(cl["from"] - _PARENT_AGE_MIN + _TYPICAL_LIFESPAN)
            for parid in parents_of.get(p.id, set()):
                pl = lived.get(parid)
                if not pl or pl["from"] is None:
                    continue
                # Як дитина: lived_from = parent.from + min_gap; lived_to = parent.to + lifespan (або parent.from + max_gap + lifespan).
                est_froms.append(pl["from"] + _PARENT_AGE_MIN)
                if pl["to"] is not None:
                    est_tos.append(pl["to"] + _TYPICAL_LIFESPAN)
                else:
                    est_tos.append(pl["from"] + _PARENT_AGE_MAX + _TYPICAL_LIFESPAN)
            # Spouse: подружжя зазвичай у межах ±15 років одне від одного.
            for spid in spouses_of.get(p.id, set()):
                sl = lived.get(spid)
                if not sl or sl["from"] is None:
                    continue
                est_froms.append(sl["from"] - 15)
                if sl["to"] is not None:
                    est_tos.append(sl["to"] + 15)
                else:
                    est_tos.append(sl["from"] + 15 + _TYPICAL_LIFESPAN)
            if not est_froms:
                continue
            # Беремо найширший union — щоб не відрізати реальні дати.
            lived[p.id] = {
                "from": min(est_froms),
                "to": max(est_tos) if est_tos else None,
                "certainty": "inferred",
                "method": "generation",
            }
            changed = True
        if not changed:
            break

    # Clamp lived_to у далекому майбутньому — generation/spouse pass може дати 2229
    # коли особа inferred-через-онуків. Для приватних залишаємо запас (можуть бути живі).
    for pid, info in lived.items():
        if info["to"] is None or info["certainty"] == "exact":
            continue
        person = by_id.get(pid)
        max_to = _MAX_FUTURE_PRIVATE if (person and person.private) else _MAX_FUTURE_PUBLIC
        if info["to"] > max_to:
            info["to"] = max_to

    return lived


def _build_graph(persons: list[Person], families: list[Family]) -> dict[str, Any]:
    branch_of = _connected_components(persons, families)
    lived_map = _compute_lived_all(persons, families)

    nodes = []
    for p in persons:
        birth = _year_of("birth", p.facts)
        death = _year_of("death", p.facts)
        lived = lived_map[p.id]
        nodes.append(
            {
                "id": p.id,
                "name": p.primary_name,
                "sex": p.sex,
                "private": p.private,
                "birth": birth,
                "death": death,
                "birth_decade": _decade_of(birth),
                "death_decade": _decade_of(death),
                "lived_from": lived["from"],
                "lived_to": lived["to"],
                "lived_certainty": lived["certainty"],
                "lived_method": lived["method"],
                "branch_id": branch_of.get(p.id, p.id),
                "has_disputed": _has_disputed(p.facts),
                "min_confidence": _weakest_confidence(_person_confidences(p)),
                "fact_count": len(p.facts),
            }
        )

    links = []
    seen_spouses: set[tuple[str, str]] = set()
    for fam in families:
        marriage = _marriage_fact(fam)
        parent_attrs = _parent_attrs(marriage)
        spouse_attrs = _spouse_attrs(marriage)
        # Усі члени родини (підтверджені + гіпотетичні) з flag.
        all_husbands = [(fam.husband, False)] if fam.husband else []
        if fam.hypothetical_husband and fam.hypothetical_husband != fam.husband:
            all_husbands.append((fam.hypothetical_husband, True))
        all_wives = [(fam.wife, False)] if fam.wife else []
        if fam.hypothetical_wife and fam.hypothetical_wife != fam.wife:
            all_wives.append((fam.hypothetical_wife, True))
        all_children = [(c, False) for c in fam.children]
        all_children += [
            (c, True) for c in fam.hypothetical_children if c not in fam.children
        ]

        for child, child_hyp in all_children:
            for parent_id, parent_hyp in all_husbands + all_wives:
                is_hyp = child_hyp or parent_hyp
                attrs = dict(parent_attrs)
                if is_hyp:
                    attrs["status"] = "hypothesis"
                links.append(
                    {
                        "source": parent_id,
                        "target": child,
                        "type": "parent",
                        "family_id": fam.id,
                        "hypothetical": is_hyp,
                        **attrs,
                    }
                )

        for husband, h_hyp in all_husbands:
            for wife, w_hyp in all_wives:
                lo, hi = sorted([husband, wife])
                pair = (lo, hi)
                if pair in seen_spouses:
                    continue
                seen_spouses.add(pair)
                is_hyp = h_hyp or w_hyp
                attrs = dict(spouse_attrs)
                if is_hyp:
                    attrs["status"] = "hypothesis"
                links.append(
                    {
                        "source": pair[0],
                        "target": pair[1],
                        "type": "spouse",
                        "family_id": fam.id,
                        "hypothetical": is_hyp,
                        **attrs,
                    }
                )

    events = _build_events(persons, families)

    return {"nodes": nodes, "links": links, "events": events}


# ----- places.geojson --------------------------------------------------------


def _classify_region(admin: list[str] | None) -> str:
    a = " ".join(admin or []).lower()
    if "крим" in a or "крым" in a:
        return "crimea"
    if any(x in a for x in ["воронеж", "соликам", "ташкент", "таштагол", "слюдянк"]):
        return "rf"
    if (
        "молдова" in a
        or "бессараб" in a
        or "білгород-дністровськ" in a
        or "белгород-днестровск" in a
    ):
        return "bessarabia"
    if any(x in a for x in ["вінницьк", "хмельницьк", "кіровоградськ", "поділ"]):
        return "podillia"
    return "other"


def _build_geojson(
    places: list[Place],
    persons: list[Person],
    lived_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    place_persons: dict[str, list[dict[str, Any]]] = {pl.id: [] for pl in places}
    for p in persons:
        lived = lived_map.get(p.id, {})
        for f in p.facts:
            if not f.place_id or f.place_id not in place_persons:
                continue
            year = None
            year_end = None
            if f.date and f.date.value[:4].isdigit():
                year = int(f.date.value[:4])
                if f.date.range_end and f.date.range_end[:4].isdigit():
                    year_end = int(f.date.range_end[:4])
            place_persons[f.place_id].append(
                {
                    "id": p.id,
                    "name": "(приватна особа)" if p.private else p.primary_name,
                    "private": p.private,
                    "fact_type": f.type,
                    "fact_year": year,
                    "fact_year_end": year_end,
                    "lived_from": lived.get("from") if not p.private else _to_decade_int(lived.get("from")),
                    "lived_to": lived.get("to") if not p.private else _to_decade_int(lived.get("to")),
                    "lived_certainty": lived.get("certainty"),
                }
            )
    for pid in place_persons:
        place_persons[pid].sort(
            key=lambda x: (x["fact_year"] is None, x["fact_year"] or 0, x["id"])
        )

    features = []
    for pl in places:
        if not pl.coords:
            continue
        lat, lon = pl.coords
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "id": pl.id,
                    "name": pl.name,
                    "admin": pl.admin,
                    "region": _classify_region(pl.admin),
                    "persons": place_persons[pl.id],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _to_decade_int(year: int | None) -> int | None:
    if year is None:
        return None
    return (year // 10) * 10
