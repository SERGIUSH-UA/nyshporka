"""⚙️ Операції, доступні зараз.

Перелік навмисно короткий: сюди потрапляє лише те, чий домен уже в пакеті.
Дописувати операції «на майбутнє» не можна — tool, який відповідає «ще не
реалізовано», гірший за відсутній: агент витрачає на нього хід і довіру.

Імпорт цього модуля наповнює `core.ops.REGISTRY`, тож він має статись до
першого звернення до реєстру (див. `nyshporka.ops`).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field

from nyshporka.core import morph
from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

if TYPE_CHECKING:
    from nyshporka.sources.base import Source
    from nyshporka.sources.registry import Registry


# ── простір ──────────────────────────────────────────────────────────────────
@op("workspace.info", summary="Де лежить дослідження і що в ньому є")
def workspace_info(_: NoArgs) -> Envelope:
    from nyshporka.core import lock
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    holder = lock.read(ws.root)
    env = ok({
        "root": str(ws.root),
        "name": ws.name,
        "origin": ws.origin,
        "case_roots": [str(p) for p in ws.case_roots()],
        "exists": {"data": ws.data.is_dir(), "reports": ws.reports.is_dir()},
        "locked_by": holder.as_dict() if holder else None,
    })
    if not ws.data.is_dir():
        env.warn("empty_workspace",
                 "у просторі ще немає теки data — це новий простір")
    return env


# ── корені справ ─────────────────────────────────────────────────────────────
class RootArgs(BaseModel):
    path: str = Field(description="тека зі сканами: справа або контейнер справ")


# `agent=False`: оголошення кореня розширює зону, у якій застосунок читає диск.
# Це рішення людини про власний архів, а не крок конвеєра; агент може порадити,
# але не зробити.
@op("roots.list", summary="Де застосунок шукає справи", agent=False, private=True)
def roots_list(_: NoArgs) -> Envelope:
    """Перелік місць, звідки беруться справи, — з оголошеного, а не з наявного.

    🔴 Різниця не косметична. Перелік «що зараз існує» мовчки губить корінь на
    від'єднаному диску: людина бачить порожнє місце рівно там, де їй потрібна
    причина, чому справи зникли з переліків, — і читає це як поламку. Тому
    оголошене показуємо завжди, а недосяжне позначаємо.
    """
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    rows = [{"path": str(ws.raw), "kind": "space", "gone": not ws.raw.is_dir()}]
    rows += [{"path": str(p), "kind": "declared", "gone": not p.is_dir()}
             for p in ws.extra_case_roots]
    env = ok({"roots": rows, "declared": len(ws.extra_case_roots)})
    gone = [r["path"] for r in rows if r["gone"]]
    if gone:
        env.warn("root_gone",
                 f"цих тек зараз немає на місці: {', '.join(str(g) for g in gone)} — "
                 f"справи звідти зникнуть із переліків до наступної збірки")
    return env


@op("roots.add", summary="Оголосити теку зі сканами поза простором",
    args=RootArgs, agent=False, mutates=True)
def roots_add(a: RootArgs) -> Envelope:
    """Обхід бачитиме теку там, ДЕ вона лежить. Файли не переносяться.

    ⚠ Шифра тут, на відміну від заведення справи, не потрібна: контейнер із
    десятками книг справою не є, і дати йому шифру означало б оголосити їх усі
    однією справою.
    """
    from nyshporka.core.workspace import WorkspaceError, add_case_root

    try:
        root = add_case_root(a.path)
    except WorkspaceError as exc:
        return fail(str(exc))
    env = ok({"path": str(root)})
    env.warn("rebuild_needed",
             "теку оголошено, але в переліках справи звідти з'являться після "
             "перезбірки реєстру")
    env.suggest("cases.build", "зібрати реєстр, щоб побачити справи з нового кореня")
    return env


@op("roots.remove", summary="Зняти оголошений корінь; файли лишаються",
    args=RootArgs, agent=False, mutates=True)
def roots_remove(a: RootArgs) -> Envelope:
    """Зникає лише видимість. Скани лишаються на місці — жодного файлу не чіпаємо.

    🔴 Зворотна дія обов'язкова саме тому, що пряма робиться одним рухом і легко
    помиляється: не та тека, тимчасовий диск, флешка колеги. Доки зняти корінь
    було нічим, єдиним виходом лишалось правити маркер простору руками.
    """
    from nyshporka.core.workspace import WorkspaceError, remove_case_root

    try:
        gone = remove_case_root(a.path)
    except WorkspaceError as exc:
        return fail(str(exc))
    if not gone:
        return fail(f"такого кореня не оголошено: {a.path}")
    env = ok({"path": a.path})
    env.warn("rebuild_needed",
             "файли не чіпались; справи з цієї теки зникнуть із реєстру після "
             "перезбірки")
    env.suggest("cases.build", "перезібрати реєстр без цього кореня")
    return env


# ── дашборд головної ─────────────────────────────────────────────────────────
class PulseArgs(BaseModel):
    history_days: int = Field(default=365, ge=0, le=3650,
                              description="скільки днів історії віддати; 0 — усю")
    backfill: bool = Field(
        default=True,
        description="добудувати минуле з міток на диску, якщо журнал порожній")


# 🔴 `agent=False`. Це розкладка одного екрана, а не окреме знання: усе, що
# вона зводить, агент уже дістає точнішими операціями (`cases.list`,
# `runs.list`, `search.state`, `pages.status`). Другий tool із тими самими
# числами в іншій формі лише з'їдав би місце в переліку, який модель мусить
# дочитати до кінця, і додавав би привід звітувати зведенням замість знаменника.
@op("home.pulse", summary="Стан дослідження одним зрізом: реєстр, канон, "
                          "читання, пошук, історія",
    args=PulseArgs, agent=False)
def home_pulse(a: PulseArgs) -> Envelope:
    """Усе, що показує головна, — одним викликом.

    🔴 Одна операція, а не сім із браузера. Кожна з них самостійно перевіряє
    свіжість реєстру й читає ті самі бази, тож сім викликів означали б сім
    перевірок і — головне — сім різних зрізів на одному екрані: реєстр міг
    перезібратись між першим і сьомим запитом, і плитки почали б суперечити
    одна одній, не давши читачеві жодного натяку, котрій вірити.

    🔴 Блоки гейтяться активними секціями. Вимкнена частина застосунку не
    рахується й не приходить порожньою: нуль прочитаних сторінок у просторі, де
    читання вимкнено, — це не «нічого не прочитано», а «питання не стояло», і
    дашборд не має права видавати одне за інше.
    """
    from nyshporka.core import history, pulse
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    on = set(ws.sections)

    data: dict[str, Any] = {
        "workspace": {"root": str(ws.root), "name": ws.name,
                      "origin": ws.origin},
        "sections": {"active": sorted(on), "preset": ws.preset or ""},
        "pulse": pulse.snapshot(),
    }
    env = ok(data)

    registry = _pulse_registry(env)
    data["registry"] = registry
    data["canon"] = _pulse_canon(env)
    data["profile"] = _pulse_profile(env)
    data["reading"] = _pulse_reading(env) if "htr" in on else None
    data["search"] = _pulse_search() if "research" in on else None
    data["eye"] = _pulse_eye(registry, env) if "research" in on else None
    data["jobs"] = _pulse_jobs()
    data["machine"] = _pulse_machine()

    # 🔴 Журнал поповнюється тут, а не в диспетчері мутацій: зріз щойно
    # порахований, тож рядок коштує нуль додаткових запитів. Умова —
    # пульс зрушив із часу останнього спостереження: без неї файл ріс би на
    # кожне відкриття вкладки, а графік перетворився б на пряму з тисячі
    # однакових точок.
    data["history"] = _pulse_history(data, history, a)
    return env


def _pulse_registry(env: Envelope) -> dict[str, Any]:
    """Зведення реєстру + чесний стан «його ще не збирали»."""
    from nyshporka.cases import db

    try:
        s = db.stats()
    except Exception:
        # 🔴 `built: False`, а не нулі. «0 справ» читається як перевірений
        # результат і закриває питання; «реєстру ще немає» — як робота, яку
        # треба зробити, і поруч із ним у конверті стоїть, чим саме.
        env.warn("no_registry_yet",
                 "реєстру справ ще немає — зведення нема з чого показати")
        env.stale_because(["реєстр ще не збирали"], fix="nysh cases build")
        env.suggest("cases.build", "зібрати реєстр справ")
        return {"built": False}
    out: dict[str, Any] = {"built": True, **s}
    try:
        meta = db.index_meta()
        out["at"] = meta.get("built", "")
    except Exception:
        out["at"] = ""
    try:
        st = db.staleness()
    except Exception:
        st = {}
    if st.get("stale"):
        env.stale_because(st.get("reasons") or [], fix="nysh cases build")
    return out


def _pulse_canon(env: Envelope) -> dict[str, Any]:
    from nyshporka.storage import canon_stats

    try:
        canon = canon_stats.summary()
    except Exception as exc:
        return {"present": False, "why": f"{type(exc).__name__}: {exc}"}
    if not canon.get("present"):
        # ⚠ Банера нема. Для більшості просторів Нишпорки канону не існує
        # взагалі — його збирає дослідницький конвеєр, — тож попередження
        # висіло б угорі дашборда постійно й на другий день перестало б
        # читатись разом із тими, що поруч. Секція каже це на місці, там, де
        # число мало б стояти.
        return canon
    # ⚠ Недоведений факт виглядає в дереві так само, як доведений, тож про
    # частку без цитат мусить сказати конверт, а не лише дрібний рядок на
    # плитці: інакше вона роками лишається непоміченою.
    uncited = int(canon.get("facts_uncited") or 0)
    if uncited:
        env.warn("facts_uncited",
                 f"{uncited} фактів канону не мають жодної цитати — "
                 f"у дереві вони виглядають так само, як доведені")
    return canon


def _pulse_profile(_env: Envelope) -> dict[str, Any]:
    """Чий рід шукаємо — для кроку онбордингу на головній.

    ⚠ Банера тут БІЛЬШЕ НЕМАЄ. Він казав про відсутній профіль угорі екрана, а
    крок чекліста каже те саме на місці — і, на відміну від банера, з кнопкою.
    Два повідомлення про одне читаються як дві різні проблеми, і людина шукає
    другу.
    """
    from nyshporka.core.profile import ProfileError, active
    from nyshporka.core.workspace import WorkspaceError

    try:
        p = active()
    except (ProfileError, WorkspaceError) as exc:
        return {"present": False, "why": str(exc)}
    return {"present": True, "name": p.name, "display": p.display,
            "paradigm": p.paradigm_id, "stems": p.stems,
            "roots": [r for r, _ in p.roots],
            "spellings": len(p.all_spellings())}


#: Скільки секунд вірити попередній перевірці машини. Вона імпортує torch і
#: ходить на диск — платити цим за кожне відкриття головної не можна, а
#: змінюється вона від встановлення драйвера, не щохвилини.
_MACHINE_TTL = 300.0
_MACHINE: dict[str, Any] = {"at": 0.0, "data": None}


def _pulse_machine() -> dict[str, Any]:
    """Чи ця машина готова читати рукопис — коротко, для кроку чекліста.

    ⚠ Кеш на процес, а не на запит. `doctor.run()` перевіряє наявність карти
    (тобто імпортує torch), місце на диску й хмарну синхронізацію теки; на
    холодному старті це секунди. Крок чекліста мусить бути дешевим, інакше він
    коштуватиме рівно там, де його ніхто не просив.
    """
    import time

    now = time.monotonic()
    if _MACHINE["data"] is not None and now - _MACHINE["at"] < _MACHINE_TTL:
        return cast("dict[str, Any]", _MACHINE["data"])
    try:
        from nyshporka.setup.doctor import run

        checks = list(run())
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
    # ⚠ Профіль сюди НЕ входить: у чекліста він окремий крок. Порахований
    # двічі, він показував би той самий недолік у двох рядках — а другий рядок
    # читається як друга проблема, і людина шукає її окремо.
    checks = [c for c in checks if not c.name.startswith("Профіль")]
    worst = ("fail" if any(c.level == "fail" for c in checks)
             else "warn" if any(c.level == "warn" for c in checks) else "ok")
    out = {"ok": True, "level": worst, "ready": worst == "ok",
           "bad": [c.name for c in checks if c.level != "ok"]}
    _MACHINE.update(at=now, data=out)
    return out


def _pulse_reading(env: Envelope) -> dict[str, Any]:
    """Прогони: скільки, чим, як швидко — і скільки різних сторінок прочитано."""
    from nyshporka import htr_store

    try:
        runs = htr_store.list_cases()
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
    orphans = sum(1 for r in runs if not r.get("case_key"))
    by_engine: dict[str, int] = {}
    by_model: dict[str, int] = {}
    for r in runs:
        for eid in r.get("engine_ids") or []:
            by_engine[str(eid)] = by_engine.get(str(eid), 0) + 1
        model = str(r.get("model") or "")
        if model:
            by_model[model] = by_model.get(model, 0) + 1
    speeds = [float(r["sec_median"]) for r in runs
              if isinstance(r.get("sec_median"), int | float)]
    if orphans:
        env.warn("orphan_runs",
                 f"{orphans} прогонів без справи — їхнього тексту не видно "
                 f"на жодному екрані про справу")
    return {
        "ok": True,
        "runs": len(runs),
        # 🔴 `unique_pages`, а не сума `pages_done`: два голоси проходять ТІ
        # самі аркуші, тож сума показала б удвічі більше прочитаного на кожній
        # справі, гнаній обома, — знаменник, більший за наявне.
        "pages": htr_store.unique_pages(runs),
        "orphans": orphans,
        "by_engine": _tally(by_engine),
        "by_model": _tally(by_model),
        "sec_median": round(sorted(speeds)[len(speeds) // 2], 2) if speeds else None,
        "last": [{"name": r.get("name"), "shifra": r.get("shifra"),
                  "case_key": r.get("case_key"), "pages": r.get("pages_done"),
                  "model": r.get("model"), "updated": r.get("updated")}
                 for r in runs[:5]],
    }


def _pulse_search() -> dict[str, Any]:
    from nyshporka.search import decode as D

    try:
        return {"ok": True, **D.stats()}
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}


def _pulse_eye(registry: dict[str, Any], env: Envelope) -> dict[str, Any]:
    """Облік ока: скільки аркушів у сховищі й скільки з них дійшло до реєстру.

    🔴 Два числа, а не одне. Сховище рахує всі замітки на диску; реєстр —
    лише ті, чию справу він упізнав. Різниця це не похибка округлення, а
    занесені аркуші, яких не покаже жоден екран про справу: облік зроблено,
    роботу зроблено, а знайти її можна тільки грепом по файлах.
    """
    from nyshporka.pagestore import store

    try:
        got = store.totals()
    except Exception as exc:
        return {"built": False, "why": f"{type(exc).__name__}: {exc}"}
    out: dict[str, Any] = {
        "built": True,
        "pages": got["pages"], "pages_full": got["full"],
        "files": got["files"], "records": got["records"],
        "by_status": got["by_status"],
    }
    if registry.get("built"):
        out["cases"] = registry.get("eye_cases")
        out["in_registry"] = registry.get("eye_pages")
        out["hits_open"] = registry.get("fuzzy_hits_open")
        out["no_fuzzy"] = registry.get("fuzzy_none")
        lost = got["pages"] - int(registry.get("eye_pages") or 0)
        if lost > 0:
            env.warn("notes_off_registry",
                     f"{lost} занесених аркушів стоять на справах, яких реєстр "
                     f"не знає — на екранах про справу їх не видно")
    return out


def _pulse_jobs() -> dict[str, Any]:
    """Черга робіт — лише коли застосунок піднято.

    ⚠ Порожній список у командному рядку означав би «нічого не запущено», тоді
    як черги там немає взагалі: довга робота йде синхронно й друкує прогрес
    сама. Тому тут `running: None`, а не нуль.
    """
    from nyshporka.runtime import current_bus

    bus = current_bus()
    if bus is None:
        return {"queue": False}
    jobs = [j.as_dict() for j in bus.jobs()]
    live = [j for j in jobs if j.get("state") in ("running", "queued")]
    return {"queue": True, "running": len(live), "total": len(jobs),
            "failed": sum(1 for j in jobs if j.get("state") == "error"),
            "last": jobs[-6:]}


def _pulse_history(data: dict[str, Any], history: Any,
                   a: PulseArgs) -> list[dict[str, Any]]:
    reg = data.get("registry") or {}
    canon = data.get("canon") or {}
    reading = data.get("reading") or {}
    eye = data.get("eye") or {}
    rows: list[dict[str, Any]] = history.read()
    if not rows and a.backfill:
        # Разово: без цього графік починався б у день, коли модуль з'явився, —
        # тобто нове вміння показувало б порожнечу саме тому, що воно нове.
        try:
            history.backfill()
            rows = history.read()
        except Exception:
            rows = []
    if reg.get("built"):
        # 🔴 Пишемо безумовно, а відсіює однакове сам журнал — за числами.
        # Спокуса звірятися тут із пульсом є, але пульс б'є й на операціях, які
        # жодного з цих чисел не міняють (перейменували справу, зняли вердикт),
        # тож він дав би точку там, де на графіку нічого не зрушило. Числа —
        # єдиний чесний привід поставити крапку на кривій про числа.
        # 🔴 Кожне поле журналу має рівно одне джерело — те саме, з якого його
        # бере бекфіл. Інакше крива падає на 33 тисячі сторінок у день, коли
        # почались живі спостереження, і виглядає це не як зміна лінійки, а як
        # утрачена робота. Тому `htr_pages` тут із прогонів (`unique_pages`), а
        # не з реєстру, а `pages_noted` — зі сховища, а не з його розкладки по
        # справах. Числа реєстру лишаються на плитках, де вони й означають
        # рівно те, що написано.
        snap = {
            "cases": reg.get("cases"), "frames": reg.get("frames"),
            "ordered": reg.get("ordered"),
            "htr_pages": reading.get("pages"),
            "htr_none": reg.get("htr_none"),
            "no_fuzzy": reg.get("fuzzy_none"),
            "hits_open": reg.get("fuzzy_hits_open"),
            "pages_noted": eye.get("pages"),
            "runs": reading.get("runs"),
            "canon_persons": canon.get("persons"),
            "canon_facts": canon.get("facts"),
            "canon_sources": canon.get("sources"),
        }
        if history.record(snap, by="home.pulse"):
            rows = history.read()
    if a.history_days:
        import time as _t

        cutoff = _t.strftime("%Y-%m-%d",
                             _t.localtime(_t.time() - a.history_days * 86400))
        rows = [r for r in rows if str(r.get("at") or "")[:10] >= cutoff]
    return rows


def _tally(got: dict[str, int]) -> list[dict[str, Any]]:
    return [{"code": k, "n": n}
            for k, n in sorted(got.items(), key=lambda x: (-x[1], x[0]))]


# ── джерела ──────────────────────────────────────────────────────────────────
def _registry() -> Registry:
    """Реєстр джерел, прив'язаний до простору (там кеші й зібрані каталоги)."""
    from nyshporka.core.workspace import WorkspaceError, workspace
    from nyshporka.sources import load

    try:
        root = workspace().root
    except WorkspaceError:
        # Без простору мережеві джерела працюють обмежено (кешу немає), але
        # реєстр мусить збиратись: інакше `sources.list` мовчав би про них.
        root = None
    return load(root)


