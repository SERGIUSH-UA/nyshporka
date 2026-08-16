"""🗺🏛 Операції довідників: газетир, реєстр опису фонду, стан каталогу.

Три вкладки дослідницької консолі, яких у продуктовому застосунку не було:
«🗺 Газетир», «🏛 Фонди» і стан довідників. Тут вони з'являються так, як
належить у цьому пакеті, — **операціями, а не роутами**: один опис живить
браузер, командний рядок і агента, тож три обличчя не можуть розійтись у
відповідях.

Чому це окремий модуль, а не хвіст `ops_builtin`: домен у них спільний і
самостійний (довідники про АРХІВ, а не про нашу роботу), і читаються вони разом.

🔑 **Головна відмінність від решти операцій — покриття.** Кожна відповідь тут
несе `coverage`: у чому саме шукали і якого воно зрізу. Без цього «нічого не
знайдено» не відрізнити від «ніде не шукали», а в генеалогії ця плутанина
найдорожча — «немає» закриває напрям назавжди.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import CoverageItem, Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


# 🔴 УСІ операції цього модуля — `agent=False`, і це не забудькуватість.
#
# Перелік агентських tool'ів має СТЕЛЮ 18 (`mcp.server.TOOL_LIMIT`), і вона не
# технічна: далі модель перестає дочитувати описи й починає вгадувати, а
# вгадування коштує дорожче за відсутність інструмента. П'ять нових операцій
# підняли б перелік до 23, тобто зламали б рівно те, заради чого стеля стоїть.
#
# Тому довідники з'являються в БРАУЗЕРІ й КОМАНДНОМУ РЯДКУ (де переліку ніхто не
# «дочитує», і зайвий пункт нічого не псує), а агентська поверхня лишається
# незмінною. Це свідома неповнота, а не недогляд.
#
# ⚠ Питання «що саме має бути серед вісімнадцяти» — не моє: газетир, можливо,
# цінніший для агента за котрийсь із наявних tool'ів, але вирішувати, кого
# посунути, має власник. Природний кандидат на злиття — наявний
# `catalog.search` («де взагалі є щось про моє село»): він відповідає на ТЕ САМЕ
# питання, тільки не заглядаючи в газетир, тобто сьогодні мовчить про найкращу
# доступну відповідь.


def _coverage_of(answer: Any) -> list[CoverageItem]:
    """`catalog.query.Answer.coverage` → покриття конверта."""
    return [CoverageItem(source=c.pack_id, taken=c.taken, rows=c.rows,
                         scope=c.scope) for c in answer.coverage]


# ── 🗺 газетир: від СЕЛА до справ по всіх фондах ─────────────────────────────
#
# 🔑 Зворотний напрям до реєстру опису, і найчастіше починають саме з нього:
# людина знає СЕЛО, а не фонд. Реєстр опису на це відповісти не може — він знає
# один фонд і мовчить про сусідні.

class GeogFindArgs(BaseModel):
    q: str = Field(default="", description="назва села: укр, рос або латинкою")
    uezd: str = Field(default="", description="повіт або губернія")
    fond: str = Field(default="", description="лише де є справи цього фонду")
    section: str = Field(default="",
                         description="church | decanats | rabbinate; "
                                     "порожньо — усі конфесії")
    limit: int = Field(default=40, ge=1, le=200)


@op("geog.find", summary="Де взагалі є метрики цього села — по ВСІХ фондах архіву",
    args=GeogFindArgs, mutates=False, agent=False)
def geog_find(a: GeogFindArgs) -> Envelope:
    """Пошук поселення в довідниках.

    🕍 Конфесія — ФІЛЬТР, а не три окремі газетири. Метрики православної
    громади, костелу й рабинату одного містечка лежать у РІЗНИХ фондах
    (Бердичів — 283, 95 і 1), тож шукати лише в православному розділі означає
    систематично не бачити двох третин. Дефолт — усі розділи.
    """
    from nyshporka.catalog.query import CatalogMissing, find_places

    try:
        ans = find_places(a.q, limit=a.limit, uezd=a.uezd, fond=a.fond,
                          section=a.section)
    except CatalogMissing as exc:
        # 🔴 Відмова, а не порожній список. Джерело, яке НЕ МОЖЕ шукати, не
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


@op("geog.card", summary="Картка поселення: церква, УСІ справи, що з них у нас є",
    args=GeogCardArgs, mutates=False, agent=False)
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
        # М'якохід — усі з метриками XVIII ст. Побачити цей список ДО пошуку
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
    mutates=False, agent=False)
def catalog_packs(_: NoArgs) -> Envelope:
    """Стан каталогу — щоб «нічого не знайдено» можна було пояснити.

    ⚠ Зіпсовані паки НЕ ховаються: «немає» і «зіпсоване» лікуються по-різному
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
                 "довідників немає — пошук по каталогах архівів недоступний, "
                 "і його нуль нічого не означатиме")
    for p in packs:
        if not p.ok:
            env.warn("pack_broken", f"{p.pack_id}: {p.problem}")
    return env


# ── 🏛 реєстр опису фонду: «що взагалі існує в архіві» ───────────────────────
#
# Третє сховище поруч із бібліотекою («що ми маємо») і реєстром справ («що ми
# зробили»). Плутати їх дорого: «справи немає» з бібліотеки означає «не
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
                       description="disk | todo | mirror_only | order | scan")
    limit: int = Field(default=50, ge=1, le=500)


@op("fond.list", summary="Які фонди описано: скільки справ, скільки вже в нас",
    mutates=False, agent=False)
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
                    "scans": s["commons"] + s["mirror_only"]})
    env = ok({"fonds": out, "shown": len(out)})
    if not out:
        env.warn("no_registries",
                 "жодного реєстру опису немає — сказати «справи в архіві не "
                 "існує» нема на чому")
        env.suggest("catalog.packs", "перевірити, чи встановлено довідники")
    return env


@op("fond.rows", summary="Справи фонду за описом: що існує, що вже завантажено",
    args=FondRowsArgs, mutates=False, agent=False)
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
    sel = R.filter_rows(rows, opys=a.opys, q=a.q, surname=a.surname, year=a.year,
                        uezd=a.uezd, state=a.state, live=live)
    out = []
    for r in sel[: a.limit]:
        st = R.row_status(r, live, conf)
        out.append({"shifra": r.get("shifra"), "opys": r.get("opys"),
                    "spr": r.get("spr"), "title": r.get("title"),
                    "year_from": r.get("year_from"), "year_to": r.get("year_to"),
                    "folios": r.get("folios"), "fs_film": r.get("fs_film"),
                    "commons_url": r.get("commons_url"),
                    "on_disk": st["on_disk_live"], "state": st["disk_state"],
                    "flags": st["flags"], "conflicts": st["conflicts"]})
    # 🔴 Знаменник рахується по ВСЬОМУ фонду, а не по фільтру: інакше «5 справ»
    # читалось би як «у фонді п'ять справ», а не «п'ять із семи тисяч».
    summary = R.summarize(rows, live)
    env = ok({"fond": f["label"], "fond_id": f["id"], "rows": out,
              "shown": len(out), "matched": len(sel), "summary": summary})
    if summary.get("disk_mismatch"):
        env.warn("disk_mismatch",
                 f"колонка «на диску» в реєстрі розходиться з бібліотекою у "
                 f"{summary['disk_mismatch']} справах — показано ЖИВИЙ стан")
    if not sel:
        env.warn("nothing_matched",
                 f"під фільтр не підпало нічого з {summary['rows']} справ опису")
    return env
