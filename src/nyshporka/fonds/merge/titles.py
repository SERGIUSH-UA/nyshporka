"""🧬 Сплав заголовків і полів джерел — ядро злиття.

🔴 Правило одне: сильніше джерело перемагає, слабше лишається слідом. Але
розбіжність у ЧЕРГУ ОКА подається не завжди — і кожен виняток тут коштував
тисяч хибних позицій, доки його не поставили.

⚠ Відома прогалина, яку НЕ ЛАГОДИМО наївно: коли заголовки СХОЖІ (вище порога),
а нове джерело сильніше, попередній заголовок замінюється БЕЗ запису в
`title_alt`. Дописати його туди виглядає очевидним — і зіпсує застосунок:
прапорець «розбіжність заголовка» ставиться на будь-який непорожній `title_alt`,
а ця гілка спрацьовує саме там, де джерела ЗГОДНІ. Прапорець засвітився б на
тисячах рядків без розбіжності, і черга ока роздулась би точно як від 642
хибних на ф.224. Чесна правка вимагає переписати ще й той прапорець — це інший
радіус, і робити її принагідно не можна.
"""
from __future__ import annotations

from typing import Any

from nyshporka.fonds.merge.sources import (
    TEXT_ORDER,
    TITLE_RANK,
    SourceBook,
    blank_row,
)
from nyshporka.fonds.merge.text import key_of, token_set_ratio, village_of

#: Поріг схожості заголовків. Нижче — розбіжність, вище — та сама справа.
TITLE_THRESHOLD = 0.45

Row = dict[str, Any]
Key = tuple[str, str, str]


def _no_conflict(a: str, b: str, title_a: str, title_b: str) -> bool:
    """Чи ця пара джерел взагалі може дати розбіжність, варту ока.

    🔴 Каталог сюди не подає нічого: його «заголовок» — це ОПИС ПАРАФІЇ, а не
    назва справи, тож проти уривка транскрипції схожість завжди нульова. На
    ф.904 це давало 1606 розбіжностей із 1606 — чергу, у якій тонули п'ять
    справжніх. Замість слів каталог звіряється СЕЛОМ, окремим правилом.

    🦆 Покажчик — теж ні: він зводить ті самі описи, тобто проти транскрипції й
    опису архіву це ТРЕТІЙ переказ одного тексту.

    🔴 І пара «опис архіву ↔ транскрипція»: це ДВІ транскрипції ОДНІЄЇ таблиці,
    тож розходження в словах — манера запису, а не факт («Покрова Пресвятої
    Богородиці» проти «Свято-Покровська» — та сама церква). Розбіжністю тут є
    РІЗНЕ СЕЛО, і лише вона варта ока: 572 позиції в черзі ховали ті кілька, де
    село справді інше — а саме вони означають переплутану справу.
    """
    if {"catalog", "duck"} & {a, b}:
        return True
    same_village = ({a, b} == {"archium", "wikisource"}
                    and village_of(title_b)
                    and village_of(title_b) == village_of(title_a))
    return bool(same_village)


def fuse_text(book: SourceBook) -> tuple[dict[Key, Row], list[dict[str, str]]]:
    """Звести текстові джерела в рядки реєстру + чергу розбіжностей.

    ⚠ Порядок обробки — слабкі до сильних, і він несе байти: черга будується в
    ньому ж.
    """
    reg: dict[Key, Row] = {}
    conflicts: list[dict[str, str]] = []

    for name in TEXT_ORDER:
        for row in book.rows.get(name, ()):
            key = key_of(row)
            if not key:
                continue
            r = reg.setdefault(key, blank_row(key))
            r["src"].add(name)
            _fuse_title(r, row, name, key, conflicts)
            _fuse_fields(r, row, name)
    return reg, conflicts


