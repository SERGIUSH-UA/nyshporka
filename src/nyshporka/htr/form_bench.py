"""📏 Бенч бланка: чи видно звірені оком слова в кожному голосі справи.

Міра — частка слів-істин, які знаходяться в тексті сторінки голосу зі схожістю
≥ `THRESH` (як поріг пошуку). Порівняння — зі СЛОВАМИ рядка й парами сусідніх
слів (слово, розірване рамкою клітинки), а не з підрядком усього рядка: на сотні
шумних рядків `partial_ratio` «знаходить» коротке ім'я будь-де.

Окремо рахується «разом» — слово видно хоч в одному голосі. Саме це число
каже, що дає новий голос понад наявні: клітинки бланка й основний прогін
помиляються в різних місцях.

Істина — звірені оком читання з нотатника справи (`nysh note read`) або файл
`{сторінка: [слова]}`, де сторінка — назва кадру без розширення.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

#: Поріг схожості слова (0–100), як `--thresh` пошуку.
THRESH = 80
#: Слово-істина коротше за стільки літер не міряється: «і», «et» видно скрізь.
MIN_LEN = 3
_WORD = re.compile(r"[^\W\d_]+")


@dataclass
class VoiceScore:
    name: str
    seen: int = 0
    pages: int = 0


@dataclass
class Bench:
    words: int = 0
    pages: int = 0
    voices: list[VoiceScore] = field(default_factory=list)
    together: int = 0
    #: (сторінка, слово, {голос: схожість}) — для розбору, що саме не видно.
    rows: list[tuple[str, str, dict[str, int]]] = field(default_factory=list)

    def as_dict(self) -> dict:
        def pct(n: int) -> float:
            return round(100 * n / self.words, 1) if self.words else 0.0

        return {"words": self.words, "pages": self.pages,
                "voices": [{"name": v.name, "seen": v.seen, "pct": pct(v.seen),
                            "pages": v.pages} for v in self.voices],
                "together": {"seen": self.together, "pct": pct(self.together)},
                "missed": [{"page": p, "word": w, "best": max(s.values(), default=0)}
                           for p, w, s in self.rows
                           if max(s.values(), default=0) < THRESH]}


def _norm(s: str) -> str:
    from nyshporka.utils.translit import normalize_archival

    return normalize_archival(s)


def _tokens(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        toks = [_norm(t) for t in _WORD.findall(line)]
        out += [t for t in toks if len(t) >= 2]
        out += [a + b for a, b in zip(toks, toks[1:], strict=False)]
    return out


def best(word: str, tokens: list[str]) -> int:
    """Найкраща схожість слова з токенами сторінки (0–100)."""
    from rapidfuzz import fuzz, process

    if not tokens:
        return 0
    got = process.extractOne(_norm(word), tokens, scorer=fuzz.ratio)
    return round(got[1]) if got else 0


def page_lines(run_dir: Path, page: str) -> list[str] | None:
    """Рядки сторінки голосу; `None` — сторінки в голосі немає."""
    p = run_dir / f"{page}.txt"
    if not p.is_file():
        return None
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def score(truth: Mapping[str, Iterable[str]], voices: Mapping[str, Path]) -> Bench:
    """Слова-істини проти кожного голосу й проти всіх разом."""
    b = Bench(voices=[VoiceScore(n) for n in voices])
    for page, words in sorted(truth.items()):
        want = [w for w in dict.fromkeys(words) if len(_norm(w)) >= MIN_LEN]
        if not want:
            continue
        b.pages += 1
        toks: dict[str, list[str]] = {}
        for v in b.voices:
            lines = page_lines(voices[v.name], page)
            if lines is not None:
                v.pages += 1
            toks[v.name] = _tokens(lines or [])
        for w in want:
            got = {n: best(w, t) for n, t in toks.items()}
            b.words += 1
            for v in b.voices:
                v.seen += got[v.name] >= THRESH
            b.together += max(got.values(), default=0) >= THRESH
            b.rows.append((page, w, got))
    return b


def truth_from_notes(notes: Iterable) -> dict[str, list[str]]:
    """Звірені оком читання нотатника → {сторінка: слова}.

    Звірене одне слово (`word`) — лише воно; звірений рядок — усі його слова.
    """
    from nyshporka.pagestore.notebook import live

    out: dict[str, list[str]] = {}
    for n in live(list(notes)):
        if n.kind != "reading" or not n.page:
            continue
        text = n.word.text if n.word is not None else n.text
        words = _WORD.findall(text or "")
        if words:
            out.setdefault(Path(n.page).stem, []).extend(words)
    return out


def truth_from_file(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: очікується {{сторінка: [слова]}}")
    return {Path(str(k)).stem: [str(w) for w in v] for k, v in data.items()}
