"""Таблиця рукописного опису без друкованого бланку — з рядків цілої прочитаної сторінки.

Опис на аркушах, розграфлених олівцем ледь помітно, колонками не ріжеться: вертикалі майже не
видно. Натомість сторінка читається ЦІЛОЮ звичайним прогоном (`nysh read <тека сторінок>`:
рушій сегментує такі аркуші добре), а таблиця збирається з рамок рядків:

- розворот (ширина > 1.2 висоти) ділиться на дві сторінки за найширшим порожнім проміжком
  біля середини;
- справа починається рядком, що стоїть у лівій зоні сторінки й починається з числа
  («288», «821.», «842. По ходатайству…»); число — № справи (`no_src=read`);
- `title_starts` — ще й рядком, що починається словом «Дело», «Тоже» (як його калічить
  рушій), коли № у колонці не прочитався числом;
- назва — рядки середньої смуги між початком цієї справи й наступної; число, що злилося з
  першим рядком назви, з неї зрізається;
- рік і аркуші — короткі рядки правої зони тієї самої висоти: рік — `18xx/19xx` або дробові
  дати «24/III 1856»; аркуші — останнє коротке число;
- номери — ланцюжком якорів (`numbering.number`).

Вхід — тека прогону: `NNNN.txt` (рядок на рядок) і `NNNN.lines.json.gz` (`boxes`, `size`).
`y` справи — пікселі кадру, як його бачив рушій. Числа — машинне читання, НЕ звірене оком.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path
from typing import Any

from nyshporka.opysy.numbering import number

FIELDS = ["page", "part", "row", "y", "no", "no_src", "confirmed", "no_read", "no_span",
          "title", "year", "end", "folios"]

NUM_START = re.compile(r"^\s*(\d{1,5})\s*([а-яa-z])?\s*[.,:]?\s*(.*)$", re.I)
YEAR = re.compile(r"(1[789]\d\d)")
#: Початок назви справи (`title_starts`): «Дело/Дѣло», «Тоже/То же» — і як їх калічить
#: рушій на рукописі («Тоте», «Топле», «Доже»). Лише з великої: з малої — продовження.
#: «Дело-» з дефісом — шапка таблиці («Дело-|произв.»), не справа.
TITLE_START = re.compile(r"^\s*(Д[ѣеъ]л[оа]\b(?!\s*-)|То\s?[жтш]е|Т[оа][жтшп][еѣі]|Топле|Доже\b)")


def page_lines(run: Path, stem: str) -> tuple[list[tuple[int, int, int, int, str]], tuple[int, int]] | None:
    """Рядки сторінки прогону: [(x0, y0, x1, y1, текст)] і розмір кадру; None — немає чи битий."""
    tx, lj = run / f"{stem}.txt", run / f"{stem}.lines.json.gz"
    if not (tx.exists() and lj.exists()):
        return None
    texts = tx.read_text(encoding="utf-8").split("\n")
    try:
        with gzip.open(lj, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, EOFError, ValueError):
        # обірваний запис рамок (бокс пішов в offline посеред заходу) — сторінка
        # пропускається й рахується в `bad_pages`, а не валить увесь опис
        return None
    out = []
    for i, b in enumerate(d.get("boxes") or []):
        if b and i < len(texts) and texts[i].strip():
            out.append((int(b[0]), int(b[1]), int(b[2]), int(b[3]), texts[i].strip()))
    size = tuple(d.get("size") or (max((b[2] for b in out), default=1), max((b[3] for b in out), default=1)))
    return out, (int(size[0]), int(size[1]))


def split_spread(lines: list[tuple[int, int, int, int, str]], W: int, H: int) -> list[tuple[int, int]]:
    """Межі сторінок у кадрі: одна або дві (розворот)."""
    if W <= 1.2 * H:
        return [(0, W)]
    # найширший проміжок без рядків у середній третині
    occ = [0] * (W // 10 + 1)
    for x0, _, x1, _, _ in lines:
        for k in range(max(0, x0 // 10), min(len(occ), x1 // 10 + 1)):
            occ[k] += 1
    lo, hi = len(occ) // 3, 2 * len(occ) // 3
    best, run_s, cur = (W // 2, W // 2), None, None
    for k in range(lo, hi):
        if occ[k] == 0:
            run_s = k if run_s is None else run_s
            cur = (run_s * 10, k * 10)
            if cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            run_s = None
    mid = (best[0] + best[1]) // 2
    return [(0, mid), (mid, W)]


def half_cases(lines: list[tuple[int, int, int, int, str]], x0p: int, x1p: int, stem: str, part: int, *,
               title_starts: bool = False) -> list[dict[str, Any]]:
    """Справи половини розвороту. `title_starts` — ще й початок справи за назвою
    («Дело…», «Тоже…» з великої на початку рядка), коли № у колонці не прочитався числом.
    """
    Wp = max(1, x1p - x0p)
    L = sorted([ln for ln in lines if x0p <= (ln[0] + ln[2]) / 2 < x1p], key=lambda ln: (ln[1], ln[0]))
    if not L:
        return []
    def rel(x: float) -> float:
        return (x - x0p) / Wp

    # ліва межа тексту сторінки — щоб «ліва зона» не залежала від полів
    left = min(ln[0] for ln in L)
    starts = []
    for ln in L:
        m = NUM_START.match(ln[4])
        if m and (ln[0] - left) / Wp < 0.12 and int(m.group(1)) > 0:
            starts.append((ln[1], int(m.group(1)), (m.group(2) or ""), m.group(3)))
    if title_starts:
        # Номер у колонці рушій часто читає як «бит», «85.» — справа без числа зливалась із
        # попередньою. Назва ж майже завжди починається з «Дело/Тоже». Рядок назви, що стоїть
        # на висоті вже знайденого числа, — та сама справа.
        hs = sorted(ln[3] - ln[1] for ln in L)
        tol = (hs[len(hs) // 2] if hs else 40) * 0.7
        for ln in L:
            # Без умови «не в лівій зоні»: на сторінці, де колонка № не прочиталась зовсім,
            # лівий край тексту — це вже колонка назв (права сторінка розвороту).
            if not TITLE_START.match(ln[4]):
                continue
            if any(abs(ln[1] - s[0]) <= tol for s in starts):
                continue
            starts.append((ln[1], 0, "", ln[4]))
        starts.sort(key=lambda s: s[0])
    recs = []
    for k, (y, n, let, rest) in enumerate(starts):
        y0 = y - 15
        y1 = starts[k + 1][0] - 15 if k + 1 < len(starts) else 10 ** 9
        title, right = [], []
        if rest:
            title.append(rest)
        for ln in L:
            yc = (ln[1] + ln[3]) / 2
            if not (y0 <= yc < y1) or ln[1] == y:
                continue
            if rel(ln[0]) >= 0.62 and len(ln[4]) <= 18:
                right.append((ln[0], ln[4]))
            elif (ln[0] - left) / Wp < 0.12 and (m2 := NUM_START.match(ln[4])) and not m2.group(3):
                continue
            else:
                title.append(ln[4])
        right.sort()
        end = " ".join(t for _, t in right)
        yrs = YEAR.findall(end)
        fol = ""
        for _, t in reversed(right):
            if re.fullmatch(r"\s*\d{1,4}\s*[.,]?\s*", t):
                fol = re.sub(r"\D", "", t)
                break
        recs.append({"page": stem, "part": part, "row": k, "y": f"{int(y0)}-{int(min(y1, 99999))}",
                     "no_read": f"{n}{let}" if n else "", "title": " ".join(title).strip(),
                     "year": yrs[-1] if yrs else "", "end": end, "folios": fol})
    # рядки над першим номером — хвіст справи з попередньої сторінки
    if starts:
        head = [ln[4] for ln in L if (ln[1] + ln[3]) / 2 < starts[0][0] - 15
                and not ((ln[0] - left) / Wp < 0.12 and NUM_START.match(ln[4]))]
        if head:
            recs.insert(0, {"page": stem, "part": part, "row": -1, "y": "", "no_read": "", "cont": True,
                            "title": " ".join(head), "year": "", "end": "", "folios": ""})
    return recs


def build(run: Path, out_tsv: Path, *, title_starts: bool = False) -> dict[str, Any]:
    """Тека прогону цілих сторінок → таблиця справ TSV (`FIELDS`); підсумок — числа."""
    run = Path(run)
    stems = sorted({p.name.split(".")[0] for p in run.glob("*.txt")})
    recs: list[dict[str, Any]] = []
    bad = 0
    for stem in stems:
        got = page_lines(run, stem)
        if not got:
            bad += 1
            continue
        lines, (W, H) = got
        for part, (a, b) in enumerate(split_spread(lines, W, H)):
            for r in half_cases(lines, a, b, stem, part, title_starts=title_starts):
                if r.get("cont"):
                    if recs:
                        recs[-1]["title"] = (recs[-1]["title"] + " " + r["title"]).strip()
                    continue
                recs.append(r)
    # № — ланцюжком якорів: прочитані номери, що складаються в зростаючий ряд, — опора;
    # хибні межі (дата «8 мая» з лівого краю, число в назві) між якорями зливаються з
    # попередньою справою
    raw = len(recs)
    for r in recs:
        r.setdefault("cont", False)
    recs = number(recs, page_aware=title_starts)
    out_tsv = Path(out_tsv)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    return {"pages": len(stems), "bad_pages": bad, "rows_raw": raw, "cases": len(recs),
            "read": sum(r["no_src"] == "read" for r in recs),
            "confirmed": sum(bool(r["confirmed"]) for r in recs)}
