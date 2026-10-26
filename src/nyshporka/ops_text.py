"""🗄 Операції текстового стору: стан, збірка, регекс по прочитаному.

Стор — один файл SQLite на все прочитане (`search/store.py`). Тут три дії:
скільки в ньому є, догнати його по прогонах і знайти рядок регексом так, як
досі робив `rg --no-ignore` — але без обходу дерева й без сліпоти `.gitignore`.

🔴 Усі три — `agent=False`: стартовий перелік агента (`nysh ops --agent`) тримається коротким. Агентові
вистачає командного рядка (`nysh text grep`, `nysh text state`, `nysh text
index`), а сам пошук прізвища йде через `search.run`, який стор бере сам,
щойно той покриває область.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import AGENT, ALERT, Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "research"



#: Область тексту: одна справа, шифра, серія, прогін — або перелік із них
#: (`htr_store.runs_for_scope`). Рядок лишається рядком: старі виклики не
#: змінюються.
CaseScope = str | list[str]


class TextStateArgs(BaseModel):
    verify: bool = Field(default=False,
                         description="звірити блоби кандидатів із чинним кодом — приймач "
                                     "однорідності стору після обірваної перебудови")
    sample: int = Field(default=3, ge=0,
                        description="скільки сторінок кожного прогону звіряти (перша, "
                                    "остання й між ними); 0 — усі")
    case: CaseScope = Field(default="",
                            description="звіряти лише прогони цієї справи (серії, "
                                        "переліку) або цей прогін; порожньо — усе")


@op("text.state", summary="Скільки прочитаного лежить у текстовому сторі",
    args=TextStateArgs, mutates=False, section=SECTION,
    skill="find-surname",
    when="скільки прочитаного в сторі пошуку і що ще не внесено")
def text_state(a: TextStateArgs) -> Envelope:
    """Знаменник стору — до запиту, а не після.

    🔴 «Не знайшлось» на сторі, що покриває 40 прогонів із 1300, — не та сама
    відповідь, що на повному. Число застарілих друкується першим.

    `verify` — не відбиток, а доказ: кандидати звірених сторінок
    перераховуються чинним кодом і порівнюються з блобами (`store.verify`).
    """
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    try:
        st = ST.stats()
    except Exception as exc:
        return fail(f"стан стору недоступний ({type(exc).__name__}: {exc})")
    if a.verify:
        if not st.get("exists"):
            return fail("стору ще немає — нема чого звіряти: nysh text index")
        runs = None
        if a.case:
            try:
                runs = [r["name"] for r in S.runs_for_scope(a.case)["rows"]]
            except ValueError as exc:
                return fail(str(exc))
        try:
            st["verify"] = ST.verify(runs, sample=a.sample)
        except Exception as exc:
            return fail(f"звірка блобів не вдалась ({type(exc).__name__}: {exc})")
    if (fast := _fast_state()) is not None:
        st["fast"] = fast
    env = ok(st)
    if fast and fast["behind"]:
        env.warn("fast_behind",
                 f"швидкий індекс охоплює {fast['covered']} прогонів із {fast['runs']}: "
                 f"решта шукається свіпом — повільніше, але без утрат; догнати — "
                 f"nysh text index")
    if a.verify:
        _warn_verify(env, st["verify"])
    if st["stale"]:
        env.suggest("text.index", "догнати стор по решті прогонів")
    if st.get("rules_stale"):
        env.warn("rules_stale", RULES_STALE_MSG)
    if st.get("rules_other"):
        # 🔴 Змішаний стор: частина прогонів зібрана іншим правилом склейки.
        # Так виглядає перебудова, яку вбили посеред, і доти вона була НЕВИДИМА
        # — спільний відбиток уже показував нове правило, бо його ставив перший
        # переіндексований прогін.
        env.warn("rules_mixed",
                 f"{st['rules_other']} прогонів зібрані ІНШИМ правилом склейки — "
                 f"стор змішаний, і пошук по них відповідає не тим, чим по решті")
        env.suggest("text.index", "доіндексувати саме їх")
    return env


def _names(runs: list[str], k: int = 8) -> str:
    more = f" і ще {len(runs) - k}" if len(runs) > k else ""
    return ", ".join(runs[:k]) + more


def _warn_verify(env: Envelope, v: dict[str, Any]) -> None:
    """Розбіжності звірки — з діагнозом і тим, що саме її лікує."""
    lying = [d["run"] for d in v["differ"] if d["rules_same"]]
    old = [d["run"] for d in v["differ"] if not d["rules_same"]]
    if lying:
        # 🔴 Найтихіший випадок: `text index` вважає такі прогони свіжими,
        # бо відбиток збігається, і сам їх не перебудує ніколи.
        env.warn("blobs_differ",
                 f"{len(lying)} прогонів тримають кандидатів, яких чинні правила НЕ дають, "
                 f"під чинним відбитком — відбиток бреше, і nysh text index їх не "
                 f"побачить; перебудувати поштучно: nysh text index --rebuild --case "
                 f"<прогін> ({_names(lying)})")
    if old:
        env.warn("blobs_old",
                 f"{len(old)} прогонів зібрані іншим правилом, і кандидати справді інші — "
                 f"nysh text index доганяє саме їх ({_names(old)})")
        env.suggest("text.index", "доіндексувати прогони зі старими кандидатами")
    fp = v["fingerprint_only"]
    if fp and not v["differ"]:
        env.warn("fingerprint_only",
                 f"{len(fp)} прогонів мають інший відбиток, а кандидати на звірених "
                 f"сторінках тотожні чинним — перебудова не потрібна: "
                 f"nysh text index --accept-rules")
    elif fp:
        # Відбиток приймається гуртом, на ВСІ прогони: поруч зі справді іншими
        # кандидатами це поставило б чинну заяву і на них.
        env.warn("fingerprint_only",
                 f"{len(fp)} прогонів мають інший відбиток при тотожних кандидатах, але "
                 f"поруч є прогони зі справді іншими — приймати відбиток гуртом не можна, "
                 f"спершу полагодити розбіжності")
    if v["missing"]:
        env.warn("verify_missing",
                 f"{len(v['missing'])} прогонів області немає в сторі — їх не звіряли "
                 f"({_names(v['missing'])})")


RULES_STALE_MSG = ("відбиток правил склейки кандидатів не збігається зі збіркою стору — "
                   "якщо правила змінились, перебудувати: nysh text index --rebuild; "
                   "якщо змінився лише спосіб рахувати відбиток — прийняти: "
                   "nysh text index --accept-rules")


class TextIndexArgs(BaseModel):
    case: CaseScope = Field(default="",
                            description="лише прогони цієї справи (серії, переліку) або "
                                        "цей прогін; порожньо — усе")
    rebuild: bool = Field(default=False,
                          description="перебудувати й свіже (після зміни правил розбору)")
    accept_rules: bool = Field(default=False,
                               description="прийняти чинний відбиток правил без перебудови "
                                           "(правила не мінялись)")
    fast: bool = Field(default=False,
                       description="зібрати або догнати ВЕСЬ швидкий індекс Tantivy "
                                   "(nyshporka[fast]) і злити його сегменти; зі справою "
                                   "(`--case`) індекс і так доганяється точково, без "
                                   "злиття великих сегментів")


@op("text.index", summary="Зібрати текстовий стор — один раз довго, далі швидко",
    args=TextIndexArgs, mutates=True, long=True, section=SECTION,
    tier="core", skill="read-case",
    when="після нового прогону — внести прочитане в стор пошуку")
def text_index(a: TextIndexArgs) -> Envelope:
    """Індексація читає дерево прогонів ОДИН раз. Далі кожен запит до тексту —
    запит до одного файлу.

    ⚠ Стор — похідне: його можна видалити, наступна збірка відтворить його з
    прогонів.
    """
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    if a.accept_rules:
        if not ST.exists():
            return fail("стору ще немає — нема чого приймати")
        h = ST.accept_rules()
        st = ST.stats()
        env = ok({"built": 0, "asked": 0, "accepted_rules": h, **st})
        return env
    if a.case:
        try:
            runs = [r["name"] for r in S.runs_for_scope(a.case)["rows"]]
        except ValueError as exc:
            return fail(str(exc))
    else:
        runs = [c["name"] for c in S.list_cases()]
    # 🔴 Для названої справи FTS не оптимізується ніколи: `optimize` зливає ВСІ
    # сегменти стору під замком на запис, і `--rebuild --case X` на сторі в 52 ГБ
    # висів понад дві хвилини (убито), тримаючи замок для наглядачів хмари
    # (25.10.2026). Те саме чекало б будь-яку справу від 50 прогонів.
    built = sum(1 for _ in ST.ensure_all(runs, force=a.rebuild, reset_rules=not a.case,
                                         optimize=False if a.case else None))
    st = ST.stats(runs if a.case else None)
    # Справа названа й `--fast` не просили — догнати швидкий індекс лише для неї
    # (`fastidx.sync`, параметр `only`): повний догін і злиття — без справи.
    fast = _fast_sync(a.fast, runs if a.case and not a.fast else None)
    if isinstance(fast, Envelope):
        return fast
    env = ok({"built": built, "asked": len(runs), **st, "fast": fast})
    if fast and fast.get("busy"):
        env.warn("fast_busy", "швидкий індекс зараз доганяє інша сесія — цього разу "
                              "не доганявся; неохоплені прогони пошук бере свіпом, а "
                              "наступний `text index --case …` (будь-якої справи) їх доганяє")
    if fast and fast.get("schema_old"):
        env.warn("fast_schema_old", "швидкий індекс іншої схеми: точково його не оновити — "
                                    "`nysh text index --fast` збере його наново (години); "
                                    "до того пошук іде свіпом")
    if fast and fast.get("merge_pending_docs"):
        env.warn("fast_merge_due",
                 f"у швидкому індексі чекає злиття сегментів ({fast['merge_pending_docs']:_} "
                 f"рядків) — точковий догін його не чекає; зливає `nysh text index --fast`, "
                 f"коли ніхто не шукає (хвилини-години, потрібне вільне місце на диску "
                 f"під копії сегментів)".replace("_", " "))
    if fast and fast.get("error"):
        env.warn("fast_failed", f"швидкий індекс не догнано ({fast['error']}); пошук "
                                f"неохоплені прогони бере свіпом")
    if st.get("rules_stale"):
        env.warn("rules_stale", RULES_STALE_MSG)
    if ST.LOCKED_SKIPPED:
        env.warn("locked_skipped",
                 f"{len(ST.LOCKED_SKIPPED)} прогонів НЕ проіндексовано: стор тримала "
                 f"інша сесія довше за {ST.INDEX_WAIT_SEC / 60:.0f} хв (індексація чи "
                 f"optimize) — до повтору `nysh text index` пошук їх не бачить",
                 level=ALERT)
    if st["stale"] and not a.case:
        env.warn("some_not_indexed",
                 f"{st['stale']} прогонів лишились поза стором — найчастіше це "
                 f"теки без жодного `.txt`")
    return env


def _fast_state() -> dict[str, Any] | None:
    """Скільки прогонів стору несе швидкий індекс; None — індексу немає.

    🔴 Відставання індексу пошук не бреше (неохоплене йде свіпом), але й не
    показує: 23.10.2026 перерваний догін лишив 4714 прогонів із 16 373 без
    документів, і корпусний пошук день мовчки ходив по них свіпом.
    """
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    if not FX.available() or not (FX.path() / FX.STATE).is_file():
        return None
    try:
        conn = ST.connect(readonly=True)
    except Exception:
        return None
    try:
        runs = [r for (r,) in conn.execute("select id from runs")]
        covered = len(FX.covered(conn, runs))
    finally:
        conn.close()
    return {"schema": FX.SCHEMA, "fresh": FX.exists(), "runs": len(runs),
            "covered": covered, "behind": covered < len(runs), **FX.segments_state()}


def _fast_sync(wanted: bool, runs: list[str] | None = None) -> dict[str, Any] | Envelope | None:
    """Догнати швидкий індекс: на прохання (`--fast`) або коли він уже є.

    🔴 Наявний індекс доганяється завжди, а не лише з прапорцем: індекс, що
    відстав від стору, пошук не бреше (неохоплені прогони йдуть свіпом), але
    повільнішає непомітно — людина вже не пам'ятає, що колись ставила `--fast`.
    """
    from nyshporka.search import fastidx as FX
    from nyshporka.search import store as ST

    if not wanted and not FX.exists():
        return None
    if not FX.available():
        from nyshporka.setup.update import how_to_update

        # Команда цієї установки, а не `pip install`: у середовище інструмента uv
        # (майстер, `uv tool install`) чужий pip пакета не донесе.
        return fail("швидкий індекс потребує пакета tantivy — поставити: "
                    + how_to_update(add=("fast",)))
    conn = ST.connect()
    try:
        only = None
        if runs is not None:
            marks = ",".join("?" * len(runs))
            only = {int(r) for (r,) in conn.execute(
                f"select id from runs where run in ({marks})", runs)} if runs else set()
        return FX.sync(conn, only=only, lock_wait=FX.LOCK_WAIT_SEC)
    except Exception as exc:  # стор зібрано; індекс лише прискорює
        # Збій індексу не губить зробленого стором: результат `text index` іде
        # далі, а про індекс — попередження (рецензія 20.10.2026).
        return {"error": f"{type(exc).__name__}: {exc}", "busy": False}
    finally:
        conn.close()


def _warn_cuts(env: Envelope, layered: dict[str, Any]) -> None:
    """Сказати про кожне звуження вибірки шарів.

    🔴 Мовчазне звуження читається як «не знайшлось». Стеля обходу описів і
    тека `--dir`, якої немає на диску, дають рівно нуль — і без цього рядка
    той нуль виглядає як відповідь про матеріал, а не про наш обхід.
    """
    for line in layered.get("cuts") or []:
        env.warn("layer_cut", f"вибірку звужено — {line}")


def _peek_elsewhere(env: Envelope, pattern: str, layers: list[str],
                    ignore_case: bool) -> None:
    """Чи є збіг у каноні чи нотатках ІНШИХ проєктів — лише лічильник.

    🔴 Вміст не показується. Агент у проєкті має знати, що «в роді Б теж є
    Сидоруки», і сказати про це людині, але Сидоруки іншого роду не мусять
    потрапити в його контекст: він сплутав би одну родину з іншою. Відкрити —
    `nysh --project Б …`, лише читання.
    """
    import re

    from nyshporka.core import projects as P
    from nyshporka.core.workspace import workspace

    want = tuple(x for x in layers if x in P.PEEK_LAYERS)
    if not want:
        return
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        found = P.peek(workspace(), rx, want)
    except Exception:
        return          # підсвітка — підказка, а не умова відповіді
    if not found:
        return
    if isinstance(env.data, dict):
        env.data["elsewhere"] = found
    label = {"canon": "у каноні", "notes": "у нотатках",
             "pages": "у коментарях до сторінок"}
    for f in found:
        env.warn("elsewhere",
                 f"ще в проєкті «{f['project']}» ({f['name']}): {f['count']} збігів "
                 f"{label.get(str(f['layer']), f['layer'])} — не завантажено. "
                 f"Відкрити лише на прохання людини: nysh --project {f['project']} …")


class TextGrepArgs(BaseModel):
    pattern: str = Field(description="регекс Python; кирилиця як у тексті")
    case: CaseScope = Field(default="",
                            description="лише в цій справі (серії, переліку) або прогоні; "
                                        "порожньо — усе прочитане")
    context: int = Field(default=1, ge=0, le=6, description="рядків сусідства")
    limit: int = Field(default=100, ge=1, le=2000)
    ignore_case: bool = Field(default=True)
    where: str = Field(default="decode",
                       description="decode | canon | opys | notes | pages | all — або кілька через кому")
    extra: str = Field(default="", description="ще теки/файли окремим шаром «dir», через «;»")
    fold: bool = Field(default=False,
                       description="регекс по НОРМАЛІЗОВАНОМУ рядку (ѳ=ф, ъ/ь відкинуто, і=и тощо — "
                                   "та сама норма, що в індексі); показується сирий рядок. "
                                   "Нечутливий до регістру; збіг нечіткіший, ніж по сирому. "
                                   "Лише для шару decode")


@op("text.grep", summary="Регекс по сирому тексту прочитаного — замість rg по теці прогонів",
    args=TextGrepArgs, mutates=False, section=SECTION,
    tier="core", scope="mixed", skill="find-surname",
    when="регекс по прочитаному; --where all — чи ми це вже знаємо")
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
    extra = [x.strip() for x in a.extra.split(";") if x.strip()]
    layered: dict[str, Any] | None = None
    if layers or extra:
        layered = T.grep_layers(a.pattern, layers, ignore_case=a.ignore_case,
                                limit=a.limit, context=a.context, extra=extra)
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
        _warn_cuts(env, layered)
        _peek_elsewhere(env, a.pattern, layers, a.ignore_case)
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
                  context=a.context, fold=a.fold)
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
                     "fold": a.fold,
                     "scope": scope["kind"], "case": scope["key"],
                     "shifra": scope["shifra"]}}
    if scope["kind"] == "all" or not res["hits"]:
        from nyshporka import htr_store as _S
        from nyshporka.search import reach as _R

        data["coverage"]["reach"] = _R.reach(len(_S.list_cases()))
    if layered is not None:
        data["layers"] = {"hits": layered["hits"], "total": layered["total"],
                          "coverage": layered["layers"]}
    env = ok(data)
    if layered is not None:
        _warn_cuts(env, layered)
        _peek_elsewhere(env, a.pattern, layers, a.ignore_case)
    if res["unindexed"]:
        env.warn("partial_store",
                 f"{res['unindexed']} прогонів поза стором: їхній текст ще не "
                 f"проіндексовано. Прочесано {res['runs']}.")
        env.suggest("text.index", "догнати стор")
    if not res["prefiltered"]:
        env.warn("full_scan", "у регексі немає літерала з трьох літер — прочесано "
                              "кожен рядок області, а не звужений корпус")
    if a.fold:
        env.warn("folded",
                 "--fold: збіг шукали в нормалізованому рядку (ѳ=ф, ѣ=е, і=и, ъ/ь відкинуто, "
                 "Kraken-плутанини зведено), регістр не розрізнявся; показано сирий рядок. "
                 "Збіг нечіткіший, ніж по сирому тексту: звіряти кропом.")
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
                     f"збігся — перевірте написання (ь/ъ/і/ѣ): `--fold` ганяє регекс по нормалізованому "
                     f"рядку, нечітке по словах — `nysh search`")
    return env


# ── етап 2: контекст, кроп, голоси, покриття, картка ─────────────────────────
class TextCtxArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")
    page: str = Field(description="скан: «73», «0073», «Image00073.jpg»")
    line: int | None = Field(default=None, description="рядок (з одиниці); порожньо — уся сторінка")
    window: int = Field(default=4, ge=0, le=60, description="рядків з кожного боку")
    full: bool = Field(default=False, description="уся сторінка незалежно від вікна")


@op("text.ctx", summary="Контекст рядка: сторінка, усі голоси, сусіди за геометрією, роки, око",
    args=TextCtxArgs, mutates=False, section=SECTION,
    tier="core", skill="find-surname",
    when="контекст рядка: голоси моделей і сусіди за колонкою")
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
    with_prev: bool = Field(default=False,
                            description="разом із попереднім рядком (хвіст після переносу)")
    wide: bool = Field(default=False, description="на всю ширину сторінки")
    pad: int = Field(default=12, ge=0, le=200)
    scale: float = Field(default=1.0, gt=0, le=4)
    out: str = Field(default="", description="куди зберегти PNG; порожньо — data/derived/crops")


# `private=True`: `out` пише файл туди, куди скаже клієнт, — без токена це робила
# б будь-яка сторінка, що дістанеться демона.
@op("text.crop", summary="Кроп рядка з кадру за рамкою рушія — з поворотом і масштабом",
    args=TextCropArgs, mutates=False, section=SECTION, private=True,
    tier="core", skill="find-surname",
    when="кроп рядка — показати людині чи звірити оком")
def text_crop(a: TextCropArgs) -> Envelope:
    from nyshporka.search import textops as T

    def cut() -> dict[str, Any]:
        return T.crop(a.case, a.page, a.line, with_next=a.with_next, with_prev=a.with_prev,
                      wide=a.wide, pad=a.pad, scale=a.scale, out=a.out or None)

    try:
        try:
            res = cut()
        except FileNotFoundError:
            # 🔴 Стору тексту ще немає — у свіжому просторі його ніхто не збирав,
            # а пошук працює й без нього. Доти тут стояла відмова з командою
            # терміналу, і людина з консоллю кропу не діставала ніколи (прохід
            # новачка 23.10.2026). Вноситься лише ця справа — не весь корпус.
            if not _index_case(a.case):
                raise
            res = cut()
    except ValueError as exc:
        return fail(str(exc))
    except FileNotFoundError:
        # Стору тексту ще немає: людина бачила сирий виняток зі шляхом до
        # sqlite у вікні гіпотези (прохід консолі 22.10.2026).
        return fail("прочитаного цієї справи в просторі немає — кропу нема з чого "
                    "різати. Після прогону: nysh text index --case <справа>")
    if res.get("error"):
        return fail(str(res["error"]))
    env = ok(res)
    if res.get("frame_source") == "registry":
        # 🔴 Кадр узято НЕ звідти, куди веде мета прогону: її шлях мертвий
        # (типово — тека орендованого бокса), і теку дібрав резолвер за шифрою.
        # Збіг імені файла при цьому ще не є збігом кадру — плоский стейджинг
        # перенумеровує сторінки. Кроп — приймач ока, і мовчазна підміна аркуша
        # тут коштує вердикту.
        env.warn("frame_by_registry",
                 f"кадр узято не з меты прогону, а з теки справи за реєстром "
                 f"({res.get('frame')}): звірити рядок «скан:» перед вердиктом")
        env.suggest("text.ctx", "звірити текст рядка з тим, що видно на кропі")
    return env


def _index_case(case: str) -> bool:
    """Внести в стор тексту прогони однієї справи. `False` — вносити нічого."""
    from nyshporka import htr_store as S
    from nyshporka.search import store as ST

    try:
        runs = [r["name"] for r in S.runs_for_scope(case)["rows"]]
    except ValueError:
        return False
    if not runs:
        return False
    for _ in ST.ensure_all(runs, optimize=False):
        pass
    return True


class TextVerdictArgs(BaseModel):
    case: str = Field(description="справа, шифра або прогін")
    run: str = Field(description="прогін, у якому знайдено рядок")
    page: str = Field(description="скан")
    line_no: int = Field(ge=1, description="номер рядка, з 1")
    verdict: Literal["other-surname", "noise", "unreadable"] = Field(
        description="інше прізвище · не прізвище · не читається")
    q: str = Field(default="", description="що шукали")
    note: str = Field(default="")
    source: str = Field(default="", description="`console` ставить кнопка Розбору")


# 🔴 Розбір кандидатів умів лише «Наш → у канон»: відкинути кандидата людина не
# могла, і сотня знахідок гортались без сліду (прохід новачка 23.10.2026).
# Вердикт про прізвище — лише з кнопки людини (`source: console`), як і з
# гортача (`source: sheet`): агент закриває хіба «не прізвище» й «не читається».
@op("text.verdict", summary="Вердикт людини на одного кандидата Розбору",
    args=TextVerdictArgs, mutates=True, section=SECTION, scope="project",
    skill="find-surname", when="відкинути кандидата: інше прізвище, не прізвище, не читається")
def text_verdict(a: TextVerdictArgs) -> Envelope:
    from nyshporka.search import textops as T

    res = T.verdicts_apply([{"run": a.run, "page": a.page, "line_no": a.line_no,
                             "verdict": a.verdict, "note": a.note, "source": a.source}],
                           a.case, q=a.q, agent="console" if a.source == "console" else "op")
    if res.get("error"):
        env = fail(str(res["error"]))
        for b in res.get("bad") or []:
            env.warn("bad_row", str(b))
        return env
    from nyshporka.core import vcs as V

    env = ok(res)
    V.autosave_env(env, f"Вердикт Розбору: {res.get('shifra') or a.case}")
    return env


class TextVoicesArgs(BaseModel):
    case: str = Field(description="справа, шифра або ім'я прогону")
    page: str = Field(description="скан")
    lines: str = Field(default="", description="діапазон рядків «10-30»; порожньо — усі")


@op("text.voices", summary="Два голоси рядок до рядка: де зійшлись, де ні",
    args=TextVoicesArgs, mutates=False, section=SECTION,
    skill="find-surname",
    when="два голоси моделей рядок до рядка: де розійшлись")
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
    args=TextCoverageArgs, mutates=False, section=SECTION,
    scope="mixed", skill="find-surname",
    when="що не дивились: кадри → прочитано → прошукано → оком")
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
    args=TextWhatisArgs, mutates=False, section=SECTION,
    tier="core", scope="mixed", skill="find-surname",
    when="картка справи: що прочитано, якими моделями, що шукали")
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
    case: CaseScope = Field(default="",
                            description="справа, шифра, серія («RGIA 592-25»), перелік "
                                        "справ або прогін; порожньо — усе прочитане")
    thresh: int = Field(default=78, ge=50, le=100)
    limit: int = Field(default=40, ge=1, le=5000)
    context: int = Field(default=1, ge=0, le=6)
    family: str = Field(default="",
                        description="чий рід: ім'я профілю з `config/research_profile.yaml`. "
                                    "Порожньо — рід, написанням якого є запит")
    with_terms: list[str] = Field(
        default_factory=list,
        description="слова-ознаки каналу запису (`--with`): ім'я («Юрко») чи прізвище "
                    "поруч із прізвищем запиту. Запис, де зійшлись прізвище й ці слова, "
                    "стає першим, а канал вмикається й без `kin` та канону. Потребує справи")


def _mark_in_canon(res: dict[str, Any]) -> None:
    """Позначити рядки видачі, вирізані кропом у канон якогось проєкту.

    🔴 Збіг — точний, за походженням кропу (справа, скан, рядок), а не за
    прізвищем: Іван Сидорук є в кожному селі, і збіг за іменем підсвічував би
    чужих людей як «уже в каноні». Кроп без походження (внесений до хвилі 7г
    чи без `--from`) не позначається — і підсумок `in_canon_known` каже, зі
    скількох кропів позначка взагалі могла взятись (знаменник).

    Агентові — лише позначка проєкту й ID картки, без вмісту картки: людина
    тримає в голові, що це інша родина, агент — ні (див. `projects.peek`).
    """
    from nyshporka.canon import evidence as E
    from nyshporka.core import projects as P
    from nyshporka.core import workspace as W

    try:
        ws = W.workspace()
        spots = E.origins(ws.citations / "MANIFEST_citations.json")
        names = {P.tag_of(p.id): p.name for p in P.list_projects(ws.hub)}
    except Exception:  # позначка — зручність показу, видача без неї правдива
        return
    res["in_canon_known"] = len(spots)
    if not spots:
        return
    base = str(res.get("case_key") or "")

    def mark(items: list[dict[str, Any]]) -> None:
        for h in items:
            try:
                spot = (str(h.get("case_key") or base), E.page_id(h.get("page")),
                        int(h.get("line_no") or 0))
            except (TypeError, ValueError):
                continue
            got = spots.get(spot)
            if got:
                h["in_canon"] = [{"project": P.tag_of(pid), "name": names.get(P.tag_of(pid), pid),
                                  "card": card} for pid, card in got]

    mark(res.get("hits") or [])
    mark((res.get("anchor") or {}).get("hits") or [])
    mark((res.get("record") or {}).get("hits") or [])


# `section="core"`: це й пошук консолі (`search.find`), а він в основі — див.
# `core.sections.SCREENS`.
@op("text.find", summary="Знайти рід усіма каналами разом — зі знаменником і журналом заходу",
    args=TextFindArgs, mutates=False, section="core",
    tier="core", scope="mixed", skill="find-surname",
    when="знайти рід чи прізвище в справі всіма каналами, зі знаменником")
def text_find(a: TextFindArgs) -> Envelope:
    """🔴 Нуль тут не друкується без журналу: скільки кадрів, скільки прочитано,
    скільки в сторі, якими голосами, які канали ганяли й що бачить око.

    Канали: прізвище всіма написаннями роду (ціле слово + корінь, склейки
    через рядок і колонку вже в кандидатах стору), якорі імен роду у вікні
    років справи, запис (ознаки родини з різних колонок одного запису),
    самоперевірка на аркушах, які око вже виписало. Латинський голос окремої
    команди не потребує: стор тримає всі прогони справи.

    Рід — будь-який профіль файла: названий `family` або той, написанням якого
    є запит.
    """
    from nyshporka.search import textops as T

    try:
        res = T.find(a.q, a.case, thresh=a.thresh, limit=a.limit, context=a.context,
                     family=a.family, with_terms=a.with_terms)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    _mark_in_canon(res)
    env = ok(res)
    if res.get("stopped"):
        env.warn("search_stopped",
                 "пошук спинено: прочесано не все, тож нуль чи неповний перелік "
                 "тут нічого не доводить — запустіть ще раз, щоб знати напевно",
                 level=ALERT)
    led = res["ledger"]
    for ch in led["channels"]:
        if not ch["ran"] and ch.get("why"):
            fix = f"; {ch['fix']}" if ch.get("fix") else ""
            # `AGENT`: людина бачить ту саму причину в журналі «Де й чим
            # шукали» — без команди терміналу, яку їй нема куди набрати.
            env.warn(f"channel_{ch['id']}_off",
                     f"канал «{ch['label']}» не ганяли: {ch['why']}{fix}", level=AGENT)
    ser = led.get("series") or {}
    if ser:
        # 🔴 Справи опису без жодного прогону в знаменник не входять — і мусять
        # бути названі числом, інакше нуль по серії читається як нуль по опису.
        head = f"{ser.get('label') or ser['repo']} {ser['fond']}-{ser['opys']}"
        if ser.get("listed") is None:
            env.warn("series_no_registry",
                     f"реєстру опису {head} на машині немає — скільки справ в описі, "
                     f"невідомо; шукано в прочитаних тут {ser['read']}")
        elif ser.get("unread"):
            miss = ser["unread"]
            env.warn("series_unread",
                     f"в описі {head} за реєстром справ {ser['listed']}, не прочитано тут "
                     f"{len(miss)} — у пошук і знаменник не входять: "
                     + ", ".join(miss[:10]) + (" …" if len(miss) > 10 else ""))
    if led.get("unindexed"):
        env.warn("partial_store", f"{led['unindexed']} прогонів поза стором")
        env.suggest("text.index", "догнати стор")
    if led.get("rules_stale"):
        env.warn("rules_stale", RULES_STALE_MSG)
    if led.get("short_stems"):
        env.warn("short_stems",
                 f"короткі стеми {', '.join(led['short_stems'])}: `partial_ratio` знаходить їх "
                 f"усередині будь-якого довшого слова — хіти за ними судити з осторогою")
    sc = res.get("selfcheck") or {}
    if sc.get("why"):
        env.warn("recall_not_measured", str(sc["why"]))
    elif sc and sc.get("missed"):
        env.warn("selfcheck_missed",
                 f"око бачило прізвище на аркушах, яких пошук не підняв: {sc['missed']}")
    rec = next((ch for ch in led["channels"] if ch["id"] == "record"), None)
    if rec and rec.get("ran") and rec.get("common"):
        env.warn("record_common",
                 f"ознаки, які запис звичайного розміру в цій справі зустрічає "
                 f"випадково частіше, ніж через раз, майже нічого не важать: "
                 f"{', '.join(rec['common'])}")
    cut = T.truncation_note(
        [("прізвище", len(res.get("hits") or []), int(res.get("total") or 0)),
         ("якорі", len((res.get("anchor") or {}).get("hits") or []),
          int((res.get("anchor") or {}).get("total") or 0)),
         ("запис", len((res.get("record") or {}).get("hits") or []),
          int((res.get("record") or {}).get("total") or 0))],
        a.limit, cap=5000)
    if cut:
        env.warn("shown_truncated", cut)
    if a.with_terms:
        if not rec or not rec.get("ran"):
            env.warn("with_not_applied",
                     "`--with` не спрацював: канал запису не ганяли"
                     + (f" ({rec['why']})" if rec and rec.get("why") else ""))
        elif rec.get("sources"):
            env.warn("record_signs",
                     "ознаки запису: " + "; ".join(
                         f"{x['source']}: {', '.join(x['terms'])}" for x in rec["sources"]))
    if not res.get("hits") and not (res.get("anchor") or {}).get("hits")             and not (res.get("record") or {}).get("hits"):
        env.warn("zero_with_denominator",
                 f"не знайшлось — кадрів {led.get('frames') or '?'}, прочитано "
                 f"{led.get('decoded') or '?'}, у сторі прогонів {led.get('in_store')} із "
                 f"{led.get('runs')}, голоси: {', '.join(led.get('voices') or []) or '—'}")
    return env


class TextNearArgs(BaseModel):
    q: str = Field(description="перше слово: прізвище, ім'я, село")
    other: str = Field(description="друге слово, яке має стояти поруч")
    case: CaseScope = Field(default="",
                            description="справа, шифра, серія, перелік справ або прогін; "
                                        "порожньо — усе прочитане")
    window: int = Field(default=1, ge=0, le=6,
                        description="на скільки рядків друге слово може відстояти від "
                                    "першого: 0 — той самий рядок, 1 — ще й сусідні "
                                    "(перенос), більше — сусідні рядки запису")
    thresh: int = Field(default=78, ge=50, le=100)
    limit: int = Field(default=40, ge=1, le=5000)
    follow: bool = Field(default=False,
                         description="друге слово одразу після першого в тому самому рядку, "
                                     "у набраному порядку: ім'я + по батькові, ім'я + прізвище")


@op("text.near", summary="Два слова поруч: ім'я + прізвище, прізвище + село, два прізвища",
    args=TextNearArgs, mutates=False, section=SECTION,
    tier="situational", scope="mixed", skill="find-surname",
    when="шукати пару: ім'я з прізвищем, прізвище з селом, ім'я з по батькові")
def text_near(a: TextNearArgs) -> Envelope:
    """Довше слово шукається по всій області (на корпусі — швидким індексом),
    коротше — лише на рядках біля нього. Обидва — тими самими написаннями, що
    й у пошуку прізвища (гніздо імен, форми роду).

    🔴 Нуль — зі знаменником: скільки місць першого слова знайдено й на скількох
    сторінках, бо «пари немає» при сотні місць першого слова і при нулі — різні
    відповіді.
    """
    from nyshporka.search import textops as T

    try:
        res = T.near(a.q, a.other, a.case, window=a.window, thresh=a.thresh, limit=a.limit,
                     follow=a.follow)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        env = fail(str(res["error"]))
        if "стору" in str(res["error"]):
            env.suggest("text.index", "зібрати стор по прочитаному")
        return env
    env = ok(res)
    if res["stopped"]:
        env.warn("search_stopped", "пошук спинено: прочесано не все, нуль нічого не доводить",
                 level=ALERT)
    if res["unindexed"]:
        env.warn("partial_store", f"{res['unindexed']} прогонів поза стором")
        env.suggest("text.index", "догнати стор")
    if res["rules_stale"]:
        env.warn("rules_stale", RULES_STALE_MSG)
    if res["fast_error"]:
        why = ("запит заширокий для швидкого індексу" if "TooBroad" in res["fast_error"]
               else "швидкий індекс недоступний")
        env.warn("fast_failed", f"{why} ({res['fast_error']}) — перше слово шукано свіпом")
    short = [s for s in res["stems_other"] if len(s) < 5]
    if short:
        env.warn("short_stems",
                 f"короткі стеми другого слова {', '.join(short)}: `partial_ratio` знаходить "
                 f"їх усередині довших слів — пари за ними судити з осторогою")
    if res["stopped"]:
        return env
    if not res["first_total"]:
        env.warn("zero_with_denominator",
                 f"«{res['q']}» не знайдено — «{res['other']}» поруч з ним не шукали; "
                 f"прочесано прогонів {res['runs']}, сторінок {res['pages']}")
    elif not res["hits"]:
        where = ("сусіднім словом у набраному порядку" if res["follow"]
                 else f"поруч (±{res['window']})")
        env.warn("zero_with_denominator",
                 f"пари не знайшлось — «{res['q']}» знайдено на {res['first_total']} рядках "
                 f"({res['first_pages']} стор.), «{res['other']}» {where} "
                 f"не стоїть на жодному; прочесано прогонів {res['runs']}, сторінок "
                 f"{res['pages']}")
    return env


# 🔴 Консоль шукає ТІЄЮ САМОЮ командою, що й агент (дослідник 07.10.2026:
# «чому агенти шукають готовою командою, а консоль чимось своїм?»). Доти
# консольний пошук ішов через `search.run` — той самий двигун, але без
# каналів роду, без журналу знаменника, без самоперевірки й з іншим порогом:
# людина на той самий запит діставала біднішу відповідь, ніж агент.
# Окрема операція лише тому, що довга: це `text.find` роботою в черзі.
@op("search.find", summary="Знайти в прочитаному — та сама команда, що `text.find`, роботою в черзі",
    args=TextFindArgs, mutates=False, long=True, section="core",
    tier="rare", scope="mixed", skill="find-surname")
def search_find(a: TextFindArgs) -> Envelope:
    return text_find(a)


#: Шифра на початку назви справи: «ДАХмО ф.315 оп.1 спр.8413:».
_TITLE_SHIFRA = re.compile(r"^\S+\s+ф\.\s*\S+\s+оп\.\s*\S+\s+спр\.\s*\S+?:\s*")


def _natural(parts: tuple[str, ...]) -> tuple[Any, ...]:
    """«ф.127» перед «ф.1040»: числа в шифрі порівнюються як числа."""
    out: list[Any] = []
    for p in parts:
        out += [(0, int(x)) if x.isdigit() else (1, x.casefold())
                for x in re.split(r"(\d+)", p) if x]
    return tuple(out)


class ScopesArgs(BaseModel):
    q: str = Field(default="", description="що набрано в полі «Де»")
    limit: int = Field(default=40, ge=1, le=200)


@op("search.scopes", summary="Де шукати: фонди, описи й справи, у яких є прочитане",
    args=ScopesArgs, mutates=False, section="core",
    tier="rare")
def search_scopes(a: ScopesArgs) -> Envelope:
    """Підказки поля «Де» — лише з того, у чому справді є прочитане.

    🔴 Межу пошуку людина руками не набере: «ДАВіО 904-24» чи шифру справи
    треба знати напам'ять, а помилка в ній дає відмову або чужу область.
    Тут — фонди, описи й справи бібліотеки з числом прочитаних справ, у
    порядку від ширшого до вужчого. Значення — те, що приймає межа
    `text.find` (`htr_store.runs_for_scope`).
    """
    from nyshporka.cases import db as CDB

    try:
        rows = CDB.query_rows(kind="case")
    except FileNotFoundError:
        return ok({"items": [], "registry": False})
    fonds: dict[tuple[str, str], int] = {}
    series: dict[tuple[str, str, str], int] = {}
    cases: list[dict[str, Any]] = []
    for r in rows:
        if str(r.get("htr_stage") or "none") == "none":
            continue
        lab = str(r.get("repo_label") or r.get("repo") or "").strip()
        fond = str(r.get("fond") or "").strip()
        opys = str(r.get("opys") or "").strip()
        if lab and fond:
            fonds[(lab, fond)] = fonds.get((lab, fond), 0) + 1
            if opys:
                series[(lab, fond, opys)] = series.get((lab, fond, opys), 0) + 1
        shifra = str(r.get("shifra") or "").strip()
        if shifra:
            # Назва часто починається з тієї самої шифри («ДАХмО ф.315 оп.1
            # спр.8413: Клірові…») — у підказці вона стоїть поруч і вдруге
            # лише відсуває назву за край.
            title = _TITLE_SHIFRA.sub("", " ".join(str(r.get("title") or "").split()))
            # Значення — ключ справи: шифру з літерою чи з власною розміткою
            # («ДАВіО ф.474 оп.1 спр.84») резолвер не розбирає, а ключ — завжди.
            y0, y1 = r.get("year_from"), r.get("year_to")
            years = (f"{y0}–{y1}" if y0 and y1 and y0 != y1 else str(y0 or y1 or ""))
            cases.append({"value": str(r.get("key") or "").strip() or shifra,
                          "kind": "case", "cases": 1,
                          "label": f"{shifra} — {title[:70]}" if title else shifra,
                          # Для переліку справ на «Пошуку»: шифра, назва, роки й
                          # скільки сторінок прочитано — окремими полями.
                          "shifra": shifra, "title": title, "years": years,
                          "pages": int(r.get("htr_pages_max") or 0),
                          "place": str(r.get("settlement") or r.get("place_raw") or "")})
    items: list[dict[str, Any]] = (
        [{"value": f"{lab} {f}", "kind": "fond", "cases": n,
          "label": f"{lab} ф.{f}", "head": f}
         for (lab, f), n in sorted(fonds.items(), key=lambda kv: _natural(kv[0]))]
        + [{"value": f"{lab} {f}-{o}", "kind": "opys", "cases": n,
            "label": f"{lab} ф.{f} оп.{o}", "head": f"{f}-{o}"}
           for (lab, f, o), n in sorted(series.items(), key=lambda kv: _natural(kv[0]))]
        + sorted(cases, key=lambda c: _natural((c["value"],))))
    want = " ".join(a.q.casefold().split())
    if want:
        items = [x for x in items
                 if want in x["label"].casefold() or want in x["value"].casefold()]
    items = [{k: v for k, v in x.items() if k != "head"} for x in _searchable(items)]
    return ok({"items": items[:a.limit], "total": len(items), "registry": True})


def _searchable(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Лише фонди й описи, які пошук справді прийме як межу.

    🔴 Серію пошук впізнає за числовим хвостом шифри, тож фонд із літерою
    («ДАВіО R-6129», «MNK 90») давав відмову «не розпізнав справу» вже після
    того, як людина обрала його з підказки. Підказка — те, на чому пошук не
    падає; тому кожну серію звіряємо тим самим `runs_for_scope`.
    """
    from nyshporka import vydannia
    from nyshporka.htr_store import series_form_ok

    # Перевіряється ФОРМА значення, а не прогони: серії взято з реєстру, тож
    # прочитане в них є. Прогін пошуком через `runs_for_scope` коштував 13 с
    # на 140 серіях — забагато для підказки під час набору.
    return [x for x in items
            if x["kind"] == "case" or series_form_ok(x["value"], x["head"])
            or vydannia.parse_series(x["value"])]


