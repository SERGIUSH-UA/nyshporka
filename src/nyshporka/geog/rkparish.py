"""⛪ Римо-католицькі парафії: склад сіл і книги за роками — розбір і форми назв.

Таблиці укладача (сторінка на парафію) відповідають на питання, якого не знає
жоден покажчик справ: **до якого костелу ходило село**. Покажчик бачить костел
лише в самому містечку, а село за 10 км лежить у його книгах без жодної згадки
в описі. Без цієї відповіді парафію доводиться вгадувати між трьома сусідніми
містечками й читати не ту книгу.

Цей модуль не ходить у мережу: він читає збережений розбір сторінок
(`parishes.json` — перелік парафій із `villages`, `villages_uk`, `books`) і
віддає плоскі рядки для пака `rkparishes`.

🔑 **Назва села тут двомовна**: польський перелік (за Słownikiem
geograficznym) і український перелік сучасних назв. Питають же кирилицею —
українською чи російською формою — і латинкою. Тому кожна назва зводиться до
кількох ASCII-форм (`forms`), а запит — тим самим згортанням (`fold`): польське
`h` проти кириличного `г`, `-owce` проти `-івці`/`-овцы`, `ó` проти `о`/`і`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

#: Позначки типу поселення перед назвою в українському переліку
#: («сс. Богданівці», «м-ко Деражня», «передм. м-ка …»). Знімаються з початку
#: повторно, бо стоять ланцюжком.
_PREFIX = re.compile(
    r"^(?:\(?\s*(?:сс|cc|с|мм|м|м-ко|м-ка|мст|с-ще|прис|хут|кол|ст|слоб|з-ст|"
    r"зашт|передм|пердм|пердмістя|передмістя|села|істечка|містечка|она же)"
    r"[.:]?\)?\s+)", re.IGNORECASE)
_TAIL = re.compile(r"\s+та\s+ін\.?$|\s*\(.*?\)\s*$|[.;,:]+$")


def clean_name(raw: str) -> str:
    """Назва з переліку → назва села, без позначки типу й хвоста «та ін»."""
    s = " ".join(str(raw or "").split())
    for _ in range(4):
        new = _PREFIX.sub("", s)
        if new == s:
            break
        s = new
    s = _TAIL.sub("", s).strip(" ()-")
    return s


def _norm(s: str) -> str:
    from nyshporka.geog.gazetteer import norm_name
    from nyshporka.utils.translit import normalize_for_matching

    return normalize_for_matching(norm_name(s))


def fold(form: str) -> str:
    """ASCII-форма → згорнута: те, чим різняться мови, а не села.

    Застосовується однаково до назви з таблиці й до запиту людини, тож збіг
    не залежить від того, якою мовою село записали:

        Bohdanowce → bohdanovce → bogdanovci
        Богдановцы → bogdanovci
        Деражня → derazna;   Derażnia → deraznia → derazna
    """
    s = form.replace("ch", "h").replace("h", "g").replace("j", "i").replace("y", "i")
    for a, b in (("ia", "a"), ("ie", "e"), ("io", "o"), ("iu", "u")):
        s = s.replace(a, b)
    return re.sub(r"ce\b", "ci", s)


def forms(name: str, lang: str) -> list[str]:
    """Згорнуті ASCII-форми назви для пошуку.

    Польське `ó` дає три форми: як є (→ u), `о` (російська форма: Wójtowce ↔
    Войтовцы) і `і` (українська в закритому складі: Międzybóż ↔ Меджибіж). Це
    форми-здогади для пошуку, як `name_forms` покажчика; у `name` вони не йдуть.
    """
    variants = [name]
    if lang == "pl" and "ó" in name.casefold():
        variants += [name.replace("ó", "o").replace("Ó", "O"),
                     name.replace("ó", "i").replace("Ó", "I")]
    out: list[str] = []
    for v in variants:
        f = fold(_norm(v))
        if f and f not in out:
            out.append(f)
    return out


_YEARS = re.compile(r"(1[5-9]\d\d)")


def _years(s: str) -> tuple[int | None, int | None]:
    ys = [int(y) for y in _YEARS.findall(str(s or ""))]
    return (min(ys), max(ys)) if ys else (None, None)


def records(parishes: Iterable[dict[str, Any]]
            ) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]]:
    """Розбір → (парафія, села, книги) на кожну парафію.

    Рядки книг ідуть усі, зокрема без розпізнаної шифри: такий рядок несе
    `raw`, і людина бачить його як у джерелі, а не відсутнім.
    """
    for p in parishes:
        slug = str(p.get("parish_slug") or "").strip()
        if not slug:
            continue
        links = [*(p.get("geneteka_links") or []), *(p.get("drive_links") or [])]
        parish = {"slug": slug, "name": str(p.get("parish_name") or slug),
                  "gubernia": str(p.get("gubernia") or ""),
                  "dekanat": str(p.get("dekanat") or ""),
                  "url": str(p.get("url") or ""),
                  "overview": 1 if p.get("is_overview") else 0,
                  "links": " | ".join(links)}
        villages: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for lang, key in (("pl", "villages"), ("uk", "villages_uk")):
            for raw in p.get(key) or []:
                name = clean_name(raw)
                if not name or (lang, name) in seen:
                    continue
                seen.add((lang, name))
                villages.append({"slug": slug, "name": name, "lang": lang,
                                 "forms": " | ".join(forms(name, lang))})
        books = []
        for b in p.get("books") or []:
            yf, yt = _years(b.get("years") or "")
            books.append({"slug": slug, "years": str(b.get("years") or ""),
                          "year_from": yf, "year_to": yt,
                          "archive": str(b.get("archive_text") or ""),
                          "shifra": str(b.get("shifra") or ""),
                          "shifry": " | ".join(b.get("shifry") or []),
                          "types": " | ".join(b.get("types") or []),
                          "raw": " | ".join(str(x) for x in b.get("raw_row") or [])})
        yield parish, villages, books


def gubernia_uk(slug: str) -> str:
    """`gubernia-podolska` → «Подільська»; невідома — як є."""
    return {"gubernia-podolska": "Подільська", "gubernia-kijowska": "Київська",
            "gubernia-wolynska": "Волинська"}.get(slug, slug)


def dekanat_label(slug: str) -> str:
    """`dekanat-letyczowski` → `letyczowski` — ключ сторінки без префікса."""
    return slug.removeprefix("dekanat-") if slug else ""