def _source(source_id: str) -> Source:
    from nyshporka.sources.base import SourceError

    reg = _registry()
    src = reg.get(source_id)
    if src is None:
        known = ", ".join(s.id for s in reg.all())
        raise SourceError(f"джерела {source_id!r} немає. Є: {known}")
    return src


def _catalog_basis(src: Any) -> dict[str, Any]:
    """На чому це джерело шукає — і чи є на чому взагалі.

    🔴 Стан каталогу мусить бути видимим до пошуку, а не після. «Нічого не
    знайшлось» у джерелі без каталогу і «нічого не знайшлось» у зрізі на дев'ять
    тисяч справ — це різні відповіді, і друга закриває напрям, якого ніхто не
    перевіряв. Доти перелік джерел казав лише, що джерело існує.

    ⚠ Метод береться через `getattr`: `Source` — це `Protocol`, а не базовий
    клас, тож дефолту успадкувати нізвідки. Джерело без каталогу (локальна тека)
    чесно віддає `kind: "none"` і `rows: None` — не нуль.
    """
    fn = getattr(src, "catalog_source", None)
    searchable = "search" in getattr(src, "caps", ())
    out: dict[str, Any] = {"searchable": searchable, "kind": "none",
                           "taken": "", "rows": None, "scope": "", "fix": ""}
    if fn is None:
        return out
    try:
        kind, info = fn()
    except Exception as exc:
        out["fix"] = f"каталог не читається: {type(exc).__name__}: {exc}"
        return out
    out["kind"] = kind
    out["taken"] = str(info.get("taken") or "")
    rows = info.get("rows")
    out["rows"] = int(rows) if isinstance(rows, int) else None
    regions = info.get("regions") or []
    if regions:
        out["scope"] = ", ".join(str(x) for x in regions)
    elif info.get("scope"):
        # Джерело без каталогу на диску теж має межі: покажчик накриває свій
        # перелік архівів, і поза ним його нуль нічого не означає.
        out["scope"] = str(info["scope"])
    if kind == "none" and searchable:
        # Порада мусить бути виконуваною. Обхід збирається однією командою, і
        # саме її бракувало тому, хто діставав `source_unavailable` після
        # одинадцяти секунд очікування.
        out["fix"] = f"nysh crawl {src.id}"
    return out


@op("sources.list", summary="Звідки можна брати матеріал", section="material")
def sources_list(_: NoArgs) -> Envelope:
    reg = _registry()
    rows: list[dict[str, Any]] = [
        {"id": s.id, "label": s.label, "caps": sorted(s.caps),
         "catalog": _catalog_basis(s)} for s in reg.all()]
    env = ok({"sources": rows, "shown": len(rows),
              # 🔴 Скільки джерел уміють шукати й скільки з них мають на чому.
              # Друге число і є знаменником кожного нуля на цьому екрані.
              "searchable": sum(1 for r in rows if r["catalog"]["searchable"]),
              "with_catalog": sum(1 for r in rows
                                  if r["catalog"]["searchable"]
                                  and r["catalog"]["kind"] != "none")})
    # ⚠ Джерело без обходу тут більше не попереджає. Це не втрата: сам перелік
    # і є відповіддю на питання «де шукали» — у рядку такого джерела стоїть і
    # «шукати нема на чому», і команда, якою це лікується, поіменно. Жовтий
    # рядок згори повторював те саме іншими словами й горів при кожному
    # відкритті екрана; попередження, яке горить завжди, перестають читати —
    # разом із тим єдиним, що означає зіпсований нуль.
    for name, why in reg.broken:
        # Зламаний плагін називається поіменно: «мого архіву немає в списку»
        # інакше не має пояснення, і причину шукатимуть у своїх налаштуваннях.
        env.warn("broken_source", f"джерело «{name}» не завантажилось: {why}")
    return env


class LookArgs(BaseModel):
    path: str = Field(description="тека зі сканами, PDF або тека з PDF")


@op("material.look", summary="Що це за матеріал: скільки кадрів, одна справа чи багато",
    args=LookArgs)
def material_look(a: LookArgs) -> Envelope:
    from nyshporka.sources.local import LocalSource, inspect

    shape = inspect(a.path)
    data = {"kind": shape.kind, "path": str(shape.path), "usable": shape.usable,
            "explain": shape.explain(), "images": shape.images,
            "pdfs": shape.pdfs, "pages": shape.pages,
            "cases": [{"ref": c.ref, "label": c.label, "frames": c.frames}
                      for c in shape.cases]}
    env = ok(data)
    if shape.kind == "cases":
        # 🔴 Це не помилка й не успіх: тека містить багато справ. Мовчазне
        # «усе гаразд» призвело б до прогону на нуль сторінок.
        env.warn("many_cases",
                 f"це не одна справа, а {len(shape.cases)} — оберіть потрібну")
        return env
    if not shape.usable:
        env.warn("not_usable", shape.explain())
        return env
    m = LocalSource().manifest(str(shape.path))
    data["frames"] = m.frames
    data["bytes"] = m.bytes_estimate
    return env


class CatalogSearchArgs(BaseModel):
    q: str = Field(description="назва села, прізвище чи слово із заголовка справи")
    source: str = Field(default="", description="одне джерело; порожньо = усі, що вміють шукати")
    limit: int = Field(default=30, ge=1, le=200)


@op("catalog.search", summary="Де взагалі є щось про моє село",
    args=CatalogSearchArgs, mutates=False, section="material")
def catalog_search(a: CatalogSearchArgs) -> Envelope:
    """Пошук по каталогах джерел.

    🔴 Нуль тут завжди зі знаменником. Джерело, яке не може шукати (каталог не
    зібрано, дерево не завантажене), не додає нуль до суми — воно потрапляє в
    `unavailable` з причиною й готовою командою. Інакше «0 знахідок у трьох
    архівах» означало б «дивились у трьох», хоча дивились в одному, і напрям
    пошуку закрився б висновком, якого ніхто не робив.
    """
    from nyshporka.sources.base import SourceError, supports

    reg = _registry()
    picked = [reg.get(a.source)] if a.source else reg.with_cap("search")
    if a.source and picked[0] is None:
        return fail(f"джерела {a.source!r} немає")
    hits: list[dict[str, object]] = []
    searched: list[str] = []
    unavailable: list[dict[str, str]] = []
    #: Джерела, чия видача вперлась у власну стелю: їхній перелік неповний.
    truncated: list[dict[str, Any]] = []
    #: На чому саме шукали — вкладений зріз чи зібраний обходом, і від якої дати.
    basis: list[dict[str, Any]] = []
    for src in picked:
        if src is None or not supports(src, "search"):
            continue
        try:
            found = src.search(a.q, limit=a.limit)
        except SourceError as exc:
            unavailable.append({"source": src.id, "why": str(exc)})
            continue
        except Exception as exc:  # мережа, розмітка, побитий кеш
            unavailable.append({"source": src.id, "why": f"{type(exc).__name__}: {exc}"})
            continue
        searched.append(src.id)
        # 🔴 Стеля видачі — це обрізка, а не результат. Джерело з пагінацією в
        # пошуку (Duck: 50 без продовження) віддає рівно стелю і на слові, під
        # яке підпадають тисячі справ; узятий за повний, такий перелік стає
        # знаменником негативу, якого ніхто не міряв.
        ceiling = int(getattr(src, "search_ceiling", 0) or 0)
        if ceiling and len(found) >= ceiling:
            truncated.append({"source": src.id, "ceiling": ceiling})
        # 🔴 Чим саме шукали — частина знаменника. Вкладений зріз каталогу
        # старіє: «не знайшлось» у ньому означає «не було на дату зрізу», а не
        # «не існує», і без дати ці два висновки не відрізнити. Саме тому дата
        # їде в `basis` — його показують до пошуку, коли на нього ще дивляться.
        note = getattr(src, "catalog_source", None)
        if callable(note):
            kind, meta = note()
            if kind == "bundled":
                basis.append({"source": src.id, "kind": "вкладений зріз",
                              "taken": str(meta.get("taken") or ""),
                              "rows": meta.get("rows"),
                              "regions": meta.get("regions") or None})
            elif kind == "workspace":
                basis.append({"source": src.id, "kind": "зібраний на місці"})
            elif kind == "live":
                basis.append({"source": src.id, "kind": "живий запит",
                              "taken": "", "rows": None, "regions": None})
        hits.extend({"source": h.source, "ref": h.ref, "title": h.title,
                     "years": h.years, "place": h.place, "shifra": h.shifra,
                     "frames": h.frames, "acquirable": h.acquirable,
                     "note": h.note, "url": h.url,
                     "repo": h.repo, "archive": h.archive, "fond": h.fond}
                    for h in found)
    shown = hits[:a.limit]
    env = ok({"q": a.q, "hits": shown, "fonds": _by_fond(shown),
              "coverage": {"searched": searched, "unavailable": unavailable,
                           "basis": basis, "truncated": truncated}})
    _warn_once(env, hits=hits, searched=searched,
               unavailable=unavailable, truncated=truncated)
    return env


