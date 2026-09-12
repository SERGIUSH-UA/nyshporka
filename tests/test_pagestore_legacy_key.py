"""Облік, записаний до того, як опис увійшов у ключ фонду, не зникає мовчки.

🔴 Коли фонд потрапляє в `_OPYS_IN_KEY` (0.13: ДАХмО ф.196, ДАЖО ф.1 і ф.118,
ДАВоО ф.382), файл сховища сторінок міняє ім'я: `196-712.json` →
`196-1-712.json`. Старий файл лишається на диску, а резолвер його більше не
питає — тож `pages status` каже «не дивились» про аркуші, які вже переглянуто,
а новий запис лягає в новий файл поруч зі старим. Обидва наслідки тихі: так
виглядає саме той нуль, що закриває напрям пошуку.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from nyshporka.core import workspace as W

    monkeypatch.setattr(W, "_override", W._override)   # повернути простір після тесту
    W.use(W.Workspace(root=tmp_path, name="тест", origin="test"))

    from nyshporka.pagestore import store as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "PAGES_ROOT", tmp_path / "data" / "pages")
    monkeypatch.setattr(S, "load_library", lambda: [
        {"key": "DAHMO/196-1/712", "repo": "DAHMO", "fond": "196", "opys": "1",
         "spr": "712", "shifra": "ДАХмО 196-1-712"},
        {"key": "DAHMO/196-8/712", "repo": "DAHMO", "fond": "196", "opys": "8",
         "spr": "712", "shifra": "ДАХмО 196-8-712"},
    ])
    (tmp_path / "data" / "pages" / "DAHMO").mkdir(parents=True)
    return S


def _legacy(S: Any, opys: str) -> Path:
    p = S.PAGES_ROOT / "DAHMO" / "196-712.json"
    p.write_text(json.dumps({"key": "DAHMO/196/712", "repo": "DAHMO", "fond": "196",
                             "spr": "712", "opys": opys, "pages": {}, "records": []}),
                 encoding="utf-8")
    return p


def test_legacy_file_of_this_book_is_a_refusal_not_an_empty_case(store: Any) -> None:
    _legacy(store, "1")
    with pytest.raises(ValueError, match=r"196-1-712\.json"):
        store.resolve_case("DAHMO/196-1/712")


def test_legacy_file_of_another_book_does_not_block(store: Any) -> None:
    """Старий файл належав оп.8 — до оп.1 він стосунку не має."""
    _legacy(store, "8")
    ref = store.resolve_case("DAHMO/196-1/712")
    assert store.case_path(ref).name == "196-1-712.json"


def test_no_legacy_file_resolves_as_before(store: Any) -> None:
    ref = store.resolve_case("DAHMO/196-1/712")
    assert ref.key == "DAHMO/196-1/712"
