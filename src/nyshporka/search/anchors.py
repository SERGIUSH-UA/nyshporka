"""⚓ Якірний канал: рід шукається не прізвищем, а іменами.

🔴 **Навіщо.** Рушій калічить довге прізвище сильніше, ніж коротке формулярне
слово. Замір, який це купив (він же стоїть у `htr.runner.rescue_pick`): обидва
золоті рятунки мали в Писаря по прізвищу бал **нуль** — мовна модель підставила
правдоподібне чуже слово, — а по батькові той самий рушій прочитав **дослівно**.
Тобто прізвищний канал там не «трохи не дотягнув», його там не було зовсім.

🔴 **Пара обов'язкова, одинак не рахується.** «Іосифовъ» стоїть у метриці на
кожному аркуші; сам по собі він не ознака. Ознакою є ім'я ПЛЮС по батькові
поруч — у межах кількох токенів одного рядка.

🔴 **Якір прив'язується до ЧАСУ, і це головне правило каналу.** Ім'я корисне,
поки людина жива; по батькові — поки живі її діти, тобто воно переживає носія
на покоління. Без прив'язки до років якір вироджувався до чверті всіх рядків
книги — тобто вимикав сам себе.

⚠ Чого тут свідомо НЕМАЄ, на відміну від приватного конвеєра: відсіву сучасних
написань. Там він заразом відрізав **усю латинку**, тож для польської чи
румунської справи канал був німий за побудовою. Нишпорка читає латинку окремим
рушієм, і глушити її тут означало б зламати те, заради чого той рушій є.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nyshporka.records.names import norm_given, norm_patronymic
from nyshporka.utils.translit import normalize_archival

#: Скільки років по батькові лишається корисним після народження носія: від
#: повноліття (діти починають з'являтися в актах) до згасання покоління.
PATR_FROM, PATR_TO = 18, 100
#: Скільки живе людина, якщо дати смерті ми не знаємо. Явна константа, а не
#: мовчазне припущення: вона визначає, чи потрапить ім'я у вікно справи.
ASSUMED_LIFE = 85

#: Пороги збігу. Окремими іменами, хоч зараз і рівні: ім'я та по батькові
#: калічаться по-різному, і колись їх доведеться розвести.
THR_GIVEN = 82.0
THR_PATR = 82.0
#: Скільки токенів дозволено між іменем і по батькові.
WIN = 3
#: Коротший токен не порівнюється: «Анна» це рівно чотири нормалізовані літери.
MIN_TOK = 4

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Person:
    """Людина роду як джерело якорів."""

    given: str = ""
    patronymic: str = ""
    born: int | None = None
    died: int | None = None

    @property
    def dated(self) -> bool:
        return self.born is not None or self.died is not None


@dataclass(frozen=True)
class Keys:
    """Якорі, звужені під роки справи, і чесний облік того, що відпало."""

    given: tuple[str, ...] = ()
    patronymic: tuple[str, ...] = ()
    #: Скільки осіб профілю не мають жодної дати — вони вікно не звужують.
    undated: int = 0
    #: Скільки осіб узагалі розглянуто.
    people: int = 0
    #: Вікно, під яке звужували; порожнє — років справи не знайшли.
    years: tuple[int, int] | None = None

    @property
    def empty(self) -> bool:
        return not self.given or not self.patronymic


EMPTY = Keys()


def people(prof: Any = None) -> list[Person]:
    """Люди роду з профілю простору, доповнені каноном, якщо він є.

    🔴 Профіль головний, і це не смак. Пакет сам про себе каже, що для
    більшості просторів канону не існує взагалі — його збирає дослідницький
    конвеєр. Канон-первинний канал повторив би помилку полів, які профіль
    оголошує, а пошук не читає: механізм є, даних під нього немає.

    ⚠ Профіль перекриває канон за іменем: те, що дослідник виписав руками, він
    виписав, подивившись на документ.
    """
    if prof is None:
        try:
            from nyshporka.core.profile import active

            prof = active()
        except Exception:
            prof = None
    # 🔴 Ключ — ПАРА ім'я + по батькові. У роді імена повторюються через
    # покоління («Іван Федорович» і «Іван Петрович»), і ключ за самим іменем
    # зливав їх в одну особу: по батькові другого разом із його вікном років
    # зникало з якорів (рецензія 08.09, третій раунд).
    out: dict[tuple[str, str], Person] = {}
    for p in _from_canon():
        out.setdefault(_person_key(p), p)
    for p in _from_profile(prof):
        out[_person_key(p)] = p
    return [p for p in out.values() if p.given or p.patronymic]


def _person_key(p: Person) -> tuple[str, str]:
    return (norm_given(p.given) or p.given.lower(),
            norm_patronymic(p.patronymic) or p.patronymic.lower())


def _from_profile(prof: Any) -> list[Person]:
    out: list[Person] = []
    for raw in (getattr(prof, "kin", ()) or ()):
        if not isinstance(raw, dict):
            continue
        out.append(Person(given=str(raw.get("given") or ""),
                          patronymic=str(raw.get("patronymic") or ""),
                          born=_int(raw.get("born")),
                          died=_int(raw.get("died"))))
    return out


def _from_canon() -> list[Person]:
    """Особи канону, якщо він у цьому просторі є. Немає — порожньо, не помилка.

    ⚠ По батькові беремо розбором рядка імені (`split_name`): у канонічній
    моделі окремого поля патроніма немає, і заводити його заради цього каналу
    означало б міграцію всіх наявних карток.
    """
    try:
        from nyshporka.core.workspace import workspace
        from nyshporka.records.names import split_name
        from nyshporka.storage.files import read_person

        root = workspace().canonical / "persons"
        if not root.is_dir():
            return []
        subs = _surname_substrings()
        out: list[Person] = []
        for path in sorted(root.glob("*.md")):
            try:
                person = read_person(path)
            except Exception:
                continue
            form = ""
            for nm in person.names:
                if nm.form:
                    form = nm.form
                    break
            given, patr, _ = split_name(form)
            out.append(Person(given=_clean_anchor(given, subs),
                              patronymic=_clean_anchor(patr, subs),
                              born=_life(person, "birt"),
                              died=_life(person, "deat")))
        return out
    except Exception:
        return []


def _surname_substrings() -> tuple[str, ...]:
    """Підрядки прізвища роду з профілю — щоб воно не стало «по батькові»."""
    try:
        from nyshporka.core.profile import active

        return tuple(normalize_archival(s) for s in (active().substrings or ()) if s)
    except Exception:
        return ()


def _clean_anchor(tok: str, subs: tuple[str, ...]) -> str:
    """Якір — лише слово з літер, і не прізвище роду.

    🔴 `split_name` бере по батькові розбором рядка, і на картці, де прізвище
    стоїть не останнім, ним ставало саме прізвище: канал якорів тоді шукав
    прізвище під виглядом по батькові й підтверджував сам себе. Так само
    відпадають обрізки на кшталт «митроп.» — крапка в якорі не буває.
    """
    s = (tok or "").strip()
    # Апостроф і дефіс усередині слова законні: «В'ячеслав», «Лук'янович»,
    # «Марія-Анна». Крапка й цифри — ні: «митроп.» якорем не буває.
    if not s or not re.fullmatch(r"[^\W\d_]+(?:['’ʼ-][^\W\d_]+)*", s):
        return ""
    n = normalize_archival(s)
    if any(sub and sub in n for sub in subs):
        return ""
    return s


def _life(person: Any, kind: str) -> int | None:
    for f in getattr(person, "facts", ()) or ():
        if str(getattr(f, "type", "")).startswith(kind):
            date = getattr(f, "date", None)
            got = re.search(r"(1[5-9]\d\d|20\d\d)", str(getattr(date, "value", "")))
            if got:
                return int(got.group(1))
    return None


def _int(v: Any) -> int | None:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def keys(y1: int | None = None, y2: int | None = None, *,
         any_date: bool = False, prof: Any = None) -> Keys:
    """Якорі під вікно років справи.

    🔴 Особа без дати вікно НЕ звужує, і за замовчуванням у якорі не йде. Це
    куплено заміром: без прив'язки до років канал вироджувався до чверті рядків
    книги, тобто переставав відрізняти що-небудь. `any_date=True` бере всіх —
    але тоді про це сказано вголос, а не мовчки.

    ⚠ Років справи може не бути. Тоді звужувати нема чим, і беруться всі — але
    це стан «не знаємо», а не «підходять усі», і він теж їде у відповідь.
    """
    folk = people(prof)
    given: set[str] = set()
    patr: set[str] = set()
    undated = 0
    for p in folk:
        if not p.dated:
            undated += 1
            if not any_date:
                continue
        g = norm_given(p.given)
        if len(g) >= MIN_TOK and _alive(p, y1, y2):
            given.add(g)
        pt = norm_patronymic(p.patronymic)
        if len(pt) >= MIN_TOK and _patr_window(p, y1, y2):
            patr.add(pt)
    win = (y1, y2) if y1 is not None and y2 is not None else None
    return Keys(given=tuple(sorted(given)), patronymic=tuple(sorted(patr)),
                undated=undated, people=len(folk), years=win)


def _alive(p: Person, y1: int | None, y2: int | None) -> bool:
    """Ім'я корисне, поки людина жива."""
    if y1 is None or y2 is None or not p.dated:
        return True
    if p.born is not None:
        end = p.died if p.died is not None else p.born + ASSUMED_LIFE
        return p.born <= y2 and end >= y1
    death = p.died
    return death is not None and death >= y1 and death - ASSUMED_LIFE <= y2


