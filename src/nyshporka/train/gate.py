"""🚪 Ворота злиття: що НЕ пускати в мітки, і що показати людині.

Найдорожча помилка в псевдо-мітках — не хибне слово, а два тихіші класи:

* **белькіт на порожній смужці** — рушій не вміє мовчати; на лінійці графи
  чи згині він видає слова, арбітр слухняно зводить «найкращий варіант», і
  в мітку їде текст, під яким на аркуші нічого немає;
* **зсув** — правильний текст під ЧУЖИМ кропом. Усі рядки осмислені, тож ні
  око, ні CER цього не бачать; арбітр губить один рядок посередині, і хвіст
  сторінки їде на +1.

Обидва ловляться з ТЕКСТУ (і, за наявності, частки чорнила), без зображень і
без моделей. Що ловиться — понижується до `low` (лишається видимим, у корпус
не йде), а не видаляється: викинуте ніхто не побачить, і не буде як
перевірити, чи ворота ріжуть правильно.

🔴 Розбіжність голосів автопониження НЕ дає. Калібрування в дослідницькому
конвеєрі показало, що вона ріже друковані штампи й заголовки — реальний і
цінний текст, на якому рушіям просто важко. Такі рядки лише показуються
(`suspects`). Так само дорадчою лишається «неопертість» злиття на голоси:
детектор домислених прізвищ, але й він судить лише за схожістю.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from nyshporka.train.text import strip_conflict_marks

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
DIGIT = re.compile(r"\d")
#: Довжина «повного слова». 5, а не 4: у формулярах повно чотирилітерних
#: огризків («тому», «года»), і поріг 4 пропускав белькіт.
WORD_MIN = 5
#: Довга смужка — там є що рятувати; рішення за людиною.
BABBLE_MAX_LEN = 25
#: Розбіжність голосів показується людині лише на коротких рядках.
LONG_ENOUGH = 40
#: Нижче цієї частки чорнила смужка — чистий папір. 0.15%, не 1.2%: метрика
#: міряє КОНТРАСТ, і бліде письмо на вохряному папері дає 0.2%; порожні —
#: 0.00–0.05%. Поріг стоїть там, де промах неможливий.
INK_MIN = 0.0015
#: Середня попарна схожість голосів, нижче якої вони «незгодні».
AGREE_MIN = 45.0
#: Схожість злиття з найближчим голосом, нижче якої рядок «неопертий».
GROUNDED_MIN = 75.0
#: Зсув: скільки перших символів порівнювати (хвіст довгого рядка в PARSeq
#: вироджується), наскільки зсув має бити нуль, скільки рядків поспіль.
SHIFT_HEAD = 60
SHIFT_MARGIN = 8.0
SHIFT_MIN_RUN = 6
SHIFT_SPAN = 2


#: Щільність мітки = символів на одну висоту рядка ширини чорнила. У однієї
#: руки на сторінці вона стала, тож рядок, щільніший за медіану сторінки,
#: несе в мітці більше, ніж видно на кропі: добудоване обрізане слово
#: («Anastazya» при видимому «…tnaza»), два рядки в одному кропі, кроп,
#: поставлений боком. Заміряно на корпусі Скриби PPv3 (5 001 рядок,
#: 14.10.2026): від ×6 — лише отрута (41 кроп голландців боком, ×50–87);
#: у смузі ×3–6 отрути 4 з 10, решта — щільне законне письмо, тож там
#: лише показ людині.
DENSITY_DEMOTE = 6.0
DENSITY_SUSPECT = 3.0
#: Медіана сторінки чесна лише від стількох рядків.
DENSITY_PAGE_MIN = 8


def norm_tok(tok: str) -> str:
    """ъ/ь геть, ѣ→е: рушій те саме коротке слово віддає щоразу з іншим хвостом."""
    return tok.lower().replace("ъ", "").replace("ь", "").replace("ѣ", "е")


def ink_fraction(png: Path) -> float:
    """Частка чорнильних пікселів усередині полігона рядка — з гістограми.

    Кроп має ЧОРНУ заливку поза полігоном (так ріже kraken, і так само —
    наш фолбек); її треба виключити, інакше будь-яка смужка виглядає
    списаною. Рахується з 256-бінної гістограми, без numpy: пакет його не має.
    """
    from PIL import Image

    with Image.open(png) as im:
        hist = im.convert("L").histogram()
    inside = hist[13:]
    n = sum(inside)
    if n < 200:
        return 0.0
    thr = _paper(inside, n) - 28
    ink = sum(c for v, c in enumerate(inside, start=13) if v < thr)
    return ink / n


def _paper(inside: list[int], n: int) -> int:
    """75-й процентиль «внутрішніх» значень гістограми — це папір."""
    acc = 0
    for v, c in enumerate(inside, start=13):
        acc += c
        if acc >= 0.75 * n:
            return v
    return 255


def ink_span(png: Path) -> tuple[int, int] | None:
    """(ширина чорнила, висота кропа) у пікселях; `None` — чорнила нема.

    Ширина — від першої до останньої колонки, де чорнило займає ≥4% висоти:
    одиночні крапки й шум краю полігона її не розтягують. Поріг — посередині
    між папером і найтемнішими 2% пікселів: фіксований відступ від паперу
    на блідому письмі бачив лише кілька штрихів, і шість чистих рядків
    корпусу Скриби вийшли «задовгими» (×6–20).
    """
    from PIL import Image

    with Image.open(png) as im:
        g = im.convert("L")
    w, h = g.size
    inside = g.histogram()[13:]
    n = sum(inside)
    if n < 200 or w < 2:
        return None
    paper = _paper(inside, n)
    acc, dark = 0, paper
    for v, c in enumerate(inside, start=13):
        acc += c
        if acc >= 0.02 * n:
            dark = v
            break
    if paper - dark < 20:
        return None
    thr = paper - (paper - dark) / 2
    mask = g.point(lambda v: 255 if 13 <= v < thr else 0)
    cols = list(mask.resize((w, 1), Image.BOX).getdata())
    hit = [x for x, v in enumerate(cols) if v >= 255 * 0.04]
    if not hit:
        return None
    return hit[-1] - hit[0] + 1, h


def label_density(text: str, png: Path) -> float | None:
    """Символів мітки на одну висоту ширини чорнила; `None` — міряти нема чого."""
    n = len(text.strip())
    span = ink_span(png) if n else None
    if not span or span[0] < 5:
        return None
    return n / (span[0] / span[1])


def density_ratios(dens: dict[Any, float], *, min_n: int = DENSITY_PAGE_MIN) -> dict[Any, float]:
    """Щільність кожного рядка відносно медіани групи (сторінки, руки)."""
    vals = sorted(dens.values())
    if len(vals) < min_n:
        return {}
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {k: v / med for k, v in dens.items()} if med > 0 else {}


def density_outliers(rows: list[tuple[Any, Any, str, Path]], *,
                     floor: float = DENSITY_SUSPECT) -> dict[Any, float]:
    """Рядки корпусу (ключ, група, мітка, кроп), де мітка щільніша за групу ≥ `floor`.

    Для корпусу поза лабораторією (чужі датасети, старий реєстр): групу
    задає той, хто збирає, — сторінка чи рука.
    """
    by: dict[Any, dict[Any, float]] = {}
    for key, grp, text, png in rows:
        d = label_density(text, png)
        if d is not None:
            by.setdefault(grp, {})[key] = d
    out: dict[Any, float] = {}
    for dens in by.values():
        for k, r in density_ratios(dens).items():
            if r >= floor:
                out[k] = r
    return out


def signals(merged: str, voices: list[str], ink: float | None) -> list[str]:
    """Які ознаки не-тексту спрацювали на рядку."""
    toks = TOKEN.findall(merged)
    out: list[str] = []
    if not toks:
        return ["порожньо"]
    if len(toks) >= 3 and max(len(t) for t in toks) < WORD_MIN:
        out.append("розсип")
    if len(toks) >= 3:
        c = Counter(norm_tok(t) for t in toks)
        if c.most_common(1)[0][1] >= 2:
            out.append("повторюваність")
    live = [v for v in voices if v.strip()]
    if len(live) >= 2:
        pairs = [fuzz.ratio(a, b) for i, a in enumerate(live) for b in live[i + 1:]]
        if sum(pairs) / len(pairs) < AGREE_MIN:
            out.append("розбіжність")
    if ink is not None and ink < INK_MIN:
        out.append("чорнила нема")
    return out


def verdict(sig: list[str], merged: str) -> bool:
    """Чи понижувати рядок до `low` АВТОМАТИЧНО.

    Порожній кроп і кроп без чорнила — вирок самі по собі. Решта — лише повний
    портрет белькоту: розсип І повторюваність на короткій смужці без цифр.
    Кожна складова відсіює свій клас хибних спрацювань: розсип без повтору —
    законний уривок («Въ селѣ Ходъ»); повтор без розсипу — двоколонковий
    рядок; цифри — числова комірка.
    """
    if "порожньо" in sig or "чорнила нема" in sig:
        return True
    if len(merged) >= BABBLE_MAX_LEN or DIGIT.search(merged):
        return False
    return {"розсип", "повторюваність"} <= set(sig)


def suspect(sig: list[str], merged: str) -> bool:
    """Показати людині, не понижуючи: голосам тут важко, а чому — не видно."""
    return "розбіжність" in sig and len(merged) < LONG_ENOUGH


def grounded(merged: str, voices: list[str]) -> float:
    """Схожість злиття з найближчим голосом (0–100). Низька — можливий домисел."""
    live = [v for v in voices if v.strip()]
    if not live or not merged.strip():
        return 100.0
    return max(fuzz.ratio(merged.lower(), v.lower()) for v in live)


# ── зсув ─────────────────────────────────────────────────────────────────────
def _sim(llm: list[str], vs: list[list[str]], i: int, off: int) -> float:
    j = i + off
    if j < 0:
        return -1.0
    cand = [v[j][:SHIFT_HEAD] for v in vs if j < len(v) and v[j].strip()]
    return max((fuzz.ratio(llm[i][:SHIFT_HEAD], c) for c in cand), default=-1.0)


def shifted_blocks(llm: list[str], vs: list[list[str]], *, span: int = SHIFT_SPAN,
                   margin: float = SHIFT_MARGIN,
                   min_run: int = SHIFT_MIN_RUN) -> list[tuple[int, int, int]]:
    """Прогони рядків, де ненульовий зсув стабільно б'є нуль: `(від, до, зсув)`.

    🔴 Блоками, а не сторінкою: арбітр не зсуває аркуш цілком — він губить
    один рядок посередині, і їде лише хвіст. Усереднення по сторінці дає
    переможцем 0 і зсуву не бачить.
    """
    per: dict[int, int] = {}
    for i, t in enumerate(llm):
        if not t.strip():
            continue
        sims = {o: _sim(llm, vs, i, o) for o in range(-span, span + 1)}
        best = max(sims, key=lambda o: sims[o])
        if best and sims[best] - sims[0] >= margin:
            per[i] = best
    out: list[tuple[int, int, int]] = []
    cur: list[int] | None = None
    for i in sorted(per):
        if cur and per[i] == cur[2] and i - cur[1] <= 3:
            cur[1] = i
        else:
            if cur and cur[1] - cur[0] + 1 >= min_run:
                out.append((cur[0], cur[1], cur[2]))
            cur = [i, i, per[i]]
    if cur and cur[1] - cur[0] + 1 >= min_run:
        out.append((cur[0], cur[1], cur[2]))
    return out


# ── ворота над сторінкою злиття ──────────────────────────────────────────────
@dataclass
class PageGate:
    page: str
    demoted: list[int] = field(default_factory=list)      # → low
    marks_stripped: list[int] = field(default_factory=list)
    shift_blocks: list[tuple[int, int, int]] = field(default_factory=list)
    suspects: list[tuple[int, str]] = field(default_factory=list)   # (idx, чому)
    dense: list[tuple[int, float]] = field(default_factory=list)    # (idx, ×медіани) → low

    def as_dict(self) -> dict[str, Any]:
        return {"page": self.page, "demoted": self.demoted,
                "dense": [[i, round(r, 1)] for i, r in self.dense],
                "marks_stripped": self.marks_stripped,
                "shift_blocks": [list(b) for b in self.shift_blocks],
                "suspects": [{"idx": i, "why": w} for i, w in self.suspects]}


def dense_why(r: float) -> str:
    return (f"мітка задовга для кропа (щільність ×{r:.1f} від сторінки): добудоване "
            f"з-поза рамки слово, два рядки в кропі або кроп боком")


def gate_page(page: str, merged: list[str], voices: list[list[str]],
              conf: dict[int, str], *, ink_of: Any = None,
              crop_of: Any = None) -> PageGate:
    """Прогнати ворота по сторінці злиття; ПРАВИТЬ `merged` і `conf` на місці.

    `ink_of(idx)` — частка чорнила кропа або `None`, коли кропа немає;
    `crop_of(idx)` — шлях до кропа (для щільності мітки) або `None`.
    """
    g = PageGate(page=page)
    for i, text in enumerate(merged):
        if not text.strip():
            continue
        clean = strip_conflict_marks(text)
        if clean != text or any(ch in clean for ch in "‹›|"):
            clean = "".join(ch for ch in clean if ch not in "‹›|")
            merged[i] = " ".join(clean.split())
            g.marks_stripped.append(i)
            conf[i] = "low"
    for i, text in enumerate(merged):
        if not text.strip():
            continue
        vs = [v[i] if i < len(v) else "" for v in voices]
        ink = ink_of(i) if ink_of is not None else None
        sig = signals(text, vs, ink)
        if verdict(sig, text):
            if conf.get(i) != "low":
                g.demoted.append(i)
            conf[i] = "low"
            continue
        if suspect(sig, text):
            g.suspects.append((i, "голоси розходяться: " + ", ".join(sig)))
        elif grounded(text, vs) < GROUNDED_MIN and len(text) >= 6:
            g.suspects.append((i, "злиття не спирається на жоден голос — можливий "
                                  "домисел (перевірити кроп)"))
    if crop_of is not None:
        dens = {}
        for i, text in enumerate(merged):
            png = crop_of(i) if text.strip() else None
            d = label_density(text, png) if png is not None else None
            if d is not None:
                dens[i] = d
        for i, r in sorted(density_ratios(dens).items()):
            if r >= DENSITY_DEMOTE:
                if conf.get(i) != "low":
                    g.demoted.append(i)
                    g.dense.append((i, r))
                conf[i] = "low"
            elif r >= DENSITY_SUSPECT and conf.get(i) != "low":
                g.suspects.append((i, dense_why(r)))
    blocks = shifted_blocks(merged, voices)
    for a, b, off in blocks:
        g.shift_blocks.append((a, b, off))
        for i in range(a, b + 1):
            if merged[i].strip() and conf.get(i) != "low":
                g.demoted.append(i)
            conf[i] = "low"
    return g


def spelling_splits(glossary: list[str], by_file: dict[str, dict[str, str]],
                    thresh: int = 82) -> list[dict[str, Any]]:
    """Розкол написань: одне словникове слово — різні форми в різних файлах.

    Причт, розрізаний між двома арбітрами, розколюється по межі файлу («Ѳедоръ»
    ×52 проти «Ѳадоръ» ×44), і порядкове злиття цього не бачить: кожен арбітр
    усередині себе бездоганно консистентний.
    """
    out: list[dict[str, Any]] = []
    for term in glossary:
        forms: dict[str, set[str]] = {}
        for fname, rows in by_file.items():
            for text in rows.values():
                for tok in TOKEN.findall(text):
                    if len(tok) >= 4 and fuzz.ratio(tok.lower(), term.lower()) >= thresh:
                        forms.setdefault(tok, set()).add(fname)
        if len(forms) > 1:
            out.append({"term": term,
                        "forms": {f: sorted(files) for f, files in forms.items()}})
    return out


def audit_marks(marks: dict[tuple[str, int], dict[str, Any]],
                voice_lines: Any, *, min_len: int = 12,
                margin: float = SHIFT_MARGIN) -> list[dict[str, Any]]:
    """Чи не з'їхав якір ручної мітки: `draft` мусить збігтися з голосом на
    ТОМУ САМОМУ індексі. `voice_lines(page)` → список списків рядків голосів."""
    out: list[dict[str, Any]] = []
    cache: dict[str, list[list[str]]] = {}
    for (pg, i), rec in marks.items():
        d = str(rec.get("draft") or "").strip()
        if len(d) < min_len:
            continue
        if pg not in cache:
            cache[pg] = voice_lines(pg) or []
        vs = cache[pg]
        sims: dict[int, float] = {}
        for off in range(-3, 4):
            j = i + off
            if j < 0:
                continue
            sc = max((fuzz.ratio(d[:SHIFT_HEAD], v[j][:SHIFT_HEAD]) for v in vs
                      if j < len(v) and v[j].strip()), default=-1.0)
            sims[off] = sc
        if not sims or max(sims.values()) < 55:
            continue
        best = max(sims, key=lambda o: sims[o])
        if best != 0 and sims[best] - sims.get(0, -1.0) >= margin:
            out.append({"page": pg, "idx": i, "shift": best, "draft": d[:45]})
    return out