def _fuse_title(r: Row, row: dict[str, str], name: str, key: Key,
                conflicts: list[dict[str, str]]) -> None:
    title = (row.get("title") or "").strip()
    if not title:
        return
    rank = TITLE_RANK[name]
    cur_rank = TITLE_RANK.get(r["title_src"], -1)

    if not r["title"]:
        r["title"], r["title_src"] = title, name
        return

    if token_set_ratio(title, r["title"]) < TITLE_THRESHOLD:
        if not _no_conflict(name, r["title_src"], title, r["title"]):
            conflicts.append({
                "opys": key[0], "spr": key[1] + key[2], "field": "title",
                "value_a": r["title"], "src_a": r["title_src"],
                "value_b": title, "src_b": name,
                "score": f"{token_set_ratio(title, r['title']):.2f}",
                "verdict": "", "note": ""})
        # Заміна відбувається НЕЗАЛЕЖНО від того, чи подано розбіжність: черга
        # ока — про те, що людині варто глянути, а не про те, кому вірити.
        if rank > cur_rank:
            r["title_alt"].append(f"{r['title_src']}:{r['title']}")
            r["title"], r["title_src"] = title, name
        else:
            r["title_alt"].append(f"{name}:{title}")
    elif rank > cur_rank:
        # ⚠ Див. прогалину в шапці модуля: попередній заголовок тут губиться.
        r["title"], r["title_src"] = title, name


def _fuse_fields(r: Row, row: dict[str, str], name: str) -> None:
    """Роки, аркуші й власні поля джерела — правилом «перше непорожнє»."""
    for fld in ("year_from", "year_to"):
        v = (row.get(fld) or "").strip()
        if v and not r[fld]:
            r[fld] = v
            # ⚠ Відома неточність: коли роки прийшли з РІЗНИХ джерел, тут
            # лишається назва останнього. Виправляти окремо — це змінює байти.
            r["years_src"] = name

    fol = (row.get("folios") or "").strip()
    if fol and not r["folios"]:
        r["folios"], r["folios_src"] = fol, name

    if name == "ocr":
        # Єдине джерело номера тому й адреси прочитання в описі.
        for fld in ("dv_no", "src_page", "page_quality", "num_src"):
            v = (row.get(fld) or "").strip()
            if v and not r[fld]:
                r[fld] = v

    if name == "archium":
        # Адреса кадрів, а не ще один заголовок: саме за нею справа качається
        # посторінково, і свіжіше значення завжди краще.
        for fld in ("archium_file", "archium_url"):
            v = (row.get(fld) or "").strip()
            if v:
                r[fld] = v

    if name == "duck":
        for fld in ("duck_url", "duck_online", "duck_copy_url"):
            v = (row.get(fld) or "").strip()
            if v:
                r[fld] = v


def fuse_alfavitka(reg: dict[Key, Row], rows: list[dict[str, str]]) -> None:
    """Алфавітка архіву: сам факт існування справи + прізвища роду.

    ⚠ Ключ будується власним розбором, бо тут номер приходить суцільним полем;
    опис за замовчуванням — перший, бо алфавітка його часто не називає.
    """
    from nyshporka.fonds.merge.text import _RE_SPR, letter_cyr

    for row in rows:
        m = _RE_SPR.match((row.get("spr") or "").strip())
        if not m:
            continue
        key = ((row.get("opys") or "1").strip(), m.group(1),
               letter_cyr(m.group(2).lower()))
        r = reg.setdefault(key, blank_row(key))
        r["src"].add("alfavitka")
        name = (row.get("surname") or "").strip()
        if name and name not in r["surnames"]:
            r["surnames"].append(name)


def fuse_covers(reg: dict[Key, Row], rows: list[dict[str, str]]) -> None:
    """Обкладинка, прочитана оком. Перезаписує БЕЗУМОВНО: око сильніше за
    будь-який друкований каталог."""
    for row in rows:
        key = key_of(row)
        if not key:
            continue
        r = reg.setdefault(key, blank_row(key))
        for fld in ("cover_place", "cover_letters", "cover_note"):
            v = (row.get(fld) or "").strip()
            if v:
                r[fld] = v
        r["src"].add("covers")