def _by_fond(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Знахідки, зведені у фонди — те, про що насправді приймають рішення.

    🔴 Пошук по каталогах не самоціль, а перший крок циклу: знайти фонд за
    словом → оцінити, чи він вартий уваги → зібрати його реєстр. Список
    окремих справ другого кроку не витримує: три томи одного фонду й три
    випадкові збіги з трьох різних архівів виглядають однаково, а звідки саме
    прийшла знахідка, доводиться вичитувати з шифри очима.

    Роки беруться з самих знахідок і чесно означають «у знайденому», а не «у
    фонді»: межі фонду знає його картка (`catalog.fond`), і вигадувати їх тут
    із випадкової вибірки означало б назвати фонд вужчим, ніж він є.
    """
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for h in hits:
        repo = str(h.get("repo") or "")
        archive = str(h.get("archive") or "")
        fond = str(h.get("fond") or "")
        if not fond:
            # Джерело, яке не знає фондів (дзеркало плівок адресує плівки), —
            # не привід вигадати йому фонд: такий рядок просто не бере участі
            # в оцінці, і це видно з того, що сума по фондах менша за видачу.
            continue
        # 🔴 Архів у ключі, а не лише фонд. Номери фондів між архівами
        # колізують, і два невідомі паку архіви з фондом 118 злилися б в один
        # рядок — вагу однієї знахідки приписало б іншій.
        row = out.setdefault((repo, archive, fond), {
            "repo": repo, "archive": archive, "fond": fond, "hits": 0,
            # Чим підписати рядок: наш код, якщо архів нам відомий, інакше — як
            # його зве покажчик. Порожньо лишається лише там, де назви не дав
            # ніхто, і тоді це справді «невідомо», а не стерте нами.
            "label": repo or archive,
            "sources": [], "years": [], "sample": str(h.get("title") or "")[:120]})
        row["hits"] += 1
        src = str(h.get("source") or "")
        if src and src not in row["sources"]:
            row["sources"].append(src)
        for part in str(h.get("years") or "").replace("—", "-").split("-"):
            digits = "".join(c for c in part if c.isdigit())
            if len(digits) == 4:
                row["years"].append(int(digits))
    rows = []
    for row in out.values():
        years = row.pop("years")
        row["year_from"] = min(years) if years else None
        row["year_to"] = max(years) if years else None
        rows.append(row)
    rows.sort(key=lambda r: (-int(r["hits"]), r["label"], r["fond"]))
    return rows


def _warn_once(env: Envelope, *, hits: list[dict[str, object]],
               searched: list[str], unavailable: list[dict[str, str]],
               truncated: list[dict[str, Any]]) -> None:
    """Одне попередження на пошук — і тільки там, де знаменник пошкоджено.

    🔴 Чому не по попередженню на джерело. Раніше кожне джерело з вкладеним
    зрізом додавало своє «шукали у зрізі від такої дати», і звичайний пошук
    двома джерелами відкривався трьома жовтими рядками щоразу — при тому, що
    ті самі дати стоять у переліку джерел просто нижче, з обсягом і станом
    кожного. Попередження, яке горить завжди, перестають читати; разом із ним
    перестають читати й те єдине, що означає зіпсований нуль.

    Лишається рівно три приводи, і кожен змінює висновок, а не оформлення:

    - шукати не було де взагалі — нуль не означає нічого;
    - видача вперлась у стелю джерела — перелік неповний, і негатив по ньому
      неможливий;
    - джерело відпало, і при цьому не знайшлось нічого — нуль без частини
      знаменника. Коли знахідки є, той самий факт лишається в `coverage`:
      він більше не міняє відповіді, тож не варте жовтого рядка.
    """
    parts: list[str] = []
    code = ""
    if not searched:
        code = "no_denominator"
        parts.append("жодне джерело не змогло шукати — цей нуль нічого не означає")
    if truncated:
        code = code or "search_truncated"
        where = "; ".join(f"{t['source']} (стеля {t['ceiling']})" for t in truncated)
        parts.append(f"видача обрізана — перелік неповний: {where}. "
                     f"Звужуй запит або бери фонд цілком")
    if unavailable and not hits:
        code = code or "partial_denominator"
        where = "; ".join(f"{u['source']}: {u['why']}" for u in unavailable)
        parts.append(f"нуль неповний — не шукали в {where}")
    if parts:
        env.warn(code, " · ".join(parts))


class FondCardArgs(BaseModel):
    repo: str = Field(description="код архіву: DAHMO, CDIAK, ДАХмО…")
    fond: str = Field(description="номер фонду")


# ⚠ `agent=False` навмисно: перелік tool'ів тримається під стелею, і картка
# фонду належить до тієї ж родини, що `fond.list` і `registry.*`, — усі вони
# живуть у застосунку й командному рядку, а не в переліку агента.
@op("catalog.fond", summary="Що це за фонд і чи варто збирати його реєстр",
    args=FondCardArgs, mutates=False, agent=False, section="material")
def catalog_fond(a: FondCardArgs) -> Envelope:
    """Картка фонду з зовнішнього покажчика плюс наш власний стан по ньому.

    🔴 Ця операція — пропущена ланка циклу. Пошук по каталогах відповідає «де
    взагалі щось є» і віддає окремі справи; збирання реєстру опису коштує
    десятків хвилин під лімітом сервісу. Між ними стояло рішення «чи вартий
    цей фонд того, щоб його збирати», і приймали його наосліп: назви фонду
    видача не несе, меж років не знає, скільки в ньому описів — теж, а чи не
    зібрано його в нас уже — питали в іншому місці й іншими словами.

    Тут обидві половини відповіді разом: що це за фонд у покажчику (назва,
    роки, описи) і що по ньому є в нас (реєстр, скільки справ, скільки вже на
    диску). Порожня друга половина — не помилка, а найчастіша причина сюди
    зайти: фонд бачать уперше.
    """
    from nyshporka.archives import active
    from nyshporka.sources.base import SourceError

    pack = active()
    raw = str(a.repo or "").strip()
    # Сюди приходить і наш код («DAHMO»), і той, яким архів зве покажчик
    # («ДАЖО») — саме він стоїть у знахідці, коли архіву немає в паку. Спершу
    # пробуємо перекласти чужий на наш: інакше той самий архів, названий двома
    # способами, дав би дві різні відповіді про те, що в нас уже є.
    repo = pack.repo_for_code("duck", raw) or pack.canon_repo(raw)
    codes = pack.codes_for(repo, "duck")
    # ⚠ Невідомий паку архів не є глухим кутом: у покажчику 43 архіви, і його
    # власний код можна передати сюди як є. Мовчазна відмова тут закрила б
    # рівно той випадок, заради якого зведений покажчик і додано, — «архів,
    # якого ми ще не знаємо».
    archive_code = codes[0] if codes else raw
    src = _registry().get("duck")
    card: dict[str, Any] = {}
    why = ""
    if src is None:
        why = "джерела «duck» немає в реєстрі"
    else:
        try:
            # Картку фонду вміє один покажчик, і протокол `Source` її не
            # оголошує навмисно: це не спільна можливість, а заглушок контракт
            # не приймає. Реєстр повертає джерело за id, тобто тип тут ширший
            # за те, що насправді прийшло.
            card = src.fond_card(archive_code, a.fond)  # type: ignore[attr-defined]
        except SourceError as exc:
            why = str(exc)
        except Exception as exc:  # мережа, розмітка
            why = f"{type(exc).__name__}: {exc}"
    ours = _our_fond(repo, a.fond)
    env = ok({"repo": repo, "fond": str(a.fond), "archive_code": archive_code,
              "card": card, "ours": ours})
    if why:
        # 🔴 Порожня картка мусить мати причину. Без неї «покажчик про цей фонд
        # не знає» і «покажчик не відповів» виглядають однаково — а це різниця
        # між «фонду немає» і «спитай ще раз».
        env.warn("card_unavailable", f"покажчик не дав картки: {why}")
    if not ours["has_registry"]:
        env.suggest("registry.plan",
                    "скільки коштуватиме зібрати опис цього фонду")
    return env


def _our_fond(repo: str, fond: str) -> dict[str, Any]:
    """Що по цьому фонду вже є в нас: реєстр, справи, кадри на диску.

    Друга половина оцінки, і без неї перша веде до подвійної роботи: фонд, що
    виглядає цікавим, регулярно виявляється вже зібраним.
    """
    out: dict[str, Any] = {"has_registry": False, "rows": 0, "on_disk": 0}
    try:
        from nyshporka.fonds import registry as R

        for f in R.discover_fonds():
            if not (str(f.get("fond")) == str(fond)
                    and str(f.get("repo", "")).upper() == str(repo).upper()):
                continue
            rows = R.load_rows(f["id"])
            s = R.summarize(rows, R.live_on_disk(f["repo"], f["fond"]))
            out.update(has_registry=True, id=f["id"], label=f.get("label", ""),
                       rows=s["rows"], on_disk=s["on_disk_live"],
                       todo=s["todo"])
            break
    except Exception as exc:  # реєстри недоступні — це не привід валити картку
        out["why"] = f"{type(exc).__name__}: {exc}"
    return out


class BrowseArgs(BaseModel):
    source: str = Field(description="id джерела (`sources.list`)")
    ref: str = Field(default="", description="вузол; порожньо = верхній рівень")


@op("catalog.browse", summary="Що лежить у фонді, описі, теці", args=BrowseArgs,
    mutates=False, section="material")
def catalog_browse(a: BrowseArgs) -> Envelope:
    from nyshporka.sources.base import SourceError

    try:
        src = _source(a.source)
        nodes = src.browse(a.ref or None)
    except SourceError as exc:
        return fail(str(exc))
    return ok({"source": a.source, "ref": a.ref,
               "nodes": [{"ref": n.ref, "label": n.label, "kind": n.kind,
                          "frames": n.frames, "size": n.size} for n in nodes]})


class ManifestArgs(BaseModel):
    source: str = Field(description="id джерела")
    ref: str = Field(description="адреса справи чи плівки в цьому джерелі")


@op("catalog.manifest", summary="Що саме принесе завантаження — ДО того, як почалось",
    args=ManifestArgs, mutates=False, section="material")
def catalog_manifest(a: ManifestArgs) -> Envelope:
    from nyshporka.sources.base import SourceError

    try:
        m = _source(a.source).manifest(a.ref)
    except SourceError as exc:
        return fail(str(exc))
    env = ok({"source": m.source, "ref": m.ref, "title": m.title,
              "frames": m.frames, "bytes_estimate": m.bytes_estimate,
              "sheets": [{"from": s.frm, "to": s.to, "label": s.label}
                         for s in m.sheets],
              "meta": {k: v for k, v in m.meta.items() if k != "files"}})
    if not m.sheets and m.meta.get("meta_rows"):
        # Підписи теки є, а поаркушевого покажчика немає — і це різні речі.
        env.warn("no_sheet_index",
                 "покажчика аркушів у цій плівці немає, лише підпис теки — "
                 "яке село на якому кадрі, звідси не видно")
    return env


# ── мої справи ───────────────────────────────────────────────────────────────
class CasesArgs(BaseModel):
    q: str = Field(default="", description="підрядок: шифра, назва, місце")
    repo: str = ""
    htr: str = Field(default="", description="none | partial | pysar | diak | both")
    year: str = Field(default="", description="рік або діапазон «1840-1860»")
    place: str = ""
    # ⚠ Прокинуто, бо `cases stats` радить `nysh cases list --kind unfiled` —
    # а фільтр був лише в дослідницькому CLI, тобто скопійована порада не
    # працювала. Шар даних (`db.query_rows`) `kind` приймав від початку.
    kind: str = Field(default="",
                      description="case | bundle | unfiled (матеріал без шифри)")
    limit: int = Field(default=60, ge=1, le=500,
                       description="скільки рядків віддати; `page_size` сильніший")
    page: int = Field(default=0, ge=0, le=10_000, description="сторінка видачі")
    page_size: int = Field(default=0, ge=0, le=200,
                           description="розмір сторінки; 0 — узяти `limit`")


@op("cases.list", summary="Мої справи: що є, що прочитано, що прошукано",
    args=CasesArgs, mutates=False)
def cases_list(a: CasesArgs) -> Envelope:
    """Реєстр справ із застереженням про свіжість.

    🔴 Застереження — не косметика. Реєстр це зріз п'яти сховищ, і будь-який
    прогін робить його старим за хвилини. Застарілий зріз небезпечніший за
    відсутній: він виглядає як відповідь («декоду немає») там, де декод зробили
    годину тому, — і саме по ньому вирішують, що гнати далі.
    """
    from nyshporka.cases import db

    # 🔴 Знаменник рахується завжди, навіть коли сторінок не просили. Доти
    # видача казала лише «показано N», і 60 рядків із півтори тисячі виглядали
    # як уся відповідь — обрізаний список без знаменника нічим не кращий за
    # нуль без нього.
    size = a.page_size or a.limit
    try:
        rows, total = db.query_page(page=a.page, page_size=size, q=a.q,
                                    repo=a.repo, htr=a.htr, year=a.year,
                                    place=a.place, kind=a.kind)
    except FileNotFoundError:
        # 🔴 «Реєстру ще немає» — це нормальний стан щойно створеного простору,
        # а не поламка. Відмова тут була першим, що бачив новачок, відкривши
        # «Мої справи»: червоне «Не вийшло» замість порожнього переліку. Гірше
        # того, екран на відмові не малювався взагалі — разом із кнопкою 🔄,
        # якою це й лікується, тобто вихід зникав саме тоді, коли був потрібен.
        # `shown`/`total` — `None`, а не `0`: нуль тут означав би «перевірили,
        # справ немає», тоді як реєстру просто не збирали.
        env = ok({"cases": [], "shown": None, "total": None, "registry": False,
                  "page": a.page, "page_size": size, "pages": 0})
        env.warn("no_registry_yet",
                 "реєстру справ ще немає — його збирають після того, як у "
                 "просторі з'явиться перша справа")
        env.stale_because(["реєстр ще не збирали"], fix="nysh cases build")
        return env
    except Exception as exc:
        return fail(f"реєстр справ недоступний ({type(exc).__name__}: {exc})"
                    ).suggest("cases.build", "зібрати реєстр справ")
    pages = (total + size - 1) // size if size else 0
    try:
        counts = db.kind_counts()
    except Exception:
        counts = {}
    env = ok({"cases": rows, "shown": len(rows), "total": total,
              "page": a.page, "page_size": size, "pages": pages,
              "counts": counts, "registry": True})
    if a.page and a.page >= pages:
        env.warn("page_past_end",
                 f"сторінки {a.page + 1} немає: усього {pages} під цим фільтром")
    try:
        st = db.staleness()
    except Exception:
        st = {}
    if st.get("stale"):
        env.stale_because(st.get("reasons") or [], fix="nysh cases build")
    return env


# ── пошук по прочитаному ─────────────────────────────────────────────────────
@op("search.state", summary="Чи зібрано індекс прочитаного",
    mutates=False, agent=False, section="research")
def search_state(_: NoArgs) -> Envelope:
    """Знаменник екрана пошуку — до запиту, а не після.

    🔴 Пошук чеше лише зібране, і «не знайшлось» при повному й частковому
    індексі — різні відповіді. Показати це можна лише тут: у самій видачі це
    вже застереження, тобто після того, як людина зачекала й повірила нулю.
    """
    from nyshporka.search import decode as D

    try:
        st = D.stats()
    except Exception as exc:
        return fail(f"стан індексу недоступний ({type(exc).__name__}: {exc})")
    env = ok(st)
    if st["stale"]:
        env.suggest("search.index", "зібрати індекс решти прогонів")
    return env


class IndexArgs(BaseModel):
    rebuild: bool = Field(default=False,
                          description="перебудувати навіть свіже (після зміни "
                                      "правил склейки)")


@op("search.index", summary="Зібрати індекс прочитаного — щоб пошук був швидким",
    args=IndexArgs, mutates=True, long=True, agent=False, section="research")
def search_index(a: IndexArgs) -> Envelope:
    """Індекс декоду: один раз довго, далі щоразу швидко.

    🔴 Навіщо окрема операція, а не «саме зробиться при пошуку». Зібрати
    індекс усього прочитаного коштує чверть години на великому корпусі, і
    робити це мовчки всередині запиту з браузера означає повісити застосунок
    без жодного слова про те, чим він зайнятий. Тому збирання — робота в
    черзі: її видно, її можна спинити, і вона робиться раз.

    ⚠ Індекс — похідне. Його можна видалити будь-коли; наступний пошук просто
    скаже, скільки прогонів лишилось поза ним.
    """
    from nyshporka import htr_store
    from nyshporka.search import decode as D

    runs = [c["name"] for c in htr_store.list_cases()]
    if a.rebuild:
        for r in runs:
            try:
                D.index_path(r).unlink(missing_ok=True)
            except OSError:
                # Не змогли прибрати — індекс просто лишиться старим, і
                # наступний прохід звірить його штампом. Валити перезбірку
                # через один недоступний файл немає підстав.
                continue
    built = sum(1 for _ in D.ensure_all(runs))
    st = D.stats()
    env = ok({"built": built, **st})
    if st["stale"]:
        # Не помилка: прогін без жодного тексту індексувати нема з чого.
        env.warn("some_not_indexed",
                 f"{st['stale']} прогонів лишились без індексу — найчастіше це "
                 f"теки без жодного `.txt`")
    return env


class SearchArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    where: Literal["decode", "pages", "records"] = Field(
        default="decode",
        description="decode — тексти прогонів; pages — виписані прізвища; "
                    "records — учасники розібраних записів")
    case: str = Field(
        default="",
        description="обмежити однією справою: ключ «DAHMO/315/8433», шифра "
                    "«ДАХмО 315-1-8433», шлях теки або ім'я прогону")
    thresh: int = Field(default=80, ge=50, le=100)
    # 🔴 Вікно, а не рядок. Рядок-хіт не розрізняє прізвищ зі спільним коренем,
    # а в одній парафії їх буває кілька: заміряно на метриках одного села — 78
    # кандидатів верхівки розклались на три різні роди з тим самим коренем плюс
    # причт, і за самим рядком вони зливаються в купу однаково правдоподібних
    # хітів. Розрізняє їх сусідство: перенесена половина слова читається лише
    # разом із наступним рядком, а стан і роль стоять у сусідньому.
    context: int = Field(default=1, ge=0, le=3,
                         description="рядків сусідства до кожного хіта "
                                     "(0 — лише сам рядок)")
    limit: int = Field(default=100, ge=1, le=500)


class SweepArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    thresh: int = Field(default=80, ge=50, le=100)
    context: int = Field(default=1, ge=0, le=3)
    limit: int = Field(default=100, ge=1, le=500)


# `agent=False`: агентові довга робота через чергу недоступна — черга живе в
# процесі застосунку. Йому лишається `search.run`, і це правильно: він працює
# у межах справи, а не чеше корпус.
@op("search.sweep", summary="Прочесати все прочитане — робота в черзі",
    args=SweepArgs, mutates=False, long=True, agent=False, section="research")
def search_sweep(a: SweepArgs) -> Envelope:
    """Той самий пошук, що `search.run`, але як робота з видимим поступом.

    🔴 Навіщо друга операція, коли пошук уже є. Різниця не в тому, що робиться,
    а скільки це триває: у межах справи пошук — це частка секунди, по всьому
    корпусу — хвилини. Дві хвилини синхронного запиту виглядають у браузері
    рівно як зависання: сторінка не відповідає й не каже, чому.

    ⚠ Тіло — той самий `htr_store.search`. Другої реалізації пошуку немає й
    бути не може: розійшовшись, вони давали б різні відповіді на те саме
    питання залежно від того, звідки спитали.
    """
    return search_run(SearchArgs(q=a.q, where="decode", case="",
                                 thresh=a.thresh, context=a.context,
                                 limit=a.limit))


@op("search.run", summary="Знайти прізвище в тому, що вже прочитано",
    args=SearchArgs, mutates=False, section="research")
def search_run(a: SearchArgs) -> Envelope:
    """🔴 Нуль завжди зі знаменником.

    Порожній результат від пошуку по декоду означає «в цих N прогонах не
    знайшлось», а не «цього немає»: декодовано завжди меншу частину того, що є
    на диску. Тому у відповіді йде `coverage` — по скількох прогонах і скількох
    сторінках шукали. Без цього числа нуль читається як доведений.
    """
    if a.where == "decode":
        from nyshporka import htr_store

        try:
            res = htr_store.search(a.q, name=a.case or None, thresh=a.thresh,
                                   limit=a.limit, context=a.context)
        except ValueError as exc:
            # Область пошуку не впізнано. Відмова тут нормативна (перелік
            # прийнятних форм), і вона краща за мовчазний пошук по всьому
            # корпусу: людина просила одну справу, і відповідь «шукали
            # скрізь» на це питання не відповідає.
            return fail(str(exc))
        # 🔴 Знаменник береться з тієї самої відповіді, що й хіти. Поки він
        # рахувався тут окремим `list_cases()`, він ігнорував `--case`: на
        # просторі з 506 прогонами пошук по одній справі звітував «не
        # знайшлось у 1 прогонах (320 669 сторінок)» — чисельник від справи,
        # знаменник від усього простору. Раніше той самий рядок брав ключ
        # `pages` замість `pages_done` і давав знаменник, тотожно рівний
        # нулю. Обидва рази вада була тиха й читалась як відповідь.
        pages = int(res.get("pages") or 0)
        scanned = res.get("cases") or 0
        blind = int(res.get("unindexed") or 0)
        scope_kind = str(res.get("scope") or "all")
        env = ok({"hits": res.get("hits") or [],
                  "coverage": {"runs": scanned, "pages": pages,
                               "thresh": a.thresh,
                               # Чим саме звужено пошук — щоб знаменник можна
                               # було прочитати, не здогадуючись про область.
                               "scope": scope_kind,
                               "case": res.get("scope_key") or "",
                               "shifra": res.get("scope_shifra") or "",
                               # 🔴 Скільки прогонів лишилось поза пошуком.
                               # Це не деталь реалізації індексу, а знаменник:
                               # «не знайшлось у 400 з 1142» і «не знайшлось у
                               # 1142» — різні відповіді, і за другою закривають
                               # напрям, якого не перевіряли.
                               "unindexed": blind}})
        if res.get("error"):
            env.warn("bad_query", str(res["error"]))
        if blind:
            env.warn("partial_index",
                     f"{blind} прогонів поза пошуком: їхній текст ще не "
                     f"проіндексовано. Прочесано {scanned}.")
            env.suggest("search.index", "зібрати індекс решти прогонів")
        if scope_kind == "case" and not int(res.get("runs_scoped") or 0):
            # Справу впізнано, але прочитаного в ній немає. Це зовсім інша
            # відповідь, ніж «шукали й не знайшли», і зливати їх в одну —
            # означає видати непрочитану справу за перевірену.
            env.warn("case_not_read",
                     f"справу {res.get('scope_shifra') or a.case} впізнано, але "
                     f"жодного прогону в ній немає — шукати нема в чому.")
            env.suggest("read.plan", "прочитати цю справу рушієм")
        elif not (res.get("hits") or []) and not res.get("error"):
            # ⚠ Числа йдуть після двокрапки, а не в узгодженні з іменником:
            # «у 2 прогонах (3 сторінок)» доводилось би відмінювати під кожне
            # число, і на «1 прогонах» це щоразу вилазило.
            if scope_kind == "case":
                where = f"у справі {res.get('scope_shifra') or res.get('scope_key')}"
            elif scope_kind == "run":
                where = f"у прогоні {a.case}"
            else:
                where = "у прочитаному"
            env.warn("zero_with_denominator",
                     f"не знайшлось {where} — прочесано прогонів: {scanned}, "
                     f"сторінок: {pages}")
        return env

    from nyshporka.pagestore import query

    # 🔴 Той самий `--case` мусить означати ту саму справу в усіх трьох гілках.
    # Сховище сторінок звіряє ключ точним рівнянням, тож шифра, шлях чи ім'я
    # прогону давали тут тихий нуль — при тому, що в довідці прапорець один і
    # обіцяє «лише в цій справі».
    case_key = a.case or None
    if case_key:
        from nyshporka import htr_store

        try:
            scope = htr_store.runs_for_scope(case_key)
        except ValueError as exc:
            return fail(str(exc))
        if not scope["key"]:
            return fail(
                f"«{a.case}» — прогін без ключа справи, а виписане ключується "
                f"справою. Дай ключ або шифру справи, або прив'яжи прогін: "
                f"nysh cases bind")
        case_key = scope["key"]

    if a.where == "pages":
        res = query.grep_surnames(a.q, thresh=a.thresh, case_key=case_key,
                                  limit=a.limit)
    else:
        res = query.grep_records(a.q, thresh=a.thresh, case_key=case_key,
                                 limit=a.limit)
    # 🔴 Знаменник тут такий самий обов'язковий, як у пошуку по декоду, — і
    # довго його не було саме тут, у гілці, найближчій до людини. «Не
    # знайшлось у виписаному» означає лише «серед того, що вже занесли оком»:
    # занесена завжди менша частина того, що на диску. Без цього числа нуль
    # читається як доведений нуль, хоч він про обсяг роботи.
    hits = res.get("hits") or []
    env = ok({"hits": hits, "total": res.get("total", len(hits)),
              "coverage": {"cases": res.get("cases") or 0,
                           "thresh": res.get("thresh", a.thresh),
                           "stems": res.get("stems") or []}})
    if res.get("error"):
        env.warn("bad_query", str(res["error"]))
    elif not hits:
        where = ("виписаних прізвищах" if a.where == "pages"
                 else "учасниках розібраних записів")
        env.warn("zero_with_denominator",
                 f"не знайшлось у {where}: переглянуто "
                 f"{res.get('cases') or 0} справ")
    return env


# ── гортач ───────────────────────────────────────────────────────────────────
class PageArgs(BaseModel):
    run: str = Field(description="ім'я прогону (тека в reports/htr)")
    page: str = Field(default="", description="скан; порожньо = перелік сторінок")


@op("page.text", summary="Що прочитано на сторінці й де саме лежить кожен рядок",
    args=PageArgs, mutates=False, section="htr")
def page_text(a: PageArgs) -> Envelope:
    from nyshporka import htr_store as S

    if not a.page:
        pages = S.case_pages(a.run)
        if pages is None:
            return fail(f"немає прогону «{a.run}»")
        return ok(pages)
    txt = S.read_page_text(a.run, a.page)
    if txt is None:
        return fail(f"немає сторінки «{a.page}» у прогоні «{a.run}»")
    geo = S.page_lines(a.run, a.page) or {}
    # 🔴 Текст і геометрія — під різними ключами. `read_page_text` віддає рядки
    # тексту саме як `lines`, і накладання геометрії тим самим ім'ям знищувало
    # прочитане: відповідь лишалась `ok`, але тексту в ній не було зовсім.
    # Гортач через це показував порожню сторінку — тобто головний екран
    # «подивитись, що прочитала машина» мовчки не показував нічого.
    text_lines = list(txt.get("lines") or [])
    env = ok({**txt, "lines": text_lines, "text": "\n".join(text_lines),
              "geometry": geo})
    if not geo.get("has"):
        # Рамок немає — гортач покаже сторінку цілком. Це не помилка, але
        # мовчати не можна: перегляд рядка й перегляд сторінки коштують по-різному.
        env.warn("no_line_boxes",
                 "прогін не зберіг рамок рядків — показати окремий рядок "
                 "не вийде, лише сторінку цілком")
    return env


class ViewArgs(BaseModel):
    run: str = Field(description="ім'я прогону")
    page: str = Field(description="скан сторінки")
    line: int | None = Field(default=None, description="номер рядка з нуля")
    region: Literal["line", "page"] = Field(
        default="line",
        description="line — вирізка рядка (дешево); page — уся сторінка (дорого)")
    pad: int = Field(default=24, ge=0, le=200,
                     description="запас навколо рядка в пікселях")
    annotate: bool = Field(
        default=True,
        description="домалювати рамку рядка — без неї видно кілька рядків "
                    "і незрозуміло, який оцінюють")


# 🔴 `agent=False`: агентові перелік прогонів нічого не додає — він і так
# приходить із назвою справи, а зайвий tool росте в переліку, який модель мусить
# читати цілком при кожному виклику. Тут він потрібен вікну: імена прогонів
# довгі й схожі, і набирати їх руками означає помилятись у назві саме тоді, коли
# шукаєш конкретну сторінку.
class RunsArgs(BaseModel):
    q: str = Field(default="", description="підрядок: ім'я прогону, шифра, назва")
    case: str = Field(default="", description="ключ справи `repo/fond/spr`")
    engine: str = Field(default="", description="рушій: pysar | diak | skryba")
    orphan: bool = Field(default=False, description="лише прогони без справи")
    page: int = Field(default=0, ge=0, le=10_000)
    page_size: int = Field(default=0, ge=0, le=200,
                           description="розмір сторінки; 0 — усі прогони")


@op("runs.list", summary="Прогони читання: що вже прочитано і чим",
    args=RunsArgs, mutates=False, section="htr", agent=False)
def runs_list(a: RunsArgs) -> Envelope:
    """Перелік прочитаного — для вибору в гортачі.

    ⚠ Рушій тут частина відповіді, а не прикраса: на одну справу прогонів
    буває кілька (латинку читає один, кирилицю інший), і без нього два рядки
    з однаковою назвою нічим не відрізнити.
    """
    from nyshporka import htr_store

    try:
        runs = htr_store.list_cases()
    except Exception as exc:
        return fail(f"перелік прогонів недоступний ({type(exc).__name__}: {exc})")
    everything = len(runs)
    orphans = sum(1 for r in runs if not r.get("case_key"))
    if a.orphan:
        runs = [r for r in runs if not r.get("case_key")]
    if a.case:
        runs = [r for r in runs if r.get("case_key") == a.case]
    if a.engine:
        runs = [r for r in runs if a.engine in (r.get("engine_ids") or [])]
    if a.q:
        needle = a.q.casefold()
        runs = [r for r in runs if needle in " ".join(
            str(r.get(k) or "") for k in ("name", "shifra", "title", "case_key")
        ).casefold()]
    total = len(runs)
    # 🔴 Сторінка ріже після фільтрів і не чіпає знаменників: `total` — скільки
    # підпало, `everything` — скільки їх узагалі. Без другого числа фільтр
    # «без справи» читався б як «прогонів усього 123».
    size = a.page_size
    if size:
        start = a.page * size
        runs = runs[start:start + size]
    env = ok({"runs": runs, "shown": len(runs), "total": total,
              "everything": everything, "orphans": orphans,
              "page": a.page, "page_size": size,
              "pages": ((total + size - 1) // size) if size else 0})
    if not everything:
        env.warn("nothing_read_yet",
                 "жодної справи ще не прочитано — гортати нема чого")
        env.suggest("read.plan", "порахувати, чим і скільки читати")
    elif not total:
        env.warn("nothing_matched",
                 f"під фільтр не підпало нічого з {everything} прогонів")
    if orphans and not a.orphan:
        # 🔴 Нічийний прогін — текст, чия справа невідома. Він не загублений, а
        # невидимий: жоден екран про справу його не покаже, і зшивати
        # доводиться правкою файлу руками.
        env.warn("orphan_runs",
                 f"{orphans} прогонів без справи — їхнього тексту не видно "
                 f"з жодної картки")
        env.suggest("cases.bind", "прив'язати нічийний прогін до справи")
    return env


class LinesArgs(BaseModel):
    run: str = Field(description="ім'я прогону")
    page: str = Field(description="скан сторінки")


# 🔴 `agent=False`: це геометрія для ока. Агентові рамки нічого не кажуть — він
# читає текст, а не дивиться на пікселі; tool, який віддає координати, лише
# росте в переліку.
@op("page.lines", summary="Рамки рядків сторінки — щоб клікати по знімку",
    args=LinesArgs, mutates=False, section="htr", agent=False)
def page_lines(a: LinesArgs) -> Envelope:
    """Геометрія рядків у координатах того самого зображення, що показують.

    ⚠ Відсутність рамок — не помилка: старі прогони їх не писали зовсім. Тоді
    відповідь чесно каже `has: false` з причиною, і гортач лишається без
    оверлея замість того, щоб виглядати зламаним.
    """
    from nyshporka import htr_store

    try:
        geo = htr_store.page_lines(a.run, a.page)
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")
    # 🔴 «Прогону чи сторінки немає» і «рамок не записано» — різні відповіді.
    # `page_lines` віддає `None` на обидва, і зведення їх до одного застереження
    # каже людині лагодити не те: вона шукала б старий прогін, тоді як насправді
    # помилилась у назві. Порожня відповідь тут ще й іншої форми — без `has`, —
    # тож фронт мовчки лишався б без оверлея й без пояснення.
    if geo is None:
        return fail(f"немає сторінки «{a.page}» у прогоні «{a.run}» — "
                    f"звірте назву прогону (`runs.list`) і скан")
    env = ok(geo)
    if not geo.get("has"):
        env.warn("no_boxes", str(geo.get("why")
                 or "цей прогін не записав рамок рядків — клікати по знімку нічим"))
    return env


@op("page.view", summary="Подивитись на рядок чи сторінку оком", args=ViewArgs,
    mutates=False, section="htr")
def page_view(a: ViewArgs) -> Envelope:
    """🔴 Центральна операція звірки: виявити ≠ перевірити.

    Машина подає кандидата, вирішує око — і другий рушій тут не суддя, бо
    ознака в пікселях. Дефолт — рядок: ціла сторінка коштує моделі вчетверо
    дорожче, а звірок за сеанс бувають десятки.
    """
    from nyshporka.htr.view import ViewError, shot

    try:
        s = shot(a.run, a.page, line=a.line, region=a.region, pad=a.pad,
                 annotate=a.annotate)
    except ViewError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")
    env = ok({**s.as_dict(), "image": s.data_url})
    if s.note:
        env.warn("view_fallback", s.note)
    return env


# ── завести справу руками ────────────────────────────────────────────────────
class CaseRegisterArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами")
    shifra: str = Field(default="",
                        description="«ДАХмО 315-1-8433», «ф.315 оп.1 спр.8433», "
                                    "«Ф. 211 Оп. 3 Д. 140»")
    # 🔴 Досі відмова «не видно архіву» радила «вкажіть окремо» — про параметр,
    # якого не було ні тут, ні у формі, ні в CLI. Порада була нездійсненна, і
    # людина лишалась без виходу (звіт 29.08.2026). Тепер поле є й справді
    # рятує шифру, набрану без назви архіву («705-1-1»).
    repo: str = Field(default="",
                      description="архів окремо, коли його немає в шифрі: "
                                  "код (DAKO) або скорочення (ДАКО)")
    title: str = Field(default="", description="назва справи, як в описі архіву")
    doc_type: str = Field(default="", description="метрична / сповідна / ревізька…")
    # ⚠ `str` поруч із `int` — щоб роки теж можна було СТЕРТИ. Форма обіцяє
    # «тире стирає поле», і мовчазний виняток для двох полів робив би обіцянку
    # напівправдою: помилковий рік лишався б назавжди.
    year_from: int | str | None = Field(default=None, description="рік або «-», щоб стерти")
    year_to: int | str | None = Field(default=None, description="рік або «-», щоб стерти")
    place: str = Field(default="", description="село, повіт, губернія")
    note: str = Field(default="", description="звідки взято, що незрозуміло")
    adopt: bool = Field(
        default=False,
        description="взяти теку під облік, якщо вона лежить поза простором: "
                    "оголосити її коренем справ у nyshporka.toml")
    reindex: bool = Field(
        default=True,
        description="перезібрати бібліотеку, щоб справа одразу з'явилась у переліках")


@op("case.register", summary="Завести або виправити справу: шифра, назва, роки",
    args=CaseRegisterArgs, mutates=True)
def case_register(a: CaseRegisterArgs) -> Envelope:
    """Зробити теку зі сканами справою.

    🔴 Без шифри тека лишається купою файлів: у неї немає ключа, а отже ні
    обліку прочитаного, ні місця в реєстрі, ні можливості послатись на
    знахідку. Опис пишеться В теку — вона переїжджає між дисками й потрапляє
    до колег, і опис мусить їхати з нею.

    🔴 Бібліотека перезбирається одразу. Інакше людина заводить справу, іде в
    «Мої справи» — і не бачить її там; виглядає це як «нічого не спрацювало»,
    хоча опис записаний. На великому просторі це коштує секунд двадцять, і це
    чесна ціна: система щойно дізналась про нову справу.
    """
    from nyshporka.cases.register import RegisterError, describe

    try:
        out = describe(a.case_dir, shifra=a.shifra, title=a.title,
                       doc_type=a.doc_type, year_from=a.year_from,
                       year_to=a.year_to, place=a.place, note=a.note,
                       repo_hint=a.repo)
    except RegisterError as exc:
        return fail(str(exc))
    env = ok({"case_dir": a.case_dir, "sidecar": out})
    # 🔴 Тека поза простором — мовчазна поразка всього подальшого. Опис у ній
    # запишеться, ✅ покажеться, а збірка бібліотеки її не побачить: сканується
    # лише `data/raw` (і оголошені корені справ). Далі кожен крок падав окремо
    # й не називав справжньої причини. Тому кажемо одразу і кажемо, куди класти.
    from nyshporka.cases.register import case_path, reachable

    here = case_path(a.case_dir)
    env.data["reachable"] = True
    if not reachable(here):
        from nyshporka.core.workspace import WorkspaceError, add_case_root

        if a.adopt:
            try:
                root = add_case_root(here)
            except WorkspaceError as exc:
                env.data["reachable"] = False
                env.warn("adopt_refused",
                         f"взяти теку під облік не вийшло: {exc}")
            else:
                env.data["adopted"] = str(root)
                env.warn("adopted",
                         f"теку взято під облік: {root}. Її оголошено в "
                         f"nyshporka.toml, тож вона лишиться видимою й після "
                         f"перезапуску — і поїде разом із простором.")
        else:
            env.data["reachable"] = False
            env.warn("outside_workspace",
                     "тека лежить поза простором, тож у переліках справа не "
                     "з'явиться. Поставте позначку «взяти теку під облік» — "
                     "і вона буде видима там, де лежить, без перенесення "
                     "файлів.")
    if not out.get("title"):
        env.warn("no_title",
                 "назви немає — у переліках справа буде «без назви», і впізнати "
                 "її за рік стане важко")
    if a.reindex:
        try:
            from nyshporka.library import build_library, write_library

            entries = build_library()
            write_library(entries)
            env.data["library"] = len(entries)
        except Exception as exc:
            env.warn("reindex_failed",
                     f"опис записано, але бібліотеку не перезібрано "
                     f"({type(exc).__name__}: {exc}) — справа з'явиться в "
                     f"переліках після наступної перезбірки")
    return env


# 🔴 `agent=False` і жодної фонової перевірки. Запит іде до pypi.org, тобто в
# мережу, а `PRIVACY.md` обіцяє «фонової активності в мережі немає» — обіцянка
# дорожча за зручність. Тому перевірка робиться рівно тоді, коли її попросили
# кнопкою чи командою.
@op("update.check", summary="Чи є новіша версія застосунку", agent=False)
def update_check(_: NoArgs) -> Envelope:
    """⬆️ Що стоїть, що є на pypi.org і чим оновитись.

    🔴 Шляху оновлення не було зовсім: ні команди, ні перевірки версії, ні
    рядка в `doctor`. Людина з `.exe`-установленням не мала звідки дізнатись про
    нову збірку, тож вада, полагоджена вчора, лишалась у неї назавжди — і
    питання про неї йшло у спільноту замість того, щоб зникнути оновленням.
    """
    from nyshporka.setup.update import how_to_update, install_info, latest

    # ⚠ Виклик синхронний, а обробник демона крутиться в циклі подій — тому
    # стеля очікування в `latest()` навмисно коротка. Виносити операцію в
    # `long=True` тут не варто: людина натиснула «перевірити» й чекає ВІДПОВІДІ,
    # а не рядка в переліку робіт.
    rel = latest()
    env = ok({"installed": rel.installed, "latest": rel.latest,
              "newer": rel.newer, "known": rel.known,
              "how": how_to_update(),
              "preset": install_info().get("preset", "")})
    if not rel.known:
        # 🔴 Третій стан називається вголос. «Не питали» й «свіжа» — різні
        # відповіді, і зводити їх в одну означає показати спокій там, де його
        # ніхто не перевіряв.
        env.warn("not_asked",
                 f"версію на pypi.org не дізнались: {rel.why}. Це не означає, "
                 f"що оновлень немає — означає, що ми не питали.")
    elif rel.newer:
        env.warn("outdated",
                 f"стоїть {rel.installed}, вийшла {rel.latest}. Оновлення "
                 f"робиться в терміналі й ПРИ ЗАКРИТОМУ застосунку: воно міняє "
                 f"те саме середовище, з якого зараз запущено «nysh», а "
                 f"працюючий файл на Windows заблокований.")
    return env


# `agent=False` — це питання про машину, а не про дослідження: агентові
# середовище описує `htr.env`, а решту він бачить у відмовах операцій.
@op("setup.check", summary="Чи готова ця машина читати рукопис", agent=False)
def setup_check(_: NoArgs) -> Envelope:
    """🔴 Найважливіше питання аматора — і до нього не було входу з екрана.

    Людина, яка щойно поставила застосунок, має дізнатись, чи все складеться,
    до того, як вкладе три тисячі сканів і чекатиме ніч. Ця перевірка була
    лише в командному рядку (`nysh doctor`), а на екрані картка «показати на
    прикладі» віддавала сирий JSON про середовище рушіїв — тобто відповідала
    не на те питання й не тими словами.
    """
    from nyshporka.core.ops import REGISTRY
    from nyshporka.core.workspace import workspace
    from nyshporka.setup import sample as S
    from nyshporka.setup.doctor import run

    # 🔴 Кнопка віддається лише тоді, коли операція справді зареєстрована.
    # Обіцяна в перевірці, але відсутня дія — це та сама порада, якої не
    # виконати, лише тепер вона ще й виглядає натискальною.
    known = set(REGISTRY.ops)
    checks = [{"name": c.name, "level": c.level, "detail": c.detail,
               "fix": c.fix, "op": c.op if c.op in known else ""}
              for c in run()]
    worst = ("fail" if any(c["level"] == "fail" for c in checks)
             else "warn" if any(c["level"] == "warn" for c in checks) else "ok")
    # 🔴 Названо окремим полем, бо це не поламка машини: зразок або вже
    # розгорнутий у просторі, або його треба розгорнути однією командою — і
    # плутати це з «машина не готова» означало б посилати людину лагодити те,
    # що справне.
    try:
        has_sample = S.installed(workspace())
    except Exception:
        has_sample = False          # простору ще немає — питання передчасне
    env = ok({"checks": checks, "level": worst,
              "ready": worst == "ok",
              "sample_case": has_sample,
              "sample_available": S.sample_dir() is not None})
    if worst != "ok":
        env.warn("not_ready",
                 "читання рукопису на цій машині поки не запуститься — нижче "
                 "написано, чого бракує і чим це ставиться")
    if not has_sample and env.data["sample_available"]:
        env.warn("no_sample",
                 "зразкову справу ще не розгорнуто — `nysh sample` покладе в "
                 "простір три аркуші ДАХмО 315-1-159 з готовим декодом, і "
                 "застосунок можна буде пройти наскрізь без власних сканів")
    return env


class SampleArgs(BaseModel):
    force: bool = Field(default=False,
                        description="перезаписати вже розгорнуті файли — "
                                    "потрібно лише якщо зразок зіпсовано")


# `agent=False`, як і в сусіднього `setup.check`: зразок розгортає людина, яка
# щойно поставила застосунок і хоче побачити, що він робить. Агент застосунку не
# ставить, а місце в переліку tool'ів коштує — там стеля читабельності.
@op("sample.install", summary="Розгорнути зразкову справу в просторі",
    args=SampleArgs, agent=False, mutates=True)
def sample_install(a: SampleArgs) -> Envelope:
    """📖 Три аркуші справжньої архівної справи з готовим декодом.

    🔴 Зразок не вимагає рушіїв. Усе, що йде ПІСЛЯ читання, працює одразу:
    гортач із рамкою рядка, пошук у декоді, реєстр, сховище прочитаного. Саме
    цей ланцюг людина й має побачити до того, як поставить рушії, вкладе три
    тисячі власних сканів і чекатиме ніч. Прочитати ці аркуші заново — після
    `nysh htr install` і `nysh models get`.
    """
    from nyshporka.core.workspace import workspace
    from nyshporka.setup import sample as S

    try:
        got = S.install(workspace(), force=a.force)
    except FileNotFoundError as exc:
        return fail(str(exc))
    env = ok(got)
    if not got["runs"]:
        env.warn("no_decode",
                 "кадри розгорнуто, але декоду до них немає — гортач покаже "
                 "аркуш, а пошуку в тексті не буде")
    if not got.get("registry_built"):
        env.warn("registry_stale",
                 "реєстр справ не перезібрався — «Мої справи» покажуть нуль "
                 "при розгорнутій справі; полагодити: `nysh cases build`")
    return env


class BindArgs(BaseModel):
    run: str = Field(description="ім'я теки прогону в reports/htr")
    key: str = Field(description="ключ справи: DAHMO/315/159")
    why: str = Field(default="", description="на чому стоїть рішення")


# 🔴 `agent=False` — і це не економія місця в переліку, а суть операції. Вона
# вписує рішення людини, найсильніше в реєстрі: воно перебиває всі п'ять
# автоматичних каналів резолвера. Агент, якому дати цю ручку, замість «не знаю»
# видасть правдоподібну прив'язку — а помилка тут тиха й довговічна: чужий
# декод під правильною шифрою, з якого потім цитують знахідки. Побачити нічиї
# прогони агент може (`cases.list`, `cases orphans`); вирішувати — ні.
@op("cases.bind", summary="Прив'язати прогін до справи руками",
    args=BindArgs, agent=False, mutates=True)
def cases_bind(a: BindArgs) -> Envelope:
    """🔗 Ремонт «нічиїх» прогонів — той, що досі вимагав текстового редактора.

    Хмарний прогін пише в мету теку орендованого боксу; на цій машині її немає,
    і прогін не зводиться до жодної справи. Декод при цьому є, рамки є, а
    подивитись оком нічим — гортач не знає, де лежать кадри. Автомат тут
    безсилий за побудовою, тому рішення ухвалює людина, і воно найсильніше.
    """
    from nyshporka.cases.resolve import bind_run

    try:
        got = bind_run(a.run, a.key, a.why)
    except ValueError as exc:
        return fail(str(exc))
    env = ok(got)
    if not a.why:
        env.warn("no_reason",
                 "підстава не записана — через півроку буде видно прив'язку, "
                 "але не те, на чому вона стоїть")
    env.stale_because(["ручні прив'язки змінено"], fix="nysh cases build")
    return env


class CasesBuildArgs(BaseModel):
    rescan: bool = Field(default=True,
                         description="перечитати ще й диск — потрібно, коли "
                                     "з'явились нові теки, а не лише новий декод")


# `agent=False`: агент дізнається про застарілий зріз із поля `stale` в конверті
# й має пораду в ньому ж; окремий tool на це з'їдав би місце в переліку.
@op("cases.build", summary="Перезібрати реєстр справ", args=CasesBuildArgs,
    mutates=True, long=True, agent=False)
def cases_build(a: CasesBuildArgs) -> Envelope:
    """🔴 Кнопка, на яку посилались тексти, якої не було.

    Реєстр — зріз п'яти сховищ, і будь-який прогін робить його старим за
    хвилини. Про це чесно попереджав кожен перелік — і відсилав по виправлення
    в командний рядок. Для того, хто працює формами, це те саме, що не мати
    виправлення взагалі.

    Виконує роботу застосунок: на просторі в тисячу справ перезбірка триває
    десятки секунд, і синхронна відповідь означала б завислу вкладку.

    Шлях без застосунку — команда `nysh cases build`: ті самі десятки секунд,
    але в терміналі вони видимі, а не виглядають як зависання.
    """
    return fail("перезбірку веде застосунок — підніміть його командою "
                "`nysh serve` або скористайтесь `nysh cases build`")


class CaseShowArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами")


# `agent=False` — це підживлення форми, а не дія дослідження: агент читає опис
# через `cases.list` і `pages.status`, де він іде разом зі станом обробки.
@op("case.show", summary="Поточний опис теки — щоб правити, а не передруковувати",
    args=CaseShowArgs, agent=False)
def case_show(a: CaseShowArgs) -> Envelope:
    """🔴 Правити наосліп — не правка.

    Форма без поточних значень змушує передруковувати весь опис заново, аби
    змінити одне слово; напівзаповнена форма при цьому виглядає як повний опис.
    Тому «змінити» починається з показу того, що вже записано.
    """
    import json

    from nyshporka.cases.register import SIDECAR, case_path

    d = case_path(a.case_dir)
    if not d.is_dir():
        return fail(f"теки немає: {d}")
    sc: dict[str, Any] = {}
    path = d / SIDECAR
    if path.is_file():
        try:
            sc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return fail(f"опис пошкоджено ({exc}) — виправте {path} або "
                        f"видаліть його й заведіть справу наново")
    scans = sum(1 for p in d.iterdir()
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"})
    env = ok({"case_dir": str(d), "described": bool(sc), "scans": scans,
              "sidecar": sc})
    if not sc:
        env.warn("not_described",
                 "тека ще не справа: без шифри в неї немає ключа, а отже ні "
                 "обліку прочитаного, ні місця в реєстрі")
    elif not scans:
        env.warn("no_scans",
                 "опис є, а зображень у теці немає — можливо, скани лежать "
                 "у підтеці, і читання їх не побачить")
    return env


# ── облік прочитаного ────────────────────────────────────────────────────────
class PagesStatusArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    scans: str = Field(default="", description="кома-список сканів для точкової перевірки")


@op("pages.status", summary="Що в цій справі вже дивились оком, а що ні",
    args=PagesStatusArgs, mutates=False, section="research")
def pages_status(a: PagesStatusArgs) -> Envelope:
    """🔴 Гейт перед переглядом, а не звіт після.

    Найдорожча помилка в довгій справі — передивитись ті самі аркуші вдруге:
    тисяча сторінок коштує вечора, і другий вечір на них не додає нічого. Тому
    питання «що вже бачили» ставиться до того, як щось відкривати.
    """
    from nyshporka.pagestore import store

    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    scans = [s.strip() for s in a.scans.split(",") if s.strip()]
    st = store.case_status(ref, scans or None)
    env = ok(st)
    if not st.get("case_dir_known", True):
        # 🔴 «0 на диску» тут читалось би як «скани зникли». Насправді реєстр
        # просто ще не знає, де лежить справа, — і це лікується одним кроком.
        env.warn("case_dir_unknown",
                 "теки зі сканами цієї справи реєстр не знає, тож «на диску» "
                 "нижче — не нуль, а «невідомо»")
        # Кнопка, а не команда: обидві дії в застосунку є, і саме вони тут
        # потрібні. Текст із `nysh case …` називав крок тому, кому набирати
        # його нема де.
        env.suggest("case.register", "описати теку зі сканами цієї справи")
        env.suggest("cases.build", "або перезібрати реєстр, якщо опис уже є")
    left = st.get("unnoted_count")
    if left:
        env.suggest("pages.note",
                    f"{left} сторінок ще ніхто не заносив — переглянуте без "
                    f"запису наступна сесія перегляне заново")
    return env


class PageNoteArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    scan: str = Field(description="голе ім'я файлу скана: 0030.JPG")
    # 🔴 Перелік значень, а не вільний рядок з «…» у поясненні. Приймається
    # рівно чотирнадцять слів, і поки схема мовчала про це, форма показувала
    # порожнє поле: людина писала «метрична» й діставала відмову переліком
    # англійських літералів. Оголошений перелік доїжджає в `/api/ops`, тож
    # вибір будується сам — і в консолі, і в будь-якого читача схеми.
    page_type: Literal[
        "birth", "marriage", "death", "confession", "revision", "census",
        "index", "title", "cover", "flyleaf", "blank", "illegible", "mixed",
        "other"] = Field(description="що це за сторінка")
    surnames: str = Field(default="", description="кома-список ЯК написано в джерелі")
    places: str = Field(default="")
    years: str = Field(default="", description="кома-список років: 1858,1859")
    sheet: str = Field(default="", description="архівний аркуш: 31зв-32")
    status: Literal["full", "partial", "skipped", "unreadable"] = Field(
        default="full", description="наскільки повно виписано")
    method: Literal["visual", "htr", "ocr", "hybrid", "text"] = Field(
        default="visual", description="чим читали")
    comment: str = Field(default="")
    agent: str = Field(default="", description="хто заносив")


@op("pages.note", summary="Занести переглянуту сторінку в облік", args=PageNoteArgs,
    mutates=True, section="research")
def pages_note(a: PageNoteArgs) -> Envelope:
    """🔴 без винятків: кожен скан, який реально відкривали, заноситься.

    Навіть якщо він виявився пустишкою. Негативний результат коштує тих самих
    очей, що й позитивний, і без запису наступна сесія перегляне той самий
    аркуш ще раз. У коментарі варто писати, чому це не те.

    ⚠ `status=full` ставиться, лише якщо виписано всі прізвища сторінки —
    інакше `partial`. Від цього залежить, чи можна довіряти нулю по цій справі.
    """
    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import PageNote

    def _csv(v: str) -> list[str]:
        return [x.strip() for x in v.split(",") if x.strip()]

    try:
        ref = store.resolve_case(a.case)
        note = PageNote(
            scan=a.scan, page_type=a.page_type,
            surnames=_csv(a.surnames), places=_csv(a.places),
            years=[int(y) for y in _csv(a.years)], sheet=a.sheet,
            status=a.status, method=a.method,
            comment=a.comment, agent=a.agent)
    except (ValidationError, ValueError) as exc:
        return fail(str(exc))
    report = store.annotate_pages(ref, [note])
    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict()})
    if a.status == "full" and not note.surnames:
        env.warn("full_without_surnames",
                 "status=full означає «виписано всі прізвища сторінки», а їх "
                 "тут жодного. Якщо сторінка не порожня — це має бути partial")
    if a.method in ("htr", "text"):
        env.warn("not_eye_verified",
                 "метод каже, що читали декод, а не зображення — така гілка "
                 "успадковує чужі помилки; у коментарі варто позначити «оком не звірено»")
    return env


class PageNoteBatchArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    notes: str = Field(description="JSON-масив анотацій (PageNote) або JSON-lines")
    replace: bool = Field(default=False,
                          description="замінити наявні анотації, а не домержити")


# ⚠ `agent=False`, і це не приниження операції. Стеля агентських інструментів
# у 18 — свідомий приймач: перелік, який модель мусить дочитати до кінця, не
# росте безкарно, а два інструменти на ту саму дію («занеси сторінку» й «занеси
# сторінки») — рівно та бавовна, від якої стеля й стереже. Агент має
# `pages.note`, а масовий шлях скіли ведуть командним рядком
# (`nysh pages note-batch`), як і `records add`.
@op("pages.note_batch", summary="Занести переглянуті сторінки пачкою",
    args=PageNoteBatchArgs, mutates=True, agent=False, section="research")
def pages_note_batch(a: PageNoteBatchArgs) -> Envelope:
    """Головний масовий шлях: аркуші заносять десятками за один перегляд.

    🔴 Крива анотація НЕ забирає з собою решту. Валідні лягають, невалідні
    вертаються переліком із номером і сканом: втратити сорок сторінок через
    одну одруківку — гірше, ніж занести тридцять дев'ять і назвати сорокову.

    🔴 Ключ сторінки звіряється з ІМЕНАМИ ФАЙЛІВ на диску. Ключ без розширення
    («0106» замість «0106.jpg») проходить валідацію моделі й зі сканом не
    матчиться — сторінка, яку вже дивились оком, лишається в черзі на рендер.
    Саме так 16.08.2026 розійшлись 62 ключі у 23 справах, і побачити це можна
    лише звіркою з диском. Тека без зображень (справа з PDF) дає порожній
    перелік — там звіряти нема з чим, і мовчання правильне.
    """
    import json as _json

    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import PageNote

    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))

    raw = (a.notes or "").strip()
    items: list[Any] = []
    if raw:
        try:
            got = _json.loads(raw)
            items = got if isinstance(got, list) else [got]
        except _json.JSONDecodeError:
            # JSON-lines — агенти пишуть і так, і так, і вимагати одного
            # формату означало б завести глухий кут на рівному місці.
            try:
                items = [_json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            except _json.JSONDecodeError as exc:
                return fail(f"не JSON: {exc}")

    notes: list[Any] = []
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        try:
            notes.append(PageNote.model_validate(item))
        except ValidationError as exc:
            errors.append({"index": i,
                           "scan": item.get("scan") if isinstance(item, dict) else None,
                           "error": str(exc)})
    report = (store.annotate_pages(ref, notes, replace=a.replace) if notes
              else store.MergeReport(path=""))
    disk = set(store._disk_scans(ref))
    off_disk = [n.scan for n in notes if n.scan not in disk] if disk else []

    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict(),
              "ok": len(notes), "failed": len(errors), "errors": errors,
              "off_disk": off_disk})
    if errors:
        env.warn("some_notes_refused",
                 f"{len(errors)} анотацій не прийнято — решта {len(notes)} лягла")
    if off_disk:
        env.warn("off_disk",
                 f"{len(off_disk)} сканів немає на диску теки справи "
                 f"({', '.join(off_disk[:5])}{'…' if len(off_disk) > 5 else ''}). "
                 f"Ключ мусить збігатися з іменем файлу, інакше сторінка "
                 f"лишиться в черзі на перегляд")
    full_blank = [n.scan for n in notes if n.status == "full" and not n.surnames]
    if full_blank:
        env.warn("full_without_surnames",
                 f"{len(full_blank)} сторінок занесено як «виписано всі "
                 f"прізвища» з порожнім переліком — якщо вони не порожні, це "
                 f"partial, і від цього залежить, чи можна вірити нулю по справі")
    return env


class RecordsAddArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    records: str = Field(description="JSON-масив записів (Record)")


@op("records.add", summary="Занести розібрані записи джерела", args=RecordsAddArgs,
    mutates=True, section="research")
def records_add(a: RecordsAddArgs) -> Envelope:
    """Хто/коли/батьки/восприємники — структурою, а не прозою.

    Невалідні елементи пропускаються зі звітом, валідні лягають: не втрачати
    сорок розібраних актів через одну одруківку в сорок першому.
    """
    import json as _json

    from pydantic import ValidationError

    from nyshporka.pagestore import store
    from nyshporka.pagestore.models import Record

    try:
        raw = _json.loads(a.records)
    except ValueError as exc:
        return fail(f"records не є JSON: {exc}")
    if not isinstance(raw, list):
        raw = [raw]
    try:
        ref = store.resolve_case(a.case)
    except ValueError as exc:
        return fail(str(exc))
    recs, errors = [], []
    for i, item in enumerate(raw):
        try:
            recs.append(Record.model_validate(item))
        except ValidationError as exc:
            errors.append({"index": i, "error": str(exc)[:400]})
    report = store.add_records(ref, recs) if recs else store.MergeReport(path="")
    env = ok({"case": ref.key, "shifra": ref.shifra, **report.as_dict(),
              "ok": len(recs), "failed": len(errors), "errors": errors})
    if errors:
        env.warn("some_records_refused",
                 f"{len(errors)} записів не пройшли перевірку — решта {len(recs)} "
                 f"занесені; виправте й додайте окремо")
    return env


# ── експорт ──────────────────────────────────────────────────────────────────
class ExportArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    what: Literal["acts", "records", "pages", "tally"] = Field(
        default="acts",
        description="acts — рядок=акт, ролі в колонки · records — рядок=учасник "
                    "(тут фільтрується прізвище, стан, вік) · pages · tally")


def _export_case_file(case: str) -> tuple[Any, Any] | Envelope:
    """Справа зі сховища або готовий конверт відмови — спільне для обох операцій."""
    from nyshporka.pagestore import store

    try:
        ref = store.resolve_case(case)
    except ValueError as exc:
        return fail(str(exc))
    cf = store.load_case(ref)
    if cf is None:
        return fail(f"по справі {ref.shifra} ще нічого не занесено")
    return ref, cf


def _empty_export_note(env: Envelope, shifra: str, what: str,
                       cf: Any = None) -> Envelope:
    """🔴 Порожня таблиця мусить сказати, ЧОМУ вона порожня.

    Без цього рядка вона читається як «у книзі цього немає», хоча означає
    «цього ще не вичитували»: аркуші могли бути прочитані машиною, а акти в
    поля не розібрані. Різниця тут та сама, що між нулем і відсутнім
    знаменником.

    І якщо в справі є хоч щось інше, це називається: інакше людина вирішує, що
    по справі немає нічого, маючи в сховищі перелік прізвищ по аркушах.
    """
    env.warn(
        "empty_export",
        f"у справі {shifra} немає нічого типу «{what}» — це стан обліку, а не "
        f"властивість справи: акти в поля, схоже, ще не розбирали")
    if cf is not None and what != "pages" and cf.pages:
        env.warn("pages_are_there",
                 f"але аркушів у сховищі {len(cf.pages)} — виписка «pages» "
                 f"віддасть їхні прізвища й географію вже зараз")
    return env


@op("export.case", summary="Викласти прочитане зі справи таблицею", args=ExportArgs,
    mutates=False, section="research")
def export_case(a: ExportArgs) -> Envelope:
    """Прочитане зі справи — у плаский вигляд, придатний до таблиці.

    🔴 Кожен рядок несе скан, а не лише текст. Виписка без посилання на аркуш —
    це переказ: перевірити його можна тільки перечитавши всю справу, тобто
    ніяк. Саме тому тут немає режиму «лише імена».

    Віддає дані; файл пише `export.write`. Самі вигляди й правила їх побудови —
    у `nyshporka.tabular`.
    """
    from nyshporka import tabular

    got = _export_case_file(a.case)
    if isinstance(got, Envelope):
        return got
    ref, cf = got

    columns, rows = tabular.build(cf, a.what)
    # Шапки їдуть разом із даними, а не складаються на боці читача: інакше
    # браузер і командний рядок називали б ті самі колонки по-різному, і
    # розійшлись би вони тихо.
    env = ok({"case": ref.key, "shifra": ref.shifra, "what": a.what,
              "columns": columns, "rows": rows,
              "labels": {c: tabular.label_for(c, a.what) for c in columns}})
    if not rows:
        _empty_export_note(env, ref.shifra, a.what, cf)
    return env


class ExportWriteArgs(BaseModel):
    case: str = Field(description="справа у будь-якому форматі")
    out: str = Field(description="куди писати файл; шлях обовʼязковий і явний")
    what: Literal["acts", "records", "pages", "tally", "all"] = Field(
        default="acts", description="«all» — усі вигляди аркушами, лише для xlsx")
    format: Literal["csv", "tsv", "xlsx"] = Field(
        default="xlsx", description="xlsx потребує openpyxl; csv/tsv — ні")
    headers: Literal["uk", "raw"] = Field(
        default="uk", description="uk — людські шапки, raw — машинні ключі полів")
    overwrite: bool = Field(
        default=False, description="дозволити перезапис наявного файлу")


# `agent=False`: файл лягає ЗА МЕЖІ простору, у теку, яку називає людина. Це
# рішення про власний архів, а не крок конвеєра, — той самий випадок, що й
# `roots.add`. Агентові лишається `export.case`: ті самі дані, без запису на
# чужий диск. Плюс стеля переліку tool'ів насичена, і місце в ній коштує
# дорожче за зручність.
@op("export.write", summary="Записати таблицю справи файлом (XLSX/CSV/TSV)",
    args=ExportWriteArgs, mutates=False, agent=False, section="research")
def export_write(a: ExportWriteArgs) -> Envelope:
    """Виписка зі справи файлом — щоб віднести її в Ексель чи чужу програму.

    🔴 Шлях обовʼязковий і нікуди не підставляється сам. Людина вивантажує, щоб
    забрати дані за МЕЖІ застосунку, і застосунок не має права вирішувати за
    неї, у якій теці вони опиняться. З тієї самої причини наявний файл не
    перезаписується мовчки.

    `mutates=False`: сховище не змінюється — файл лягає назовні.
    """
    from nyshporka import tabular

    got = _export_case_file(a.case)
    if isinstance(got, Envelope):
        return got
    ref, cf = got

    if a.what == "all" and a.format != "xlsx":
        return fail("«all» кладе кілька виглядів аркушами, а це вміє лише xlsx; "
                    f"для csv/tsv назвіть один вигляд: {', '.join(tabular.VIEWS)}")

    dest = Path(a.out).expanduser()
    if dest.exists() and not a.overwrite:
        return fail(f"{dest} уже існує; додайте overwrite, щоб перезаписати")

    views = list(tabular.VIEWS) if a.what == "all" else [a.what]
    built = [(v, *tabular.build(cf, v)) for v in views]
    human = a.headers == "uk"

    try:
        if a.format == "xlsx":
            # 🔴 Порожній вигляд аркушем не стає: аркуш «Підсумки» з самою
            # шапкою читається як «підсумків у книзі немає», хоча означає, що їх
            # не вичитували. Що саме пропущено — сказано попередженням нижче.
            # Якщо порожні всі, лишається один аркуш: файл без жодного аркуша
            # Ексель не відкриє взагалі.
            sheets = [(v, c, r) for v, c, r in built if r] or built[:1]
            report = tabular.write_xlsx(dest, sheets, human=human)
        else:
            _, columns, rows = built[0]
            report = tabular.write_delimited(
                dest, columns, rows, view=built[0][0],
                sep=tabular.SEPARATOR[a.format], human=human)
    except tabular.ExportError as exc:
        return fail(str(exc))
    except OSError as exc:
        return fail(f"не вдалося записати {dest}: {exc}")

    env = ok({"case": ref.key, "shifra": ref.shifra, "what": a.what,
              "format": a.format, **report,
              "views": [v for v, _, r in built if r]})
    if not report["rows"]:
        _empty_export_note(env, ref.shifra, a.what, cf)
    skipped = [v for v, _, r in built if not r]
    if skipped and a.what == "all" and report["rows"]:
        env.warn("views_skipped",
                 "порожні вигляди аркушами не стали: " + ", ".join(skipped))
    if report["truncated"]:
        env.warn("cells_truncated",
                 f"{report['truncated']} комірок обрізано на межі формату "
                 f"(32767 символів) — повний текст лишається у сховищі")
    if report["cleaned"]:
        env.warn("chars_stripped",
                 f"{report['cleaned']} комірок містили керівні символи, яких "
                 f"Ексель не приймає, — їх прибрано з ФАЙЛУ, не зі сховища")
    return env


# ── завантаження як довга робота ─────────────────────────────────────────────
class AcquireArgs(BaseModel):
    source: str = Field(description="id джерела")
    ref: str = Field(description="адреса справи чи плівки")
    dest: str = Field(default="", description="куди класти; порожньо = у простір")
    frames: str = Field(default="", description="діапазон «12-80»; порожньо = всі")


class CaseInfoArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами")
    script: Literal["", "latin", "cyrillic", "mixed"] = Field(
        default="", description="письмо, якщо вирішили самі")


# `agent=False`: це картка для ока перед довгою роботою. Агент не витрачає ніч
# карти й не звіряє письмо по перших сторінках — йому вистачає `read.plan`.
@op("htr.case_info", summary="Що це за справа й чим її читати — ДО прогону",
    args=CaseInfoArgs, mutates=False, agent=False, section="htr")
def htr_case_info(a: CaseInfoArgs) -> Envelope:
    """Опис справи, письмо з причиною, покриття рушіями й розриви.

    🔴 письмо йде З причиною, і причина важить більше за саме письмо. Здогад
    із назви теки й запис у паспорті справи — різні за надійністю на порядок,
    а на екрані виглядали б однаково. Помилка тут не дає збою: вона дає
    осмислене на вигляд сміття через годину роботи.

    🔴 «Прогін є» мовчки читається як «справу прочитано». Для тримовної книги
    це неправда: один рушій закриває лише своє письмо, і половина сторінок
    лишається непрочитаною при зеленому статусі. Тому розриви називаються
    окремо від прогонів.
    """
    from nyshporka.htr import pick

    try:
        card = pick.case_info(a.case_dir, script_hint=a.script)
    except Exception as exc:
        return fail(f"картка справи недоступна ({type(exc).__name__}: {exc})")
    env = ok(card)
    if not card.get("frames"):
        env.warn("no_frames",
                 "у теці немає жодного кадру — читати нема чого. Перевірте "
                 "шлях: перегляд і читання не рекурсивні")
    if card.get("script") == "unknown":
        env.warn("script_unknown",
                 "письмо невідоме, і це повна відповідь, а не порожня: "
                 "мовчазний здогад «кирилиця» дав би сміття, схоже на текст")
    elif card.get("script_trust") == "folder":
        env.warn("script_guessed", card.get("script_why") or "")
    if card.get("script") == "mixed":
        env.warn("mixed_script",
                 "у справі два письма — потрібні два прогони окремими теками: "
                 "один рушій закриє лише своє")
    for gap in card.get("gaps") or []:
        env.warn(str(gap.get("kind") or "gap"), str(gap.get("text") or ""))
    if not card.get("found"):
        env.suggest("case.register",
                    "описати теку — без шифри прогін не прив'яжеться до справи")
    return env


class ReadArgs(BaseModel):
    case_dir: str = Field(description="тека зі сканами (пласка, без підтек)")
    out_dir: str = Field(default="", description="куди класти текст; порожньо = у простір")
    script: Literal["", "latin", "cyrillic"] = Field(
        default="", description="письмо; порожньо = вгадати з імені теки")
    second_voice: bool = Field(
        default=True,
        description="читати ще й другим рушієм — він помиляється інакше")
    case_key: str = Field(default="", description="шифра справи у мету прогону")
    # ── важелі для досвідчених ───────────────────────────────────────────────
    # 🔴 Прокинуто рівно ті, у яких є зміряне правило користування. Ручка без
    # такого правила — пастка: її крутять навмання, а ціна помилки тут ніч
    # роботи й текст, який виглядає осмисленим.
    model: str = Field(default="", description="ваги замість добраних самим")
    limit: int = Field(default=0, ge=0, le=100_000,
                       description="лише перші N кадрів — спершу спробувати")
    pages: str = Field(default="", pattern=r"^$|^\d+(-\d+)?(,\d+(-\d+)?)*$",
                       description="діапазони кадрів: 1-50,60")
    workers: int = Field(default=1, ge=1, le=8,
                         description="скільки процесів ділять карту; "
                                     "вирішує вільна VRAM, а не ядра")
    seg_height: int = Field(default=0, ge=0, le=4000,
                            description="висота сегментації; єдиний важіль, "
                                        "що коштує якістю пошуку")
    device: str = Field(default="", description="cuda:0 · cpu")


# `agent=False`: план рахує й сам `read.start`, а людині він потрібен окремо —
# щоб побачити його до того, як натисне «читати». Агентові двох tool'ів на
# одну дію не треба.
@op("read.plan", summary="Чим і як читатимемо цю справу — ДО запуску",
    args=ReadArgs, mutates=False, agent=False, section="htr")
def read_plan(a: ReadArgs) -> Envelope:
    """Скільки кадрів, яке письмо, яка модель, куди ляже текст.

    🔴 Окрема операція, а не крок усередині запуску. Справа читається годинами;
    дізнатись «модель не та» або «кадрів не двадцять, а три тисячі» після
    старту означає втратити ніч. Той самий поділ, що `manifest` перед `fetch`.
    """
    from nyshporka.htr.run import ReadError, plan

    try:
        p = plan(a.case_dir, out_dir=a.out_dir, script=a.script,
                 second_voice=a.second_voice)
    except ReadError as exc:
        return fail(str(exc))
    env = ok({"plan": p.as_dict()})
    if not a.script:
        # Здогад про письмо слабкий за побудовою — з імені теки нічого не
        # видно. Мовчазний здогад тут дав би тихе сміття.
        env.warn("script_guessed",
                 f"письмо «{p.script}» вгадано з імені теки. Помилка тут дає "
                 f"не збій, а осмислене на вигляд сміття — звірте перші "
                 f"сторінки або вкажіть письмо явно")
    if a.seg_height:
        # 🔴 Єдиний важіль, що коштує якістю, а не лише часом, — і мовчати про
        # це не можна: збій він дає не одразу, а через місяць, коли по декоду
        # шукають прізвище й не знаходять.
        env.warn("seg_height_costs_quality",
                 f"висота сегментації {a.seg_height} px: 1440 ≈ −4% слів, "
                 f"1200 ≈ −10% повноти пошуку. Це не швидкість задарма")
    if a.workers > 1:
        env.warn("workers_share_the_card",
                 f"{a.workers} процеси ділять одну карту: виграш дає вільна "
                 f"VRAM, а не ядра. Приймач — симптом (чи не впало все), а не "
                 f"секунди")
    if p.voice is None and p.script == "cyrillic":
        env.warn("single_voice",
                 "другого голосу немає — читатиме один рушій. Другий помиляється "
                 "інакше й витягує те, де перший підставив правдоподібне слово")
    return env


@op("read.start", summary="Прочитати справу рукописним рушієм", args=ReadArgs,
    mutates=True, long=True, section="htr")
def read_start(a: ReadArgs) -> Envelope:
    """Ставить читання в чергу; саму роботу веде застосунок.

    Викликана поза застосунком, операція чесно каже, що черги немає, — замість
    того щоб тихо нічого не зробити.

    🔴 Синхронний шлях, який працює завжди: `nysh read <тека>`. Він читає прямо
    в процесі й друкує прогрес — так і задумано, бо прогін ставлять на ніч,
    часто по ssh. Черга ж потрібна там, де роботу замовляють з іншого вікна:
    `nysh serve`, далі `job.query`. Ця відповідь навмисно називає обидва шляхи
    до виклику (`nysh op read.start --describe`), бо дізнатись про режим
    постфактум означає витратити хід на відмову.

    ⚠ `nysh read` не ідемпотентний: другий запуск по тій самій теці б'ється з
    першим за карту. Перед стартом перевірте, чи читання вже не йде.
    """
    return fail("читання веде застосунок — підніміть його командою "
                "`nysh serve` або запустіть `nysh read <тека>`")


@op("acquire.start", summary="Завантажити справу або плівку", args=AcquireArgs,
    mutates=True, long=True, section="material")
def acquire_start(a: AcquireArgs) -> Envelope:
    """Ставить у чергу; сама робота йде у застосунку.

    🔴 Синхронно цього робити не можна навіть у CLI-подібному вигляді: справа
    буває на кілька гігабайтів, тобто на годину. Відповідь мусить бути
    посиланням на завдання, а не очікуванням.

    Шлях без черги — команда `nysh get <джерело> <ref> --out <тека>`: вона
    друкує маніфест до завантаження, тож обсяг видно перед тим, як його брати.
    Черга ж є лише в піднятому застосунку (`nysh serve`), і саме тому режим
    названо тут — щоб він був відомий до виклику, а не з відмови.
    """
    return fail("завантаження виконує застосунок — підніміть його командою "
                "`nysh serve` або скористайтесь `nysh get`")


# ── завдання ─────────────────────────────────────────────────────────────────
class JobArgs(BaseModel):
    action: Literal["list", "status", "wait", "cancel"] = "list"
    job_id: str = ""
    timeout_s: int = Field(default=30, ge=0, le=120,
                           description="скільки чекати зміни (для action=wait)")
    since: int = Field(default=0, description="курсор: віддати лише новіше за нього")


@op("job.query", summary="Стан довгих робіт: перелік, очікування, скасування",
    args=JobArgs, mutates=False)
def job_query(a: JobArgs) -> Envelope:
    """Стан завдань — рівно там, де є черга, тобто в піднятому застосунку.

    🔴 Поза ним відповіді немає й бути не може, і це не половина функції: у
    командному рядку довга робота йде синхронно (`nysh read`, `nysh get`,
    `nysh cases build`) і сама друкує прогрес, тож питати про стан нема кого —
    він перед очима. Порожній список тут був би гіршим за відмову: «жодного
    завдання» читається як «нічого не запущено», а запущене могло крутитись у
    сусідньому вікні.
    """
    # Черга живе в демоні; без нього відповідаємо чесно, а не порожнім списком.
    from nyshporka.runtime import current_bus

    bus = current_bus()
    if bus is None:
        return fail("черга недоступна: застосунок не запущено. "
                    "Підніміть його командою `nysh serve`")
    if a.action == "list":
        return ok({"jobs": [j.as_dict() for j in bus.jobs()], "seq": bus.seq})
    if a.action in ("status", "cancel") and not a.job_id:
        return fail(f"для action={a.action} потрібен job_id")
    if a.action == "status":
        job = bus.get(a.job_id)
        return ok(job.as_dict()) if job else fail(f"немає завдання {a.job_id}")
    return fail(f"дія «{a.action}» доступна лише в запущеному застосунку")


# ── профіль дослідження ──────────────────────────────────────────────────────
#: Що саме людина втрачає без профілю. Формулювання спільне для всіх трьох
#: облич, і воно навмисно каже правду про СЬОГОДНІШНІЙ код.
#:
#: 🔴 Тут стояло «пошук працюватиме на прізвище чужого дослідження». Це було
#: не так: `q` у `search.run` обов'язкове, дефолтного прізвища в пакеті немає
#: ніде, і взятись чужому не було звідки. Фраза лишилась від конвеєра, де рід
#: жив константами в модулях (`htr/runner.py`), і лякала вигаданим ризиком —
#: заразом ховаючи справжній: без профілю всі написання прізвища доводиться
#: пригадувати щоразу самому.
NO_PROFILE = ("рід не названо: прізвище й усі його написання доведеться "
              "набирати щоразу руками — а рушій калічить саме середину слова, "
              "тож пригадати їх усі важче, ніж здається")


def _profile_payload(p: Any) -> dict[str, Any]:
    from nyshporka.core import morph

    return {"present": True,
            "name": p.name, "display": p.display, "paradigm": p.paradigm_id,
            "stems": p.stems, "roots": [r for r, _ in p.roots],
            "substrings": list(p.substrings),
            "spellings": p.all_spellings(),
            # ⚠ `ALL_`, а не `ORTHOGRAPHIES`: `spellings` нижче рахуються з
            # УСІХ основ профілю, і віддати таблиці лише з питаних означало б
            # показати перелік написань, якого таблиці під ним не пояснюють.
            "forms": {o: p.forms(o) for o in p.stems if o in morph.ALL_ORTHOGRAPHIES},
            "selftest_mode": (p.selftest or {}).get("mode", "strict")}


def _profile_shell(env: Envelope) -> dict[str, Any]:
    """Довідка, потрібна формі незалежно від того, чи профіль є.

    Віддається й у порожньому стані — саме там вона й потрібна: без переліку
    парадигм і орфографій форму заведення нема з чого намалювати.
    """
    from nyshporka.core import morph
    from nyshporka.core.profile import (
        ProfileError,
        available,
        config_path,
        paradigm_choices,
        read_source,
    )

    out: dict[str, Any] = {"paradigms": paradigm_choices(),
                           "orthographies": list(morph.ORTHOGRAPHIES)}
    try:
        out["path"] = str(config_path())
        out["available"] = available()
        out["source"] = read_source()["text"]
    except ProfileError as exc:
        # Побитий файл — окремий стан, і його не можна плутати з «профілю
        # немає»: перше лікується правкою тексту, друге — заведенням.
        out["broken"] = str(exc)
        out["available"] = []
        out["source"] = _raw_text()
    return out


def _active_name() -> str:
    """Ім'я профілю, який шукається зараз. Порожньо — жодного."""
    from nyshporka.core.profile import ProfileError, active
    from nyshporka.core.workspace import WorkspaceError

    try:
        return active().name
    except (ProfileError, WorkspaceError):
        return ""


def _raw_text() -> str:
    """Текст конфігу повз розбір — щоб редактор показав те, що не парситься."""
    from nyshporka.core.profile import config_path

    try:
        path = config_path()
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except Exception:
        return ""


# `agent=False` — це конфіг дослідження, а не дія. Читається файлом.
@op("profile.show", summary="Чий рід шукаємо: форми, корені, парадигма",
    agent=False)
def profile_show(_: NoArgs) -> Envelope:
    """Профіль або чесна відповідь, що його ще немає.

    🔴 «Профілю ще немає» — НОРМАЛЬНИЙ стан щойно створеного простору, а не
    відмова: `nysh init` його не створює, шаблону в комплекті теж немає. Доти
    операція повертала `fail`, а конверт відмови не має `data` — тобто саме
    тоді, коли треба намалювати форму заведення, екран не діставав ні переліку
    парадигм, ні шляху до файла, ні кнопки. Та сама вада вже виправлена в
    `cases.list` («реєстру ще немає»), і формулювання там записане дослівно:
    вихід зникав саме тоді, коли був потрібен.

    Відмовою лишається тільки те, що справді відмова: немає простору.
    """
    from nyshporka.core.profile import ProfileError, active
    from nyshporka.core.workspace import WorkspaceError

    try:
        shell = _profile_shell(ok())
    except WorkspaceError as exc:
        return fail(str(exc))
    try:
        p = active()
    except ProfileError as exc:
        env = ok({"present": False, "why": str(exc), **shell})
        env.warn("no_profile", NO_PROFILE)
        env.suggest("profile.set", "назвати рід — прізвище й написання")
        return env
    except WorkspaceError as exc:
        return fail(str(exc))
    return _warn_uncovered(ok({**_profile_payload(p), **shell}), p)


def _warn_uncovered(env: Envelope, p: Any) -> Envelope:
    """Сказати вголос, що частина написань не породжується.

    🔴 Без цього втрата не має ЖОДНОЇ ознаки: список написань виглядає повним,
    бо коротшим він і мав би бути — просто в ньому немає цілої орфографії.
    """
    gap = p.uncovered_orthographies()
    if gap:
        env.warn("paradigm_gap",
                 f"парадигма «{p.paradigm_id}» не має таблиці для: "
                 f"{', '.join(gap)} — основа задана, а написання цими "
                 f"орфографіями не породжуються й не шукаються")
    return env


class ProfileSetArgs(BaseModel):
    display: str = Field(description="прізвище, як воно пишеться: Сікорський")
    name: str = Field(default="", description="ключ профілю; типово — з прізвища")
    # 🔴 Перелік будується з реєстру, а не переписується. Доти він стояв
    # літералом і тут, і в довідці CLI, і в шаблоні скіла — три копії, які при
    # додаванні парадигми мовчки застарівають, причому третя їде в дистрибутиві.
    paradigm: str = Field(default="adj_skyi", description=morph.paradigm_ids())
    orth: str = Field(default="uk",
                      description="якою орфографією подано прізвище: "
                                  "uk | ru_modern | ru_prereform | pl")
    stems: dict[str, str] = Field(
        default_factory=dict,
        description="орфографія → ОСНОВА без закінчення: {'pl': 'Liszczyn'}")
    roots: list[str] = Field(default_factory=list,
                             description="корені для фаззі-пошуку")
    substrings: list[str] = Field(
        default_factory=list, description="куски, за якими прізвище впізнається")


# 🔴 `agent=False`, як і в `profile.show`. Прізвище й написання питаються в
# людини, а не виводяться з назви теки чи з першої знайденої справи — це
# записано в скілі окремим 🛑. Агентові лишається командний рядок, де той самий
# запис іде через цю саму операцію.
@op("profile.set", summary="Назвати рід: прізвище, парадигма, основи",
    args=ProfileSetArgs, mutates=True, agent=False)
def profile_set(a: ProfileSetArgs) -> Envelope:
    """Завести профіль або оновити поля, які показує форма.

    🔴 Не переписує файл, писаний рукою. Подробиці й приймач — у `core.profile.save`.
    """
    from nyshporka.core.profile import ProfileError, resolve, save
    from nyshporka.core.workspace import WorkspaceError

    try:
        res = save(a.name, a.display, paradigm=a.paradigm, orth=a.orth,
                   stems=dict(a.stems), roots=list(a.roots),
                   substrings=list(a.substrings))
    except (ProfileError, WorkspaceError) as exc:
        env = fail(str(exc))
        env.suggest("profile.source", "правити текстом — форма тут не пройде")
        return env
    # 🔴 Показуємо ТОЙ профіль, який щойно записали, а не активний. Другий
    # профіль у файлі активним не стає (`fallback` уже стоїть), і віддавати
    # замість нього чужий означало б показати людині чуже прізвище рівно в
    # мить, коли вона зберегла своє.
    try:
        wrote = resolve(res["name"])
    except ProfileError as exc:
        return fail(str(exc))
    env = ok({**res, **_profile_payload(wrote)})
    if wrote.name != _active_name():
        env.warn("not_active",
                 f"профіль «{wrote.name}» записано, але шукається зараз інший — "
                 f"активний задає `fallback` у файлі")
    missing = [o for o in ("ru_prereform", "pl")
               if not (env.data.get("stems") or {}).get(o)]
    if missing:
        # ⚠ Не помилка, а межа знайденого: без основи на дореформену орфографію
        # метрики XIX ст. просто не шукаються, і мовчати про це не можна.
        env.warn("stems_partial",
                 f"основи не задано для: {', '.join(missing)} — цими "
                 f"написаннями прізвище не шукатиметься")
    return _warn_uncovered(env, wrote)


class ProfileSourceArgs(BaseModel):
    text: str = Field(default="",
                      description="новий текст конфігу; порожньо — лише прочитати")


@op("profile.source", summary="Конфіг роду як текст: прочитати або записати",
    args=ProfileSourceArgs, mutates=True, agent=False)
def profile_source(a: ProfileSourceArgs) -> Envelope:
    """Сирий YAML — для полів, яких форма не знає.

    ⚠ `mutates=True` навіть на читанні: одна операція з двома режимами інакше
    оминала б перевірку токена в тому режимі, який пише. Дешевше оголосити її
    мутувальною, ніж розводити на дві й пояснювати, чим вони різняться.

    🔴 Порожній `text` НЕ означає «стерти файл». Стерти конфіг випадковою
    відправкою порожньої форми — саме той клас втрати, після якого не лишається
    ні даних, ні сліду; порожнеча тут читається як «покажи, що там».
    """
    from nyshporka.core.profile import ProfileError, read_source, write_source
    from nyshporka.core.workspace import WorkspaceError

    try:
        if not a.text.strip():
            env = ok({"written": False, **read_source()})
            env.warn("read_only", "показано як є — записано нічого не було")
            return env
        res = write_source(a.text)
    except (ProfileError, WorkspaceError) as exc:
        return fail(str(exc))
    env = ok({"written": True, **res, **read_source()})
    env.suggest("profile.show", "звірити написання, які з цього вийшли")
    return env


# ── архіви ───────────────────────────────────────────────────────────────────
class FondArgs(BaseModel):
    repo: str = Field(description="код архіву, напр. DAHMO")
    fond: str = Field(description="номер фонду")


# `agent=False` — довідка про фонд: потрібна раз на дослідження й читається
# з паку архівів. У переліку tool'ів вона з'їдала б місце, яке модель мусить
# дочитати до кінця.
@op("archive.fond", summary="Що відомо про фонд: губернія, опис у ключі, дефолти",
    args=FondArgs, agent=False, section="material")
def archive_fond(a: FondArgs) -> Envelope:
    from nyshporka.archives import active
    from nyshporka.library import default_opys, opys_in_key

    pk = active()
    f = pk.fonds.get((a.repo.upper(), a.fond))
    # 🔴 Відповідь про опис бере той самий предикат, яким збирається ключ.
    # Читаючи натомість поле паку, команда відповідала «ні» там, де бібліотека
    # опис включала, — а питання задають рівно перед тим, як складати ключ.
    in_key = opys_in_key(a.repo.upper(), a.fond)
    data = {"repo": a.repo.upper(), "repo_label": pk.repo_label(a.repo),
            "fond": a.fond, "known": f is not None,
            "name": f.name if f else "", "guberniya": pk.guberniya(a.repo, a.fond),
            "default_opys": default_opys(a.repo.upper(), a.fond),
            "opys_in_key": in_key,
            "note": f.note if f else ""}
    env = ok(data)
    if f is None:
        env.warn("unknown_fond",
                 f"фонд {a.repo.upper()} {a.fond} невідомий паку — правила за "
                 f"замовчуванням можуть не підійти")
    elif in_key:
        env.warn("opys_in_key",
                 "у цьому фонді опис входить у ключ справи: без нього різні "
                 "книги злипаються в одну")
    return env


class ArchiveAddArgs(BaseModel):
    code: str = Field(description="внутрішній код: латиниця й цифри (DAKO)")
    label: str = Field(description="скорочення, яким його пишуть у шифрі (ДАКО)")
    name: str = Field(default="", description="повна назва архіву")
    country: str = Field(default="UA", description="код країни")


# `agent=False` — перелік архівів агент бачить у відмовах операцій і в довідці
# про фонд; окремим tool'ом він з'їдав би місце в переліку, який модель мусить
# дочитати до кінця. А от екранові він потрібен: без нього форма заведення
# справи вимагає значення зі списку, якого ніде не показано.
@op("archives.list", summary="Які архіви застосунок знає", agent=False,
    section="material")
def archives_list(_: NoArgs) -> Envelope:
    """Склад паку архівів — для селекта у формі й для довідки.

    🔴 Список був закритий і невидимий одночасно: валідатор шифри вимагав
    назву саме звідси, а показати його не було де. Дослідник із незнайомим
    архівом упирався в глухий кут і не мав як зрозуміти, що взагалі приймається.
    """
    from nyshporka.archives import active

    pk = active()
    rows = [{"code": code, "label": r.label, "name": r.name,
             "country": r.country,
             # Канонічний код: два записи одного архіву («ДАВіО») мусять
             # показуватись як один вибір, а не як два однакові рядки.
             "canon": pk.canon_repo(code)}
            for code, r in sorted(pk.repositories.items(),
                                  key=lambda kv: kv[1].label)]
    seen: set[str] = set()
    uniq = [r for r in rows if not (r["canon"] in seen or seen.add(r["canon"]))]
    return ok({"archives": uniq, "total": len(uniq),
               "overlay": str(_overlay_or_empty())})


def _overlay_or_empty() -> str:
    from nyshporka.archives import pack as PK

    try:
        p = PK.overlay_path()
    except Exception:
        return ""
    return str(p) if p.is_file() else ""


@op("archive.add", summary="Додати архів, якого застосунок ще не знає",
    args=ArchiveAddArgs, mutates=True, agent=False, section="material")
def archive_add(a: ArchiveAddArgs) -> Envelope:
    """Дописати архів у накладку простору.

    🔴 Досі це вміла лише правка YAML руками, і застосунок про неї не казав
    ніде. Дослідник із польським чи білоруським архівом не заводив справу через
    інтерфейс узагалі — валідатор шифри вимагав назву зі списку, поповнити який
    з екрана було нічим.
    """
    from nyshporka.archives.pack import PackError, add_repository

    try:
        path = add_repository(a.code, a.label, a.name, a.country)
    except PackError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"не вдалося дописати архів ({type(exc).__name__}: {exc})")
    env = ok({"code": a.code.upper(), "label": a.label, "path": str(path)})
    env.warn("local_only",
             f"архів записано у ваш простір ({path}), а не у вбудований пак. "
             f"Він поїде разом із простором, але колезі, який працює у своєму, "
             f"буде невідомий — там його треба додати так само.")
    return env


