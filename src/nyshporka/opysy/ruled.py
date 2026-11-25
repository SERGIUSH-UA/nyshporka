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
- номери — ланцюжком якорів (`numbering.number`) з добудовою прочитаних (`dobudova`, типово ввімкнено:
  звірено оком на ДАОО ф.445, кадри 41, 47, 58, 77, 90 — 24.11.2026).

Вхід — тека прогону: `NNNN.txt` (рядок на рядок) і `NNNN.lines.json.gz` (`boxes`, `size`).
`y` справи — пікселі кадру, як його бачив рушій. Числа — машинне читання, НЕ звірене оком.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from nyshporka.opysy.numbering import number

FIELDS = ["page", "part", "row", "y", "no", "no_src", "confirmed", "no_read", "no_span",
          "title", "year", "end", "folios"]

#: Номер на початку рядка: «288», «821.», «136а», «842. По ходатайству…». Літера номера — лише
#: мала одразу за цифрами й не початок слова: з `re.I` «13 Дело» читалось як справа «13Д» з
#: назвою «ело…» (ДАОО ф.445 — 8 рядків з 1416).
NUM_START = re.compile(r"^\s*(\d{1,5})([а-яa-z](?![а-яёіїєґa-z]))?\s*[.,:]?\s*(.*)$")
YEAR = re.compile(r"(1[789]\d\d)")
#: Початок назви справи (`title_starts`): «Дело/Дѣло», «Тоже/То же» — і як їх калічить
#: рушій на рукописі («Тоте», «Топле», «Доже»). Лише з великої: з малої — продовження.
#: «Дело-» з дефісом — шапка таблиці («Дело-|произв.»), не справа.
TITLE_START = re.compile(r"^\s*(Д[ѣеъ]л[оа]\b(?!\s*-)|То\s?[жтш]е|Т[оа][жтшп][еѣі]|Топле|Доже\b)")


