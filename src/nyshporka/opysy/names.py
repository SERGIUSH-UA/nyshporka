"""🔤 Власні назви в назві справи: позначки ⟨?…⟩ і звірка нормалізованого з сирим.

Нормалізація (шаблон `norm_prompt.md`) виправляє ЗВИЧАЙНІ слова, а прізвища,
імена й назви місць переписує буквально — дозволено лише закінчення за
відмінком. Зіпсовану основу вона не лагодить, а обгортає: `⟨?Ібанов⟩`.
Виправити саме прізвище можна лише правилом підстановки з доказом, а не
нормалізацією.

🔴 Навіщо звірка. Вільна нормалізація на скорописі вигадала 49 власних назв на
60 рядків (вибірка описів XIX ст., 22.11.2026): «виправлене» прізвище читається
впевнено, а людина шукає не того й замовляє не ту справу. Тут машинно
перевіряється, що кожна власна назва нормалізованого тексту має відповідник у
сирому — у тому самому слові чи у склейці сусідніх (рушій рве й склеює слова).

Звірка йде у фолді `normalize_archival` (старі літери, плутанини рушія): основа
до основи — бо закінчення міняти можна — і ціле слово до цілого.

Заміри (22.11.2026, вибірка A/B і Б2; калібрування — у дослідницькому конвеєрі, не в пакеті) —
частка рядків із назвою без відповідника, зі словником: B ≤ 5 %, Б2 0,3 %, вільна
нормалізація A на скорописі 31,7 %. 🔴 Без словника B на скорописі дає 16,7 %, Б2 —
7,9 %: чини й установи з великої йдуть за «вигадані прізвища». Тому для мови без
словника ворота лише позначають рядки, а не відмовляють (`gates._gate_invented`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from rapidfuzz import fuzz

from nyshporka.utils.translit import normalize_archival

#: Позначка зіпсованої власної назви: `⟨?слово⟩`.
MARK_RX = re.compile(r"⟨\?([^⟩]*)⟩")
#: Слово: літери будь-якого з наших письм, з дефісом усередині.
WORD_RX = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")

#: Найкоротша власна назва, яку звіряємо (коротші — ініціали, «св», «г»).
MIN_NAME = 3
#: Скільки знаків закінчення відкидати перед звіркою основ: 2, а в довгому
#: слові 3 — інакше дореформене «-аго» і сучасне «-ого» дають різні основи.
ENDING = 2
ENDING_LONG = 3
LONG_WORD = 8
#: Межа схожості (rapidfuzz `ratio`). 70 і 75 дали ті самі частки, 80+ уже
#: позначає чесні рядки (`gates.POLICY` змінюється разом із нею).
STEM_RATIO = 75.0

#: Загальна лексика з великої літери: чини, установи, «Крестьянъ» у ділових
#: назвах XIX ст. Основи слів, які людські описи справ (сучасна орфографія) пишуть з МАЛОЇ;
#: власні назви з малої не пишуться. Словник будує дослідницький конвеєр, не пакет.
LEXICON = "common_ru.txt"
#: Мова опису → словник. Мова поза переліком словника не має.
LEXICONS = {"ru": LEXICON}
#: Скільки основ у словнику: тест звіряє, щоб зміна словника не пройшла повз
#: номер правил воріт.
LEXICON_STEMS = 5364


def marks(text: str) -> list[str]:
    """Вміст позначок ⟨?…⟩ по порядку."""
    return [m.strip() for m in MARK_RX.findall(text or "")]


def unmark(text: str) -> str:
    """Текст із розкритими позначками: `⟨?Ібанов⟩` → `Ібанов`."""
    return MARK_RX.sub(lambda m: m.group(1), text or "")


def _cut(folded: str) -> str:
    if len(folded) >= LONG_WORD:
        return folded[:-ENDING_LONG]
    return folded[:-ENDING] if len(folded) > ENDING + 2 else folded


def _fold(word: str) -> str:
    return normalize_archival(word).replace(" ", "")


def stem(word: str) -> str:
    """Основа слова у фолді: без закінчення, старі літери зведені."""
    return _cut(_fold(word))


@lru_cache(maxsize=4)
def common_stems(name: str = LEXICON) -> frozenset[str]:
    """Основи загальних слів (вбудований словник).

    🔴 Відсутній файл — помилка, а не порожній словник: без нього ворота
    тихо стають суворішими (чини й установи йдуть як «вигадані прізвища»), і
    клієнт із сервером судили б той самий пакет по-різному.
    """
    text = resources.files("nyshporka.opysy").joinpath("data", name).read_text(encoding="utf-8")
    return frozenset(x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#"))


def lexicon_for(language: str) -> frozenset[str] | None:
    """Словник загальних слів мови опису; None — для цієї мови словника немає."""
    name = LEXICONS.get(language)
    return common_stems(name) if name else None


def proper_names(text: str, common: frozenset[str] = frozenset()) -> list[str]:
    """Слова з великої літери, крім першого слова назви, — кандидати у власні назви.

    Перше слово великим пишеться за правописом («Дело…», «По жалобе…»), тож
    воно нічого не каже. Слово з малої — звичайне, його нормалізація правити
    може. Слово з великої, чия основа є в `common` (чин, установа), — теж.
    """
    words = WORD_RX.findall(unmark(text))
    return [w for w in words[1:]
            if len(w) >= MIN_NAME and w[0].isupper() and stem(w) not in common]


@dataclass
class RawIndex:
    """Сирий текст для звірки: слова й склейки двох-трьох сусідів, у фолді."""

    folded: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, raw: str) -> RawIndex:
        words = [_fold(w) for w in WORD_RX.findall(raw or "")]
        out: list[str] = []
        for i in range(len(words)):
            # Слово, склейка двох і трьох сусідів: рушій рве слово («Нико ласьской»).
            for n in (1, 2, 3):
                if i + n <= len(words):
                    out.append("".join(words[i:i + n]))
        return cls(folded=out)


def found_in_raw(name: str, idx: RawIndex, *, ratio: float = STEM_RATIO) -> bool:
    """Чи має власна назва відповідник у сирому тексті."""
    full = _fold(name)
    s = _cut(full)
    if not s:
        return True
    for cand in idx.folded:
        # Основа до основи (закінчення міняти можна). Ціле слово до цілого — лише
        # в короткому слові, де відкинуте закінчення важить завелике («Сабирь» →
        # «Сибирь»); у довгому спільне закінчення тягне схожість угору й пропускає
        # підмінену основу («Шварушана» → «Шварцмана»).
        if fuzz.ratio(s, _cut(cand)) >= ratio:
            return True
        if len(full) < LONG_WORD and fuzz.ratio(full, cand) >= ratio:
            return True
        # Склеєне з сусідом: основа стоїть усередині довшого сирого слова
        # («помещикаЛопухина»). Лише довга основа й майже дослівно.
        if len(cand) > len(full) + 2 and len(s) >= 5 and fuzz.partial_ratio(s, cand) >= max(ratio, 90.0):
            return True
    return False


def invented(raw: str, norm: str, *, ratio: float = STEM_RATIO,
             common: frozenset[str] | None = None) -> list[str]:
    """Власні назви нормалізованого тексту, яких у сирому немає.

    Вміст позначок ⟨?…⟩ звіряється так само, слово за словом: позначене мало
    бути переписане з сирого буквально. `common` — основи загальних слів;
    None — вбудований словник.
    """
    if not norm:
        return []
    common = common_stems() if common is None else common
    idx = RawIndex.of(raw)
    marked = [w for m in marks(norm) for w in WORD_RX.findall(m) if len(w) >= MIN_NAME]
    seen: list[str] = []
    for name in proper_names(norm, common) + marked:
        if name not in seen and not found_in_raw(name, idx, ratio=ratio):
            seen.append(name)
    return seen
