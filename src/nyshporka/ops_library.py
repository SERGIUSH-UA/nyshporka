"""📚 Бібліотека справ — що взагалі є на руках, і що з цим уже вирішено.

Відповідає на питання, якого не закриває жоден інший екран: **що я маю**.
`cases.list` каже про справи, взяті під облік у цьому просторі; бібліотека
зводить ширше — опис, шари роботи над справою і людські вердикти разом.

🔴 Вердикт тут — рішення людини, і воно не застаріває. Скан застаріває від
зміни моделі, декод — від нового прогону, а «я переглянув цю справу очима,
роду немає» лишається правдою й через рік. Саме тому вердикти живуть окремим
файлом, а не полем зведення, яке перезбирають.

🔴 Своєї «перезбірки» тут немає навмисно. Зведення будує `cases.build` — той
самий прохід, що збирає реєстр справ (`build_library` + `write_library`
всередині). Друга довга операція поруч виглядала б як окрема кнопка, робила б
те саме й дозволяла б двом проходам писати в один файл одночасно.

⚠ Порожня бібліотека і незібрана бібліотека — різні відповіді, і плутати їх
дорого: «0 справ» читається як факт («у мене нічого немає»), тоді як насправді
зведення просто не будували. Тому операції нижче розрізняють ці стани явно, а
`shown: null` означає «невідомо», а не нуль.

🔴🔴 Те саме правило вдруге, на шар глибше: колонки роботи (чим прочитано, чи
прошукано, скільки занесено оком) приходять із реєстру, і його теж може не
бути. Тоді вони `null`, а не нулі: «1331 справа без декоду» виглядає як факт
про роботу, а означає «зрізу не збирали».
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class LibraryArgs(BaseModel):
    q: str = Field(default="", description="шифр, назва або місце; шукає й "
                                           "приблизно, з урахуванням відмінка "
                                           "та латинки")
    q_thresh: int = Field(default=80, ge=60, le=100,
                          description="поріг приблизного збігу для `q`")
    key: str = Field(default="", description="точний ключ справи `repo/fond/spr` "
                                             "— вхід із реєстру опису чи газетира")
    repo: str = Field(default="", description="архів: DAHMO, DAVO, CDIAK…")
    fond: str = Field(default="", description="номер фонду")
    record_type: str = Field(default="", description="тип запису: birth, revision…")
    doc_type: str = Field(default="", description="тип документа, підрядком")
    uezd: str = Field(default="", description="повіт; порівнюються корені форм")
    htr: Literal["", "any", "none", "partial", "pysar", "diak", "skryba",
                 "both"] = Field(default="", description="стан читання; "
                                                         "`any` — хоч якийсь декод")
    fuzzy: Literal["", "any", "none", "scanned", "swept", "reviewed"] = Field(
        default="", description="стан пошуку роду")
    status: Literal["", "missing", "on_disk", "unread", "partial", "read",
                    "todo"] = Field(default="", description="стан справи; "
                                                            "`todo` — ні свіжого "
                                                            "прогону, ні вердикту")
    verdict: Literal["", "any", "none", "no_clan", "clan_found", "recheck"] = Field(
        default="", description="фільтр за людським вердиктом; "
                                "`any` — будь-який, `none` — вердикту немає")
    curated: bool = Field(default=False, description="лише відібрані дослідником")
    on_disk: bool | None = Field(
        default=None, description="лише ті, що є на диску (або лише яких немає)")
    page: int = Field(default=0, ge=0, le=10_000, description="сторінка видачі")
    page_size: int = Field(default=50, ge=10, le=200)


#: Поля, які їдуть у браузер. Не весь `CaseEntry`: у ньому є службові сліди
#: збірки (`desc_source`, `rtypes_inferred`, `tag`), і показувати їх означало б
#: пропонувати рішення на підставі того, як зведення себе зібрало.
_FIELDS = ("key", "repo", "repo_label", "fond", "opys", "spr", "shifra", "title",
           "year_from", "year_to", "doc_type", "record_types", "place", "parish",
           "path", "on_disk", "frames", "script", "langs", "curated", "group",
           "why")


def _row(case: dict[str, Any], layer_fields: tuple[str, ...]) -> dict[str, Any]:
    """Рядок видачі: опис + колонки роботи + вердикт.

    ⚠ Перелік колонок роботи приходить аргументом, а не імпортом на рівні
    модуля. `nyshporka.cases` при першому дотику піднімає резолвер, а той —
    бібліотеку, яка вимагає простору вже на імпорті; отже модульний імпорт
    звідси валив би весь реєстр операцій там, де простору ще немає — тобто в
    кожного, хто щойно поставив застосунок.
    """
    out = {k: case.get(k) for k in (*_FIELDS, *layer_fields)}
    for k in ("verdict", "verdict_note", "verdict_date", "verdict_pages"):
        out[k] = case.get(k)
    out["verdict"] = out["verdict"] or ""
    return out


def _fuzzy_hit(q: str, row: dict[str, Any], thresh: int) -> bool:
    """Чи схожа справа на запит — підрядком або приблизно.

    🔴 Підрядка мало, і це не зручність. Назва села в описі буває латинкою
    («Miastkowka»), в іншому відмінку («Ольгопільського») або з апострофом,
    якого людина не набирає. Підрядком такі форми не збігаються ніколи — і
    справа, яка є, чесно відповідає «немає».

    Точний збіг перевіряється першим: він дешевий і не потребує пояснень.
    """
    hay = " ".join(str(row.get(k) or "") for k in
                   ("shifra", "title", "place", "parish", "doc_type", "key",
                    "group", "why"))
    if q.casefold() in hay.casefold():
        return True
    from nyshporka.cases.db import geo_hit

    # Гео-порівняння працює по коренях нормалізованих форм, тобто знімає і
    # відмінок, і латинку заразом.
    return geo_hit(q, [str(row.get(k) or "") for k in
                       ("place", "parish", "settlement", "uezd", "title")])


def _matches(row: dict[str, Any], a: LibraryArgs) -> bool:
    # 🔴 точний збіг, а не підрядок. Це вхід із реєстру опису й газетира, де
    # ключ уже відомий; приблизний пошук за шифрою давав би сусідні справи
    # того самого фонду — тобто відкривав би не ту книгу.
    #
    # ⚠ Одному ключу може відповідати кілька рядків: та сама архівна справа
    # буває завантажена кількома вирізками кадрів у різні теки. Показуємо всі —
    # сховати частину означало б збрехати про те, що є на диску.
    if a.key and str(row.get("key") or "") != a.key:
        return False
    if a.repo and (row.get("repo") or "").upper() != a.repo.upper():
        return False
    if a.fond and str(row.get("fond") or "") != a.fond:
        return False
    if a.curated and not row.get("curated"):
        return False
    if a.on_disk is not None and bool(row.get("on_disk")) is not a.on_disk:
        return False
    if a.record_type and a.record_type not in (row.get("record_types") or []):
        return False
    if a.doc_type and a.doc_type.casefold() not in str(row.get("doc_type") or "").casefold():
        return False
    if a.uezd:
        from nyshporka.cases.db import geo_hit

        # Повіт розбирає реєстр; поки його немає, лишається текст опису —
        # у ньому повіт часто стоїть просто в назві місця.
        if not geo_hit(a.uezd, [str(row.get(k) or "") for k in
                                ("uezd", "settlement", "place", "parish")]):
            return False
    if a.verdict == "any" and not row["verdict"]:
        return False
    if a.verdict == "none" and row["verdict"]:
        return False
    if a.verdict not in ("", "any", "none") and row["verdict"] != a.verdict:
        return False
    if a.htr:
        stage = row.get("htr_stage")
        # 🔴 Реєстру немає — фільтр за шаром не «нічого не знайшов», а
        # «нічим фільтрувати». Пропускаємо рядок: інакше порожня видача
        # виглядала б як відповідь про роботу.
        if stage is not None:
            stage = stage or "none"
            if a.htr == "any" and stage == "none":
                return False
            if a.htr != "any" and stage != a.htr:
                return False
    if a.fuzzy:
        st = row.get("fuzzy_stage")
        if st is not None:
            st = st or "none"
            if a.fuzzy == "any" and st == "none":
                return False
            if a.fuzzy != "any" and st != a.fuzzy:
                return False
    if a.status:
        from nyshporka.cases.layers import status_of

        got = status_of(row)
        if a.status == "todo":
            # Найдорожче питання екрана: на що варто витрачати ніч. Це справи
            # без жодного рішення — ні машинного, ні людського.
            if row.get("verdict") or got in ("read", "missing"):
                return False
        elif got != a.status:
            return False
    # Запит іде останнім навмисно: він найдорожчий (нормалізація й приблизне
    # порівняння), а дешеві фільтри до нього вже відсіяли більшість.
    return not a.q or _fuzzy_hit(a.q, row, a.q_thresh)


# 🔴 `agent=False` в обох — рішення, а не «поки не зробили».
#
# `library.list` агентові нічого не додає: те саме про справи в роботі він уже
# питає через `cases.list`, а зайвий tool росте в переліку, який модель мусить
# читати цілком при кожному виклику.
#
# `library.verdict` — принциповіше. Вердикт по справі виносить людина, і
# «роду тут немає» від агента закриває напрям пошуку назавжди: наступна сесія
# прочитає його як доведений факт і туди більше не гляне. Тому дія лишається
# рівно там, де сидить той, хто дивився очима.
@op("library.list", summary="Бібліотека: які справи є на руках і що з ними вирішено",
    args=LibraryArgs, section="material", agent=False)
def library_list(a: LibraryArgs) -> Envelope:
    """Зведення справ із шарами роботи й людськими вердиктами.

    🔴 «Зведення ще не збирали» не виглядає як «справ немає». Нуль без
    знаменника не результат: побачивши «0 справ», людина вирішує, що шукати
    нема де, — і закриває напрям, якого ніхто не відкривав. Тому кількість тут
    `null`, а не 0, і поруч стоїть застереження з тим, чим це лікується.
    """
    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    # 🔴 Три стани, а не два, і читаються вони тут, а не через `load_library()`.
    # Той ковтає будь-який виняток і віддає `[]`, тобто зводить «файла немає» і
    # «файл побитий» до «справ немає» — рівно того хибного нуля, від якого
    # написаний докстрінг модуля. Побита бібліотека при цьому виглядала б
    # гірше за відсутню: `built: true`, «0 справ», жодного натяку на причину.
    if not L.LIBRARY_PATH.exists():
        env = ok({"cases": [], "shown": None, "total": None, "built": False})
        env.warn("no_library_yet",
                 "бібліотеку ще не збирали — це не означає, що справ немає")
        env.stale_because(["зведення справ ще не будували"], fix="nysh cases build")
        env.suggest("cases.build", "зібрати зведення з канону й диска")
        return env
    try:
        json.loads(L.LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        # 🔴 Побите зведення лишало екран БЕЗ жодної кнопки — на відміну від
        # стану «ще не збирали», де кнопка є. Тобто гірший із двох станів мав
        # менше виходів, ніж кращий.
        return fail(f"зведення справ не читається ({type(exc).__name__}: {exc}) — "
                    f"файл {L.LIBRARY_PATH.name} побитий, його треба "
                    f"перезібрати").suggest(
            "cases.build", "перезібрати зведення справ")

    all_rows = [_row(c, LY.LAYER_FIELDS) for c in LY.entries()]
    hit = [r for r in all_rows if _matches(r, a)]
    total = len(hit)
    start = a.page * a.page_size
    shown = hit[start:start + a.page_size]

    env = ok({
        "cases": shown, "shown": len(shown), "total": total,
        "page": a.page, "page_size": a.page_size,
        "pages": (total + a.page_size - 1) // a.page_size,
        "library_total": len(all_rows), "built": True,
        # 🔴 Фасети — з усієї бібліотеки, а не з видачі. Зібрані з
        # відфільтрованого, вони схлопуються до одного пункту після першого ж
        # вибору: решта архівів зникає зі списку, і повернутись до них нема
        # чим — екран починає брехати про діючий фільтр.
        "facets": LY.facets(all_rows),
        "summary": LY.summary(all_rows),
        "kinds": {k: v["label"] for k, v in L.VERDICT_KINDS.items()},
        # Сумісність: перелік архівів окремим полем читає нинішній екран.
        "repos": sorted({r["repo"] for r in all_rows if r.get("repo")}),
    })

    if not LY.has_layers():
        env.warn("no_layers",
                 "шарів роботи над справами немає: реєстру ще не збирали")
        env.suggest("cases.build", "зібрати реєстр справ")
    else:
        st = LY.staleness()
        if st.get("stale"):
            env.stale_because(st.get("reasons") or ["реєстр відстав від джерел"],
                              fix="nysh cases build")
        elif st.get("unknown"):
            # 🔴 Збіг мітки означає лише «через застосунок нічого не міняли».
            # Тека, покладена провідником, пульсу не б'є — і сказати «свіжий»
            # тут було б вигадкою.
            env.warn("staleness_unknown",
                     "через застосунок нічого не міняли, але файли могли "
                     "покласти повз нього — свіжість зрізу невідома")

    # 🔴 Знаменник поруч із видачею, а не лише в підсумку: «нічого не
    # знайшлось» означає різне при 12 справах у бібліотеці й при 1200.
    if not hit:
        env.warn("empty_filter",
                 f"під фільтр не підпало жодної справи з {len(all_rows)} "
                 f"у бібліотеці")
    elif start >= total:
        env.warn("page_past_end",
                 f"сторінки {a.page + 1} немає: під фільтр підпало {total} справ")
    return env


class VerdictArgs(BaseModel):
    key: str = Field(description="ключ справи з бібліотеки, напр. DAHMO/315/8433")
    verdict: Literal["", "no_clan", "clan_found", "recheck"] = Field(
        default="", description="порожньо — зняти вердикт")
    note: str = Field(default="", description="чим саме доведено")
    pages: int | None = Field(default=None, description="скільки аркушів переглянуто")


@op("library.verdict", summary="Позначити справу вердиктом людини",
    args=VerdictArgs, section="material", mutates=True, agent=False)
def library_verdict(a: VerdictArgs) -> Envelope:
    """Рішення ока по справі.

    🔴 Нуль без знаменника — не результат. «Роду немає» без числа переглянутих
    аркушів наступного разу читається як доведений факт, хоча може означати
    «глянув перші три сторінки». Тому при `no_clan` без `pages` конверт
    попереджає — але не відмовляє: вердикт виносить людина, і машина не має
    права не пустити її рішення.
    """
    from datetime import date

    from nyshporka import library as L
    from nyshporka.cases import layers as LY

    if not a.key.strip():
        return fail("не сказано, якій справі ставити вердикт")
    try:
        cur = L.set_verdict(a.key.strip(), a.verdict or None, note=a.note,
                            pages=a.pages, date=date.today().isoformat())
    except ValueError as exc:
        return fail(str(exc))
    # Зведення тримається кешем на відбитку джерел; вердикт щойно змінив одне
    # з них, і чекати збігу мітки означало б показати старе на наступному ж
    # оновленні екрана.
    LY.reset()
    env = ok({"key": a.key.strip(), "verdict": cur})
    if a.verdict == "no_clan" and not a.pages:
        env.warn("no_denominator",
                 "«роду немає» без числа переглянутих аркушів — наступна сесія "
                 "прочитає це як доведений нуль")
    return env