def fuse_catalog(reg: dict[Key, Row], rows: list[dict[str, str]],
                 conflicts: list[dict[str, str]]) -> None:
    """Друкований каталог: парафія, тип запису, географія — і звірка СЕЛОМ.

    🔴 Ці поля НЕ перекривають прочитане оком: обкладинка сильніша за друк.
    Каталог заповнює те, чого ніхто не дивився, — а таких справ переважна
    більшість, бо оком бачено десятки, а в каталозі тисячі.

    🔴 ОСЬ ТУТ каталог і сперечається з рештою — не словами заголовка, а СЕЛОМ.
    Заміряно на ф.904: 5 розбіжностей проти 1606 при порівнянні заголовків, і
    всі п'ять справжні (спр.178 — «Вільшанка» в каталозі проти «євреї
    М'ясківка» на скані).

    🔴 Звіряємо лише з тим голосом, який САМ називає поселення. Заголовок
    транскрипції для ф.904 — це уривок присвяти («Богородична»), села в ньому
    немає за побудовою, і питати з нього село означає оголосити розбіжністю
    кожен рядок фонду: перша спроба дала 1019 із 1019.
    """
    from nyshporka.fonds.merge.text import names_settlement, village_matches

    for row in rows:
        key = key_of(row)
        if not key:
            continue
        r = reg.setdefault(key, blank_row(key))
        for fld, col in (("cat_place", "place"), ("cat_attached", "attached"),
                         ("cat_uezd", "uezd"), ("cat_confession", "confession"),
                         ("cat_district", "district"),
                         ("cat_parishes_n", "parishes_n"),
                         ("record_types", "record_types")):
            v = (row.get(col) or "").strip()
            if v and not r[fld]:
                r[fld] = v

        other = (r.get("commons_title") or "").strip()
        vills = [v.strip() for v in (row.get("place") or "").split(";") if v.strip()]
        if (other and vills and names_settlement(other)
                and not any(village_matches(v, other) for v in vills)):
            conflicts.append({
                "opys": key[0], "spr": key[1] + key[2], "field": "village",
                "value_a": other, "src_a": "commons",
                "value_b": "; ".join(vills), "src_b": "catalog",
                "score": "0.00", "verdict": "",
                "note": "село каталогу не згадане в назві файлу на Commons"})


def fuse_fs(reg: dict[Key, Row], fs_rows: list[dict[str, str]],
            wiki_rows: list[dict[str, str]]) -> None:
    """Плівки: DGS, тип запису, місце, кадри — і резервне джерело з опису.

    🔴 ДРУГЕ ДЖЕРЕЛО — КОЛОНКА В САМІЙ ТАБЛИЦІ ОПИСУ. Майстер-індекс плівок
    існує не для кожного фонду: у ЦДІАК ф.224 його немає зовсім, зате
    транскрипція має колонку з плівкою для 1516 із 1526 справ опису 1. Через це
    реєстр писав «сканів онлайн немає — замовлення в архіві» про справи, які
    лежать онлайн. Рангом це джерело нижче: заповнює лише порожнє.
    """
    for row in fs_rows:
        key = key_of(row)
        if not key:
            continue
        r = reg.setdefault(key, blank_row(key))
        for fld, col in (("fs_dgs", "dgs"), ("fs_film", "fs_film"),
                         ("fs_record_type", "record_type"), ("fs_place", "place"),
                         ("fs_frames", "frames")):
            v = (row.get(col) or "").strip()
            if v and not r[fld]:
                r[fld] = v
        if r["fs_dgs"] and not r["fs_url"]:
            r["fs_url"] = f"https://www.familysearch.org/search/film/{r['fs_dgs']}"

    for row in wiki_rows:
        key = key_of(row)
        if not key:
            continue
        film = (row.get("fs_film") or row.get("fs_dgs") or "").strip()
        if not film:
            continue
        r = reg.setdefault(key, blank_row(key))
        if not r["fs_film"]:
            r["fs_film"] = film
        if not r["fs_dgs"]:
            r["fs_dgs"] = film
        if not r["fs_url"]:
            r["fs_url"] = ("https://www.familysearch.org/records/images/"
                           f"search-results?imageGroupNumbers={film}")
