"""⛪ База Шади ~1772: розбір дампу ArcGIS і словники її кодів.

Bogumił Szady (KUL) звів у одну геобазу два друковані реєстри церков Речі
Посполитої напередодні поділів: Kołbuk «Kościoły wschodnie w Rzeczypospolitej
około 1772 roku» (1998) і Radwan «Socjografia Kościoła greckokatolickiego na
Bracławszczyźnie i Kijowszczyźnie w 1782 roku» (2004). На кожну церкву стоїть
сторінка джерела, деканат, присвята й патронат — тобто рівно те, чого немає в
жодному архівному описі: **чи була в селі церква до 1793 і чия вона була**.

Цей модуль не ходить у мережу: він читає збережений дамп шарів FeatureServer
(`{"unickie": [feature, …], "prawoslawne": […]}` або просто перелік feature'ів)
і віддає плоскі рядки для пака `churches`.

🔴 Словники нижче — переклад **кодів** бази, а не тлумачення джерела. Код,
якого в словнику немає, віддається як є, а не найближчим схожим: «майже та
присвята» гірша за польське скорочення, бо саме присвятою звіряють, чи це та
церква (Липовеньке: «Успіння» в базі проти «Uspienia Świętey Anny» у візитації
1784 — уже цим рядком видно, що база скорочує).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

#: Код воєводства (`pal_name`) → назва. Лише певні; решта лишається кодом.
VOIVODESHIPS: dict[str, str] = {
    "brac": "Брацлавське", "kij": "Київське", "pod": "Подільське",
    "rus": "Руське", "woł": "Волинське", "beł": "Белзьке",
    "kr": "Краківське", "podl": "Підляське", "lub": "Люблінське",
    "maz": "Мазовецьке",
}

#: Патронат (`patronage`): чиє право подання на парафію.
PATRONAGE: dict[str, str] = {
    "s": "шляхетський", "k": "королівський", "d": "духовний",
    "mk": "міський", "bracki": "братський",
}

MATERIAL: dict[str, str] = {
    "dr": "дерев'яна", "mr": "мурована", "dr-mr": "дерев'яна і мурована",
}

#: Присвята: код бази → українська форма. Ключ — нижній регістр без крапки в
#: кінці й зі стиснутими пробілами (див. `_title_key`). Кілька написань одного
#: коду (описки самої бази) ведуть до одного значення.
TITLES: dict[str, str] = {
    # Богородичні
    "opnmp": "Покрови Пресвятої Богородиці",
    "narnmp": "Різдва Пресвятої Богородиці",
    "wnnmp": "Успіння Пресвятої Богородиці",
    "zaśnnmp": "Успіння Пресвятої Богородиці",
    "ofnmp": "Введення в храм Пресвятої Богородиці",
    "zwnmp": "Благовіщення Пресвятої Богородиці",
    "sobór nmp": "Собору Пресвятої Богородиці",
    'sobór nmp ("pochwała nmp")': "Похвали Пресвятої Богородиці",
    "npnmp": "Непорочного Зачаття Пресвятої Богородиці",
    "złszatnmp": "Положення ризи Пресвятої Богородиці",
    "ocznmp": "Стрітення Господнього (Очищення Богородиці)",
    "nawnmp": "Відвідин Пресвятої Богородиці",
    "nmp": "Пресвятої Богородиці",
    "ucieczka do egiptu nmp": "Втечі в Єгипет Пресвятої Богородиці",
    "ucieczki do egiptu nmp": "Втечі в Єгипет Пресвятої Богородиці",
    "różańcowa nmp": "Богородиці Вервиці",
    "bolesna nmp": "Скорботної Богородиці",
    "nmp kazańska": "Казанської ікони Богородиці",
    # Господські
    "ppańskie": "Преображення Господнього",
    "zmpańskie": "Воскресіння Господнього",
    "wnpańskie": "Вознесіння Господнього",
    "wnpńskie": "Вознесіння Господнього",
    "narpańskie": "Різдва Христового",
    "objpańskie": "Богоявлення Господнього",
    "spotkanie pańskie": "Стрітення Господнього",
    "wjazd pański do jerozolimy": "Входу Господнього в Єрусалим",
    "pkrzyża św": "Воздвиження Чесного Хреста",
    "św. krzyż": "Святого Хреста",
    "św. trójca": "Пресвятої Трійці",
    "zducha św": "Зіслання Святого Духа",
    "św. duch": "Святого Духа",
    "św duch": "Святого Духа",
    "duch św": "Святого Духа",
    "podwyższenie św. ducha": "Святого Духа",
    "boże ciało": "Тіла Христового",
    "wszyscy św": "Всіх Святих",
    # Ангели
    "michał a": "Архангела Михаїла",
    "sobór michała a": "Собору Архангела Михаїла",
    "cuda michała a": "Чуда Архангела Михаїла",
    # Іоан Хреститель
    "jan ch": "Іоана Хрестителя",
    "sobór jana ch": "Собору Іоана Хрестителя",
    "narjana ch": "Різдва Іоана Хрестителя",
    "ścięcie głowy jana ch": "Усікновення глави Іоана Хрестителя",
    "ścięgie głowy jana ch": "Усікновення глави Іоана Хрестителя",
    "poczęcie jana ch": "Зачаття Іоана Хрестителя",
    # апостоли, євангелісти
    "jan ew": "Іоана Богослова",
    "łukasz ew": "Євангеліста Луки",
    "marek ew": "Євангеліста Марка",
    "piotr i paweł aap": "Апостолів Петра і Павла",
    "andrzej ap": "Апостола Андрія",
    "jakub ap": "Апостола Якова",
    "filip ap": "Апостола Пилипа",
    "tomasz ap": "Апостола Фоми",
    "mateusz ap": "Апостола Матвія",
    "sobór 70 świętych apostołów": "Собору сімдесяти апостолів",
    # святителі
    "mikołaj bp": "Святителя Миколая",
    "przeniesienie relikwii mikołaja bpa": "Перенесення мощей святителя Миколая",
    "przeniesienie relikwi mikołaja bpa": "Перенесення мощей святителя Миколая",
    "przeniesienia relikwii mikołaja bpa": "Перенесення мощей святителя Миколая",
    "przeniesienie relikwii mikołaja bp": "Перенесення мощей святителя Миколая",
    "bazyli w": "Василія Великого",
    "bazyli wielki": "Василія Великого",
    "jan chryzostom": "Іоана Золотоустого",
    "jan jał": "Іоана Милостивого",
    "trzej święci patriarchowie": "Трьох Святителів",
    "trzej patriarchowie": "Трьох Святителів",
    "trzech świętych patriarchów": "Трьох Святителів",
    "sawa bp": "Святителя Сави",
    "ignacy antiocheński": "Ігнатія Богоносця",
    "ignacy bpm": "Ігнатія Богоносця",
    "nicetas patriarcha": "Микити",
    "jan n": "Іоана Непомука",
    "jozafat kuncewicz": "Йосафата Кунцевича",
    "jozafat": "Йосафата Кунцевича",
    # мученики
    "prakseda pm": "Преподобномучениці Параскеви",
    "prakseda om": "Преподобномучениці Параскеви",
    "prakseda tyrnowska": "Параскеви Тирновської",
    "prakseda trnawska": "Параскеви Тирновської",
    "prakseda trnowska": "Параскеви Тирновської",
    "demetriusz m": "Великомученика Димитрія",
    "demetriusz pm": "Великомученика Димитрія",
    "demetriusz mm": "Великомученика Димитрія",
    "demteriusz m": "Великомученика Димитрія",
    "demeriusz m": "Великомученика Димитрія",
    "dematriusz m": "Великомученика Димитрія",
    "jerzy m": "Великомученика Георгія (Юрія)",
    "kosma i damian mm": "Безсрібників Косми і Дам'яна",
    "kosma i daman mm": "Безсрібників Косми і Дам'яна",
    "barbara pm": "Великомучениці Варвари",
    "barbara m": "Великомучениці Варвари",
    "roman i dawid mm": "Романа і Давида (Бориса і Гліба)",
    "borys i gleb mm": "Бориса і Гліба",
    "przeniesienie relikwi romana i dawida mm": "Перенесення мощей Бориса і Гліба",
    "eustachy m": "Євстафія Плакиди",
    "pantaleon m": "Великомученика Пантелеймона",
    "stefan a": "Первомученика Стефана",
    "stefan archidiakon": "Первомученика Стефана",
    "eufemia m": "Євфимії",
    "tekla pm": "Первомучениці Теклі",
    "40 mm": "Сорока мучеників Севастійських",
    "ławrencjusz m": "Лаврентія",
    "męczennicy machabeusze": "Мучеників Маккавеїв",
    "teodor": "Феодора Тирона",
    "teodor tyron": "Феодора Тирона",
    # преподобні, пророки, праведні
    "eliasz pr": "Пророка Іллі",
    "daniel": "Пророка Даниїла",
    "onufry p": "Онуфрія Великого",
    "onufry pustelnik": "Онуфрія Великого",
    "onufry": "Онуфрія Великого",
    "symeon słupnik": "Симеона Стовпника",
    "sumeon słupnik": "Симеона Стовпника",
    "antoni pieczerski": "Антонія Печерського",
    "antoni w": "Антонія Великого",
    "aleksy w": "Олексія, чоловіка Божого",
    "anna": "Святої Анни",
    "poczęcie anny": "Зачаття святої Анни",
    "joachim i anna": "Йоакима і Анни",
    "józef oblnmp": "Йосифа Обручника",
    "józef obl": "Йосифа Обручника",
    "konstantyn i helena": "Костянтина і Олени",
    "łazarz": "Лазаря",
    "weronika": "Вероніки",
    "niewiasty niosące wonności": "Жон-мироносиць",
}

#: Хвіст-сміття в полі присвяти: два і більше пробіли й один знак («Mikołaj Bp
#: … A», «Prakseda PM … (») — залишок сусідньої колонки при експорті бази.
_TAIL_JUNK = re.compile(r"\s{2,}\S{1,2}$")
_WS = re.compile(r"\s+")


def _title_key(code: str) -> str:
    return _WS.sub(" ", code).strip().rstrip(".").casefold()


def clean_title(raw: str | None) -> str:
    """Код присвяти без експортного сміття, але в написанні бази."""
    # 🔴 хвіст знімається ДО стиснення пробілів: ознака сміття — саме довгий
    # пробільний розрив перед ним, і після стиснення її вже не видно
    s = _TAIL_JUNK.sub("", str(raw or "").rstrip())
    return _WS.sub(" ", s).strip()


def title_uk(raw: str | None) -> str:
    """Присвята українською. Кілька присвят через кому → через « · ».

    Невідомий код повертається як є — не найближчим схожим.
    """
    code = clean_title(raw)
    if not code:
        return ""
    parts: list[str] = []
    # ⚠ дужки всередині ключа теж містять кому («Sobór NMP ("Pochwała NMP")»
    # — ні, там її немає), але цілий рядок пробуємо спершу — на випадок, коли
    # словник знає саме складений код
    whole = TITLES.get(_title_key(code))
    if whole:
        return whole
    for piece in code.split(","):
        key = _title_key(piece)
        if not key:
            continue
        parts.append(TITLES.get(key, piece.strip()))
    return " · ".join(parts)


def confession_of(denom: str | None) -> str:
    """`denom` бази → uniate | orthodox | latin | ''."""
    d = (denom or "").casefold()
    if "prawosław" in d:
        return "orthodox"
    if "greckiego" in d:
        return "uniate"
    if "łacińskiego" in d or "lacinskiego" in d:
        return "latin"
    return ""


def iter_features(dump: Any) -> Iterator[dict[str, Any]]:
    """Feature'и з дампу будь-якої з трьох форм: шар → перелік; перелік;
    відповідь FeatureServer (`{"features": […]}`)."""
    if isinstance(dump, list):
        yield from (f for f in dump if isinstance(f, dict))
        return
    if not isinstance(dump, dict):
        return
    if isinstance(dump.get("features"), list):
        yield from (f for f in dump["features"] if isinstance(f, dict))
        return
    for layer in dump.values():
        if isinstance(layer, list):
            yield from (f for f in layer if isinstance(f, dict))
        elif isinstance(layer, dict) and isinstance(layer.get("features"), list):
            yield from (f for f in layer["features"] if isinstance(f, dict))


def record(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Плоский рядок пака з одного feature. `None` — без ключа чи назви."""
    a = feature.get("attributes") or feature.get("properties") or {}
    g = feature.get("geometry") or {}
    ob_id = a.get("ob_id")
    name = (a.get("pl_name") or "").strip()
    if ob_id is None or not name:
        return None
    lat, lng = g.get("y"), g.get("x")
    if lat is None and isinstance(g.get("coordinates"), list):
        lng, lat = g["coordinates"][:2]
    role = "auxiliary" if "pomocnicz" in (a.get("type") or "") else "main"
    return {
        "ob_id": int(ob_id),
        "name": name,
        "name_v": (a.get("pl_name_v") or "").strip(),
        "place_type": (a.get("pl_type") or "").strip(),
        "confession": confession_of(a.get("denom")),
        "role": role,
        "parish_of": (a.get("parish") or "").strip(),
        "title": clean_title(a.get("title")),
        "title_uk": title_uk(a.get("title")),
        "material": (a.get("material") or "").strip(),
        "patronage": (a.get("patronage") or "").strip(),
        "monastery": (a.get("name") or a.get("kind") or "").strip(),
        "voivodeship": (a.get("pal_name") or "").strip(),
        "deanery": (a.get("deanery") or "").strip(),
        "adeaconry": (a.get("adeaconry") or "").strip(),
        "diocese": (a.get("diocese") or "").strip(),
        "source": (a.get("source") or "").strip(),
        "lat": float(lat) if lat is not None else None,
        "lng": float(lng) if lng is not None else None,
    }


def records(dump: Any) -> Iterable[dict[str, Any]]:
    for f in iter_features(dump):
        r = record(f)
        if r is not None:
            yield r


def describe(row: dict[str, Any]) -> dict[str, str]:
    """Людські підписи до кодів рядка — для CLI й екрана, не для пака."""
    pat = "-".join(PATRONAGE.get(p, p) for p in (row.get("patronage") or "").split("-")
                   if p) if row.get("patronage") else ""
    return {
        "voivodeship_uk": VOIVODESHIPS.get(row.get("voivodeship") or "", ""),
        "patronage_uk": pat,
        "material_uk": MATERIAL.get(row.get("material") or "", ""),
    }
