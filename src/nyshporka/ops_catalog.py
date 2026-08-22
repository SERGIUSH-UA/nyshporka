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
    args=GeogFindArgs, mutates=False, agent=False, section="material")
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
    mutates=False, agent=False, section="material")
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
                       description="disk | todo | film | mirror_only | order | scan; `film` = вільна плівка FS (качається за DGS), `order` = каналу немає зовсім")
    limit: int = Field(default=50, ge=1, le=500)


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
                    "scans": s["commons"] + s["mirror_only"]})
    env = ok({"fonds": out, "shown": len(out)})
    if not out:
        env.warn("no_registries",
                 "жодного реєстру опису немає — сказати «справи в архіві не "
                 "існує» нема на чому")
        env.suggest("catalog.packs", "перевірити, чи встановлено довідники")
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


# ── 🧾 збирачі реєстру опису ─────────────────────────────────────────────────
# Той самий домен, що й решта цього модуля: знання про АРХІВ, а не про нашу
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


def _target(a: CollectArgs) -> Any:
    from nyshporka.archives import active
    from nyshporka.fonds.collect import Target

    repo = a.repo.strip()
    # Архів можна назвати і кодом (`CDIAK`), і як його пишуть люди (`ЦДІАК`).
    pack = active()
    if repo.upper() not in pack.repositories:
        for code, r in pack.repositories.items():
            if r.label.casefold() == repo.casefold():
                repo = code
                break
    return Target(repo=repo.upper(), fond=a.fond.strip(),
                  opys=tuple(o.strip() for o in a.opys.split(",") if o.strip()))


@op("registry.collectors", summary="Які збирачі реєстру опису є і що кожен уміє",
    mutates=False, agent=False, section="material")
def registry_collectors(_: NoArgs) -> Envelope:
    """Перелік збирачів.

    ⚠ Порожній перелік — це СТАН, а не поломка: збирачі тягнуть extras
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
    """Що принесе збирання — ДО того, як воно почалось.

    Те саме, чим маніфест є для завантаження: фонд на три тисячі справ при
    п'яти запитах на десять секунд збирається десятки хвилин, і питання
    «скільки це» мусить мати відповідь до старту.
    """
    from nyshporka.fonds import collect

    c = collect.load().get(a.collector)
    if c is None:
        return fail(f"збирача «{a.collector}» немає — див. `nysh registry sources`")
    return ok(c.plan(_target(a)).as_dict())


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

    target = _target(a)
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
    # 🔴 Зібране ще не злите. Сказати це треба тут, інакше `registry collect`
    # виглядає обіцянкою без виходу: файли з'явились, а реєстр опису той самий.
    env.warn("merge_pending",
             "зібране лягло в registry/ окремим файлом; зведення джерел в один "
             "реєстр опису — окремий крок, якого в цій версії ще немає")
    return env
