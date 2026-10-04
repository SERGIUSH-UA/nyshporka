"""Ім'я файла кадру: номер у справі й id кадру джерела — двома полями.

Завантажувач кладе в ім'я файла обидва: `0037_f351120.jpg` — 37-й кадр справи,
кадр `351120` на сайті архіву. Номер потрібен, щоб читати по порядку; id —
щоб знайти той самий кадр у джерелі й упізнати його в чужій зйомці тієї самої
справи.

🔴 Доки обидва жили лише в імені, кожен читач розбирав його сам і по-своєму.
Правило «номер сторінки — остання група цифр» для такого імені віддає id
джерела: «скан 37» справи з ARCHIUM не знаходився, бо його номером вважалось
351120. Паспорт завантаження й перелік кадрів пакета цих полів не мали зовсім
(звіт користувача 29.09.2026). Тут — одна пара функцій на всіх: ім'я будується
й розбирається в одному місці.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

#: `NNNN_f<id>` — форма ARCHIUM і плоского стейджингу плівок: маркер `_f`
#: однозначний, тож вона впізнається без підказки про джерело.
_WITH_ID = re.compile(r"^(\d{1,6})_f(\d+)$")
#: `NNNN_<ім'я в сховищі>` — так називає кадри «Бабин Яр». Без маркера, тому
#: лише за підказкою: `1854_0012` в іншій теці — рік і номер, а не номер і id.
_WITH_STEM = re.compile(r"^(\d{4,6})_(.+)$")
#: `n<лист>` — Internet Archive: номер листа і є id у джерелі.
_LEAF = re.compile(r"^n(\d+)$")

#: Джерела, чию форму імені впізнаємо лише за назвою джерела.
BY_STEM = "babynyar"
BY_LEAF = "ia"
#: Сканотека ПТГ: `185_R` — права половина розвороту, скан 185 (`core.skanoteka`).
BY_SPREAD = "skanoteka"


@dataclass(frozen=True)
class Frame:
    """Що ім'я кадру каже про нього. Чого не каже — `None` і порожньо."""

    n: int | None = None
    src: str = ""


def build(n: int, src: str | int = "") -> str:
    """Стем файла кадру: `0037_f351120` або, без id джерела, `0037`."""
    head = f"{int(n):04d}"
    return f"{head}_f{src}" if str(src) else head


def parse(name: str, source: str = "") -> Frame:
    """Номер у справі й id джерела з імені файла. Нерозбірне ім'я — порожньо.

    `source` — звідки теку завантажено (`fetched_from` паспорта): без нього
    впізнається лише форма з маркером `_f`.

    🔴 Не вгадує. Ім'я без відомої форми (`Image00148`, `f792-1-55_0042`)
    повертає порожній `Frame`: номер сторінки з такого імені й далі бере той,
    хто питає, своїм правилом — тут йому нічого не обіцяно.
    """
    stem = PurePath(str(name)).stem
    m = _WITH_ID.match(stem)
    if m:
        return Frame(int(m.group(1)), m.group(2))
    if source == BY_STEM:
        m = _WITH_STEM.match(stem)
        if m:
            return Frame(int(m.group(1)), m.group(2))
    if source == BY_LEAF:
        m = _LEAF.match(stem)
        if m:
            return Frame(int(m.group(1)), m.group(1).lstrip("0") or "0")
    if source == BY_SPREAD:
        from nyshporka.core import skanoteka

        got = skanoteka.page_scan(stem)
        if got:
            # Номер скана — не номер сторінки справи (розворот дає дві), тож `n` порожнє.
            return Frame(None, skanoteka.src_of(*got))
    return Frame()
