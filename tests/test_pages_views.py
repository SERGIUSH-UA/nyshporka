"""Сховище сторінок на двох шарах: факт аркуша — Майстерня, погляд — проєкт.

Помилка тут тиха: коментар «шукали Сидорука» одного роду, що ліг у спільний
файл справи, агент сусіднього проєкту прочитав би як знання про свій рід.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nyshporka.core import projects as P
from nyshporka.core import workspace as W
from nyshporka.pagestore import store as S
from nyshporka.pagestore.models import PageNote

# Шляхи — справжні від простору: тест саме й перевіряє, де лягає кожен шар.
pytestmark = pytest.mark.real_paths


def _hub(tmp_path: Path, *, hub_only: bool = False) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    flag = "hub_only = true\n" if hub_only else ""
    (hub / W.MARKER).write_text(f'[workspace]\nname = "Майстерня"\nkeys = 2\n{flag}',
                                encoding="utf-8")
    return hub


def _project(hub: Path, pid: str) -> Path:
    root = hub / W.PROJECTS_DIR / pid
    root.mkdir(parents=True)
    (root / W.MARKER).write_text(f'[project]\nname = "Рід {pid}"\nkind = "family"\n',
                                 encoding="utf-8")
    return root


REF = S.CaseRef(key="DAHMO/315/1/8433", repo="DAHMO", fond="315", spr="8433", opys="1")
REF2 = S.CaseRef(key="DAHMO/315/1/8434", repo="DAHMO", fond="315", spr="8434", opys="1")


def _note(comment: str, surnames: list[str] | None = None, scan: str = "0001.jpg") -> PageNote:
    return PageNote(scan=scan, page_type="birth", surnames=surnames or ["Сидорук"],
                    comment=comment, agent="test")


@pytest.fixture(autouse=True)
def _clean() -> object:
    W.reset()
    yield
    W.reset()


def _hub_file(hub: Path, ref: S.CaseRef = REF) -> dict:
    return json.loads((hub / "data" / "pages" / ref.repo / f"{ref.fond}-1-{ref.spr}.json")
                      .read_text(encoding="utf-8"))


def test_project_note_splits_fact_to_hub_and_view_to_project(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    S.annotate_pages(REF, [_note("шукали Сидорука для alpha")])
    page = _hub_file(hub)["pages"]["0001.jpg"]
    assert page["surnames"] == ["Сидорук"]
    assert page["comment"] == "" and page["agent"] == ""
    view = json.loads((alpha / "data" / "views" / "DAHMO" / "315-1-8433.json")
                      .read_text(encoding="utf-8"))
    assert view["pages"]["0001.jpg"]["comment"] == "шукали Сидорука для alpha"
    # Очима свого проєкту — справа ціла.
    cf = S.load_case(REF)
    assert cf is not None and cf.pages["0001.jpg"].comment == "шукали Сидорука для alpha"


def test_legacy_root_writes_inline_as_before(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    W.use(W._build(hub, "test"))
    S.annotate_pages(REF, [_note("старий простір")])
    assert _hub_file(hub)["pages"]["0001.jpg"]["comment"] == "старий простір"
    assert not (hub / "data" / "views").exists()


def test_neighbour_sees_fact_and_only_a_count_of_the_view(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    W.use(W._build(alpha, "test"))
    S.annotate_pages(REF, [_note("ALPHA-SECRET")])
    W.use(W._build(beta, "test"))
    cf = S.load_case(REF)
    assert cf is not None
    page = cf.pages["0001.jpg"]
    assert page.surnames == ["Сидорук"] and page.comment == ""
    assert S.views_elsewhere(REF) == [{"project": "alpha", "name": "Рід alpha", "pages": 1}]


def test_root_inline_comment_is_foreign_in_a_project(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    W.use(W._build(hub, "test"))
    S.annotate_pages(REF, [_note("ROOT-SECRET")])
    alpha = _project(hub, "alpha")
    W.use(W._build(alpha, "test"))
    cf = S.load_case(REF)
    assert cf is not None and cf.pages["0001.jpg"].comment == ""
    assert [f["project"] for f in S.views_elsewhere(REF)] == ["."]
    # Запис проєкту, навіть із заміною, коментаря кореня не стирає.
    S.annotate_pages(REF, [_note("свій", ["Іваненко"])], replace=True)
    page = _hub_file(hub)["pages"]["0001.jpg"]
    assert page["comment"] == "ROOT-SECRET" and page["surnames"] == ["Іваненко"]


def test_pure_hub_refuses_a_comment_without_project(tmp_path: Path) -> None:
    hub = _hub(tmp_path, hub_only=True)
    W.use(W._build(hub, "test"))
    with pytest.raises(W.NoProjectError):
        S.annotate_pages(REF, [_note("без проєкту")])
    S.annotate_pages(REF, [_note("")])                      # факт — можна
    assert _hub_file(hub)["pages"]["0001.jpg"]["agent"] == ""


def test_text_grep_pages_in_project_skips_foreign_comment(tmp_path: Path) -> None:
    from nyshporka.search import textops as T

    hub = _hub(tmp_path)
    W.use(W._build(hub, "test"))
    S.annotate_pages(REF2, [_note("ROOT-SECRET", ["Іваненко"])])    # вбудований погляд кореня
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    W.use(W._build(alpha, "test"))
    S.annotate_pages(REF, [_note("ALPHA-SECRET")])
    assert T.grep_layers("ALPHA-SECRET", ["pages"])["total"] == 1    # свій погляд
    W.use(W._build(beta, "test"))
    assert T.grep_layers("ALPHA-SECRET", ["pages"])["total"] == 0
    assert T.grep_layers("ROOT-SECRET", ["pages"])["total"] == 0
    assert T.grep_layers("Іваненко", ["pages"])["total"] == 1        # факт — спільний
    assert [f["project"] for f in P.peek(W.workspace(), re.compile("ROOT-SECRET"),
                                         ("pages",))] == ["."]
    found = P.peek(W.workspace(), re.compile("ALPHA-SECRET"), ("pages",))
    assert found == [{"project": "alpha", "name": "Рід alpha", "layer": "pages", "count": 1}]


def test_surname_search_shows_own_comment_only(tmp_path: Path) -> None:
    from nyshporka.pagestore import query as Q

    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    W.use(W._build(alpha, "test"))
    S.annotate_pages(REF, [_note("ALPHA-SECRET")])
    W.use(W._build(beta, "test"))
    hits = Q.grep_surnames("Сидорук", profile=False)["hits"]
    assert hits and all(h["comment"] == "" for h in hits)


def test_split_moves_root_view_into_project_and_rolls_back(tmp_path: Path) -> None:
    from nyshporka.pagestore import split_views as SV

    hub = _hub(tmp_path)
    W.use(W._build(hub, "test"))
    S.annotate_pages(REF, [_note("замовлення №3: шукали"), _note("", scan="0002.jpg")])
    before = (hub / "data" / "pages" / "DAHMO" / "315-1-8433.json").read_bytes()
    rid = _project(hub, "rid")
    pl = SV.plan("rid")
    assert (pl["pages"], pl["with_view"], pl["marks"]) == (2, 2, {"замовлен": 1})
    # 0002.jpg без коментаря, але з agent — теж погляд: хто дивився.
    got = SV.apply("rid")
    assert got["problems"] == [] and got["moved"] == 2
    page = _hub_file(hub)["pages"]["0001.jpg"]
    assert page["comment"] == "" and page["agent"] == "" and page["surnames"] == ["Сидорук"]
    W.use(W._build(rid, "test"))
    assert S.load_case(REF).pages["0001.jpg"].comment == "замовлення №3: шукали"  # type: ignore[union-attr]
    W.use(W._build(hub, "test"))
    SV.rollback()
    assert (hub / "data" / "pages" / "DAHMO" / "315-1-8433.json").read_bytes() == before
    assert not (rid / "data" / "views" / "DAHMO" / "315-1-8433.json").exists()
    with pytest.raises(SV.SplitError):
        SV.plan(".")


def test_move_pages_carries_views_of_every_project(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    alpha, beta = _project(hub, "alpha"), _project(hub, "beta")
    for root, text in ((alpha, "A"), (beta, "B")):
        W.use(W._build(root, "test"))
        S.annotate_pages(REF, [_note(text), _note(text, scan="0002.jpg")])
    got = S.move_pages(REF, REF2, ["0002.jpg"])
    assert got["pages"] == 1 and got["views"] == 2
    for root, text in ((alpha, "A"), (beta, "B")):
        W.use(W._build(root, "test"))
        assert S.load_case(REF2).pages["0002.jpg"].comment == text   # type: ignore[union-attr]
        assert "0002.jpg" not in S.load_case(REF).pages               # type: ignore[union-attr]
