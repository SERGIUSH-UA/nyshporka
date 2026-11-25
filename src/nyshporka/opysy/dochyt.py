"""🔢 Дочит колонки № і межі справ з чорнила — для рукописного опису, прочитаного цілими сторінками.

Звичайна сегментація (`blla`) на описах систематично калічить колонку №, а з нею — межі справ:

- рамка номера вузька й висока, тож рушій губить першу й останню цифру («1313» → «313»,
  «1314» → «3»); перекіс аркуша тут ні до чого (замір 25.11.2026, ф.445: 22 % номерів лівої
  сторінки, 60 % правої);
- номери правої сторінки розвороту стоять у тіні корінця, і рядком їх сегментація часто не виділяє
  взагалі — справи зливаються (ф.445 оп.1: 1 049 рядків на ~1 565 одиниць).

Тому два кроки, обидва на вже прочитаних сторінках, без нового прогону сегментації:

1. **Дочит:** кожен рядок колонки № — прямокутний кроп із запасом обабіч (1 ширина цифри ≈ 0,33
   висоти рамки), обмежений вертикаллю бланка, читається цілим рядком (`nysh read --whole-line`).
   Замір на чотирьох описах — без втрат: підтверджених номерів +2…+15 пп.
2. **Плями чорнила колонки №** — межі справ незалежно від читання: локальний поріг «темніше за
   околицю», довгі вертикалі (лінії, край корінця) знято, зв'язні плями згуртовано в номери. Кожна
   пляма теж читається цілим рядком; пляма без числа — межа справи без номера.

Де ставити межі з чорнила, вирішує `skhema` — за повнотою (знаменник — `sprav` метаданих агента) і
часткою підтверджених номерів прогону: лікувати там, де справи губляться, і не різати назви там, де
таблиця вже повна (оп.101: −6 пп назв від зайвих меж). Учасник нічого не вибирає.

Заміри — `reports/opysy/SEG_ZAMIR.md` Майстерні (ф.445 оп.1, ЦДІАК ф.442 оп.52, 101, 738).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

#: Ширина цифри — частка висоти рамки рядка; запас дочиту — стільки ширин обабіч.
DIGIT_W = 0.33
ZAPAS = 1.0
#: Вертикаль бланка: стовпчик, темний на стільки висоти рамки.
RULE_FILL = 0.7
#: Чорнило плям: темніше за середнє околиці (вікно 41 px) на стільки.
INK_DELTA = 28
DIR = "dochyt"
KROPY = "kropy"
KROPY_OUT = "kropy_out"
MAPA = "dochyt.json"
#: Вибір схеми меж з чорнила (заміри 25.11.2026 на чотирьох описах; пороги попередні).
POVNOTA_MIN = 0.95
PIDTV_MIN = 0.40


# ── кропи рядків колонки № ──────────────────────────────────────────────────


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _rules(g: np.ndarray, y0: int, y1: int, xa: int, xb: int) -> np.ndarray:
    xa, xb = max(0, xa), min(g.shape[1], xb)
    band = g[max(0, y0):max(y0 + 1, y1), xa:xb]
    if band.size == 0:
        return np.array([], dtype=int)
    dark = band < (np.median(band) - 40)
    return xa + np.where(dark.mean(axis=0) >= RULE_FILL)[0]


def _kryla(g: np.ndarray, box: tuple[int, int, int, int], d: int) -> tuple[int, int]:
    """Межі кропа з запасом `d` обабіч, не далі за вертикаль бланка."""
    x0, y0, x1, y1 = box
    xl, xr = x0 - d, x1 + d
    rl = _rules(g, y0, y1, xl, x0)
    rr = _rules(g, y0, y1, x1, xr)
    xl = int(rl.max()) + 3 if len(rl) else max(0, xl)
    xr = int(rr.min()) - 3 if len(rr) else min(g.shape[1], xr)
    return max(0, min(xl, x0)), max(xr, x1)


def nomerni(lines: list[tuple[int, int, int, int, str]], W: int, H: int
            ) -> list[tuple[int, int, tuple[int, int, int, int, str]]]:
    """Рядки колонки № сторінки — тим самим правилом, що `ruled.half_cases`, плюс короткі рядки лівої
    зони (номер, який рушій прочитав літерами): (номер рядка, половина, рядок)."""
    from nyshporka.opysy import ruled as RU

    out = []
    for part, (x0p, x1p) in enumerate(RU.split_spread(lines, W, H)):
        Wp = max(1, x1p - x0p)
        L = [(i, ln) for i, ln in enumerate(lines) if x0p <= (ln[0] + ln[2]) / 2 < x1p]
        if not L:
            continue
        left = min(ln[0] for _, ln in L)
        for i, ln in L:
            if (ln[0] - left) / Wp >= 0.12:
                continue
            m = RU.NUM_START.match(ln[4])
            if (m and int(m.group(1)) > 0) or len(ln[4].strip()) <= 6:
                out.append((i, part, ln))
    return out


# ── плями чорнила ───────────────────────────────────────────────────────────


def _komponenty(mask: np.ndarray) -> list[list[int]]:
    """Зв'язні плями маски (4-зв'язність): [y0, y1, x0, x1, пікселів]. Відрізками рядків і
    об'єднанням множин — без `scipy` (його немає в ядрі пакета)."""
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev: list[tuple[int, int, int]] = []
    runs: list[tuple[int, int, int, int]] = []
    for y in range(mask.shape[0]):
        row = mask[y]
        if not row.any():
            prev = []
            continue
        dd = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        cur = []
        for s, e in zip(np.flatnonzero(dd == 1), np.flatnonzero(dd == -1), strict=True):
            lab = -1
            for ps, pe, pl in prev:
                if ps < e and s < pe:
                    if lab < 0:
                        lab = find(pl)
                    else:
                        a, b = find(lab), find(pl)
                        if a != b:
                            parent[b] = a
            if lab < 0:
                lab = len(parent)
                parent.append(lab)
            cur.append((int(s), int(e), lab))
            runs.append((y, int(s), int(e), lab))
        prev = cur
    boxes: dict[int, list[int]] = {}
    for y, s, e, lab in runs:
        r = find(lab)
        bx = boxes.get(r)
        if bx is None:
            boxes[r] = [y, y + 1, s, e, e - s]
        else:
            bx[0], bx[1] = min(bx[0], y), max(bx[1], y + 1)
            bx[2], bx[3] = min(bx[2], s), max(bx[3], e)
            bx[4] += e - s
    return list(boxes.values())


