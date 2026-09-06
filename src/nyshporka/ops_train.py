"""🧪 Операції лабораторії — розмітка й навчання Писаря.

🔴 Усі — `section="lab"`, `agent=False`. Не «поки що»: перелік MCP-tool'ів має
стелю, за якою модель перестає читати описи, і лабораторні дії туди не йдуть
ніколи (`core/ops.py`). Агентові вистачає командного рядка: `nysh train …` і
`nysh op train.<ім'я> --describe`.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op

SECTION = "lab"


def _registry() -> Any:
    from nyshporka.train import sets as S

    return S.registry()


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


# ── реєстр наборів ───────────────────────────────────────────────────────────
class SetsArgs(BaseModel):
    name: str = Field(default="", description="один набір; порожньо — усі")
    all: bool = Field(default=False, description="показати й приховані набори")


@op("train.sets", summary="Набори для розмітки й трену: сторінки, кропи, мітки, злиття",
    args=SetsArgs, agent=False, section=SECTION)
def train_sets(a: SetsArgs) -> Envelope:
    """Що є на машині і в якому стані — зі знаменниками, а не самозвітом.

    🔴 Це приймач видимості для всього конвеєра. Число кропів береться З
    ДИСКА, число міток — із `lines.jsonl`, покриття злиття — з `_meta.json`
    теки `merge`. Набір, який тут не показує злиття, у корпус не потрапить,
    хоч би скільки рядків для нього звели.
    """
    from nyshporka.train import sets as S

    reg = _registry()
    broken: list[str] = []
    if a.name:
        try:
            rows = [reg.stats(a.name)]
        except S.SetError as exc:
            return fail(str(exc))
    else:
        rows = []
        for n in reg.names(hidden=a.all):
            try:
                rows.append(reg.stats(n))
            except S.SetError as exc:
                broken.append(f"{n}: {exc}")
    env = ok({"sets": rows, "root": str(reg.root), "n": len(rows)})
    for b in broken:
        env.warn("set_broken", b)
    lost = [r["name"] for r in rows if r["n_marked"] and not r["crops_present"]]
    if lost:
        # 🔴 Мітки без картинок — саме те, що сталося з 49 наборами в
        # дослідницькому конвеєрі. Мовчати про це означає дати збірнику корпусу
        # тихо пропустити набір, а людині — думати, що він у трені.
        env.warn("crops_missing",
                 f"мітки є, а кропів на диску немає: {', '.join(lost)} — "
                 f"перерізати з прогону (`nysh train cut`), інакше в корпус не ввійдуть")
    if not rows:
        env.suggest("train.cut", "наборів ще немає — нарізати перший із прогону")
    return env


# ── доктор лабораторії ───────────────────────────────────────────────────────
@op("train.doctor", summary="Що на цій машині є для розмітки й трену",
    args=NoArgs, agent=False, section=SECTION)
def train_doctor(_: NoArgs) -> Envelope:
    """Середовище рушіїв, карта, шляхи обчислень, набори — одним поглядом.

    Загальну готовність каже `nysh doctor`; тут — те, що потрібно саме
    трену: середовище рушіїв, карта, `gpurunner` на шляху, SSH-хости, і чи не
    розійшлися мітки з кропами.
    """
    from nyshporka.core.workspace import WorkspaceError
    from nyshporka.htr import gpu as G
    from nyshporka.setup import doctor as doc
    from nyshporka.train import sets as S

    d: dict[str, Any] = {}
    env = ok(d)
    try:
        venv = doc.engine_venv()
        d["engine_venv"] = str(venv)
        d["engine_present"] = venv.is_dir()
    except WorkspaceError as exc:
        return fail(str(exc))
    if not d["engine_present"]:
        env.warn("engine_missing",
                 "середовища рушіїв немає — трен локально неможливий: nysh htr install")
    try:
        card = G.detect_card()
    except Exception:
        card = None
    d["gpu"] = None if card is None else {
        "name": card.name, "capability": card.capability, "driver": card.driver}
    if card is None:
        env.warn("no_gpu", "відеокарти NVIDIA не видно — локальний трен піде на "
                           "процесорі й буде непрактично довгим; лишаються свій "
                           "сервер (--host) або gpurunner (--backend)")
    d["gpurunner"] = shutil.which("gpurunner")
    hosts: list[str] = []
    try:
        from nyshporka.cloud import ssh as C

        hosts = [h.name for h in C.load_hosts()]
    except Exception:
        hosts = []
    d["ssh_hosts"] = hosts
    reg = _registry()
    rows = []
    for n in reg.names(hidden=True):
        try:
            rows.append(reg.stats(n))
        except S.SetError as exc:
            env.warn("set_broken", f"{n}: {exc}")
    d["sets"] = {"n": len(rows),
                 "marked": sum(r["n_marked"] for r in rows),
                 "ok": sum(r["by_status"].get("ok", 0) for r in rows),
                 "crops": sum(r["n_crops"] for r in rows),
                 "holdout": [r["name"] for r in rows if r["role"] == "holdout"],
                 "without_crops": [r["name"] for r in rows
                                   if r["n_marked"] and not r["crops_present"]]}
    d["root"] = str(reg.root)
    if not rows:
        env.suggest("train.cut", "наборів немає — почати з нарізки прогону")
    elif not d["sets"]["holdout"]:
        env.warn("no_holdout",
                 "жоден набір не має ролі holdout — епоху не буде чим обирати, "
                 "а покращення val на тих самих справах не доказ")
    return env


# ── кропи з прогону ──────────────────────────────────────────────────────────
class CutArgs(BaseModel):
    run: str = Field(description="прогін, з якого різати (тека в reports/htr)")
    name: str = Field(description="ім'я набору — стане текою")
    pages: str = Field(default="", description="кома-список сторінок; порожньо — авто")
    pick: int = Field(default=0, description="скільки сторінок відібрати автоматично")
    title: str = Field(default="", description="людська назва набору")
    domain: str = Field(default="", description="жанр для арбітрів: «сповідний розпис», «метрика»")
    case: str = Field(default="", description="шифра справи, якщо прогін її не знає")
    no_engine: bool = Field(default=False,
                            description="різати полігоном пакетом, не кешем сегментації")


@op("train.cut", summary="Нарізати кропи рядків із прогону в набір для розмітки",
    args=CutArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_cut(a: CutArgs) -> Envelope:
    """Набір із прогону: кропи = рядки прогону, текст прогону = перший голос.

    🔴 Без окремої сегментації навмисно: геометрію рядків прогін уже записав,
    і кроп, вирізаний з неї, — це рівно той рядок, який дав текст. Нова
    сегментація дала б інші індекси, і голос прогону перестав би відповідати
    кропам.
    """
    from nyshporka.train import cut as C
    from nyshporka.train import sets as S

    try:
        rep = C.make_set(a.run, a.name, pages=_csv(a.pages) or None, pick=a.pick,
                         title=a.title, domain=a.domain, case=a.case,
                         prefer_engine=not a.no_engine)
    except C.CutError as exc:
        return fail(str(exc))
    st = S.registry().stats(a.name)
    env = ok({"set": a.name, "lines": rep.n_lines,
              "pages": [{"page": p.page, "n": p.n, "source": p.source,
                         "error": p.error} for p in rep.pages],
              "stats": st})
    for w in rep.warnings:
        env.warn("cut", w)
    if rep.n_lines:
        env.suggest("train.voices", "додати другий голос: без нього черга й злиття сліпі")
    return env


# ── голоси ───────────────────────────────────────────────────────────────────
class VoicesArgs(BaseModel):
    name: str = Field(description="набір")
    from_run: str = Field(default="", description="сусідній прогін тієї самої справи")
    models: str = Field(default="", description="кома-список ваг Писаря (.pt) для інферу")
    device: str = Field(default="cuda:0", description="пристрій для інферу")


@op("train.voices", summary="Додати голос рушія до набору: з сусіднього прогону або інфером",
    args=VoicesArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_voices(a: VoicesArgs) -> Envelope:
    """Другий голос — умова і для черги розмітки, і для злиття арбітрами.

    🔴 Голос із прогону береться лише після звірки: число рядків на кожній
    сторінці мусить збігтися з числом рамок набору. Інакше рядок N чужого
    прогону ліг би під кроп M — і цю помилку не видно, бо текст правдоподібний.
    """
    from nyshporka.train import sets as S
    from nyshporka.train import voices as V

    if not a.from_run and not a.models:
        return fail("вкажіть --from-run або --models")
    got: list[dict[str, Any]] = []
    try:
        if a.from_run:
            r = V.add_from_run(a.name, a.from_run)
            got.append({"voice": r.voice, "pages": r.pages, "lines": r.lines, "how": "run"})
        for m in _csv(a.models):
            r = V.run_model(a.name, m, device=a.device)
            got.append({"voice": r.voice, "pages": r.pages, "lines": r.lines, "how": "infer"})
    except (S.SetError, V.VoiceError) as exc:
        return fail(str(exc))
    st = S.registry().stats(a.name)
    env = ok({"set": a.name, "added": got, "voices": st["voices"]})
    if len(st["voices"]) >= 2:
        env.suggest("train.export", "голосів досить — можна експортувати завдання арбітрам")
    return env


# ── словник справи ───────────────────────────────────────────────────────────
class GlossaryArgs(BaseModel):
    name: str = Field(description="набір")
    add: str = Field(default="", description="кома-список власних назв, звірених оком")
    why: str = Field(default="", description="звідки взято (титул справи, реєстр…)")
    remove: str = Field(default="", description="кома-список назв, які прибрати")


@op("train.glossary", summary="Словник справи: власні назви для арбітрів, звірені оком",
    args=GlossaryArgs, mutates=True, agent=False, section=SECTION)
def train_glossary(a: GlossaryArgs) -> Envelope:
    """Причт, село, установа — те, що рушій калічить у кожному рядку по-новому.

    🔴 Словник — обмеження, не підказка «підставляй частіше»: у завдання він
    іде з формулюванням «не перебиває голоси». І гейт тут людський: назви
    беруться з ТЕКСТУ (титул, реєстр, облік сторінок), і людина їх бачить
    перед тим, як арбітри почнуть на них спиратись.
    """
    from nyshporka.train import sets as S

    reg = _registry()
    try:
        spec = reg.load(a.name)
    except S.SetError as exc:
        return fail(str(exc))
    added, removed = _csv(a.add), _csv(a.remove)
    if added or removed:
        for term in added:
            spec.glossary[term] = a.why
        for term in removed:
            spec.glossary.pop(term, None)
        reg.save(spec)
    env = ok({"set": a.name, "glossary": spec.glossary, "added": added, "removed": removed})
    if not spec.glossary:
        env.warn("glossary_empty", "словник порожній — арбітри зводитимуть власні назви "
                                   "наосліп; це нормально лише для справи без причту й "
                                   "сталих імен")
    return env


# ── завдання арбітрам ────────────────────────────────────────────────────────
class ExportArgs(BaseModel):
    name: str = Field(description="набір")
    pages: str = Field(default="", description="кома-список сторінок; порожньо — усі")
    pages_per_file: int = Field(default=3, description="сторінок на файл-завдання")
    only_missing: bool = Field(default=False, description="лише рядки без злиття")
    drafts: str = Field(default="", description="кома-список голосів; порожньо — усі")
    out: str = Field(default="", description="куди класти; порожньо — _tasks у наборі")
    no_sheets: bool = Field(default=False, description="без аркушів із рамками")


@op("train.export", summary="Завдання арбітрам: голоси по сторінках + аркуші з рамками",
    args=ExportArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_export(a: ExportArgs) -> Envelope:
    """Файли-завдання для агентів-арбітрів — по межах сторінок, з аркушами.

    🔴 Зводить не чужий API, а сесія користувача: платить той, чий агент читає.
    Порожні смужки відсіює скрипт за часткою чорнила, не око арбітра.
    """
    from nyshporka.train import sets as S
    from nyshporka.train import tasks as T

    try:
        rep = T.export_tasks(a.name, pages=_csv(a.pages), pages_per_file=a.pages_per_file,
                             only_missing=a.only_missing, drafts=_csv(a.drafts) or None,
                             out=Path(a.out) if a.out else None, sheets=not a.no_sheets)
    except (S.SetError, T.TaskError) as exc:
        return fail(str(exc))
    env = ok({"set": a.name, "out": str(rep.out), "files": [str(f) for f in rep.files],
              "rows": rep.rows, "pages": rep.pages, "dropped_blank": rep.dropped_blank,
              "sheets": rep.sheets})
    for w in rep.warnings:
        env.warn("export", w)
    if rep.dropped_blank:
        env.warn("blank_dropped", f"порожніх смужок відсіяно: {len(rep.dropped_blank)}")
    if rep.files:
        env.suggest("train.import", "коли арбітри напишуть *.answer.json — забрати їх")
    return env


class ImportArgs(BaseModel):
    name: str = Field(description="набір")
    tasks: str = Field(default="", description="тека з відповідями; порожньо — _tasks у наборі")
    keep_old: bool = Field(default=False, description="попереднє злиття лишити як merge_old")


@op("train.import", summary="Забрати відповіді арбітрів у злиття і прогнати ворота",
    args=ImportArgs, mutates=True, agent=False, section=SECTION)
def train_import(a: ImportArgs) -> Envelope:
    """Відповіді → `drafts/merge/`, і одразу ворота: маркери, белькіт, зсув.

    Часткові файли законні: арбітр пише порціями, а другий захід доливає.
    Понижене до `low` лишається видимим — у корпус воно не йде.
    """
    from nyshporka.train import sets as S
    from nyshporka.train import tasks as T

    try:
        rep = T.import_answers(a.name, tasks_dir=Path(a.tasks) if a.tasks else None,
                               keep_old=a.keep_old)
    except (S.SetError, T.TaskError) as exc:
        return fail(str(exc))
    st = _registry().stats(a.name)
    env = ok({"set": a.name, "files": rep.files, "rows": rep.rows, "pages": rep.pages,
              "conf": rep.conf, "rejected": rep.rejected,
              "gates": [g.as_dict() for g in rep.gates], "splits": rep.splits,
              "stats": st})
    for w in rep.warnings:
        env.warn("gate", w)
    n_susp = sum(len(g.suspects) for g in rep.gates)
    if n_susp:
        env.warn("suspects", f"{n_susp} рядків на очі людині (розбіжність або домисел): "
                             f"nysh train gates --set {a.name} --suspects")
    if st["merge"]:
        env.suggest("train.sets", f"злиття набору: {st['n_merged']} рядків "
                                  f"(h{st['merge']['high']}/m{st['merge']['med']}/"
                                  f"l{st['merge']['low']})")
    return env


class GatesArgs(BaseModel):
    name: str = Field(description="набір")
    suspects: bool = Field(default=False, description="показати рядки на очі людині")
    gt: bool = Field(default=False, description="звірити якір ручних міток із голосами")


@op("train.gates", summary="Ворота злиття окремо: підозрілі рядки, якір ручних міток",
    args=GatesArgs, agent=False, section=SECTION)
def train_gates(a: GatesArgs) -> Envelope:
    """Те, що ворота не понижують самі, а лише показують.

    Розбіжність голосів і неопертість злиття — сигнали «тут важко», а не
    «тут не текст»; вирок виносить людина, дивлячись на кроп.
    """
    from nyshporka.train import gate as G
    from nyshporka.train import sets as S
    from nyshporka.train import tasks as T

    reg = _registry()
    try:
        spec = reg.load(a.name)
    except S.SetError as exc:
        return fail(str(exc))
    d: dict[str, Any] = {"set": a.name}
    if a.suspects or not a.gt:
        d["suspects"] = T.suspects_of(a.name)
    if a.gt:
        voices = spec.voices()

        def _vl(pg: str) -> list[list[str]]:
            return [reg.draft_lines(spec, v, pg) or [] for v in voices]

        d["gt_shifted"] = G.audit_marks(reg.marks(a.name), _vl)
    env = ok(d)
    if d.get("gt_shifted"):
        env.warn("gt_shift", f"{len(d['gt_shifted'])} ручних міток мають якір на іншому "
                             f"індексі — перевірити, чи не з'їхала нумерація кропів")
    if not spec.merge() and not a.gt:
        env.warn("no_merge", "злиття ще немає — нема що перевіряти")
    return env


class SheetsArgs(BaseModel):
    name: str = Field(description="набір")
    pages: str = Field(default="", description="кома-список сторінок; порожньо — усі")
    out: str = Field(default="", description="куди; порожньо — _sheets у наборі")


@op("train.sheets", summary="Аркуші сторінок із пронумерованими рамками рядків",
    args=SheetsArgs, mutates=True, long=True, agent=False, section=SECTION)
def train_sheets(a: SheetsArgs) -> Envelope:
    """Аркуш для арбітра окремо від експорту — для дозаходу чи очного проходу."""
    from nyshporka.train import sets as S
    from nyshporka.train import sheets as SH
    from nyshporka.train import tasks as T

    reg = _registry()
    try:
        spec = reg.load(a.name)
    except S.SetError as exc:
        return fail(str(exc))
    pages = _csv(a.pages) or sorted(reg.crop_pages(spec))
    if not pages:
        return fail(f"у наборі «{a.name}» немає кропів — спершу `nysh train cut`")
    out = Path(a.out) if a.out else reg.set_dir(a.name) / T.SHEETS_DIR
    rep = SH.make_sheets(a.name, pages, out)
    env = ok({"set": a.name, "out": str(out),
              "pages": {pg: [f.name for f in files] for pg, files in rep.pages.items()},
              "notes": rep.notes})
    for w in rep.warnings:
        env.warn("sheet", w)
    return env


class ViewArgs(BaseModel):
    name: str = Field(description="набір")
    page: str = Field(description="сторінка")
    mode: str = Field(default="strip", description="strip | zoom | ctx")
    lines: str = Field(default="", description="strip: «6-10,15»")
    line: int = Field(default=0, description="zoom/ctx: індекс рядка")
    frm: float = Field(default=0.0, description="zoom: початок фрагмента, частка ширини")
    to: float = Field(default=1.0, description="zoom: кінець фрагмента, частка ширини")
    k: float = Field(default=1.0, description="кратність збільшення (zoom типово 4)")
    pad: int = Field(default=200, description="ctx: поле навколо рамки, px")
    out: str = Field(default="", description="записати PNG сюди (порожньо — лише data URL)")


@op("train.view", summary="Показати кропи набору: смужка, зум, контекст на сторінці",
    args=ViewArgs, agent=False, section=SECTION)
def train_view(a: ViewArgs) -> Envelope:
    """Картинка для ока — арбітра чи людини. У конверті — data URL і примітка."""
    from nyshporka.train import sets as S
    from nyshporka.train import view as V

    try:
        if a.mode == "strip":
            lines = V.parse_lines(a.lines) if a.lines else [a.line]
            shot = V.strip(a.name, a.page, lines)
        elif a.mode == "zoom":
            shot = V.zoom(a.name, a.page, a.line, frm=a.frm, to=a.to,
                          k=a.k if a.k != 1.0 else 4.0)
        elif a.mode == "ctx":
            shot = V.ctx(a.name, a.page, a.line, pad=a.pad, k=a.k)
        else:
            return fail(f"режим «{a.mode}» невідомий: strip | zoom | ctx")
    except (S.SetError, V.ViewError, ValueError) as exc:
        return fail(str(exc))
    written = ""
    if a.out:
        Path(a.out).write_bytes(shot.png)
        written = str(Path(a.out))
    return ok({"set": a.name, "page": a.page, "mode": a.mode, "width": shot.width,
               "height": shot.height, "note": shot.note, "file": written,
               "image": shot.data_url})


# ── вкладка «Розмітка» ───────────────────────────────────────────────────────
def _store(name: str) -> Any:
    from nyshporka.train import store as ST

    return ST.Store(name)


class QueueArgs(BaseModel):
    name: str = Field(description="набір")
    mode: str = Field(default="spread", description="spread | useful | page | sequential | names")
    page: str = Field(default="", description="сторінка для режиму page")
    limit: int = Field(default=400, description="стеля рядків у черзі")
    include_blank: bool = Field(default=False, description="показувати порожні смужки")


@op("train.queue", summary="Черга рядків на розмітку — за розбіжністю голосів",
    args=QueueArgs, agent=False, section=SECTION)
def train_queue(a: QueueArgs) -> Envelope:
    """Що показати людині першим: рядки, де голоси розійшлись, блоками з різних сторінок.

    🔴 `spread` — дефолт: модель, навчена на одному писарі, вміє читати одного
    писаря, а «найкорисніші» й «підряд» віддають сторінку цілком.
    """
    from nyshporka.train import sets as S

    try:
        st = _store(a.name)
        got = st.queue(a.mode, a.page, max(1, min(2000, a.limit)), a.include_blank)
    except S.SetError as exc:
        return fail(str(exc))
    env = ok(got)
    if len(st.spec.drafts) < 2:
        env.warn("one_voice", "у наборі лише один голос — черга не бачить розбіжності "
                              "й іде підряд; додайте другий: nysh train voices")
    if not got["items"]:
        env.warn("queue_empty", "у цьому режимі рядків не лишилось — усі розмічені "
                                "або порожні (увімкніть «показувати порожні»)")
    return env


class LineArgs(BaseModel):
    name: str = Field(description="набір")
    page: str = Field(description="сторінка")
    idx: int = Field(description="індекс кропа")
    span: int = Field(default=2, description="сусідніх рядків з кожного боку")


@op("train.line", summary="Один рядок для розмітки: кроп, голоси, сусіди, збережене",
    args=LineArgs, agent=False, section=SECTION)
def train_line(a: LineArgs) -> Envelope:
    """Кроп як data URL плюс усе, що людині треба бачити поруч із ним."""
    from nyshporka.train import sets as S

    try:
        return ok(_store(a.name).line(a.page, a.idx, max(1, min(5, a.span))))
    except S.SetError as exc:
        return fail(str(exc))


class PageArgs(BaseModel):
    name: str = Field(description="набір")
    page: str = Field(description="сторінка")
    max_px: int = Field(default=1800, description="довга сторона зображення")


@op("train.page", summary="Сторінка набору з рамками рядків — звідки ця смужка",
    args=PageArgs, agent=False, section=SECTION)
def train_page(a: PageArgs) -> Envelope:
    """Зменшений скан із рамками з мети нарізки; на зумі — 3600 px."""
    from nyshporka.train import sets as S

    try:
        return ok(_store(a.name).page_image(a.page, a.max_px))
    except S.SetError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"сторінку «{a.page}» показати нічим: {exc}")


class SaveArgs(BaseModel):
    name: str = Field(description="набір")
    page: str = Field(description="сторінка")
    idx: int = Field(description="індекс кропа")
    text: str = Field(default="", description="текст рядка як на аркуші")
    status: str = Field(default="ok", description="ok | skip | unsure")
    kind: str = Field(default="hand", description="hand | print | mixed")
    draft: str = Field(default="", description="чернетка, яку людина бачила")
    secs: float = Field(default=0.0, description="скільки секунд пішло")


@op("train.save", summary="Записати ручну мітку рядка",
    args=SaveArgs, mutates=True, agent=False, section=SECTION)
def train_save(a: SaveArgs) -> Envelope:
    """Append-only: історія правок зберігається, останній запис виграє.

    Маркери розбіжності знімаються на вході — `lines.jsonl` є джерелом
    правди, і маркер, прийнятий одним Enter, лишився б у ньому назавжди.
    """
    from nyshporka.train import sets as S

    try:
        rec = _store(a.name).save(a.page, a.idx, a.text, a.status, kind=a.kind,
                                  draft=a.draft, secs=a.secs)
    except S.SetError as exc:
        return fail(str(exc))
    return ok({"rec": rec})


class StatsArgs(BaseModel):
    name: str = Field(description="набір")


@op("train.stats", summary="Поступ розмітки набору: зроблено, темп, CER голосу проти людини",
    args=StatsArgs, agent=False, section=SECTION)
def train_stats(a: StatsArgs) -> Envelope:
    """Знаменники розмітки, і один вимірювач: наскільки голос (чи злиття) помиляється.

    `cer_draft` понад ~0.10 означає, що арбітри працювали погано і корпус із
    такого злиття гірший за відсутній.
    """
    from nyshporka.train import sets as S

    try:
        d = _store(a.name).stats()
    except S.SetError as exc:
        return fail(str(exc))
    env = ok(d)
    if d["cer_draft"] is not None and d["cer_lines"] < 20:
        env.warn("cer_small", f"CER голосу міряно лише на {d['cer_lines']} рядках — "
                              f"на такому числі він ще нічого не доводить")
    return env


class SuggestArgs(BaseModel):
    name: str = Field(description="набір")
    q: str = Field(description="початок фрази")
    limit: int = Field(default=6, description="скільки підказок")


@op("train.suggest", summary="Автодоповнення з уже введених міток",
    args=SuggestArgs, agent=False, section=SECTION)
def train_suggest(a: SuggestArgs) -> Envelope:
    """У метриці рядки повторюються: формула набирається один раз."""
    from nyshporka.train import sets as S

    try:
        return ok({"items": _store(a.name).suggest(a.q, max(1, min(20, a.limit)))})
    except S.SetError as exc:
        return fail(str(exc))