# ── рушії читання ────────────────────────────────────────────────────────────
class EnvArgs(BaseModel):
    venv: str = Field(default="", description="тека середовища рушіїв; "
                                              "порожньо — узяти з простору")


# 🔴 `agent=False` — діагностика. У агента для неї є `nysh doctor`, який каже
# більше й одним викликом; тримати її ще й окремим tool'ом означає з'їдати
# місце в переліку, який модель мусить дочитати до кінця.
@op("htr.env", summary="Чи готове середовище рушіїв читання", args=EnvArgs,
    agent=False, section="htr")
def htr_env(a: EnvArgs) -> Envelope:
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import env as E
    from nyshporka.setup import doctor as doc

    if a.venv:
        venv = Path(a.venv)
    else:
        try:
            # 🔴 Шлях до рушіїв рахує `doctor.engine_venv()`, і лише вона.
            # Власна арифметика тут ігнорувала і `NYSHPORKA_HTR_VENV`, і наявну
            # `.venv_kraken` — тобто та сама машина відповідала по-різному
            # залежно від того, спитали `nysh doctor` чи цей tool, і розбіжність
            # виглядала як «в агента зламано середовище».
            venv = doc.engine_venv()
        except WorkspaceError as exc:
            return fail(str(exc))
    rep = E.inspect(venv)
    env = ok({"ok": rep.ok, "python": str(rep.python or ""), "kraken": rep.kraken,
              "torch": rep.torch, "cuda": rep.cuda, "capability": rep.capability,
              "missing": list(rep.missing)})
    for p in rep.problems:
        env.warn("engine_problem", p)
    if rep.missing:
        env.warn("engine_incomplete",
                 f"бракує: {', '.join(rep.missing)} — рушій із цими залежностями "
                 f"не запуститься")
    return env


