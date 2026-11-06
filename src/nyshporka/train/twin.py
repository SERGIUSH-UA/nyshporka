"""🪞 Двійник рядка — той самий запис іншим письмом.

Ревізькі казки 1795 року з земель, щойно відібраних у Речі Посполитої, писали
кожен двір двічі: кирилицею і польською латинкою. Розкладів два:

- `spread` — розворот на одному кадрі: ліва половина одним письмом, права
  іншим (друкований двомовний бланк);
- `pages` — письмо чергується через аркуш: кириличний кадр, поруч польський.

Друга половина — НЕЗАЛЕЖНЕ читання тих самих імен: інше письмо, інша модель,
отже інші помилки. Згода голосів однієї абетки на рукописі XVIII ст. нічого не
доводить — моделі, учені на схожому матеріалі, помиляються однаково («тарита»
замість «Мария» в обох голосах). Помилка латинської моделі на «Marya» з
кириличними голосами не корелює.

Що двійник дає арбітрові: ХТО стоїть у рядку, а не як це написано. Польська
половина пише народні форми (Hnat, Paraska, Samko), кирилична здебільшого
церковні (Игнатъ, Параскевія, Самеонъ), тож літери мітки — тільки з кропа.

Що двійник дає воротам: власна назва в мітці, якої в двійнику немає навіть
віддалено, вигадана або чужа, і такий рядок іде в `low`.

Пари будуються без зображень: рамки рядків прогону дають половини кадру,
словник формул (жена/Zona, сынъ/Syn, дочь/Córka) — письмо половини, а
вирівнювання послідовностей за нормалізованим ключем — пару рядків.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

LAYOUTS = ("auto", "spread", "pages")
SCRIPTS = ("cyrillic", "latin")

#: Рядок ширший за цю частку кадру — рядок тексту запису, а не графа віку,
#: номер чи шапка колонки (на ревізіях графи 0.01–0.07, записи 0.12–0.40).
MAIN_MIN_W = 0.08
#: Нижче цієї схожості пара рядків не утворюється: так схожі між собою дві
#: різні формули («Сынъ Иванъ» / «Syn Maxym»).
PAIR_FLOOR = 0.35
#: Від цієї схожості пара певна; між FLOOR і цим порогом — пара з сумнівом.
PAIR_SURE = 0.50
#: Ворота: власна назва, найближча до якої в двійнику слабша за цей поріг, —
#: без опори. Калібровано на ревізії 1795 (ДАВіО 635-1-11, ЦДІАК 127-1076-207б).
NAME_MIN = 0.60
#: Частка рядків свого письма, що знайшли пару, нижче якої двійник сторінки не
#: вважається надійним і ворота на ній не діють.
PAGE_PAIRED_MIN = 0.30
#: Мітка, схожа на певну пару двійника не менше за цей поріг, спирається на неї
#: (на tw-207b: «ынъ Ризакъ» / «syn Ryzan» 0.67, «Ефросиния» / «frosyuya» 0.78;
#: різні формули між собою — до 0.5).
GROUND_MIN = 0.60

_CYR = {"а": "a", "б": "b", "в": "w", "г": "h", "ґ": "h", "д": "d", "е": "e", "є": "e",
        "ѣ": "e", "э": "e", "ё": "e", "ж": "z", "з": "z", "и": "i", "і": "i", "ї": "i",
        "й": "i", "ы": "i", "ѵ": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "ѡ": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ў": "u", "ф": "f",
        "ѳ": "f", "х": "h", "ц": "c", "ч": "c", "ш": "s", "щ": "s", "ъ": "", "ь": "",
        "ю": "iu", "я": "ia", "ѧ": "ia", "ꙗ": "ia", "ѯ": "ks", "ѱ": "ps", "ꙋ": "u"}
_LAT_DIGRAPHS = (("sz", "s"), ("cz", "c"), ("rz", "z"), ("ch", "h"), ("dz", "dz"))
_LAT = {"ł": "l", "ż": "z", "ź": "z", "ś": "s", "ć": "c", "ń": "n", "ó": "o", "ą": "a",
        "ę": "e", "y": "i", "j": "i", "v": "w", "g": "h", "x": "ks", "q": "k"}

#: Формули ревізької казки — по одному слову, як їх пише кожне письмо.
CYR_FORMS = ("жена", "жона", "его", "ево", "ихъ", "нихъ", "него", "сынъ", "сыновья", "сыны",
             "дочь", "дочери", "дочка", "дѣти", "дети", "вдова", "вдовецъ", "дворъ",
             "холостъ", "лѣта", "лѣтъ", "хлѣбопашецъ", "мужеска", "женска", "пола", "итого",
             "зять", "братъ", "мать", "внукъ", "внука", "пасынокъ", "падчерица", "работникъ",
             "село", "села", "уѣзда", "церкви", "священникъ", "дьячокъ", "пономарь",
             "служители", "жители", "домъ")
LAT_FORMS = ("zona", "żona", "iego", "jego", "ich", "nich", "niego", "syn", "synowie",
             "corka", "córka", "corki", "córki", "dzieci", "wdowa", "wdowiec", "chałupa",
             "chalupa", "dom", "kawaler", "lata", "rolnik", "męskiey", "meskiey", "niewieściey",
             "płci", "plci", "zięć", "ziec", "brat", "matka", "wnuk", "wnuczka", "pasierb",
             "parobek", "wsi", "wieś", "powiatu", "cerkwi", "kapłan", "dziak", "dziaczok",
             "poddani", "kmiecie")

#: Народна й церковна форма того самого імені — ключі `key()`. Двійник пише
#: «Hnat» там, де кириличний рядок пише «Игнатъ»; без цього ворота понижували б
#: правильне церковне ім'я як «без опори».
NAME_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ignat", "ignatii", "hnat", "ihnat", "ihnatii"),
    ("paraskewia", "paraskewa", "paraska", "praskowia", "praska", "parasia"),
    ("semen", "simeon", "sameon", "semion", "samko", "semko", "senko"),
    ("ilia", "ilko", "ilia", "ilias"),
    ("odaria", "odarka", "darka", "daria"),
    ("ewdokia", "ewdocha", "ieudocha", "iewdocha", "dokia", "dunia", "docka"),
    ("agafia", "ahafia", "hafia", "hapka", "gapka", "agata"),
    ("onisim", "onisko", "onisk", "onisii"),
    ("ioan", "ioann", "iwan", "iwanko", "iwas"),
    ("feodor", "fedor", "fedir", "tedor", "hwedor", "fedko"),
    ("fekla", "tekla", "teska", "teklia"),
    ("mihail", "mihailo", "mihaio", "mihalko", "misko"),
    ("grigorii", "hrihorii", "hrehorii", "hrehor", "hrico", "gzegoz", "hrihor"),
    ("georgii", "iurii", "iurko", "iuri", "iuras"),
    ("stefan", "stepan", "stec", "stepko"),
    ("wasilii", "wasil", "wasko", "wasilko"),
    ("foma", "homa", "tomas", "toma"),
    ("efrosinia", "ewfrosinia", "prosia", "fruzina", "proska", "frosina"),
    ("pelageia", "pelagia", "palaska", "pelaha", "palazka"),
    ("anna", "hanna", "hanka", "anka", "hania"),
    ("ksenia", "oksana", "ksenka", "oksenia"),
    ("timofei", "timko", "timos", "timofii", "timis"),
    ("matfei", "matwii", "matwiei", "matwei", "matwi"),
    ("iakow", "iakub", "iakiw", "iacko"),
    ("iosif", "osip", "iosip", "iosko"),
    ("dimitrii", "dmitro", "dmitri", "demko", "dmitrik"),
    ("andrei", "andrii", "andzei", "andruh", "andrus"),
    ("pawel", "pawlo", "pawlik", "pawlo"),
    ("petr", "petro", "petrus", "petrik"),
    ("kirill", "kirilo", "kiril", "kirik"),
    ("aleksii", "oleksa", "oleksii", "aleksei", "oleks"),
    ("maksim", "maksim", "maksimko"),
    ("nikolai", "mikola", "mikolai", "nikola", "mikolaiko"),
    ("ewfimii", "ewtim", "iuhim", "ohim", "iuchim"),
    ("antonii", "anton", "antos", "antosko"),
    ("pantelimon", "pantelei", "pantelii", "pantko"),
    ("mariia", "maria", "marina", "marusia", "marusa"),
    ("ewgenia", "iewhenia", "ewhenia", "ieuhenia"),
    ("tatiana", "tetiana", "tatiania", "tetiania"),
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


# ── ключ ─────────────────────────────────────────────────────────────────────
def key(text: str) -> str:
    """Грубий спільний ключ кирилиці й польської латинки.

    Не транслітерація для людини, а простір, де «Ѳеодоръ Полищукъ» і «Fedor
    Poliszczuk» стоять поруч: `fedor polisuk` / `fedor polisuk`.
    """
    s = text.lower()
    for a, b in _LAT_DIGRAPHS:
        s = s.replace(a, b)
    out: list[str] = []
    for ch in s:
        if ch in _CYR:
            out.append(_CYR[ch])
        elif ch in _LAT:
            out.append(_LAT[ch])
        elif "a" <= ch <= "z":
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def sim(a: str, b: str) -> float:
    """Схожість двох ключів, 0..1."""
    if not a or not b:
        return 0.0
    return float(fuzz.ratio(a, b)) / 100.0


_CYR_FORM_KEYS = frozenset(key(w) for w in CYR_FORMS)
_LAT_FORM_KEYS = frozenset(key(w) for w in LAT_FORMS)
_FORM_KEYS = _CYR_FORM_KEYS | _LAT_FORM_KEYS
_CYR_FORMS_RAW = frozenset(CYR_FORMS)
_LAT_FORMS_RAW = frozenset(w.lower() for w in LAT_FORMS)


def is_form(word: str) -> bool:
    """Слово — формула казки (жена, сынъ, Zona, Córka), а не ім'я.

    Рядок — смужка, тож формула буває обрізаною: друкована шапка графи
    «Муже- Жен-» — це «Мужеска / Женска», а не прізвище «Муже».
    """
    k = key(word)
    if not k:
        return True
    if k in _FORM_KEYS or any(sim(k, f) >= 0.8 for f in _FORM_KEYS if len(f) >= 4):
        return True
    return len(k) >= 3 and any(f.startswith(k) and len(f) > len(k) for f in _FORM_KEYS)


# ── письмо ділянки ───────────────────────────────────────────────────────────
def form_hits(lines: list[str], script: str) -> int:
    """Скільки рядків містять формулу казки саме цим письмом.

    🔴 Латинський голос на кириличному рядку дає латинську кашу, але
    «Zona/Dzieci/Córka» з нічого не народжує; кириличний на польському — так
    само. Тому формули кожного письма шукаються голосом ЦЬОГО письма, і
    ділянка належить тому письму, чиїх формул більше.
    """
    forms = _CYR_FORMS_RAW if script == "cyrillic" else _LAT_FORMS_RAW
    n = 0
    for t in lines:
        words = {w.lower() for w in _WORD.findall(t)}
        if words & forms:
            n += 1
    return n


def script_of(cyr_lines: list[str], lat_lines: list[str], *, min_hits: int = 2) -> str:
    """`cyrillic` | `latin` | `""` — письмо ділянки за двома голосами тих самих рядків."""
    c, la = form_hits(cyr_lines, "cyrillic"), form_hits(lat_lines, "latin")
    if max(c, la) < min_hits:
        return ""
    if la > c:
        return "latin"
    if c > la:
        return "cyrillic"
    return ""


# ── геометрія ────────────────────────────────────────────────────────────────
def _xc(b: list[int]) -> float:
    return (int(b[0]) + int(b[2])) / 2.0


def gutter(boxes: list[Any], width: int) -> float:
    """Межа половин розвороту: найширший проміжок центрів рядків у середній третині.

    Без проміжку — середина кадру.
    """
    xs = sorted(_xc(b) for b in boxes if b and (int(b[2]) - int(b[0])) >= 0.05 * width)
    lo, hi = 0.30 * width, 0.70 * width
    best, at = 0.0, width / 2.0
    for a, b in itertools.pairwise(xs):
        if b < lo or a > hi:
            continue
        a2, b2 = max(a, lo), min(b, hi)
        if b2 - a2 > best:
            best, at = b2 - a2, (a2 + b2) / 2.0
    return at


def halves(boxes: list[Any], width: int) -> tuple[list[int], list[int]]:
    """Індекси рядків лівої й правої половини розвороту."""
    g = gutter(boxes, width)
    left = [i for i, b in enumerate(boxes) if b and _xc(b) < g]
    right = [i for i, b in enumerate(boxes) if b and _xc(b) >= g]
    return left, right


def main_lines(idx: list[int], boxes: list[Any], width: int,
               texts: list[str]) -> list[int]:
    """Рядки записів (не графи віку й не номери) у порядку читання — згори вниз."""
    out = []
    for i in idx:
        b = boxes[i] if i < len(boxes) else None
        if not b or (int(b[2]) - int(b[0])) < MAIN_MIN_W * width:
            continue
        t = texts[i] if i < len(texts) else ""
        if len(key(t).replace(" ", "")) < 3:
            continue
        out.append(i)
    return sorted(out, key=lambda i: (int(boxes[i][1]), int(boxes[i][0])))


# ── вирівнювання ─────────────────────────────────────────────────────────────
def align(a: list[str], b: list[str], *, ya: list[float] | None = None,
          yb: list[float] | None = None, floor: float = PAIR_FLOOR) -> list[tuple[int, int, float]]:
    """Монотонні пари `(i, j, схожість)` двох послідовностей рядків.

    Динамічне вирівнювання з пропусками: максимум суми `схожість − floor` по
    парах. Формули, що повторюються в кожному дворі («Дѣти у нихъ» / «Dzieci
    u nich»), стають якорями саме тому, що пари не можуть перехреститися.
    `ya`/`yb` — відносна висота рядка на сторінці (0..1): пара, розведена по
    висоті більш ніж на чверть сторінки, слабшає.
    """
    ka, kb = [key(t) for t in a], [key(t) for t in b]
    n, m = len(ka), len(kb)
    if not n or not m:
        return []
    s = [[sim(ka[i], kb[j]) for j in range(m)] for i in range(n)]
    if ya is not None and yb is not None:
        for i in range(n):
            for j in range(m):
                if abs(ya[i] - yb[j]) > 0.25:
                    s[i][j] *= 0.7
    tab = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(tab[i + 1][j], tab[i][j + 1])
            g = s[i][j] - floor
            if g > 0:
                best = max(best, g + tab[i + 1][j + 1])
            tab[i][j] = best
    out: list[tuple[int, int, float]] = []
    i = j = 0
    while i < n and j < m:
        g = s[i][j] - floor
        if g > 0 and abs(tab[i][j] - (g + tab[i + 1][j + 1])) < 1e-9:
            out.append((i, j, s[i][j]))
            i, j = i + 1, j + 1
        elif abs(tab[i][j] - tab[i + 1][j]) < 1e-9:
            i += 1
        else:
            j += 1
    return out


@dataclass
class PagePair:
    """Двійник однієї сторінки набору."""

    page: str
    twin_page: str
    own: list[int] = field(default_factory=list)        # рядки свого письма
    twin: list[int] = field(default_factory=list)       # рядки двійника (на twin_page)
    pairs: list[tuple[int, int, float]] = field(default_factory=list)  # (свій, двійника, схожість)
    own_main: int = 0
    note: str = ""

    @property
    def paired(self) -> float:
        """Частка рядків записів свого письма, що мають певну пару."""
        sure = sum(1 for _, _, s in self.pairs if s >= PAIR_SURE)
        return sure / self.own_main if self.own_main else 0.0


def pair_lines(own_idx: list[int], twin_idx: list[int], own_boxes: list[Any],
               twin_boxes: list[Any], own_h: int, twin_h: int, width: int,
               own_text: list[str], twin_text: list[str]) -> tuple[list[tuple[int, int, float]], int]:
    """Пари рядків записів між своєю ділянкою й ділянкою двійника."""
    om = main_lines(own_idx, own_boxes, width, own_text)
    tm = main_lines(twin_idx, twin_boxes, width, twin_text)
    ya = [int(own_boxes[i][1]) / max(1, own_h) for i in om]
    yb = [int(twin_boxes[j][1]) / max(1, twin_h) for j in tm]
    got = align([own_text[i] for i in om], [twin_text[j] for j in tm], ya=ya, yb=yb)
    return [(om[a], tm[b], s) for a, b, s in got], len(om)


_DIGITS = re.compile(r"\d+")


def grounds(text: str, twin_line: str) -> bool:
    """Мітка спирається на пару з двійника: те саме число або той самий запис.

    Число — збігом цифр (вік 42 в обох половинах); текст — схожістю спільних
    ключів не нижче `GROUND_MIN` і жодною власною назвою без опори.
    """
    if not text.strip() or not twin_line.strip():
        return False
    d1, d2 = _DIGITS.findall(text), _DIGITS.findall(twin_line)
    k1 = key(text)
    if d1 and not k1.replace(" ", "").strip():
        return d1 == d2
    if len(k1.replace(" ", "")) < 3:
        return False
    if sim(k1, key(twin_line)) < GROUND_MIN:
        return False
    return not unsupported(text, twin_line)


# ── ворота ───────────────────────────────────────────────────────────────────
#: Коротший огризок ворота не судять: трилітерний край прізвища на межі
#: смужки («Гав-») у двійнику ніде не стоїть цілим, і опора його випадкова.
NAME_MIN_LEN = 4


def name_words(text: str) -> list[str]:
    """Власні назви мітки: слово з великої літери, не формула, ≥`NAME_MIN_LEN` літер."""
    out = []
    for w in _WORD.findall(text):
        if len(w) < NAME_MIN_LEN or not w[0].isupper() or is_form(w):
            continue
        out.append(w)
    return out


def _variants(k: str) -> set[str]:
    out = {k}
    for g in NAME_GROUPS:
        if any(sim(k, v) >= 0.8 for v in g):
            out.update(g)
    return out


def support(word: str, twin_text: str) -> float:
    """Найкраща опора слова в тексті двійника, 0..1.

    Три шляхи: схожість зі словом двійника; народна чи церковна форма того
    самого імені (`NAME_GROUPS`); входження в суцільний текст двійника без
    пробілів — латинська модель рве слова пробілами («Hara cz ko w»).
    """
    k = key(word)
    if not k:
        return 1.0
    words = [w for w in key(twin_text).split() if len(w) >= 3]
    best = 0.0
    for v in _variants(k):
        for w in words:
            best = max(best, sim(v, w))
    flat = key(twin_text).replace(" ", "")
    if len(k) >= 5 and flat:
        best = max(best, float(fuzz.partial_ratio(k, flat)) / 100.0 * 0.95)
    return best


def unsupported(text: str, twin_text: str, *, floor: float = NAME_MIN) -> list[str]:
    """Власні назви мітки, яких у двійнику немає навіть віддалено."""
    if not twin_text.strip():
        return []
    return [w for w in name_words(text) if support(w, twin_text) < floor]


# ── двійник набору ───────────────────────────────────────────────────────────
TWIN_ID = "twin"
TWIN_PAGE_ID = "twin_page"
LINE_FILE = "hints/twin_line.json"
PAGE_FILE = "hints/twin_page.json"

HOW = ("той самий запис іншим письмом. Рядок двійника каже, ХТО стоїть у рядку: ім'я, "
       "по батькові, прізвище, родинний зв'язок, вік. Упізнай за ним особу, а літери бери "
       "з голосів і кропа.")
CAVEATS = (
    "польська половина пише народні форми імен (Hnat, Paraska, Samko, Iłko), кирилична — "
    "здебільшого церковні (Игнатъ, Параскевія, Самеонъ, Илья): форму з двійника в мітку "
    "НЕ переносити",
    "двійник — машинне читання іншою моделлю, у ньому свої помилки; збіг із ним літер не "
    "доводить",
    "пару рядків знайдено автоматично; ⚠ — пара непевна, двійник може належати сусідньому "
    "рядку",
    "прізвища, якого немає в двійнику навіть віддалено, у мітку з голосів не бери на "
    "high/med — імовірно, голоси його вигадали",
)


class TwinError(ValueError):
    """Нема з чого будувати двійник."""


@dataclass
class TwinReport:
    set: str
    pages: list[PagePair] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)    # сторінки без двійника
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        ok = [p for p in self.pages if p.pairs]
        lines = sum(p.own_main for p in ok)
        sure = sum(1 for p in ok for *_, s in p.pairs if s >= PAIR_SURE)
        return {"set": self.set, "pages": len(self.pages), "with_twin": len(ok),
                "spread": sum(1 for p in ok if p.page == p.twin_page),
                "pages_layout": sum(1 for p in ok if p.page != p.twin_page),
                "main_lines": lines, "paired_sure": sure,
                "paired": round(sure / lines, 3) if lines else 0.0,
                "missing": self.missing}


def _other(script: str) -> str:
    return "latin" if script == "cyrillic" else "cyrillic"


def _classify(own_script: str, own_lines: list[str], twin_lines: list[str]) -> str:
    """Письмо ділянки, де `own_lines` — голос свого письма, `twin_lines` — іншого."""
    if own_script == "cyrillic":
        return script_of(own_lines, twin_lines)
    return script_of(twin_lines, own_lines)


def _region_text(idx: list[int], boxes: list[Any], texts: list[str]) -> str:
    order = sorted((i for i in idx if i < len(texts) and texts[i].strip()),
                   key=lambda i: (int(boxes[i][1]), int(boxes[i][0])) if boxes[i] else (0, 0))
    return " / ".join(texts[i].strip() for i in order)


def build(name: str, *, twin_run: str = "", twin_set: str = "", twin_draft: str = "",
          own_draft: str = "", layout: str = "auto", script: str = "",
          dry_run: bool = False, ws: Any = None) -> TwinReport:
    """Знайти двійника кожної сторінки набору й записати його як джерело підказок.

    Свій текст — голос `own_draft` (типово перший голос набору, тобто прогін);
    текст двійника — голос `twin_draft` набору `twin_set` (типово цього ж), а
    де його немає — прогін `twin_run` (гілка іншого письма того самого прогону:
    рамки ті самі). Сторінка без двійника лишається як є і йде в `missing`.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.train import cut as C
    from nyshporka.train import sets as S

    if layout not in LAYOUTS:
        raise TwinError(f"розклад «{layout}» невідомий: {' | '.join(LAYOUTS)}")
    w = ws if ws is not None else workspace()
    reg = S.registry(w)
    spec = reg.load(name)
    if script:
        if script not in SCRIPTS:
            raise TwinError(f"письмо «{script}» невідоме: {' | '.join(SCRIPTS)}")
        # Набір із мішаного прогону (`mixed`) успадковує його письмо, а сторінки
        # в ньому — одного: назвати письмо набору тут дешевше, ніж правити set.json.
        spec.script = script
    if spec.script not in SCRIPTS:
        raise TwinError(f"письмо набору «{spec.script}» — назвіть письмо свого набору: "
                        f"--script {' | '.join(SCRIPTS)}")
    run = spec.source_run
    if not run:
        raise TwinError(f"набір «{name}» нарізаний не з прогону — рамок для пар немає")
    voices = spec.voices()
    own_d = next((d for d in voices if d.id == own_draft), None) if own_draft \
        else (voices[0] if voices else None)
    if own_d is None:
        raise TwinError(f"голосу «{own_draft}» у наборі немає")
    t_spec = reg.load(twin_set) if twin_set else spec
    t_d = None
    if twin_draft:
        t_d = next((d for d in t_spec.drafts if d.id == twin_draft), None)
        if t_d is None:
            raise TwinError(f"голосу «{twin_draft}» у наборі «{t_spec.name}» немає")
    if t_d is None and not twin_run:
        raise TwinError("звідки текст двійника: --twin-draft (голос набору) або "
                        "--twin-run (прогін іншого письма)")
    meta = C.run_meta(run, w)
    run_pages = sorted(C.page_keys(meta))
    pos = {p: i for i, p in enumerate(run_pages)}
    have = reg.crop_pages(spec)

    def own_text(pg: str) -> list[str]:
        got = reg.draft_lines(spec, own_d, pg) if pg in have else None
        return got if got is not None else (C.page_text(run, pg, w) or [])

    def twin_text(pg: str) -> list[str]:
        got = None
        if t_d is not None and pg in reg.crop_pages(t_spec):
            got = reg.draft_lines(t_spec, t_d, pg)
        if got is None and twin_run:
            got = C.page_text(twin_run, pg, w)
        return got or []

    rep = TwinReport(set=name)
    line_hints: dict[str, dict[str, str]] = {}
    page_hints: dict[str, dict[str, str]] = {}
    pages_meta: dict[str, Any] = {}
    other = _other(spec.script)
    for pg in sorted(have):
        geo = C.page_geometry(run, pg, w)
        if geo is None:
            rep.missing.append(pg)
            rep.warnings.append(f"{pg}: прогін не зберіг рамок — двійника не шукали")
            continue
        boxes = geo.get("boxes") or []
        width, height = int(geo["size"][0]), int(geo["size"][1])
        mine, tw = own_text(pg), twin_text(pg)
        pp: PagePair | None = None
        if layout in ("auto", "spread"):
            left, right = halves(boxes, width)
            sl = _classify(spec.script, [mine[i] for i in left if i < len(mine)],
                           [tw[i] for i in left if i < len(tw)])
            sr = _classify(spec.script, [mine[i] for i in right if i < len(mine)],
                           [tw[i] for i in right if i < len(tw)])
            if {sl, sr} == {spec.script, other}:
                own_idx, t_idx = (left, right) if sl == spec.script else (right, left)
                pairs, n = pair_lines(own_idx, t_idx, boxes, boxes, height, height, width,
                                      mine, tw)
                pp = PagePair(page=pg, twin_page=pg, own=own_idx, twin=t_idx, pairs=pairs,
                              own_main=n, note="spread")
        if pp is None and layout in ("auto", "pages"):
            i = pos.get(pg)
            best: PagePair | None = None
            for q in (run_pages[i - 1] if i else None,
                      run_pages[i + 1] if i is not None and i + 1 < len(run_pages) else None):
                if not q:
                    continue
                g2 = C.page_geometry(run, q, w)
                if g2 is None:
                    continue
                b2 = g2.get("boxes") or []
                q_own, q_tw = own_text(q), twin_text(q)
                if _classify(spec.script, q_own, q_tw) != other:
                    continue
                pairs, n = pair_lines(list(range(len(boxes))), list(range(len(b2))),
                                      boxes, b2, height, int(g2["size"][1]), width,
                                      mine, q_tw)
                cand = PagePair(page=pg, twin_page=q, own=[], twin=list(range(len(b2))),
                                pairs=pairs, own_main=n, note="pages")
                if best is None or cand.paired > best.paired:
                    best = cand
            pp = best
        if pp is None or not pp.pairs:
            rep.missing.append(pg)
            continue
        rep.pages.append(pp)
        t_lines = tw if pp.twin_page == pg else twin_text(pp.twin_page)
        t_boxes = boxes if pp.twin_page == pg else \
            ((C.page_geometry(run, pp.twin_page, w) or {}).get("boxes") or [])
        # Графи віку окремо не в'язати: прив'язка через рядок запису на ревізії
        # 1795 дала 1 збіг проти 7 розбіжностей із мітками (tw-207b, 06.11.2026) —
        # польська половина розставляє вік інакше. Вік арбітр бере з ДВІЙНИК-СТОР.
        for a, b, s in pp.pairs:
            if b >= len(t_lines) or not t_lines[b].strip():
                continue
            v = {"text": t_lines[b].strip()}
            if s < PAIR_SURE:
                v["doubt"] = f"пара непевна (схожість {s:.2f})"
            line_hints[f"{pg}:{a}"] = v
        page_hints[pg] = {"text": _region_text(pp.twin, t_boxes, t_lines)}
        entry: dict[str, Any] = {"layout": pp.note, "twin_page": pp.twin_page,
                                 "paired": round(pp.paired, 3)}
        if pp.note == "spread":
            entry["own"] = sorted(pp.own)
        pages_meta[pg] = entry
    if dry_run:
        return rep
    d = reg.set_dir(name)
    from nyshporka.utils.atomic import write_json

    (d / "hints").mkdir(parents=True, exist_ok=True)
    write_json(d / LINE_FILE, line_hints)
    write_json(d / PAGE_FILE, page_hints)
    src_txt = (f"голос «{t_d.id}» набору «{t_spec.name}»" if t_d is not None
               else f"прогін «{twin_run}»")
    keep = [h for h in spec.hint_sources if h.id not in (TWIN_ID, TWIN_PAGE_ID)]
    spec.hint_sources = [
        *keep,
        S.HintSource(id=TWIN_ID, kind="twin", level="line", label="ДВІЙНИК",
                     title=f"той самий рядок іншим письмом ({src_txt})", by="машинне читання",
                     trust="single", how=HOW, caveats=list(CAVEATS), file=LINE_FILE),
        S.HintSource(id=TWIN_PAGE_ID, kind="twin", level="page", label="ДВІЙНИК-СТОР",
                     title=f"уся половина іншим письмом ({src_txt})", by="машинне читання",
                     trust="single", how="весь запис двору іншим письмом, у порядку аркуша — "
                                         "для контексту, коли пару рядка не знайдено",
                     file=PAGE_FILE),
    ]
    spec.twin = {"source": {"run": twin_run, "set": t_spec.name if t_d is not None else "",
                            "draft": t_d.id if t_d is not None else "", "own": own_d.id},
                 "pages": pages_meta}
    reg.save(spec)
    return rep


