"""🌳 Канон: перевірка ловить те, що ламає правка файлом; ID не вгадуються; доказ
лягає в стор так, щоб цитата не провисла.

ID тут вигадані й поза діапазоном справжнього канону (`I9…`, `F9…`) — ворота
приватних даних шукають саме вигляд робочих ID.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from nyshporka import ops as O
from nyshporka.canon import check as C
from nyshporka.canon import evidence as E
from nyshporka.canon.ids import new_id
from nyshporka.core import workspace as W
from nyshporka.models import (
    Citation,
    Fact,
    Family,
    GedDate,
    NameVariant,
    Person,
    Place,
    Source,
)
from nyshporka.storage.files import write_entity

SRC = "S_TEST_BOOK"


def _person(pid: str, name: str, sex: str = "M", born: str | None = None,
            died: str | None = None, **kw) -> Person:
    facts = []
    for kind, val in (("birth", born), ("death", died)):
        if val:
            facts.append(Fact(type=kind, date=GedDate(value=val), status="confirmed",
                              citations=[Citation(source_id=SRC, confidence="direct",
                                                  accessed=date(2026, 1, 1))]))
    return Person(id=pid, names=[NameVariant(form=name, lang="uk", primary=True)],
                  sex=sex, facts=facts, **kw)


def _write(root: Path, kind: str, entity, name: str | None = None) -> Path:
    path = root / "data" / "canonical" / kind / f"{name or entity.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_entity(path, entity)
    return path


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    return tmp_path


@pytest.fixture
def family(space: Path) -> Path:
    """Цілий канон: батьки, дитина, місце, джерело — перевірка мусить мовчати."""
    _write(space, "sources", Source(id=SRC, type="book", title="Тестова книга"))
    _write(space, "places", Place(id="PL9001", name="Село"))
    _write(space, "persons", _person("I9001", "Іван", "M", born="1800",
                                     spouse_families=["F9001"]))
    _write(space, "persons", _person("I9002", "Марія", "F", born="1805",
                                     spouse_families=["F9001"]))
    _write(space, "persons", _person("I9003", "Петро", "M", born="1830",
                                     parent_family="F9001"))
    _write(space, "families", Family(id="F9001", husband="I9001", wife="I9002",
                                     children=["I9003"]))
    return space


def _codes(rep: C.Report, sev: str) -> list[str]:
    return sorted(i.code for i in rep.issues if i.severity == sev)


def test_a_whole_canon_has_no_errors_or_warnings(family: Path) -> None:
    rep = C.check(family)
    assert rep.ok and _codes(rep, "ERROR") == [] and _codes(rep, "WARN") == []
    assert rep.canon.counts() == {"persons": 3, "families": 1, "places": 1, "sources": 1}


def test_a_broken_card_does_not_hide_the_rest(family: Path) -> None:
    """🔴 Одна зіпсована картка — рядок ERROR, а не виняток, що ховає решту."""
    bad = family / "data" / "canonical" / "persons" / "I9004.md"
    bad.write_text("---\nid: I9004\nsex: X\n---\n", encoding="utf-8")
    _write(family, "persons", _person("I9005", "Сирота", parent_family="F9999"))
    rep = C.check(family)
    assert "schema" in _codes(rep, "ERROR")
    assert "missing_ref" in _codes(rep, "ERROR")


def test_file_name_must_match_the_id(family: Path) -> None:
    """Скопійована заготовка з незміненим id — найчастіша помилка ручної правки."""
    _write(family, "persons", _person("I9003", "Копія"), name="I9010")
    rep = C.check(family)
    assert {"file_name", "duplicate_id"} & set(_codes(rep, "ERROR"))


def test_one_sided_link_and_wrong_sex(family: Path) -> None:
    _write(family, "persons", _person("I9002", "Марія", "M", born="1805",
                                      spouse_families=["F9001"]))
    _write(family, "persons", _person("I9006", "Зайвий", parent_family="F9001", born="1832"))
    rep = C.check(family)
    assert "sex" in _codes(rep, "ERROR")
    assert "one_sided" in _codes(rep, "WARN")


def test_chronology_errors(family: Path) -> None:
    _write(family, "persons", _person("I9003", "Петро", "M", born="1808",
                                      parent_family="F9001"))
    _write(family, "persons", _person("I9001", "Іван", "M", born="1800", died="1790",
                                      spouse_families=["F9001"]))
    rep = C.check(family)
    texts = " ".join(i.text for i in rep.issues if i.code == "chronology")
    assert "пізніше за смерть" in texts
    assert "мати I9002 мав(ла) 3 років" in texts


def test_confirmed_without_a_strong_citation_is_flagged(family: Path) -> None:
    p = _person("I9003", "Петро", "M", parent_family="F9001")
    p.facts.append(Fact(type="residence", status="confirmed"))
    p.facts.append(Fact(type="occupation", status="confirmed", citations=[
        Citation(source_id=SRC, confidence="speculative", accessed=date(2026, 1, 1))]))
    _write(family, "persons", p)
    assert {"uncited", "weak_confirmed"} <= set(_codes(C.check(family), "WARN"))


def test_evidence_path_and_manifest_are_checked(family: Path) -> None:
    p = _person("I9003", "Петро", "M", parent_family="F9001",
                notes="Доказ: `data/source/citations/test/missing.jpg`")
    _write(family, "persons", p)
    crop = family / "data" / "source" / "citations" / "test" / "real.jpg"
    crop.parent.mkdir(parents=True)
    crop.write_bytes(b"x")
    E.manifest_path(family).write_text(json.dumps({
        "data/source/citations/test/real.jpg": {"secured_to": "data/source/citations/test/real.jpg",
                                                 "sha256": "0" * 64, "cited_by": []},
        "data/source/citations/test/gone.jpg": {"secured_to": "data/source/citations/test/gone.jpg",
                                                 "cited_by": ["I9003.md"]},
    }), encoding="utf-8")
    assert {"evidence_missing", "manifest_missing"} <= set(_codes(C.check(family), "ERROR"))
    assert "manifest_hash" not in _codes(C.check(family), "ERROR"), "без --hash хеш не рахується"
    assert "manifest_hash" in _codes(C.check(family, hash_evidence=True), "ERROR")


def test_regions_are_required_only_when_coverage_uses_them(family: Path) -> None:
    from nyshporka.models import CoverageSpan

    _write(family, "sources", Source(id=SRC, type="book", title="Книга", coverage=[
        CoverageSpan(region="xx", year_from=1800, year_to=1810)]))
    assert "regions" in _codes(C.check(family), "ERROR")


def test_new_id_is_max_plus_one_and_skips_gaps(family: Path) -> None:
    (family / "data" / "canonical" / "persons" / "I9003.md").unlink()
    canonical = family / "data" / "canonical"
    assert new_id(canonical, "person") == "I9003", "дірка після максимуму — не дірка"
    _write(family, "persons", _person("I9020", "Далекий"))
    assert new_id(canonical, "person") == "I9021"
    assert new_id(canonical, "place") == "PL9002"
    assert new_id(canonical, "family") == "F9002"


def _png(path: Path, size: tuple[int, int] = (300, 40), noise: bool = False) -> Path:
    if noise:
        im = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        im = Image.new("RGB", size, (200, 120, 40))
    im.save(path)
    return path


def test_evidence_add_stores_a_grey_jpeg_and_is_idempotent(space: Path) -> None:
    src = _png(space / "crop.png")
    got = E.add(space, src, "test", name="рядок 1")
    stored = space / got.path
    assert got.path == "data/source/citations/test/рядок_1.jpg"
    with Image.open(stored) as im:
        assert im.format == "JPEG" and im.mode == "L"
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == got.sha256
    man = json.loads(E.manifest_path(space).read_text(encoding="utf-8"))
    assert man[got.path]["cited_by"] == []
    again = E.add(space, src, "test", name="рядок 1")
    assert again.existed and again.sha256 == got.sha256


def test_evidence_add_refuses_what_would_break_a_citation(space: Path) -> None:
    first = E.add(space, _png(space / "a.png"), "test", name="x")
    other = _png(space / "b.png", size=(310, 40))
    with pytest.raises(E.EvidenceError, match="іншим вмістом"):
        E.add(space, other, "test", name="x")
    assert E.add(space, other, "test", name="x", overwrite=True).sha256 != first.sha256
    with pytest.raises(E.EvidenceError, match="латиниця"):
        E.add(space, other, "Архів", name="y")
    with pytest.raises(E.EvidenceError, match="аркуш, а не"):
        E.add(space, _png(space / "big.png", size=(2600, 2600), noise=True), "test")


def test_index_normalises_and_fills_cited_by(family: Path) -> None:
    got = E.add(family, _png(family / "c.png"), "test", name="c")
    other = E.add(family, _png(family / "d.png", size=(320, 40)), "test", name="d")
    man = E.manifest_path(family)
    data = json.loads(man.read_text(encoding="utf-8"))
    data[got.path]["cited_by"] = ["I9001", "data/canonical/persons/I9001.md"]
    man.write_text(json.dumps(data), encoding="utf-8")
    _write(family, "persons", _person("I9003", "Петро", "M", parent_family="F9001",
                                      notes=f"Доказ: `{got.path}`"))
    env = O.call("canon.index", {})
    assert env.ok, env.error
    data = json.loads(man.read_text(encoding="utf-8"))
    assert data[got.path]["cited_by"] == ["I9001.md", "I9003.md"]
    assert env.data["evidence"]["unreferenced"] == [other.path]
    assert (family / "data" / "derived" / "nyshporka.sqlite").is_file()


def test_ops_on_a_space_without_canon(space: Path) -> None:
    env = O.call("canon.check", {})
    assert env.ok and env.data["loaded"] == {}
    assert any(w.code == "no_canon" for w in env.warnings)
    assert not O.call("canon.index", {}).ok


def test_check_op_reports_errors_as_data(family: Path) -> None:
    _write(family, "persons", _person("I9005", "Сирота", parent_family="F9999"))
    env = O.call("canon.check", {})
    assert env.ok and env.data["errors"] == 1
    assert any(w.code == "canon_errors" for w in env.warnings)
    assert O.call("canon.new_id", {"kind": "person"}).data["id"] == "I9006"
