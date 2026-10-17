"""🌳 tree.json: подружжя лише навхрест чоловік × дружина, брати й сестри з
родини батьків. ID вигадані (`I9…`, `F9…`)."""
from __future__ import annotations

from nyshporka.models import Family, NameVariant, Person
from nyshporka.storage.tree_graph import build_tree_graph


def _p(pid: str, sex: str = "M", parent_family: str | None = None) -> Person:
    return Person(id=pid, names=[NameVariant(form=f"Тест {pid}", primary=True)],
                  sex=sex, parent_family=parent_family)


def _nodes(persons: list[Person], fams: list[Family]) -> dict[str, dict]:
    return {n["id"]: n for n in build_tree_graph(persons, fams)["nodes"]}


def test_hypothetical_father_is_not_spouse_of_confirmed_father() -> None:
    fam = Family(id="F9001", husband="I9001", hypothetical_husband="I9002",
                 wife="I9003", children=["I9004"])
    n = _nodes([_p("I9001"), _p("I9002"), _p("I9003", "F"), _p("I9004", parent_family="F9001")],
               [fam])
    assert n["I9001"]["spouse_ids"] == ["I9003"]
    assert n["I9002"]["spouse_ids"] == ["I9003"]
    assert n["I9003"]["spouse_ids"] == ["I9001", "I9002"]
    assert n["I9004"]["parent_ids"] == ["I9001", "I9002", "I9003"]


def test_siblings_from_parent_family_including_hypothetical() -> None:
    fam = Family(id="F9001", husband="I9001", children=["I9002", "I9003"],
                 hypothetical_children=["I9004"])
    n = _nodes([_p("I9001"), _p("I9002", parent_family="F9001"),
                _p("I9003", parent_family="F9001"), _p("I9004")], [fam])
    assert n["I9002"]["sibling_ids"] == ["I9003", "I9004"]
    assert n["I9004"]["sibling_ids"] == ["I9002", "I9003"]
    assert n["I9001"]["sibling_ids"] == []


def test_schema_version_two() -> None:
    assert build_tree_graph([_p("I9001")], [])["meta"]["schema_version"] == 2
