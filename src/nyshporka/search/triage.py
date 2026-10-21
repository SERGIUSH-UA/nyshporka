"""Відсів кандидатів гортача до кропу: що людині судити, що вже відоме, що не прізвище.

Гортач (`textops.sheet`) показує видачу `find` підряд, і людина судила те, що
закривається контекстом: ім'я дитини в переліку, підпис пароха, якого канон уже
знає, склейку рушія, яку другий голос читає зовсім інакше (замір 21.10.2026: із
17 рядків поза відомим 14 розібрав контекст, вердикт людини знадобився для
трьох). Тут кожна картка дістає розділ:

* `closed` — **не прізвище**, і лише з трьох підстав, які дозволяє методика:
  ім'я в переліку після формули спорідненості, топонім, порожній токен.
  🔴 За коренем чи формою слова не закривається нічого: рушій калічить саме
  середину прізвища, тож «чуже» на вигляд слово буває родом.
* `known` — аркуш уже цитує канон, або він є у сховищі сторінок із цим
  прізвищем, або поруч стоїть ім'я особи канону, вже пов'язаної з цією справою.
  Не закрито: картка згорнута, але з полем вердикту — буває тезко.
* `weak` — другий голос не підтримує прочитання. Лише опускається вниз.
* `None` — на вердикт, як і досі.

Порядок перевірок — від найдешевшої до найдорожчої, і картка бере ПЕРШУ
підставу: закрите не йде в «відоме», відоме — у «слабке».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nyshporka.utils.translit import normalize_archival

CLOSED, KNOWN, WEAK = "closed", "known", "weak"

#: Підпис розділу в гортачі.
LABEL = {
    CLOSED: "закрито: не прізвище",
    KNOWN: "уже відоме",
    WEAK: "слабке: другий голос не підтримує",
}

# Слова — точними нормалізованими (`normalize_archival`) формами, НЕ префіксом:
# префікс із трьох літер ловить прізвища («sin» — Синицкій, «dac» — Дацюкъ,
# «ponomar» — Пономаревъ), а прізвище тут — саме те, що шукаємо.
# Спорідненість, після якої іде перелік ІМЕН: «дѣтей, Томаша, Виктора»,
# «дочери 1 Анна 2. Марія». «жена» сюди свідомо не входить: «жена его Марія
# Х-ская» несе прізвище.
_KIN = frozenset({"sin", "sina", "sinu", "sinom", "sinove", "sinovi", "sinova", "sinovei",
                  "doc", "doceri", "docer", "docerei", "docerou", "doceriu", "docerem",
                  "deti", "detei", "detmi", "detam", "vnuk", "vnuka", "vnuki", "vnukov",
                  "vnucka", "vnucki", "cada", "cad"})
# Подружжя, вдівство, батьки й хресні — для винятку «акт родини» в правилах
# відомого. «zen» префіксом ловив і «женска шесть» (лічба народжених).
_FAMILY = _KIN | frozenset({
    "zena", "zenu", "zeni", "zeny", "zene", "zenou", "zenoi", "zenih",
    "muz", "muza", "muzu", "muzem", "vdova", "vdovy", "vdovec", "vdovica",
    "suprugi", "suprugov", "supruga", "otec", "otca", "otcu", "otcom",
    "roditeli", "roditelei", "roditelam", "vospriemnik", "vospriemnika",
    "vospriemniki", "vospriemnica", "vospriemnicei"})
# Скільки слів перед хітом шукати спорідненість.
_FAMILY_SPAN = 4
# Слово ОДРАЗУ після хіта, що робить його назвою місця.
_TOPO = frozenset({"uezd", "uezda", "uezdu", "povet", "poveta", "povetu", "gub",
                   "gubernii", "gubernia", "volost", "volosti", "okrug", "okruga"})
# Слова й розділювачі: число до двох цифр (з крапкою/дужкою) — номер у переліку;
# довше число (рік, сума) розділювачем не є.
_TOK = re.compile(r"\d+[.)]?|[^\W\d_]+|[,;]", re.UNICODE)
_ID = re.compile(r"\bI\d{3,5}\b")
# Скільки слів після спорідненості ще вважати переліком.
_LIST_SPAN = 8
# Поріг упізнання імені особи канону біля хіта: рушій калічить і ім'я
# («Аданъ», «Адомъ», «Азамъ» — одна літера з чотирьох), тож за однакової
# першої літери досить 75.
THR_GIVEN = 75
# Нижче цього другий голос «не підтримує» стем.
THR_ALT = 70
# Слова причту біля прізвища — ознака підпису під актом. Префіксом — лише
# довгі основи, яких у прізвищах не буває; решта — точними формами.
_CLERGY_PREFIX = ("svasc", "psalom", "prihodsk", "nastoat")
_CLERGY_EXACT = frozenset({"diakon", "diakona", "diakonom", "diakonu", "dacok", "dacka",
                           "dackom", "dacku", "ponomar", "ponomara", "ponomarem",
                           "ponomarom", "ponomaru", "prict", "pricta", "prictom", "prictu",
                           "ierei", "iereem", "iereia", "iereu"})
# Повні форми для нечіткого збігу: рушій калічить і їх («Пеаломщикъ»).
_CLERGY_FULL = ("svascennik", "psalomscik", "prihodskii")
THR_CLERGY = 80


@dataclass
class Known:
    """Що про справу вже відомо: аркуші ока й канону, імена осіб канону в справі."""

    pages: dict[str, str] = field(default_factory=dict)   # основа аркуша → чому відомий
    names: dict[str, str] = field(default_factory=dict)   # нормалізоване ім'я → підпис особи
    tied: list[str] = field(default_factory=list)          # особи канону, пов'язані зі справою


def _norm(s: str) -> str:
    return normalize_archival(s or "")


def _pid(page: str) -> str:
    from pathlib import Path

    return Path(str(page or "")).stem.lower()


def _tokens(text: str, sep: bool = False) -> list[tuple[str, bool]]:
    """Слова рядка з ознакою «перед словом стоїть розділювач переліку».

    `sep` — розділювач, що прийшов з кінця попереднього рядка («Иванъ, ⏎ …»).
    """
    out: list[tuple[str, bool]] = []
    for t in _TOK.findall(text or ""):
        if t in ",;":
            sep = True
            continue
        if t[0].isdigit():
            sep = sep or len(t.rstrip(".)")) <= 2
            continue
        out.append((t, sep))
        sep = False
    return out


def _row_tokens(rows: list[str]) -> tuple[list[tuple[str, bool]], list[int]]:
    """Слова вікна і номер рядка кожного, з переносами без дефіса склеєними.

    Рядок, що починається з малої літери, продовжує слово попереднього, якщо
    той закінчився словом або дефісом: «дѣтей, Томаша, Во ⏎ ктора, Х-инъ» —
    інакше «Во» і «ктора» виглядали двома словами без коми, і перелік імен не
    впізнавався (685-2-891, кадр 0123). Кома в кінці рядка переходить на
    перше слово наступного. Склеєне слово лишається в рядку свого початку.
    """
    toks: list[tuple[str, bool]] = []
    row_of: list[int] = []
    for k, r in enumerate(rows):
        prev = rows[k - 1].rstrip() if k else ""
        got = _tokens(r, sep=prev.endswith((",", ";")))
        ends_word = prev[-1:].isalpha() or prev.endswith("-")
        if (got and toks and row_of[-1] == k - 1 and ends_word and not got[0][1]
                and got[0][0][:1].islower()):
            w, sep = toks[-1]
            toks[-1] = (w + got[0][0], sep)
            got = got[1:]
        toks += got
        row_of += [k] * len(got)
    return toks, row_of


def _find_token(toks: list[tuple[str, bool]], matched: str) -> int:
    """Позиція хіта в словах вікна (з кінця — хіт у рядку, а не в контексті)."""
    want = _norm(matched.strip(" -.,;"))
    if not want:
        return -1
    for i in range(len(toks) - 1, -1, -1):
        w = _norm(toks[i][0])
        # `w.endswith` — хвіст переносу, що склеївся з початком у одне слово.
        if w and (w == want or (len(w) >= 4 and want.startswith(w))
                  or w.startswith(want) or (len(want) >= 4 and w.endswith(want))):
            return i
    return -1


def _empty(matched: str) -> bool:
    """Токен закороткий для прізвища — у НОРМІ, тією ж мірою, що й короткий запит.

    🔴 Сирі літери тут брехали: «Щук» — три літери, а в нормі «scuk» — чотири,
    тож коротким запитом він не вважався, а порожнім токеном — так, і точний
    збіг із запитом ішов у «закрито» (рецензія 22.10.2026).
    """
    return len(_norm(re.sub(r"[^\w]|\d|_", "", matched or ""))) <= 3


def _kin_list(toks: list[tuple[str, bool]], i: int) -> str:
    """Хіт стоїть у переліку імен після слова спорідненості — повертає це слово.

    Перелік — коли КОЖЕН пункт від спорідненості до хіта, і сам хіт, відділено
    комою чи номером, і пунктів перед хітом хоч один. «сынъ Иванъ, Х-скій»
    сюди не потрапляє: перед «Иванъ» розділювача немає — це ім'я з прізвищем.
    """
    if i <= 0 or not toks[i][1]:
        return ""
    for j in range(i - 1, max(-1, i - 1 - _LIST_SPAN), -1):
        if _norm(toks[j][0]) in _KIN:
            return toks[j][0] if i - 1 - j >= 1 else ""
        if not toks[j][1]:
            return ""
    return ""


def _toponym(toks: list[tuple[str, bool]], row_of: list[int], i: int) -> str:
    """Слово «уѣзда / губерніи» ОДРАЗУ після хіта, у тому самому рядку.

    🔴 Лише наступне слово: «Адамъ Х-скій Балтскаго уѣзда» — прізвище з місцем
    проживання. І через межу рядка не дивитись: «Псаломщикъ Ѳеодоръ Х-скій ⏎
    Бессарабской Губерніи …» — підпис, а наступний рядок уже інший запис
    (перший прогін закрив так 27 підписів псаломщика роду, Каїри 1892).
    """
    j = i + 1
    if j < len(toks) and row_of[j] == row_of[i] and _norm(toks[j][0]) in _TOPO:
        return toks[j][0]
    return ""


def _before_hit(toks: list[tuple[str, bool]], row_of: list[int], i: int) -> list[str]:
    """Слова безпосередньо перед хітом: до 4 у його рядку, а коли хіт починає
    рядок — 3 останні попереднього («сынъ псаломщика Ѳеодора ⏎ Х-скаго»).

    🔴 Не ширше: рядок декоду таблиці змішує графи, і «Макаренка жена» з графи
    батьків стоїть поруч із підписом пароха в графі причту.
    """
    if i < 0:
        i = len(toks)
    k = row_of[i] if i < len(row_of) else (row_of[-1] + 1 if row_of else 0)
    same = [toks[j][0] for j in range(max(0, i - _FAMILY_SPAN), i) if row_of[j] == k]
    if same:
        return same
    prev = [toks[j][0] for j in range(i) if row_of[j] == k - 1]
    return prev[-3:]


def _around_hit(toks: list[tuple[str, bool]], row_of: list[int], i: int) -> list[str]:
    """Слова біля хіта для імені відомої особи: ±3 у рядку хіта й 3 останні
    попереднього (підпис колонкою: «Священникъ Адамъ ⏎ Х-скій»). Хіт серед слів
    не знайдено — порожньо: судити нема з чого."""
    if i < 0:
        return []
    k = row_of[i]
    near = [toks[j][0] for j in range(max(0, i - 3), min(len(toks), i + 4))
            if row_of[j] == k and j != i]
    prev = [toks[j][0] for j in range(i) if row_of[j] == k - 1]
    return near + prev[-3:]


def _clergy(words: list[str]) -> str:
    """Перше слово причту серед слів вікна (сирим написанням) або порожньо."""
    from rapidfuzz import fuzz

    for w in words:
        nw = _norm(w)
        if len(nw) < 3:
            continue
        if nw.startswith(_CLERGY_PREFIX) or nw in _CLERGY_EXACT or any(
                fuzz.ratio(nw[:len(f)], f) >= THR_CLERGY
                for f in _CLERGY_FULL if len(nw) >= len(f) - 2):
            return w
    return ""


def _alt_supports(alt: str, stems: list[str]) -> bool:
    from rapidfuzz import fuzz

    words = [_norm(w) for w, _ in _tokens(alt)]
    words = [w for w in words if len(w) >= 3]
    for s in stems:
        ns = _norm(s)
        if len(ns) < 3:
            continue
        for w in words:
            if fuzz.partial_ratio(ns, w) >= THR_ALT or fuzz.partial_ratio(w, ns) >= THR_ALT:
                return True
    return False


def classify(card: dict[str, Any], known: Known, stems: list[str]) -> tuple[str, str] | None:
    """Розділ і причина для однієї картки; `None` — на вердикт."""
    from rapidfuzz import fuzz

    matched = str(card.get("matched") or "")
    # Коротке прізвище запиту («Рак», «Бут») саме дає короткий токен; тоді
    # порожнім вважається лише токен без жодної літери.
    short_q = any(0 < len(_norm(x)) <= 3 for x in stems[:1])
    # Сам запит (у нормі) не закривається ніколи: закривати можна лише те, що
    # не є прізвищем.
    is_query = bool(matched) and _norm(matched) in {_norm(x) for x in stems}
    if (_empty(matched) and not is_query
            and (not short_q or not re.search(r"[^\W\d_]", matched))):
        return CLOSED, f"порожній токен «{matched}»"
    before = [str(x) for x in (card.get("before") or [])][-2:]
    after = [str(x) for x in (card.get("after") or [])][:2]
    line = str(card.get("text") or "")
    # 🔴 Межа рядка — НЕ розділювач: «дочь Марія ⏎ Х-ская» — ім'я з прізвищем,
    # перенесене на новий рядок. Номер переліку («2. Х-на») розділює сам.
    toks, row_of = _row_tokens([*before, line])
    i = _find_token(toks, matched)
    if i >= 0:
        kin = _kin_list(toks, i)
        if kin:
            return CLOSED, f"ім'я в переліку після «{kin}»"
        topo = _toponym(toks, row_of, i)
        if topo:
            return CLOSED, f"топонім: далі «{topo}»"

    # 🔴 Спорідненість біля хіта — це акт ЧИЄЇСЬ родини («сынъ псаломщика
    # Ѳеодора Х-скаго», «сынъ Адамъ Х-скій»): він іде людині, навіть коли аркуш
    # уже відомий, поруч ім'я відомої особи чи слова причту. Відомий аркуш
    # (у сховищі сторінок — `partial`) не означає, що відомі всі люди на ньому.
    family = any(_norm(w) in _FAMILY for w in _before_hit(toks, row_of, i))
    if not family:
        pid = _pid(str(card.get("page") or ""))
        if pid in known.pages:
            return KNOWN, known.pages[pid]
        for w in _around_hit(toks, row_of, i):
            nw = _norm(w)
            if len(nw) < 3:
                continue
            for name, who in known.names.items():
                if nw[0] == name[0] and fuzz.ratio(nw, name) >= THR_GIVEN:
                    return KNOWN, (f"поруч «{w}» — {who}, уже пов'язаний із цією справою; "
                                   f"перевірте, чи не тезко")
        if known.tied:
            window = toks + _tokens(" ".join(after))
            cw = _clergy([w for w, _ in window])
            if cw:
                return KNOWN, (f"підпис причту (поруч «{cw}»), у справі вже відомі: "
                               f"{', '.join(known.tied[:3])}; перевірте, чи не тезко")

    alt = str(card.get("alt") or "")
    # 🔴 Другий голос судиться лише там, де прізвище стоїть у САМОМУ рядку хіта.
    # Склейка через рядок («Х-скій ⏎ Стоматовскій») показує наступний рядок, і
    # його другий голос прізвища «не підтримує» просто тому, що його там немає.
    probe = stems or [matched]
    if alt and _alt_supports(line, probe) and not _alt_supports(alt, probe):
        return WEAK, f"другий голос читає інше: «{alt[:80]}»"
    return None


def known_for(q: str, case_key: str) -> Known:
    """Відоме про справу: аркуші канону й ока, імена осіб канону в справі.

    Особа «пов'язана зі справою», коли її ID стоїть у коментарі аркуша цієї
    справи у сховищі сторінок, або канон цитує для неї аркуш цієї справи.
    Помилка будь-якого джерела — порожньо з нього, а не падіння гортача.
    """
    import contextlib

    got = Known()
    if not case_key:
        return got
    try:
        from nyshporka.pagestore import query as PQ
        from nyshporka.pagestore import store as PS
        from nyshporka.search import selfcheck as SC
    except Exception:
        return got
    ref = None
    with contextlib.suppress(Exception):
        ref = PS.resolve_case(case_key)
    ids: set[str] = set()
    with contextlib.suppress(Exception):
        for h in PQ.grep_surnames(q, case_key=case_key)["hits"] or []:
            scan = _pid(str(h.get("scan") or ""))
            if scan:
                got.pages.setdefault(scan, "аркуш уже у сховищі сторінок із цим прізвищем: "
                                           + (str(h.get("comment") or "")[:120] or "без коментаря"))
            ids |= set(_ID.findall(str(h.get("comment") or "")))
    if ref is None:
        return got
    with contextlib.suppress(Exception):
        for scan in SC.canon_pages(q, ref):
            got.pages[scan] = ("аркуш цитує канон; інша людина роду на тому самому аркуші "
                               "можлива — перевірте, чи це той самий запис")
    with contextlib.suppress(Exception):
        from nyshporka.core.workspace import workspace
        from nyshporka.records.names import expand_given

        root = workspace().canonical
        case_dir = SC._norm_path(str(getattr(ref, "path", "") or ""))
        for person in SC._persons_named(root, _norm(q), 80):
            pid = str(getattr(person, "id", "") or "")
            tied = pid in ids or any(
                _cites_case(root, c.source_id, case_dir, SC)
                for f in person.facts for c in f.citations)
            if not tied:
                continue
            g0 = next((str(getattr(nm, "given", "") or "") for nm in person.names
                       if getattr(nm, "given", None)), "")
            got.tied.append(f"{g0} {pid}".strip())
            for nm in person.names:
                g = str(getattr(nm, "given", "") or "")
                for form in expand_given(g) if g else []:
                    if len(form) >= 3:
                        got.names.setdefault(form, f"{g} {pid}".strip())
    return got


def _cites_case(root: Any, sid: str, case_dir: str, SC: Any) -> bool:
    if not case_dir:
        return False
    from nyshporka.storage.files import read_source

    p = root / "sources" / f"{sid}.md"
    if not p.is_file():
        return False
    try:
        src = read_source(p)
    except Exception:
        return False
    return bool(src.raw_path) and SC._norm_path(str(src.raw_path)) == case_dir


def triage(cards: list[dict[str, Any]], q: str, case_key: str, stems: list[str],
           known: Known | None = None) -> dict[str, int]:
    """Проставити кожній картці `triage` = {code, why} або None; повернути лічильники."""
    kn = known if known is not None else known_for(q, case_key)
    counts = {CLOSED: 0, KNOWN: 0, WEAK: 0}
    for c in cards:
        got = classify(c, kn, stems)
        c["triage"] = {"code": got[0], "why": got[1]} if got else None
        if got:
            counts[got[0]] += 1
    return counts
