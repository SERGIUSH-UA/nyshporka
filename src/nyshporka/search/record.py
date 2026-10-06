"""🏠 Канал запису: родина в межах одного запису, через усі колонки.

🔴 **Навіщо.** Метрика, сповідка, ревізія — таблиці. Ім'я дитини стоїть в одній
колонці, батьки в другій, кума в третій, і рушій читає їх окремими рядками.
Прізвищний канал і канал імен (`anchors`) дивляться на РЯДОК, тож запис, де
прізвище батька рушій скалічив, для них не існує, хоча поруч, у сусідніх
колонках, стоять ім'я дитини, по батькові матері й прізвище куми. Замір, який
це купив (метрика народження 1870-х): ім'я дитини прочитано чисто, а батька —
ім'я, по батькові й прізвище — рушій скалічив до невпізнання; прізвищний пошук
по книзі дав 4475 збігів на 193 сторінки, і цього запису серед них не було.
Ознаки, зведені в межах запису, ставлять його першим у книзі.

🔴 **Межа — запис, а не сторінка.** На сторінці метрики стоїть чотири-вісім
записів, і зведені по сторінці ознаки з'єднують чужих людей: ім'я сина з
одного запису, по батькові батька з другого, ім'я матері з третього (замір:
три різні родини давали сторінці бал вищий за справжній запис). Запис тут —
смуга висоти `BAND` медіанних рядків у геометрії сторінки, через усі колонки
й обидві половини розвороту.

🔴 **Вага ознаки — неймовірність випадкового збігу в САМІЙ смузі.** Частота
ознаки `f` береться з книги — на слово, а не на сторінку; смуга з `N` словами
зустріне її випадково з імовірністю `1 − (1 − f)^N`, і вага — `−ln` цієї
імовірності. Звідси обидва потрібні наслідки без ручних ваг і стоп-списків:
ім'я з шапки графи чи «Марія» в щільному списку (смуга — сотня слів) важать
нуль самі собою, а та сама «Марія» в короткому записі метрики — ні. Вага за
часткою СТОРІНОК цього не розрізняла: на родовідній книзі ДАХмО 230-1-13
десяток частих імен у довгій смузі давав більше, ніж прізвище роду з двома
іменами в акті, і контрольний акт стояв 642-м.

⚠ Канал подає запис на око, а не вирішує. Двоє людей з однаковими ім'ям і
прізвищем в одному селі — звичайна річ (замір: два тезки-ровесники в одному
селі 1870-х), і розрізняє їх лише повний запис.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from nyshporka.records.names import norm_given, norm_patronymic
from nyshporka.utils.translit import normalize_archival

#: Висота запису в медіанних рядках сторінки. Запис народження в метриці займає
#: в колонці батьків п'ять-шість рядків (замір на метриці 1870-х — ім'я
#: дитини й остання кума за 5.3 медіанного рядка).
BAND = 6.0
#: Ознаку, яку смуга звичайного розміру зустрічає випадково частіше, ніж у
#: половині випадків, відповідь називає окремо: вона майже нічого не важить.
COMMON_CHANCE = 0.5
#: Скільки різних ознак потрібно запису, щоб стати кандидатом.
MIN_TERMS = 2
#: Пороги. Ім'я й по батькові — як у каналі імен (`anchors`); прізвище — як у
#: прізвищному свіпі за замовчуванням.
THR_GIVEN = 80.0
#: По батькові — нижче: воно довге й калічиться в середині (замір: рушій
#: замінив першу літеру й з'їв склад — бал 78 проти справжнього по батькові).
THR_PATR = 76.0
#: Ім'я коротше за себе більш ніж на літеру — обрізок на межі рядка
#: («Тана» → Татіана, «Миха» → Михайло), і в списку він стоїть у кожному рядку.
GIVEN_SHORT = 1
THR_SURNAME = 80.0
#: Коротший токен не порівнюється.
MIN_TOK = 4
#: Прізвище — від п'яти літер: чотирилітерний уламок («чкомъ» → `ckom`) на 80
#: збігається з відмінковою формою роду на -ко («…комъ») і з кожним «жинка».
MIN_SURNAME = 5
#: Без геометрії межа запису невідома, і зводиться вся сторінка — а на ній
#: чотири-вісім записів, де два імена родини сходяться випадково (замір:
#: латинський голос польської книги 1920-х, 303 «записи» на 224 сторінки). Тут вимога на
#: одну ознаку більша.
MIN_TERMS_PAGE = MIN_TERMS + 1

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class Term:
    """Одна ознака родини."""

    #: Як її назвати людині: «Пантелеймон», «Харитонова», «прізвище роду».
    label: str
    #: surname · given · patronymic
    kind: str
    #: Ключі порівняння, вже нормалізовані тим кодом, яким порівнюється токен.
    keys: tuple[str, ...]


@dataclass(frozen=True)
class Terms:
    terms: tuple[Term, ...] = ()
    #: Скільки людей роду розглянуто і скільки з них без дат.
    people: int = 0
    undated: int = 0
    years: tuple[int, int] | None = None

    @property
    def empty(self) -> bool:
        return len(self.terms) < MIN_TERMS


def terms(prof: Any, q: str = "", y1: int | None = None, y2: int | None = None,
          *, any_date: bool = False) -> Terms:
    """Ознаки родини під роки справи: прізвище роду й люди з `kin`.

    Вікна років — ті самі, що в каналі імен: ім'я, поки людина жива; по
    батькові — поки живі її діти. Особа без дат вікно не звужує й за
    замовчуванням не йде (`any_date` бере всіх).
    """
    from nyshporka.search import anchors as A
    from nyshporka.search.store import whole_stems

    out: list[Term] = []
    sur: set[str] = set()
    asked = [normalize_archival(w) for w in _TOKEN.findall(q or "")]
    asked = [n for n in asked if len(n) >= MIN_TOK]
    if prof is not None:
        from nyshporka.core.profile import _spellings_norm

        sur |= set(_spellings_norm(prof))
    sur |= set(asked)
    # 🔴 Лише цілі написання. Профіль тримає голови й хвости переносу для
    # синтетики («doli-», «scinskii»); у ключі запису вони збігались із кожним
    # «Долги» й кожним «-щинскій» книги. Той самий відсів, що в сторі.
    sur = set(whole_stems(sorted(sur), keep=asked)[0])
    if sur:
        out.append(Term(label=(getattr(prof, "display", "") or q or "прізвище роду"),
                        kind="surname", keys=tuple(sorted(sur))))
    folk = A.people(prof)
    undated = 0
    seen: set[tuple[str, str]] = set()
    for p in folk:
        if not p.dated:
            undated += 1
            if not any_date:
                continue
        g = norm_given(normalize_archival(p.given)) if p.given else ""
        if len(g) >= MIN_TOK and A._alive(p, y1, y2) and ("given", g) not in seen:
            seen.add(("given", g))
            out.append(Term(label=p.given, kind="given", keys=(g,)))
        pt = norm_patronymic(normalize_archival(p.patronymic)) if p.patronymic else ""
        if len(pt) >= MIN_TOK and A._patr_window(p, y1, y2) and ("patronymic", pt) not in seen:
            seen.add(("patronymic", pt))
            out.append(Term(label=p.patronymic, kind="patronymic", keys=(pt,)))
        sn = normalize_archival(p.surname) if p.surname else ""
        if len(sn) >= MIN_TOK and A._alive(p, y1, y2) and ("surname", sn) not in seen:
            seen.add(("surname", sn))
            out.append(Term(label=p.surname, kind="surname", keys=(sn,)))
    win = (y1, y2) if y1 is not None and y2 is not None else None
    return Terms(terms=tuple(out), people=len(folk), undated=undated, years=win)


# ── збіг токена з ознакою ────────────────────────────────────────────────────
def _forms(raw: str) -> tuple[str, str, str]:
    n = normalize_archival(raw)
    return n, norm_given(n), norm_patronymic(n)


def _surname_score(fuzz: Any, tok: str, key: str) -> float:
    """Прізвище: ціле слово або спільний початок — закінчення відмінюється
    («Огновскій» / «Огновская»), а рушій калічить середину, не початок."""
    best = float(fuzz.ratio(tok, key)) if abs(len(tok) - len(key)) <= 4 else 0.0
    k = min(len(tok), len(key)) - 2
    if k >= 5:
        best = max(best, float(fuzz.ratio(tok[:k], key[:k])) - 5.0)
    return best


def match(fuzz: Any, raw: str, ts: Terms, memo: dict[str, tuple[tuple[int, float], ...]]
          ) -> tuple[tuple[int, float], ...]:
    """Ознаки, яким відповідає токен: ((індекс ознаки, бал), …)."""
    got = memo.get(raw)
    if got is not None:
        return got
    n, g, p = _forms(raw)
    hits: list[tuple[int, float]] = []
    for i, t in enumerate(ts.terms):
        if t.kind == "surname":
            if len(n) < MIN_SURNAME:
                continue
            sc = max(_surname_score(fuzz, n, k) for k in t.keys)
            thr = THR_SURNAME
        elif t.kind == "given":
            sc = max((float(fuzz.ratio(g, k)) for k in t.keys
                      if -GIVEN_SHORT <= len(g) - len(k) <= 4), default=0.0)
            thr = THR_GIVEN
        else:
            # 🔴 По батькові — лише слово У ФОРМІ по батькові («Ивановъ»,
            # «Харитонова», «syn Mitrofana»). Голе ім'я нормалізується однаково
            # обома правилами: «Іоаннъ» і є Іван, але це ім'я сусіда, а не
            # по батькові нашої людини, і воно стоїть у кожному записі.
            if p == g:
                continue
            sc = max((float(fuzz.ratio(p, k)) for k in t.keys
                      if abs(len(p) - len(k)) <= 4), default=0.0)
            thr = THR_PATR
        if sc >= thr:
            hits.append((i, sc))
    got = tuple(hits)
    memo[raw] = got
    return got


# ── сторінки й записи ────────────────────────────────────────────────────────
@dataclass
class Mark:
    """Ознака, знайдена на рядку."""

    term: int
    score: float
    token: str
    run: str
    line_no: int
    line: str
    box: tuple[int, int, int, int] | None


@dataclass
class Page:
    page: str
    marks: list[Mark] = field(default_factory=list)
    heights: list[int] = field(default_factory=list)
    #: (голос, середина рядка або None, скільки в ньому слів)
    lines: list[tuple[str, float | None, int]] = field(default_factory=list)


class Weigh:
    """Вага ознаки в смузі з `n` слів одного голосу: `−ln(1 − (1 − f)^n)`."""

    def __init__(self, freq: dict[int, float]) -> None:
        self.freq = freq

    def __call__(self, term: int, n: float) -> float:
        f = self.freq.get(term, 0.0)
        if f <= 0:
            return 0.0
        chance = 1.0 - (1.0 - f) ** max(n, 1.0)
        return -math.log(chance) if chance > 0 else 0.0


def _words(lines: list[tuple[str, float | None, int]]) -> float:
    """Слів у смузі на ОДИН голос: два голоси читають ті самі слова двічі."""
    per: dict[str, int] = defaultdict(int)
    for run, _y, n in lines:
        per[run] += n
    return sum(per.values()) / max(len(per), 1)


def _bands(pg: Page, weigh: Weigh) -> list[tuple[float, list[Mark], bool]]:
    """Записи сторінки: (бал, ознаки, чи за геометрією), від найсильнішого.

    Жадібно: найважча смуга, її ознаки знімаються, далі наступна — бо на одній
    сторінці буває й два записи родини (народження й хрещення в сусідніх).
    """
    marks = _one_term_per_token(pg.marks, weigh)
    boxed = [m for m in marks if m.box]
    out: list[tuple[float, list[Mark], bool]] = []
    # 🔴 Голос без геометрії (латинський прогін ділить рядки інакше й рамок
    # першого голосу не успадковує) зводиться окремо, по сторінці, і з цією
    # позначкою. Доти його ознаки мовчки випадали зі смуг: польський запис
    # «syn <імені батька>, <прізвище>» польською 1920-х не діставав жодної.
    loose = [m for m in marks if not m.box]
    if loose:
        runs = {m.run for m in loose}
        n = _words([ln for ln in pg.lines if ln[0] in runs and ln[1] is None])
        got = _best_set(loose, weigh, n, need=MIN_TERMS_PAGE)
        if got[0] > 0:
            out.append((got[0], got[1], False))
    if not boxed or not pg.heights:
        return out
    hs = sorted(pg.heights)
    span = BAND * max(hs[len(hs) // 2], 1)
    placed = [(run, y, n) for run, y, n in pg.lines if y is not None]
    left = sorted(boxed, key=lambda m: _top(m))
    while left:
        best: tuple[float, list[Mark]] = (0.0, [])
        for a in left:
            lo, hi = _top(a) - span * 0.15, _top(a) + span
            inside = [m for m in left if lo <= _mid(m) <= hi]
            n = _words([ln for ln in placed if lo <= (ln[1] or 0.0) <= hi])
            got = _best_set(inside, weigh, n)
            if got[0] > best[0]:
                best = got
        if best[0] <= 0:
            break
        out.append((best[0], best[1], True))
        y_lo = min(_top(m) for m in best[1])
        y_hi = max(_bottom(m) for m in best[1])
        left = [m for m in left if not (y_lo <= _mid(m) <= y_hi)]
    return out


def _one_term_per_token(marks: list[Mark], weigh: Weigh) -> list[Mark]:
    """Одне слово — одна ознака. «Митрофаъ» схожий і на ім'я Митрофан, і на
    по батькові Митрофанов; зарахований двічі, він сам собою давав запису дві
    ознаки, тобто «родину» з одного спотвореного слова. Лишається найкращий
    збіг, на рівних — рідша ознака."""
    best: dict[tuple[str, int, str], Mark] = {}
    for m in marks:
        k = (m.run, m.line_no, m.token)
        cur = best.get(k)
        if cur is None or (m.score, -weigh.freq.get(m.term, 1.0)) > (
                cur.score, -weigh.freq.get(cur.term, 1.0)):
            best[k] = m
    keep = set(map(id, best.values()))
    return [m for m in marks if id(m) in keep]


def _top(m: Mark) -> float:
    return float((m.box or (0, 0, 0, 0))[1])


def _bottom(m: Mark) -> float:
    return float((m.box or (0, 0, 0, 0))[3])


def _mid(m: Mark) -> float:
    return (_top(m) + _bottom(m)) / 2


def _best_set(marks: list[Mark], weigh: Weigh, n: float, *,
              need: int = MIN_TERMS) -> tuple[float, list[Mark]]:
    """Кожна ознака — один раз, найкращим збігом; бал — сума ваг у смузі з `n` слів."""
    by: dict[int, Mark] = {}
    for m in marks:
        if m.term not in by or m.score > by[m.term].score:
            by[m.term] = m
    if len(by) < need:
        return 0.0, []
    return (sum(weigh(t, n) for t in by),
            sorted(by.values(), key=lambda m: m.term))


def scan(rows: list[dict[str, Any]], ts: Terms, *, limit: int = 40) -> dict[str, Any]:
    """Записи справи, де зійшлись ознаки родини.

    `rows` — прогони справи (усі голоси). Сторінка — кадр: голоси одного кадру
    зводяться разом, бо кадр той самий і геометрія в нього одна.
    """
    from rapidfuzz import fuzz

    from nyshporka.search import store as ST

    pages: dict[str, Page] = {}
    memo: dict[str, tuple[tuple[int, float], ...]] = {}
    geo: set[str] = set()
    if ts.empty or not ST.exists():
        return {"on": not ts.empty, "hits": [], "total": 0, "pages": 0,
                "terms": [], "common": [], "geo_pages": 0}
    words = 0
    count: dict[int, int] = defaultdict(int)
    line_words: list[int] = []
    conn = ST.connect(readonly=True)
    try:
        for row in rows:
            run = str(row["name"])
            rid = conn.execute("select id from runs where run=?", (run,)).fetchone()
            if not rid:
                continue
            for pid, page in conn.execute(
                    "select id, page from pages where run_id=? order by id", (rid[0],)):
                key = _frame_key(str(page))
                pg = pages.setdefault(key, Page(page=str(page)))
                raw = ST._raw_lines(conn, int(pid))
                boxes = {ln.no: ln.box for ln in ST._page_lines(conn, int(pid))}
                had_geo = False
                for no, text in enumerate(raw, 1):
                    box = boxes.get(no)
                    if box:
                        had_geo = True
                        pg.heights.append(max(1, box[3] - box[1]))
                    toks = [t for t in _TOKEN.findall(text) if len(t) >= MIN_TOK]
                    if not toks:
                        continue
                    mid = (box[1] + box[3]) / 2 if box else None
                    pg.lines.append((run, mid, len(toks)))
                    line_words.append(len(toks))
                    words += len(toks)
                    for tok in toks:
                        for ti, sc in match(fuzz, tok, ts, memo):
                            pg.marks.append(Mark(ti, sc, tok, run, no, text, box))
                            count[ti] += 1
                if had_geo:
                    geo.add(key)
    finally:
        conn.close()
    freq = {i: count.get(i, 0) / max(words, 1) for i in range(len(ts.terms))}
    weigh = Weigh(freq)
    # Смуга «звичайного» розміру — лише щоб назвати людині часті ознаки.
    lw = sorted(line_words)
    typical = BAND * (lw[len(lw) // 2] if lw else 1)
    common = [t.label for i, t in enumerate(ts.terms)
              if count.get(i) and math.exp(-weigh(i, typical)) >= COMMON_CHANCE]
    hits: list[dict[str, Any]] = []
    for pg in pages.values():
        for score, marks, by_geo in _bands(pg, weigh):
            hits.append(_hit(pg, score, marks, by_geo, ts, freq))
    hits.sort(key=lambda h: (-h["score"], h["page"]))
    return {"on": True, "hits": hits[:limit], "total": len(hits), "pages": len(pages),
            "geo_pages": len(geo), "words": words,
            "terms": [{"label": t.label, "kind": t.kind, "found": count.get(i, 0),
                       "per_1000": round(1000 * freq[i], 2),
                       "weight": round(weigh(i, typical), 2)}
                      for i, t in enumerate(ts.terms)],
            "common": common}


def _frame_key(page: str) -> str:
    stem = page.rsplit(".", 1)[0]
    digits = re.findall(r"\d+", stem)
    if not digits:
        return stem.lower()
    return digits[-1].lstrip("0") or "0"


def _hit(pg: Page, score: float, marks: list[Mark], by_geo: bool, ts: Terms,
         freq: dict[int, float]) -> dict[str, Any]:
    first = min(marks, key=lambda m: (_top(m), m.line_no))
    ys = [m.box for m in marks if m.box]
    return {"name": first.run, "page": pg.page, "line_no": first.line_no,
            "line_index": first.line_no - 1, "channel": "record",
            "score": round(score, 2), "by_geometry": by_geo,
            "band": ([min(b[1] for b in ys), max(b[3] for b in ys)] if ys else None),
            "marks": [{"term": ts.terms[m.term].label, "kind": ts.terms[m.term].kind,
                       "token": m.token, "score": round(m.score, 1),
                       "per_1000": round(1000 * freq.get(m.term, 0.0), 2),
                       "run": m.run, "line_no": m.line_no, "line": m.line}
                      for m in marks]}
