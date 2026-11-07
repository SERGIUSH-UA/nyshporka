"""📇 Перелік осіб сторінки — поіменний індекс як підказка арбітрам і ворота злиття.

Поіменний індекс (FamilySearch, Geneteka, власний покажчик архіву) каже, ХТО
записаний на кадрі й скільки йому років, але не як це написано: індексатори
нормалізують правопис, відкидають ъ, пишуть ѳ як «фт» чи «ф», прізвище ставлять
лише голові двору. Тож це не голос і не мітка, а третє незалежне спостереження —
як двійник ревізії (`train/twin.py`), лише без рамок: місце особи на аркуші треба
знайти самим.

Як знаходиться:
1. голови дворів (є прізвище) — до рядка, де голоси найближчі до імені й прізвища;
2. решта двору — лише в блоці свого двору: від рядка голови до рядка наступного
   голови. «Марія» стоїть у кожному третьому дворі, і поза блоком вона липла б
   куди завгодно;
3. вік — до вузької смужки праворуч від рядка імені на тій самій висоті: певна
   прив'язка — коли хоч один голос читає саме цей вік, інакше найближча за
   висотою з позначкою сумніву. Заміри на пілоті (6 сторінок): імена — 183 з 184
   прив'язок збіглися зі злиттям арбітрів; вік — певні 15 з 16, непевні 16 з 26.
   Тому ворота за віком діють лише на певних прив'язках.

Що дає арбітрові: рядок «ІНДЕКС: Симеон Леонтиев Крига (глава) 40» біля рядка
імені й «ІНДЕКС: вік 40 — Симеон Леонтиев Крига» біля смужки віку, плюс увесь
перелік сторінки по дворах.

Що дає воротам (лише на сторінках, де знайдено досить осіб, `PAGE_MIN_MATCHED`):
власна назва мітки, якої в індексі сторінки немає навіть віддалено, → `low`
(рядки з назвою церкви чи села не судяться: таких назв індекс не має); вік, що
розходиться з певно прив'язаним віком індексу й не має жодного голосу на
підтвердження, → `low`.

Пілот: сповідки ЦДІАК ф.127 з індексом FamilySearch, 6 рук, 07.11.2026 —
злиття впізнає на 10–60 % більше імен з індексу, ніж найкращий голос; індекс
помиляється сам (вік трьох синів, літера прізвища, пропущені родини), тому він
не суддя тексту, а опора для вибору між голосами.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nyshporka.train import twin as TW

ROSTER_LINE_ID = "roster"
ROSTER_PAGE_ID = "roster_page"
LINE_FILE = "hints/roster_line.json"
PAGE_FILE = "hints/roster_page.json"
STATE_FILE = "hints/roster.json"

#: Рядок імені — рамка не вужча за це (графи віку й лічильників — вузькі).
NAME_MIN_W = 0.04
#: Смужка віку — вужча за це.
AGE_MAX_W = 0.06
#: Наскільки далеко праворуч від рядка імені може стояти графа віку.
AGE_MAX_DX = 0.15
#: Центр смужки віку — не далі за стільки висот рядка імені від його центру.
AGE_MAX_DY = 0.6
#: Поріг збігу голови двору (ім'я + прізвище/по батькові) з рядком.
HEAD_MIN = 0.72
#: Поріг для решти двору — у блоці свого двору.
MEMBER_MIN = 0.78
#: Поріг для особи, чий голова не знайдений: блоку немає, тож вимога вища.
LOOSE_MIN = 0.86
#: Від цієї схожості пара певна, нижче — з позначкою сумніву.
SURE = 0.86
#: Ворота діють на сторінці, де знайдено щонайменше стільки осіб…
PAGE_MIN_MATCHED = 5
#: …і вони становлять хоч таку частку рядків імені обраної частини сторінки.
PAGE_MIN_SHARE = 0.25

HEAD_RELS = {"глава", "head", "голова", "голова двору", "глава семьи"}

HOW = ("перелік осіб, яких поіменний індекс знайшов на цьому кадрі (якщо кадр — розворот, "
       "то на обох сторінках), по дворах: ім'я, по батькові, прізвище голови, стосунок, вік. "
       "Каже ХТО стоїть у рядку і скільки йому років; літери мітки — лише з голосів і кропа")
CAVEATS = (
    "правопис індексу не джерельний: кінцевий ъ відкинуто, «и» замість «і», ѣ → е; ѳ буває "
    "записано як «фт» (Фтома = Ѳома), буває як «ф» — форму з індексу в мітку не переносити; "
    "але «фт» буває й у самому джерелі (писар пише «Фтеодосія») — вирішує кроп",
    "прізвище й по батькові здебільшого лише в голови двору; «двір N» — номер в індексі, не "
    "обов'язково лічильник на аркуші; порядок індексу — не порядок аркуша",
    "рядок і вік прив'язано автоматично; ⚠ — прив'язка непевна, особа може стояти сусіднім рядком",
    "індекс буває неповним і помиляється сам (вік, літера прізвища): він не суддя — вирішує кроп",
)

#: Лексика сповідних розписів і метрик, яку пишуть з великої, а ім'ям вона не є.
CONFESSION_FORMS = (
    "посполитые", "посполитіе", "посполиті", "поселяне", "поселяни", "домашніе", "домашние",
    "домашній", "дѣти", "дети", "сынъ", "сыновья", "дочь", "дочери", "жена", "жены", "вдова",
    "вдовецъ", "мать", "матерь", "братъ", "сестра", "внукъ", "внука", "внучка", "внуки", "зять",
    "невѣстка", "невестка", "сноха", "племянникъ", "племянница", "пасынокъ", "падчерица",
    "работникъ", "работница", "работники", "питомецъ", "питомица", "приймакъ", "сирота",
    "женатъ", "холостъ", "пришлецъ", "бобыль", "бобыли", "число", "людей", "дворовъ", "лѣта",
    "лѣтъ", "мужеска", "женска", "пола", "показаніе", "показанія", "дѣйства", "дѣйствія",
    "исповѣди", "исповѣдь", "причастія", "причастились", "были", "били", "небыли",
    "малолѣтства", "малолѣтствомъ", "причтъ", "священникъ", "священническая", "діаконъ",
    "дьяконъ", "дьячокъ", "пономарь", "пономарская", "псаломщикъ", "псаломщицкая",
    "псаломщицкій", "просфорня", "протоіерей", "протоіерейская", "церкви", "церковь", "села",
    "деревни", "прихода", "приходъ", "мѣщане", "купцы", "однодворцы", "крестьяне", "дворяне",
    "духовные", "военные", "чиновники", "отставные", "солдаты", "солдатка", "званіе", "имя",
    "отчество", "фамилія", "старообрядцы", "дворовые", "дворовый", "его", "ея", "ее", "ихъ",
    "рожденія", "которые", "которыя", "кто", "токмо", "винословія", "какимъ", "почему",
    "служитель", "служители", "служителка", "служительница", "служителей", "душей", "душъ",
    "дьячиха", "пономариха", "просвирня", "попадья", "попадія",
)
_CONF_KEYS = frozenset(TW.key(w) for w in CONFESSION_FORMS)
#: Рядок із назвою церкви, села, округи — назви, яких індекс осіб не має.
_PLACE_MARK = re.compile(r"причт|церк|села\b|сел[оа]\s|деревн|прихода|мѣстечк|мѣста\b|уѣзд|"
                         r"повѣт|губерн|благочин|округ", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


class RosterError(ValueError):
    """Немає переліку, сторінок або рамок."""


# ── особи ────────────────────────────────────────────────────────────────────
@dataclass
class Person:
    name: str = ""
    given: str = ""
    patronymic: str = ""
    surname: str = ""
    relation: str = ""
    age: str = ""
    household: str = ""

    @property
    def full(self) -> str:
        if self.name.strip():
            return self.name.strip()
        return " ".join(x for x in (self.given, self.patronymic, self.surname) if x).strip()

    @property
    def is_head(self) -> bool:
        return self.relation.strip().lower() in HEAD_RELS or bool(self.surname.strip())

    def tokens(self) -> list[tuple[str, float]]:
        """Ключі слів імені з вагою: прізвище важить більше, по батькові — менше."""
        out: list[tuple[str, float]] = []
        if self.given or self.patronymic or self.surname:
            for part, wt in ((self.given, 1.0), (self.patronymic, 0.7), (self.surname, 1.3)):
                out += [(k, wt) for k in TW.key(part).split() if len(k) >= 3]
        if not out:
            out = [(k, 1.0) for k in TW.key(self.name).split() if len(k) >= 3]
        return out

    def label(self) -> str:
        s = self.full or "?"
        if self.relation:
            s += f" ({self.relation.lower()})"
        if self.age:
            s += f" {self.age}"
        return s

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.__dict__.items() if v}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Person:
        v = {k: str(d.get(k) or "").strip() for k in
             ("name", "given", "patronymic", "surname", "relation", "age", "household")}
        # Вік у переліку — число (40), рядок «40», «40.0» з таблиці чи «3 мес»: порівнюють
        # його з цифрами голосу, тож лишається перша група цифр, як вона стоїть у рядку.
        m = _DIGITS.search(v["age"])
        v["age"] = m.group(0) if m else ""
        return cls(**v)


def load(path: Path) -> tuple[dict[str, Any], dict[str, list[Person]]]:
    """Файл переліку: `{"source": {...}, "pages": {сторінка: [особа, …]}}`."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RosterError(f"перелік {path}: {exc}") from exc
    return load_dict(d, where=str(path))


