"""📋 Бланк → запис: клітинки голосу `-cells` за шаблоном, ролі й поля.

Вигаданий бланк і вигадана родина; ні справжніх кадрів, ні справжніх імен.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# (сторінка, рядок, колонка) → текст клітинки, як їх дає голос `-cells`
PAGE = [
    ((0, 0, 0), "ЗАПИС АКТА ПРО НАРОДЖЕННЯ № 17"),
    ((0, 1, 0), "ВІДОМОСТІ ПРО ДИТИНУ"),
    ((0, 2, 0), "1"), ((0, 2, 1), "Прізвище"), ((0, 2, 2), "Мирончук"),
    ((0, 2, 3), "2. Ім'я Орися"), ((0, 2, 4), "3. Стать"), ((0, 2, 5), "жіноча"),
    ((0, 3, 0), "Час народження"), ((0, 3, 1), "5 травня 1946"),
    ((0, 4, 0), "ВІДОМОСТІ ПРО БАТЬКІВ"),
    ((0, 5, 0), "Прізвище"), ((0, 5, 1), "Мирончук"), ((0, 5, 2), "Мирончук"),
    ((0, 6, 0), "Ім'я"), ((0, 6, 1), "Остап"), ((0, 6, 2), "Дзвінка"),
    ((0, 7, 0), "По батькові"), ((0, 7, 1), "Тарасович"), ((0, 7, 2), "Ярославівна"),
    ((0, 8, 0), "Вік"), ((0, 8, 1), "Минуло 30 років"), ((0, 8, 2), "Минуло 25 років"),
    ((0, 9, 0), "Прізвище, ім'я та адреса заявника"), ((0, 9, 1), "Мирончук Остап"),
]


def _write(run: Path, stem: str, page: list) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / f"{stem}.txt").write_text("\n".join(t for _a, t in page) + "\n", encoding="utf-8")
    (run / f"{stem}.lines.json").write_text(json.dumps(
        {"size": [100, 100], "boxes": [[0, 0, 1, 1]] * len(page),
         "cells": [list(a) for a, _t in page]}), encoding="utf-8")


def test_fields_land_in_their_roles(tmp_path: Path) -> None:
    from nyshporka.records import form as F

    _write(tmp_path / "r-cells", "0001", PAGE)
    cells = F.read_page(tmp_path / "r-cells", "0001")
    t = F.pick(F.templates(), cells)
    assert t is not None and t.name == "zags_birth"
    got = {k: v for k, (v, _line) in F.extract(t, cells).items()}
    assert got["record.row"] == "17"
    assert got["child.surname"] == "Мирончук" and got["child.given"] == "Орися"
    assert got["father.given"] == "Остап" and got["mother.given"] == "Дзвінка"
    assert got["father.patronymic"] == "Тарасович" and got["mother.patronymic"] == "Ярославівна"
    # «Прізвище, ім'я та адреса заявника» — не «Прізвище» батьків
    assert got["father.surname"] == "Мирончук"
    rec = F.to_record(t, F.extract(t, cells), scan="0001.jpg", run="r-cells")
    roles = {p["role"]: p for p in rec["persons"]}
    assert roles["child"]["sex"] == "f"
    assert roles["father"]["name"] == "Мирончук Остап Тарасович"
    assert rec["confidence"] == "indirect" and rec["agent"] == "form:zags_birth"
    assert "5 травня 1946" in rec["comment"] and "date" not in rec    # дата з декоду — не факт
    assert {ln["field"] for ln in rec["lines"]} >= {"father.surname", "child.given"}


def test_without_section_anchors_same_labels_go_by_order(tmp_path: Path) -> None:
    """Якорів розділів рушій не прочитав: перше «Прізвище» — дитини, друге — батьків."""
    from nyshporka.records import form as F

    page = [c for c in PAGE if "ВІДОМОСТІ" not in c[1]]
    _write(tmp_path / "r-cells", "0002", page)
    cells = F.read_page(tmp_path / "r-cells", "0002")
    got = {k: v for k, (v, _l) in F.extract(F.templates()["zags_birth"], cells).items()}
    assert got["child.surname"] == "Мирончук" and got["father.patronymic"] == "Тарасович"


def test_a_short_fragment_is_not_a_label() -> None:
    from nyshporka.records import form as F

    assert not F.is_label("Прізвище", "пр.")
    assert F.is_label("Прізвище", "8 Прізвище")
    assert F.is_label("Ім'я", "Імя")


def test_a_page_of_another_form_is_not_matched(tmp_path: Path) -> None:
    from nyshporka.records import form as F

    _write(tmp_path / "r-cells", "0003", [((0, 0, 0), "Список дворів"), ((0, 1, 0), "Прізвище")])
    assert F.pick(F.templates(), F.read_page(tmp_path / "r-cells", "0003")) is None


def test_workspace_template_overlays_the_package(tmp_path: Path) -> None:
    from nyshporka.records import form as F

    extra = tmp_path / "forms.yaml"
    extra.write_text("forms:\n  anketa:\n    rtype: other\n    match: ['АНКЕТА']\n"
                     "    fields:\n      - {label: ['Прізвище'], to: [head.surname]}\n",
                     encoding="utf-8")
    got = F.templates(extra)
    assert {"zags_birth", "anketa"} <= set(got)


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from nyshporka import htr_store as S
    from nyshporka.core import workspace as W

    (tmp_path / "nyshporka.toml").write_text("[workspace]\nschema = 1\n", encoding="utf-8")
    W.reset()
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))
    monkeypatch.setattr(S, "case_base", lambda: tmp_path)
    monkeypatch.setattr(S, "htr_root", lambda: tmp_path / "reports" / "htr")
    S._CACHE.clear()
    S._RUNS_CACHE = None
    yield tmp_path
    W.reset()


def test_extract_dry_run_then_apply_and_human_records_are_kept(space: Path) -> None:
    from nyshporka.ops_form import FormExtractArgs, form_extract
    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import Record

    run = space / "reports" / "htr" / "проба-cells"
    _write(run, "0001", PAGE)
    _write(run, "0002", PAGE)
    ref = store.resolve_case("ДАІФО/9999/1/1")
    # акт на 0002 уже вичитала людина — машинний туди не ляже
    store.add_records(ref, [Record(rtype="birth", scans=["0002.jpg"], row="17",
                                   persons=[{"role": "child", "name": "Орися"}])])
    dry = form_extract(FormExtractArgs(case="ДАІФО/9999/1/1", run=str(run)))
    assert dry.ok, dry.error
    assert dry.data["records"] == 1 and dry.data["kept_human"] == 1
    assert not dry.data["applied"]
    assert len(store.load_case(ref).records) == 1
    done = form_extract(FormExtractArgs(case="ДАІФО/9999/1/1", run=str(run), apply=True))
    assert done.ok and done.data["applied"]
    recs = store.load_case(ref).records
    assert len(recs) == 2
    machine = next(r for r in recs if r.agent == "form:zags_birth")
    assert machine.rid.endswith("-form") and machine.confidence == "indirect"
    human = next(r for r in recs if r.agent != "form:zags_birth")
    assert human.persons[0].name == "Орися"                    # не затерто
    again = form_extract(FormExtractArgs(case="ДАІФО/9999/1/1", run=str(run), apply=True))
    assert again.ok and len(store.load_case(ref).records) == 2   # повтор не подвоює
