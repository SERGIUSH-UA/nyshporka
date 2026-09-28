"""🌱 Засівання канону з GEDCOM: дерево з іншої програми стає картками, які
проходять перевірку, — і не перетирає вже наявний канон."""
from __future__ import annotations

from pathlib import Path

import pytest

from nyshporka import ops as O
from nyshporka.canon import check as C
from nyshporka.canon import gedcom as G
from nyshporka.core import workspace as W
from nyshporka.ids import family_id, person_id
from nyshporka.storage.files import read_family, read_person

pytest.importorskip("ged4py")

# ID канону в тесті — через `ids`, а не літералами: ворота приватних даних
# шукають саме вигляд робочих ID.
# NOTE з голими переносами — як у експортах MyHeritage; посилання на родину,
# якої у файлі немає; живий без дат; дати з ABT і BET … AND ….
GED = """0 HEAD
1 CHAR UTF-8
1 GEDC
2 VERS 5.5.1
0 @I1@ INDI
1 NAME Іван /Коваль/
2 GIVN Іван
2 SURN Коваль
1 SEX M
1 BIRT
2 DATE ABT 1800
2 PLAC Село, Повіт, Губернія
1 DEAT
2 DATE 14 MAY 1860
1 FAMS @F1@
1 RIN 101
1 NOTE Перший рядок нотатки
<p>розірваний рядок без префікса</p>
0 @I2@ INDI
1 NAME Марія /Коваль/
1 SEX F
1 BIRT
2 DATE BET 1802 AND 1805
1 FAMS @F1@
1 DEAT
2 DATE 1870
0 @I3@ INDI
1 NAME Петро /Коваль/
1 SEX M
1 BIRT
2 DATE 1830
2 PLAC Село, Повіт, Губернія
1 FAMC @F1@
1 OCCU хлібороб
1 DEAT
2 DATE 1890
0 @I4@ INDI
1 NAME Онука /Коваль/
1 SEX F
1 FAMC @F9@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 MARR
2 DATE 1825
0 TRLR
"""


@pytest.fixture
def space(tmp_path: Path) -> Path:
    (tmp_path / W.MARKER).write_text('[workspace]\nschema = 1\nname = "t"\n', encoding="utf-8")
    W.use(W.Workspace(root=tmp_path, name="t", origin="test"))
    return tmp_path


@pytest.fixture
def ged(tmp_path: Path) -> Path:
    p = tmp_path / "incoming" / "tree.ged"
    p.parent.mkdir()
    p.write_text(GED, encoding="utf-8")
    return p


def test_orphan_note_lines_are_glued() -> None:
    fixed, n = G.fix_orphan_continuations(GED.encode())
    assert n == 1
    assert b"2 CONC <p>" in fixed


def test_import_seeds_a_canon_that_passes_the_check(space: Path, ged: Path) -> None:
    rep = G.import_file(space, ged, G.Options(source_id="S_TEST_TREE", alias_prefix="T"))
    assert (rep.persons, rep.families, rep.places) == (4, 1, 1)
    canonical = space / "data" / "canonical"
    ivan = read_person(canonical / "persons" / f"{person_id(1)}.md")
    assert ivan.aliases == ["T:101"]
    assert ivan.facts[0].date is not None and ivan.facts[0].date.qualifier == "about"
    assert all(f.status == "hypothesis" for f in ivan.facts), "дереву без --trust-tree не віримо"
    maria = read_person(canonical / "persons" / f"{person_id(2)}.md")
    birth = maria.facts[0].date
    assert birth is not None and (birth.qualifier, birth.range_end) == ("between", "1805")
    granddaughter = read_person(canonical / "persons" / f"{person_id(4)}.md")
    assert granddaughter.parent_family is None, "посилання в нікуди не валить імпорт"
    assert granddaughter.private and not ivan.private
    fam = read_family(canonical / "families" / f"{family_id(1)}.md")
    assert (fam.husband, fam.wife, fam.children) == (person_id(1), person_id(2), [person_id(3)])
    assert (space / "data" / "source" / "gedcom" / "tree.ged").is_file()

    report = C.check(space)
    assert report.ok, [i for i in report.issues if i.severity == "ERROR"]


def test_import_refuses_a_non_empty_canon(space: Path, ged: Path) -> None:
    G.import_file(space, ged)
    with pytest.raises(G.GedcomError, match="вже є"):
        G.import_file(space, ged)


def test_trust_tree_and_dry_run_via_the_op(space: Path, ged: Path) -> None:
    env = O.call("canon.import", {"file": str(ged), "dry_run": True})
    assert env.ok and env.data["persons"] == 4 and not env.data["written"]
    assert not (space / "data" / "canonical").exists()
    env = O.call("canon.import", {"file": str(ged), "trust_tree": True})
    assert env.ok and env.data["written"]
    ivan = read_person(space / "data" / "canonical" / "persons" / f"{person_id(1)}.md")
    assert ivan.facts[0].status == "confirmed"


def test_import_refuses_even_when_only_a_place_card_exists(space: Path, ged: Path) -> None:
    """🔴 Імпорт нумерує місця з одиниці: ручна картка місця інакше ставала першим
    місцем дерева й губила координати."""
    from nyshporka.ids import place_id
    from nyshporka.models import Place
    from nyshporka.storage.files import write_entity

    card = space / "data" / "canonical" / "places" / f"{place_id(1)}.md"
    card.parent.mkdir(parents=True)
    write_entity(card, Place(id=place_id(1), name="Ручне", coords=(48.0, 28.0)))
    with pytest.raises(G.GedcomError, match="вже є"):
        G.import_file(space, ged)
    assert "Ручне" in card.read_text(encoding="utf-8")
