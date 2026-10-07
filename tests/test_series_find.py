"""🔎 Пошук по фонду чи опису: швидко, з поступом по справах, у тому ж порядку.

Замір 07.10.2026: «Липовеньке» по ЦДІАК ф.224 — 151 с, увесь час на «блоки
корпусу 1 із 1». З 189 с профілю сам пошук займав 16: решта — канон,
перечитаний 109 разів (89 с), і 524 обходи переліку прогонів (46 с).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from nyshporka.core import progress as P
from nyshporka.search import textops as T


def _one(case: str, hits: list[dict[str, Any]], matches: dict[str, int]) -> dict[str, Any]:
    return {"case_key": case, "hits": hits, "total": len(hits), "matches": matches,
            "anchor": {}, "record": {}, "notebook": {},
            "ledger": {"channels": [{"id": "surname", "ran": True, "hits": len(hits)}],
                       "runs": 1, "pages_scoped": 1, "frames": 1, "decoded": 1}}


def _sc(*keys: str) -> dict[str, Any]:
    return {"keys": list(keys), "rows": [{"name": k, "case_canon": k} for k in keys],
            "kind": "cases", "shifra": "А 1"}


def test_series_keeps_the_match_order_and_sums_the_split() -> None:
    """🔴 Зведення сортувало самим балом — «100» стема в чужому слові знову вгорі."""
    a = _one("A/1/1/1", [{"score": 99, "match": "inside", "name": "a"}],
             {"exact": 0, "variant": 0, "ending": 0, "inside": 1})
    b = _one("A/1/1/2", [{"score": 95, "match": "variant", "name": "b"}],
             {"exact": 0, "variant": 1, "ending": 0, "inside": 0})
    got = T._merge_finds("x", _sc("A/1/1/1", "A/1/1/2"), [("A/1/1/1", a), ("A/1/1/2", b)],
                         limit=10)
    # Варіант із балом 95 — вище за «у довшому слові» з 99: вид важить більше.
    assert [h["match"] for h in got["hits"]] == ["variant", "inside"]
    assert got["matches"] == {"exact": 0, "variant": 1, "ending": 0, "inside": 1}


def test_series_reports_progress_by_case_and_hides_the_inner_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int, str]] = []

    def fake_one(q: str, k: str, **_: Any) -> dict[str, Any]:
        P.report(1, 1, "блоки корпусу")          # внутрішній — мусить не дійти
        return _one(k, [], {})

    monkeypatch.setattr(T, "_find_one", fake_one)
    with P.sink(lambda i, n, w: seen.append((i, n, w))):
        T._find_many("x", _sc("A/1/1/1", "A/1/1/2", "A/1/1/3"), thresh=78, limit=10, context=0)
    assert seen == [(1, 3, "справи серії"), (2, 3, "справи серії"), (3, 3, "справи серії")]


def test_series_stops_between_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    stop = threading.Event()

    def fake_one(q: str, k: str, **_: Any) -> dict[str, Any]:
        asked.append(k)
        stop.set()                                 # «Спинити» натиснули під час першої
        return _one(k, [], {})

    monkeypatch.setattr(T, "_find_one", fake_one)
    with P.stop_scope(stop):
        got = T._find_many("x", _sc("A/1/1/1", "A/1/1/2"), thresh=78, limit=10, context=0)
    assert asked == ["A/1/1/1"] and got["stopped"] is True


def test_canon_cards_are_parsed_once_until_they_change(tmp_path: Path) -> None:
    """🔴 42 837 розборів YAML на фонді зі 109 справ — канон перечитувався щоразу."""
    from nyshporka.search import selfcheck as SC

    card = tmp_path / "p.md"
    card.write_text("x", encoding="utf-8")
    reads: list[Path] = []

    def read(p: Path) -> str:
        reads.append(p)
        return p.read_text(encoding="utf-8")

    SC._PERSONS.clear()
    assert SC._person(card, read) == "x"
    assert SC._person(card, read) == "x"
    assert len(reads) == 1, "незмінну картку розібрано вдруге"
    card.write_text("yy", encoding="utf-8")       # інший розмір — правку видно одразу
    assert SC._person(card, read) == "yy"
    assert len(reads) == 2
    SC._PERSONS.clear()
