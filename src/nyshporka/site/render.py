"""Рендер канону в сторінки сайту через Jinja2-шаблони.

Кожен запуск чистить `{persons,families,places,sources}/` у теці сирців і
генерує сторінки наново; решту теки (рукописні сторінки) не чіпає.

Шаблони — пакетні (`site/data/templates`), але тека з однойменними файлами в
просторі (`SiteConfig.templates`) їх перекриває: так рід із власним оформленням
не мусить копіювати весь генератор.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from nyshporka.models import Fact, Family, MediaRef, Person, Place, Source
from nyshporka.site.config import GENERATIONS, SOURCE_TYPES, SiteConfig
from nyshporka.site.filters import register as register_filters
from nyshporka.site.privacy import redact_person
from nyshporka.storage.files import read_family, read_person, read_place, read_source

#: Пакетні шаблони сторінок.
TEMPLATES = Path(__file__).resolve().parent / "data" / "templates"

#: Перша літера латинкою → кирилицею для покажчика: той самий рід у різних
#: транслітераціях стоїть під однією літерою.
_LATIN_TO_CYR = {
    "A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д", "E": "Е", "Z": "З",
    "I": "І", "Y": "Й", "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О",
    "P": "П", "R": "Р", "S": "С", "T": "Т", "U": "У", "F": "Ф", "H": "Х",
    "C": "Ц", "J": "Ж",
}


def environment(templates_dirs: list[Path]) -> Environment:
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(str(d)) for d in [*templates_dirs, TEMPLATES]]),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    register_filters(env)
    return env


def _generations(title_no_date: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for title, lo, hi in GENERATIONS:
        out.append((title, lambda y, lo=lo, hi=hi: bool(y) and (lo is None or int(y) >= lo)
                    and (hi is None or int(y) <= hi)))
    out.append((title_no_date, lambda y: not y))
    return out


@dataclass
class RenderReport:
    persons: int = 0
    families: int = 0
    places: int = 0
    sources: int = 0
    withheld_sources: list[str] = field(default_factory=list)


def build(
    project_root: Path,
    *,
    docs_dir: Path,
    cfg: SiteConfig | None = None,
    templates_dirs: list[Path] | None = None,
    hidden: set[str] | frozenset[str] = frozenset(),
    drop_source_types: set[str] | frozenset[str] = frozenset(),
    source_filter: Callable[[Source], bool] | None = None,
) -> RenderReport:
    """`hidden` вмикає відкриту збірку (report/public.py): цих осіб на сайті немає
    зовсім — ні сторінки, ні рядка в індексах, ні імені у вузлі дерева, ні сканів.
    Джерела, які цитують лише вони, і типи з `drop_source_types` (усні свідчення)
    не публікуються. Посилання на прихованих у ЧУЖИХ сторінках прибирає вже
    постобробка `site.public` — тут вони ще лишаються звичайними лінками."""
    cfg = cfg or SiteConfig()
    canonical = project_root / "data" / "canonical"
    hidden = frozenset(hidden)
    public = bool(hidden)
    env = environment(templates_dirs or [])
    citing: dict[str, set[str]] = {}

    persons_raw = sorted(
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

    place_names = {pl.id: pl.name for pl in places}
    # Імена осіб для перехресних посилань — берем primary з canonical (не редакт).
    person_names = {p.id: p.primary_name for p in persons_raw}
    sources_by_id = {s.id: s for s in sources}

    # Відкрита збірка: хто й що взагалі потрапляє на сайт.
    shown = [p for p in persons_raw if p.id not in hidden]
    withheld: list[str] = []
    if public:
        families = [
            f for f in families
            if not _family_members(f) or _family_members(f) - hidden
        ]
        citing = _citing_ids(persons_raw, families)
        kept: list[Source] = []
        for s in sources:
            by = citing.get(s.id, set())
            if (
                s.type in drop_source_types
                or (by and by <= hidden)
                or (source_filter is not None and source_filter(s))
            ):
                withheld.append(s.id)
            else:
                kept.append(s)
        sources = kept
    published_sources = {s.id for s in sources}

    # Очистити автогенеровані каталоги.
    for sub in ("persons", "families", "places", "sources"):
        target = docs_dir / sub
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    # Доказ-вирізки документів (data/source/citations) → map page_id -> [docs]
    # + копія файлів у docs/assets/citations/, щоб сайт їх віддавав.
    allowed = (
        {p.id for p in shown} | {f.id for f in families} | {pl.id for pl in places}
        | published_sources
    ) if public else None
    citation_docs = _load_citation_docs(project_root, docs_dir, allowed=allowed)

    # Persons.
    persons = [redact_person(p) for p in shown]
    families_by_id = {f.id: f for f in families}
    person_tpl = env.get_template("person.md.j2")
    for p in persons:
        if public and _touches_hidden(p, families_by_id, hidden):
            p = p.model_copy(update={"notes": _NOTES_WITHHELD})
        used = _used_sources_for(p.facts, sources_by_id, published_sources)
        relations = _person_relations(p, families_by_id, person_names)
        media_lines = [_media_line(m) for m in p.media] if not p.private else []
        out = docs_dir / "persons" / f"{p.id}.md"
        out.write_text(
            person_tpl.render(
                person=p,
                place_names=place_names,
                all_sources=used,
                relations=relations,
                media_lines=media_lines,
                documents=citation_docs.get(p.id, []),
            ),
            encoding="utf-8",
        )

    # Persons index — alphabet jump-bar + cards, групування за літерою прізвища.
    index_persons: list[dict[str, Any]] = []
    for p in persons:
        surname = _primary_surname(p)
        given = _primary_given(p)
        birth_pid = _first_place_id(p, "birth")
        first = surname[0].upper() if surname else ""
        letter = _LATIN_TO_CYR.get(first, first) if first else "—"
        index_persons.append({
            "id": p.id,
            "primary_name": p.primary_name,
            "surname": surname,
            "given": given,
            "letter": letter,
            "birth": _first_year(p, "birth"),
            "death": _first_year(p, "death"),
            "birth_place_id": birth_pid,
            "birth_place_name": place_names.get(birth_pid) if birth_pid else None,
            "sex": p.sex,
            "private": p.private,
        })
    # Сортуємо за letter (нормалізована кирилиця) → surname → given → birth_year.
    index_persons.sort(key=lambda d: (
        d["letter"] if d["letter"] != "—" else "ЯЯЯ",
        d["surname"].lower() if d["surname"] else "яяя",
        d["given"].lower() if d["given"] else "яяя",
        d["birth"] or "9999",
    ))
    # Групування для шаблону.
    letters: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ip in index_persons:
        lt = ip["letter"]
        if lt not in grouped:
            grouped[lt] = []
            letters.append(lt)
        grouped[lt].append(ip)
    # Групування за поколінням (для accordion-секції).
    generations = _generations("Без дати народження")
    by_generation = []
    for gen_title, gen_filter in generations:
        members = [ip for ip in index_persons if gen_filter(ip["birth"])]
        if members:
            by_generation.append({"title": gen_title, "members": members})
    (docs_dir / "persons" / "index.md").write_text(
        env.get_template("_index_persons.md.j2").render(
            persons=index_persons,
            letters=letters,
            grouped=grouped,
            by_generation=by_generation,
        ),
        encoding="utf-8",
    )

    # Families.
    family_tpl = env.get_template("family.md.j2")
    for f in families:
        if public and _family_members(f) & hidden:
            f = f.model_copy(update={"notes": _NOTES_WITHHELD})
        used = _used_sources_for(f.facts, sources_by_id, published_sources)
        out = docs_dir / "families" / f"{f.id}.md"
        out.write_text(
            family_tpl.render(
                family=f,
                person_names=person_names,
                place_names=place_names,
                all_sources=used,
                documents=citation_docs.get(f.id, []),
            ),
            encoding="utf-8",
        )

    # Families index — cards + jump-bar за літерою husband (або wife якщо husband порожній).
    persons_by_id = {p.id: p for p in persons_raw}

    def _pers(pid: str | None) -> Person | None:
        return persons_by_id.get(pid) if pid else None

    def _birth_year(pid: str | None) -> str | None:
        if pid in hidden:
            return None
        p = _pers(pid)
        return _first_year(p, "birth") if p else None

    def _shown_name(pid: str | None) -> str | None:
        if not pid:
            return None
        return "жива особа" if pid in hidden else person_names.get(pid)

    index_fams: list[dict[str, Any]] = []
    for f in families:
        husband = _pers(f.husband)
        wife = _pers(f.wife)
        hyp_husband = _pers(f.hypothetical_husband)
        hyp_wife = _pers(f.hypothetical_wife)
        # Літера сортування: husband.surname → wife.surname → hyp.surname → "—"
        pivot = husband or wife or hyp_husband or hyp_wife
        surname = _primary_surname(pivot) if pivot else ""
        first = surname[0].upper() if surname else ""
        letter = _LATIN_TO_CYR.get(first, first) if first else "—"
        # Рік для покоління — найперший рік народження подружжя.
        years = [
            y for y in [
                _birth_year(f.husband), _birth_year(f.wife),
                _birth_year(f.hypothetical_husband), _birth_year(f.hypothetical_wife),
            ] if y
        ]
        pivot_year = min(years) if years else None
        index_fams.append({
            "id": f.id,
            "husband_name": _shown_name(f.husband),
            "husband_id": f.husband,
            "husband_year": _birth_year(f.husband),
            "wife_name": _shown_name(f.wife),
            "wife_id": f.wife,
            "wife_year": _birth_year(f.wife),
            "hypothetical_husband_name": _shown_name(f.hypothetical_husband),
            "hypothetical_husband_id": f.hypothetical_husband,
            "hypothetical_wife_name": _shown_name(f.hypothetical_wife),
            "hypothetical_wife_id": f.hypothetical_wife,
            "children_count": len(f.children),
            "hypothetical_children_count": len(f.hypothetical_children),
            "letter": letter,
            "surname": surname,
            "pivot_year": pivot_year,
            "is_hypothetical": not (f.husband or f.wife) and bool(f.hypothetical_husband or f.hypothetical_wife),
        })
    index_fams.sort(key=lambda d: (
        d["letter"] if d["letter"] != "—" else "ЯЯЯ",
        d["surname"].lower() if d["surname"] else "яяя",
        d["pivot_year"] or "9999",
        d["id"],
    ))
    fam_letters: list[str] = []
    fam_grouped: dict[str, list[dict[str, Any]]] = {}
    for fi in index_fams:
        lt = fi["letter"]
        if lt not in fam_grouped:
            fam_grouped[lt] = []
            fam_letters.append(lt)
        fam_grouped[lt].append(fi)
    fam_generations_def = _generations("Без дати")
    fam_by_generation = []
    for title, flt in fam_generations_def:
        members = [fi for fi in index_fams if flt(fi["pivot_year"])]
        if members:
            fam_by_generation.append({"title": title, "members": members})
    (docs_dir / "families" / "index.md").write_text(
        env.get_template("_index_families.md.j2").render(
            families=index_fams,
            letters=fam_letters,
            grouped=fam_grouped,
            by_generation=fam_by_generation,
        ),
        encoding="utf-8",
    )

    # Places.
    related_by_place = _places_related(places, shown)
    place_tpl = env.get_template("place.md.j2")
    for pl in places:
        out = docs_dir / "places" / f"{pl.id}.md"
        out.write_text(
            place_tpl.render(place=pl, related_persons=related_by_place.get(pl.id, [])),
            encoding="utf-8",
        )

    # Places index — cards з jump-bar за групою місць із налаштувань сайту.
    groups = cfg.ordered_groups()
    REGION_LABELS = {g.id: g.label for g in groups}
    REGION_ORDER = [g.id for g in groups]
    index_places: list[dict[str, Any]] = []
    for pl in places:
        region = cfg.place_group(pl.admin).id
        rel_persons = related_by_place.get(pl.id, [])
        unique_pids = {ip["id"] for ip in rel_persons} if rel_persons else set()
        index_places.append({
            "id": pl.id,
            "name": pl.name,
            "admin": pl.admin,
            "has_coords": pl.coords is not None,
            "region": region,
            "region_label": REGION_LABELS.get(region, region),
            "persons_count": len(unique_pids),
        })
    # Сортування: за регіоном (наш порядок) → за назвою.
    region_idx = {r: i for i, r in enumerate(REGION_ORDER)}
    index_places.sort(key=lambda d: (
        region_idx.get(d["region"], 99),
        d["name"].lower(),
    ))
    pl_grouped: dict[str, list[dict[str, Any]]] = {r: [] for r in REGION_ORDER}
    for ip in index_places:
        pl_grouped[ip["region"]].append(ip)
    pl_groups = [
        {"id": r, "label": REGION_LABELS[r], "members": pl_grouped[r]}
        for r in REGION_ORDER if pl_grouped[r]
    ]
    (docs_dir / "places" / "index.md").write_text(
        env.get_template("_index_places.md.j2").render(
            places=index_places,
            groups=pl_groups,
        ),
        encoding="utf-8",
    )

    # Sources.
    from nyshporka.models import load_regions
    from nyshporka.storage.reindex import _COVERAGE_RECORD_TYPES, _COVERAGE_STATUSES

    region_names = (load_regions(project_root).names()
                    if (canonical / "regions.yml").is_file() else {})
    cov_status_labels = {st["id"]: st["label"] for st in _COVERAGE_STATUSES}
    cov_rt_labels = {rt["id"]: rt["label"] for rt in _COVERAGE_RECORD_TYPES}

    referenced_by_source = _sources_referenced(sources, shown, person_names)
    source_tpl = env.get_template("source.md.j2")
    for s in sources:
        if public and citing.get(s.id, set()) & hidden:
            s = s.model_copy(update={"notes": _NOTES_WITHHELD})
        out = docs_dir / "sources" / f"{s.id}.md"
        out.write_text(
            source_tpl.render(
                source=s,
                referenced_facts=referenced_by_source.get(s.id, []),
                documents=citation_docs.get(s.id, []),
                region_names=region_names,
                cov_status_labels=cov_status_labels,
                cov_rt_labels=cov_rt_labels,
            ),
            encoding="utf-8",
        )

    # Sources index — cards з jump-bar за типом + кількість фактів-цитат.
    SOURCE_TYPE_LABELS = dict(SOURCE_TYPES)
    SOURCE_TYPE_ORDER = [t for t, _ in SOURCE_TYPES]
    # Підрахунок цитувань: скільки фактів у persons вказують на конкретний source_id.
    citations_count: dict[str, int] = {}
    for pr in persons_raw:
        for fact in pr.facts:
            for c in fact.citations:
                citations_count[c.source_id] = citations_count.get(c.source_id, 0) + 1
    index_sources: list[dict[str, Any]] = []
    for src in sources:
        index_sources.append({
            "id": src.id,
            "title": src.title,
            "type": src.type,
            "type_label": SOURCE_TYPE_LABELS.get(src.type, src.type),
            "authority": src.authority,
            "url": src.url,
            "citations_count": citations_count.get(src.id, 0),
        })
    # Сортуємо: за type → citations_count DESC → title.
    type_idx = {t: i for i, t in enumerate(SOURCE_TYPE_ORDER)}
    index_sources.sort(key=lambda d: (
        type_idx.get(d["type"], 99),
        -d["citations_count"],
        d["title"].lower(),
    ))
    src_grouped: dict[str, list[dict[str, Any]]] = {t: [] for t in SOURCE_TYPE_ORDER}
    for row in index_sources:
        src_grouped.setdefault(row["type"], []).append(row)
    src_groups = [
        {"id": t, "label": SOURCE_TYPE_LABELS.get(t, t), "members": src_grouped[t]}
        for t in SOURCE_TYPE_ORDER if src_grouped.get(t)
    ]
    # Топ-10 найцитованіших — для «Найважливіші» секції зверху.
    src_top = sorted(index_sources, key=lambda d: -d["citations_count"])[:10]

    (docs_dir / "sources" / "index.md").write_text(
        env.get_template("_index_sources.md.j2").render(
            sources=index_sources,
            groups=src_groups,
            top=src_top,
        ),
        encoding="utf-8",
    )

    # Скопіювати places.geojson у docs/assets/, щоб Leaflet-мапа його бачила.
    assets_dir = docs_dir / "assets"
    geojson_src = project_root / "data" / "derived" / "places.geojson"
    if geojson_src.exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        if public:
            # Кожна точка мапи несе ПОІМЕННИЙ список осіб — прихованих звідти геть.
            gj = json.loads(geojson_src.read_text(encoding="utf-8"))
            for feat in gj.get("features", []):
                props = feat.get("properties") or {}
                if isinstance(props.get("persons"), list):
                    props["persons"] = [
                        x for x in props["persons"] if x.get("id") not in hidden
                    ]
            (assets_dir / "places.geojson").write_text(
                json.dumps(gj, ensure_ascii=False), encoding="utf-8"
            )
        else:
            shutil.copy2(geojson_src, assets_dir / "places.geojson")

    # Безпечна копія graph.json: приватні особи без імен і точних років.
    # Поряд — повна графа graph.full.json для локального dev-перегляду
    # (під .gitignore, не публікується).
    graph_src = project_root / "data" / "derived" / "graph.json"
    if graph_src.exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        raw_graph = json.loads(graph_src.read_text(encoding="utf-8"))
        safe = _redact_graph(raw_graph, hidden)
        (assets_dir / "graph.json").write_text(
            json.dumps(safe, ensure_ascii=False), encoding="utf-8"
        )
        if not public:
            (assets_dir / "graph.full.json").write_text(
                json.dumps(raw_graph, ensure_ascii=False), encoding="utf-8"
            )

    # Те саме для tree.json (нова multi-pane візуалізація).
    tree_src = project_root / "data" / "derived" / "tree.json"
    if tree_src.exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        raw_tree = json.loads(tree_src.read_text(encoding="utf-8"))
        safe_tree = _redact_tree_graph(raw_tree, hidden)
        (assets_dir / "tree.json").write_text(
            json.dumps(safe_tree, ensure_ascii=False), encoding="utf-8"
        )
        if not public:
            (assets_dir / "tree.full.json").write_text(
                json.dumps(raw_tree, ensure_ascii=False), encoding="utf-8"
            )

    # coverage.json для карти покриття джерел — публічний як є (без raw_path,
    # приватних осіб там немає).
    coverage_src = project_root / "data" / "derived" / "coverage.json"
    if coverage_src.exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(coverage_src, assets_dir / "coverage.json")

    return RenderReport(
        persons=len(persons),
        families=len(families),
        places=len(places),
        sources=len(sources),
        withheld_sources=withheld,
    )


# Нотатки на межі з живими описують їх прозою — ім'я, адреса,
# вулиця й хата — без ID і часто у відмінку, тож ні заміна посилань, ні проби
# імен їх не ловлять. На відкритому сайті такі нотатки не публікуються цілком.
_NOTES_WITHHELD = "_Нотатки не публікуються у відкритій версії: у них ідеться про живих родичів._"


def _touches_hidden(p: Person, families_by_id: dict[str, Family], hidden: frozenset[str]) -> bool:
    """Чи є серед подружжя або дітей особи прихований."""
    for fid in [*p.spouse_families, *p.hypothetical_spouse_families]:
        fam = families_by_id.get(fid)
        if fam and (_family_members(fam) - {p.id}) & hidden:
            return True
    return False


def _family_members(f: Family) -> set[str]:
    return {
        x for x in [
            f.husband, f.wife, f.hypothetical_husband, f.hypothetical_wife,
            *f.children, *f.hypothetical_children,
        ] if x
    }


def _citing_ids(persons: list[Person], families: list[Family]) -> dict[str, set[str]]:
    """source_id → хто його цитує (ID особи або родини)."""
    out: dict[str, set[str]] = {}
    for p in persons:
        for f in p.facts:
            for c in f.citations:
                out.setdefault(c.source_id, set()).add(p.id)
    for fam in families:
        for f in fam.facts:
            for c in f.citations:
                out.setdefault(c.source_id, set()).add(fam.id)
    return out


_WITHHELD_TITLE = "Джерело не публікується у відкритій версії"


def _used_sources_for(
    facts: list[Fact], sources_by_id: dict[str, Source], published: set[str] | None = None
) -> list[dict[str, Any]]:
    """Зібрати тільки ті джерела, що реально цитуються у фактах сторінки.

    Джерело поза `published` (відкрита збірка) лишає зноску, але без назви й
    посилання: назва усного свідчення часто сама називає живу людину."""
    seen: list[str] = []
    for f in facts:
        for c in f.citations:
            if c.source_id in sources_by_id and c.source_id not in seen:
                seen.append(c.source_id)
    out = []
    for sid in seen:
        if published is not None and sid not in published:
            out.append({"id": sid, "title": _WITHHELD_TITLE, "withheld": True})
        else:
            out.append({"id": sid, "title": sources_by_id[sid].title, "withheld": False})
    return out


def _first_year(p: Person, fact_type: str) -> str | None:
    for f in p.facts:
        if f.type == fact_type and f.date and f.date.value[:4].isdigit():
            return f.date.value[:4]
    return None


def _first_place_id(p: Person, fact_type: str) -> str | None:
    for f in p.facts:
        if f.type == fact_type and f.place_id:
            return f.place_id
    return None


def _primary_surname(p: Person) -> str:
    for n in p.names:
        if n.primary and n.surname:
            return n.surname
    for n in p.names:
        if n.surname:
            return n.surname
    return ""


def _primary_given(p: Person) -> str:
    for n in p.names:
        if n.primary and n.given:
            return n.given
    for n in p.names:
        if n.given:
            return n.given
    return ""


_DOC_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _humanize_doc_name(stem: str) -> str:
    """`d199_0016_dmytrij_birth_1914` → `d199 0016 dmytrij birth 1914`."""
    return stem.replace("_", " ").replace("-", " ").strip()


def _load_citation_docs(
    project_root: Path, docs_dir: Path, allowed: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Читає MANIFEST_citations.json, копіює доказ-файли у docs/assets/citations/
    і повертає map page_id (без .md) -> [ {url, caption, is_pdf, is_img, filename} ].

    Показуємо ВСЕ (і PDF, і на сторінках живих) — за рішенням користувача;
    docs/assets/citations/ під .gitignore (відтворювана копія з data/source/citations).
    `allowed` (відкрита збірка) — лише сторінки, що публікуються: файл, який цитують
    тільки приховані, не копіюється взагалі."""
    citations_root = project_root / "data" / "source" / "citations"
    manifest_path = citations_root / "MANIFEST_citations.json"
    by_page: dict[str, list[dict[str, Any]]] = {}
    if not manifest_path.exists():
        return by_page

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.values() if isinstance(manifest, dict) else manifest
    assets_cit = docs_dir / "assets" / "citations"
    copied: set[str] = set()

    for rec in records:
        if not isinstance(rec, dict):
            continue
        path = rec.get("secured_to")
        cited_by = rec.get("cited_by") or []
        if allowed is not None:
            cited_by = [
                cb for cb in cited_by
                if isinstance(cb, str) and (cb[:-3] if cb.endswith(".md") else cb) in allowed
            ]
        if not path or not cited_by:
            continue
        src = project_root / path
        if not src.exists():
            continue
        ext = src.suffix.lower()
        is_pdf = ext == ".pdf"
        is_img = ext in _DOC_IMG_EXT
        if not (is_pdf or is_img):
            continue
        try:
            rel = src.relative_to(citations_root)
        except ValueError:
            rel = Path(src.name)
        dest = assets_cit / rel
        key = str(dest)
        if key not in copied:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.add(key)
        entry = {
            "url": "../assets/citations/" + rel.as_posix(),
            "caption": _humanize_doc_name(src.stem),
            "is_pdf": is_pdf,
            "is_img": is_img,
            "filename": src.name,
        }
        for cb in cited_by:
            pid = cb[:-3] if isinstance(cb, str) and cb.endswith(".md") else cb
            by_page.setdefault(pid, []).append(entry)

    # Дедуп за url + стабільне сортування за іменем файлу.
    for pid, lst in by_page.items():
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for e in lst:
            if e["url"] in seen:
                continue
            seen.add(e["url"])
            uniq.append(e)
        by_page[pid] = sorted(uniq, key=lambda e: e["filename"])
    return by_page


