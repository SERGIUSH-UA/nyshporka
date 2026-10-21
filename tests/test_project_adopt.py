"""🧳 `nysh project adopt`: корінь старого типу → Майстерня + проєкт, і назад.

Помилка тут дорога й тиха. Переїзд, що загубив картку, лишив коментар
сторінки в корені чи зламав посилання на доказ, видно лише тоді, коли
наступна сесія не знайде того, що рід уже знав. Тому тут перевіряється не
«команда відпрацювала», а що після переїзду все на місці й перевіряється, а
відкат повертає дерево побайтно.

Рід і ID вигадані (`I9…`, «Сидорук»): ворота приватних даних шукають справжні.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest

from nyshporka.core import projects as P
from nyshporka.core import workspace as W
from nyshporka.models import Citation, Fact, Family, GedDate, NameVariant, Person, Source
from nyshporka.pagestore import store as S
from nyshporka.pagestore.models import PageNote
from nyshporka.project import adopt as A
from nyshporka.storage.files import write_entity

pytestmark = pytest.mark.real_paths

SRC = "S_TEST_BOOK"
REF = S.CaseRef(key="DAHMO/315/1/8433", repo="DAHMO", fond="315", spr="8433", opys="1")


def _person(pid: str, name: str, sex: str = "M", born: str = "1800", **kw: object) -> Person:
    fact = Fact(type="birth", date=GedDate(value=born), status="confirmed",
                citations=[Citation(source_id=SRC, confidence="direct",
                                    accessed=date(2026, 1, 1))])
    return Person(id=pid, names=[NameVariant(form=name, lang="uk", primary=True)],
                  sex=sex, facts=[fact], **kw)  # type: ignore[arg-type]


def _write(root: Path, kind: str, entity: object) -> Path:
    path = root / "data" / "canonical" / kind / f"{entity.id}.md"  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, entity)  # type: ignore[arg-type]
    return path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True).stdout.decode("utf-8")


def _tree(root: Path) -> dict[str, str]:
    """Відбиток дерева без службового: git, журнали переїзду й переносу поглядів."""
    skip = (".git/", "data/cases/adopt/", "data/cases/pages-split/")
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root).as_posix()
        if f.is_file() and not rel.startswith(skip):
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def _age(root: Path, seconds: float = 3600) -> None:
    """Файли «записано годину тому»: інакше ворота свіжих записів спрацюють на фікстурі."""
    old = time.time() - seconds
    for f in root.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            os.utime(f, (old, old))


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Своя «домашня» тека: копія пам'яті агента не має лягти в справжню."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """Корінь старого типу: канон, профіль, вердикти, коментар сторінки, прогін, git."""
    if shutil.which("git") is None:
        pytest.skip("git недоступний")
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text(
        '[workspace]\nname = "Тест"\nkeys = 2\n\n[adopt]\nextra = ["data/source/letters"]\n',
        encoding="utf-8")
    W.use(W._build(hub, "test"))
    _write(hub, "sources", Source(id=SRC, type="book", title="Тестова книга"))
    _write(hub, "persons", _person("I9001", "Іван", spouse_families=["F9001"]))
    _write(hub, "persons", _person("I9002", "Марія", "F", spouse_families=["F9001"],
                                   notes="Лист: `data/source/letters/l1.txt`"))
    _write(hub, "families", Family(id="F9001", husband="I9001", wife="I9002"))
    (hub / "data" / "source" / "letters").mkdir(parents=True)
    (hub / "data" / "source" / "letters" / "l1.txt").write_text("лист", encoding="utf-8")
    (hub / "config").mkdir()
    (hub / "config" / "research_profile.yaml").write_text("surname: Сидорук\n", encoding="utf-8")
    (hub / "config" / "archives.yaml").write_text("{}\n", encoding="utf-8")   # хабове
    (hub / "data" / "derived").mkdir(parents=True)
    (hub / "data" / "derived" / "verdicts.json").write_text("{}", encoding="utf-8")
    cit = hub / "data" / "source" / "citations"
    cit.mkdir(parents=True)
    (cit / "a.jpg").write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xD9]))
    (cit / "MANIFEST_citations.json").write_text(json.dumps(
        {"data/source/citations/a.jpg": {"cited_by": ["I9001.md"]}}), encoding="utf-8")
    S.annotate_pages(REF, [PageNote(scan="0001.jpg", page_type="birth",
                                    surnames=["Сидорук"], comment="портал: шукали",
                                    agent="test")])
    _git(hub, "init", "-q")
    _git(hub, "config", "user.email", "t")
    _git(hub, "config", "user.name", "t")
    _git(hub, "add", "-A")
    _git(hub, "commit", "-qm", "base")
    _age(hub)
    return hub


def test_plan_names_what_moves_and_what_would_dangle(legacy: Path) -> None:
    pl = A.plan(legacy, "rid")
    moved = {m.path for m in pl.moves}
    assert {"data/canonical", "config/research_profile.yaml", "data/derived/verdicts.json",
            "data/source/letters"} <= moved
    assert "config/archives.yaml" not in moved, "пак архівів — Майстерні"
    assert pl.problems == []
    assert pl.views["with_view"] == 1 and pl.views["marks"] == {"портал": 1}

    # Без `extra` тека з листом, на який посилається картка, їде сама.
    (legacy / W.MARKER).write_text('[workspace]\nname = "Тест"\nkeys = 2\n', encoding="utf-8")
    _age(legacy)
    pl = A.plan(legacy, "rid")
    assert "data/source/letters" in {m.path for m in pl.moves} and pl.problems == []

    # Лишена свідомо (`stay`) — посилання провисло б, і план про це каже.
    (legacy / W.MARKER).write_text('[workspace]\nname = "Тест"\nkeys = 2\n'
                                   '[adopt]\nstay = ["data/source/letters"]\n', encoding="utf-8")
    _age(legacy)
    pl = A.plan(legacy, "rid")
    assert any("data/source/letters/l1.txt" in p and "stay" in p for p in pl.problems)


def test_plan_refuses_uncommitted_work(legacy: Path) -> None:
    (legacy / "data" / "canonical" / "persons" / "I9001.md").write_text("правка",
                                                                         encoding="utf-8")
    assert any("незакомічене" in p for p in A.plan(legacy, "rid").problems)


def test_archive_must_live_outside_the_hub(legacy: Path) -> None:
    with pytest.raises(A.AdoptError, match="поза Майстернею"):
        A.apply(legacy, "rid", archive=legacy / "backup")
    assert not (legacy / "projects").exists()


def test_apply_moves_everything_and_rollback_restores_bytes(legacy: Path,
                                                            tmp_path: Path) -> None:
    from nyshporka import project as PR
    from nyshporka.canon import hook as H
    from nyshporka.canon.check import check

    hub_mem = PR.memory_dir(legacy)
    hub_mem.mkdir(parents=True)
    (hub_mem / "MEMORY.md").write_text("- [Рід](rid.md)\n", encoding="utf-8")
    before = _tree(legacy)
    got = A.apply(legacy, "rid", archive=tmp_path / "arch")
    rid = legacy / "projects" / "rid"

    # Пам'ять агента — копія в проєкт; у хабі лишилась.
    assert (PR.memory_dir(rid) / "MEMORY.md").read_text(encoding="utf-8").startswith("- [Рід]")
    assert (hub_mem / "MEMORY.md").is_file()
    assert got["after"] and got["memory"] == str(PR.memory_dir(rid))

    # Архів: усе, що поїхало, з переліком sha256.
    with zipfile.ZipFile(got["archive"]["zip"]) as z:
        names = set(z.namelist())
    assert "data/canonical/persons/I9001.md" in names and "_sha256.json" in names

    # Проєктне — у проєкті, хабове — на місці.
    assert (rid / "data" / "canonical" / "persons" / "I9001.md").is_file()
    assert not (legacy / "data" / "canonical").exists()
    assert (rid / "config" / "research_profile.yaml").is_file()
    assert (legacy / "config" / "archives.yaml").is_file()
    assert (rid / "data" / "source" / "letters" / "l1.txt").is_file()
    marker = W._read_marker(legacy / W.MARKER)
    assert marker["hub_only"] is True and marker["legacy_project"] == "rid"

    # Погляд на сторінку — у проєкті; перелік чужого — у журналі.
    W.reset()
    W.use(W._build(rid, "test"))
    assert S.load_case(REF).pages["0001.jpg"].comment == "портал: шукали"  # type: ignore[union-attr]
    journal = legacy / A.ADOPT_DIR / got["stamp"]
    assert "портал" in (journal / "foreign.tsv").read_text(encoding="utf-8")

    # Канон проєкту зелений, `cited_by` — з ім'ям проєкту, старі записи — «мої».
    assert [i for i in check(rid).issues if i.severity == "ERROR"] == []
    man = json.loads((legacy / "data" / "source" / "citations" / "MANIFEST_citations.json")
                     .read_text(encoding="utf-8"))
    assert man["data/source/citations/a.jpg"]["cited_by"] == ["rid:I9001.md"]
    assert P.tag_of(None) == "rid" and P.tag_of(".") == "rid"
    assert P.is_mine(None)

    # Хук канону бачить картку в підтеці.
    _write(rid, "persons", _person("I9003", "Петро", parent_family="F9404"))
    _git(legacy, "add", "-A")
    assert any("projects/rid" in p and "I9003" in p and "F9404" in p
               for p in H.problems(legacy))
    _git(legacy, "reset", "-q", "--", "projects/rid/data/canonical/persons/I9003.md")
    (rid / "data" / "canonical" / "persons" / "I9003.md").unlink()

    # Відкат — дерево побайтно як до.
    W.reset()
    W.use(W._build(legacy, "test"))
    A.rollback(legacy)
    W.reset()
    assert _tree(legacy) == before
    assert not (legacy / "projects").exists()
    assert not PR.memory_dir(rid).exists() and (hub_mem / "MEMORY.md").is_file()


def test_legacy_tag_without_move_stays_root(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text('[workspace]\nname = "Тест"\n', encoding="utf-8")
    W.use(W._build(hub, "test"))
    assert P.tag_of(None) == "." and P.tag() == "."


def test_machine_settings_live_in_the_hub_even_without_a_project(tmp_path: Path) -> None:
    """Хмара, Супряга, пак архівів, трен — не рід: чиста Майстерня мусить їх мати."""
    from nyshporka.archives import pack
    from nyshporka.catalog import store
    from nyshporka.cloud import ssh
    from nyshporka.share import profile
    from nyshporka.train import layout

    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text('[workspace]\nname = "М"\nhub_only = true\n', encoding="utf-8")
    W.use(W._build(hub, "test"))
    assert ssh.hosts_path().parent == hub / "config"
    assert profile.config_path().parent == hub / "config"
    assert pack.overlay_path().parent == hub / "config"
    assert layout.config_root() == hub / "config" / "train"
    assert layout.train_root() == hub / "data" / "train"
    assert store.own_path() == hub / "data" / "catalog" / "own.sqlite"


def test_project_pack_overlays_the_hub_pack(tmp_path: Path) -> None:
    from nyshporka.archives import pack

    hub = tmp_path / "hub"
    (hub / "config").mkdir(parents=True)
    (hub / W.MARKER).write_text('[workspace]\nname = "М"\n', encoding="utf-8")
    (hub / "config" / pack.WORKSPACE_PACK).write_text("{}\n", encoding="utf-8")
    rid = hub / W.PROJECTS_DIR / "rid"
    (rid / "config").mkdir(parents=True)
    (rid / W.MARKER).write_text('[project]\nname = "Рід"\n', encoding="utf-8")
    (rid / "config" / pack.WORKSPACE_PACK).write_text("{}\n", encoding="utf-8")
    W.use(W._build(rid, "test"))
    assert pack._overlay_paths() == [rid / "config" / pack.WORKSPACE_PACK,
                                     hub / "config" / pack.WORKSPACE_PACK]


def test_archive_that_does_not_verify_stops_before_any_move(
        legacy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Архів, що не звірився, — не копія: переїзд не починається."""
    monkeypatch.setattr(A, "_sha_member", lambda z, name: "0" * 64)   # в архіві «інше»
    with pytest.raises(A.AdoptError, match="не звірився"):
        A.apply(legacy, "rid", archive=tmp_path / "arch")
    assert (legacy / "data" / "canonical" / "persons" / "I9001.md").is_file()
    assert not (legacy / "projects").exists()
    assert "hub_only" not in W._read_marker(legacy / W.MARKER)


