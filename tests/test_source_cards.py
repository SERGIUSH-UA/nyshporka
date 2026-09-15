"""🪪 Джерело каже про себе те саме, що картка довідника.

Маршрут агента будується з карток `where-to-dig-channels.md` і таблиці класів
`where-to-dig.md`, а перелік джерел — з реєстру. Доки їх звіряла лише
домовленість, два списки розійшлись мовчки: фотоархів Волока був підключений,
але без картки, і в симуляції 15.09.2026 випав із плану про Донеччину — хоча
саме там мав списки населених місць і розпис парафій.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest

from nyshporka.sources.base import MatchHow, MatchOn, SourceAbout, SourceScope, about_of

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ROOT / "docs" / "agents" / "where-to-dig-channels.md"
ROUTE = ROOT / "docs" / "agents" / "where-to-dig.md"


def _builtin() -> list[Any]:
    from nyshporka.sources.registry import _builtin as build

    return list(build(None))


def _key(src: Any) -> str:
    about = about_of(src)
    return (about.card if about and about.card else "") or src.id


def _class_rows() -> dict[str, str]:
    """Таблиця «Класи каналів»: клас → увесь рядок."""
    text = ROUTE.read_text(encoding="utf-8")
    block = text.split("## Класи каналів", 1)[1].split("\n---", 1)[0]
    rows: dict[str, str] = {}
    for line in block.splitlines():
        if not line.startswith("| ") or line.startswith("| клас "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows[cells[0]] = line
    return rows


SOURCES = _builtin()
IDS = [s.id for s in SOURCES]


@pytest.mark.parametrize("src", SOURCES, ids=IDS)
def test_every_builtin_source_describes_itself(src: Any) -> None:
    about = about_of(src)
    assert isinstance(about, SourceAbout), (
        f"{src.id}: без `about` джерело не каже, де його межі й що доводить "
        f"його нуль, — і в маршруті агента стоїть навмання")
    for field in ("answers", "gives", "not_gives", "zero_means", "where_class"):
        assert str(getattr(about, field)).strip(), f"{src.id}: порожнє `{field}`"


@pytest.mark.parametrize("src", SOURCES, ids=IDS)
def test_every_builtin_source_has_a_card(src: Any) -> None:
    """🔴 Саме цієї перевірки бракувало `volok`."""
    headers = re.findall(r"^### Канал: .*$", CHANNELS.read_text(encoding="utf-8"),
                         flags=re.MULTILINE)
    key = _key(src)
    assert any(f"`{key}`" in h for h in headers), (
        f"{src.id}: немає картки `### Канал: … `{key}`` у where-to-dig-channels.md")


@pytest.mark.parametrize("src", SOURCES, ids=IDS)
def test_class_is_a_row_of_the_table_that_names_the_source(src: Any) -> None:
    about = about_of(src)
    assert about is not None
    rows = _class_rows()
    assert about.where_class in rows, (
        f"{src.id}: клас «{about.where_class}» не є рядком таблиці «Класи каналів» — "
        f"агент не зведе джерело з маршрутом жанру")
    assert f"`{_key(src)}`" in rows[about.where_class], (
        f"{src.id}: рядок класу «{about.where_class}» не називає джерела")


@pytest.mark.parametrize("src", SOURCES, ids=IDS)
def test_what_it_matches_agrees_with_what_it_can(src: Any) -> None:
    about = about_of(src)
    assert about is not None
    searches = "search" in src.caps
    assert searches == bool(about.match_on), (
        f"{src.id}: `search` у caps і `match_on` мусять казати одне")
    assert set(about.match_on) <= set(get_args(MatchOn))
    if about.match_on:
        assert about.match_how in get_args(MatchHow)
    else:
        assert about.match_how is None


@pytest.mark.parametrize("src", SOURCES, ids=IDS)
def test_declared_archives_are_codes_of_the_pack(src: Any) -> None:
    from nyshporka.archives import active

    about = about_of(src)
    assert about is not None
    scope: SourceScope = about.scope
    for code in scope.archives or ():
        assert code in active().repositories, f"{src.id}: архіву {code} немає в паку"
    if scope.years and None not in scope.years:
        lo, hi = scope.years
        assert lo is not None and hi is not None and lo <= hi


class _Plugin:
    """Сторонній плагін, який про самоопис нічого не знає."""

    id = "x-plugin"
    label = "Сторонній"
    caps = frozenset({"search"})

    def search(self, q: str, *, limit: int = 30) -> list[Any]:
        return []


class _Described(_Plugin):
    id = "x-described"
    about = SourceAbout(answers="питання", gives="щось", not_gives="інше",
                        where_class="фотоархів дослідника", scope=SourceScope(),
                        match_on=("title",), match_how="substring",
                        zero_means="у назвах немає")


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka.sources import registry

    monkeypatch.setattr(registry, "_from_entry_points",
                        lambda: ([_Plugin(), _Described()], []))


def test_sources_list_carries_about_and_names_the_undeclared(plugins: None) -> None:
    from nyshporka.core.ops import NoArgs
    from nyshporka.ops_builtin import sources_list

    env = sources_list(NoArgs())
    rows = {r["id"]: r for r in env.data["sources"]}
    assert rows["x-plugin"]["about"] is None
    assert env.data["undeclared"] == ["x-plugin"], (
        "джерело без опису мусить бути назване, а не мовчки пропущене")
    assert any(w.code == "source_undeclared" and "x-plugin" in w.text
               for w in env.warnings)
    assert rows["volok"]["about"]["where_class"] == "фотоархів дослідника"
    assert rows["volok"]["about"]["zero_means"]


def test_a_total_zero_says_what_each_zero_proves(plugins: None) -> None:
    from nyshporka.ops_builtin import CatalogSearchArgs, catalog_search

    env = catalog_search(CatalogSearchArgs(q="щосьтакенемає", source="x-described",
                                           by_address=False))
    cov = env.data["coverage"]
    assert cov["zeros"] == [{"source": "x-described", "means": "у назвах немає"}]
    assert cov["basis"][0]["match"] == ["title"]
    warned = [w for w in env.warnings if w.code == "zero_with_denominator"]
    assert warned and "у назвах немає" in warned[0].text


def test_an_undeclared_zero_says_so(plugins: None) -> None:
    from nyshporka.ops_builtin import CatalogSearchArgs, catalog_search

    env = catalog_search(CatalogSearchArgs(q="щосьтакенемає", source="x-plugin",
                                           by_address=False))
    zero = env.data["coverage"]["zeros"][0]
    assert zero["source"] == "x-plugin" and "не задекларувало" in zero["means"]