def load_dict(d: Any, *, where: str = "перелік") -> tuple[dict[str, Any], dict[str, list[Person]]]:
    """Те саме, що `load`, з уже розібраного об'єкта."""
    if not isinstance(d, dict) or not isinstance(d.get("pages"), dict):
        raise RosterError(f"{where}: потрібен об'єкт з полем «pages»")
    pages = {str(pg): [Person.from_dict(x) for x in v if isinstance(x, dict)]
             for pg, v in d["pages"].items() if isinstance(v, list)}
    return dict(d.get("source") or {}), pages


def page_text(people: list[Person]) -> str:
    """Перелік сторінки по дворах — для арбітра й для воріт."""
    groups: dict[str, list[Person]] = {}
    for p in people:
        groups.setdefault(p.household or "?", []).append(p)

    def order(k: str) -> tuple[int, int, str]:
        return (0, int(k), "") if k.isdigit() else (1, 0, k)

    parts = []
    for k in sorted(groups, key=order):
        ps = sorted(groups[k], key=lambda p: 0 if p.is_head else 1)
        head = f"двір {k}" if k.isdigit() else (k if k != "?" else "без двору")
        parts.append(f"{head}: " + "; ".join(p.label() for p in ps))
    return " | ".join(parts)


# ── рядки сторінки ───────────────────────────────────────────────────────────
def _box(b: Any) -> tuple[int, int, int, int] | None:
    if not b:
        return None
    if isinstance(b[0], (list, tuple)):
        xs, ys = [int(p[0]) for p in b], [int(p[1]) for p in b]
        return min(xs), min(ys), max(xs), max(ys)
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def score(p: Person, texts: list[str]) -> float:
    """Схожість особи з рядком: зважене середнє найкращих збігів слів імені, найкращий голос."""
    toks = p.tokens()
    if not toks:
        return 0.0
    best = 0.0
    for t in texts:
        words = [w for w in TW.key(t).split() if len(w) >= 3]
        if not words:
            continue
        tot = sum(wt * max(TW.sim(k, w) for w in words) for k, wt in toks)
        best = max(best, tot / sum(wt for _, wt in toks))
    return best