def _media_line(m: MediaRef) -> str:
    parts: list[str] = ["- "]
    if m.caption:
        parts.append(f"{m.caption} — ")
    if m.url:
        parts.append(f"[оригінал]({m.url})")
    else:
        parts.append("локальне фото")
    if m.sha256:
        parts.append(f" `{m.sha256[:12]}…`")
    return "".join(parts)


def _person_relations(
    person: Person,
    families_by_id: dict[str, Family],
    person_names: dict[str, str],
) -> dict[str, Any]:
    """Готова структура родинних зв'язків для шаблону person.md.j2.

    Резолвить parent_family/spouse_families у конкретні імена батьків,
    братів/сестер, подружжя й дітей — щоб шаблон не виводив самі IDs.
    Гіпотетичні зв'язки — окремим блоком."""

    def _name(pid: str) -> str:
        return person_names.get(pid, pid)

    def _resolve_family(fid: str | None) -> dict[str, Any] | None:
        if not fid or fid not in families_by_id:
            return None
        fam = families_by_id[fid]
        return {
            "id": fid,
            "husband": (
                {"id": fam.husband, "name": _name(fam.husband)} if fam.husband else None
            ),
            "wife": (
                {"id": fam.wife, "name": _name(fam.wife)} if fam.wife else None
            ),
            "children": [{"id": c, "name": _name(c)} for c in fam.children],
            "hypothetical_husband": (
                {"id": fam.hypothetical_husband, "name": _name(fam.hypothetical_husband)}
                if fam.hypothetical_husband
                else None
            ),
            "hypothetical_wife": (
                {"id": fam.hypothetical_wife, "name": _name(fam.hypothetical_wife)}
                if fam.hypothetical_wife
                else None
            ),
            "hypothetical_children": [
                {"id": c, "name": _name(c)} for c in fam.hypothetical_children
            ],
        }

    def _md_link_person(item: dict[str, Any]) -> str:
        return f'[{item["name"]}](../persons/{item["id"]}.md)'

    def _md_link_family(fid: str) -> str:
        return f'[{fid}](../families/{fid}.md)'

    def _build_branch(parent_fid: str | None, spouse_fids: list[str], hypothetical: bool) -> dict[str, Any]:
        parent_fam = _resolve_family(parent_fid)
        parents: list[dict[str, Any]] = []
        siblings: list[dict[str, Any]] = []
        if parent_fam:
            for slot in ("husband", "wife"):
                if parent_fam[slot]:
                    parents.append(parent_fam[slot])
            if hypothetical:
                for slot in ("hypothetical_husband", "hypothetical_wife"):
                    if parent_fam[slot]:
                        parents.append(parent_fam[slot])
            for ch in parent_fam["children"]:
                if ch["id"] != person.id:
                    siblings.append(ch)
            if hypothetical:
                for ch in parent_fam["hypothetical_children"]:
                    if ch["id"] != person.id and not any(s["id"] == ch["id"] for s in siblings):
                        siblings.append(ch)

        spouses: list[dict[str, Any]] = []
        for fid in spouse_fids:
            fam = _resolve_family(fid)
            if not fam:
                continue
            # Партнер = той з husband/wife, хто не я.
            partner = None
            for slot in ("husband", "wife"):
                p = fam[slot]
                if p and p["id"] != person.id:
                    partner = p
                    break
            if not partner and hypothetical:
                for slot in ("hypothetical_husband", "hypothetical_wife"):
                    p = fam[slot]
                    if p and p["id"] != person.id:
                        partner = p
                        break
            children = list(fam["children"])
            # Гіпотетичні діти — у окрему гілку: для confirmed spouse-родин
            # їх теж треба бачити, але з позначкою.
            hyp_children = [
                c for c in fam["hypothetical_children"]
                if not any(cc["id"] == c["id"] for cc in children)
            ]
            if hypothetical:
                # У гіпотетичному режимі склеюємо все разом — гіп. шлюб, всі діти однаково непідтверджені.
                for c in hyp_children:
                    children.append(c)
                hyp_children = []
            spouses.append(
                {
                    "id": fid,
                    "family_md": _md_link_family(fid),
                    "partner_md": _md_link_person(partner) if partner else "_невідомо_",
                    "children_md": ", ".join(_md_link_person(c) for c in children),
                    "has_children": bool(children),
                    "hypothetical_children_md": ", ".join(_md_link_person(c) for c in hyp_children),
                    "has_hypothetical_children": bool(hyp_children),
                }
            )

        return {
            "parent_family_id": parent_fid,
            "parent_family_md": _md_link_family(parent_fid) if parent_fid else "",
            "parents_md": " і ".join(_md_link_person(p) for p in parents),
            "has_parents": bool(parents),
            "siblings_md": ", ".join(_md_link_person(s) for s in siblings),
            "has_siblings": bool(siblings),
            "spouses": spouses,
            "has_spouses": bool(spouses),
        }

    return {
        "confirmed": _build_branch(
            person.parent_family, person.spouse_families, hypothetical=False
        ),
        "hypothetical": _build_branch(
            person.hypothetical_parent_family,
            person.hypothetical_spouse_families,
            hypothetical=True,
        ),
    }


