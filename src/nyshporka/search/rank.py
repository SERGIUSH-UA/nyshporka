"""⚖ Ранг кандидата: чому слово радше чуже — сказано, але не викинуто.

🔴 **Позначка, а не фільтр.** Це не обережність, а виміряна асиметрія ціни:
хибний плюс людина відсіює за секунди, а пропущений аркуш не відсівається
нічим, бо його ніколи не буде в списку. Тому все, що може виявитись прізвищем,
опускається вниз із названою причиною — і лишається у видачі.

Прецедент у пакеті той самий: `htr_store.mark_phantoms` («🪤 Позначити хіти…
НЕ прибирати. 🔴 Позначка, а не фільтр, і це рішення»).

🔴 **Знання про рід живе в профілі простору, не тут.** У цьому модулі немає й
не сміє з'явитись жодного прізвища, кореня чи слова конкретної канцелярії:
`confusers` і `rank_down` приходять із `config/research_profile.yaml`, куди
заготовка профілю прямо запрошує їх дописати. Доти ці поля читались лише
формою — тобто пакет просив калібрувати те, чого потім не питав.

⚠ **Порівняння йде з НОРМАЛІЗОВАНИМ текстом** (`normalize_archival`: кирилиця й
латинка зведені, історичні літери й плутанини рушія згорнуті). Для `confusers`
це безпечно — вони рядки, і ми нормалізуємо їх самі. Для `rank_down` це
регекси, нормалізувати які не можна: правило, написане кирилицею, не спрацює
НІКОЛИ. Тому таке правило не мовчить, а називається вголос.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nyshporka.utils.translit import normalize_archival

#: Кандидат, якого чуже слово пояснює краще за шукане прізвище.
CONFUSER = "confuser"
#: Кандидат, який підпав під іменоване правило зниження з профілю.
RANK_DOWN = "rank_down"

#: Наскільки опускається кожен клас. Числа, а не булеве: конфузер сильніший за
#: правило рангу, бо він каже «є краще пояснення цього слова», а правило лише
#: «схоже на службовий формуляр».
PENALTY = {CONFUSER: 2, RANK_DOWN: 1}

#: Літери, яких у нормалізованому тексті не буває. Правило з ними мертве.
_CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґЎўЪъЫыЬьѢѣѲѳѴѵ]")


@dataclass(frozen=True)
class Rules:
    """Правила рангу з профілю. Порожні — модуль нічого не робить."""

    #: Нормалізовані рядки-конфузери.
    confusers: tuple[str, ...] = ()
    #: (ім'я правила, скомпільований регекс) — ім'я їде у відповідь як причина.
    rank_down: tuple[tuple[str, re.Pattern[str]], ...] = ()
    #: Правила, написані кирилицею: вони не спрацюють ніколи, і про це кажемо.
    dead: tuple[str, ...] = ()
    #: Правила, які не скомпілювались. Теж не привід падати, але й не мовчати.
    broken: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.confusers and not self.rank_down


EMPTY = Rules()


def rules(prof: Any = None) -> Rules:
    """Правила з профілю простору. Профілю немає — порожньо, і це не помилка.

    ⚠ Профіль читається тут, а не передається згори, бо кличеться це з двох
    незалежних областей пошуку. Друга копія правила розійшлася б із першою
    тихо, і дві області почали б по-різному відповідати на те саме питання.
    """
    if prof is None:
        try:
            from nyshporka.core.profile import active

            prof = active()
        except Exception:
            return EMPTY
    conf = tuple(sorted({normalize_archival(c) for c in
                         (getattr(prof, "confusers", ()) or ()) if c}))
    good: list[tuple[str, re.Pattern[str]]] = []
    dead: list[str] = []
    broken: list[str] = []
    for name, pat in (getattr(prof, "rank_down", {}) or {}).items():
        text = str(pat or "")
        if not text:
            continue
        if _CYRILLIC.search(text):
            dead.append(str(name))
            continue
        try:
            good.append((str(name), re.compile(text, re.IGNORECASE)))
        except re.error:
            broken.append(str(name))
    return Rules(confusers=conf, rank_down=tuple(good),
                 dead=tuple(sorted(dead)), broken=tuple(sorted(broken)))


def mark(hits: list[dict[str, Any]], rul: Rules, *, key: str = "norm",
         ) -> dict[str, int]:
    """Проставити хітам `rank`, `rank_why` і `rank_penalty`. Нічого не видаляє.

    🔴 Конфузер вирішується ПОРІВНЯННЯМ, а не наявністю в списку. Кандидат
    живий, поки бал до шуканого вищий за бал до найближчого чужого слова;
    щойно чуже пояснює токен краще — це видно числом, а не здогадом. Правило
    взяте з приватного конвеєра, де воно стоїть у двох місцях однаково.

    ⚠ Кличеться ДО зрізу за `limit`, інакше позначка міняла б лише порядок
    показаного, а не те, що показують.
    """
    from rapidfuzz import fuzz

    tally = {CONFUSER: 0, RANK_DOWN: 0}
    if rul.empty:
        return tally
    # 🔴 Рахується по ФОРМАХ, не по хітах: на корпусі 300 тис. хітів, а різних
    # форм у рази менше, і 2.7 млн викликів регексу давали 7 с із 11 у пошуку
    # з кешу (замір 08.09). Бал до конфузера й правило зниження залежать лише
    # від форми; лише порівняння з балом хіта — від хіта.
    forms = {str(h.get(key) or "") for h in hits}
    forms.discard("")
    best_of: dict[str, float] = {}
    if rul.confusers:
        best_of = _confuser_scores(fuzz, sorted(forms), rul.confusers)
    down_of: dict[str, str] = {}
    for norm in forms:
        for name, rx in rul.rank_down:
            if rx.search(norm):
                down_of[norm] = name
                break
    for h in hits:
        norm = str(h.get(key) or "")
        if not norm:
            continue
        best = best_of.get(norm)
        if best is not None and best >= float(h.get("score") or 0):
            _put(h, CONFUSER, f"чуже слово пояснює краще ({round(best)})")
            tally[CONFUSER] += 1
            continue
        rule = down_of.get(norm)
        if rule:
            _put(h, RANK_DOWN, rule)
            tally[RANK_DOWN] += 1
    return tally


def _confuser_scores(fuzz: Any, forms: list[str], confusers: tuple[str, ...]
                     ) -> dict[str, float]:
    """Найкращий бал кожної форми до пулу конфузерів — гуртом, якщо є numpy."""
    try:
        import numpy as np
        from rapidfuzz.process import cdist
    except ImportError:
        return {f: max(fuzz.ratio(f, c) for c in confusers) for f in forms}
    if not forms:
        return {}
    m = cdist(forms, list(confusers), scorer=fuzz.ratio, dtype=np.float32, workers=-1)
    best = m.max(axis=1)
    return {f: float(best[i]) for i, f in enumerate(forms)}


def _put(h: dict[str, Any], kind: str, why: str) -> None:
    h["rank"] = kind
    h["rank_why"] = why
    h["rank_penalty"] = PENALTY[kind]


def sort_key(h: dict[str, Any]) -> tuple[int, float]:
    """Порядок видачі: спершу чисті, всередині кожного класу — за балом.

    🔴 Одна точка на всі області пошуку. Доти сортування було просто `-score`,
    і найгучніші хіти справи регулярно виявлялись службовим формуляром: замір
    приватного конвеєра — 60 сильних кандидатів, з них 26 рубрика «домашнія»,
    19 сусідній рід, роду НУЛЬ, і всі три верхні місця за балом займала рубрика.
    """
    return (int(h.get("rank_penalty") or 0), -float(h.get("score") or 0))
