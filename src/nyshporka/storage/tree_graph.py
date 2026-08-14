"""Tree-graph: окремий derived JSON для нової multi-pane візуалізації.

Доповнює стару `_build_graph` (force-directed): додає generation, photo,
initials, родинні id-маси та об'єкт families[] для sugiyama-DAG layout-у
у браузері (dagre).

Старий `data/derived/graph.json` лишається — Phase 4 його прибере.
"""

from __future__ import annotations

from datetime import UTC, datetime

from nyshporka.models import Family, Person
from nyshporka.storage.reindex import (
    _build_events,
    _compute_lived_all,
    _connected_components,
    _decade_of,
    _has_disputed,
    _marriage_fact,
    _parent_attrs,
    _person_confidences,
    _spouse_attrs,
    _weakest_confidence,
    _year_of,
)


def build_tree_graph(persons: list[Person], families: list[Family]) -> dict:
    """Зібрати `tree.json` з усіма полями для multi-pane UI."""
    branch_of = _connected_components(persons, families)
    lived_map = _compute_lived_all(persons, families)

    by_id = {p.id: p for p in persons}

    parents_of, children_of, spouses_of, parent_family_of, spouse_families_of = (
        _build_relation_index(persons, families)
    )

    generations = _compute_generations(persons, parents_of)
    eras = _compute_eras(persons, lived_map)
    ancestor_counts = _compute_relation_counts(persons, parents_of)
    descendant_counts = _compute_relation_counts(persons, children_of)

    nodes: list[dict] = []
    for p in persons:
        birth = _year_of("birth", p.facts)
        death = _year_of("death", p.facts)
        lived = lived_map[p.id]
        photo = _select_photo(p)
        nodes.append(
            {
                "id": p.id,
                "name": p.primary_name,
                "sex": p.sex,
                "private": p.private,
                "initials": _initials(p),
                "photo_url": photo["url"],
                "has_photo": photo["url"] is not None,
                "photo_stale_risk": photo["stale_risk"],
                "birth": birth,
                "death": death,
                "birth_decade": _decade_of(birth),
                "death_decade": _decade_of(death),
                "lived_from": lived["from"],
                "lived_to": lived["to"],
                "lived_certainty": lived["certainty"],
                "lived_method": lived["method"],
                "generation": generations.get(p.id),
                "era_index": eras.get(p.id),
                "branch_id": branch_of.get(p.id, p.id),
                "has_disputed": _has_disputed(p.facts),
                "min_confidence": _weakest_confidence(_person_confidences(p)),
                "fact_count": len(p.facts),
                "parent_ids": sorted(parents_of.get(p.id, set())),
                "child_ids": sorted(children_of.get(p.id, set())),
                "spouse_ids": sorted(spouses_of.get(p.id, set())),
                "parent_family_id": parent_family_of.get(p.id),
                "spouse_family_ids": sorted(spouse_families_of.get(p.id, set())),
                "is_root": not parents_of.get(p.id),
                "ancestor_count": ancestor_counts.get(p.id, 0),
                "descendant_count": descendant_counts.get(p.id, 0),
            }
        )

    links: list[dict] = _build_links(families, by_id)
    fams: list[dict] = _build_families_list(families)
    events = _build_events(persons, families)

    gens = [g for g in generations.values() if g is not None]
    gen_range = {"min": min(gens), "max": max(gens)} if gens else {"min": 0, "max": 0}

    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "person_count": len(persons),
            "family_count": len(families),
            "redacted": False,
            "schema_version": 1,
        },
        "generations": gen_range,
        "nodes": nodes,
        "links": links,
        "families": fams,
        "events": events,
    }


# ----- допоміжне: індекси зв'язків ------------------------------------------


def _build_relation_index(
    persons: list[Person], families: list[Family]
) -> tuple[
    dict[str, set[str]],  # parents_of
    dict[str, set[str]],  # children_of
    dict[str, set[str]],  # spouses_of
    dict[str, str | None],  # parent_family_of
    dict[str, set[str]],  # spouse_families_of
]:
    """Один прохід по families → усі чотири індекси.

    Включає гіпотетичні зв'язки (Person.hypothetical_*, Family.hypothetical_*).
    Розмежування підтверджених vs гіпотетичних робиться окремо у `_build_links`
    через `attrs.status: hypothesis` на ребрі.
    """
    parents_of: dict[str, set[str]] = {p.id: set() for p in persons}
    children_of: dict[str, set[str]] = {p.id: set() for p in persons}
    spouses_of: dict[str, set[str]] = {p.id: set() for p in persons}
    parent_family_of: dict[str, str | None] = {p.id: p.parent_family for p in persons}
    spouse_families_of: dict[str, set[str]] = {
        p.id: set(p.spouse_families) for p in persons
    }

    # Гіпотетичні parent_family / spouse_families з Person.
    for p in persons:
        if p.hypothetical_parent_family and not parent_family_of.get(p.id):
            parent_family_of[p.id] = p.hypothetical_parent_family
        for fid in p.hypothetical_spouse_families:
            spouse_families_of[p.id].add(fid)

    person_ids = {p.id for p in persons}

    for fam in families:
        parent_ids: list[str] = []
        for pid in (fam.husband, fam.wife, fam.hypothetical_husband, fam.hypothetical_wife):
            if pid and pid in person_ids and pid not in parent_ids:
                parent_ids.append(pid)
        child_ids: list[str] = []
        for cid in fam.children:
            if cid in person_ids:
                child_ids.append(cid)
        for cid in fam.hypothetical_children:
            if cid in person_ids and cid not in child_ids:
                child_ids.append(cid)

        for c in child_ids:
            parents_of[c].update(parent_ids)
        for par in parent_ids:
            children_of[par].update(child_ids)
        for a in parent_ids:
            for b in parent_ids:
                if a != b:
                    spouses_of[a].add(b)

    return parents_of, children_of, spouses_of, parent_family_of, spouse_families_of


