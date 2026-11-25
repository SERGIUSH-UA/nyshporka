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

Заміри — у дослідницькому конвеєрі, не в пакеті: чотири рукописні описи XIX ст. (друковані бланки й
розграфлені від руки).
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
#: Лінія під друкованою шапкою бланка: шукається у верхній частці сторінки, смугами по ширині
#: половини; лінія — ряд, де чорнило заповнює ≥ SHAPKA_FILL смуги, у ≥ SHAPKA_MIN смуг з SHAPKA_SMUH
#: на одній прямій (з нахилом аркуша).
SHAPKA_TOP = 0.30
SHAPKA_SMUH = 16
SHAPKA_FILL = 0.5
SHAPKA_MIN = 10
#: Шапка — смуга, чия медіанна висота рядка нижча за цю частку медіани половини (рукопису).
SHAPKA_DRIBNI = 0.85
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


def _linii(g: np.ndarray, x0p: int, x1p: int) -> list[list[float]]:
    """Суцільні горизонтальні лінії у верхніх SHAPKA_TOP сторінки на половині: [x0, y0, нахил] згори
    вниз. Лінія — ряд, де чорнило заповнює ≥ SHAPKA_FILL смуги, у ≥ SHAPKA_MIN смуг на одній прямій."""
    from nyshporka.htr import form_cells as FC

    y1 = int(SHAPKA_TOP * g.shape[0])
    a, b = int(x0p + .03 * (x1p - x0p)), int(x1p - .03 * (x1p - x0p))
    if y1 < 50 or b - a < 200:
        return []
    reg = g[:y1, a:b]
    ink = FC._local_mean(reg, 41) - INK_DELTA > reg
    w = (b - a) // SHAPKA_SMUH
    pts: list[tuple[int, float, float]] = []
    for k in range(SHAPKA_SMUH):
        fr = ink[:, k * w:(k + 1) * w].mean(axis=1)
        # ±6 рядків: нахил і вигин аркуша в межах смуги; без загортання країв (чорне поле сканера
        # згори інакше ставало «лінією» внизу області)
        pad = np.pad(fr, 6)
        fr = np.max(np.stack([pad[6 + d:6 + d + fr.size] for d in range(-6, 7)]), axis=0)
        rows = np.flatnonzero(fr >= SHAPKA_FILL)
        if not rows.size:
            continue
        for grp in np.split(rows, np.flatnonzero(np.diff(rows) > 3) + 1):
            pts.append((k, a + (k + .5) * w, float(grp.mean())))
    kand: list[tuple[float, int, list[float]]] = []
    for _k0, x0, y0 in pts:
        for nahyl in np.arange(-0.08, 0.0801, 0.005):
            smuhy = {k for k, x, y in pts if abs(y - (y0 + nahyl * (x - x0))) <= 12}
            if len(smuhy) >= SHAPKA_MIN:
                kand.append((float(y0 + nahyl * ((a + b) / 2 - x0)), len(smuhy), [x0, y0, float(nahyl)]))
    # та сама лінія з різних опорних точок — одна, з найбільшим числом смуг
    linii: list[tuple[float, int, list[float]]] = []
    for yc, n, lin in sorted(kand, key=lambda t: -t[1]):
        if all(abs(yc - y2) > 15 for y2, _, _ in linii):
            linii.append((yc, n, lin))
    return [lin for _, _, lin in sorted(linii, key=lambda t: t[0])]


def shapka(g: np.ndarray, x0p: int, x1p: int,
           riadky: list[tuple[int, int, int, int, str]]) -> list[float] | None:
    """Нижня лінія друкованої шапки бланка на половині розвороту: [x0, y0, нахил] — y(x) = y0 +
    нахил·(x − x0); не знайшлась — None.

    Шапка («№ по порядку · СОДЕРЖАНІЕ ДѢЛЪ · …») інакше лягає в назву першої справи половини, а раз
    стає й окремою справою, що зсуває номери (на заміряному бланку — 60 рядків з 476). Під шапкою —
    суцільна друкована лінія; продовження справи з попередньої сторінки лежить уже під нею.

    Котра з ліній верхньої частини — під шапкою, вирішує текст над нею (`riadky` — рядки прогону
    половини): друкована шапка дрібніша за рукопис (медіана 0,62–0,76 висоти рядка проти ~1,0 у тілі
    на заміряних бланках). Береться найнижча лінія, над якою (до попередньої) ≥ 2 рядки з медіанною
    висотою < SHAPKA_DRIBNI рукописного. Так лінії під кожним рядком, що їх друкують деякі бланки («Форма № 1», ДАОО
    ф.445 оп.5), шапкою не стають: над ними — рукопис. 🔴 Лише для бланка (`forma=blank`)."""
    linii = _linii(g, x0p, x1p)
    L = [ln for ln in riadky if x0p <= (ln[0] + ln[2]) / 2 < x1p]
    if not linii or not L:
        return None
    hm = float(np.median([ln[3] - ln[1] for ln in L])) or 1.0
    best = None
    for k, lin in enumerate(linii):
        smuha = [ln for ln in L if nad_shapkoiu(lin, (ln[0] + ln[2]) / 2, (ln[1] + ln[3]) / 2)
                 and (k == 0 or not nad_shapkoiu(linii[k - 1], (ln[0] + ln[2]) / 2, (ln[1] + ln[3]) / 2))]
        if len(smuha) >= 2 and float(np.median([ln[3] - ln[1] for ln in smuha])) < SHAPKA_DRIBNI * hm:
            best = lin
    return best