def _places_related(places: list[Place], persons: list[Person]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {pl.id: [] for pl in places}
    for p in persons:
        for f in p.facts:
            if f.place_id and f.place_id in result:
                ctx_date = f.date.value[:4] if f.date else "—"
                result[f.place_id].append(
                    {
                        "id": p.id,
                        "name": p.primary_name,
                        "context": f"{_fact_context(f.type)} ({ctx_date})",
                    }
                )
    return result


def _sources_referenced(
    sources: list[Source], persons: list[Person], names: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {s.id: [] for s in sources}
    for p in persons:
        for f in p.facts:
            for c in f.citations:
                if c.source_id in result:
                    result[c.source_id].append(
                        {
                            "person_id": p.id,
                            "person_name": names.get(p.id, p.id),
                            "fact_type": f.type,
                        }
                    )
    return result


def _fact_context(fact_type: str) -> str:
    return {
        "birth": "народився",
        "death": "помер",
        "marriage": "одружився",
        "burial": "похований",
        "baptism": "охрещений",
        "residence": "проживав",
    }.get(fact_type, fact_type)


def _redact_graph(raw: dict[str, Any], hidden: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """Підготувати graph.json до публікації в docs/: приватні особи редаговані.

    `hidden` (відкрита збірка) редагує так само ще й тих, хто не позначений
    `private`, але на відкритий сайт не йде."""
    nodes = []
    for n in raw.get("nodes", []):
        if n.get("private") or n.get("id") in hidden:
            nodes.append(
                {
                    **n,
                    "name": "(приватна особа)",
                    "birth": n.get("birth_decade"),
                    "death": n.get("death_decade"),
                    "fact_count": 0,
                }
            )
        else:
            nodes.append(n)
    events = raw.get("events", [])
    if hidden:
        events = [e for e in events if not (isinstance(e, dict) and e.get("person_id") in hidden)]
    return {
        "nodes": nodes,
        "links": raw.get("links", []),
        "events": events,
    }


def _redact_tree_graph(raw: dict[str, Any], hidden: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """Public-варіант tree.json.

    Приватним особам обнуляємо: name → '(приватна особа)', initials → '?',
    photo_url → None, has_photo → False, точні роки → десятиліття,
    fact_count → 0. Топологію (parent_ids/child_ids/spouse_ids) лишаємо —
    приватна особа просто фігурує без імені, інакше граф розривається.

    Події (events) приватних осіб не лишаються в публічному timeline.
    """
    private_ids = {n["id"] for n in raw.get("nodes", []) if n.get("private")} | set(hidden)

    nodes = []
    for n in raw.get("nodes", []):
        if n["id"] in private_ids:
            nodes.append(
                {
                    **n,
                    "name": "(приватна особа)",
                    "initials": "?",
                    "photo_url": None,
                    "has_photo": False,
                    "photo_stale_risk": False,
                    "birth": n.get("birth_decade"),
                    "death": n.get("death_decade"),
                    "fact_count": 0,
                }
            )
        else:
            nodes.append(n)

    events = [
        e for e in raw.get("events", []) if e.get("person_id") not in private_ids
    ]

    meta = dict(raw.get("meta") or {})
    meta["redacted"] = True

    return {
        "meta": meta,
        "generations": raw.get("generations", {"min": 0, "max": 0}),
        "nodes": nodes,
        "links": raw.get("links", []),
        "families": raw.get("families", []),
        "events": events,
    }
