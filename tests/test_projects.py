"""Проєкти Майстерні: тека проєкту знаходить хаб, чистий хаб не має проєкту,
сусідній проєкт відкривається лише для читання.

Помилка тут не падає голосно: сесія в роді дружини, що тихо резолвиться в
корінь хаба, писала б її вердикти в канон іншого роду.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nyshporka.core import projects as P
from nyshporka.core import workspace as W


def _hub(tmp_path: Path, *, hub_only: bool = False, extra: str = "") -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    flag = "hub_only = true\n" if hub_only else ""
    (hub / W.MARKER).write_text(
        f'[workspace]\nname = "Майстерня"\nkeys = 2\npreset = "lab"\n{flag}{extra}',
        encoding="utf-8")
    return hub


def _project(hub: Path, pid: str, body: str = "") -> Path:
    root = hub / W.PROJECTS_DIR / pid
    root.mkdir(parents=True)
    (root / W.MARKER).write_text(f'[project]\nname = "Рід {pid}"\nkind = "family"\n{body}',
                                 encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def test_project_folder_resolves_to_project_with_hub(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    hub = _hub(tmp_path, extra='text_store = "store"\n')
    alpha = _project(hub, "alpha")
    (alpha / "reports").mkdir()
    monkeypatch.chdir(alpha / "reports")
    ws = W.resolve()
    assert (ws.root, ws.hub, ws.project) == (alpha, hub, "alpha")
    assert ws.raw == hub / "data" / "raw"
    assert ws.canonical == alpha / "data" / "canonical"
    assert ws.text_store_dir == hub / "store"
    assert ws.name == "Рід alpha"
    # Профіль секцій без власного — від Майстерні.
    assert ws.profile[0] == "lab"


def test_project_own_preset_wins(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha", 'preset = "researcher"\n')
    ws = W._build(alpha, "test")
    assert ws.preset == "researcher"
    assert ws.profile[0] == "researcher"


def test_project_outside_projects_dir_is_refused(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    stray = hub / "elsewhere" / "alpha"
    stray.mkdir(parents=True)
    (stray / W.MARKER).write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(W.WorkspaceError, match="projects"):
        W._build(stray, "test")


def test_pure_hub_has_no_project_layer(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    ws = W._build(hub, "test")
    assert ws.raw == hub / "data" / "raw"          # Майстерня — так
    for name in ("canonical", "config", "reports", "project_derived", "clan_hunt"):
        with pytest.raises(W.NoProjectError, match="--project"):
            getattr(ws, name)


def test_legacy_space_keeps_project_in_root(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    ws = W._build(hub, "test")
    assert ws.project is None and not ws.hub_only
    assert ws.canonical == hub / "data" / "canonical"


def test_list_projects_and_archive(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _project(hub, "alpha")
    _project(hub, "beta", "archived = true\n")
    (hub / W.PROJECTS_DIR / "notes").mkdir()       # не проєкт — без маркера
    assert [p.id for p in P.list_projects(hub)] == [".", "alpha"]
    assert [p.id for p in P.list_projects(hub, archived=True)] == [".", "alpha", "beta"]
    pure = _hub(tmp_path / "x", hub_only=True)
    assert P.list_projects(pure) == []


@pytest.mark.parametrize("bad", ["Alpha", "рід", "a b", "a:b", "-a", ""])
def test_bad_names_refused(bad: str) -> None:
    with pytest.raises(P.ProjectError):
        P.check_name(bad)


def test_neighbour_from_project_is_readonly(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    here = W._build(alpha, "test")
    other = P.open_project("beta", here)
    assert other.root == beta and other.readonly
    assert not P.open_project("alpha", here).readonly
    root_proj = P.open_project(".", here)
    assert root_proj.root == hub and root_proj.readonly
    # З кореня Майстерні — міжпроєктний режим, запис дозволено.
    assert not P.open_project("beta", W._build(hub, "test")).readonly
    with pytest.raises(P.ProjectError, match="Є:"):
        P.open_project("gamma", here)


def test_readonly_refuses_mutating_ops(tmp_path: Path) -> None:
    from nyshporka.core.ops import Op, _readonly_refusal

    hub = _hub(tmp_path)
    _project(hub, "alpha")
    _project(hub, "beta")
    W.use(P.open_project("beta", W._build(hub / "projects" / "alpha", "test")))
    writer = Op(name="x.write", summary="", fn=lambda a: None, mutates=True)  # type: ignore[arg-type,return-value]
    reader = Op(name="x.read", summary="", fn=lambda a: None)  # type: ignore[arg-type,return-value]
    assert "лише для читання" in (_readonly_refusal(writer) or "")
    assert _readonly_refusal(reader) is None


def test_section_write_goes_to_project_table(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    W.set_sections(["core", "material"])
    got = W._read_toml(alpha / W.MARKER)
    assert got["project"]["preset"] == "catalog"
    assert "workspace" not in got
    assert "catalog" not in (hub / W.MARKER).read_text(encoding="utf-8")


def test_case_root_written_to_hub_marker(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    arch = tmp_path / "arch" / "scans"
    arch.mkdir(parents=True)
    W.use(W._build(alpha, "test"))
    W.add_case_root(arch)
    assert "scans" in (hub / W.MARKER).read_text(encoding="utf-8")
    assert "scans" not in (alpha / W.MARKER).read_text(encoding="utf-8")


#: Маркер, яким його лишає `nysh init` з історією: таблиця `[history]` — у хвості.
_INIT_MARKER = ('[workspace]\nschema = 1\nkeys = 2\nname = "Нишпорка"\n\n'
                '# Скани, що лежать поза простором (зовнішній диск, мережева теку):\n'
                '# case_roots = ["D:/архів"]\n\n'
                '# Історія простору (`nysh history`): локальний git,\n'
                '[history]\n\nauto = true\n')


def test_case_root_lands_in_workspace_table_after_init(tmp_path: Path) -> None:
    """🔴 Свіжий простір закінчується таблицею `[history]`.

    Рядок, дописаний у кінець файлу, лягав туди, і корінь не читав ніхто:
    «У мене є скани» з текою на робочому столі давало «✓» над порожньою
    Бібліотекою (прохід новачка 23.10.2026).
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text(_INIT_MARKER, encoding="utf-8")
    scans = tmp_path / "Desktop" / "Скани"
    scans.mkdir(parents=True)
    W.use(W._build(hub, "test"))
    W.add_case_root(scans)
    got = W._read_toml(hub / W.MARKER)
    assert got["workspace"]["case_roots"] == [str(scans).replace("\\", "/")]
    assert "case_roots" not in got["history"]
    assert got["history"]["auto"] is True
    assert scans in W._build(hub, "test").extra_case_roots