# ── міграція без переліку руками ─────────────────────────────────────────────
def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "ще")
    _age(root)


def test_reports_and_site_move_by_schema_htr_and_stay_remain(legacy: Path) -> None:
    """`reports/*` (крім `htr`) і сайт MkDocs їдуть самі; `stay` лишає своє, і всередині теки."""
    for rel in ("reports/research/a.md", "reports/research/chuzhe/b.md", "reports/htr/run/x.txt",
                "reports/delivery/z.md", "reports/llm_bench.json", "docs/index.md",
                "mkdocs.yml", "mkdocs.public.yml"):
        (legacy / rel).parent.mkdir(parents=True, exist_ok=True)
        (legacy / rel).write_text("x", encoding="utf-8")
    with (legacy / W.MARKER).open("a", encoding="utf-8") as fh:
        fh.write('stay = ["reports/delivery", "reports/llm_*", "reports/research/chuzhe"]\n')
    _commit(legacy)
    moved = {m.path for m in A.plan(legacy, "rid").moves}
    assert {"reports/research/a.md", "docs", "mkdocs.yml", "mkdocs.public.yml"} <= moved
    assert not any(m.startswith(("reports/htr", "reports/delivery", "reports/llm_",
                                 "reports/research/chuzhe")) for m in moved)
    assert "reports/research" not in moved, "тека з лишеним усередині їде поелементно"