# ── етап 4: гортач і вердикти ────────────────────────────────────────────────
class TextSheetArgs(BaseModel):
    q: str = Field(description="прізвище або слово")
    case: str = Field(description="справа, шифра або прогін")
    thresh: int = Field(default=78, ge=50, le=100)
    limit: int = Field(default=60, ge=1, le=2000, description="кандидатів у гортачі")
    crops: int = Field(default=40, ge=0, le=500, description="скільком верхнім дати кроп")
    out: str = Field(default="", description="куди покласти HTML; порожньо — data/derived/sheets")
    serve_port: int = Field(default=8788, ge=1, le=65535,
                            description="порт `nysh serve` для посилань «сторінка цілком»")
    triage: bool = Field(default=True, description="відсіяти відоме й не-прізвища до кропу; "
                                                   "False — усі картки підряд, як до 0.37")


# `private=True`: як `text.crop` — `out` пише файл за шляхом від клієнта.
@op("text.sheet", summary="HTML-гортач кандидатів із кропами й полем вердикту для людини",
    args=TextSheetArgs, mutates=False, section=SECTION, private=True,
    tier="core", scope="project", skill="find-surname",
    when="гортач кандидатів із кропами для вердикту людини")
def text_sheet(a: TextSheetArgs) -> Envelope:
    from nyshporka.search import textops as T

    try:
        res = T.sheet(a.q, a.case, thresh=a.thresh, limit=a.limit, crops=a.crops,
                      out=a.out or None, serve_port=a.serve_port, triage=a.triage)
    except ValueError as exc:
        return fail(str(exc))
    if res.get("error"):
        return fail(str(res["error"]))
    env = ok(res)
    if res["cards"] and not res["crops"]:
        env.warn("no_crops", "жодного кропу: кадрів справи на цій машині немає або "
                             "прогін без геометрії — гортач лише текстом")
    if int(res.get("total") or 0) > int(res["cards"]):
        env.warn("cut", f"у гортачі {res['cards']} із {res['total']} кандидатів — решта "
                        f"поза ним; підняти --limit або звузити --case")
    by_reg = res.get("frames_by_registry") or []
    if by_reg:
        # 🔴 У гортачі вердикт виносить ОКО по картинці, тож підмінений аркуш
        # коштує тут дорожче, ніж будь-де: людина закриє кандидата, дивлячись
        # на чужу сторінку, і сліду не лишиться.
        env.warn("frame_by_registry",
                 f"кадри {len(by_reg)} прогонів узято не з меты, а з теки справи "
                 f"за реєстром ({', '.join(by_reg[:3])}): у цих картках звіряти "
                 f"рядок «скан:» перед вердиктом")
    env.suggest("text.verdicts", "занести вердикти з гортача у сховище сторінок")
    return env


class TextVerdictsArgs(BaseModel):
    path: str = Field(description="JSON із гортача")
    case: str = Field(description="справа, шифра або прогін")
    q: str = Field(default="", description="який запит судили — для примітки")


@op("text.verdicts", summary="Занести вердикти гортача у сховище сторінок",
    args=TextVerdictsArgs, mutates=True, section=SECTION,
    scope="project", skill="find-surname",
    when="занести вердикти людини з гортача в облік сторінок")
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
    from nyshporka.core import vcs as V

    V.autosave_env(env, f"Вердикти гортача: {a.case or a.path}")
    return env