# ── секції застосунку ────────────────────────────────────────────────────────
# 🔴 Обидві `agent=False`, і це рішення, а не недогляд. Перелік агентських
# tool'ів має стелю (див. `tests/test_reference_tabs`): далі модель перестає
# дочитувати описи й починає вгадувати. Переналаштування самого застосунку —
# не та річ, заради якої її рухати; для цього в агента є командний рядок.
class SectionsSetArgs(BaseModel):
    preset: str = Field("", description="пресет: amateur | researcher | lab")
    enable: list[str] = Field(default_factory=list, description="увімкнути секції")
    disable: list[str] = Field(default_factory=list, description="вимкнути секції")


def _sections_payload() -> dict[str, Any]:
    from nyshporka.core import sections as S
    from nyshporka.core.ops import REGISTRY
    from nyshporka.core.workspace import workspace

    active = workspace().sections
    in_use = REGISTRY.sections_in_use()
    rows = []
    for sec in S.all_sections():
        n = sum(1 for o in REGISTRY.all() if o.section == sec.id)
        rows.append({
            "id": sec.id, "label": sec.label(), "label_en": sec.label_en,
            "why": sec.why(), "why_en": sec.why_en,
            "required": sec.required, "active": sec.id in active,
            "ops": n,
            # Порожня секція не показується: вкладка без вмісту — обіцянка без входу.
            "visible": sec.id in in_use,
            "screens": list(S.screens_of(sec.id)),
        })
    # 🔴 Знаки їдуть звідси, а не з переліку у фронті. Кнопки навігації будує
    # браузер, і другий список іконок у ньому розходився б із `brand.yaml`
    # тихо: додався б екран — і кнопка виявилась би без знака поряд з
    # оформленими, тобто виглядала б зламаною.
    from nyshporka.brand import active as _brand

    b = _brand()
    return {"sections": rows, "preset": S.preset_of(active),
            "presets": {n: sorted(s) for n, s in S.PRESETS.items()},
            "screens": dict(S.SCREENS),
            # Куди вести з поради «→ далі: <операція>». Конверт називає
            # операцію, а людині треба екран — без цієї мапи браузер може лише
            # надрукувати ім'я, тобто сказати те, чого не натиснеш.
            "op_screen": dict(S.OP_SCREEN),
            "glyphs": {"screens": dict(b.screen_glyphs),
                       "sections": dict(b.section_glyphs)},
            # Значок спрайта поруч із емодзі, а не замість нього: емодзі
            # лишається для терміналу й README, де спрайта немає, а у вікні
            # малюється лінійний знак — він бере `currentColor` і тому не
            # лишається різнобарвною плямою на пофарбованій активній вкладці.
            "icons": {"screens": dict(b.screen_icons),
                      "sections": dict(b.section_icons)}}