def test_case_root_stuck_in_history_is_read_and_moved(tmp_path: Path) -> None:
    """Корінь, оголошений консоллю до 0.37, лежить у `[history]` — читається й так.

    Наступне оголошення переносить його в `[workspace]`, а не губить.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    stuck = _INIT_MARKER + f'case_roots = ["{str(old).replace(chr(92), "/")}"]\n'
    (hub / W.MARKER).write_text(stuck, encoding="utf-8")
    assert old in W._build(hub, "test").extra_case_roots
    W.use(W._build(hub, "test"))
    W.add_case_root(new)
    got = W._read_toml(hub / W.MARKER)
    assert len(got["workspace"]["case_roots"]) == 2
    assert "case_roots" not in got["history"]
    W.use(W._build(hub, "test"))
    assert W.remove_case_root(old)
    assert W._read_toml(hub / W.MARKER)["workspace"]["case_roots"] == [
        str(new).replace("\\", "/")]


def test_marker_set_touches_only_its_table(tmp_path: Path) -> None:
    text = '[workspace]\nname = "x"\n\n[history]\nauto = true\n'
    out = W._marker_set(text, "auto", "auto = false")
    assert W.tomllib.loads(out) == {"workspace": {"name": "x", "auto": False},
                                    "history": {"auto": True}}


def test_peek_counts_only(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    for root, text in ((alpha, "Сидорук Іван\n"), (beta, "Сидорук Петро\nСидорук Олена\n"),
                       (hub, "Сидорук Степан\n")):
        (root / "data" / "canonical").mkdir(parents=True)
        (root / "data" / "canonical" / "P1.md").write_text(text, encoding="utf-8")
    got = P.peek(W._build(alpha, "test"), re.compile("Сидорук"))
    assert {(g["project"], g["layer"], g["count"]) for g in got} == {
        ("beta", "canon", 2), (".", "canon", 1)}
    assert all(set(g) == {"project", "name", "layer", "count"} for g in got)


# ── докази: файл у Майстерні, цитата в проєкті ───────────────────────────────
def test_citation_from_project_canon_resolves_from_hub(tmp_path: Path) -> None:
    from nyshporka.canon import check as C
    from nyshporka.canon import refs

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    ref = "data/source/citations/dahmo/row.jpg"
    (hub / ref).parent.mkdir(parents=True)
    (hub / ref).write_bytes(b"x")
    assert refs.resolve(alpha, ref) == hub / ref
    assert C._resolves(refs.resolver(alpha), ref)
    # нотатка проєкту — від проєкту
    assert refs.resolve(alpha, "reports/x.md") == alpha / "reports/x.md"
    # резолвер на весь прохід перевірки веде туди само, що й `resolve`
    one = refs.resolver(alpha)
    assert one(ref) == hub / ref
    assert one(r"reports\x.md") == alpha / "reports/x.md"
    assert C.manifest_path(alpha) == hub / "data/source/citations/MANIFEST_citations.json"


def test_cited_by_of_two_projects_do_not_clobber(tmp_path: Path) -> None:
    import json

    from nyshporka.canon import evidence as E
    from nyshporka.canon import refs

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    shared, mine = "data/source/citations/d/a.jpg", "data/source/citations/d/b.jpg"
    man = hub / "data/source/citations/MANIFEST_citations.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({shared: {"secured_to": shared, "cited_by": ["I1001.md"]},
                               mine: {"secured_to": mine, "cited_by": []}}),
                   encoding="utf-8")
    card = alpha / "data/canonical/persons/I1001.md"
    card.parent.mkdir(parents=True)
    card.write_text(f"доказ: `{shared}`\n", encoding="utf-8")
    got = E.refresh_cited_by(alpha, {"I1001": card})
    recs = json.loads(man.read_text(encoding="utf-8"))
    assert recs[shared]["cited_by"] == ["I1001.md", "alpha:I1001.md"]
    # доказ, на який посилається лише корінь, — не «без посилань» для alpha
    assert got["unreferenced"] == [mine]
    assert refs.own_cited(alpha, recs[shared]["cited_by"]) == ["I1001.md"]
    assert refs.own_cited(hub, recs[shared]["cited_by"]) == ["I1001.md"]


def test_project_journals_live_in_the_project(tmp_path: Path) -> None:
    from nyshporka.search import textops, trace

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    assert trace.path() == alpha / "data/derived/search_log.json"
    assert textops._verdicts_path() == alpha / "data/derived/verdicts.json"


def test_search_from_the_bare_hub_has_no_trace_and_no_canon(tmp_path: Path) -> None:
    """🔴 Пошук із кореня Майстерні (консоль «без проєкту») падав відмовою
    «вкажіть проєкт»: читав слід «прошукано» й канон роду, яких у Майстерні
    немає (23.10.2026). Слово, село, чуже прізвище шукаються й без роду — сліду
    тоді немає взагалі: ні читається, ні пишеться."""
    from nyshporka.pagestore.store import CaseRef
    from nyshporka.search import selfcheck, trace

    hub = _hub(tmp_path, hub_only=True)
    _project(hub, "alpha")
    W.use(W._build(hub, "test"))
    with pytest.raises(W.NoProjectError):
        trace.path()
    assert trace.of("DAVO/904/24/1") == [] and trace.searched() == {}
    trace.note("DAVO/904/24/1", q="Сидорук", thresh=78, hits=1, pages=1,
               models=["m"], channels=["surname"])
    with trace.batch():
        trace.note("DAVO/904/24/2", q="Сидорук", thresh=78, hits=1, pages=1,
                   models=["m"], channels=["surname"])
    assert not list(hub.rglob("search_log.json")), "у Майстерні слід не пишеться"
    ref = CaseRef(key="DAVO/904/24/1", repo="DAVO", fond="904", spr="1", opys="24")
    assert selfcheck.canon_pages("Сидорук", ref, 78) == set()


def test_text_grep_in_project_sees_own_canon_and_only_counts_others(tmp_path: Path) -> None:
    from nyshporka import ops as O

    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    for root, text in ((alpha, "Сидорук Іван, 1800\n"), (beta, "Сидорук Петро, 1801\n")):
        (root / "data" / "canonical" / "persons").mkdir(parents=True)
        (root / "data" / "canonical" / "persons" / "I1001.md").write_text(text, encoding="utf-8")
    W.use(W._build(alpha, "test"))
    env = O.call("text.grep", {"pattern": "Сидорук", "where": "canon"})
    assert env.ok, env
    lines = [h["line"] for h in env.data["hits"]]
    assert lines == ["Сидорук Іван, 1800"], "чужий канон потрапив у вивід"
    assert "Петро" not in str(env.data)
    assert env.data["elsewhere"] == [
        {"project": "beta", "name": "Рід beta", "layer": "canon", "count": 1}]


# ── nysh project … ───────────────────────────────────────────────────────────
def test_project_new_lays_out_agent_files(tmp_path: Path) -> None:
    import json

    from nyshporka import ops as O

    hub = _hub(tmp_path)
    (hub / ".claude").mkdir()
    (hub / ".claude" / "settings.json").write_text(json.dumps({
        "skillOverrides": {"find-surname": "off"},
        "hooks": {"PreToolUse": []}}), encoding="utf-8")
    W.use(W._build(hub, "test"))
    env = O.call("project.new", {"name": "rid-b", "title": "Рід Б", "surname": "Сидорук"})
    assert env.ok, env.error
    root = hub / "projects" / "rid-b"
    for rel in ("nyshporka.toml", "CLAUDE.md", "AGENTS.md", ".claude/settings.json",
                ".codex/hooks.json", ".codex/config.toml", "notes/agent-memory.md",
                "config/research_profile.yaml", ".nysh-project.json"):
        assert (root / rel).is_file(), rel
    assert not (hub / "config" / "research_profile.yaml").exists(), "профіль ліг у хаб"
    st = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    assert st["autoMemoryDirectory"].endswith("/memory")
    assert "rid-b" in st["autoMemoryDirectory"]
    cmd = st["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert cmd.endswith("project status --agent")
    assert st["skillOverrides"] == {"find-surname": "off"}
    assert any(w.code == "hub_hooks" for w in env.warnings)
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "nysh project status --agent" in agents.split("\n\n")[1]
    assert "rid-b" in agents and "$" not in agents
    # старий простір: хабових інструкцій не дописуємо — у нього свої
    assert not (hub / "AGENTS.md").exists()
    ws = W._build(root, "test")
    assert ws.project == "rid-b" and ws.name == "Рід Б"
    again = O.call("project.new", {"name": "rid-b"})
    assert not again.ok and "уже є" in (again.error or "")


def test_pure_hub_gets_hub_instructions_and_refuses_project_layer(tmp_path: Path) -> None:
    from nyshporka import ops as O

    hub = _hub(tmp_path, hub_only=True)
    W.use(W._build(hub, "test"))
    assert O.call("project.new", {"name": "alpha", "kind": "order"}).ok
    assert "Майстерня" in (hub / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Замовлення" in (hub / "projects/alpha/CLAUDE.md").read_text(encoding="utf-8")
    env = O.call("canon.next")
    assert not env.ok and "--project" in (env.error or "")
    st = O.call("project.status")
    assert st.ok and st.data["project"] is None and "alpha" in st.data["text"]


def test_status_for_agent_fits_the_budget(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from nyshporka import ops as O
    from nyshporka import ops_project as OP
    from nyshporka import project as T

    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    _project(hub, "beta")
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    mem = T.memory_dir(hub)
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("- правило Майстерні\n" * 5000, encoding="utf-8")
    W.use(W._build(alpha, "test"))
    text = O.call("project.status", {"agent": True}).data["text"]
    assert len(text) <= OP.AGENT_BUDGET
    assert text.startswith("📁 Проєкт «alpha»")
    assert "beta" in text and "правило Майстерні" in text
    plain = O.call("project.status").data["text"]
    assert "правило Майстерні" not in plain and len(plain) <= OP.STATE_BUDGET


def test_sync_updates_untouched_and_keeps_edited(tmp_path: Path) -> None:
    import json

    from nyshporka import project as T

    hub = _hub(tmp_path)
    made = T.create(hub, "alpha", version="0.1.0")
    root = made.root
    (root / "CLAUDE.md").write_text("моє\n", encoding="utf-8")            # людина правила
    led = json.loads((root / T.LEDGER).read_text(encoding="utf-8"))
    (root / "AGENTS.md").write_text("стара версія шаблону\n", encoding="utf-8")
    led["files"]["AGENTS.md"] = T._sha("стара версія шаблону\n")         # поклав пакет
    (root / T.LEDGER).write_text(json.dumps(led), encoding="utf-8")
    got = T.sync(root, "0.2.0")
    assert got["CLAUDE.md"] == "kept" and got["AGENTS.md"] == "updated"
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "моє\n"
    assert "nysh project status" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert T.sync(root, "0.2.0") == {}                                    # та сама версія


def test_archive_hides_from_list_and_peek(tmp_path: Path) -> None:
    from nyshporka import ops as O

    hub = _hub(tmp_path)
    _project(hub, "alpha")
    W.use(W._build(hub, "test"))
    assert O.call("project.archive", {"name": "alpha"}).ok
    assert [p.id for p in P.list_projects(hub)] == ["."]
    assert P._from_dir(hub / "projects" / "alpha").archived  # type: ignore[union-attr]
    assert O.call("project.archive", {"name": "alpha", "undo": True}).ok
    assert [p.id for p in P.list_projects(hub)] == [".", "alpha"]


def test_project_color_glyph_and_variants(tmp_path: Path) -> None:
    """Колір і знак — у маркері проєкту; варіанти прізвища — одразу в профіль."""
    import yaml

    from nyshporka import ops as O

    hub = _hub(tmp_path, hub_only=True)
    W.use(W._build(hub, "test"))
    env = O.call("project.new", {"name": "rid-s", "surname": "Сидорук",
                                 "variants": ["Sydoruk", " "], "color": "#8a5a2b",
                                 "glyph": "С"})
    assert env.ok, env.error
    # Парадигма — за закінченням, а не завжди `adj_skyi` («Сидорского»).
    assert env.data["profile"]["paradigm"] == "noun_bare"
    rows = {r["id"]: r for r in O.call("project.list").data["projects"]}
    assert (rows["rid-s"]["color"], rows["rid-s"]["glyph"]) == ("#8a5a2b", "С")
    # Огляд проєкту в консолі бере колір і знак зі статусу проєкту.
    W.use(W._build(hub / "projects/rid-s", "test"))
    stat = O.call("project.status").data
    assert (stat["color"], stat["glyph"]) == ("#8a5a2b", "С")
    W.use(W._build(hub, "test"))
    prof = yaml.safe_load((hub / "projects/rid-s/config/research_profile.yaml")
                          .read_text(encoding="utf-8"))
    one = next(iter(prof["profiles"].values()))
    assert one["surname"]["substrings"] == ["Sydoruk"]
    for bad in ({"color": "red"}, {"glyph": "Сидорук"}):
        got = O.call("project.new", {"name": "rid-x", **bad})
        assert not got.ok and not (hub / "projects/rid-x").exists(), bad
    st = O.call("project.style", {"name": "rid-s", "color": "", "glyph": "🌳"})
    assert st.ok and (st.data["color"], st.data["glyph"]) == ("", "🌳")
    assert "color" not in (hub / "projects/rid-s/nyshporka.toml").read_text(encoding="utf-8")
    # Назва для людини: перенесення роду лишало в ній id, і консоль скрізь
    # показувала id проєкту (22.10.2026). Порожня назва нічого не стирає.
    st = O.call("project.style", {"name": "rid-s", "title": "Рід Сидоруків"})
    assert st.ok and st.data["title"] == "Рід Сидоруків"
    assert O.call("project.style", {"name": "rid-s", "title": "  "}).data["title"] == "Рід Сидоруків"
    assert {r["id"]: r for r in O.call("project.list").data["projects"]}["rid-s"]["name"] == "Рід Сидоруків"


def test_a_broken_color_in_the_marker_does_not_break_the_list(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    _project(hub, "rid-a", 'color = "червоний"\nglyph = "ааа"\n')
    pr = P.list_projects(hub)[0]
    assert (pr.id, pr.color, pr.glyph) == ("rid-a", "", "")