@dataclass
class PageMatch:
    page: str
    persons: int = 0
    name_lines: int = 0
    names: dict[int, tuple[int, float]] = field(default_factory=dict)   # рядок → (особа, схожість)
    ages: dict[int, int] = field(default_factory=dict)                  # рядок → особа
    #: Смужки віку, де хоч один голос читає саме вік індексу: прив'язка певна.
    ages_sure: set[int] = field(default_factory=set)

    @property
    def matched(self) -> int:
        return len(self.names)

    @property
    def reliable(self) -> bool:
        return (self.matched >= PAGE_MIN_MATCHED
                and self.matched >= PAGE_MIN_SHARE * max(1, self.name_lines))


def match_page(page: str, people: list[Person], boxes: list[Any], width: int,
               voices: list[list[str]], own: set[int] | None = None) -> PageMatch:
    """Прив'язати осіб переліку до рядків імені й смужок віку однієї сторінки."""
    pm = PageMatch(page=page, persons=len(people))
    geo = {i: _box(b) for i, b in enumerate(boxes)}

    def texts(i: int) -> list[str]:
        return [v[i] for v in voices if i < len(v) and v[i].strip()]

    cand = [i for i, bx in geo.items() if bx and (own is None or i in own)
            and (bx[2] - bx[0]) >= NAME_MIN_W * width
            and any(len(TW.key(t).replace(" ", "")) >= 3 for t in texts(i))]
    pm.name_lines = len(cand)
    sc: dict[tuple[int, int], float] = {}
    for pi, p in enumerate(people):
        for i in cand:
            s = score(p, texts(i))
            if s >= min(HEAD_MIN, MEMBER_MIN):
                sc[(pi, i)] = s
    used_p: set[int] = set()
    used_l: set[int] = set()

    def take(pi: int, i: int, s: float) -> None:
        pm.names[i] = (pi, s)
        used_p.add(pi)
        used_l.add(i)

    # 1. Голови дворів.
    heads = [pi for pi, p in enumerate(people) if p.is_head and len(p.tokens()) >= 2]
    for (pi, i), s in sorted(sc.items(), key=lambda kv: -kv[1]):
        if pi in heads and pi not in used_p and i not in used_l and s >= HEAD_MIN:
            take(pi, i, s)
    # 2. Блоки дворів: від рядка голови до рядка наступного знайденого голови.
    top = {pi: bx[1] for i, (pi, _) in pm.names.items() if (bx := geo[i]) is not None}
    starts = sorted(top.values())
    block: dict[str, tuple[int, int]] = {}
    for pi, y in top.items():
        nxt = next((y2 for y2 in starts if y2 > y), 10 ** 9)
        hh = people[pi].household or f"#{pi}"
        block[hh] = (y - 5, nxt - 5)
    for (pi, i), s in sorted(sc.items(), key=lambda kv: -kv[1]):
        if pi in used_p or i in used_l:
            continue
        p = people[pi]
        b = block.get(p.household) if p.household else None
        bx = geo[i]
        if b is not None and bx is not None:
            if b[0] <= bx[1] < b[1] and s >= MEMBER_MIN:
                take(pi, i, s)
        elif s >= LOOSE_MIN:
            # Без блоку — лише певна й однозначна пара: друга найкраща пара для
            # цієї особи помітно слабша.
            alt = max((s2 for (pj, j), s2 in sc.items() if pj == pi and j != i
                       and j not in used_l), default=0.0)
            if s - alt >= 0.08:
                take(pi, i, s)
    # 3. Вік: вузька смужка праворуч на висоті рядка імені. Певна — коли хоч
    # один голос читає саме цей вік; інакше найближча за висотою, з сумнівом.
    narrow = [j for j, bx in geo.items() if bx and (own is None or j in own) and j not in pm.names
              and (bx[2] - bx[0]) < AGE_MAX_W * width and texts(j)
              and not any(len(_LETTERS.findall(t)) >= 3 and not _DIGITS.search(t)
                          for t in texts(j))]
    for i, (pi, _s) in sorted(pm.names.items(), key=lambda kv: -kv[1][1]):
        age = people[pi].age.strip()
        bx = geo[i]
        if not age or bx is None:
            continue
        h = max(1, bx[3] - bx[1])
        y0 = (bx[1] + bx[3]) / 2
        cands: list[tuple[bool, float, int]] = []    # (голос читає вік, відстань по y, рядок)
        for j in narrow:
            if j in pm.ages:
                continue
            bj = geo[j]
            if bj is None:
                continue
            yc = (bj[1] + bj[3]) / 2
            if abs(yc - y0) > AGE_MAX_DY * h:
                continue
            dx = bj[0] - bx[2]
            if dx < -0.01 * width or dx > AGE_MAX_DX * width:
                continue
            reads = any(_DIGITS.findall(t)[:1] == [age] for t in texts(j))
            cands.append((reads, abs(yc - y0), j))
        if not cands:
            continue
        sure = [c for c in cands if c[0]]
        pick = min(sure or cands, key=lambda c: c[1])
        pm.ages[pick[2]] = pi
        if pick[0]:
            pm.ages_sure.add(pick[2])
    return pm


