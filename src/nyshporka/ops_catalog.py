"""🗺🏛 Операції довідників: газетир, реєстр опису фонду, стан каталогу.

Три вкладки дослідницької консолі, яких у продуктовому застосунку не було:
«🗺 Газетир», «🏛 Фонди» і стан довідників. Тут вони з'являються так, як
належить у цьому пакеті, — **операціями, а не роутами**: один опис живить
браузер, командний рядок і агента, тож три обличчя не можуть розійтись у
відповідях.

Чому це окремий модуль, а не хвіст `ops_builtin`: домен у них спільний і
самостійний (довідники про архів, а не про нашу роботу), і читаються вони разом.

🔑 **Головна відмінність від решти операцій — покриття.** Кожна відповідь тут
несе `coverage`: у чому саме шукали і якого воно зрізу. Без цього «нічого не
знайдено» не відрізнити від «ніде не шукали», а в генеалогії ця плутанина
найдорожча — «немає» закриває напрям пошуку.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import CoverageItem, Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

# 🔴 усі операції цього модуля — `agent=False`, і це не забудькуватість.
#
# Перелік агентських tool'ів має стелю 18 (`mcp.server.TOOL_LIMIT`), і вона не
# технічна: далі модель перестає дочитувати описи й починає вгадувати, а
# вгадування коштує дорожче за відсутність інструмента. П'ять нових операцій
# підняли б перелік до 23, тобто зламали б рівно те, заради чого стеля стоїть.
#
# Тому довідники з'являються в браузері й командному рядку (де переліку ніхто не
# «дочитує», і зайвий пункт нічого не псує), а агентська поверхня лишається
# незмінною. Це свідома неповнота, а не недогляд.
#
# ⚠ Питання «що саме має бути серед вісімнадцяти» — не моє: газетир, можливо,
# цінніший для агента за котрийсь із наявних tool'ів, але вирішувати, кого
# посунути, має власник. Природний кандидат на злиття — наявний
# `catalog.search` («де взагалі є щось про моє село»): він відповідає на ТЕ саме
# питання, тільки не заглядаючи в газетир, тобто сьогодні мовчить про найкращу
# доступну відповідь.


def _coverage_of(answer: Any) -> list[CoverageItem]:
    """`catalog.query.Answer.coverage` → покриття конверта."""
    return [CoverageItem(source=c.pack_id, taken=c.taken, rows=c.rows,
                         scope=c.scope) for c in answer.coverage]


# ── 🗺 газетир: від села до справ по всіх фондах ─────────────────────────────
#
# 🔑 Зворотний напрям до реєстру опису, і найчастіше починають саме з нього:
# людина знає село, а не фонд. Реєстр опису на це відповісти не може — він знає
# один фонд і мовчить про сусідні.

class GeogFindArgs(BaseModel):
    q: str = Field(default="", description="назва села: укр, рос або латинкою")
    uezd: str = Field(default="", description="повіт або губернія")
    fond: str = Field(default="", description="лише де є справи цього фонду")
    section: str = Field(default="",
                         description="church | decanats | rabbinate; "
                                     "порожньо — усі конфесії")
    limit: int = Field(default=40, ge=1, le=200)


@op("geog.find", summary="Де взагалі є метрики цього села — по всіх фондах архіву",
    args=GeogFindArgs, mutates=False, agent=False, section="material")
def geog_find(a: GeogFindArgs) -> Envelope:
    """Пошук поселення в довідниках.

    🕍 Конфесія — фільтр, а не три окремі газетири. Метрики православної
    громади, костелу й рабинату одного містечка лежать у різних фондах
    (Бердичів — 283, 95 і 1), тож шукати лише в православному розділі означає
    систематично не бачити двох третин. Дефолт — усі розділи.
    """
    from nyshporka.catalog.query import CatalogMissing, find_places

    try:
        ans = find_places(a.q, limit=a.limit, uezd=a.uezd, fond=a.fond,
                          section=a.section)
    except CatalogMissing as exc:
        # 🔴 Відмова, а не порожній список. Джерело, яке не може шукати, не
        # додає нуль до суми: «такого села немає в жодному фонді» закрило б
        # напрям назавжди, тоді як насправді просто не поставлено довідник.
        return fail(str(exc))
    env = ok({"places": ans.rows, "shown": len(ans.rows)})
    env.covered_by(_coverage_of(ans))
    if not ans.rows:
        env.warn("nothing_found",
                 "у переглянутих довідниках такого поселення немає — це їхня "
                 "межа, а не відповідь про архів у цілому")
    else:
        env.suggest("geog.card",
                    "подивитись усі справи поселення й що з них у нас є")
    return env


class GeogCardArgs(BaseModel):
    card: str = Field(description="ідентифікатор картки або назва села")
    confusers: bool = Field(default=True,
                            description="показати схожі назви, які плутає фаззі")


@op("geog.card", summary="Картка поселення: церква, усі справи, що з них у нас є",
    args=GeogCardArgs, mutates=False, agent=False, section="material")
def geog_card(a: GeogCardArgs) -> Envelope:
    from nyshporka.catalog.query import (
        CatalogMissing,
        confusers,
        find_places,
        place_card,
    )

    card = a.card
    try:
        if not card.endswith(".xml"):
            found = find_places(card, limit=1)
            if not found.rows:
                env = ok({"place": None})
                env.covered_by(_coverage_of(found))
                env.warn("not_found", f"поселення «{a.card}» у довідниках немає")
                return env
            card = found.rows[0]["card"]
        ans = place_card(card)
    except CatalogMissing as exc:
        return fail(str(exc))

    if not ans.rows:
        env = ok({"place": None})
        env.covered_by(_coverage_of(ans))
        env.warn("not_found", "; ".join(ans.partial) or "картки немає")
        return env

    place = ans.rows[0]
    if a.confusers:
        # ⚠ Не прикраса: у каталозі поруч стоять М'ястківка, М'яколовичі й
        # М'якохід — усі з метриками XVIII ст. Побачити цей список до пошуку
        # дешевше, ніж потім розбирати, чому «знайшлось» не те село.
        place["confusers"] = confusers(card).rows
    env = ok({"place": place})
    env.covered_by(_coverage_of(ans))
    n_all = len(place.get("cases") or [])
    if n_all and not int(place.get("n_on_disk") or 0):
        env.suggest("catalog.search",
                    f"жодної з {n_all} справ цього поселення в нас немає — "
                    f"пошукати, де їх узяти")
    return env


# ── 🗂 стан довідників ───────────────────────────────────────────────────────
@op("catalog.packs", summary="Які довідники встановлено і якого вони зрізу",
    mutates=False, agent=False, section="material")
def catalog_packs(_: NoArgs) -> Envelope:
    """Стан каталогу — щоб «нічого не знайдено» можна було пояснити.

    ⚠ Зіпсовані паки не ховаються: «немає» і «зіпсоване» лікуються по-різному
    (перше встановленням, друге — повторним), і плутати їх означає радити не те.
    """
    from nyshporka.catalog import store

    packs = store.installed()
    rows = [{"pack_id": p.pack_id, "domain": p.domain, "taken": p.taken,
             "rows": p.rows, "size": p.size, "note": p.note,
             "state": "ok" if p.ok else "broken", "problem": p.problem}
            for p in packs]
    env = ok({"packs": rows, "dir": str(store.catalog_dir()),
              "domains": sorted({p.domain for p in packs if p.ok})})
    if not packs:
        env.warn("no_catalog",
                 "довідників немає — пошук по каталогах архівів недоступний")
    for p in packs:
        if not p.ok:
            env.warn("pack_broken", f"{p.pack_id}: {p.problem}")
    return env


# ── 🏛 реєстр опису фонду: «що взагалі існує в архіві» ───────────────────────
#
# Третє сховище поруч із бібліотекою («що ми маємо») і реєстром справ («що ми
# зробили»). Плутати їх не можна: «справи немає» з бібліотеки означає «не
# завантажено», а з реєстру опису — «в архіві не існує».

class FondRowsArgs(BaseModel):
    fond: str = Field(description="ідентифікатор фонду зі `fond.list`")
    opys: str = ""
    q: str = Field(default="", description="підрядок у заголовку справи")
    surname: str = Field(default="",
                         description="прізвище з алфавітки архіву — зворотний "
                                     "напрям «від прізвища до справи»")
    year: str = Field(default="", description="рік або діапазон «1840-1860»")
    uezd: str = ""
    state: str = Field(default="",
                       description="disk | todo | film | mirror_only | order | scan; `film` = вільна плівка FS (качається за DGS), `order` = каналу немає зовсім")
    spr: str = Field(default="", description="номер справи — точковий вхід із "
                                             "бібліотеки чи газетира")
    limit: int = Field(default=50, ge=1, le=500,
                       description="скільки рядків віддати; `page_size` сильніший")
    page: int = Field(default=0, ge=0, le=10_000, description="сторінка видачі")
    page_size: int = Field(default=0, ge=0, le=200,
                           description="розмір сторінки; 0 — узяти `limit`")


@op("fond.list", summary="Які фонди описано: скільки справ, скільки вже в нас",
    mutates=False, agent=False, section="material")
def fond_list(_: NoArgs) -> Envelope:
    from nyshporka.fonds import registry as R

    try:
        found = R.discover_fonds()
    except Exception as exc:
        return fail(f"реєстри описів недоступні ({type(exc).__name__}: {exc})")
    out = []
    for f in found:
        rows = R.load_rows(f["id"])
        live = R.live_on_disk(f["repo"], f["fond"])
        s = R.summarize(rows, live)
        out.append({"id": f["id"], "label": f["label"], "repo": f["repo"],
                    "fond": f["fond"], "rows": s["rows"],
                    "on_disk": s["on_disk_live"], "todo": s["todo"],
                    "scans": s["commons"] + s["mirror_only"],
                    # 🔴 Зведення цілком. `summarize` рахує вісімнадцять
                    # показників в одному проході, а віддавалось чотири — тож
                    # екран не міг сказати ні скільки справ обрізає дзеркало,
                    # ні скільки номерів відновлено між якорями, ні скільки
                    # справ має прізвища з алфавітки. Це не «додаткові дані»:
                    # саме ними вирішують, чи має сенс замовляти документ.
                    "summary": s,
                    "schema": f.get("schema") or "",
                    # Чи є супутні файли — щоб екран не обіцяв того, чого немає.
                    "has_coverage": bool(f.get("has_coverage")),
                    "has_conflicts": bool(f.get("has_conflicts")),
                    "has_alfavitka": bool(f.get("has_alfavitka"))})
    env = ok({"fonds": out, "shown": len(out)})
    if not out:
        env.warn("no_registries",
                 "жодного реєстру опису немає")
        # 🔴 Порада мусить вести туди, де це лікується. Доти вона кликала
        # `catalog.packs` — довідники газетира, які до опису фонду стосунку не
        # мають: відповідь була не на те питання, а виглядала як відповідь.
        env.suggest("registry.collectors",
                    "чим збирати опис фонду на цій машині")
    return env


@op("fond.rows", summary="Справи фонду за описом: що існує, що вже завантажено",
    args=FondRowsArgs, mutates=False, agent=False, section="material")
def fond_rows(a: FondRowsArgs) -> Envelope:
    from nyshporka.fonds import registry as R

    found = {f["id"]: f for f in R.discover_fonds()}
    f = found.get(a.fond)
    if f is None:
        known = ", ".join(sorted(found)) or "(жодного)"
        return fail(f"фонду «{a.fond}» немає серед реєстрів опису. Є: {known}")

    rows = R.load_rows(a.fond)
    live = R.live_on_disk(f["repo"], f["fond"])
    conf = R.conflicts_index(a.fond)
    # 🔴 Кадри на диску — четвертим аргументом `row_status`. Без них прапорець
    # `partial` («завантажено меншу частину справи») не виставлявся ніколи:
    # гілка в `registry.row_status` є, поріг `_PARTIAL_RATIO` є, CLI цей
    # аргумент передає — а операція мовчала, тобто недовантажена справа
    # виглядала так само, як повна.
    frames = R.live_frames(f["repo"], f["fond"])
    sel = R.filter_rows(rows, opys=a.opys, q=a.q, surname=a.surname, year=a.year,
                        uezd=a.uezd, state=a.state, live=live)
    if a.spr:
        # Точковий вхід із бібліотеки чи газетира: там уже знають номер справи,
        # і шукати його підрядком у заголовку означало б не знайти нічого.
        want = a.spr.strip().lower()
        sel = [r for r in sel if str(r.get("spr") or "").strip().lower() == want]
    size = a.page_size or a.limit
    start = max(0, a.page) * size
    out = []
    for r in sel[start:start + size]:
        st = R.row_status(r, live, conf, frames)
        out.append({"shifra": r.get("shifra"), "opys": r.get("opys"),
                    "spr": r.get("spr"), "title": r.get("title"),
                    # 🔴 Номер і літера — різні поля, і зводити їх в одне
                    # не можна: «40» і «40е» це різні книги, а реєстр
                    # шукає рядок саме за парою. Доти наверх ішов лише
                    # склеєний `spr`, і будь-який споживач, якому треба
                    # знайти рядок, розбирав його рядковими операціями
                    # заново — тобто з певною ймовірністю не знаходив.
                    "spr_int": r.get("spr_int"),
                    "spr_letter": r.get("spr_letter") or "",
                    # 🔴 Спільний ключ трьох реєстрів. Складається тут, поруч
                    # із джерелом `repo`/`fond`, а не в браузері: складений на
                    # тому боці, він розійшовся б із бібліотечним тихо, і
                    # кнопка «показати в бібліотеці» відкривала б порожньо.
                    "key": f"{f['repo']}/{f['fond']}/{r.get('spr')}",
                    "repo": f["repo"], "fond": f["fond"],
                    "year_from": r.get("year_from"), "year_to": r.get("year_to"),
                    "folios": r.get("folios"), "fs_film": r.get("fs_film"),
                    # 🔴 Плівка — окремий канал, не позначка. Наверх ішов
                    # самий номер, тобто його можна було прочитати й не
                    # можна було ним скористатись: ні адреси, ні числа
                    # кадрів, ні того, що саме на плівці знято. Для
                    # справи, якої немає ні на Commons, ні в переглядачі
                    # архіву, це буває єдиний спосіб її побачити.
                    "fs_url": r.get("fs_url"), "fs_dgs": r.get("fs_dgs"),
                    "fs_frames": r.get("fs_frames"),
                    "fs_place": r.get("fs_place"),
                    "fs_record_type": r.get("fs_record_type"),
                    "commons_url": r.get("commons_url"),
                    "on_disk": st["on_disk_live"], "state": st["disk_state"],
                    # 🔴 Чи можна взяти одним кліком — рахується тут, де видно
                    # самі адреси. Браузер бачить лише `commons_url`, а качає
                    # застосунок за `archium_url`/`commons_title`; вгадування на
                    # тому боці дало б кнопку, яка відмовляє після кліку.
                    "takeable": bool(r.get("archium_url") or r.get("commons_title")),
                    "flags": st["flags"], "conflicts": st["conflicts"],
                    # 🔴 Розходження порядково, а не лише числом у зведенні.
                    # «17 справ розходяться» не каже, які саме, — і людина
                    # мусила вгадувати, котрому рядку не вірити.
                    "disk_mismatch": st["disk_mismatch"],
                    # Скільки важить скан і скільки в ньому сторінок. Це не
                    # прикраса: 25 МБ проти 771 МБ на тій самій справі означає
                    # обрізане дзеркало, і качати з нього — змарнувати ніч.
                    "commons_size": r.get("commons_size"),
                    "commons_pages": r.get("commons_pages"),
                    "commons_files": r.get("commons_files"),
                    "mirror_size": r.get("mirror_size"),
                    "truncated_mirror": r.get("truncated_mirror"),
                    "archium_url": r.get("archium_url"),
                    # ⚠ `None` тут означає «схема цього фонду такого поля не
                    # знає», а `""` — «знає, порожньо». Зводити їх до одного
                    # означало б показати прочерк там, де насправді незнання.
                    "dv_no": r.get("dv_no"),
                    # Наскільки можна вірити самому номеру справи й рядку опису.
                    "num_src": r.get("num_src"),
                    "page_quality": r.get("page_quality"),
                    "src_page": r.get("src_page"),
                    # Альтернативні прочитання заголовка: OCR опису б'ється з
                    # назвою на Commons частіше, ніж здається.
                    "title_alt": r.get("title_alt"),
                    "commons_title": r.get("commons_title"),
                    "surnames": r.get("surnames"),
                    # Скільки кадрів лежить проти скількох мало б бути.
                    # `row_status` рахує з них лише прапорець `partial`; самі
                    # числа потрібні, щоб сказати «завантажено 100 з 207», а не
                    # просто «неповно».
                    "frames_disk": frames.get(
                        (r.get("opys") or "", r.get("spr_int") or "",
                         r.get("spr_letter") or "")) or None,
                    "frames_expected": R.expected_frames(r) or None})
    # 🔴 Знаменник рахується по всьому фонду, а не по фільтру: інакше «5 справ»
    # читалось би як «у фонді п'ять справ», а не «п'ять із семи тисяч».
    summary = R.summarize(rows, live)
    pages = (len(sel) + size - 1) // size if size else 0
    env = ok({"fond": f["label"], "fond_id": f["id"], "rows": out,
              "shown": len(out), "matched": len(sel), "total": len(sel),
              "page": a.page, "page_size": size, "pages": pages,
              "summary": summary,
              "schema": f.get("schema") or "",
              # 🔴 Фасети рахувались і не виходили нікуди. Без них фільтр
              # «опис» і «повіт» довелося б набирати наосліп, не знаючи ні
              # переліку, ні того, скільки справ за кожним, — а лічильник тут
              # і є відповіддю на «чи варто туди дивитись».
              # ⚠ По всьому фонду, а не по видачі: інакше перелік звужувався б
              # разом із фільтром і перестав би бути мапою фонду.
              "facets": R.facets(rows, f["id"]),
              # Прізвища з алфавітки архіву. Порожньо — законний стан
              # («алфавітки для цього фонду немає»), а не поломка.
              "surnames": R.surname_list(f["id"]),
              # Покриття по описах: скільки номерів в описі взагалі є і
              # скількох ми не бачимо. `None` = не рахувалось.
              "coverage": R.load_coverage(f["id"])})
    if summary.get("disk_mismatch"):
        env.warn("disk_mismatch",
                 f"колонка «на диску» в реєстрі розходиться з бібліотекою у "
                 f"{summary['disk_mismatch']} справах — показано живий стан")
    if not sel:
        env.warn("nothing_matched",
                 f"під фільтр не підпало нічого з {summary['rows']} справ опису")
    return env



class FondCaseArgs(BaseModel):
    fond: str = Field(description="id фонду: dahmo_230")
    opys: str = Field(description="номер опису")
    spr: str = Field(description="номер справи")
    letter: str = Field("", description="літера справи, якщо є: 24а")


@op("fond.case", summary="Картка справи з реєстру опису: усе, що про неї відомо",
    args=FondCaseArgs, mutates=False, agent=False, section="material")
def fond_case(a: FondCaseArgs) -> Envelope:
    """Повний розбір одного рядка опису.

    🔴 Рядок таблиці показує сім полів із п'ятдесяти двох. Решта — не дрібниця:
    саме там лежить, звідки взято заголовок, чи є альтернативне прочитання, з
    яких файлів складається скан, чи ріже його дзеркало, чому номер справи
    вважається відновленим і на якій сторінці опису його звіряти. Без цього
    рядок є твердженням без доказу, а перевірити його нічим.
    """
    from nyshporka.fonds import registry as R

    found = {f["id"]: f for f in R.discover_fonds()}
    f = found.get(a.fond)
    if f is None:
        known = ", ".join(sorted(found)) or "(жодного)"
        return fail(f"фонду «{a.fond}» немає серед реєстрів опису. Є: {known}")

    row, path = R.registry_row(f["repo"], f["fond"], a.opys, a.spr, a.letter)
    if row is None:
        return fail(f"справи {a.opys}-{a.spr}{a.letter} немає в {path.name}")

    live = R.live_on_disk(f["repo"], f["fond"])
    frames = R.live_frames(f["repo"], f["fond"])
    st = R.row_status(row, live, R.conflicts_index(a.fond), frames)
    env = ok({"row": row, "status": st, "registry": str(path),
              "fond": f["label"], "repo": f["repo"],
              "key": f"{f['repo']}/{f['fond']}/{row.get('spr')}",
              "expected_frames": R.expected_frames(row) or None})
    if st.get("disk_mismatch"):
        env.warn("disk_mismatch",
                 "реєстр каже одне, бібліотека інше — показано живий стан диска")
    if row.get("num_src") == "interp":
        env.warn("interp_number",
                 f"номер справи відновлено між якорями, не прочитано — звірити "
                 f"оком сторінку опису {row.get('src_page') or '?'}")
    if row.get("truncated_mirror"):
        env.warn("truncated",
                 "дзеркало віддає цю справу обрізаною — качати з нього марно")
    return env


class FondTakeArgs(BaseModel):
    key: str = Field(description="ключ справи: DAHMO/230/43 або DAHMO/230/1/43")
    force: bool = Field(default=False, description="перезаписати вже завантажене")


@op("fond.take", summary="Узяти справу з опису: завантажити й зареєструвати",
    args=FondTakeArgs, mutates=True, long=True, agent=False, section="material")
def fond_take(a: FondTakeArgs) -> Envelope:
    """Від рядка опису до теки на диску — одним кроком.

    🔴 Досі цей крок жив лише в командному рядку дослідницького конвеєра, тож
    рядок опису в браузері був тупиком: «скан є, не взято» — і нічим узяти.
    Логіка не була відокремлена від друку в консоль; тепер вона в
    `cases.take`, і обидва входи кличуть одне й те саме.

    🔴 Приймач — бібліотека, а не код завершення: тека без паспорта невидима
    для всього, що йде далі, і прогін по ній ляже нічиїм.
    """
    from nyshporka.cases import take as T

    try:
        got = T.take(a.key, force=a.force)
    except T.TakeError as exc:
        return fail(str(exc))
    env = ok(got)
    if got.get("shifra_needs_eye"):
        # ⚠ Узяти можна, вірити шифрі — ні. Номер відновлено інтерполяцією за
        # сусідами в опису, і помилка тут дає правдоподібну шифру на чужій
        # справі — найдорожчий рід помилки в обліку.
        env.warn("shifra_needs_eye",
                 "номер справи в описі відновлено, а не прочитано — звірте "
                 "шифру оком по титулу, перш ніж на неї посилатись")
    if got.get("in_library") is False:
        env.warn("not_in_library",
                 "справи не видно в бібліотеці — перевірте теку й `meta.json`")
    else:
        env.suggest("library.list", "справа в бібліотеці — можна читати")
    return env

# ── 🧾 збирачі реєстру опису ─────────────────────────────────────────────────
# Той самий домен, що й решта цього модуля: знання про архів, а не про нашу
# роботу. І та сама стеля агентських tool'ів — тому `agent=False`.
class CollectorsArgs(BaseModel):
    pass


class CollectArgs(BaseModel):
    collector: str = Field(..., description="id збирача: archium | commons | duck")
    repo: str = Field(..., description="код архіву: CDIAK, ДАХмО…")
    fond: str = Field(..., description="номер фонду")
    opys: str = Field("", description="описи через кому; порожньо — всі")
    refresh: bool = Field(False, description="не читати кеш")
    dry_run: bool = Field(False, description="лише порахувати, нічого не писати")
    fond_id: str = Field("", description="внутрішній номер фонду на сайті архіву")
    # ⚠ Вимикається лише тим, хто збирає кількома джерелами поспіль:
    # зводити після кожного означало б перезводити той самий реєстр
    # стільки разів, скільки джерел.
    merge: bool = Field(True, description="звести зібране в реєстр опису")


def _target(repo_raw: str, fond: str, opys: str = "") -> Any:
    from nyshporka.archives import active
    from nyshporka.fonds.collect import Target

    repo = repo_raw.strip()
    # Архів можна назвати і кодом (`CDIAK`), і як його пишуть люди (`ЦДІАК`).
    pack = active()
    if repo.upper() not in pack.repositories:
        for code, r in pack.repositories.items():
            if r.label.casefold() == repo.casefold():
                repo = code
                break
    return Target(repo=repo.upper(), fond=fond.strip(),
                  opys=tuple(o.strip() for o in opys.split(",") if o.strip()))


@op("registry.collectors", summary="Які збирачі реєстру опису є і що кожен уміє",
    mutates=False, agent=False, section="material")
def registry_collectors(_: NoArgs) -> Envelope:
    """Перелік збирачів.

    ⚠ Порожній перелік — це стан, а не поломка: збирачі тягнуть extras
    `archives`, і без них пакет усе одно вміє читати вже зібраний реєстр.
    """
    from nyshporka.fonds import collect

    reg = collect.load()
    env = ok({"collectors": [
        {"id": c.id, "label": c.label, "file": c.filename,
         "source": c.source_id, "caps": sorted(c.caps)} for c in reg.all()]})
    for name, why in reg.broken:
        env.warn("collector_broken", f"{name}: {why}")
    if not reg.all():
        env.warn("no_collectors",
                 "жодного збирача — реєстр опису можна читати, але не складати. "
                 "Це стан, а не помилка: pip install 'nyshporka[archives]'")
    return env


@op("registry.plan", summary="Скільки коштуватиме збирання й чого для нього бракує",
    args=CollectArgs, mutates=False, agent=False, section="material")
def registry_plan(a: CollectArgs) -> Envelope:
    """Що принесе збирання — до того, як воно почалось.

    Те саме, чим маніфест є для завантаження: фонд на три тисячі справ при
    п'яти запитах на десять секунд збирається десятки хвилин, і питання
    «скільки це» мусить мати відповідь до старту.
    """
    from nyshporka.fonds import collect

    c = collect.load().get(a.collector)
    if c is None:
        return fail(f"збирача «{a.collector}» немає — див. `nysh registry sources`")
    return ok(c.plan(_target(a.repo, a.fond, a.opys)).as_dict())


class MergeArgs(BaseModel):
    repo: str = Field(..., description="код архіву: CDIAK, ДАХмО…")
    fond: str = Field(..., description="номер фонду")
    dry_run: bool = Field(False, description="лише порахувати, нічого не писати")
    fond_id: str = Field("", description="тека фонду, якщо вона не збігається з кодом архіву й номером")


@op("registry.merge",
    summary="Звести джерела опису в реєстр фонду, чергу розбіжностей і покриття",
    args=MergeArgs, mutates=True, long=True, agent=False, section="material")
def registry_merge(a: MergeArgs) -> Envelope:
    """Останній крок конвеєра реєстру: з багатьох джерел — один реєстр.

    🔴 Покриття рахується лише там, де відомі межі описів. Без них частка була б
    вигадана, а «0/0 · немає 0» читається як «усе на місці» — тому знаменника
    немає і в конверті, а не підставлено нуль.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.fonds.merge.run import MergeError, merge_fond
    from nyshporka.fonds.registry import fond_path, registry_dir

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))

    target = _target(a.repo, a.fond)
    # ⚠ Тека фонду виводиться з коду архіву й номера (`cdiak_224`), але на диску
    # вона могла з'явитись раніше й під іншим кодом того самого архіву. Хто вже
    # знає точну теку — називає її, і тоді реєстр не роздвоюється.
    fond_id = a.fond_id.strip() or target.fond_id
    try:
        res = merge_fond(
            target, dest=ws.root / registry_dir(fond_id),
            out=ws.root / fond_path(fond_id),
            library=ws.root / "data" / "derived" / "case_library.json",
            dry_run=a.dry_run)
    except MergeError as exc:
        return fail(str(exc))

    env = ok(res.as_dict())
    for b in res.blind:
        env.warn(f"blind_{b.kind}", b.why)
    # Покриття джерел: одне на кожне ім'я, включно З нулем. «Джерела не було» і
    # «джерело дало нуль» — різні відповіді, і плутати їх означає ховати
    # прогалину.
    for name, n in res.sources:
        env.coverage.append(CoverageItem(source=name, rows=n, scope=target.fond_id))
    return env