def plyamy(g: np.ndarray, xa: int, xb: int, y_top: int, hmed: float) -> list[tuple[int, int, int, int]]:
    """Плями чорнила смуги [xa, xb) нижче `y_top`: рамки номерів (x0, y0, x1, y1) у пікселях кадру."""
    from nyshporka.htr import form_cells as FC

    R = g[y_top:, xa:xb].astype(np.float64)
    if R.size == 0 or R.shape[1] < 20:
        return []
    ink = FC._local_mean(R, 41) - INK_DELTA > R
    # довгі вертикальні смуги (лінії бланка, край корінця) — геть, інакше цифри, що їх торкаються,
    # зливаються з ними в одну задовгу пляму й відкидаються разом
    vert = FC._open_runs(ink, int(1.1 * hmed), axis=0)
    shyr = vert.copy()
    for dx in (1, 2):
        shyr[:, dx:] |= vert[:, :-dx]
        shyr[:, :-dx] |= vert[:, dx:]
    ink = ink & ~shyr
    keep = sorted((y0, y1, x0, x1) for y0, y1, x0, x1, n in _komponenty(ink)
                  if (y1 - y0) <= 1.5 * hmed and (x1 - x0) <= 2.5 * hmed and n >= 25)
    out: list[list[int]] = []
    gap = .22 * hmed
    for y0, y1, x0, x1 in keep:
        if out and y0 - out[-1][3] <= gap and x0 < out[-1][2] + hmed and x1 > out[-1][0] - hmed:
            o = out[-1]
            o[0], o[1], o[2], o[3] = min(o[0], x0), min(o[1], y0), max(o[2], x1), max(o[3], y1)
        else:
            out.append([x0, y0, x1, y1])
    # висока пляма — кілька чисел рядок у рядок: різати за порожніми рядками всередині
    rozrizani: list[list[int]] = []
    for x0, y0, x1, y1 in out:
        if y1 - y0 <= 1.15 * hmed:
            rozrizani.append([x0, y0, x1, y1])
            continue
        prof = ink[y0:y1, x0:x1].sum(axis=1)
        pusto = prof == 0
        a = k = 0
        while k < len(prof):
            if pusto[k]:
                b = k
                while b < len(prof) and pusto[b]:
                    b += 1
                if b - k >= .08 * hmed and k - a >= .25 * hmed:
                    rozrizani.append([x0, y0 + a, x1, y0 + k])
                    a = b
                k = b
            else:
                k += 1
        rozrizani.append([x0, y0 + a, x1, y1])
    # тонкі уламки ліній, широкі й низькі (лінія, край аркуша) — геть; плями того самого рядка — в одну
    good = sorted((o for o in rozrizani if o[3] - o[1] >= .25 * hmed and o[2] - o[0] >= .15 * hmed
                   and (o[2] - o[0]) <= 3.0 * (o[3] - o[1])), key=lambda o: o[1])
    zlyti: list[list[int]] = []
    for o in good:
        if zlyti:
            z = zlyti[-1]
            ov = min(z[3], o[3]) - max(z[1], o[1])
            if ov > .5 * min(z[3] - z[1], o[3] - o[1]):
                z[0], z[1], z[2], z[3] = min(z[0], o[0]), min(z[1], o[1]), max(z[2], o[2]), max(z[3], o[3])
                continue
        zlyti.append(list(o))
    return [(xa + x0, y_top + y0, xa + x1, y_top + y1) for x0, y0, x1, y1 in zlyti]