def _patr_window(p: Person, y1: int | None, y2: int | None) -> bool:
    """По батькові корисне, поки живі ДІТИ носія — воно переживає його.

    ⚠ Особа, від якої відома лише дата смерті, по батькові не дає взагалі: без
    року народження вікно `[нар+18 … нар+100]` не будується, а вгадувати його
    означало б розтягнути якір мовчки.
    """
    if y1 is None or y2 is None or not p.dated:
        return True
    if p.born is None:
        return False
    return p.born + PATR_FROM <= y2 and p.born + PATR_TO >= y1


def scan(line: str, k: Keys) -> tuple[str, str] | None:
    """Пара «ім'я + по батькові» в рядку, або нічого.

    🔴 Заборона self-match лише на БУКВАЛЬНО однакових токенах. Ширший фаззі
    тут зрізав добір еталонних аркушів на третину: «Григорій Григоріевъ» і
    «Іосифъ Іосифовъ» — законні пари, а не подвоєне рушієм слово.

    🔴 Нормалізуються ОБИДВІ сторони, і саме тим кодом, що зводить особи
    (`norm_given` / `norm_patronymic`). Спершу тут порівнювався сирий токен із
    канонічною основою — і пара розсипалась на рівному місці: ключ «Ѳеодоровъ»
    зводиться до `fedor`, а токен лишається `feodorov`, тобто 76.9 при порозі
    82. Ознака була в даних, а канал її не бачив.

    ⚠ Побічний виграш: гніздо написань імені працює й тут, тож «Явдоха» в
    профілі ловить «Євдокію» в тексті без окремого правила.
    """
    from rapidfuzz import fuzz

    if k.empty:
        return None
    toks = [_tok(t) for t in _TOKEN.findall(line) if len(t) >= MIN_TOK]
    for i, (t, g, _p) in enumerate(toks):
        if _best(fuzz, g, k.given) < THR_GIVEN:
            continue
        for nxt, _g2, p2 in toks[i + 1:i + 1 + WIN]:
            if nxt == t:
                continue
            if _best(fuzz, p2, k.patronymic) >= THR_PATR:
                return t, nxt
    return None