def test_stay_inside_a_moving_dir_survives_apply_and_rollback(legacy: Path,
                                                               tmp_path: Path) -> None:
    for rel in ("reports/research/a.md", "reports/research/chuzhe/b.md"):
        (legacy / rel).parent.mkdir(parents=True, exist_ok=True)
        (legacy / rel).write_text("x", encoding="utf-8")
    with (legacy / W.MARKER).open("a", encoding="utf-8") as fh:
        fh.write('stay = ["reports/research/chuzhe"]\n')
    _commit(legacy)
    before = _tree(legacy)
    A.apply(legacy, "rid", archive=tmp_path / "arch")
    rid = legacy / "projects" / "rid"
    assert (rid / "reports" / "research" / "a.md").is_file()
    assert (legacy / "reports" / "research" / "chuzhe" / "b.md").is_file()
    assert not (rid / "reports" / "research" / "chuzhe").exists()
    W.reset()
    W.use(W._build(legacy, "test"))
    A.rollback(legacy)
    W.reset()
    assert _tree(legacy) == before


def test_someone_writing_right_now_stops_the_plan(legacy: Path) -> None:
    """Свіжий файл у шляхах переїзду — інша сесія пише; переносити з-під неї не можна."""
    f = legacy / "data" / "clan_hunt" / "state.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}", encoding="utf-8")
    _git(legacy, "add", "-A")
    _git(legacy, "commit", "-qm", "стан")          # закомічено, але щойно записано
    probs = A.plan(legacy, "rid").problems
    assert any("пишуть просто зараз" in p and "data/clan_hunt/state.json" in p for p in probs)
    _age(legacy)
    assert A.plan(legacy, "rid").problems == []


