"""Дві довідникові осі реєстру: **стан** і **місце**.

Обидві в метриках записані вільним текстом і в непрямих відмінках —
«М. Мясковки крестьянинъ», «села Ротмистровки», «проживающій въ М. Мясковкѣ
однодворецъ». Без зведення до класів реєстр села вироджується в купу рядків,
де «Мясковки», «Мясковкѣ» і «Мястковка» — три різні місця.

**Стан важить не менше за прізвище.** Однодворці — не селяни, а здекласована
шляхта, і саме стан відрізняє носія роду від однофамільця
(пор. [[rod-estate-odnodvortsi-not-peasants]]). Тому зберігаємо і сирий рядок
як у джерелі, і клас, і — окремо — чи особа тутешня, чи прийшла: формула
«**проживающій въ** М. Мясковкѣ однодворецъ» замість «М. Мясковки крестьянинъ»
прямо позначає приблуду, а такі записи і є слідом міграції роду.

Класи свідомо грубі: дрібніші відтінки («временнообязанный», «поселянинъ»)
лишаються у сирому рядку, а клас потрібен для розрізів і статистики.
"""
from __future__ import annotations

import re

from nyshporka.utils.translit import normalize_archival

# 🔴 Причт не стає особою реєстру: священник, дяк і паламар повторюються під
# КОЖНИМ актом однаково, тож у переліку мешканців вони лише шум — та ще й
# джерело фальшивих конфліктів між двома вичитками. З самих записів вони НЕ
# видаляються (дані не губимо), просто не йдуть у звід і в чергу ескалації.
# Духовенство серед мирян («діаконовъ сынъ» як наречений) проходить під
# звичайною роллю й лишається.
#
# Змінити перелік можна профілем книги (`reconstitute.skip_roles`) — у джерелі,
# де причт не повторюється, викидати його не треба.
SKIP_ROLES = {"priest"}

# клас → маркери (шукаються як підрядок у нормалізованому вигляді)
_ESTATE_MARKERS: dict[str, tuple[str, ...]] = {
    "однодворці": ("odnodvorec", "odnodvorc", "odnodvor"),
    "шляхта": ("slahtic", "slahetn", "dvoranin", "dvorank", "blagorodn",
               "nobil", "szlacht"),
    "духовенство": ("svascennik", "ierei", "diakon", "dacok", "ponomar",
                    "psalomsc", "pricetnik", "cerkovnik", "klirik",
                    "kseondz", "prezviter"),
    "міщани": ("mesanin", "mescanin", "mesan", "mesc"),
    "купці": ("kupec", "kupc"),
    "військові": ("soldat", "radovoi", "otstavn", "unter", "ofic", "bombardir",
                  "kantonist", "kazak", "rekrut", "ratnik"),
    "колоністи": ("kolonist", "poselenec"),
    "двірські": ("dvorov", "krepostn"),
    "селяни": ("krestanin", "krestane", "krestan", "krest", "poselanin",
               "vremennoobazann", "hlebopasec"),
    "євреї": ("evrei", "iudei", "zid"),
}

# «проживающій въ», «прибывшій», «временно проживающ» — маркер, що особа НЕ тутешня
_INCOMER_RE = re.compile(
    r"prozivau|prozivaus|pribiv|vremenno proziv|priselen|prislii|inogorodn")

# службові слова перед топонімом (у т.ч. формула прописки «проживающій въ»)
_PLACE_PREFIX = re.compile(
    r"^(m|mest|mestecka|mesteck|mestecko|s|sel|sela|selo|selca|selce|d|derevni|derevna|"
    r"slobodi|sloboda|hutora|hutor|goroda|gorod|posada|posad|kolonii|kolonia|"
    r"prozivauscii|prozivausii|prozivaus|prozivau|v|vo|pri)\.?\s+")
# хвіст непрямого відмінка: Мясковки / Мясковкѣ / Мясковкою / Ямпольскаго
_PLACE_TAIL = re.compile(r"(ago|ogo|omu|imi|ou|oi|ei|ii|ah|am|i|e|a|u|o|y)$")
# адміністративний хвіст, який не є назвою: «Ямпольскаго уѣзда»
_ADMIN_TAIL = re.compile(
    r"\s*(uezda|uezd|gubernii|guberna|volosti|volost|prihoda|prihod|"
    r"okruga|okrug|povita|povit)\b.*$")


def estate_class(raw: str | None) -> str:
    """Сирий стан → грубий клас. Невідоме повертає '' (сирий рядок не втрачається)."""
    n = normalize_archival(raw or "")
    if not n:
        return ""
    for cls, markers in _ESTATE_MARKERS.items():
        if any(m in n for m in markers):
            return cls
    return ""


def is_incomer(raw: str | None) -> bool:
    """Чи формула запису позначає прийшлого («проживающій въ …»), а не тутешнього."""
    return bool(_INCOMER_RE.search(normalize_archival(raw or "")))


def place_key(raw: str | None) -> str:
    """Топонім → ключ, стійкий до відмінка й службових слів.

    «М. Мясковки», «с. Мясковкѣ», «Мястковка» → близькі ключі, які потім
    зводить fuzzy. Точну форму джерела тут НЕ підміняємо — вона лишається
    в самому записі, а ключ потрібен лише для групування.
    """
    n = normalize_archival(raw or "")
    if not n:
        return ""
    n = _ADMIN_TAIL.sub("", n).strip()
    prev = None
    while prev != n:                       # «м. села Мясковки» — префікси бувають парами
        prev = n
        n = _PLACE_PREFIX.sub("", n).strip()
    if not n:
        return ""
    # головне слово — ОСТАННЄ: у слов'янських назвах означення стоїть попереду
    # («Верхняя Ротмистровка», «Новая Мясковка»), і за першим словом два села
    # одного куща розповзлись би в різні місця
    head = n.split()[-1]
    return _PLACE_TAIL.sub("", head) or head


def estate_label(raw: str | None) -> str:
    """Короткий підпис стану для таблиць: клас, а якщо не розпізнано — сирий рядок."""
    return estate_class(raw) or (raw or "").strip()
