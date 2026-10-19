"""🗺 Карта «ситуація → команда» для агента і пошук решти (`nysh ops find`).

Агент, якому дали всі ~200 дій, не відрізняє важливого: скіли, що розрослися,
не дочитує, а стартовий перелік із 18 оп за півтора місяця транскриптів
кликав рідше, ніж `--help` по одній команді (інвентар хвилі К, 20.10.2026:
`text crop --help` — 58 разів, `workspace.info` — жодного). Тому два шари:

- **ядро** (`tier="core"`) — карта в хуку старту, ≤ `MAP_BUDGET` знаків,
  згрупована за ситуаціями дослідження;
- **решта** — запитом `nysh ops find <що треба>`: ранжування по «коли брати»,
  підпису й докстрінгу. Рядки ядра теж знаходяться, щоб запит не залежав від
  того, чи агент пам'ятає карту.

Оп і друковані команди поза реєстром (`core.routes`) тут однакові: `Entry`.
Карта фільтрується тим самим, що й виконання: вимкнена секція, проєкт лише
для читання (ховає запис), чистий хаб (ховає проєктний шар) — показати дію,
яка відмовить, означало б витратити хід агента на відмову.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any

#: Частка бюджету хука старту (`project status --agent`) під карту.
MAP_BUDGET = 3_000

#: Порядок груп карти. Ядро поза групами падає в «інше» — тест цього не пускає.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("орієнтація", ("ops.find", "doctor")),
    ("знайти матеріал", ("catalog.search", "parish.find", "share.pull",
                         "acquire.start", "case.register", "cases.list",
                         "cases.build")),
    ("прочитати", ("read.start", "cloud.go", "cloud.state", "text.index")),
    ("шукати в прочитаному", ("text.find", "text.grep", "text.whatis",
                              "text.ctx", "text.crop", "text.sheet")),
    ("записати", ("pages.status", "pages.note", "note.add")),
    ("канон", ("canon.next", "evidence.add", "canon.check")),
    ("поділитися", ("share.pack", "share.push", "share.card")),
    ("після оновлення", ("migrate.status",)),
)

_TIER_RANK = {"core": 0, "situational": 1, "rare": 2}


@dataclass(frozen=True)
class Entry:
    name: str
    cli: str
    summary: str
    tier: str
    when: str
    skill: str
    scope: str
    mutates: bool
    section: str
    kind: str          # "op" | "route"
    doc: str = ""

    def card(self) -> dict[str, Any]:
        return {"name": self.name, "cli": self.cli, "summary": self.summary,
                "tier": self.tier, "when": self.when, "skill": self.skill,
                "scope": self.scope, "mutates": self.mutates,
                "section": self.section, "kind": self.kind}


def _doc_head(fn: Any) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.split("\n\n", 1)[0].strip()


def entries() -> list[Entry]:
    """Усі дії: оп реєстру + команди поза ним. Обгортки оп (`@route(op=…)`) — не окремо."""
    from nyshporka import ops as O
    from nyshporka.core import routes as R

    out = [Entry(name=o.name, cli=R.friendly(o.name), summary=o.summary, tier=o.tier,
                 when=o.when, skill=o.skill, scope=o.scope, mutates=o.mutates,
                 section=o.section, kind="op", doc=_doc_head(o.fn))
           for o in O.all_ops()]
    out += [Entry(name=r.name, cli=f"nysh {r.cli}", summary=r.summary, tier=r.tier,
                  when=r.when, skill=r.skill, scope=r.scope, mutates=r.mutates,
                  section=r.section, kind="route")
            for r in R.ROUTES.values() if not r.op]
    return out


def _context() -> tuple[frozenset[str] | None, bool, bool]:
    """(активні секції, лише читання, чистий хаб). Простір, що не резолвиться, — без фільтрів."""
    try:
        from nyshporka.core import projects as P
        from nyshporka.core import workspace as W

        ws = W.workspace()
        return ws.sections, ws.readonly, P.tag(ws) == ""
    except Exception:
        return None, False, False


def visible(items: list[Entry], *, show_all: bool = False) -> list[Entry]:
    """Те, що в цьому просторі справді виконається."""
    if show_all:
        return items
    from nyshporka.core import sections as S

    active, readonly, pure_hub = _context()
    req = S.required_ids()
    keep = []
    for e in items:
        if active is not None and e.section not in req and e.section not in active:
            continue
        if readonly and e.mutates:
            continue
        if pure_hub and e.scope == "project":
            continue
        keep.append(e)
    return keep


def agent_map(budget: int = MAP_BUDGET) -> str:
    """Карта ядра для хука старту: «команда — коли брати», групами."""
    core = {e.name: e for e in visible(entries()) if e.tier == "core"}
    lines = ["── Команди: ядро (решта — `nysh ops find <що треба>`, "
             "аргументи — `nysh op <ім'я> --describe` або `--help`) ──"]
    placed: set[str] = set()
    for title, names in GROUPS:
        rows = [core[n] for n in names if n in core]
        if not rows:
            continue
        lines.append(f"{title}:")
        lines += [f"  {e.cli} — {e.when}" for e in rows]
        placed.update(e.name for e in rows)
    rest = [e for n, e in sorted(core.items()) if n not in placed]
    if rest:
        lines.append("інше:")
        lines += [f"  {e.cli} — {e.when}" for e in rest]
    text = "\n".join(lines)
    if len(text) > budget:
        text = text[:budget - 20].rsplit("\n", 1)[0] + "\n… (карту обрізано)"
    return text


_WORD = re.compile(r"[\w'’ʼ-]+", re.UNICODE)


def _stems(text: str) -> list[str]:
    """Нижній регістр, апостроф один, префікс ~5 літер — щоб «прогін»/«прогону» зійшлись."""
    out = []
    for w in _WORD.findall(text.lower().replace("’", "'").replace("ʼ", "'")):
        w = w.strip("-'")
        if len(w) < 2:
            continue
        out.append(w[:5] if len(w) > 5 else w)
    return out


def _match(q: str, hay: set[str]) -> bool:
    return any(h.startswith(q) or q.startswith(h) for h in hay if len(h) >= 3 or h == q)


def find(query: str, *, limit: int = 8, show_all: bool = False) -> list[tuple[Entry, int]]:
    """Дії під ситуацію, найкращі першими. Нульові збіги не повертаються."""
    qs = list(dict.fromkeys(_stems(query)))
    if not qs:
        return []
    pool = visible(entries(), show_all=show_all)
    # Слово, що стоїть у кожній п'ятій дії («справа», «прочитане»), нічого не
    # розрізняє, а лише топить рідкісне: «чи був уже прогін справи» віддавав
    # `nysh find`. Його не рахуємо, якщо в запиті є бодай одне інше.
    hays = [set(_stems(e.when + " " + e.summary)) for e in pool]
    common = {q for q in qs if sum(_match(q, h) for h in hays) > len(pool) / 5}
    if len(common) < len(qs):
        qs = [q for q in qs if q not in common]
    scored = []
    for e in pool:
        fields = ((3, e.when), (2, e.summary), (2, e.cli + " " + e.name), (1, e.doc))
        score = 0
        for q in qs:
            best = 0
            for weight, text in fields:
                if weight > best and _match(q, set(_stems(text))):
                    best = weight
            score += best
        if score:
            scored.append((e, score))
    scored.sort(key=lambda p: (-p[1], _TIER_RANK.get(p[0].tier, 3), p[0].name))
    return scored[:limit]