def nad_shapkoiu(lin: list[float], x: float, y: float) -> bool:
    """Точка (центр рядка) лежить над лінією шапки."""
    x0, y0, nahyl = lin
    return y < y0 + nahyl * (x - x0)


def bez_shapky(stem: str, lines: list[Any], mapa: dict[str, Any],
               polovyny_x: list[tuple[int, int]]) -> list[Any]:
    """Рядки сторінки без тих, що над лінією шапки своєї половини (`shapka` у мапі дочиту)."""
    sh = (mapa.get(stem) or {}).get("shapka") or {}
    if not sh:
        return lines
    out = []
    for ln in lines:
        xc, yc = (ln[0] + ln[2]) / 2, (ln[1] + ln[3]) / 2
        part = next((k for k, (a, z) in enumerate(polovyny_x) if a <= xc < z), -1)
        lin = sh.get(str(part))
        if lin is not None and nad_shapkoiu(lin, xc, yc):
            continue
        out.append(ln)
    return out


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
        if meta is not None and meta.forma == "blank":
            sh = {str(pt): lin for pt, (a, z) in enumerate(RU.split_spread(lines, W, H))
                  if (lin := shapka(g, a, z, lines)) is not None}
            if sh:
                zap["shapka"] = sh
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
            "shapok": sum(len(v.get("shapka") or {}) for v in mapa.values()),
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
               chyt: dict[str, str], *, plyamy_polovyn: Iterable[int] = (),
               polovyny_x: list[tuple[int, int]] | None = None) -> tuple[list[Any], list[tuple[int, int]]]:
    """Рядки сторінки з дочитаними номерами й плямами вибраних половин.

    Повертає (рядки, межі без номера [(половина, y)]). Пляма з числом — рядок номера на місці,
    де його побачить `half_cases`; без числа — межа справи без номера.

    Одне джерело номера на половину: де стоять плями, дочит № не підставляється (`polovyny_x` —
    межі половин, щоб знати, чия). Обидва разом дають два початки на одному рядку (дочит «98»
    поруч із плямою «5»): на заміряному описі збіг номерів з еталоном падав з 90 до 78 %."""
    zap = mapa.get(stem) or {}
    vybrani = set(plyamy_polovyn)
    plyamy = [p for p in zap.get("plyamy", []) if p["part"] in vybrani]
    # під плямою знімається короткий рядок колонки № — за ВИХІДНИМ текстом: дочитаний номер буває
    # довшим (у кроп із запасом заходить дата сусідньої колонки), і тоді лишалось би два номери
    # на одному місці (на заміряному описі збіг номерів з еталоном 90 → 78 %)
    het = {i for i, ln in enumerate(lines) for p in plyamy
            if ln[0] < p["box"][2] + 40 and ln[2] > p["box"][0] - 40 and ln[1] < p["box"][3]
            and ln[3] > p["box"][1] and len(ln[4]) <= 8}
    out = list(lines)
    def _chyia(b: list[int]) -> int:
        xc = (b[0] + b[2]) / 2
        for k, (a, z) in enumerate(polovyny_x or [(-10**9, 10**9)]):
            if a <= xc < z:
                return k
        return -1

    for n in zap.get("nomery", []):
        if vybrani and _chyia(n["box"]) in vybrani:
            continue
        t = chyt.get(n["id"])
        i = n["i"]
        if t and i < len(out) and tuple(out[i][:4]) == tuple(n["box"]):
            out[i] = (*out[i][:4], t)
    out = [ln for i, ln in enumerate(out) if i not in het]
    bez: list[tuple[int, int]] = []
    sh = zap.get("shapka") or {}
    for p in plyamy:
        x0, y0, x1, y1 = p["box"]
        lin = sh.get(str(p["part"]))
        if lin is not None and nad_shapkoiu(lin, (x0 + x1) / 2, (y0 + y1) / 2):
            continue              # пляма в шапці бланка («№») — не справа; за ЦЕНТРОМ: номер, що
            #                       торкається лінії шапки, верхом лежить над нею (ф.445, №136)
        m = re.search(r"\d{1,5}", chyt.get(p["id"], ""))
        xv = p.get("xv", x0)
        if m and int(m.group(0)) > 0:
            out.append((xv, y0, xv + (x1 - x0), y1, m.group(0)))
        else:
            bez.append((p["part"], y0))
    return out, bez