def page_gate_text(reg: Any, spec: Any, page: str) -> str:
    """Текст двійника сторінки для воріт — лише коли пари на ній надійні."""
    info = ((spec.twin or {}).get("pages") or {}).get(page) or {}
    if float(info.get("paired") or 0.0) < PAGE_PAIRED_MIN:
        return ""
    src = next((h for h in spec.hint_sources if h.id == TWIN_PAGE_ID), None)
    if src is None:
        return ""
    return str((reg.hint_data(spec, src).get(page) or {}).get("text") or "")


def line_twins(reg: Any, spec: Any, page: str) -> dict[int, str]:
    """{рядок: певна пара двійника} — без пар із сумнівом."""
    src = next((h for h in spec.hint_sources if h.id == TWIN_ID), None)
    if src is None:
        return {}
    out: dict[int, str] = {}
    for k, v in reg.hint_data(spec, src).items():
        pg, _, idx = k.rpartition(":")
        if pg == page and idx.isdigit() and not v.get("doubt"):
            out[int(idx)] = str(v.get("text") or "")
    return out


__all__ = ["GROUND_MIN", "LAYOUTS", "NAME_MIN", "PAIR_FLOOR", "PAIR_SURE", "PagePair",
           "TwinError", "TwinReport", "align", "build", "form_hits", "grounds", "gutter",
           "halves", "is_form", "key", "line_twins", "main_lines", "name_words",
           "page_gate_text", "pair_lines", "script_of", "sim", "support",
           "unsupported"]
