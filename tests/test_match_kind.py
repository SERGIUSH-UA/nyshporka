"""🔎 Вид збігу: «100» стема всередині чужого слова — не те саме, що «100» слова.

Холодний прохід 07.10.2026: на «Ярошинський» — 296 тис. збігів, у всіх перших
схожість 100, першим «Pan Paroszynskiin». Замір: 182 тис. — стем усередині
довших слів (злиплі рушієм ім'я й прізвище, чужі прізвища з хвостом «-инський»).
"""
from __future__ import annotations

import pytest

from nyshporka.search import rank as RANK
from nyshporka.utils.translit import normalize_archival as N

STEM = N("Ярошинський")          # `arosinskii`: «Я» нормалізація з'їдає


@pytest.mark.parametrize(("word", "kind"), [
    ("Ярошинський", "exact"),
    ("Ярошинскій", "exact"),            # дореформене «і» нормалізація зводить
    ("Ярошенський", "variant"),         # рушій перекрутив середину
    ("Ярошинського", "ending"),         # інший відмінок
    ("Jaroszyński", "variant"),         # латинка: йотований початок
    ("Jaroszyńskiego", "ending"),       # латинка + відмінок: зсув на «j» — те саме слово
    ("Paroszynskiin", "variant"),       # J→P: схоже слово, а не «100 у вікні»
    ("Kaparoszynskiego", "inside"),     # стем глибоко в чужому слові
    ("Олександрярошинський", "inside"),  # злиплі рушієм ім'я й прізвище
])
def test_match_kind(word: str, kind: str) -> None:
    assert RANK.match_kind(STEM, N(word), 80) == kind


def test_inside_matches_are_not_dropped_only_ordered() -> None:
    """🔴 Позначка, а не відсів: злипле «ім'я+прізвище» — теж рід."""
    hits = [{"norm": N("Paroszynskiin"), "stem": STEM, "score": 100},
            {"norm": N("Ярошинського"), "stem": STEM, "score": 100},
            {"norm": N("Ярошинський"), "stem": STEM, "score": 100},
            {"norm": N("Олександрярошинський"), "stem": STEM, "score": 100}]
    counts = RANK.classify(hits, 80)
    hits.sort(key=RANK.sort_key)
    assert [(h["match"], h["score"]) for h in hits] == [
        ("exact", 100), ("ending", 99), ("variant", 91), ("inside", 99)]
    assert counts == {"exact": 1, "variant": 1, "ending": 1, "inside": 1}


def test_only_an_exact_match_scores_100() -> None:
    """🔴 100 стема в будь-якому вікні слова читалось як «те саме прізвище»."""
    hits = [{"norm": N(w), "stem": STEM, "score": 100}
            for w in ("Paroszynskiin", "Ярошинського", "Олександрярошинський")]
    RANK.classify(hits, 80)
    assert all(h["score"] < 100 for h in hits)


def test_rank_penalty_still_comes_first() -> None:
    """Правило профілю й конфузер важать більше за вид збігу — як і було."""
    hits = [{"norm": N("Ярошинський"), "stem": STEM, "score": 100, "rank_penalty": 2},
            {"norm": N("Kaparoszynskiego"), "stem": STEM, "score": 100}]
    RANK.classify(hits, 80)
    hits.sort(key=RANK.sort_key)
    assert hits[0]["match"] == "inside"


def test_hits_without_a_kind_keep_their_order() -> None:
    """Області, де виду не рахують, сортуються як раніше — за балом."""
    hits = [{"score": 80}, {"score": 95}]
    hits.sort(key=RANK.sort_key)
    assert [h["score"] for h in hits] == [95, 80]


def test_an_iotated_start_with_an_ending_is_the_same_word() -> None:
    """«Ja-» латинкою — це «Я»: зсув на «j» не робить слово чужим, на «p» — робить."""
    assert RANK.match_kind(STEM, "jarosinskiiegomu", 80) == "ending"
    assert RANK.match_kind(STEM, "parosinskiiegomu", 80) == "inside"


def test_search_returns_the_split_and_orders_by_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Розклад і порядок — у самому пошуку, тож їх мають і консоль, і `text.find`."""
    from nyshporka import htr_store as S
    from nyshporka.search import decode as D
    from nyshporka.search import store as ST

    raw = [{"name": "r1", "page": "a.jpg", "line_no": 1, "line_index": 0,
            "norm": N(w), "stem": STEM, "score": 100}
           for w in ("Paroszynskiin", "Олександрярошинський", "Ярошинський")]

    monkeypatch.setattr(S, "runs_for_scope", lambda _n: {
        "rows": [{"name": "r1", "pages_done": 1}], "kind": "all", "key": "", "shifra": ""})
    monkeypatch.setattr(ST, "exists", lambda: True)
    monkeypatch.setattr(ST, "stale_count", lambda *_a, **_k: 0)
    monkeypatch.setattr(D, "is_fresh", lambda _r: True)
    monkeypatch.setattr(ST, "sweep", lambda *_a, **_k: {
        "hits": [dict(h) for h in raw], "scanned": 1, "runs": 1, "unindexed": 0,
        "backend": "store"})
    res = S.search("Ярошинський", context=0, rank=False, profile=False, given=False)
    assert res["matches"] == {"exact": 1, "variant": 1, "ending": 0, "inside": 1}
    assert [h.get("match") for h in res["hits"]] == ["exact", "variant", "inside"]
