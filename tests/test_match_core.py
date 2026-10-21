"""Ядро балу `store._match_cdist`: прискорене дає ТОЙ САМИЙ результат до бала.

Еталон — заморожена копія ядра до прискорення (main 6fe58a2, два проходи
`ratio`). Будь-яка розбіжність означає, що пошук роду знайде інше, ніж
знаходив: зсунеться поріг, і нуль по справі перестане означати те, що означав.
"""
from __future__ import annotations

import random

import numpy as np
import pytest
from rapidfuzz import fuzz
from rapidfuzz.process import cdist

from nyshporka.search import store as ST


def _reference(order: list[str], stems: list[str], thresh: int) -> dict[int, tuple[float, int]]:
    if not order:
        return {}
    lens = np.fromiter((len(n) for n in order), dtype=np.int32, count=len(order))
    best: dict[int, tuple[float, int]] = {}
    lmax = int(lens.max())
    cutoff = 0
    if stems:
        cutoff = max(0, int(min(float(ST._partial_bound(len(s), np.int32(lmax), thresh))
                                for s in stems)))
    r = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=cutoff, dtype=np.uint8, workers=-1)
    r_hit = cdist(stems, order, scorer=fuzz.ratio, score_cutoff=thresh, dtype=np.uint8,
                  workers=-1)
    for si, stem in enumerate(stems):
        need = max(4, int(len(stem) * 0.6))
        floor = max(need, len(stem))
        sc = np.where((r_hit[si] >= thresh) & (lens >= need), r_hit[si], 0).astype(np.int32)
        idx = np.flatnonzero((lens >= floor)
                             & (r[si] >= ST._partial_bound(len(stem), lens, thresh)))
        if len(idx):
            pr = cdist([stem], [order[int(j)] for j in idx], scorer=fuzz.partial_ratio,
                       score_cutoff=thresh, dtype=np.uint8, workers=-1)[0]
            sc[idx] = np.maximum(sc[idx], np.where(pr >= thresh, pr, 0).astype(np.int32))
        for j in np.flatnonzero(sc):
            v = float(sc[j])
            cur = best.get(int(j))
            if cur is None or v > cur[0]:
                best[int(j)] = (v, si)
    return best


ABC = "абвгдежзиклмнопрстуфхцчшщ"


def _words(rng: random.Random, stems: list[str], n: int) -> list[str]:
    out = []
    for _ in range(n):
        s = rng.choice(stems)
        mode = rng.random()
        if mode < 0.3:       # спотворений стем
            w = list(s)
            for _ in range(rng.randint(0, 4)):
                p = rng.randrange(len(w) + 1)
                op = rng.random()
                if op < 0.4 and w:
                    w.pop(min(p, len(w) - 1))
                elif op < 0.7:
                    w.insert(p, rng.choice(ABC))
                elif w:
                    w[min(p, len(w) - 1)] = rng.choice(ABC)
            out.append("".join(w))
        elif mode < 0.5:     # стем усередині довшого слова — канал `partial_ratio`
            out.append("".join(rng.choice(ABC) for _ in range(rng.randint(0, 6))) + s
                       + "".join(rng.choice(ABC) for _ in range(rng.randint(0, 6))))
        else:
            out.append("".join(rng.choice(ABC) for _ in range(rng.randint(1, 18))))
    return out


@pytest.mark.parametrize("seed", range(40))
def test_fast_core_equals_reference_on_random_batches(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(8):
        stems = ["".join(rng.choice("абвгдлмнищскій") for _ in range(rng.randint(4, 14)))
                 for _ in range(rng.randint(1, 6))]
        order = _words(rng, stems, rng.randint(1, 300))
        thresh = rng.choice([70, 76, 78, 80, 85, 90])
        assert ST._match_cdist(order, stems, thresh) == _reference(order, stems, thresh)


def test_rounding_edge_does_not_pass_below_threshold() -> None:
    # ratio 77.78 (стем з 11 літер проти «abcdefg»: LCS 7, 200·7/18)
    # округлюється до 78, але поріг 78 не проходить. Слово коротше за стем, тож
    # `partial_ratio` його не рятує — судить лише `ratio`.
    stem = "abcdefghijk"
    order = ["abcdefg", "abcdefghij", "abcdefghijk", "zzzz"]
    assert fuzz.ratio(stem, order[0]) < 78 <= round(fuzz.ratio(stem, order[0]))
    got = ST._match_cdist(order, [stem], 78)
    assert got == _reference(order, [stem], 78)
    assert 0 not in got and 1 in got and 2 in got


def test_first_stem_wins_a_tie() -> None:
    order = ["ковальчинскій"]
    stems = ["ковальчинскій", "ковальчинскій"]
    assert ST._match_cdist(order, stems, 78) == {0: (100.0, 0)}


def test_empty_inputs() -> None:
    assert ST._match_cdist([], ["ковальчинск"], 78) == {}
    assert ST._match_cdist(["ковальчинск"], [], 78) == {}
