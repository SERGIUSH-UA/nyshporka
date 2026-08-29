r"""Географія справи: вільний текст `place` → село / повіт / губернія + місце канону.

Поле `place` у каталозі складали різні джерела в різні роки, тож воно містить усе
одразу: «м. Ольгопіль Ольгопільського повіту», «Фузовка (Fuzăuca), Оргеївський
пов., Бессарабія», «с. Вербка Дерев'яна, проскурівський пов.», коди `pod.olgopil`,
латинку `slobodo-obodivka, Olgopol, Podolia, Russian Empire` і дослідницькі хвости
(«. Ціль: рід у дірі 1828-1858», «— маєток Ярошинських»). Поки це один рядок,
фільтр «усі справи Ольгопільського повіту» неможливий: «Ольгопільський» не
знаходить ні «Ольгопільського», ні «Olgopol».

🔴 Розбір консервативний: усе, що не впізнане як повіт чи губернія, лишається
населеним пунктом, а `place_raw` не викидається ніколи. Порожній розбір видно як
`?` — мовчазна порожнеча читалася б як «місце невідоме», хоч насправді воно
записане, просто в незнайомій формі.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from nyshporka.utils.translit import normalize_for_matching

#: Хвости, які дослідник дописував до місця: мета пошуку, коментар, застереження.
#: Ріжемо до розбору, інакше «Шиндеровські» стають населеним пунктом.
_TAIL_RE = re.compile(
    r"(?:\.\s*(?:Ціль|Мета|Увага)\s*:.*$)"          # «. Ціль: рід у дірі 1828-1858»
    r"|(?:\s+[—–-]\s+.*$)"                           # «— маєток Ярошинських»
    r"|(?:\(\s*⚠.*?\)\s*)"                           # «(⚠ не Вербка Волоська …)»
    r"|(?:\(\s*=\s*[^)]*\))",                        # «(= с. Городківка з 1946)»
    re.IGNORECASE | re.DOTALL)

#: Повіт: «Ольгопільського повіту», «Оргеївський пов.», «Ольгопольский уезд».
#: ⚠ Порядок альтернатив у хвості має йти від довшої до коротшої: інакше `пов\.?`
#: з'їдає лише «пов» зі слова «повіту», і «іту» лишається жити як назва села.
_UEZD_RE = re.compile(
    r"\b([А-ЯІЇЄҐA-Z][\w'’-]*(?:ськ|цьк|ск)(?:ий|ого|ому|ім|им)?)\s*"
    r"(?:повіт\w*|уезд\w*|пов\.?|у\.)(?![\w])", re.IGNORECASE | re.UNICODE)
#: «Гайсинський і Ольгопільський повіти» — два повіти на одну справу.
_UEZD_PAIR_RE = re.compile(
    r"\b([А-ЯІЇЄҐ][\w'’-]*(?:ськ|цьк)(?:ий|ого)?)\s*(?:і|та|and|,)\s*"
    r"([А-ЯІЇЄҐ][\w'’-]*(?:ськ|цьк)(?:ий|ого)?)\s*повіт\w*", re.IGNORECASE | re.UNICODE)
#: Губернія: «Подільської губернії», «Подільська губ.», «Podolia».
_GUB_RE = re.compile(
    r"\b([А-ЯІЇЄҐA-Z][\w'’-]*(?:ськ|ск)(?:ої|ая|а|ой)?)\s*"
    r"(?:губерні\w*|губерни\w*|губ\.?)(?![\w])", re.IGNORECASE | re.UNICODE)
#: Історичні області, які в наших джерелах стоять на місці губернії.
_REGION_WORDS = {
    "бессарабія": "Бессарабія", "бессарабия": "Бессарабія", "basarabia": "Бессарабія",
    "podolia": "Подільська", "поділля": "Подільська",
}
#: Префікс типу поселення — прибираємо з назви, але тип не втрачаємо.
_SETTLE_PREFIX_RE = re.compile(
    r"^\s*(?:с|м|м-ко|мст|смт|сщ|д|сл|х|обл|г)\.\s*", re.IGNORECASE)
#: Коди-скорочення, якими підписані деякі теки.
_CODES = {
    "pod": (None, None, "Подільська"),
    "pod.olgopil": (None, "Ольгопільський", "Подільська"),
    "pod.balta": (None, "Балтський", "Подільська"),
    "pod.yampil": (None, "Ямпільський", "Подільська"),
}
#: Слова, які ніколи не є назвою поселення.
_STOP_WORDS = {
    "російська імперія", "russian empire", "урср", "ссср", "україна", "молдова",
    "губернія", "повіт", "повіти", "уезд", "маєток", "костел", "церква", "невідомо",
}
_SPLIT_RE = re.compile(r"[,;/]|\s+\+\s+")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().strip(".,;·")).strip()


#: Російські написання повітів, що трапляються в назвах справ. Без зведення
#: «Ольгопольський» стає другим значенням фільтра поруч з «Ольгопільським», і
#: зріз по повіту тихо ділиться навпіл.
#: Ключі — вже в називному з українським суфіксом «-ський» (аліас застосовується
#: після зняття відмінка), різниця лише в корені: «Ольгопольський» ↔ «Ольгопільський».
_UEZD_ALIASES = {
    "ольгопольський": "Ольгопільський", "ямпольський": "Ямпільський",
    "проскуровський": "Проскурівський", "литинський": "Літинський",
    "летичевський": "Летичівський", "могилевський": "Могилівський",
    "каменецький": "Кам'янецький", "винницький": "Вінницький",
    "оргеевський": "Оргеївський",
}
# ⚠ «Бершадський» у аліаси не входить, хоч і виглядає як помилка: сповідка
# 315-1-6671 (1796) прямо зве його «повітом Брацлавським», і це реальна одиниця
# Брацлавського намісництва, скасованого 1797 разом із намісництвом. Звести його
# до Ольгопільського означало б переписати адмінподіл під пізнішу звичку.


def _nominative_uezd(word: str) -> str:
    """«Ольгопільського» → «Ольгопільський», «Ольгопольского» → «Ольгопільський».

    Порядок важливий: спершу знімаємо відмінок, і лише потім зводимо російське
    написання. Інакше аліас не спрацьовує на жодній формі, крім називного, — а в
    назвах справ повіт стоїть майже завжди в родовому («церков Ольгопольського
    повіту»), і фільтр тихо ділиться на два значення того самого повіту.
    """
    w = _clean(word)
    if not w:
        return ""
    low = w.lower()
    for end, repl in (("ського", "ський"), ("цького", "цький"), ("ского", "ський"),
                      ("ському", "ський"), ("ським", "ський"), ("ская", "ський"),
                      ("ский", "ський"), ("ском", "ський"), ("ского", "ський")):
        if low.endswith(end):
            w, low = w[: -len(end)] + repl, low[: -len(end)] + repl
            break
    if low in _UEZD_ALIASES:
        return _UEZD_ALIASES[low]
    # «проскурівський» (дослідник виділив капсом) — зводимо до звичайного вигляду,
    # інакше в фільтрі це окреме значення поруч із «Проскурівський».
    return w.capitalize() if w.isupper() else w[0].upper() + w[1:]


def _nominative_gub(word: str) -> str:
    """«Подільської» → «Подільська»."""
    w = _clean(word)
    if not w:
        return ""
    low = w.lower()
    for end, repl in (("ської", "ська"), ("ской", "ська"), ("ская", "ська"),
                      ("ськой", "ська")):
        if low.endswith(end):
            return w[: -len(end)] + repl
    return w[0].upper() + w[1:]


def _settlement_name(chunk: str) -> str:
    """Кусок тексту → назва поселення (без типу, без дужкової альтернативи)."""
    s = _SETTLE_PREFIX_RE.sub("", _clean(chunk))
    s = re.sub(r"\([^)]*\)", " ", s)          # «Фузовка (Fuzăuca)» → «Фузовка»
    s = _clean(s)
    if not s or s.lower() in _STOP_WORDS or len(s) < 3:
        return ""
    if re.search(r"(?:пов|повіт|губ|уезд)", s, re.IGNORECASE):
        return ""
    if not re.search(r"[А-Яа-яІіЇїЄєҐґA-Za-z]", s):
        return ""
    return s


class ParsedPlace(TypedDict):
    """Форма розібраного місця. Оголошена, бо цей словник ходить далеко.

    Він потрапляє в реєстр справ, у геозріз і в лендінг; там його читають по
    ключах, і хибно названий ключ мовчки дав би порожню географію — тобто
    справу, яку не знайдуть за селом.
    """

    settlements: list[str]
    uezds: list[str]
    guberniya: str
    alt_names: list[str]


def parse_place(raw: str) -> ParsedPlace:
    """Вільний текст → {settlements, uezds, guberniya, alt_names}.

    Порожній результат означає «розібрати не вдалось», а не «місця немає»:
    виклик має лишити `place_raw` і показати це окремо.
    """
    text = _clean(raw)
    out: ParsedPlace = {"settlements": [], "uezds": [], "guberniya": "",
                        "alt_names": []}
    if not text:
        return out
    code = _CODES.get(text.lower())
    if code:
        _, uezd, gub = code
        out["uezds"] = [uezd] if uezd else []
        out["guberniya"] = gub or ""
        return out
    # альтернативні написання в дужках зберігаємо: «Фузовка (Fuzăuca)», «(Miastkówka)»
    for m in re.finditer(r"\(([^)]{3,40})\)", text):
        alt = _clean(m.group(1))
        if alt and not re.search(r"⚠|=|повіт|пов\.|маєток", alt, re.IGNORECASE):
            out["alt_names"].append(alt)
    body = _TAIL_RE.sub(" ", text)
    # Дужкову вставку прибираємо до пошуку повіту — у «Аккерманський (Четатя-Албе)
    # пов.» вона розриває прикметник і слово «пов.». Але саме в дужках повіт часом
    # і стоїть («Слобода-Ободівка (Ольгопільський повіт)»), тож адміністративну
    # вставку розкриваємо, а не викидаємо. Вміст уже збережено як alt_names.
    body = re.sub(r"\(([^)]{3,40})\)",
                  lambda m: (" " + m.group(1) + " "
                             if re.search(r"пов|губ|уезд", m.group(1), re.IGNORECASE)
                             else " "), body)
    # губернія / історична область
    gub = ""
    mg = _GUB_RE.search(body)
    if mg:
        gub = _nominative_gub(mg.group(1))
        body = body[: mg.start()] + " " + body[mg.end():]
    else:
        for word, canon in _REGION_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", body, re.IGNORECASE):
                gub = canon
                body = re.sub(rf"\b{re.escape(word)}\b", " ", body, flags=re.IGNORECASE)
                break
    out["guberniya"] = gub
    # повіти (спершу парні: «Гайсинський і Ольгопільський повіти»)
    uezds: list[str] = []
    mp = _UEZD_PAIR_RE.search(body)
    if mp:
        uezds = [_nominative_uezd(mp.group(1)), _nominative_uezd(mp.group(2))]
        body = body[: mp.start()] + " " + body[mp.end():]
    else:
        for m in list(_UEZD_RE.finditer(body))[::-1]:
            u = _nominative_uezd(m.group(1))
            if u and u not in uezds:
                uezds.insert(0, u)
            body = body[: m.start()] + " " + body[m.end():]
    out["uezds"] = uezds
    # решта — поселення
    seen: set[str] = set()
    for chunk in _SPLIT_RE.split(body):
        name = _settlement_name(chunk)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out["settlements"].append(name)
    return out


#: Губернія за фондом — там, де це властивість самої установи, а не окремої
#: справи. 🔴 Без цього зріз «по Поділлю» недорахував половину: сповідки
#: Подільської духовної консисторії (ДАХмО ф.315) описані переліком сіл, поле
#: місця в них порожнє, і сім із чотирнадцяти прочесаних справ не потрапляли
#: у вибірку по губернії — при тому, що подільські вони за визначенням фонду.
#: Сюди йдуть лише фонди, чия назва прямо називає губернію (звірено з описами
#: й каталогами проєкту), і лише як запасний варіант — розбір тексту сильніший.
# 🏛 Знання про фонди переїхало в пак архівів (`nyshporka.archives`): новий фонд
# додається рядком у YAML, а не правкою коду. Перелік нижче лишається дослівним
# фолбеком і еталоном тесту — на випадок, коли пак не читається.
_LEGACY_FOND_GUBERNIYA = {
    ("DAHMO", "315"): "Подільська",   # Подільська духовна консисторія
    ("DAHMO", "226"): "Подільська",   # Подільська казенна палата
    ("DAHMO", "196"): "Подільська",   # Подільська палата цивільного суду
    ("DAHMO", "230"): "Подільська",   # Подільське дворянське депутатське зібрання
    ("DAVIO", "904"): "Подільська",   # метричні книги Подільської губернії
    ("DAVIO", "792"): "Подільська",   # нотаріат М'ястківки, Ольгопільський пов.
    # ⚠ Давній код того самого архіву — простори, що лишились на ньому, мусять
    # діставати ту саму губернію, інакше зріз по губернії мовчки худне.
    ("DAVO", "904"): "Подільська",
    ("DAVO", "792"): "Подільська",
}


def guberniya_by_fond(repo: str | None, fond: str | None) -> str:
    """Губернія, задана самим фондом. Порожньо, якщо фонд не з відомих."""
    try:
        from nyshporka.archives import active
        return active().guberniya(repo, fond)
    except Exception:
        # Тихо тут можна: порожня губернія лише послаблює зріз, вона нічого не
        # спотворює. Гучний фолбек стоїть там, де ціна — хибний результат.
        return _LEGACY_FOND_GUBERNIYA.get(
            (str(repo or "").upper(), str(fond or "")), "")


#: Поселення в назві справи: «церкви … м-ка М'ястківка», «с. Крутеньке».
#: ⚠ Дефісні форми («м-ка», «м-ко») пишуть без крапки, і альтернативи мають іти
#: від довшої до коротшої — інакше `м` збігається першим і чекає крапку, якої нема.
_TITLE_SETTLE_RE = re.compile(
    r"\b(?:м-ка|м-ко|смт|мст|с|м|сл|д)\.?\s+([А-ЯІЇЄҐA-Z][\w'’ʼ-]{2,}"
    r"(?:\s+[А-ЯІЇЄҐA-Z][\w'’ʼ-]{2,})?)", re.UNICODE)


def settlement_from_title(title: str) -> str:
    """Назва справи → поселення, але лише коли воно там одне.

    🔴 Умова однозначності принципова: «Метрична книга церкви Благовіщення …
    м-ка М'ястківка» називає село прямо, а «Сповідальні відомості церков
    Ольгопільського повіту» перелічує їх десятками — узяти звідти «головне»
    означало б призначити справі село навмання.
    """
    found = {_clean(m.group(1)) for m in _TITLE_SETTLE_RE.finditer(title or "")}
    found = {f for f in found if f and f.lower() not in _STOP_WORDS}
    return next(iter(found)) if len(found) == 1 else ""


@lru_cache(maxsize=1)
def _canon_places() -> list[tuple[str, list[str]]]:
    """[(PL-id, [нормалізовані форми назви])] з канонічних місць.

    🔴 Варіанти обов'язкові: канон зве село сучасним іменем («Городківка»), а справи
    XIX ст. — історичним («М'ястківка», `Miastkówka`). Без `name_variants` головне
    село роду не прив'язалось би до жодної справи.
    """
    try:
        from nyshporka.library import ROOT
        from nyshporka.storage.files import read_place
    except Exception:
        return []
    out: list[tuple[str, list[str]]] = []
    places_dir = ROOT / "data" / "canonical" / "places"
    if not places_dir.is_dir():
        return out
    for md in sorted(places_dir.glob("PL*.md")):
        try:
            pl = read_place(md)
        except Exception:
            continue
        forms = {pl.name, *(pl.name_variants or {}).values()}
        norm = sorted({normalize_for_matching(f) for f in forms if f and len(f) > 2})
        if norm:
            out.append((pl.id, norm))
    return out


#: Поріг прив'язки до канону. Високий свідомо: «Вербка Волоська» і «Вербка
#: Дерев'яна» — різні села у різних повітах, а схожість у них 85+.
_MATCH_MIN = 93


def match_place_id(settlements: list[str]) -> str | None:
    """Перше село справи → id місця канону; None якщо збіг непевний."""
    if not settlements:
        return None
    try:
        from rapidfuzz import fuzz
    except Exception:
        return None
    target = normalize_for_matching(settlements[0])
    if len(target) < 3:
        return None
    best: tuple[int, str | None] = (0, None)
    second = 0
    for pid, forms in _canon_places():
        score = max((int(fuzz.ratio(target, f)) for f in forms), default=0)
        if score > best[0]:
            second = best[0]
            best = (score, pid)
        elif score > second:
            second = score
    if best[0] >= _MATCH_MIN and best[0] - second >= 3:
        return best[1]
    return None


def geo_blob(settlements: list[str], uezds: list[str], guberniya: str,
             alt_names: list[str] | None = None) -> str:
    """Нормалізований рядок для пошуку: кирилиця й латинка зводяться до однієї форми.

    Завдяки цьому `--uezd Olgopol` знаходить «Ольгопільський», а `--settlement
    Miastkowka` — «М'ястківку»: та сама нормалізація, що в matching прізвищ.
    """
    parts = [*(settlements or []), *(uezds or []), *(alt_names or [])]
    if guberniya:
        parts.append(guberniya)
    return " ".join(normalize_for_matching(p) for p in parts if p).strip()