@op("registry.collect", summary="Зібрати перелік справ фонду в registry/*.tsv",
    args=CollectArgs, mutates=True, long=True, agent=False, section="material")
def registry_collect(a: CollectArgs) -> Envelope:
    """Скласти те, що досі можна було лише прочитати.

    🔴 Відповідь несе не лише число рядків. Позиційний розбір таблиці опису вже
    одного разу віддав 2944 справи з однаковим заголовком і нулем аркушів — за
    числом рядків це виглядало повним успіхом. Тому поруч їдуть `quality`
    (скільки рядків мають роки, аркуші, заголовок) і `blind` (чого джерело не
    бачить або не вважає справою).
    """
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.fonds import collect
    from nyshporka.fonds.registry import registry_dir

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))

    reg = collect.load(ws.root)
    c = reg.get(a.collector)
    if c is None:
        return fail(f"збирача «{a.collector}» немає — див. `nysh registry sources`")

    target = _target(a.repo, a.fond, a.opys)
    plan = c.plan(target)
    if not plan.ready and not a.fond_id:
        return fail(plan.why or f"{c.label}: збирати нічим")

    dest = ws.root / registry_dir(target.fond_id)
    kw: dict[str, Any] = {"refresh": a.refresh, "dry_run": a.dry_run}
    # Внутрішній номер фонду розуміє не кожен збирач — передаємо лише тому, хто
    # його просить, інакше решта падала б на несподіваному аргументі.
    if a.fond_id and "fond_id" in getattr(c.collect, "__annotations__", {}):
        kw["fond_id"] = a.fond_id
    res = c.collect(target, dest=dest, **kw)
    env = ok(res.as_dict())
    for b in res.blind:
        env.warn(f"blind_{b.kind}", f"{b.count}: {b.why}")
    if res.kept:
        env.warn("kept_untouched",
                 f"збережено {res.kept} рядків описів, яких цей запуск не чіпав")
    # 🔴 Зібране саме по собі реєстру не міняє: воно лягло окремим файлом
    # джерела. Сказати наступний крок треба тут, інакше `collect` виглядає
    # обіцянкою без виходу — файли з'явились, а реєстр опису той самий.
    if a.dry_run or not a.merge:
        env.warn("merge_next",
                 "проба: зібране нікуди не лягло, тож і зводити нема чого"
                 if a.dry_run else
                 "зібране лягло окремим файлом; реєстр зведеться після "
                 "решти джерел")
        return env

    # 🔴 Зведення — частина збирання, а не наступна дія людини.
    #
    # Обхід кладе свій файл у `registry/<фонд>/`, а реєстр опису читається з
    # іншого файла — зведеного. Доти, доки ці кроки були розділені, «Зібрати
    # опис» закінчувалось так: робота «готово», 229 справ у файлі — і екран
    # описів, який каже «реєстру опису ще не збирали». Людина зробила все
    # правильно й дістала порожнечу, а порада звести лежала текстом у черзі.
    #
    # ⚠ Зводяться всі джерела фонду, не лише щойно зібране, — саме тому це
    # безпечно робити щоразу: другий збирач не загубиться, а повторний запуск
    # просто перезведе те саме.
    # ⚠ `fond_id` не передається: у збирача це внутрішній номер фонду на сайті
    # архіву, а в зведенні — тека фонду на диску. Однакове ім'я, різні речі;
    # передавши одне замість іншого, реєстр роздвоївся б у теку з чужим ім'ям.
    merged = registry_merge(MergeArgs(repo=a.repo, fond=a.fond, dry_run=False,
                                      fond_id=""))
    if not merged.ok:
        env.warn("merge_failed",
                 f"зібране лягло у файл джерела, але звести його в реєстр не "
                 f"вийшло: {merged.error}")
        env.suggest("registry.merge", "спробувати звести ще раз")
        return env
    data = merged.data or {}
    env.data["merged"] = data
    env.warn("merged_into_registry",
             f"зібране зведено в реєстр опису: "
             f"{data.get('rows') or 0} справ у фонді {a.repo} {a.fond}")
    env.suggest("fond.list", "подивитись опис фонду")
    return env