# ── набір ────────────────────────────────────────────────────────────────────
@dataclass
class RosterReport:
    set: str
    pages: list[PageMatch] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"set": self.set, "pages": len(self.pages),
                "persons": sum(p.persons for p in self.pages),
                "matched": sum(p.matched for p in self.pages),
                "ages": sum(len(p.ages) for p in self.pages),
                "reliable": sum(1 for p in self.pages if p.reliable),
                "missing": self.missing}


def build(name: str, file: Path, *, dry_run: bool = False, ws: Any = None) -> RosterReport:
    """Прив'язати перелік осіб до сторінок набору й записати джерело підказок."""
    from nyshporka.core.workspace import workspace
    from nyshporka.train import cut as C
    from nyshporka.train import sets as S
    from nyshporka.utils.atomic import write_json

    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    if not spec.source_run:
        raise RosterError(f"набір «{name}» нарізаний не з прогону — рамок для прив'язки немає")
    source, pages = load(file)
    have = reg.crop_pages(spec)
    voices = spec.voices()
    own = spec.own_lines()
    rep = RosterReport(set=name)
    line_hints: dict[str, dict[str, str]] = {}
    page_hints: dict[str, dict[str, str]] = {}
    state_pages: dict[str, Any] = {}
    for pg, people in sorted(pages.items()):
        if pg not in have:
            rep.missing.append(pg)
            continue
        if not people:
            continue
        geo = C.page_geometry(spec.source_run, pg, w)
        if geo is None:
            rep.missing.append(pg)
            rep.warnings.append(f"{pg}: прогін не зберіг рамок — перелік лише сторінкою")
            page_hints[pg] = {"text": page_text(people)}
            continue
        vl = [reg.draft_lines(spec, d, pg) or [] for d in voices]
        pm = match_page(pg, people, geo.get("boxes") or [], int(geo["size"][0]), vl, own.get(pg))
        rep.pages.append(pm)
        for i, (pi, s) in pm.names.items():
            v = {"text": people[pi].label()}
            if s < SURE:
                v["doubt"] = f"прив'язка непевна (схожість {s:.2f})"
            line_hints[f"{pg}:{i}"] = v
        for j, pi in pm.ages.items():
            if j in pm.ages_sure:
                line_hints[f"{pg}:{j}"] = {"text": f"вік {people[pi].age} — {people[pi].full}"}
            else:
                # Без голосу прив'язка віку частіше хибна, ніж ні (хвиля fsi 07.11:
                # арбітри знаходили чужий вік на 8 з 11 таких смужок), тож числа тут
                # не показуємо — лише що це графа віку; віки двору є в ІНДЕКС-СТОР.
                line_hints[f"{pg}:{j}"] = {
                    "text": "графа віку (особу певно не прив'язано) — число лише з кропа",
                    "doubt": "віки двору — у переліку кадру"}
        page_hints[pg] = {"text": page_text(people)}
        state_pages[pg] = {"persons": [p.as_dict() for p in people],
                           "names": {str(i): pi for i, (pi, _) in sorted(pm.names.items())},
                           "ages": {str(j): pi for j, pi in sorted(pm.ages.items())},
                           "ages_sure": sorted(pm.ages_sure),
                           "name_lines": pm.name_lines, "reliable": pm.reliable}
        if not pm.reliable:
            rep.warnings.append(f"{pg}: знайдено {pm.matched} з {pm.persons} осіб — ворота "
                                f"на сторінці не діятимуть")
    if dry_run:
        return rep
    d = reg.set_dir(name)
    (d / "hints").mkdir(parents=True, exist_ok=True)
    write_json(d / LINE_FILE, line_hints)
    write_json(d / PAGE_FILE, page_hints)
    write_json(d / STATE_FILE, {"source": source, "file": str(file), "pages": state_pages})
    title = str(source.get("title") or "поіменний індекс")
    by = str(source.get("by") or "індексатори")
    caveats = [*CAVEATS, *[str(c) for c in source.get("caveats") or []]]
    keep = [h for h in spec.hint_sources if h.id not in (ROSTER_LINE_ID, ROSTER_PAGE_ID)]
    spec.hint_sources = [
        *keep,
        S.HintSource(id=ROSTER_LINE_ID, kind="normalized", level="line", label="ІНДЕКС",
                     title=f"особа цього рядка за індексом ({title})", by=by, trust="single",
                     how=str(source.get("how") or HOW), caveats=caveats, file=LINE_FILE),
        S.HintSource(id=ROSTER_PAGE_ID, kind="normalized", level="page", label="ІНДЕКС-СТОР",
                     title=f"усі особи кадру за індексом ({title})", by=by, trust="single",
                     how="перелік осіб кадру по дворах — для контексту, коли рядок не "
                         "прив'язано", file=PAGE_FILE),
    ]
    reg.save(spec)
    return rep


