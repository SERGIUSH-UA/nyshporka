"""🧭 Команди поза реєстром оп — ті самі метадані для агента, та сама межа запису.

Більшість друкованих команд — обгортки над оп (`core.ops`), і рівень, «коли
брати» та шар беруться звідти. Але частина живе поза реєстром: хмара
(`nysh cloud …`), каталоги, `read`, `get`, `crawl`. Без метаданих їх не було б ні
в карті агента, ні в `nysh ops find`, хоча саме ними агент читає справи.

    @cloud_app.command("rent")
    @route("cloud rent", tier="situational", when="орендувати карту під читання",
           mutates=True)
    def rent(...): ...

🔴 `mutates=True` — не косметика. Відмова писати в проєкт, відкритий лише для
читання (`nysh --project Y`), стоїть у `Registry.call`, а ці команди його
минають. Обгортка ставить ту саму перевірку (`ops.readonly_refusal`) перед
тілом команди — інакше межа проєктів трималась би лише для половини поверхні
(борг хвилі 2 багатопроєктності).

`op=` над обгорткою, чия назва не збігається з оп (`nysh find` →
`catalog.search`), каже карті, як цю оп набирати по-людськи. Збіг за назвою
(`nysh text find` ↔ `text.find`) зв'язується сам (`friendly`).

Повноту тримає `tests/test_routes.py`: кожен листок дерева CLI — або оп, або
`@route`, або в `EXEMPT`.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nyshporka.core.ops import SCOPES, TIERS, Scope, Tier, readonly_refusal

#: Службові листки, яким карта агента не потрібна: самі є картою або входом.
EXEMPT: frozenset[str] = frozenset({
    "version", "ops", "op", "mcp", "serve", "info",
})


@dataclass(frozen=True)
class Route:
    cli: str
    summary: str
    tier: Tier = "situational"
    when: str = ""
    skill: str = ""
    scope: Scope = "hub"
    mutates: bool = False
    section: str = "core"
    op: str = ""
    #: Чи цю команду показувати як «людську» форму `op` (дві команди на одну оп —
    #: `nysh search` і `nysh pages grep` — карта друкує одну).
    primary: bool = True

    @property
    def name(self) -> str:
        return self.cli.replace(" ", ".").replace("-", "_")


#: Секція команди за групою, коли її не названо: та сама, що в оп цієї групи.
_SECTION_BY_GROUP = {"cloud": "htr", "models": "htr", "htr": "htr", "queue": "htr",
                     "catalog": "material", "registry": "material", "geog": "material",
                     "canon": "research", "records": "research", "pages": "research"}

#: Маршрути за друкованим шляхом (`"cloud rent"`).
ROUTES: dict[str, Route] = {}


def _summary(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.strip().splitlines()[0].strip() if doc.strip() else ""


def route(cli: str, *, op: str = "", tier: Tier = "situational", when: str = "",
          skill: str = "", scope: Scope = "hub", mutates: bool = False,
          section: str = "", summary: str = "", primary: bool = True
          ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Позначити друковану команду. Ставиться ПІД `@app.command(...)`."""
    if tier not in TIERS:
        raise ValueError(f"команда «{cli}»: рівень «{tier}», є {', '.join(TIERS)}")
    if scope not in SCOPES:
        raise ValueError(f"команда «{cli}»: шар «{scope}», є {', '.join(SCOPES)}")

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if cli in ROUTES:
            raise ValueError(f"команда «{cli}» вже позначена")
        ROUTES[cli] = Route(cli=cli, summary=summary or _summary(fn), tier=tier,
                            when=when, skill=skill, scope=scope, mutates=mutates,
                            section=section or _SECTION_BY_GROUP.get(cli.split()[0], "core"),
                            op=op, primary=primary)
        if not mutates:
            return fn

        @functools.wraps(fn)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            off = readonly_refusal(f"nysh {cli}", True)
            if off is not None:
                import typer

                typer.echo(f"✗ {off}", err=True)
                raise typer.Exit(1)
            return fn(*args, **kwargs)

        return guarded

    return deco


def friendly(op_name: str) -> str:
    """Як оп набирають по-людськи: друкована команда, а не `nysh op … --args`.

    Спершу листок з тією самою назвою (`text.find` → `nysh text find`), далі
    позначена `@route(op=…)` обгортка, і лише тоді універсальний вхід.
    """
    leaf = op_name.replace(".", " ")
    for cand in (leaf, leaf.replace("_", "-")):
        if cand in cli_leaves():
            return f"nysh {cand}"
    for r in ROUTES.values():
        if r.op == op_name and r.primary:
            return f"nysh {r.cli}"
    return f"nysh op {op_name}"


@functools.lru_cache(maxsize=1)
def cli_leaves() -> frozenset[str]:
    """Усі листки дерева `nysh` (шлях через пробіл). Будує дерево один раз."""
    import typer

    from nyshporka import cli as C

    out: set[str] = set()

    def walk(cmd: Any, path: list[str]) -> None:
        subs = getattr(cmd, "commands", None)
        if subs is not None:
            for name, sub in subs.items():
                walk(sub, [*path, name])
            return
        out.add(" ".join(path))

    walk(typer.main.get_command(C.app), [])
    return frozenset(out)
