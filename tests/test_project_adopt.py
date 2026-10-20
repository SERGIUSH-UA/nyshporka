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
import shutil
import subprocess
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
    return hub


def test_plan_names_what_moves_and_what_would_dangle(legacy: Path) -> None:
    pl = A.plan(legacy, "rid")
    moved = {m.path for m in pl.moves}
    assert {"data/canonical", "config/research_profile.yaml", "data/derived/verdicts.json",
            "data/source/letters"} <= moved
    assert "config/archives.yaml" not in moved, "пак архівів — Майстерні"
    assert pl.problems == []
    assert pl.views["with_view"] == 1 and pl.views["marks"] == {"портал": 1}

    # Без `extra` лист, на який посилається картка, лишився б у корені.
    (legacy / W.MARKER).write_text('[workspace]\nname = "Тест"\nkeys = 2\n', encoding="utf-8")
    pl = A.plan(legacy, "rid")
    assert any("data/source/letters/l1.txt" in p for p in pl.problems)


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
    from nyshporka.canon import hook as H
    from nyshporka.canon.check import check

    before = _tree(legacy)
    got = A.apply(legacy, "rid", archive=tmp_path / "arch")
    rid = legacy / "projects" / "rid"

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
    """Архів, що не звірився розпакуванням, — не копія: переїзд не починається."""
    real = A._sha

    def lying(p: Path) -> str:
        return real(p) if legacy in p.parents else "0" * 64   # розпаковане «інше»

    monkeypatch.setattr(A, "_sha", lying)
    with pytest.raises(A.AdoptError, match="не звірився"):
        A.apply(legacy, "rid", archive=tmp_path / "arch")
    assert (legacy / "data" / "canonical" / "persons" / "I9001.md").is_file()
    assert not (legacy / "projects").exists()
    assert "hub_only" not in W._read_marker(legacy / W.MARKER)