# ── ворота ───────────────────────────────────────────────────────────────────
def state(reg: Any, spec: Any) -> dict[str, Any]:
    from nyshporka.utils.atomic import read_json

    got = read_json(reg.set_dir(spec.name) / STATE_FILE, default=None)
    return got if isinstance(got, dict) else {}


def _page(st: dict[str, Any], page: str) -> dict[str, Any]:
    return ((st.get("pages") or {}).get(page) or {}) if st else {}


#: Формули двійника, розпису й канцелярії разом — ключами `twin.key`.
_ALL_FORMS = _CONF_KEYS | TW._FORM_KEYS | TW._OFFICE_KEYS
#: Нечіткий збіг з формулою — лише з довгою формулою й лише від цієї схожості.
#: 🔴 Правило двійника (≥0,8 з формулою від 4 літер) ковтає «Марія» через «мая»
#: (місяць у датах ревізії): для воріт за індексом це вимкнуло б найчастіше ім'я.
FORM_FUZZY = 0.85
FORM_FUZZY_MIN_LEN = 5


def is_form(word: str) -> bool:
    """Слово — формула розпису чи ревізії, а не ім'я."""
    k = TW.key(word)
    if not k:
        return True
    if k in _ALL_FORMS:
        return True
    low = word.lower().rstrip("ъь")
    if len(word) >= 7 and TW._PARTICIPLE.search(low):
        return True
    # Обрізана на краю смужки формула: «Посполи-», «Причас-», «Губерн-».
    if len(k) >= 4 and any(f.startswith(k) and len(f) > len(k) for f in _ALL_FORMS):
        return True
    return any(TW.sim(k, f) >= FORM_FUZZY for f in _ALL_FORMS if len(f) >= FORM_FUZZY_MIN_LEN)


