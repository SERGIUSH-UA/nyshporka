"""🧭 Карта команд для агента: повнота метаданих, межа запису, фільтри, пошук.

Хвиля К: агент знає ядро («ситуація → команда») з хука старту, а решту
знаходить `nysh ops find`. Обидва шари тримаються метаданими в одному місці —
`@op(tier=, when=, skill=, scope=)` і `@route(...)` для друкованих команд поза
реєстром. Тест повноти тут головний: новий листок без метаданих інакше тихо
випадав би і з карти, і з пошуку, і з межі `readonly`.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import re
from pathlib import Path

import pytest
import typer

from nyshporka import cli as C
from nyshporka import ops as O
from nyshporka.core import routemap as M
from nyshporka.core import routes as R
from nyshporka.core import workspace as W

pytestmark = pytest.mark.real_paths

_CALL = re.compile(r"""O\.call\(\s*["'][a-z_]+\.[a-z_]+["']""")


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def _leaves() -> dict[str, typer.models.CommandInfo]:
    out: dict[str, object] = {}

    def walk(cmd: object, path: list[str]) -> None:
        subs = getattr(cmd, "commands", None)
        if subs is not None:
            for name, sub in subs.items():
                walk(sub, [*path, name])
            return
        out[" ".join(path)] = cmd

    walk(typer.main.get_command(C.app), [])
    return out  # type: ignore[return-value]


def _ro(root: Path) -> W.Workspace:
    """Простір лише для читання — як `nysh --project Y` з іншого проєкту."""
    return dataclasses.replace(W._build(root, "test"), readonly=True)


def _hub(tmp_path: Path, extra: str = "") -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    (hub / W.MARKER).write_text(
        f'[workspace]\nname = "Майстерня"\nkeys = 2\n{extra}', encoding="utf-8")
    return hub


# ── повнота ──────────────────────────────────────────────────────────────────
def test_every_cli_leaf_is_an_op_wrapper_a_route_or_exempt() -> None:
    """Листок, що пише повз реєстр без `@route`, обходив би і карту, і `readonly`."""
    bare = []
    for path, cmd in _leaves().items():
        if path in R.EXEMPT or path in R.ROUTES:
            continue
        src = inspect.getsource(inspect.unwrap(cmd.callback))  # type: ignore[attr-defined]
        if not _CALL.search(src):
            bare.append(path)
    assert not bare, f"листки без оп і без @route: {bare}"


def test_routes_point_at_real_leaves_and_ops() -> None:
    leaves = _leaves()
    for cli, r in R.ROUTES.items():
        assert cli in leaves, f"@route «{cli}» — такої команди немає"
        if r.op:
            assert O.get(r.op) is not None, f"@route «{cli}»: оп «{r.op}» немає"


def test_when_skill_scope_are_filled_where_they_must_be() -> None:
    from nyshporka.skills import available

    skills = {s.name for s in available()}
    for e in M.entries():
        if e.tier in ("core", "situational"):
            assert e.when.strip(), f"«{e.name}» ({e.tier}) без when — його не знайде ops find"
        assert len(e.when) <= 100, f"«{e.name}»: when довший за рядок карти"
        if e.skill:
            assert e.skill in skills, f"«{e.name}»: скіла «{e.skill}» у пакеті немає"


# Дизайн багатопроєктності, розд. 7: проєктні й змішані дії.
PROJECT = {"text.sheet", "text.verdicts", "library.verdict",
           "canon.check", "canon.import", "canon.index", "canon.new_id", "canon.next",
           "site.build", "site.rebuild", "site.status",
           "profile.set", "profile.show", "profile.source",
           "sections.set", "sections.show",
           "migrate.done", "migrate.scan", "migrate.status"}
MIXED = {"cases.list", "text.grep", "text.whatis", "text.coverage", "text.find",
         "search.run", "search.find", "pages.note", "pages.note_batch", "pages.show",
         "pages.status", "evidence.add", "home.pulse", "workspace.info", "project.status"}


def test_op_scope_matches_the_design_table() -> None:
    got_p = {o.name for o in O.all_ops() if o.scope == "project"}
    got_m = {o.name for o in O.all_ops() if o.scope == "mixed"}
    assert got_p == PROJECT
    assert got_m == MIXED


def test_core_is_grouped_and_groups_hold_only_core() -> None:
    core = {e.name for e in M.entries() if e.tier == "core"}
    grouped = {n for _, names in M.GROUPS for n in names}
    assert grouped == core, (f"поза групами: {core - grouped}; "
                             f"у групах не ядро: {grouped - core}")
    assert {o.name for o in O.for_agent()} <= core


def test_friendly_form_prefers_the_printed_command() -> None:
    assert R.friendly("text.find") == "nysh text find"
    assert R.friendly("acquire.start") == "nysh get"
    assert R.friendly("search.run") == "nysh search", "основна форма, не `pages grep`"
    assert R.friendly("disk.report") == "nysh op disk.report"
    try:                       # неосновна обгортка, оголошена першою, не перемагає
        R.route("zz alias", op="zz.fake", primary=False)(lambda: None)
        R.route("zz main", op="zz.fake")(lambda: None)
        assert R.friendly("zz.fake") == "nysh zz main"
    finally:
        R.ROUTES.pop("zz alias", None)
        R.ROUTES.pop("zz main", None)


# ── межа запису ──────────────────────────────────────────────────────────────
def test_mutating_route_refuses_in_a_read_only_project(tmp_path: Path) -> None:
    """`cases build` пише повз реєстр: без обгортки `--project Y` його не зупиняв."""
    build = _leaves()["cases build"].callback  # type: ignore[attr-defined]
    W.use(_ro(_hub(tmp_path)))
    with pytest.raises(typer.Exit):
        build()


def test_route_guard_passes_when_writable(tmp_path: Path) -> None:
    calls = []

    def body() -> str:
        calls.append(1)
        return "ok"

    name = "zz-test route"
    try:
        guarded = R.route(name, tier="rare", mutates=True)(body)
        W.use(W._build(_hub(tmp_path), "test"))
        assert guarded() == "ok" and calls == [1]
        W.use(_ro(tmp_path / "hub"))
        with pytest.raises(typer.Exit):
            guarded()
        assert calls == [1]
    finally:
        R.ROUTES.pop(name, None)


# ── карта ────────────────────────────────────────────────────────────────────
def test_map_fits_budget_and_lists_core(tmp_path: Path) -> None:
    W.use(W._build(_hub(tmp_path, 'preset = "lab"\n'), "test"))
    text = M.agent_map()
    assert len(text) <= M.MAP_BUDGET
    for cmd in ("nysh text find", "nysh read", "nysh cloud go", "nysh ops find"):
        assert f"  {cmd} — " in text
    assert "nysh train view" not in text, "ситуативне в карту не йде"
    assert "карту обрізано" in M.agent_map(400)


def test_map_hides_disabled_section_read_only_writes_and_project_layer(
        tmp_path: Path) -> None:
    hub = _hub(tmp_path, 'preset = "catalog"\n')
    W.use(W._build(hub, "test"))
    text = M.agent_map()
    assert "nysh find —" in text
    assert "nysh cloud go" not in text and "nysh text grep" not in text, \
        "секції htr/research вимкнено"

    W.use(_ro(hub))
    assert "nysh get —" not in M.agent_map(), "лише читання ховає запис"

    (hub / W.MARKER).write_text('[workspace]\nname = "М"\nkeys = 2\nhub_only = true\n'
                                'preset = "lab"\n', encoding="utf-8")
    W.reset()
    W.use(W._build(hub, "test"))
    text = M.agent_map()
    assert "nysh canon next" not in text, "чистий хаб: проєктного шару немає"
    assert "nysh text grep" in text


# ── пошук ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("query", "want"), [
    ("залити справу в Супрягу", "nysh share push"),
    ("де метрики села", "nysh geog find"),
    ("зупинити оренду карти", "nysh cloud stop"),
    ("хмарний прогін великої справи", "nysh cloud go"),
    ("чи був уже прогін справи", "nysh op runs.list"),
    ("словник власних назв для арбітрів", "nysh train glossary"),
    ("скільки місця на диску", "nysh op disk.report"),
    ("відкликати запис нотатника", "nysh note retract"),
    ("таблиця Excel зі справи", "nysh export case"),
    ("сусідні села", "nysh geog near"),
    ("знайти прізвище в прочитаному", "nysh text find"),
    ("кроп рядка", "nysh text crop"),
])
def test_find_puts_the_right_command_in_top_three(tmp_path: Path, query: str,
                                                  want: str) -> None:
    W.use(W._build(_hub(tmp_path, 'preset = "lab"\n'), "test"))
    top = [e.cli for e, _ in M.find(query, limit=3)]
    assert want in top, f"{query!r} → {top}"


