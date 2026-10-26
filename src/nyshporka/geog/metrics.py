"""📚 Покажчик метрик за селом: назви, ключі й зіставлення.

Пак `metrics` відповідає на питання Рідних (ridni.org) — **які книги є про
село** — без мережі, як запасний канал на час, коли Рідні не відповідають
(25.10.2026 — Cloudflare 522). Адрес копій і плівок у ньому немає. Запис пака — церква (костел,
синагога, сільрада, група сіл РАЦС) з місцем, приписними селами й справами за
типом запису. Джерела — Зведений каталог метричних книг т.1–10 і власні
каталоги й описи архівів; що саме, каже `meta.note` і `coverage_scope` пака.

Тут — лише рядкова частина, спільна для збирача й читача: ключі назви
записуються в пак тими самими функціями, якими потім рахується запит. Розійдись
вони — і пак мовчки перестав би знаходити те, що в ньому лежить.

🔴 **Кирилиця з кирилицею — напряму, транслітерація — лише між письмами.**
Нечіткий збіг через латинський ключ давав «Зеленка ~ Зеленівка»: дві різні
назви одного письма, які ця гілка зводила в одну. Польські й латинські форми
(«Zielonka», «Bełz») ловить `fold`, і тільки коли запит і назва в різних письмах.

🔴 **Сільраду в село не перетворюємо.** Описи РАЦС пишуть «по Ковалівській с/р»:
запис лишається «Ковалівська с/р», а запит «Ковалів» знаходить його за основою
(`sr_variants`) з позначкою «сільрада ~». Назва села, вгадана з прикметника,
була б вигаданим даним.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Роки в полі «роки» справи: «1835-1837,1839-1844», «1866–1938».
YEARS_RE = re.compile(r"\b(1[5-9]\d{2}|20[0-4]\d)\b")
#: Закінчення прикметника — для основи слова повіту («Кременецький» → кременецьк).
_ADJ_END = re.compile(r"(ого|ому|ий|ій|им|ім|ої|ою|ая|а|е|і|у)$")
#: Латинська літера (з польськими) — назва в іншому письмі.
_LATIN = re.compile(r"[a-ząćęłńóśźż]")
#: Поріг нечіткого збігу транслітерованих форм: «prusiniv» ~ «prusinuv» = 88.
FOLD_MIN = 86
#: Поріг «схожих назв» на нуль: одна літера в назві з 7–8 літер ≈ 86.
SIMILAR_MIN = 80


def norm(s: str) -> str:
    """Пробіли й м'який перенос («Житомирськог­ о пов.» — шов переносу)."""
    return " ".join(re.sub("­\\s*", "", s or "").split())


def name_key(s: str) -> str:
    """Ключ назви: регістр, апострофи, ё, наголоси геть."""
    s = norm(s).lower()
    for a in ("ʼ", "'", "`"):
        s = s.replace(a, "’")
    return s.replace("ё", "е").replace("́", "").strip(" .,;")


def fold(name: str) -> str:
    """Транслітерований ключ: «Белз» і «Bełz» → belz (той самий, що в паку РК-парафій)."""
    from nyshporka.geog.rkparish import fold as rk_fold
    from nyshporka.utils.translit import normalize_for_matching

    return rk_fold(normalize_for_matching(norm(name))) if name and name.strip() else ""


def is_latin(s: str) -> bool:
    return bool(_LATIN.search((s or "").lower()))


def stem(word: str) -> str:
    w = word.lower().strip(" .,;")
    s = _ADJ_END.sub("", w)
    return s if len(s) >= 3 else w


def narrowed(narrow: str, *fields: str) -> bool:
    """Чи лежить запис у названому повіті/губернії/сотні — за основою слова.

    ЦДІАЛ пише повіт іменником («повіт Кременець»), запит — прикметником
    («Кременецький»): основа «кременецьк» у «кременець» не входить, перші 6 літер — так.
    """
    if not narrow:
        return True
    words = [stem(w) for w in narrow.split() if not w.lower().startswith(("пов", "губ"))]
    hay = " ".join(fields).lower()
    return all(w in hay or (len(w) >= 6 and w[:6] in hay) for w in words if w)


def match(key: str, cand: str) -> str:
    """`exact` | `near` | порожньо.

    `near`: різниця в закінченні («Кропивна» ↔ «Кропивне», «Нападівка» ↔
    «Нападівці») або інше село з тим самим першим словом («Кропивна Нижча») —
    показати з «~», бо відсіяти — рішення людини.
    """
    c = name_key(cand)
    if not c:
        return ""
    if c == key:
        return "exact"
    if len(key) >= 5 and c[:-1] == key[:-1] and abs(len(c) - len(key)) <= 1:
        return "near"
    if " " in c and c.split()[0] == key:
        return "near"
    return ""


def sr_stems(nom: str) -> list[str]:
    """Основи сільради: «Ковалівська» → ковалів; «Крищинецька» → крищине, крищин."""
    k = name_key(nom)
    m = re.match(r"^(.+?)(?:ська|цька|зька)$", k)
    if not m or len(m[1]) < 3:
        return []
    out = [m[1]]
    if m[1].endswith("е") and len(m[1]) > 4:
        out.append(m[1][:-1])
    return out


def sr_variants(key: str) -> list[str]:
    """Основи запиту, з якими порівнюються сільради: «антонівка» → антонівка, антонів."""
    out = [key]
    for suf in ("ка", "ки", "ці", "ичі", "и", "і", "е", "а", "я", "о"):
        if key.endswith(suf) and len(key) - len(suf) >= 3:
            out.append(key[: -len(suf)])
    return list(dict.fromkeys(out))


def name_rows(rec: dict[str, Any]) -> list[tuple[str, str, str, str, str, str, str]]:
    """Рядки таблиці `names` для запису: (назва, вид, ключ, основа, перше слово, fold, pref).

    Вид: `place` (місце й інше написання), `attached` (приписні), `page` (згадане
    на сторінці каталогу), `sr` (основа сільради — уже готовий ключ).
    """
    out = []
    for kind, names in (("place", [rec.get("place") or "", rec.get("place_alt") or ""]),
                        ("attached", rec.get("attached") or []),
                        ("page", rec.get("page_mentions") or []),
                        ("sr", rec.get("sr_keys") or [])):
        for n in names:
            k = name_key(n)
            if not k:
                continue
            f = fold(n)
            out.append((n, kind, k, k[:-1], k.split()[0] if " " in k else "", f, f[:4]))
    return out


def years_span(refs: Iterable[dict[str, Any]]) -> str:
    ys = [int(y) for r in refs for y in YEARS_RE.findall(r.get("years") or "")]
    return f"{min(ys)}–{max(ys)}" if ys else "?"


def compact(refs: Iterable[dict[str, Any]]) -> list[str]:
    """Посилання одного типу: «1860–1891: 35-9-27» — у порядку довідника, без повторів."""
    seen, out = set(), []
    for r in refs:
        key = (r.get("years"), r.get("fond"), r.get("opys"), r.get("spr"))
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{r.get('years') or '?'}: "
                   + "-".join(x for x in (r.get("fond"), r.get("opys"), r.get("spr")) if x))
    return out
