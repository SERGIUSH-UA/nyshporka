"""📖 Сторінка розвороту: кадр знято розворотом, а набір зводить одну сторінку.

Плівки FamilySearch і більшість архівних зйомок книг кладуть у кадр дві сторінки.
Рука на них зазвичай та сама, рядків удвічі більше, тож мітки з однієї сторінки
дають ту саму руку за половину ціни. `mark_side` записує в набір рядки обраної
сторінки; експорт, черга розмітки й ворота далі працюють лише з ними
(`SetSpec.own_lines`), а аркуш із рамками показує кадр цілим.

🔴 Межа — НАЙШИРША смуга кадру без рамок у середній частині, а не перший x без
рамок. Рядок сповідки чи метрики розрізано лінійками граф на 3–5 рамок, і
проміжки між графами теж порожні: перший такий x на кадрі 1798 р. ліг на 0,40
ширини — посеред лівої сторінки (пілот 07.11.2026). Корінець розвороту ширший
за будь-який проміжок між графами.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SIDES = ("left", "right")
#: Де шукати корінець: середня частина кадру.
LO, HI = 0.30, 0.70
#: Центральне вікно, де корінець шукається першим.
CENTER = (0.44, 0.58)
STEP = 4


class SpreadError(ValueError):
    """Немає рамок або сторона не та."""


def _span(b: Any) -> tuple[int, int] | None:
    """[x0, y0, x1, y1] або полігон → (x0, x1)."""
    if not b:
        return None
    if isinstance(b[0], (list, tuple)):
        xs = [int(p[0]) for p in b]
        return min(xs), max(xs)
    return int(b[0]), int(b[2])


def _widest_low_run(spans: list[tuple[int, int]], width: int, lo: float,
                    hi: float) -> tuple[int, int, int] | None:
    """Найширша смуга з найменшим покриттям у [lo, hi] ширини: (x, ширина px, покриття)."""
    xs = list(range(int(width * lo), int(width * hi), STEP))
    if not xs:
        return None
    cov = [sum(1 for a, c in spans if a <= x <= c) for x in xs]
    low = min(cov)
    best: tuple[int, int, int] | None = None   # (довжина, перший, останній)
    start = None
    for i, c in enumerate([*cov, low + 1]):
        if c == low and start is None:
            start = i
        elif c != low and start is not None:
            run = (i - start, start, i - 1)
            if best is None or run[0] > best[0]:
                best = run
            start = None
    assert best is not None
    n, a, z = best
    return (xs[a] + xs[z]) // 2, n * STEP, low


def gutter(boxes: list[Any], width: int) -> tuple[int, int, int]:
    """Корінець розвороту: (x, ширина смуги в px, скільки рамок її перетинає).

    Спершу — центральне вікно кадру (`CENTER`): корінець майже завжди там, і
    чиста смуга в ньому — він, хоч би й вужча за проміжок між графами деінде
    (кадр 1798 р., хвиля fsi 07.11.2026: корінець 0,506 на 8–12 px, а проміжок між
    графою віку й графою показань лівої сторінки на 0,39 — на 20 px). Немає в
    центрі смуги з покриттям ≤ 1 — найширша смуга з найменшим покриттям у
    середній частині кадру.
    """
    spans = [s for s in (_span(b) for b in boxes) if s]
    if not spans or width <= 0:
        raise SpreadError("на сторінці немає рамок рядків")
    mid = _widest_low_run(spans, width, *CENTER)
    if mid is not None and mid[2] <= 1:
        return mid
    got = _widest_low_run(spans, width, LO, HI)
    assert got is not None
    return got


def side_lines(boxes: list[Any], width: int, side: str) -> list[int]:
    """Індекси рядків обраної сторінки розвороту — за центром рамки."""
    if side not in SIDES:
        raise SpreadError(f"сторона «{side}» невідома: {' | '.join(SIDES)}")
    x, _, _ = gutter(boxes, width)
    out = []
    for i, b in enumerate(boxes):
        s = _span(b)
        if s is None:
            continue
        if ((s[0] + s[1]) / 2 < x) == (side == "left"):
            out.append(i)
    return out


@dataclass
class SideReport:
    set: str
    side: str
    pages: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


#: Корінець, який перетинають рамки, або смуга вужча за це — розворот сумнівний.
MIN_GAP_PX = 40


def mark_side(name: str, side: str, *, pages: list[str] | None = None,
              dry_run: bool = False, ws: Any = None) -> SideReport:
    """Записати в набір рядки сторінки `side` кожного кадру (або лише `pages`).

    `side=""` знімає позначку: набір знову зводить кадри цілими.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.train import cut as C
    from nyshporka.train import sets as S

    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    rep = SideReport(set=name, side=side)
    if not side:
        if not dry_run:
            spec.side = {}
            reg.save(spec)
        return rep
    if side not in SIDES:
        raise SpreadError(f"сторона «{side}» невідома: {' | '.join(SIDES)}")
    if not spec.source_run:
        raise SpreadError(f"набір «{name}» нарізаний не з прогону — рамок немає")
    have = sorted(reg.crop_pages(spec))
    todo = [p for p in have if not pages or p in set(pages)]
    old = spec.side or {}
    if pages and old.get("side") and old.get("side") != side:
        # Інша сторона лише для частини сторінок дала б набір, що зветься «right», а на
        # решті сторінок тримає рядки лівої: сторона в наборі одна на всі сторінки.
        raise SpreadError(f"набір «{name}» позначено стороною «{old['side']}» — нову сторону "
                          f"ставлять усім сторінкам разом (без --pages)")
    same = old.get("side") == side
    got_pages: dict[str, list[int]] = dict(old.get("pages") or {}) if same else {}
    gut: dict[str, int] = dict(old.get("gutter") or {}) if same else {}
    for pg in todo:
        geo = C.page_geometry(spec.source_run, pg, w)
        if geo is None:
            got_pages.pop(pg, None)
            gut.pop(pg, None)
            rep.warnings.append(f"{pg}: прогін не зберіг рамок — сторінку лишено цілою")
            continue
        boxes = geo.get("boxes") or []
        width = int(geo["size"][0])
        x, gap, crossing = gutter(boxes, width)
        idx = side_lines(boxes, width, side)
        if crossing or gap < MIN_GAP_PX:
            rep.warnings.append(f"{pg}: корінець непевний (смуга {gap} px, рамок через неї "
                                f"{crossing}) — можливо, це не розворот; перевір аркуш")
        got_pages[pg] = idx
        gut[pg] = x
        rep.pages[pg] = {"lines": len(idx), "of": len(boxes), "gutter": x, "gap": gap}
    if not dry_run:
        spec.side = {"side": side, "pages": got_pages, "gutter": gut}
        reg.save(spec)
    return rep


__all__ = ["MIN_GAP_PX", "SIDES", "SideReport", "SpreadError", "gutter", "mark_side",
           "side_lines"]