# ── кропи на диск ───────────────────────────────────────────────────────────


def kropy(run: Path, pages: Path, out: Path, meta: Any = None) -> dict[str, Any]:
    """Кропи дочиту (рядки колонки №) і плям чорнила кожної сторінки таблиці → `<out>/kropy/*.jpg`,
    мапа → `<out>/dochyt.json`. Повтор переписує: кропи — похідне від прочитаних сторінок."""
    from nyshporka.opysy import ruled as RU

    out = Path(out)
    kd = out / KROPY
    kd.mkdir(parents=True, exist_ok=True)
    stems = sorted({p.name.split(".")[0] for p in Path(run).glob("*.txt")})
    stems = [s for s in stems if meta is None or meta.u_tablytsi(s)]
    # 1-й прохід: де колонка № відносно лівого краю назв — за прочитаними номерами кожної сторони
    kadry, zsuv = [], []
    for stem in stems:
        got = RU.page_lines(Path(run), stem)
        if not got:
            continue
        lines, (W, H) = got
        for part, (x0p, x1p) in enumerate(RU.split_spread(lines, W, H)):
            L = [ln for ln in lines if x0p <= (ln[0] + ln[2]) / 2 < x1p]
            dovgi = [ln for ln in L if len(ln[4]) > 12]
            if not dovgi:
                continue
            title_left = int(np.percentile([ln[0] for ln in dovgi], 10))
            left = min(ln[0] for ln in L)
            Wp = max(1, x1p - x0p)
            nom = [(ln[0] + ln[2]) / 2 for ln in L if (ln[0] - left) / Wp < .12
                   and (m := RU.NUM_START.match(ln[4])) and int(m.group(1)) > 0 and len(ln[4]) <= 8]
            poch = [ln[1] for ln in L if RU.TITLE_START.match(ln[4])] or [
                ln[1] for ln in L if (m := RU.NUM_START.match(ln[4])) and int(m.group(1)) > 0 and len(ln[4]) <= 8]
            kc = float(np.median(nom)) if nom else None
            if kc is not None:
                zsuv.append((part, title_left - kc))
            kadry.append((stem, part, x0p, title_left, kc, min(poch) if poch else None))
    zsuv_po = {pt: float(np.median([z for q, z in zsuv if q == pt])) for pt in {q for q, _ in zsuv}}
    zsuv_med = float(np.median([z for _, z in zsuv])) if zsuv else 300.0
    mapa: dict[str, Any] = {}
    g = np.zeros((1, 1), dtype=np.float32)
    hmed = 100.0
    for stem in stems:
        src = next((p for p in (Path(pages) / f"{stem}.jpg", Path(pages) / f"{stem}.png") if p.exists()), None)
        got = RU.page_lines(Path(run), stem)
        if src is None or not got:
            continue
        lines, (W, H) = got
        img = Image.open(src).convert("L")
        g = _gray(img)
        hs = sorted(ln[3] - ln[1] for ln in lines) or [100]
        hmed = float(hs[len(hs) // 2])
        zap: dict[str, Any] = {"nomery": [], "plyamy": []}
        # дочит рядків колонки №
        for i, _part, ln in nomerni(lines, W, H):
            h = max(1, ln[3] - ln[1])
            xl, xr = _kryla(g, ln[:4], round(ZAPAS * DIGIT_W * h))
            cid = f"{stem}__n{i:03d}"
            img.crop((xl, ln[1], xr, ln[3])).save(kd / f"{cid}.jpg", quality=95)
            zap["nomery"].append({"id": cid, "i": i, "box": list(ln[:4])})
        # плями чорнила
        for st2, part, x0p, title_left, kc, y_poch in kadry:
            if st2 != stem or y_poch is None:
                continue
            vuzko = bool(meta is not None and meta.vuzko(part))
            shyr = .8 if vuzko else 1.6
            col_c = kc if kc is not None else title_left - zsuv_po.get(part, zsuv_med)
            if x0p > 0 and kc is None:
                # права сторінка без прочитаних номерів: колонка № — від корінця (найтемніший стовпчик
                # біля межі розвороту) до ~1 висоти рядка правіше; номер буває й у тіні корінця
                h0, h1 = int(.15 * g.shape[0]), int(.9 * g.shape[0])
                a0, a1 = max(0, x0p - 250), min(g.shape[1], x0p + 60)
                sm = np.convolve(g[h0:h1, a0:a1].mean(axis=0), np.ones(15) / 15, mode="same")
                kor = a0 + int(np.argmin(sm[7:-7])) + 7
                xa, xb = int(kor - .25 * hmed), int(min(title_left - 15, kor + 1.0 * hmed))
                col_c = (xa + xb) / 2
            else:
                xa, xb = int(max(x0p, col_c - shyr * hmed)), int(min(title_left - 15, col_c + shyr * hmed))
            dop = hmed if shyr > 1 else .6 * hmed
            for k, b in enumerate(p for p in plyamy(g, xa, xb, max(0, int(y_poch) - 10), hmed)
                                  if abs((p[0] + p[2]) / 2 - col_c) <= dop):
                d = round(DIGIT_W * (b[3] - b[1]))
                cid = f"{stem}__p{part}{k:02d}"
                img.crop((max(0, b[0] - d), b[1] - 6, min(title_left - 10, b[2] + d), b[3] + 6)) \
                    .save(kd / f"{cid}.jpg", quality=95)
                zap["plyamy"].append({"id": cid, "part": part, "box": [int(v) for v in b],
                                      "xv": max(int(b[0]), int(x0p) + 5), "title_left": title_left})
        mapa[stem] = zap
    (out / MAPA).write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")
    return {"kropiv": sum(len(v["nomery"]) + len(v["plyamy"]) for v in mapa.values()),
            "nomeriv": sum(len(v["nomery"]) for v in mapa.values()),
            "plyam": sum(len(v["plyamy"]) for v in mapa.values()), "dir": str(kd)}


def chytannia(out: Path) -> dict[str, str]:
    """Прочитане цілими рядками: id кропа → текст (порожній кроп — немає в словнику)."""
    d = Path(out) / KROPY_OUT
    res = {}
    for t in d.glob("*.txt") if d.is_dir() else ():
        tx = t.read_text(encoding="utf-8").strip()
        if tx:
            res[t.stem] = tx
    return res


# ── схема й підстановка ─────────────────────────────────────────────────────


def skhema(spraw: int, pidtv: int, sprav: int) -> tuple[str, str]:
    """Де ставити межі з чорнила: `usi` — на всю таблицю, `zlypli` — лише на половинах зі злипанням.

    Всюди — коли таблиця губить справи (повнота < `POVNOTA_MIN` від `sprav` метаданих) або прогін
    погано прочитав номери (підтверджено < `PIDTV_MIN`): тоді плями дають і межі, і номери (ф.445:
    повнота 67 → 89 %; оп.52: номерів 34 → 64 %, назв +5 пп). Інакше зайві межі лише ріжуть назви
    (оп.101: −6 пп), тож — тільки там, де ланцюжок бачить злипання."""
    if sprav and spraw < POVNOTA_MIN * sprav:
        return "usi", f"повнота {100 * spraw / sprav:.0f} % від {sprav} справ за метаданими"
    if spraw and pidtv < PIDTV_MIN * spraw:
        return "usi", f"прогін підтвердив лише {100 * pidtv / spraw:.0f} % номерів"
    return "zlypli", "таблиця повна, номери читаються — межі з чорнила лише там, де справи злиплись"


def pidstavyty(stem: str, lines: list[tuple[int, int, int, int, str]], mapa: dict[str, Any],
               chyt: dict[str, str], *, plyamy_polovyn: Iterable[int] = ()) -> tuple[list[Any], list[tuple[int, int]]]:
    """Рядки сторінки з дочитаними номерами й плямами вибраних половин.

    Повертає (рядки, межі без номера [(половина, y)]). Пляма з числом — рядок номера на місці,
    де його побачить `half_cases`; без числа — межа справи без номера."""
    zap = mapa.get(stem) or {}
    out = list(lines)
    for n in zap.get("nomery", []):
        t = chyt.get(n["id"])
        i = n["i"]
        if t and i < len(out) and tuple(out[i][:4]) == tuple(n["box"]):
            out[i] = (*out[i][:4], t)
    bez: list[tuple[int, int]] = []
    vybrani = set(plyamy_polovyn)
    for p in zap.get("plyamy", []):
        if p["part"] not in vybrani:
            continue
        x0, y0, x1, y1 = p["box"]
        out = [ln for ln in out if not (ln[0] < x1 + 40 and ln[2] > x0 - 40 and
                                        ln[1] < y1 and ln[3] > y0 and len(ln[4]) <= 8)]
        m = re.search(r"\d{1,5}", chyt.get(p["id"], ""))
        xv = p.get("xv", x0)
        if m and int(m.group(0)) > 0:
            out.append((xv, y0, xv + (x1 - x0), y1, m.group(0)))
        else:
            bez.append((p["part"], y0))
    return out, bez
