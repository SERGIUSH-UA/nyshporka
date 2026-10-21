"""Смуги запису (`record._bands`): прискорений цикл дає ті самі записи, що й до нього.

Еталон — заморожена копія циклу до прискорення (main 6fe58a2). Порядок `left`
вирішує нічию в `_best_set`, тож порівнюються не лише бали, а й самі ознаки.
"""
from __future__ import annotations

import random

import pytest

from nyshporka.search import record as R


def _reference(pg: R.Page, weigh: R.Weigh) -> list[tuple[float, list[R.Mark], bool]]:
    marks = R._one_term_per_token(pg.marks, weigh)
    boxed = [m for m in marks if m.box]
    out: list[tuple[float, list[R.Mark], bool]] = []
    loose = [m for m in marks if not m.box]
    if loose:
        runs = {m.run for m in loose}
        n = R._words([ln for ln in pg.lines if ln[0] in runs and ln[1] is None])
        got = R._best_set(loose, weigh, n, need=R.MIN_TERMS_PAGE)
        if got[0] > 0:
            out.append((got[0], got[1], False))
    if not boxed or not pg.heights:
        return out
    hs = sorted(pg.heights)
    span = R.BAND * max(hs[len(hs) // 2], 1)
    placed = [(run, y, n) for run, y, n in pg.lines if y is not None]
    left = sorted(boxed, key=lambda m: R._top(m))
    while left:
        best: tuple[float, list[R.Mark]] = (0.0, [])
        for a in left:
            lo, hi = R._top(a) - span * 0.15, R._top(a) + span
            inside = [m for m in left if lo <= R._mid(m) <= hi]
            n = R._words([ln for ln in placed if lo <= (ln[1] or 0.0) <= hi])
            got = R._best_set(inside, weigh, n)
            if got[0] > best[0]:
                best = got
        if best[0] <= 0:
            break
        out.append((best[0], best[1], True))
        y_lo = min(R._top(m) for m in best[1])
        y_hi = max(R._bottom(m) for m in best[1])
        left = [m for m in left if not (y_lo <= R._mid(m) <= y_hi)]
    return out


def _page(rng: random.Random) -> tuple[R.Page, R.Weigh]:
    runs = ["писар", "дяк", "скриба"][:rng.randint(1, 3)]
    pg = R.Page(page="0001.jpg")
    n_lines = rng.randint(1, 60)
    for no in range(1, n_lines + 1):
        run = rng.choice(runs)
        geo = rng.random() > 0.15
        top = rng.choice([no * 40, no * 40, rng.randint(0, 2500)])  # бувають однакові висоти
        box = (10, top, 900, top + rng.choice([30, 35, 40])) if geo else None
        if box:
            pg.heights.append(box[3] - box[1])
        words = rng.randint(1, 9)
        pg.lines.append((run, (box[1] + box[3]) / 2 if box else None, words))
        for k in range(rng.randint(0, 3)):
            pg.marks.append(R.Mark(term=rng.randint(0, 6), score=rng.choice([80.0, 85.0, 90.0, 100.0]),
                                   token=f"t{no}_{k}", run=run, line_no=no, line="", box=box))
    weigh = R.Weigh({t: rng.choice([0.001, 0.01, 0.05, 0.2]) for t in range(7)})
    return pg, weigh


@pytest.mark.parametrize("seed", range(60))
def test_fast_bands_equal_reference(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(10):
        pg, weigh = _page(rng)
        assert R._bands(pg, weigh) == _reference(pg, weigh)


def test_window_words_counts_one_voice() -> None:
    words_in = R._window_words([("писар", 10.0, 4), ("дяк", 10.0, 6), ("писар", 50.0, 3)])
    assert words_in(0, 20) == (4 + 6) / 2
    assert words_in(0, 60) == (4 + 6 + 3) / 2
    assert words_in(40, 60) == 3
    assert words_in(70, 90) == 0
