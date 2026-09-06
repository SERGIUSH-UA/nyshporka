"""📏 Чим міряти модель: CER, WER і recall власних назв — з одного прогону.

🔴 CER і придатність до пошуку РОЗХОДЯТЬСЯ: версія з гіршим CER знаходила на
десять прізвищ більше зі ста восьми. Нишпорка шукає прізвища, а не читає
текст, тож первинний критерій — recall власних назв: слова з великої літери
довжиною ≥5, без посад і станів, без підписантів набору (`skip_names`), кожне
шукається у ВІДПОВІДНОМУ рядку прогнозу нечітко поверх тієї самої
нормалізації, що й у пошуку. CER показується поруч: коли переможець за
recall програє за CER, це відомий розхід двох метрик, а не помилка виміру.

🔴 Корпусний CER (сума відстаней / сума довжин), не середнє по рядках:
інакше короткі уламки важать як повний рядок.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from nyshporka.utils.translit import normalize_for_matching

HIST_MAP = str.maketrans({"ъ": "", "ь": "", "ѣ": "е", "ѳ": "ф",
                          "і": "и", "ї": "и", "ы": "и", "ѵ": "и"})
#: Слова з великої літери, які НЕ є власними назвами: посади, стани, установи.
GENERIC = ("Священник", "Псаломщик", "Діакон", "Дьячок", "Пономар", "Приходск",
           "Крестьян", "Мѣщан", "Церкв", "Церков", "Мѣстечк", "Метрическ", "Села",
           "Село", "Мѣсяц", "Званіе", "Лѣта")
NAME_RE = re.compile(r"[А-ЯІЇЄҐѢѲ][а-яіїєґѣѳ\-]{4,}")
THRESH = 80
#: Набір із меншим числом рядків самостійного висновку не витримує.
SMALL_SET = 60


def norm_cer(s: str, mode: str = "strip") -> str:
    s = unicodedata.normalize("NFC", s)
    s = " ".join(s.split())
    if mode == "loose":
        s = s.lower().translate(HIST_MAP)
    return s


def names_of(text: str, skip: tuple[str, ...] | list[str] = ()) -> list[str]:
    out = []
    for w in NAME_RE.findall(text):
        if any(w.startswith(g) for g in GENERIC):
            continue
        if any(w.startswith(c) for c in skip):
            continue
        out.append(w)
    return out


def name_score(name: str, line: str) -> int:
    """Найкращий бал назви проти токенів рядка прогнозу (нормалізовано)."""
    target = normalize_for_matching(name)
    if not target:
        return 0
    best = 0
    for tok in line.split():
        tok_n = normalize_for_matching(tok)
        if tok_n:
            best = max(best, int(fuzz.ratio(target, tok_n)))
    return best


@dataclass
class SetMetrics:
    n_ok: int = 0
    ce: int = 0
    clen: int = 0
    we: int = 0
    wlen: int = 0
    n_names: int = 0
    hit: int = 0
    exact: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def cer(self) -> float:
        return self.ce / max(1, self.clen)

    @property
    def wer(self) -> float:
        return self.we / max(1, self.wlen)

    @property
    def recall(self) -> float:
        return self.hit / max(1, self.n_names)

    def as_dict(self) -> dict[str, Any]:
        return {"n_ok": self.n_ok, "ce": self.ce, "clen": self.clen, "we": self.we,
                "wlen": self.wlen, "n_names": self.n_names, "hit": self.hit,
                "exact": self.exact, "cer": round(self.cer, 4), "wer": round(self.wer, 4),
                "recall": round(self.recall, 4), "small": self.n_ok < SMALL_SET}


def measure(pairs: list[tuple[str, str]], *, skip_names: list[str] | None = None,
            mode: str = "strip", thresh: int = THRESH) -> SetMetrics:
    """`pairs` — [(еталон, прогноз)] лише для рядків `ok`."""
    m = SetMetrics()
    skip = tuple(skip_names or ())
    for gt, pred in pairs:
        g, pr = norm_cer(gt, mode), norm_cer(pred, mode)
        m.ce += Levenshtein.distance(g, pr)
        m.clen += len(g)
        m.we += Levenshtein.distance(g.split(), pr.split())
        m.wlen += len(g.split())
        m.n_ok += 1
        for name in names_of(gt, skip):
            m.n_names += 1
            s = name_score(name, pred)
            if s >= thresh:
                m.hit += 1
            else:
                m.misses.append(name)
            if s == 100:
                m.exact += 1
    return m


def micro(rows: dict[str, SetMetrics]) -> dict[str, float]:
    """Складені влучання й назви по ВСІХ наборах: вага набору = його обсяг.

    Макро (середнє відсотків) дало б набору з вісьмома назвами таку саму вагу,
    як набору з п'ятьма сотнями. Показуємо обидва: розбіжність між ними — сама
    по собі сигнал, що рейтинг тримається на малому наборі.
    """
    hit = sum(m.hit for m in rows.values())
    nn = max(1, sum(m.n_names for m in rows.values()))
    ex = sum(m.exact for m in rows.values())
    ce = sum(m.ce for m in rows.values())
    cl = max(1, sum(m.clen for m in rows.values()))
    return {"recall": hit / nn, "exact": ex / nn, "cer": ce / cl, "n_names": nn - (0 if nn else 1)}


def macro(rows: dict[str, SetMetrics]) -> dict[str, float]:
    if not rows:
        return {"recall": 0.0, "cer": 0.0}
    return {"recall": sum(m.recall for m in rows.values()) / len(rows),
            "cer": sum(m.cer for m in rows.values()) / len(rows)}
