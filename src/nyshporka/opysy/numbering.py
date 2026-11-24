"""Номери справ опису: прочитані номери, що складаються в ланцюжок, — опора; проміжки — послідовністю.

Рушій читає номер справи в колонці № ненадійно (рукописний номер — найчастіше ні), а межі справ
бувають зайві чи пропущені. Тому:

1. **Якорі** — самі прочитані номери, що складаються в зростаючий ланцюжок (`chain`); номер, що
   ланцюжок рве, — хибне читання, а не новий відлік.
2. **Між якорями** — послідовність. Рядків більше, ніж бракує номерів, — частина рядків не нові
   справи, а продовження: зайві зливаються з попередньою справою (спершу без номера з малої літери,
   далі найкоротші). Рядків менше — пропущені номери лягають позначкою `no_span` («N–M»).
3. **Підтвердження** (`confirmed`): `neighbors` — сусід по ланцюжку з тим самим кроком;
   `between` — проміжок, де рядків рівно стільки, скільки бракує номерів, і нічого не злито.

Числа — машинне читання, НЕ звірене оком.
"""
from __future__ import annotations

import re
from itertools import pairwise
from typing import Any


def num(s: str) -> int | None:
    """Номер з клітинки: число з короткими уламками довкола («85.», «№ 12»), інакше None."""
    m = re.fullmatch(r"\D{0,2}(\d{1,4})\D{0,3}", (s or "").strip())
    return int(m.group(1)) if m else None


def join(parts: list[str]) -> str:
    """Рядки назви одним текстом; перенос («Подоль- ской») зливається."""
    return re.sub(r"(\w)[-—¬] (\w)", r"\1\2", " ".join(p for p in parts if p))


def merge_into(m: dict[str, Any], r: dict[str, Any]) -> None:
    """Злити рядок `r` у справу `m`: назва, дати, аркуші, ще один шматок місця."""
    m["title"] = join([m["title"], r["title"]])
    m["end"] = (m["end"] + " " + r["end"]).strip()
    m["year"] = m["year"] or r["year"]
    m["folios"] = (m["folios"] + " " + r["folios"]).strip()
    m["y"] += f"; {r['page']}_{r['part']}:{r['y']}"


def chain(reads: list[tuple[int, int]], look: int = 80) -> list[tuple[int, int]]:
    """Найдовший ланцюжок прочитаних номерів, зростаючий і за рядком, і за номером,
    де номер не обганяє рядки більш ніж утричі (пропущені межі) і не відстає нижче 1
    на рядок… а саме: 1 ≤ Δномер ≤ 3·Δрядок + 2. Рівні довжини — менший сумарний
    розрив |Δномер − Δрядок|."""
    n = len(reads)
    best = [(1, 0)] * n          # (довжина, −розрив)
    prev = [-1] * n
    for b in range(n):
        ib, nb = reads[b]
        for a in range(max(0, b - look), b):
            ia, na = reads[a]
            di, dn = ib - ia, nb - na
            if di < 1 or dn < 1 or dn > 3 * di + 2:
                continue
            cand = (best[a][0] + 1, best[a][1] - abs(dn - di))
            if cand > best[b]:
                best[b], prev[b] = cand, a
    if not n:
        return []
    k = max(range(n), key=lambda i: best[i])
    out = []
    while k >= 0:
        out.append(reads[k])
        k = prev[k]
    return out[::-1]