def test_find_matches_word_forms() -> None:
    """«прогону» / «прогін» / «прогони» — один префікс."""
    assert M._stems("прогону") == M._stems("прогони") == ["прого"]
    assert M._match("прогі", {"прогі"})
    assert not M.find("")


# ── хук ──────────────────────────────────────────────────────────────────────
def test_status_for_agent_carries_map_and_optional_memory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops_project as OP

    monkeypatch.setattr(OP, "_hub_memory", lambda hub: "ПАМ'ЯТЬ-МАЙСТЕРНІ " * 50)
    W.use(W._build(_hub(tmp_path, 'preset = "lab"\n'), "test"))
    full = O.call("project.status", {"agent": True}).data["text"]
    bare = O.call("project.status", {"agent": True, "no_memory": True}).data["text"]
    assert "── Команди: ядро" in full and "── Команди: ядро" in bare
    assert "ПАМ'ЯТЬ-МАЙСТЕРНІ" in full and "ПАМ'ЯТЬ-МАЙСТЕРНІ" not in bare
    assert len(full) <= OP.AGENT_BUDGET
    assert full.index("── Команди") < full.index("ПАМ'ЯТЬ")


# ── private_default у завантажувачах ─────────────────────────────────────────
def test_loader_passport_in_order_project_is_private(tmp_path: Path) -> None:
    from nyshporka.cases.acquire import patch_meta
    from nyshporka.project import create

    hub = _hub(tmp_path)
    for pid, kind in (("rid", "family"), ("order-1", "order")):
        create(hub, pid, kind=kind, title=pid, version="0")
    raw = hub / "data" / "raw" / "dahmo_315"
    W.use(W._build(hub / "projects" / "order-1", "test"))
    a = patch_meta(raw / "spr-1", {"archive": "DAHMO"})
    assert json.loads(a.read_text(encoding="utf-8"))["private"] is True
    patch_meta(raw / "spr-1", {"private": False})
    patch_meta(raw / "spr-1", {"title": "x"})
    assert json.loads(a.read_text(encoding="utf-8"))["private"] is False, \
        "наявний паспорт позначка сама не чіпає"
    W.use(W._build(hub / "projects" / "rid", "test"))
    b = patch_meta(raw / "spr-2", {"archive": "DAHMO"})
    assert "private" not in json.loads(b.read_text(encoding="utf-8"))