class BuildArgs(BaseModel):
    repo: str = Field(..., description="код архіву: CDIAK, ДАХмО…")
    fond: str = Field(..., description="номер фонду")
    opys: str = Field("", description="описи через кому; порожньо — всі")
    refresh: bool = Field(False, description="не читати кеш")
    fond_id: str = Field("", description="внутрішній номер фонду на сайті "
                                         "архіву — потрібен не всім збирачам")


@op("registry.build",
    summary="Зібрати опис фонду всіма доступними джерелами і звести в реєстр",
    args=BuildArgs, mutates=True, long=True, agent=False, section="material")
def registry_build(a: BuildArgs) -> Envelope:
    """Одна дія замість вибору джерела.

    🔴 Який саме сайт віддав рядок — наша механіка, а не рішення дослідника.
    Доти людина мусила обрати збирача зі списку, зібрати ним, потім (можливо)
    згадати про другий і зібрати ще раз, і аж тоді звести. Кожен із цих кроків
    вона робила, не маючи чим відповісти на питання «а котрий з них знає мій
    фонд» — відповідь знає план, і питати про неї треба не людину.

    🔴 Джерело, яке не готове, пропускається з поясненням, а не валить дію.
    Причини різні й нормальні: archium адресує фонд власним внутрішнім
    номером, Commons знає лише те, що хтось виклав. Один невдалий збирач не
    привід не взяти те, що дають інші, — але й мовчати про нього не можна:
    тоді реєстр виглядав би повнішим, ніж він є.

    ⚠ Зведення робиться один раз, після всіх обходів. Тому кожен збирач тут
    викликається з `merge=False`: інакше той самий реєстр перезводився б
    стільки разів, скільки джерел.
    """
    from nyshporka.core import progress
    from nyshporka.fonds import collect as C

    reg = C.load()
    all_collectors = list(reg.all())
    if not all_collectors:
        env = fail("жодного збирача — реєстр опису нема чим складати")
        env.warn("no_collectors",
                 "це стан, а не поломка: pip install 'nyshporka[archives]'")
        return env

    took: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    total = len(all_collectors)
    for i, c in enumerate(all_collectors, 1):
        progress.report(i - 1, total, f"джерел: {c.id}")
        args = CollectArgs(collector=c.id, repo=a.repo, fond=a.fond,
                           opys=a.opys, refresh=a.refresh, dry_run=False,
                           fond_id=a.fond_id, merge=False)
        plan = registry_plan(args)
        if not plan.ok:
            skipped.append({"collector": c.id, "why": plan.error})
            continue
        pd = plan.data or {}
        if not pd.get("ready"):
            # `why` збирача пояснює причину людською мовою — саме її й треба
            # показати, а не «не вийшло».
            skipped.append({"collector": c.id,
                            "why": pd.get("why") or "джерело не готове"})
            continue
        got = registry_collect(args)
        if not got.ok:
            skipped.append({"collector": c.id, "why": got.error})
            continue
        gd = got.data or {}
        took.append({"collector": c.id, "rows": gd.get("rows") or 0,
                     "out": str(gd.get("out") or "")})
    progress.report(total, total, "джерел")

    data: dict[str, Any] = {"took": took, "skipped": skipped,
                            "collectors": total}
    if not took:
        env = ok(data)
        for s in skipped:
            env.warn("source_skipped", f"{s['collector']}: {s['why']}")
        env.warn("nothing_collected",
                 f"жодне з {total} джерел не змогло зібрати цей фонд — "
                 f"реєстр лишився таким, як був")
        return env

    merged = registry_merge(MergeArgs(repo=a.repo, fond=a.fond, dry_run=False,
                                      fond_id=""))
    if not merged.ok:
        env = ok(data)
        env.warn("merge_failed",
                 f"джерела зібрано, але звести їх у реєстр не вийшло: "
                 f"{merged.error}")
        env.suggest("registry.merge", "спробувати звести ще раз")
        return env

    md = merged.data or {}
    data["merged"] = md
    env = ok(data)
    # 🔴 Пропущені джерела називаються завжди, навіть коли решта дала багато:
    # реєстр із двох джерел і реєстр із трьох — різні знаменники для майбутнього
    # «такої справи в архіві не існує».
    for s in skipped:
        env.warn("source_skipped", f"{s['collector']}: {s['why']}")
    env.warn("built",
             f"опис зібрано з {len(took)} джерел ({', '.join(x['collector'] for x in took)})"
             + (f", пропущено {len(skipped)}" if skipped else "")
             + f" — у реєстрі {md.get('rows') or 0} справ фонду {a.repo} {a.fond}")
    env.suggest("fond.list", "подивитись опис фонду")
    return env