@op("sections.show", summary="Які частини застосунку ввімкнено", agent=False)
def sections_show(_: NoArgs) -> Envelope:
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        ws = workspace()
    except WorkspaceError as exc:
        return fail(str(exc))
    env = ok(_sections_payload())
    problem = ws.profile[2]
    if problem:
        env.warn("sections_profile",
                 f"профіль секцій у {ws.marker.name} не прочитано "
                 f"({problem}) — діє набір за замовчуванням")
    return env


@op("sections.set", summary="Увімкнути або вимкнути частини застосунку",
    args=SectionsSetArgs, mutates=True, agent=False)
def sections_set(a: SectionsSetArgs) -> Envelope:
    from nyshporka.core import sections as S
    from nyshporka.core.workspace import WorkspaceError, set_sections, workspace

    try:
        current = workspace().sections
    except WorkspaceError as exc:
        return fail(str(exc))

    if a.preset:
        try:
            target = set(S.preset_sections(a.preset))
        except S.SectionError as exc:
            return fail(str(exc))
    else:
        target = set(current)
    bad = S.unknown([*a.enable, *a.disable])
    if bad:
        return fail(f"невідомі секції: {', '.join(bad)}. "
                    f"Є: {', '.join(sorted(S.ids()))}")
    target |= set(a.enable)
    # 🔴 Обов'язкову секцію не знімаємо навіть на пряме прохання: без неї
    # лишається шапка без жодного екрана, до якого можна дійти.
    refused = sorted(set(a.disable) & S.required_ids())
    target -= set(a.disable) - S.required_ids()

    try:
        active = set_sections(target)
    except (S.SectionError, WorkspaceError, OSError) as exc:
        return fail(f"не вдалось записати профіль: {exc}")

    env = ok(_sections_payload())
    for sid in refused:
        sec = S.get(sid)
        env.warn("section_required",
                 f"секцію «{sec.label() if sec else sid}» вимкнути не можна — "
                 f"без неї застосунок лишається без жодного екрана")
    # Порожню секцію вмикати не заборонено — але сказати про це треба, інакше
    # людина ввімкне «Лабораторію» й шукатиме, чому в шапці нічого не додалось.
    from nyshporka.core.ops import REGISTRY

    for sid in sorted((active - S.required_ids()) - REGISTRY.sections_in_use()):
        sec = S.get(sid)
        env.warn("section_empty",
                 f"секція «{sec.label() if sec else sid}» ще порожня — "
                 f"операцій у ній немає, тож в UI вона не з'явиться")
    return env