def page_lines(run: Path, stem: str) -> tuple[list[tuple[int, int, int, int, str]], tuple[int, int]] | None:
    """Рядки сторінки прогону: [(x0, y0, x1, y1, текст)] і розмір кадру; None — немає чи битий."""
    from nyshporka.htr.layout import load_geometry

    tx = run / f"{stem}.txt"
    if not tx.exists():
        return None
    # немає рамок чи обірваний запис (бокс пішов в offline посеред заходу) — сторінка
    # пропускається й рахується в `bad_pages`, а не валить увесь опис
    d = load_geometry(run, stem)
    if d is None:
        return None
    texts = tx.read_text(encoding="utf-8").split("\n")
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
               title_starts: bool = False, bez_nomera: tuple[int, ...] | list[int] = ()) -> list[dict[str, Any]]:
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
    if bez_nomera:
        # межі справ без номера (`dochyt`: пляма чорнила в колонці №, що не прочиталась числом)
        hs2 = sorted(ln[3] - ln[1] for ln in L)
        tol2 = (hs2[len(hs2) // 2] if hs2 else 40) * 0.7
        for y in bez_nomera:
            if not any(abs(y - s0[0]) <= tol2 for s0 in starts):
                starts.append((y, 0, "", ""))
        starts.sort(key=lambda s0: s0[0])
    syn = {int(y) for y in bez_nomera}          # межі без власного рядка — нічого не «з'їдають»
    recs = []
    for k, (y, n, let, rest) in enumerate(starts):
        y0 = y - 15
        y1 = starts[k + 1][0] - 15 if k + 1 < len(starts) else 10 ** 9
        title, right = [], []
        if rest:
            title.append(rest)
        for ln in L:
            yc = (ln[1] + ln[3]) / 2
            if not (y0 <= yc < y1) or (ln[1] == y and y not in syn):
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


def _tablytsia(pages: dict[str, Any], *, title_starts: bool, dobudova: bool,
               bez: dict[tuple[str, int], list[int]] | None = None) -> tuple[list[dict[str, Any]], int]:
    recs: list[dict[str, Any]] = []
    for stem in sorted(pages):
        lines, _wh, halves = pages[stem]
        for part, (a, b) in enumerate(halves):
            for r in half_cases(lines, a, b, stem, part, title_starts=title_starts,
                                bez_nomera=(bez or {}).get((stem, part), ())):
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
    return number(recs, page_aware=title_starts, dobudova=dobudova), raw


def build(run: Path, out_tsv: Path, *, title_starts: bool = False,
          dobudova: bool = True, dochyt: Path | None = None, meta: Any = None) -> dict[str, Any]:
    """Тека прогону цілих сторінок → таблиця справ TSV (`FIELDS`); підсумок — числа.

    `meta` — метадані агента (`opysy.meta`): сторінки поза таблицею пропускаються, `sprav` —
    знаменник повноти. `dochyt` — тека `opysy.dochyt` з прочитаними кропами: номери колонки № —
    дочитані, межі справ — ще й з плям чорнила за схемою (`dochyt.skhema`)."""
    from nyshporka.opysy import dochyt as DC

    run = Path(run)
    stems = sorted({p.name.split(".")[0] for p in run.glob("*.txt")})
    pages: dict[str, Any] = {}
    bad = 0
    for stem in stems:
        if meta is not None and not meta.u_tablytsi(stem):
            continue
        got = page_lines(run, stem)
        if not got:
            bad += 1
            continue
        lines, (W, H) = got
        # межа розвороту — з рядків прогону, до будь-яких вставок
        pages[stem] = (lines, (W, H), split_spread(lines, W, H))
    recs, raw = _tablytsia(pages, title_starts=title_starts, dobudova=dobudova)
    sprav = int(getattr(meta, "sprav", 0) or 0)
    extra: dict[str, Any] = {}
    mapa = {}
    if dochyt is not None and (Path(dochyt) / DC.MAPA).exists():
        import json

        mapa = json.loads((Path(dochyt) / DC.MAPA).read_text(encoding="utf-8"))
    if mapa and dochyt is not None:
        chyt = DC.chytannia(Path(dochyt))
        # шапка бланка — геть з усіх трьох проходів; ПІСЛЯ підстановки: дочит № прив'язаний до
        # номера рядка вихідного прогону
        def _bez(st: str, L: list[Any], hv: list[tuple[int, int]]) -> list[Any]:
            return DC.bez_shapky(st, L, mapa, hv)

        if any((v or {}).get("shapka") for v in mapa.values()):
            recs, raw = _tablytsia({st: (_bez(st, L, hv), wh, hv) for st, (L, wh, hv) in pages.items()},
                                   title_starts=title_starts, dobudova=dobudova)
        # схема — за чистим прогоном (так її й міряно), злипання — після дочиту номерів
        sk, why = DC.skhema(len(recs), sum(bool(r["confirmed"]) for r in recs), sprav)
        p1 = {st: (_bez(st, DC.pidstavyty(st, L, mapa, chyt)[0], hv), wh, hv)
              for st, (L, wh, hv) in pages.items()}
        recs1, _ = _tablytsia(p1, title_starts=title_starts, dobudova=dobudova)
        zlypli = {(r["page"], int(r["part"])) for r in recs1 if r["no_span"]}
        p2: dict[str, Any] = {}
        bez: dict[tuple[str, int], list[int]] = {}
        for st, (L, wh, hv) in pages.items():
            polovyny = range(len(hv)) if sk == "usi" else [pt for (s2, pt) in zlypli if s2 == st]
            ln2, b = DC.pidstavyty(st, L, mapa, chyt, plyamy_polovyn=polovyny, polovyny_x=hv)
            p2[st] = (_bez(st, ln2, hv), wh, hv)
            for pt, y in b:
                bez.setdefault((st, pt), []).append(y)
        recs, raw = _tablytsia(p2, title_starts=title_starts, dobudova=dobudova, bez=bez)
        extra = {"skhema": sk, "skhema_chomu": why, "dochytano": len(chyt),
                 "shapok": sum(len((v or {}).get("shapka") or {}) for v in mapa.values())}
    out_tsv = Path(out_tsv)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    res = {"pages": len(pages), "bad_pages": bad, "rows_raw": raw, "cases": len(recs),
           "read": sum(r["no_src"] == "read" for r in recs),
           "confirmed": sum(bool(r["confirmed"]) for r in recs), **extra}
    if sprav:
        res["sprav"] = sprav
        res["povnota"] = round(len(recs) / sprav, 3)
    return res
