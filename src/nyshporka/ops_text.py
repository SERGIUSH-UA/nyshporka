"""🗄 Операції текстового стору: стан, збірка, регекс по прочитаному.

Стор — один файл SQLite на все прочитане (`search/store.py`). Тут три дії:
скільки в ньому є, догнати його по прогонах і знайти рядок регексом так, як
досі робив `rg --no-ignore` — але без обходу дерева й без сліпоти `.gitignore`.

🔴 Усі три — `agent=False`. Стеля переліку MCP-tool'ів насичена (18), і додати
tool означає прибрати інший; агентові вистачає командного рядка (`nysh text
grep`, `nysh text state`, `nysh text index`), а сам пошук прізвища йде через
`search.run`, який стор бере сам, щойно той покриває область.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

SECTION = "research"


@op("text.state", summary="Скільки прочитаного лежить у текстовому сторі",
    mutates=False, agent=False, section=SECTION)
def text_state(_: NoArgs) -> Envelope:
    """Знаменник стору — до запиту, а не після.

    🔴 «Не знайшлось» на сторі, що покриває 40 прогонів із 1300, — не та сама
    відповідь, що на повному. Число застарілих друкується першим.
    """
    from nyshporka.search import store as ST

    try:
        st = ST.stats()
    except Exception as exc:
        return fail(f"стан стору недоступний ({type(exc).__name__}: {exc})")
    env = ok(st)
    if st["stale"]:
        env.suggest("text.index", "догнати стор по решті прогонів")
    if st.get("rules_stale"):
        env.warn("rules_stale", "правила склейки кандидатів змінились після збірки — "
                                "перебудувати: nysh text index --rebuild")
    return env


class TextIndexArgs(BaseModel):
    case: str = Field(default="",
                      description="лише прогони цієї справи або цей прогін; порожньо — усе")
    rebuild: bool = Field(default=False,
                          description="перебудувати й свіже (після зміни правил розбору)")


@op("text.index", summary="Зібрати текстовий стор — один раз довго, далі швидко",
    args=TextIndexArgs, mutates=True, long=True, agent=False, section=SECTION)
def text_index(a: TextIndexArgs) -> Envelope:
    """Індексація читає дерево прогонів ОДИН раз. Далі кожен запит до тексту —
    запит до одного файлу.

    ⚠ Стор — похідне: його можна видалити, наступна збірка відтворить його з
    прогонів.
    """
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    if a.case:
        try:
            runs = [r["name"] for r in S.runs_for_scope(a.case)["rows"]]
        except ValueError as exc:
            return fail(str(exc))
    else:
        runs = [c["name"] for c in S.list_cases()]
    built = sum(1 for _ in ST.ensure_all(runs, force=a.rebuild))
    st = ST.stats()
    env = ok({"built": built, "asked": len(runs), **st})
    if st.get("rules_stale"):
        env.warn("rules_stale", "правила склейки кандидатів змінились після збірки — "
                                "кандидати в сторі старі; перебудувати: nysh text index --rebuild")
    if st["stale"] and not a.case:
        env.warn("some_not_indexed",
                 f"{st['stale']} прогонів лишились поза стором — найчастіше це "
                 f"теки без жодного `.txt`")
    return env


class TextGrepArgs(BaseModel):
    pattern: str = Field(description="регекс Python; кирилиця як у тексті")
    case: str = Field(default="",
                      description="лише в цій справі або прогоні; порожньо — усе прочитане")
    context: int = Field(default=1, ge=0, le=6, description="рядків сусідства")
    limit: int = Field(default=100, ge=1, le=2000)
    ignore_case: bool = Field(default=True)
    where: str = Field(default="decode",
                       description="decode | canon | opys | notes | all — або кілька через кому")
    extra: str = Field(default="", description="додаткові теки/файли для шару notes, через «;»")


@op("text.grep", summary="Регекс по сирому тексту прочитаного — замість rg по теці прогонів",
    args=TextGrepArgs, mutates=False, agent=False, section=SECTION)
def text_grep(a: TextGrepArgs) -> Envelope:
    """🔴 Нуль завжди зі знаменником: скільки прогонів і сторінок прочесано,
    скільки прогонів поза стором, і чи звужувався корпус літералами регексу.

    Регекс без літерала в три літери сканує кожен рядок області; це
    повідомляється, бо по корпусу такий запит триває секунди, а не мілісекунди.
    """
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST
    from nyshporka.search import textops as T

    wanted = [w.strip() for w in a.where.split(",") if w.strip()]
    if "all" in wanted:
        wanted = ["decode", *T.LAYERS]
    bad = [w for w in wanted if w not in ("decode", *T.LAYERS)]
    if bad:
        return fail(f"невідомий шар {bad}: є decode, {', '.join(T.LAYERS)}, all")
    layers = [w for w in wanted if w != "decode"]
    layered: dict[str, Any] | None = None
    if layers:
        layered = T.grep_layers(a.pattern, layers, ignore_case=a.ignore_case,
                                limit=a.limit, context=a.context,
                                extra=[x for x in a.extra.split(";") if x.strip()])
        if layered.get("error"):
            return fail(str(layered["error"]))
    if "decode" not in wanted:
        assert layered is not None
        env = ok({"hits": layered["hits"], "total": layered["total"],
                  "coverage": {"layers": layered["layers"], "scope": "layers"}})
        if not layered["hits"]:
            env.warn("zero_with_denominator",
                     "не знайшлось — файлів прочесано: " + ", ".join(
                         f"{k} {v['files']}" for k, v in layered["layers"].items()))
        return env
    if not ST.exists():
        env = fail("текстового стору ще немає")
        env.suggest("text.index", "зібрати стор по прочитаному")
        return env
    try:
        scope = S.runs_for_scope(a.case)
    except ValueError as exc:
        return fail(str(exc))
    runs = [r["name"] for r in scope["rows"]]
    res = ST.grep(a.pattern, runs, ignore_case=a.ignore_case, limit=a.limit,
                  context=a.context)
    if res.get("error"):
        return fail(str(res["error"]))
    by_run = {r["name"]: r for r in scope["rows"]}
    for h in res["hits"]:
        row = by_run.get(h["name"]) or {}
        h["case_key"] = (row.get("case_key") or "").strip()
        h["shifra"] = row.get("shifra") or ""
    data: dict[str, Any] = {
        "hits": res["hits"], "total": res["total"],
        "coverage": {"runs": res["runs"], "runs_asked": res["runs_asked"],
                     "unindexed": res["unindexed"], "pages": res["pages"],
                     "pages_scanned": res["pages_scanned"],
                     "prefiltered": res["prefiltered"], "literals": res["literals"],
                     "scope": scope["kind"], "case": scope["key"],
                     "shifra": scope["shifra"]}}
    if layered is not None:
        data["layers"] = {"hits": layered["hits"], "total": layered["total"],
                          "coverage": layered["layers"]}
    env = ok(data)
    if res["unindexed"]:
        env.warn("partial_store",
                 f"{res['unindexed']} прогонів поза стором: їхній текст ще не "
                 f"проіндексовано. Прочесано {res['runs']}.")
        env.suggest("text.index", "догнати стор")
    if not res["prefiltered"]:
        env.warn("full_scan", "у регексі немає літерала з трьох літер — прочесано "
                              "кожен рядок області, а не звужений корпус")
    if not res["hits"]:
        env.warn("zero_with_denominator",
                 f"не знайшлось — прочесано прогонів: {res['runs']}, "
                 f"сторінок: {res['pages_scanned']}")
        if res.get("literal_pages"):
            # 🔴 Літерал є в НОРМАЛІЗОВАНОМУ тексті, а регекс по сирому не
            # збігся: майже завжди орфографія («Стопковськ» проти «Стопковской»
            # без «ь»). Це нуль по написанню, а не по слову.
            env.warn("literal_in_norm",
                     f"літерал регексу є в нормалізованому тексті на "
                     f"{res['literal_pages']} стор., але сам регекс по сирому рядку не "
                     f"збігся — перевірте написання (ь/ъ/і/ѣ) або шукайте `nysh search`")
    return env


# ── етап 2: контекст, кроп, голоси, покриття, картка ─────────────────────────
class TextCtxArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")
    page: str = Field(description="скан: «73», «0073», «Image00073.jpg»")
    line: int | None = Field(default=None, description="рядок (з одиниці); порожньо — уся сторінка")
    window: int = Field(default=4, ge=0, le=60, description="рядків з кожного боку")
    full: bool = Field(default=False, description="уся сторінка незалежно від вікна")


@op("text.ctx", summary="Контекст рядка: сторінка, усі голоси, сусіди за геометрією, роки, око",
    args=TextCtxArgs, mutates=False, agent=False, section=SECTION)
def text_ctx(a: TextCtxArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.ctx(a.case, a.page, a.line, window=a.window, full=a.full)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    env = ok(res)
    if not res.get("aligned"):
        env.warn("voices_not_aligned", "голоси мають різне число рядків — другий голос "
                                       "показано за номером, а не за тим самим рядком")
    if len(res.get("voices") or []) < 2:
        env.warn("single_voice", "справу читано одним голосом — звірити читання нема з чим")
    return env


class TextCropArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")
    page: str = Field(description="скан")
    line: int = Field(ge=1, description="рядок (з одиниці)")
    with_next: bool = Field(default=True, description="разом із наступним рядком (перенос)")
    wide: bool = Field(default=False, description="на всю ширину сторінки")
    pad: int = Field(default=12, ge=0, le=200)
    scale: float = Field(default=1.0, gt=0, le=4)
    out: str = Field(default="", description="куди зберегти PNG; порожньо — data/derived/crops")


@op("text.crop", summary="Кроп рядка з кадру за рамкою рушія — з поворотом і масштабом",
    args=TextCropArgs, mutates=False, agent=False, section=SECTION)
def text_crop(a: TextCropArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.crop(a.case, a.page, a.line, with_next=a.with_next, wide=a.wide,
                     pad=a.pad, scale=a.scale, out=a.out or None)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    return ok(res)


class TextVoicesArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")
    page: str = Field(description="скан")
    lines: str = Field(default="", description="діапазон рядків «10-30»; порожньо — усі")


@op("text.voices", summary="Два голоси рядок до рядка: де зійшлись, де ні",
    args=TextVoicesArgs, mutates=False, agent=False, section=SECTION)
def text_voices(a: TextVoicesArgs) -> Envelope:
    from nyshporka.search import textops as T

    rng: tuple[int, int] | None = None
    if a.lines:
        try:
            lo, _sep, hi = a.lines.partition("-")
            rng = (int(lo), int(hi or lo))
        except ValueError:
            return fail(f"діапазон рядків не розбирається: «{a.lines}»")
    try:
        res = T.voices(a.case, a.page, lines=rng)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    return ok(res)


class TextCoverageArgs(BaseModel):
    case: str = Field(default="", description="справа, фонд («DAHMO/230») або порожньо — усе")
    unsearched: bool = Field(default=False, description="лише прочитані, але ще не шукані")
    limit: int = Field(default=300, ge=1, le=5000)


@op("text.coverage", summary="Кадри → прочитано → у сторі → чим шукали → скільки бачило око",
    args=TextCoverageArgs, mutates=False, agent=False, section=SECTION)
def text_coverage(a: TextCoverageArgs) -> Envelope:
    from nyshporka.search import textops as T

    res = T.coverage(a.case, unsearched=a.unsearched, limit=a.limit)
    env = ok(res)
    if res.get("why"):
        env.warn("no_registry", str(res["why"]))
        env.suggest("cases.build", "зібрати реєстр справ")
    if res.get("truncated"):
        env.warn("truncated", f"показано {a.limit}, ще {res['truncated']} справ за межею")
    return env


class TextWhatisArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")


@op("text.whatis", summary="Картка справи: реєстр, паспорт, прогони, слід пошуку, око, слова",
    args=TextWhatisArgs, mutates=False, agent=False, section=SECTION)
def text_whatis(a: TextWhatisArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.whatis(a.case)
    except ValueError as exc:
        return fail(str(exc))
    return ok(res)



# ── етап 3: find — усі канали разом, зі знаменником і журналом ───────────────
class TextFindArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    case: str = Field(default="", description="справа, шифра або прогін; порожньо — усе прочитане")
    thresh: int = Field(default=78, ge=50, le=100)
    limit: int = Field(default=40, ge=1, le=5000)
    context: int = Field(default=1, ge=0, le=6)


@op("text.find", summary="Знайти рід усіма каналами разом — зі знаменником і журналом заходу",
    args=TextFindArgs, mutates=False, agent=False, section=SECTION)
def text_find(a: TextFindArgs) -> Envelope:
    """🔴 Нуль тут не друкується без журналу: скільки кадрів, скільки прочитано,
    скільки в сторі, якими голосами, які канали ганяли й що бачить око.

    Канали: прізвище всіма написаннями профілю (ціле слово + корінь, склейки
    через рядок і колонку вже в кандидатах стору), якорі імен роду у вікні
    років справи, самоперевірка на аркушах, які око вже виписало. Латинський
    голос окремої команди не потребує: стор тримає всі прогони справи.
    """
    from nyshporka.search import textops as T

    try:
        res = T.find(a.q, a.case, thresh=a.thresh, limit=a.limit, context=a.context)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    env = ok(res)
    led = res["ledger"]
    for ch in led["channels"]:
        if not ch["ran"] and ch.get("why"):
            env.warn(f"channel_{ch['id']}_off", f"канал «{ch['label']}» не ганяли: {ch['why']}")
    if led.get("unindexed"):
        env.warn("partial_store", f"{led['unindexed']} прогонів поза стором")
        env.suggest("text.index", "догнати стор")
    sc = res.get("selfcheck") or {}
    if sc.get("why"):
        env.warn("recall_not_measured", str(sc["why"]))
    elif sc and sc.get("missed"):
        env.warn("selfcheck_missed",
                 f"око бачило прізвище на аркушах, яких пошук не підняв: {sc['missed']}")
    if not res.get("hits") and not (res.get("anchor") or {}).get("hits"):
        env.warn("zero_with_denominator",
                 f"не знайшлось — кадрів {led.get('frames') or '?'}, прочитано "
                 f"{led.get('decoded') or '?'}, у сторі прогонів {led.get('in_store')} із "
                 f"{led.get('runs')}, голоси: {', '.join(led.get('voices') or []) or '—'}")
    return env



# ── етап 4: гортач і вердикти ────────────────────────────────────────────────
class TextSheetArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    case: str = Field(description="справа, шифра або прогін")
    thresh: int = Field(default=78, ge=50, le=100)
    limit: int = Field(default=60, ge=1, le=2000, description="кандидатів у гортачі")
    crops: int = Field(default=40, ge=0, le=500, description="скільком верхнім дати кроп")
    out: str = Field(default="", description="куди покласти HTML; порожньо — data/derived/sheets")


@op("text.sheet", summary="HTML-гортач кандидатів із кропами й полем вердикту для людини",
    args=TextSheetArgs, mutates=False, agent=False, section=SECTION)
def text_sheet(a: TextSheetArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.sheet(a.q, a.case, thresh=a.thresh, limit=a.limit, crops=a.crops,
                      out=a.out or None)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    env = ok(res)
    if res["cards"] and not res["crops"]:
        env.warn("no_crops", "жодного кропу: кадрів справи на цій машині немає або "
                             "прогін без геометрії — гортач лише текстом")
    env.suggest("text.verdicts", "занести вердикти з гортача у сховище сторінок")
    return env


class TextVerdictsArgs(BaseModel):
    path: str = Field(description="JSON із гортача")
    case: str = Field(description="справа, шифра або прогін")
    q: str = Field(default="", description="який запит судили — для примітки")


@op("text.verdicts", summary="Занести вердикти гортача у сховище сторінок",
    args=TextVerdictsArgs, mutates=True, agent=False, section=SECTION)
def text_verdicts(a: TextVerdictsArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.verdicts_import(a.path, a.case, q=a.q)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        env = fail(str(res["error"]))
        for b in res.get("bad") or []:
            env.warn("bad_row", str(b))
        return env
    env = ok(res)
    for b in res.get("bad") or []:
        env.warn("bad_row", f"рядок пропущено: {b}")
    env.suggest("cases.build", "перебудувати реєстр: облік ока змінився")
    return env