def dobuduvaty(reads: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Прочитані номери, що не лягли в ланцюжок, — добудовані до найближчого очікуваного.

    Рушій губить першу цифру номера на краю колонки («313» там, де в описі 1313) і плутає
    цифру, затерту виправленням («1920» замість 1120). Сирий ланцюжок такий номер відкидає, а
    рахунок справ від попереднього якоря зсувається (ДАОО ф.445 оп.1, кадр 77: 1309 замість
    1313). Очікуване — від найближчого якоря ланцюжка (Δрядок); добудова:
    - **старші розряди** до 2–3-цифрового номера, у вікні ±10 (тризначний) чи ±5 (двозначний);
    - **одна хибна цифра не в кінці** 4–5-цифрового номера, у вікні ±10, якщо кандидат один.
    Результат лишається між сусідніми якорями; однозначні номери не чіпаються. Підтвердження
    дає вже `number()`: добудований номер — якір, лише коли сусід іде з тим самим кроком.
    Замір 24.11.2026 на ф.445: підтверджених 45 % → 59 %.
    """
    from bisect import bisect_left

    ch = chain(reads)
    idx = [i for i, _ in ch]
    anch = dict(ch)
    out: list[tuple[int, int]] = []
    for i, n in reads:
        if i in anch or n < 10:
            out.append((i, n))
            continue
        k = bisect_left(idx, i)
        prev = ch[k - 1] if k > 0 else None
        nxt = ch[k] if k < len(ch) else None
        if prev is None and nxt is None:
            out.append((i, n))
            continue
        e = prev[1] + (i - prev[0]) if prev else nxt[1] - (nxt[0] - i)  # type: ignore[index]
        if n >= 1000:
            s = str(n)
            cands = [c for c in range(e - 10, e + 11) if c > 0 and len(str(c)) == len(s)
                     and sum(x != y for x, y in zip(str(c), s, strict=True)) == 1
                     and str(c)[-1] == s[-1]]
            c, ok = (cands[0], True) if len(cands) == 1 else (n, False)
        else:
            base = 10 ** len(str(n))
            m = round((e - n) / base)
            c = n + m * base
            ok = m >= 1 and abs(c - e) <= (10 if base >= 1000 else 5)
        if ok and prev and c <= prev[1]:
            ok = False
        if ok and nxt and c >= nxt[1]:
            ok = False
        out.append((i, c) if ok else (i, n))
    return out


def number(recs: list[dict[str, Any]], *, page_aware: bool = False,
           dobudova: bool = False) -> list[dict[str, Any]]:
    """Номери за якорями. Повертає записи (частину зайвих злито з попередніми).

    `page_aware` — коли рядків між якорями МЕНШЕ, ніж бракує номерів, рядки на сторінці
    наступного якоря рахуються НАЗАД від нього, а рядки сторінки попереднього — вперед від
    нього; пропущені номери лягають діапазоном (`no_span`) на межу сторінок. Без цього
    недорахунок унизу попередньої сторінки зсував усю верхівку наступної (ДАОО ф.445 оп.1,
    кадр 47: 839–853 замість 846–859 за паспортом, 22.11.2026).

    `dobudova` — прочитані номери, що рвуть ланцюжок, спершу добудовуються (`dobuduvaty`);
    поле `no_read` лишається як прочитано.
    """
    reads = [(i, n) for i, r in enumerate(recs) for n in [num(r["no_read"])] if n and 0 < n < 20000]
    if dobudova:
        reads = dobuduvaty(reads)
    ch = chain(reads)
    for r in recs:
        r.update(no="", no_src="", confirmed="", no_span="")
    if not ch:
        return recs
    # підтверджений якір: сусід по ланцюжку з тим самим кроком (Δномер = Δрядок ≤ 3)
    for k, (i, n) in enumerate(ch):
        ok = any(0 <= k + d < len(ch) and abs(ch[k + d][0] - i) <= 3
                 and ch[k + d][1] - n == ch[k + d][0] - i for d in (-1, 1))
        recs[i].update(no=n, no_src="read", confirmed="neighbors" if ok else "")
    drop: set[int] = set()
    # проміжки між якорями
    for (ia, na), (ib, nb) in pairwise(ch):
        mid = list(range(ia + 1, ib))
        need = nb - na - 1
        # Злиття «зайвих» меж — здогад (слабка назва), тож проміжок, де щось злито, не
        # підтверджений: інакше номери, зсунуті хибним вибором, ішли б як `between` без
        # позначки «звірити» (ДАХмО ф.17 оп.2, кадр 45: 156–170 замість 154–169, 24.11.2026).
        zlyto = len(mid) > need
        if len(mid) > need:
            # зайві межі: спершу без номера з малої, далі найкоротша назва
            def weak(i: int) -> tuple[int, int]:
                t = recs[i]["title"].lstrip(" -—.,")
                return (0 if (t[:1].islower() or not t) else 1, len(recs[i]["title"]))
            extra = sorted(mid, key=weak)[:len(mid) - need]
            drop.update(extra)
            mid = [i for i in mid if i not in extra]
        if page_aware and len(mid) < need and recs[ia]["page"] != recs[ib]["page"]:
            tail = [i for i in mid if recs[i]["page"] == recs[ib]["page"]]
            head = [i for i in mid if i not in tail]
            for k, i in enumerate(head):
                recs[i].update(no=na + 1 + k, no_src="seq", confirmed="")
            for k, i in enumerate(reversed(tail)):
                recs[i].update(no=nb - 1 - k, no_src="seq", confirmed="")
            lo, hi = na + len(head), nb - len(tail) - 1
            if hi > lo:
                last = head[-1] if head else ia
                recs[last]["no_span"] = f"{recs[last]['no']}–{hi}"
            continue
        for k, i in enumerate(mid):
            recs[i].update(no=na + 1 + k, no_src="seq",
                           confirmed="between" if len(mid) == need and not zlyto else "")
        if len(mid) < need:
            last = mid[-1] if mid else ia
            recs[last]["no_span"] = f"{recs[last]['no']}–{nb - 1}"
    # до першого і після останнього якоря — послідовність від якоря
    i0, n0 = ch[0]
    for i in range(i0 - 1, -1, -1):
        v = n0 - (i0 - i)
        if v >= 1:
            recs[i].update(no=v, no_src="seq")
    i1, n1 = ch[-1]
    for i in range(i1 + 1, len(recs)):
        recs[i].update(no=n1 + (i - i1), no_src="seq")
    out: list[dict[str, Any]] = []
    for i, r in enumerate(recs):
        if i in drop and out:
            merge_into(out[-1], r)
            continue
        out.append(r)
    return out