def name_words(text: str) -> list[str]:
    """Власні назви мітки: з великої літери, ≥`twin.NAME_MIN_LEN` літер, не формула."""
    return [w for w in TW._WORD.findall(text)
            if len(w) >= TW.NAME_MIN_LEN and w[0].isupper() and not is_form(w)]


def _people(pg: dict[str, Any]) -> list[Person]:
    return [Person.from_dict(x) for x in pg.get("persons") or [] if isinstance(x, dict)]


def gate_text(st: dict[str, Any], page: str) -> str:
    """Усі імена сторінки — для воріт; порожньо, якщо прив'язка ненадійна."""
    pg = _page(st, page)
    if not pg.get("reliable"):
        return ""
    return " ".join(p.full for p in _people(pg))


def line_entries(st: dict[str, Any], page: str) -> dict[int, tuple[str, Person, str]]:
    """{рядок: ("name" | "age" | "age?", особа, імена її двору)}; «age?» — вік без голосу.

    Імена двору — бо рядок імені називає й інших: «Жена Григорія Уліяна» — це
    Уліяна, а Григорій — голова її двору.
    """
    pg = _page(st, page)
    people = _people(pg)
    sure = {int(x) for x in pg.get("ages_sure") or [] if str(x).isdigit()}
    hh: dict[str, list[str]] = {}
    for p in people:
        hh.setdefault(p.household, []).append(p.full)
    out: dict[int, tuple[str, Person, str]] = {}
    for kind in ("names", "ages"):
        for i, pi in (pg.get(kind) or {}).items():
            if not (str(i).isdigit() and isinstance(pi, int) and 0 <= pi < len(people)):
                continue
            if kind == "ages" and int(i) in out:
                continue                      # ім'я на цьому рядку важливіше за вік
            k = "name" if kind == "names" else ("age" if int(i) in sure else "age?")
            p = people[pi]
            out[int(i)] = (k, p, " ".join(hh.get(p.household, []) if p.household else []))
    return out


