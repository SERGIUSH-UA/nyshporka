"""🌳 Канон для консолі: список карток, картка, гіпотези — лише читання.

Екрани «Канон» і «Гіпотези» стоять на цих операціях. Перевіряється, що
список знаходить особу за варіантом імені, картка несе свої зауваження
перевірки (а не чужі), а гіпотези йдуть тим самим порядком, що «що вирішити»
(`canon.next`), із закритими в кінці. Рід вигаданий (`I9…`, «Сидорук»).
"""
from __future__ import annotations

from pathlib import Path

from test_canon import _hit, _hyp, _person, _write, family, space  # noqa: F401

from nyshporka import ops as O
from nyshporka.models import NameVariant


def _canon(root: Path) -> None:
    p = _person("I9004", "Олекса Сидорук", "M", born="1850", private=True)
    p.names.append(NameVariant(form="Алексѣй Сидорукъ", lang="ru"))
    _write(root, "persons", p)
    _write(root, "hypotheses", _hyp("H9001", about=["I9003"]))
    _write(root, "hypotheses", _hyp("H9002", "awaiting", about=["I9003", "I9001"],
                                    hits=[_hit("strong", line=4)]))
    # Вага закритої більша за відкриту: у кінці вона мусить стояти за станом.
    _write(root, "hypotheses", _hyp("H9003", "closed", claim="Петро — не наш",
                                    about=["I9001", "I9002", "I9003"],
                                    verdict="ні", reopen_if="нова метрика"))


def test_cards_list_all_kinds_and_find_by_a_variant(family: Path) -> None:  # noqa: F811
    _canon(family)
    d = O.call("canon.cards", {}).data
    assert d["counts"]["persons"] == 4 and d["found"] == 4 + 1 + 1 + 1 + 3
    fam = next(r for r in d["rows"] if r["id"] == "F9001")
    assert fam["title"] == "Іван × Марія" and fam["kind"] == "families"
    hit = O.call("canon.cards", {"q": "алексѣй"}).data["rows"]
    assert [(r["id"], r["private"]) for r in hit] == [("I9004", True)]
    assert hit[0]["file"] == "data/canonical/persons/I9004.md"
    only = O.call("canon.cards", {"kind": "places"}).data["rows"]
    assert [r["id"] for r in only] == ["PL9001"]


def test_card_carries_its_own_issues_and_hypotheses(family: Path) -> None:  # noqa: F811
    _canon(family)
    _write(family, "persons", _person("I9005", "Гнат", "M", parent_family="F9999"))
    d = O.call("canon.card", {"id": "I9003"}).data
    assert d["kind"] == "persons" and d["card"]["sex"] == "M"
    assert {h["id"] for h in d["hypotheses"]} == {"H9001", "H9002", "H9003"}
    assert d["issues"] == [], "чуже зауваження (I9005) сюди не потрапляє"
    bad = O.call("canon.card", {"id": "I9005"}).data
    assert bad["issues"] and all("I9005" in i["where"] or "F9999" in i["text"]
                                 for i in bad["issues"])
    assert not O.call("canon.card", {"id": "I9404"}).ok


def test_hyps_follow_the_decision_order_with_closed_last(family: Path) -> None:  # noqa: F811
    _canon(family)
    d = O.call("canon.hyps", {}).data
    assert d["counts"] == {"open": 1, "awaiting": 1, "closed": 1}
    assert [r["id"] for r in d["rows"]] == ["H9002", "H9001", "H9003"]
    assert d["rows"][0]["strong"] and d["rows"][0]["weight"] == 2
    closed = O.call("canon.hyps", {"status": "closed"}).data["rows"]
    assert [r["id"] for r in closed] == ["H9003"]
    nxt = O.call("canon.next", {"limit": 5}).data["next"]
    assert [x["id"] for x in nxt] == ["H9002", "H9001"], "next закритих не показує"


def test_hyp_gives_hits_with_a_crop_command(family: Path) -> None:  # noqa: F811
    _canon(family)
    d = O.call("canon.hyp", {"id": "H9002"}).data
    assert d["hits"][0]["crop"] == 'nysh text crop "TEST/1/2/3" 0007 4'
    assert d["card"]["status"] == "awaiting" and "hits" not in d["card"]
    assert not O.call("canon.hyp", {"id": "I9003"}).ok


def test_without_canon_the_answer_says_so(space: Path) -> None:  # noqa: F811
    for name in ("canon.cards", "canon.hyps"):
        env = O.call(name, {})
        assert not env.ok and "data/canonical" in env.error