def _compute_generations(
    persons: list[Person],
    parents_of: dict[str, set[str]],
) -> dict[str, int]:
    """Generation = longest path від кореня (особа без батьків у графі).

    Стабільно для DAG. Якщо є цикл через hypothetical_* — детектуємо й
    розриваємо: запис лишається без generation (None) і JS-layer вирішує.
    """
    generations: dict[str, int | None] = {p.id: None for p in persons}

    def resolve(pid: str, on_stack: set[str]) -> int | None:
        if pid in on_stack:
            return None  # цикл — повертаємо None, не падаємо
        cached = generations.get(pid)
        if cached is not None:
            return cached
        parents = parents_of.get(pid, set())
        if not parents:
            generations[pid] = 0
            return 0
        on_stack.add(pid)
        parent_gens = []
        for par in parents:
            g = resolve(par, on_stack)
            if g is not None:
                parent_gens.append(g)
        on_stack.discard(pid)
        if not parent_gens:
            return None
        result = max(parent_gens) + 1
        generations[pid] = result
        return result

    for p in persons:
        if generations[p.id] is None:
            resolve(p.id, set())

    return {pid: g for pid, g in generations.items() if g is not None}


_ERA_ANCHOR_YEAR = 1820
_ERA_LENGTH = 25


def _compute_eras(
    persons: list[Person],
    lived_map: dict[str, dict],
) -> dict[str, int]:
    """Era index = (lived_from - anchor) // 25. None якщо немає жодної дати.

    JS-layer прив'язує сиріт без батьків до anchor свого ряду, щоб не
    збиватись з гілками XIX ст. Для осіб з батьками rank беруть з батька.
    """
    eras: dict[str, int] = {}
    for p in persons:
        info = lived_map.get(p.id) or {}
        lf = info.get("from")
        if lf is None:
            continue
        eras[p.id] = max(0, (lf - _ERA_ANCHOR_YEAR) // _ERA_LENGTH)
    return eras


def _compute_relation_counts(
    persons: list[Person],
    edges: dict[str, set[str]],
) -> dict[str, int]:
    """BFS-підрахунок усіх досяжних предків (або нащадків) через `edges`."""
    counts: dict[str, int] = {}
    for p in persons:
        visited: set[str] = set()
        frontier = list(edges.get(p.id, set()))
        while frontier:
            cur = frontier.pop()
            if cur in visited:
                continue
            visited.add(cur)
            frontier.extend(edges.get(cur, set()) - visited)
        counts[p.id] = len(visited)
    return counts


# ----- фото та ініціали -----------------------------------------------------


def _select_photo(p: Person) -> dict:
    """Перше photo з media. Не редагує — для приватних робить redact layer."""
    for m in p.media:
        if m.type != "photo":
            continue
        if m.url:
            # MyHeritage URL: підписаний, може протухнути.
            return {"url": m.url, "stale_risk": True}
        if m.path:
            # Локальний шлях — буде скопійовано render-ом (Phase 4 — поки лишаємо).
            return {"url": m.path, "stale_risk": False}
    return {"url": None, "stale_risk": False}


def _initials(p: Person) -> str:
    """2 латинські/кириличні літери з given+surname для silhouette-fallback."""
    name = p.primary_name.strip()
    if not name:
        return "?"
    parts = [w for w in name.split() if w]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[-1][:1]).upper()
    return parts[0][:2].upper() if parts else "?"


# ----- links ----------------------------------------------------------------


def _build_links(families: list[Family], by_id: dict[str, Person]) -> list[dict]:
    """Parent + spouse links у форматі, готовому для dagre+D3."""
    links: list[dict] = []
    seen_spouses: set[tuple[str, str]] = set()
    for fam in families:
        marriage = _marriage_fact(fam)
        parent_attrs = _parent_attrs(marriage)
        spouse_attrs = _spouse_attrs(marriage)

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
            if child not in by_id:
                continue
            for parent_id, parent_hyp in all_husbands + all_wives:
                if parent_id not in by_id:
                    continue
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
                if husband not in by_id or wife not in by_id:
                    continue
                pair = tuple(sorted([husband, wife]))
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

    return links


# ----- families[] -----------------------------------------------------------


def _build_families_list(families: list[Family]) -> list[dict]:
    """Структура `families[]` для рендерера: пара + діти + статус шлюбу."""
    out: list[dict] = []
    for fam in families:
        marriage = _marriage_fact(fam)
        marriage_year = None
        marriage_status = "unknown"
        if marriage is not None:
            if marriage.date and marriage.date.value[:4].isdigit():
                marriage_year = int(marriage.date.value[:4])
            marriage_status = marriage.status

        hyp_children = [
            c for c in fam.hypothetical_children if c not in fam.children
        ]
        out.append(
            {
                "id": fam.id,
                "husband_id": fam.husband,
                "wife_id": fam.wife,
                "children_ids": list(fam.children),
                "hypothetical_husband_id": (
                    fam.hypothetical_husband
                    if fam.hypothetical_husband and fam.hypothetical_husband != fam.husband
                    else None
                ),
                "hypothetical_wife_id": (
                    fam.hypothetical_wife
                    if fam.hypothetical_wife and fam.hypothetical_wife != fam.wife
                    else None
                ),
                "hypothetical_children_ids": hyp_children,
                "marriage_year": marriage_year,
                "marriage_status": marriage_status,
            }
        )
    return out