def grounds(text: str, kind: str, p: Person, household: str = "") -> bool:
    """Мітка спирається на особу індексу: той самий вік або всі власні назви — її двору."""
    if kind in ("age", "age?"):
        d = _DIGITS.findall(text)
        return bool(d) and bool(p.age) and d[0] == p.age.strip()
    words = name_words(text)
    names = f"{p.full} {household}"
    return bool(words) and all(TW.support(w, names) >= TW.NAME_MIN for w in words)


def gate_page(st: dict[str, Any], page: str, merged: list[str], conf: dict[int, str],
              touched: set[int], voices: list[list[str]],
              own: set[int] | None = None) -> list[str]:
    """Пониження за індексом. ПРАВИТЬ `conf` на місці; повертає «сторінка:рядок причина»."""
    text = gate_text(st, page)
    if not text:
        return []
    entries = line_entries(st, page)
    out: list[str] = []
    for i in sorted(touched):
        if own is not None and i not in own:
            continue
        if conf.get(i) == "low" or i >= len(merged) or not merged[i].strip():
            continue
        m = merged[i]
        kind_p = entries.get(i)
        if kind_p is not None and kind_p[0] == "age?":
            continue                        # прив'язка без голосу — не суддя
        if kind_p is not None and kind_p[0] == "age":
            p = kind_p[1]
            d = _DIGITS.findall(m)
            vs = [v[i] if i < len(v) else "" for v in voices]
            if d and p.age and d[0] != p.age.strip() and not any(
                    _DIGITS.findall(x)[:1] == d[:1] for x in vs if x):
                conf[i] = "low"
                out.append(f"{page}:{i} вік «{d[0]}» ≠ індекс {p.age}, голоси теж ні")
            continue
        if _PLACE_MARK.search(m):
            continue
        bad = [w for w in name_words(m) if TW.support(w, text) < TW.NAME_MIN]
        if bad:
            conf[i] = "low"
            out.append(f"{page}:{i} «{', '.join(bad[:3])}» немає в індексі")
    return out


__all__ = [
    "CAVEATS",
    "CONFESSION_FORMS",
    "HOW",
    "LINE_FILE",
    "PAGE_FILE",
    "ROSTER_LINE_ID",
    "ROSTER_PAGE_ID",
    "STATE_FILE",
    "PageMatch",
    "Person",
    "RosterError",
    "RosterReport",
    "build",
    "gate_page",
    "gate_text",
    "grounds",
    "is_form",
    "line_entries",
    "load",
    "load_dict",
    "match_page",
    "name_words",
    "page_text",
    "score",
    "state",
]