def scan_many(lines: list[str], k: Keys) -> list[tuple[int, str, str]]:
    """Те саме, що `scan` по кожному рядку, але гуртом: (індекс рядка, ім'я, по батькові).

    🔴 Ті самі правила, що в `scan` (той самий розбір на токени, ті самі пороги,
    та сама заборона буквального self-match); різниця лише в ціні: бал до пулу
    рахується один раз на РІЗНИЙ токен, а не на кожен рядок. Справа на 40 тис.
    рядків коштувала каналу 7.6 с із 15 (рецензія 08.09, третій раунд).
    """
    from rapidfuzz import fuzz

    if k.empty or not lines:
        return []
    per_line = [[t for t in _TOKEN.findall(ln) if len(t) >= MIN_TOK] for ln in lines]
    norms = {t: _tok(t) for ts in per_line for t in ts}
    given_ok = _pool_hits(fuzz, sorted({g for _n, g, _p in norms.values()}), k.given, THR_GIVEN)
    patr_ok = _pool_hits(fuzz, sorted({p for _n, _g, p in norms.values()}), k.patronymic, THR_PATR)
    out: list[tuple[int, str, str]] = []
    for i, ts in enumerate(per_line):
        for j, t in enumerate(ts):
            if norms[t][1] not in given_ok:
                continue
            for nxt in ts[j + 1:j + 1 + WIN]:
                if norms[nxt][0] != norms[t][0] and norms[nxt][2] in patr_ok:
                    out.append((i, norms[t][0], norms[nxt][0]))
                    break
            else:
                continue
            break
    return out