def test_archive_defaults_next_to_the_hub(legacy: Path) -> None:
    got = A.apply(legacy, "rid")
    zpath = Path(got["archive"]["zip"])
    assert zpath.parent == legacy.parent / "hub-adopt" and zpath.is_file()
    with zipfile.ZipFile(zpath) as z:
        assert "data/canonical/persons/I9001.md" in z.namelist()


def test_no_room_for_the_archive_stops_before_anything(legacy: Path, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "_free", lambda p: 10)
    probs = A.plan(legacy, "rid", archive=tmp_path / "arch").problems
    assert any("для архіву треба" in p and "--archive" in p for p in probs)
    with pytest.raises(A.AdoptError, match="для архіву треба"):
        A.apply(legacy, "rid", archive=tmp_path / "arch")
    assert not (legacy / "projects").exists()
    assert not (tmp_path / "arch").exists()


def test_existing_project_memory_is_not_overwritten(legacy: Path) -> None:
    from nyshporka import project as PR

    mem = PR.memory_dir(legacy / "projects" / "rid")
    mem.mkdir(parents=True)
    (mem / "x.md").write_text("чуже", encoding="utf-8")
    assert any("пам'ять агента" in p for p in A.plan(legacy, "rid").problems)


def test_hub_hooks_follow_into_the_project(tmp_path: Path) -> None:
    """Сторож команд Майстерні діє і в сесії проєкту — скриптом із хаба."""
    from nyshporka import project as PR

    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / W.MARKER).write_text('[workspace]\nname = "М"\nhub_only = true\n', encoding="utf-8")
    (hub / ".claude").mkdir()
    guard = {"type": "command", "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/g.sh"'}
    (hub / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "хабовий старт"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [guard]}]}}), encoding="utf-8")
    made = PR.create(hub, "rid")
    st = json.loads((made.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmd = st["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == 'bash "$CLAUDE_PROJECT_DIR/../../.claude/hooks/g.sh"'
    start = st["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert start.endswith("project status --agent"), "старт у проєкту свій"
    assert any("PreToolUse" in w for w in made.warnings)


def test_legacy_root_check_asks_only_when_a_second_project_exists(legacy: Path) -> None:
    from nyshporka import migrate as M

    assert M.CHECKS["legacy_root"](legacy).state == "n/a"
    (legacy / "projects" / "druzhyna").mkdir(parents=True)
    (legacy / "projects" / "druzhyna" / W.MARKER).write_text(
        '[project]\nname = "Рід дружини"\nkind = "family"\n', encoding="utf-8")
    got = M.CHECKS["legacy_root"](legacy)
    assert got.state == "todo" and "project adopt" in got.detail and "druzhyna" in got.detail
    A.apply(legacy, "rid")
    W.reset()
    assert M.CHECKS["legacy_root"](legacy).state == "n/a"


def test_ignored_file_on_the_way_does_not_break_git(legacy: Path, tmp_path: Path) -> None:
    """Шлях, якого git ніколи не бачив (`.gitignore`), не валить `git add` переїзду.

    Так упав перший переїзд живого кореня: `git add -A -- <шлях>` на файл, що
    ніколи не був в індексі, після переносу — фатальна «pathspec не знайдено».
    Шаблон, прив'язаний до кореня, у теці проєкту вже не діє — команда це каже.
    """
    (legacy / ".gitignore").write_text("/data/derived/search_log.json\n", encoding="utf-8")
    (legacy / "data" / "derived" / "search_log.json").write_text("{}", encoding="utf-8")
    _commit(legacy)
    before = _tree(legacy)
    got = A.apply(legacy, "rid", archive=tmp_path / "arch")
    rid = legacy / "projects" / "rid"
    assert (rid / "data" / "derived" / "search_log.json").is_file()
    assert "projects/rid/data/derived/search_log.json" in got["untracked"]
    staged = _git(legacy, "diff", "--cached", "--name-only")
    assert "projects/rid/data/canonical/persons/I9001.md" in staged
    W.reset()
    W.use(W._build(legacy, "test"))
    A.rollback(legacy)
    W.reset()
    assert _tree(legacy) == before
    assert _git(legacy, "diff", "--cached", "--name-only").strip() == "", "індекс чистий після відкату"


def test_retry_after_failure_reuses_the_verified_archive(legacy: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Повтор після збою не пакує ті самі гігабайти вдруге — якщо файли ті самі."""
    from nyshporka import project as PR

    real = PR.create

    def boom(*a: object, **k: object) -> object:
        raise RuntimeError("впало після архіву")

    monkeypatch.setattr(PR, "create", boom)
    with pytest.raises(A.AdoptError, match="впало після архіву"):
        A.apply(legacy, "rid", archive=tmp_path / "arch")
    first = sorted((tmp_path / "arch").glob("adopt-*.zip"))
    assert len(first) == 1

    monkeypatch.setattr(PR, "create", real)
    W.reset()
    W.use(W._build(legacy, "test"))
    got = A.apply(legacy, "rid", archive=tmp_path / "arch")
    assert got["archive"]["reused"] is True and got["archive"]["zip"] == str(first[0])
    assert sorted((tmp_path / "arch").glob("adopt-*.zip")) == first

    # Змінився хоч один файл — архів уже інша копія, пакується новий.
    W.reset()
    W.use(W._build(legacy, "test"))
    A.rollback(legacy)
    W.reset()
    W.use(W._build(legacy, "test"))
    card = legacy / "data" / "canonical" / "persons" / "I9001.md"
    card.write_text(card.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _commit(legacy)
    time.sleep(1.1)                      # нове ім'я архіву — за секундами
    got = A.apply(legacy, "rid", archive=tmp_path / "arch")
    assert not got["archive"].get("reused")
    assert len(list((tmp_path / "arch").glob("adopt-*.zip"))) == 2