def _pool_hits(fuzz: Any, cands: list[str], pool: tuple[str, ...], thr: float) -> set[str]:
    """Кандидати, чий найкращий бал до пулу не нижчий за поріг — як `_best`."""
    if not cands or not pool:
        return set()
    try:
        import numpy as np
        from rapidfuzz.process import cdist
    except ImportError:
        return {c for c in cands if _best(fuzz, c, pool) >= thr}
    m = cdist(cands, list(pool), scorer=fuzz.ratio, dtype=np.float32, workers=-1)
    lc = np.fromiter((len(c) for c in cands), dtype=np.int32, count=len(cands))
    lp = np.fromiter((len(p) for p in pool), dtype=np.int32, count=len(pool))
    # той самий відсів за довжиною, що в `_best`: різниця понад 4 літери — не пара
    m[np.abs(lc[:, None] - lp[None, :]) > 4] = 0
    best = m.max(axis=1)
    return {c for i, c in enumerate(cands) if float(best[i]) >= thr}


#: Пам'ять на токен і на пару «токен × пул». Справа — сорок тисяч рядків і
#: півтора мільйона токенів, з яких різних — десята частина; без пам'яті канал
#: коштував 20 із 27 с пошуку по справі (замір 08.09).
_TOK_MEMO: dict[str, tuple[str, str, str]] = {}
_BEST_MEMO: dict[tuple[str, tuple[str, ...]], float] = {}
_MEMO_CAP = 400_000


def _tok(raw: str) -> tuple[str, str, str]:
    got = _TOK_MEMO.get(raw)
    if got is None:
        n = normalize_archival(raw)
        got = (n, norm_given(n), norm_patronymic(n))
        if len(_TOK_MEMO) < _MEMO_CAP:
            _TOK_MEMO[raw] = got
    return got


def _best(fuzz: Any, tok: str, pool: tuple[str, ...]) -> float:
    """Найкращий бал із попереднім відсівом за довжиною — він дешевший за фаззі."""
    key = (tok, pool)
    got = _BEST_MEMO.get(key)
    if got is not None:
        return got
    best = 0.0
    for want in pool:
        if abs(len(tok) - len(want)) > 4:
            continue
        best = max(best, float(fuzz.ratio(tok, want)))
    if len(_BEST_MEMO) < _MEMO_CAP:
        _BEST_MEMO[key] = best
    return best
