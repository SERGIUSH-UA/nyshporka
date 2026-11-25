"""📑 Операції описів фондів: перевірити робочу теку, спакувати `.nyshopys`.

🔴 Цей модуль реєструє операції лише тоді, коли його імпортують, а імпортує
його `nyshporka.ops` тільки з увімкненим флагом `NYSH_OPYSY`
(`nyshporka.features`). Без флагу операцій описів немає ні в `nysh ops`, ні
в MCP, ні в браузері.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nyshporka.core.envelope import ALERT, Envelope, fail, ok
from nyshporka.core.ops import op

SECTION = "htr"


class CheckArgs(BaseModel):
    dir: str = Field(description="робоча тека опису: manifest.json, pages.jsonl, rows.jsonl")


class PackArgs(BaseModel):
    dir: str = Field(description="робоча тека опису: manifest.json, pages.jsonl, rows.jsonl")
    out: str = Field(description="куди покласти .nyshopys (файл або тека)")


class PushArgs(BaseModel):
    file: str = Field(description="робоча тека опису (`nysh opys read`) або готовий пакет "
                                  ".nyshopys")
    norm_model: str = Field(default="", description="модель, що нормалізувала назви (для теки; "
                                                    "один раз — далі пам'ятається)")
    znovu: bool = Field(default=False, description="залити, навіть якщо цей самий пакет із теки вже "
                                                   "залито")
    na_obmin: bool = Field(default=False, description="віддати нормалізацію назв на обмін: опис "
                                                      "приймається без неї, нормалізує будь-хто")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class SearchArgs(BaseModel):
    q: str = Field(description="що шукати: село, прізвище, установа — своїми словами")
    repo: str = Field(default="", description="лише в цьому архіві")
    fond: str = Field(default="", description="лише в цьому фонді")
    limit: int = Field(default=50, description="скільки збігів показати")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class NamesArgs(BaseModel):
    repo: str = Field(description="архів: ЦДІАК, ДАОО…")
    fond: str = Field(description="фонд")
    opys: str = Field(default="", description="лише цей опис фонду")
    q: str = Field(default="", description="лише назви, що містять це")
    page: int = Field(default=1, description="сторінка словника")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class RulesArgs(BaseModel):
    repo: str = Field(description="архів")
    fond: str = Field(default="", description="фонд; порожньо — усі правила архіву")
    state: str = Field(default="", description="diie / zapyt / vidkhyleno / vidkocheno")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class RuleAddArgs(BaseModel):
    repo: str = Field(description="архів")
    fond: str = Field(description="фонд; порожньо — правило на весь архів")
    variants: list[str] = Field(description="як назву спотворено в описах (слова)")
    to: str = Field(description="певне написання, до якого звести варіанти")
    evidence: str = Field(description="rk рядка, де певне написання видно (`nysh opys names`)")
    opys: str = Field(default="", description="лише в цьому описі")
    kind: str = Field(default="prizvyshche",
                      description="prizvyshche / mistse / posadovets / inshe")
    reason: str = Field(default="", description="чому певно: кадр, джерело")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class RuleUndoArgs(BaseModel):
    id: int = Field(description="номер правила")
    reason: str = Field(default="", description="чому скасовано")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class PolicyArgs(BaseModel):
    repo: str = Field(description="архів: ЦДІАК, ДАОО…")
    fond: str = Field(description="фонд")


def _verdict_env(data: dict[str, Any], verdict: Any) -> Envelope:
    """Вердикт воріт → конверт.

    🔴 Відмова несе ВСІ причини поштучно, кожну — тривогою з кодом правила.
    Конверт помилки за контрактом не має `data`, а людина при помилці бачить
    лише `error` і примітки (`cli_emit.answer`): обрізаний перелік ховав би
    рівно те, що треба виправити, а агент не мав би кодів правил.
    """
    if verdict.passed:
        env = ok(data)
    else:
        env = fail(f"опис не пройшов ворота ({len(verdict.refusals)}) — причини нижче")
        for d in verdict.refusal_details:
            env.warn(d["rule"], d["text"], level=ALERT)
    for code, text in verdict.warnings:
        env.warn(code, text)
    return env


def _robocha_teka(d: Path) -> Envelope | None:
    """Дали робочу теку `opys read` замість теки пакета — назвати, звідки береться пакет."""
    if (d / "opys.json").exists() and not (d / "manifest.json").exists():
        return fail(f"{d} — робоча тека опису, а не пакет: `nysh opys push {d}` збере пакет і пройде "
                    f"ворота сам; лише перевірити — `nysh opys build {d}`, тоді `nysh opys check {d / 'paket'}`")
    return None


@op("opysy.check", summary="Перевірити робочу теку опису воротами Супряги, нічого не пакуючи",
    args=CheckArgs, section=SECTION, tier="rare",
    when="перед пакуванням опису — що не пройде і що лише позначиться")
def opysy_check(a: CheckArgs) -> Envelope:
    from nyshporka.opysy import bundle as B
    from nyshporka.opysy import gates as G

    if (vidmova := _robocha_teka(Path(a.dir))) is not None:
        return vidmova
    try:
        c = B.read_workdir(Path(a.dir))
    except B.BundleError as exc:
        return fail(str(exc))
    m, pages, rows, v = B.prepare(c)
    data = {"verdict": v.as_json(),
            "summary": G.summary(m, pages, rows) if m is not None else {}}
    return _verdict_env(data, v)


@op("opysy.pack", summary="Спакувати опис у .nyshopys, якщо ворота пропускають",
    args=PackArgs, mutates=True, section=SECTION, tier="rare",
    when="спакувати прочитаний опис фонду без заливки (заливає `opysy.push`)")
def opysy_pack(a: PackArgs) -> Envelope:
    from nyshporka import __version__
    from nyshporka.opysy import bundle as B

    work = Path(a.dir)
    if (vidmova := _robocha_teka(work)) is not None:
        return vidmova
    out = Path(a.out)
    if out.is_dir() or not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
        out = out / (work.resolve().name + B.SUFFIX)
    try:
        rep = B.pack(work, out, tool=f"nyshporka {__version__}")
    except B.BundleError as exc:
        return fail(str(exc))
    data = {"verdict": rep.verdict.as_json(), "summary": rep.summary,
            "file": str(rep.file) if rep.file else "", "sha256": rep.sha256,
            "bytes": rep.bytes}
    return _verdict_env(data, rep.verdict)


@op("opysy.policy", summary="Чи приймає Супряга описи цього фонду (сервер; без мережі — "
                            "вбудований перелік)",
    args=PolicyArgs, section=SECTION, tier="rare",
    when="до прогону опису — щоб не читати фонд, закритий для заливки")
def opysy_policy(a: PolicyArgs) -> Envelope:
    """Спершу сервер: його перелік ширший за вбудований і каже, куди вести людину (`link`);
    сервер недоступний чи описи там ще закриті — вбудований перелік пакета."""
    from nyshporka.opysy import gates as G
    from nyshporka.opysy import remote as R

    base = {"repo": G.repo_code(a.repo), "fond": a.fond.strip()}
    try:
        d = R.policy(a.repo, a.fond)
    except Exception:
        d = None
    if isinstance(d, dict) and "open" in d:
        return ok({**base, "open": bool(d["open"]), "why": str(d.get("why") or ""),
                   "link": str(d.get("link") or ""), "dzherelo": "server"})
    why = G.excluded(a.repo, a.fond)
    return ok({**base, "open": not why, "why": why, "dzherelo": "paket"})


@op("opysy.push", summary="Залити пакет опису в Супрягу",
    args=PushArgs, mutates=True, long=True, section=SECTION, tier="rare",
    when="віддати спакований опис фонду (.nyshopys) у Супрягу")
def opysy_push(a: PushArgs) -> Envelope:
    """Тека опису — усе за раз, як `nysh share push`: прийняти відповіді нормалізації, скласти
    робочу теку пакета, ворота, `.nyshopys`, заливка. Файл пакета — лише заливка."""
    import hashlib
    import json

    from nyshporka.opysy import remote as R
    from nyshporka.share.upload import UploadError

    path = Path(a.file)
    slid: Path | None = None
    sha = ""
    if path.is_dir():
        zibrano = _zibraty_paket(path, a.norm_model, na_obmin=a.na_obmin)
        if not zibrano.ok:
            return zibrano
        slid = path / "zalyto.json"
        path = Path(zibrano.data["file"])
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        bulo = json.loads(slid.read_text(encoding="utf-8")) if slid.exists() else {}
        if bulo.get("sha256") == sha and not a.znovu:
            # той самий пакет: сервер однаково відповів би «уже в Супрязі», але байти вже лягли б
            # у сховище й лишились би там без внеску
            return ok({"duplicate": True, "vnesok": bulo.get("vnesok"), "shyfra": bulo.get("shyfra"),
                       "text": "цей самий пакет із теки вже залито — змін немає (`--znovu`, щоб "
                               "залити все одно)"})
    try:
        got = R.push(path, base=a.base)
    except (UploadError, OSError) as exc:
        env = fail(str(exc))
        for d in getattr(exc, "details", None) or []:
            env.warn(str(d.get("rule") or "refusal"), str(d.get("text") or ""), level=ALERT)
        return env
    if slid is not None:
        slid.write_text(json.dumps({"sha256": sha, "vnesok": got.get("vnesok"),
                                    "shyfra": got.get("shyfra")}, ensure_ascii=False),
                        encoding="utf-8")
    env = ok(got)
    for w in got.get("warnings") or []:
        env.warn(str(w.get("code") or ""), str(w.get("text") or ""))
    return env


@op("opysy.search", summary="Нечіткий пошук по описах фондів у Супрязі",
    args=SearchArgs, section=SECTION, tier="rare",
    when="знайти справу за назвою в описах, яких немає в людських довідниках")
def opysy_search(a: SearchArgs) -> Envelope:
    from nyshporka.opysy import remote as R
    from nyshporka.share.upload import UploadError

    try:
        return ok(R.search(a.q, repo=a.repo, fond=a.fond, limit=a.limit, base=a.base))
    except UploadError as exc:
        return fail(str(exc))


def _remote(fn: Any, *args: Any, **kw: Any) -> Envelope:
    from nyshporka.share.upload import UploadError

    try:
        return ok(fn(*args, **kw))
    except UploadError as exc:
        env = fail(str(exc))
        for d in getattr(exc, "details", None) or []:
            env.warn(str(d.get("rule") or d.get("kod") or "refusal"), str(d.get("text") or ""),
                     level=ALERT)
        return env


@op("opysy.names", summary="Словник власних назв фонду в описах Супряги: варіанти й сусіди",
    args=NamesArgs, section=SECTION, tier="rare",
    when="побачити, як прізвище чи село спотворено в описах фонду, перед правилом підстановки")
def opysy_names(a: NamesArgs) -> Envelope:
    from nyshporka.opysy import remote as R

    return _remote(R.names, a.repo, a.fond, opys=a.opys, q=a.q, page=a.page, base=a.base)


@op("opysy.rules", summary="Правила підстановки назв в описах фонду",
    args=RulesArgs, section=SECTION, tier="rare",
    when="які варіанти назв уже зведено і що чекає рішення")
def opysy_rules(a: RulesArgs) -> Envelope:
    from nyshporka.opysy import remote as R

    return _remote(R.rules, a.repo, fond=a.fond, state=a.state, base=a.base)


@op("opysy.rule_add", summary="Звести варіанти власної назви до певного написання",
    args=RuleAddArgs, mutates=True, section=SECTION, tier="rare",
    when="у словнику фонду видно спотворені варіанти прізвища чи місця, а певне написання "
         "є в рядку-доказі")
def opysy_rule_add(a: RuleAddArgs) -> Envelope:
    from nyshporka.opysy import remote as R

    return _remote(R.rule_add, a.repo, a.fond, a.variants, a.to, evidence=a.evidence,
                   opys=a.opys, kind=a.kind, reason=a.reason, base=a.base)


@op("opysy.rule_undo", summary="Скасувати правило підстановки назв",
    args=RuleUndoArgs, mutates=True, section=SECTION, tier="rare",
    when="правило звело не те — повернути пошук до стану без нього")
def opysy_rule_undo(a: RuleUndoArgs) -> Envelope:
    from nyshporka.opysy import remote as R

    return _remote(R.rule_undo, a.id, reason=a.reason, base=a.base)


# ── Читання опису учасником: скан → сторінки → прочитане → таблиця → нормалізація → пакет ────


class InitArgs(BaseModel):
    dir: str = Field(description="робоча тека опису (буде створена)")
    pdf: str = Field(description="PDF опису на диску — той самий файл, що опубліковано")
    repo: str = Field(description="архів: ЦДІАК, ДАОО…")
    fond: str = Field(description="фонд")
    opys: str = Field(description="номер опису")
    url: str = Field(description="де цей файл опубліковано: сайт архіву чи Commons")
    kind: str = Field(default="", description="commons / archive_site / public_other; "
                                              "порожньо — з адреси")
    page_link: str = Field(default="", description="шаблон посилання на сторінку з {page}; "
                                                   "Commons — сам")
    title: str = Field(default="", description="установа фонду — для шаблону нормалізації")
    years: str = Field(default="", description="роки фонду — для шаблону нормалізації")
    language: str = Field(default="", description="мова опису (ru, uk…); порожньо — з тексту")
    published: str = Field(default="", description="оригінал, опублікований за адресою (напр. "
                                                   "djvu сайту архіву), якщо PDF — перетворення")


class DirArgs(BaseModel):
    dir: str = Field(description="робоча тека опису (`nysh opys init`)")


class PagesArgs(DirArgs):
    force: bool = Field(default=False, description="перерендерити готові сторінки")


class TableArgs(DirArgs):
    title_starts: bool = Field(default=True, description="початок справи ще й за словом «Дело», "
                                                         "«Тоже», коли № не прочитано числом")
    dobudova: bool = Field(default=True, description="добудувати номер, у якого рушій загубив "
                                                     "першу цифру чи прочитав пляму виправлення")


class NormArgs(DirArgs):
    collect: bool = Field(default=False, description="прийняти відповіді batch_NNN.out.txt")
    language: str = Field(default="", description="мова назв: ru (вихід — сучасний правопис) чи "
                                                  "uk (як в оригіналі); порожньо — з паспорта")


class BuildArgs(DirArgs):
    norm_model: str = Field(default="", description="модель, що нормалізувала назви (назва моделі "
                                                    "агента); потрібна, якщо нормалізовано")


def _workdir_fail(exc: Exception) -> Envelope:
    return fail(str(exc))


@op("opysy.init", summary="Завести робочу теку опису: паспорт джерела з PDF і адреси публікації",
    args=InitArgs, mutates=True, section=SECTION, tier="rare",
    when="почати читати опис фонду, скачаний із сайту архіву чи Commons")
def opysy_init(a: InitArgs) -> Envelope:
    from nyshporka.opysy import workdir as W

    try:
        pas = W.init(Path(a.dir), Path(a.pdf), repo=a.repo, fond=a.fond, opys=a.opys, url=a.url,
                     kind=a.kind, page_link=a.page_link, title=a.title, years=a.years,
                     language=a.language, published=Path(a.published) if a.published else None)
    except (W.WorkdirError, ValueError, OSError) as exc:
        return _workdir_fail(exc)
    return ok({"dir": str(Path(a.dir).resolve()), "pages": pas["pages"], "source": pas["source"],
               "next": f"nysh opys pages {a.dir}"})


@op("opysy.pages", summary="Сторінки опису з PDF у JPEG під читання цілими сторінками",
    args=PagesArgs, mutates=True, long=True, section=SECTION, tier="rare",
    when="після `nysh opys init`, перед `nysh read`")
def opysy_pages(a: PagesArgs) -> Envelope:
    from nyshporka.opysy import pages as PG
    from nyshporka.opysy import workdir as W

    try:
        pas = W.load(Path(a.dir))
        res = PG.render(Path(pas["pdf"]), W.pages_dir(Path(a.dir)), force=a.force)
    except (W.WorkdirError, OSError) as exc:
        return _workdir_fail(exc)
    d = Path(a.dir)
    return ok({**res, "dir": str(W.pages_dir(d)),
               "next": f"nysh read {W.pages_dir(d)} --out {W.run_dir(d)}"})


@op("opysy.table", summary="Таблиця справ опису з прочитаних цілих сторінок",
    args=TableArgs, mutates=True, section=SECTION, tier="rare",
    when="сторінки опису прочитано (`nysh read … --out <тека>/run`)")
def opysy_table(a: TableArgs) -> Envelope:
    from nyshporka.opysy import ruled as RU
    from nyshporka.opysy import workdir as W

    d = Path(a.dir)
    try:
        W.load(d)
    except W.WorkdirError as exc:
        return _workdir_fail(exc)
    if not any(W.run_dir(d).glob("*.txt")):
        return fail(f"немає прочитаних сторінок — `nysh read {W.pages_dir(d)} --out {W.run_dir(d)}`")
    from nyshporka.opysy import dochyt as DC
    from nyshporka.opysy import meta as M

    meta = M.load(d)
    dd = W.dochyt_dir(d)
    if meta is not None and meta.forma == "typed":
        from nyshporka.opysy import vl_table as VT

        if not any(W.vl_dir(d).glob("*.md")):
            return fail(f"немає розмітки рушія друку в {W.vl_dir(d)} — `nysh opys read {a.dir}`")
        from nyshporka.opysy import meta as M

        mt = M.load(d) if (d / M.FILE).exists() else None
        res = VT.build(W.vl_dir(d), W.table_path(d), opys=str(W.load(d).get("opys") or ""),
                       u_tablytsi=mt.u_tablytsi if mt is not None else None)
        res = {k: v for k, v in res.items() if not isinstance(v, (list, dict))}
        res["confirmed"] = res.get("pidtverdzheno", 0)
        # справа — рядок з назвою: рядок без назви пакет однаково відкидає (порожня клітинка VL)
        import csv

        with W.table_path(d).open(encoding="utf-8", newline="") as fh:
            res["cases"] = sum(1 for r in csv.DictReader(fh, delimiter="	") if (r.get("title") or "").strip())
        if meta.sprav:
            res["sprav"] = meta.sprav
            res["povnota"] = round(res.get("cases", 0) / meta.sprav, 3)
    else:
        res = RU.build(W.run_dir(d), W.table_path(d), title_starts=a.title_starts, dobudova=a.dobudova,
                       dochyt=dd if (dd / DC.MAPA).exists() else None, meta=meta)
    env = ok({**res, "file": str(W.table_path(d)), "next": f"nysh opys norm {a.dir}"})
    if res.get("povnota") is not None and res["povnota"] < 0.9:
        env.warn("povnota", f"справ у таблиці {res['cases']} з {res['sprav']} за метаданими "
                            f"({100 * res['povnota']:.0f} %) — частина справ злиплась чи загубилась")
    return env


class MetaArgs(BaseModel):
    dir: str = Field(description="робоча тека опису")
    forma: Literal["", "blank", "hand_ruled", "typed"] = Field(
        default="", description="blank — друкований бланк; hand_ruled — розграфлено від руки; typed — машинопис")
    rozvorot: bool | None = Field(default=None, description="у кадрі розворот двох сторінок")
    kolonky: str = Field(default="", description="ролі колонок зліва направо через кому: nomer, delovod, "
                                                 "pochatok, nazva, kinets, arkushi, vidmitka, inshe")
    kolonky_prava: str = Field(default="", description="те саме для правої сторінки, якщо вона інакша")
    sprav: int = Field(default=-1, description="скільки справ в описі (0 — невідомо)")
    dzherelo: str = Field(default="", description="звідки число справ: засвідчувальний напис, останній номер")
    storinky: str = Field(default="", description="сторінки таблиці справ «перша-остання»")


@op("opysy.meta", summary="Метадані опису від агента: форма, колонки, скільки справ, сторінки таблиці",
    args=MetaArgs, mutates=True, section=SECTION, tier="rare",
    when="перед читанням опису: агент глянув 2–3 сторінки й записує те, що машині вгадувати важко")
def opysy_meta(a: MetaArgs) -> Envelope:
    from dataclasses import replace

    from nyshporka.opysy import meta as M
    from nyshporka.opysy import workdir as W

    d = Path(a.dir)
    try:
        W.load(d)
    except W.WorkdirError as exc:
        return _workdir_fail(exc)
    m = M.load(d) or M.Meta()
    zminy: dict[str, Any] = {}
    if a.forma:
        zminy["forma"] = a.forma
    if a.rozvorot is not None:
        zminy["rozvorot"] = a.rozvorot
    if a.kolonky:
        zminy["kolonky"] = tuple(k.strip() for k in a.kolonky.split(",") if k.strip())
    if a.kolonky_prava:
        zminy["kolonky_prava"] = tuple(k.strip() for k in a.kolonky_prava.split(",") if k.strip())
    if a.sprav >= 0:
        zminy["sprav"] = a.sprav
    if a.dzherelo:
        zminy["sprav_dzherelo"] = a.dzherelo
    try:
        if a.storinky:
            zminy["storinky"] = M.rozibraty_storinky(a.storinky)
        if not zminy:
            storinok = len(list(W.pages_dir(d).glob("*.jpg")))
            return ok({"meta": None if M.load(d) is None else M.load(d).__dict__,
                       "hlianuty": [str(W.pages_dir(d) / f"{n:04d}.jpg") for n in M.kudy_hlianuty(storinok)],
                       "next": f"nysh opys meta {a.dir} --forma … --kolonky … --sprav N --dzherelo … --storinky A-B"})
        p = M.save(d, replace(m, **zminy, zapovniv="агент", koly=""))
    except M.MetaError as exc:
        return fail(str(exc))
    return ok({"file": str(p), "meta": M.load(d).__dict__ if M.load(d) else {},
               "next": f"nysh opys read {a.dir}"})


@op("opysy.norm", summary="Нормалізація назв справ опису: пачки запитів агентові або прийом "
                          "відповідей",
    args=NormArgs, mutates=True, section=SECTION, tier="rare",
    when="таблицю справ складено; рукопис без нормалізації ворота не пропускають")
def opysy_norm(a: NormArgs) -> Envelope:
    from nyshporka.opysy import norm_batches as NB
    from nyshporka.opysy import workdir as W

    d = Path(a.dir)
    try:
        pas = W.load(d)
    except W.WorkdirError as exc:
        return _workdir_fail(exc)
    if a.collect:
        res = NB.collect(W.norm_dir(d), W.norm_path(d))
        env = ok({**res, "next": f"nysh opys build {a.dir} --norm-model <модель>"})
        if res["missing"]:
            env.warn("norm_missing", f"без відповіді {len(res['missing'])} пачок: "
                                     f"{', '.join(res['missing'][:5])}")
        for b in res["bad"]:
            env.warn("norm_bad", b, level=ALERT)
        return env
    if not W.table_path(d).exists():
        return fail("немає таблиці справ — `nysh opys table`")
    mova = a.language or pas.get("language") or ""
    if not mova:
        # як у `build`: з прочитаного тексту (українська назва під `ru_modern` русифікувалась би)
        from nyshporka.opysy import pack_dir as PD

        voices = PD.run_voices(W.run_dir(d))
        mova = PD.language(PD.pages_from_voices(voices, int(pas["pages"])), "")
    if mova not in NB.MOVY:
        return fail(f"мова опису «{mova or 'не визначено з тексту'}»: шаблон нормалізації є для "
                    f"{', '.join(NB.MOVY)} — назви її (`--language`)")
    src = NB.describe_source(pas["repo"], pas["fond"], pas.get("title", ""), pas.get("years", ""), mova)
    got = NB.export(W.table_path(d), W.norm_dir(d), source=src, mova=mova,
                    have=NB.known(W.norm_path(d)))
    return ok({"batches": [str(p) for p in got], "dir": str(W.norm_dir(d)),
               "how": "кожну пачку batch_NNN.json віддати моделі (поле `request` — увесь запит); "
                      "відповідь — лише JSON-масив тієї самої довжини — у batch_NNN.out.txt поруч",
               "next": f"nysh opys norm {a.dir} --collect"})


class ReadOpysArgs(BaseModel):
    dir: str = Field(description="робоча тека опису (буде створена; повтор — продовжує з місця)")
    pdf: str = Field(default="", description="PDF опису — для нової теки: той самий файл, що "
                                             "опубліковано")
    repo: str = Field(default="", description="архів: ЦДІАК, ДАОО… (для нової теки)")
    fond: str = Field(default="", description="фонд (для нової теки)")
    opys: str = Field(default="", description="номер опису (для нової теки)")
    url: str = Field(default="", description="де файл опубліковано: сайт архіву чи Commons")
    published: str = Field(default="", description="оригінал за адресою (djvu сайту архіву), якщо "
                                                   "PDF — перетворення")
    title: str = Field(default="", description="установа фонду — для шаблону нормалізації")
    years: str = Field(default="", description="роки фонду — для шаблону нормалізації")
    language: str = Field(default="", description="мова опису (ru, uk); порожньо — з тексту")
    script: Literal["", "latin", "cyrillic"] = Field(default="", description="письмо; порожньо — "
                                                                           "як вирішить `nysh read`")
    form: Literal["hand_ruled", "typed"] = Field(default="hand_ruled",
                                                 description="вигляд опису: рукопис на розграфлених "
                                                             "аркушах чи машинопис (остаточно — "
                                                             "метадані `nysh opys meta --forma`)")
    de: Literal["auto", "lokalno", "hmara"] = Field(
        default="auto", description="де читати: `hmara` — орендована карта (`nysh cloud go`), "
                                    "`lokalno` — ця машина, `auto` — хмара, якщо плагін оренди "
                                    "стоїть, інакше тут. Машинопис — лише хмара")
    hmara_param: list[str] = Field(default_factory=list,
                                   description="параметри хмарного заходу `ключ=значення` (як `-p` "
                                               "у `nysh cloud go`)")
    confirm: bool = Field(default=False, description="дозвіл ЛЮДИНИ на хмарний захід понад стелю "
                                                     "автозапуску")


def _orenda_ye() -> bool:
    """Чи стоїть плагін оренди (наглядач хмарних заходів) — тоді `auto` читає в хмарі."""
    from nyshporka.cloud import supervised as SV

    try:
        SV.gpurunner_cmd()
    except Exception:
        return False
    return True


def _hmara_etap(d: Path, etap: str, kadry: Path, kudy: Path, a: ReadOpysArgs, *, mitka: str = ""
                ) -> tuple[str, dict[str, Any]]:
    """Етап хмарного читання: `gotovo` (результат уже в `kudy`), `ide` (захід читає — повтор
    забере) чи `postavleno` (щойно поставлено). Відмова `cloud go` — `HmaraError`."""
    from nyshporka.opysy import hmara as H

    zap = H.stan(d).get(etap)
    if zap and zap.get("zabrano"):
        return "gotovo", zap
    if zap:
        zrobleno, vsi = H.gotovo(d, etap)
        povno = bool(vsi) and zrobleno >= vsi
        if not povno and H.skinchyvsia(zap):
            if zrobleno == 0:
                # Захід скінчився, не прочитавши нічого (ринок порожній, машина не встала): етап геть,
                # причину названо; `auto` читає тут, повтор `read` поставить захід знову.
                pr = H.prychyna(zap)
                H.zabuty(d, etap)
                raise H.HmaraError("хмарний захід скінчився без результату"
                                   + (f" ({pr})" if pr else "")
                                   + " — та сама команда поставить його знову")
            # Захід скінчився з нестачею (обрив, карантин сторінки): чекати більше нічого — береться
            # прочитане, решту дочитує ця машина (сторінки, кропи) або бракує (машинопис).
            zap["nepovno"] = f"{zrobleno} з {vsi}"
            H._zapysaty(d, etap, zap)
            povno = True
        if povno:
            H.zabraty(d, etap, kudy)
            if etap == "storinky":
                # другий голос лягає поруч: `<тека результату>-<голос>` → `<тека>/run-<голос>`
                out = Path(zap["out_dir"])
                for sib in out.parent.glob(out.name + "-*"):
                    if sib.is_dir():
                        H.zabraty_tekou(sib, kudy.parent / f"{kudy.name}-{sib.name[len(out.name) + 1:]}")
            return "gotovo", H.stan(d)[etap]
        return "ide", {**zap, "prochytano": zrobleno, "vsi": vsi}
    pysmo = _pysmo(d, a)
    if not pysmo and etap != "druk":
        raise H.HmaraError("для хмари треба письмо: назвіть мову опису (`--language ru|uk|pl`) або "
                           "письмо (`--script cyrillic|latin`)")
    zap = H.postavyty(d, etap, kadry, script=pysmo, params=a.hmara_param, confirm=a.confirm,
                      mitka=mitka)
    return "postavleno", zap


def _pysmo(d: Path, a: ReadOpysArgs) -> str:
    """Письмо для хмари: явне, інакше з мови опису (ru/uk — кирилиця, pl/la — латинка). `cloud go`
    без письма відмовляє: вгаданий рушій дає не збій, а осмислене на вигляд сміття."""
    if a.script:
        return a.script
    from nyshporka.opysy import workdir as W

    mova = (a.language or str(W.load(d).get("language") or "")).lower()
    return {"ru": "cyrillic", "uk": "cyrillic", "be": "cyrillic", "pl": "latin", "la": "latin"}.get(mova, "")


def _hmara_vidpovid(d: Path, a: ReadOpysArgs, kroky: list[str], etap: str, stan: str,
                    zap: dict[str, Any]) -> Envelope:
    nazva = {"storinky": "сторінки опису", "kropy": "кропи колонки №", "druk": "машинопис (рушій друку)"}[etap]
    run_id = zap.get("run_id") or ""
    tekst = (f"{nazva}: захід поставлено в хмару" if stan == "postavleno" else
             f"{nazva}: хмара ще читає — {zap.get('prochytano', 0)} з {zap.get('vsi', zap.get('kadriv', 0))}")
    return ok({"dir": str(d.resolve()), "zrobleno": kroky, "hmara": {
        "etap": etap, "stan": stan, "run_id": run_id, "out_dir": zap.get("out_dir"),
        "byudzhet_usd": zap.get("budget_usd"), "vylka_do_usd": zap.get("fork_high")},
        "how": tekst + (f"; стан — `nysh cloud state {run_id}`" if run_id else ""),
        "next": f"nysh opys read {a.dir} — та сама команда забере результат, коли хмара дочитає"})


def _chytaty(pages: Path, run: Path, script: str, *, whole_line: bool = False) -> int:
    """`nysh read <тека>/pages --out <тека>/run` тим самим інтерпретатором: прогрес — на екран,
    як у звичайному прогоні; продовжує з місця, де читання обірвалось. `whole_line` — кропи
    (`opysy.dochyt`): кадр — уже рядок."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "nyshporka", "read", str(pages), "--out", str(run)]
    if script:
        cmd += ["--script", script]
    if whole_line:
        cmd.append("--whole-line")
    return subprocess.run(cmd, check=False).returncode


def _dochyt(d: Path, a: ReadOpysArgs, *, hmara: bool = False
            ) -> tuple[list[str], str, tuple[str, dict[str, Any]] | None]:
    """Кропи колонки № і плям чорнила (з метаданими) і їх читання цілими рядками; повтор —
    з місця. Змінились метадані — кропи перерізаються. Повертає (кроки, причина збою, хмарний
    етап, що ще йде). `hmara` — кропи читає орендована карта: на процесорі кроп ~1 с, а опис
    на сотню сторінок дає тисячі кропів (25.11.2026: 1,1 с/кроп на i7-9750H)."""
    script = a.script
    import json
    import shutil

    from nyshporka.opysy import dochyt as DC
    from nyshporka.opysy import meta as M
    from nyshporka.opysy import workdir as W

    dd = W.dochyt_dir(d)
    mf = d / M.FILE
    # Відбиток — лише полів, від яких залежать кропи, а не файла: `opys meta` щоразу пише нову мітку
    # часу, і той самий вміст скидав би дочит (а в хмарі — ставив платний захід наново).
    mt = M.load(d) if mf.exists() else None
    vidbytok = M.vidbytok_dochytu(mt) if mt is not None else ""
    mapa = dd / DC.MAPA
    kroky = []
    staryi = json.loads((dd / "meta_sha.json").read_text(encoding="utf-8")).get("sha") \
        if (dd / "meta_sha.json").exists() else None
    if not mapa.exists() or staryi != vidbytok:
        if dd.exists():
            shutil.rmtree(dd)
        DC.kropy(W.run_dir(d), W.pages_dir(d), dd, M.load(d))
        (dd / "meta_sha.json").write_text(json.dumps({"sha": vidbytok}), encoding="utf-8")
        kroky.append("кропи колонки №")
    hotovo = dd / "_chytannia_zaversheno.json"
    vsi, gotovi = _prochytano_teky(dd / DC.KROPY, dd / DC.KROPY_OUT)
    if vsi and gotovi < vsi and not hotovo.exists() and hmara:
        from nyshporka.opysy import hmara as H

        if (H.stan(d).get("kropy") or {}).get("mitka", vidbytok[:8]) != vidbytok[:8]:
            # кропи перерізано після заходу — старий результат не їхній
            H.zabuty(d, "kropy")
        try:
            stan, zap = _hmara_etap(d, "kropy", dd / DC.KROPY, dd / DC.KROPY_OUT, a, mitka=vidbytok[:8])
        except H.HmaraError as exc:
            if exc.zghoda or a.de == "hmara":
                return kroky, f"кропи колонки № у хмару не поставлено: {exc}", None
            stan, zap = "lokalno", {}
            kroky.append(f"кропи колонки № — на цій машині: хмара не взяла захід ({exc})")
        if stan not in ("gotovo", "lokalno"):
            return kroky, "", (stan, zap)
        if stan == "gotovo":
            H._zapysaty(d, "kropy", {**H.stan(d).get("kropy", {}), "mitka": vidbytok[:8]})
            vsi, gotovi = _prochytano_teky(dd / DC.KROPY, dd / DC.KROPY_OUT)
            kroky.append("дочит № (хмара)" + (f", неповно: {zap['nepovno']}" if zap.get("nepovno") else ""))
            if gotovi >= vsi:
                hotovo.write_text(json.dumps({"kropiv": vsi, "prochytano": gotovi, "de": "hmara"}),
                                  encoding="utf-8")
    if vsi and gotovi < vsi and not hotovo.exists():
        rc = _chytaty(dd / DC.KROPY, dd / DC.KROPY_OUT, script, whole_line=True)
        vsi, gotovi = _prochytano_teky(dd / DC.KROPY, dd / DC.KROPY_OUT)
        if gotovi < vsi and rc != 0:
            return kroky, f"дочитано {gotovi} з {vsi} кропів колонки № (код {rc}) — та сама команда продовжить", None
        # прогін скінчився, а кропа без тексту рушій не записав — дочит лише доповнює читання сторінок:
        # такий кроп лишається без номера, і повтор `read` не крутить його вічно
        hotovo.write_text(json.dumps({"kropiv": vsi, "prochytano": gotovi}), encoding="utf-8")
        kroky.append("дочит №")
    return kroky, "", None


def _prochytano(d: Path) -> tuple[int, int]:
    """(сторінок, прочитано). Прочитана — є текст АБО рушій записав її в мету прогону: порожня
    чи титульна сторінка тексту може не мати, і без мети «прочитано 3 з 4» не минало б ніколи."""
    from nyshporka.opysy import workdir as W

    return _prochytano_teky(W.pages_dir(d), W.run_dir(d))


def _prochytano_teky(kadry: Path, run: Path) -> tuple[int, int]:
    import contextlib
    import json

    vsi = {p.stem for p in kadry.glob("*.jpg")} if kadry.exists() else set()
    gotovi = {p.stem for p in run.glob("*.txt")} if run.exists() else set()
    meta = run / "_htr_meta.json"
    if meta.exists():
        with contextlib.suppress(ValueError, OSError):
            gotovi |= {Path(k).stem for k in (json.loads(meta.read_text(encoding="utf-8"))
                                              .get("pages") or {})}
    return len(vsi), len(gotovi & vsi)


@op("opysy.read", summary="Прочитати опис фонду: паспорт, сторінки, читання, таблиця справ і "
                          "пачки нормалізації — одним кроком",
    args=ReadOpysArgs, mutates=True, long=True, section=SECTION, tier="rare",
    when="є PDF опису фонду й адреса публікації; далі — нормалізація й `nysh opys push`")
def opysy_read(a: ReadOpysArgs) -> Envelope:
    """Увесь шлях до нормалізації, як `nysh read` для справи. Кожен крок, зроблений раніше,
    пропускається: перерваний прогін — та сама команда ще раз."""
    from nyshporka.opysy import workdir as W

    d = Path(a.dir)
    kroky: list[str] = []
    try:
        W.load(d)
    except W.WorkdirError:
        brak = [k for k, v in (("--pdf", a.pdf), ("--repo", a.repo), ("--fond", a.fond),
                               ("--opys", a.opys), ("--url", a.url)) if not v]
        if brak:
            return fail(f"нова тека опису — потрібні {', '.join(brak)}")
        pol = opysy_policy(PolicyArgs(repo=a.repo, fond=a.fond))
        if pol.ok and not pol.data.get("open"):
            why = pol.data.get("why") or "описи цього фонду Супряга не приймає"
            return fail(f"{a.repo} ф.{a.fond}: {why}")
        env = opysy_init(InitArgs(dir=a.dir, pdf=a.pdf, repo=a.repo, fond=a.fond, opys=a.opys,
                                  url=a.url, title=a.title, years=a.years, language=a.language,
                                  published=a.published))
        if not env.ok:
            return env
        kroky.append("паспорт")
    vsi, gotovi = _prochytano(d)
    if not vsi:
        env = opysy_pages(PagesArgs(dir=a.dir))
        if not env.ok:
            return env
        kroky.append("сторінки")
        vsi, gotovi = _prochytano(d)
    from nyshporka.opysy import meta as M

    meta = M.load(d)
    if meta is None:
        # Агент задає те, що машині вгадувати важко (форма, колонки, скільки справ), ДО читання:
        # на цьому стоїть вибір схеми таблиці. 2–3 сторінки оком — і та сама команда далі.
        hl = [str(W.pages_dir(d) / f"{n:04d}.jpg") for n in M.kudy_hlianuty(vsi)]
        return ok({"dir": str(d.resolve()), "zrobleno": kroky, "storinok": vsi,
                   "meta_potribni": True, "hlianuty": hl,
                   "how": "подивись ці сторінки (перша сторінка таблиці, середня, остання — там зазвичай "
                          "засвідчувальний напис з числом справ) і запиши метадані опису",
                   "next": f"nysh opys meta {a.dir} --forma blank|hand_ruled|typed --kolonky "
                           f"nomer,...,nazva,... --sprav N --dzherelo \"звідки число\" --storinky A-B; "
                           f"тоді та сама команда: nysh opys read {a.dir}"})
    from nyshporka.opysy import hmara as H

    poperedzhennia_hmary: list[str] = []
    if meta.forma == "typed":
        # Машинопис читає лише рушій друку, а він — лише в хмарі. Сторінки — під його висоту.
        from nyshporka.opysy import pages as PG
        from nyshporka.opysy import vl_table as VT

        druk = W.druk_pages_dir(d)
        if not PG.render(Path(W.load(d)["pdf"]), druk, target_h=VT.VYSOTA).get("skip"):
            kroky.append("сторінки під рушій друку")
        vl_hotovo = len(list(W.vl_dir(d).glob("*.md"))) >= len(list(druk.glob("*.jpg")))
        if not (H.stan(d).get("druk") or {}).get("zabrano") and not vl_hotovo:
            try:
                stan, zap = _hmara_etap(d, "druk", druk, W.vl_dir(d), a)
            except H.HmaraError as exc:
                return fail(f"машинопис читає рушій друку лише в хмарі, а захід не поставлено: {exc}")
            if stan != "gotovo":
                return _hmara_vidpovid(d, a, kroky, "druk", stan, zap)
            kroky.append("читання (хмара, друк)")
        if len(list(W.run_dir(d).glob("*.txt"))) < len(list(W.vl_dir(d).glob("*.md"))):
            H.vl_do_run(W.vl_dir(d), W.run_dir(d), druk)
        if (H.stan(d).get("druk") or {}).get("nepovno"):
            poperedzhennia_hmary.append(f"рушій друку скінчив з нестачею: прочитано "
                                        f"{H.stan(d)['druk']['nepovno']} сторінок — таблиця неповна")
    else:
        de = a.de if a.de != "auto" else ("hmara" if _orenda_ye() else "lokalno")
        if gotovi < vsi and de == "hmara":
            try:
                stan, zap = _hmara_etap(d, "storinky", W.pages_dir(d), W.run_dir(d), a)
            except H.HmaraError as exc:
                if a.de == "hmara" or exc.zghoda:
                    return fail(f"хмарне читання не поставлено: {exc}"
                                + ("" if a.de == "hmara" else " Або читати на цій машині: `--de lokalno`."))
                poperedzhennia_hmary.append(f"хмара не взяла захід ({exc}) — читаю на цій машині")
                de = "lokalno"
            else:
                if stan != "gotovo":
                    return _hmara_vidpovid(d, a, kroky, "storinky", stan, zap)
                kroky.append("читання (хмара)")
                vsi, gotovi = _prochytano(d)
        if gotovi < vsi:
            rc = _chytaty(W.pages_dir(d), W.run_dir(d), a.script)
            vsi, gotovi = _prochytano(d)
            if gotovi < vsi:
                return fail(f"прочитано {gotovi} з {vsi} сторінок (код {rc}) — та сама команда "
                            f"продовжить з місця")
            kroky.append("читання")
        dk, zbii, hm = _dochyt(d, a, hmara=(de == "hmara"))
        kroky += dk
        if hm is not None:
            return _hmara_vidpovid(d, a, kroky, "kropy", hm[0], hm[1])
        if zbii:
            return fail(zbii)
    env = opysy_table(TableArgs(dir=a.dir))
    if not env.ok:
        return env
    tablytsia = env.data
    poperedzhennia = list(env.warnings)
    kroky.append("таблиця")
    env = opysy_norm(NormArgs(dir=a.dir, language=a.language))
    if not env.ok:
        return env
    from nyshporka.opysy import norm_batches as NB

    # чекають відповіді — і нарізані щойно, і ті, що лишились з попереднього запуску
    pachky = NB.bez_vidpovidi(W.norm_dir(d))
    from nyshporka.opysy import norm_api as NA

    api = NA.stan()
    cherez_api = (f"`nysh opys norm {a.dir} --api` (ключ API людини: {api.get('model')}, лишилось "
                  f"${api.get('zalyshok_usd')}), або ") if api.get("nalashtovano") else ""
    nastupne = (f"{cherez_api}агент нормалізує пачки в {env.data.get('dir')}, тоді "
                f"`nysh opys push {a.dir} --norm-model <модель>`; немає агента чи ресурсів — "
                f"`nysh opys push {a.dir} --na-obmin` (нормалізує обмін у Супрязі)") if pachky \
        else f"nysh opys push {a.dir}"
    out = ok({"dir": str(d.resolve()), "zrobleno": kroky, "storinok": vsi,
              "sprav": tablytsia.get("cases"), "pidtverdzheno_nomeriv": tablytsia.get("confirmed"),
              "sprav_za_metadanymy": tablytsia.get("sprav"), "povnota": tablytsia.get("povnota"),
              "skhema": tablytsia.get("skhema"),
              "pachok_normalizatsii": len(pachky),
              "novykh_pachok": len(env.data.get("batches") or []),
              "norm_dir": env.data.get("dir"), "how": env.data.get("how"), "next": nastupne})
    out.warnings.extend(poperedzhennia)
    for t in poperedzhennia_hmary:
        out.warn("hmara", t)
    return out


def _zibraty_paket(d: Path, norm_model: str, *, na_obmin: bool = False) -> Envelope:
    """Тека опису → `.nyshopys` поруч: відповіді нормалізації, робоча тека пакета, ворота.
    Модель нормалізації називається один раз і пам'ятається в теці."""
    from nyshporka import __version__
    from nyshporka.opysy import bundle as B
    from nyshporka.opysy import norm_batches as NB
    from nyshporka.opysy import workdir as W

    try:
        W.load(d)
    except W.WorkdirError as exc:
        return _workdir_fail(exc)
    zapys = W.norm_dir(d) / "model.txt"
    if norm_model.strip():
        zapys.parent.mkdir(parents=True, exist_ok=True)
        zapys.write_text(norm_model.strip(), encoding="utf-8")
    model = norm_model.strip() or (zapys.read_text(encoding="utf-8").strip()
                                   if zapys.exists() else "")
    poperedzhennia: list[tuple[str, str]] = []
    if W.norm_dir(d).exists() and any(W.norm_dir(d).glob("batch_*.out.txt")):
        res = NB.collect(W.norm_dir(d), W.norm_path(d))
        if res["missing"]:
            poperedzhennia.append(("norm_missing", f"без відповіді {len(res['missing'])} пачок: "
                                                   f"{', '.join(res['missing'][:5])}"))
        poperedzhennia += [("norm_bad", b) for b in res["bad"]]
        if not model:
            return fail("назви нормалізовано — назвіть модель, що нормалізувала: "
                        f"`nysh opys push {d} --norm-model <модель>` (один раз)")
    try:
        W.build(d, norm_model=model, tool=f"nyshporka {__version__}", na_obmin=na_obmin)
    except (W.WorkdirError, ValueError) as exc:
        return _workdir_fail(exc)
    out = d / (d.resolve().name + B.SUFFIX)
    try:
        rep = B.pack(W.paket_dir(d), out, tool=f"nyshporka {__version__}")
    except B.BundleError as exc:
        return fail(str(exc))
    env = _verdict_env({"file": str(rep.file) if rep.file else "", "summary": rep.summary},
                       rep.verdict)
    for code, text in poperedzhennia:
        if code == "norm_bad":
            env.warn(code, text, level=ALERT)
        else:
            env.warn(code, text)
    return env


@op("opysy.build", summary="Робоча тека пакета опису з прочитаного, таблиці й нормалізації",
    args=BuildArgs, mutates=True, section=SECTION, tier="rare",
    when="таблицю складено й назви нормалізовано — перед `nysh opys pack`")
def opysy_build(a: BuildArgs) -> Envelope:
    from nyshporka import __version__
    from nyshporka.opysy import workdir as W

    d = Path(a.dir)
    try:
        res = W.build(d, norm_model=a.norm_model, tool=f"nyshporka {__version__}")
    except (W.WorkdirError, ValueError) as exc:
        return _workdir_fail(exc)
    return ok({**res, "next": f"nysh opys pack {W.paket_dir(d)} --out {d}"})


# ── обмін нормалізацією: узяти чужий опис і віддати нормалізацію ─────────────


class ObminArgs(BaseModel):
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class VziatyArgs(BaseModel):
    dir: str = Field(description="тека, куди покласти пачки запитів")
    vnesok: int | None = Field(default=None, description="який опис (внесок); порожньо — "
                                                         "найстаріший, що чекає")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


class ViddatyArgs(BaseModel):
    dir: str = Field(description="тека, взята `nysh opys vziaty`")
    model: str = Field(default="", description="модель, що нормалізувала (назва моделі агента); "
                                               "порожньо — з `model.txt` теки (пише `norm --api`)")
    base: str = Field(default="", description="адреса пулу; порожньо — типова")


@op("opysy.obmin", summary="Описи, нормалізацію яких автори віддали на обмін",
    args=ObminArgs, section=SECTION, tier="rare",
    when="є агент і ресурси нормалізувати чужий цінний опис")
def opysy_obmin(a: ObminArgs) -> Envelope:
    from nyshporka.opysy import remote as R

    return _remote(R.obmin_cherha, base=a.base)


@op("opysy.vziaty", summary="Узяти опис на нормалізацію (48 год): тека з пачками для агента",
    args=VziatyArgs, mutates=True, section=SECTION, tier="rare",
    when="узяти з обміну опис, щоб нормалізувати назви своїм агентом")
def opysy_vziaty(a: VziatyArgs) -> Envelope:
    from nyshporka.opysy import obmin as OB
    from nyshporka.opysy import remote as R

    env = _remote(R.obmin_vziaty, vnesok=a.vnesok, base=a.base)
    if not env.ok:
        return env
    z = env.data
    nove = OB.zapysaty(Path(a.dir), z)
    return ok({"obmin": z.get("obmin"), "shyfra": z.get("shyfra"), "do": z.get("do"),
               "dzherelo": z.get("dzherelo", ""),
               "nazv": len(z.get("riadky") or []), "pachok": OB.bez_vidpovidi(Path(a.dir)),
               "novykh_pachok": len(nove), "dir": str(Path(a.dir).resolve()),
               "how": "кожну пачку batch_NNN.json віддати моделі (поле `request` — увесь запит); "
                      "відповідь — лише JSON-масив тієї самої довжини — у batch_NNN.out.txt поруч",
               "next": f"nysh opys viddaty {a.dir} --model <модель>"})


@op("opysy.viddaty", summary="Віддати нормалізацію взятого опису (пачки з відповіддю)",
    args=ViddatyArgs, mutates=True, long=True, section=SECTION, tier="rare",
    when="агент відповів на пачки опису, взятого з обміну")
def opysy_viddaty(a: ViddatyArgs) -> Envelope:
    import json

    from nyshporka.opysy import obmin as OB
    from nyshporka.opysy import remote as R

    d = Path(a.dir)
    zfile = d / OB.ZAVDANNIA
    if not zfile.exists():
        return fail(f"у {d} немає взятого опису — `nysh opys vziaty {d}`")
    z = json.loads(zfile.read_text(encoding="utf-8"))
    model = a.model.strip() or ((d / "model.txt").read_text(encoding="utf-8").strip()
                                if (d / "model.txt").exists() else "")
    if not model:
        return fail(f"назвіть модель, що нормалізувала: `nysh opys viddaty {d} --model <модель>`")
    vidp, gotovi, bad = OB.vidpovidi(d)
    if not vidp:
        env = fail("немає нових відповідей — агент кладе batch_NNN.out.txt поруч із пачкою")
        for b in bad:
            env.warn("norm_bad", b, level=ALERT)
        return env
    pidsumok: dict[str, Any] = {"pryiniato": 0, "ne_sprava": 0, "avtora": 0, "poznachky": []}
    for i in range(0, len(vidp), 500):
        env = _remote(R.obmin_viddaty, int(z["obmin"]), model=model,
                      vidpovidi=vidp[i:i + 500], base=a.base)
        if not env.ok:
            return env
        for k in ("pryiniato", "ne_sprava", "avtora"):
            pidsumok[k] += int(env.data.get(k) or 0)
        pidsumok["poznachky"] += env.data.get("poznachky") or []
        pidsumok.update({k: env.data.get(k) for k in ("stan", "normalizovano", "spravy")})
    OB.poznachyty(d, gotovi)
    env = ok({**pidsumok, "shyfra": z.get("shyfra"), "pachok_bez_vidpovidi": OB.bez_vidpovidi(d)})
    for b in bad:
        env.warn("norm_bad", b, level=ALERT)
    return env


# ── нормалізація ключем API учасника ─────────────────────────────────────────


class ApiStanArgs(BaseModel):
    pass


@op("opysy.api_stan", summary="Нормалізація ключем API: модель, бюджет, витрачено, лишилось",
    args=ApiStanArgs, section=SECTION, tier="rare",
    when="перед `nysh opys norm --api` — чи налаштовано ключ і скільки лишилось бюджету")
def opysy_api_stan(a: ApiStanArgs) -> Envelope:
    from nyshporka.opysy import norm_api as NA

    return ok(NA.stan())


class NormApiArgs(BaseModel):
    dir: str = Field(description="робоча тека опису (`nysh opys read`) чи тека, взята `nysh opys vziaty`")
    rezhym: Literal["batch", "zaraz"] = Field(default="batch", description="batch — удвічі дешевше, "
                                              "відповідь за хвилини-години; zaraz — по одному запиту")
    chekaty_hv: float = Field(default=30.0, description="скільки хвилин чекати задачу batch; далі — "
                                                        "та сама команда забере готове")


def _teka_pachok(d: Path) -> Path | None:
    from nyshporka.opysy import obmin as OB
    from nyshporka.opysy import workdir as W

    try:
        W.load(d)
        return W.norm_dir(d)
    except W.WorkdirError:
        return d if (d / OB.ZAVDANNIA).exists() else None


@op("opysy.norm_api", summary="Нормалізувати назви справ ключем API людини в межах її бюджету",
    args=NormApiArgs, mutates=True, long=True, section=SECTION, tier="rare",
    when="людина налаштувала ключ API (`nysh opys api nalashtuvaty`) і є пачки без відповіді")
def opysy_norm_api(a: NormApiArgs) -> Envelope:
    from nyshporka.opysy import norm_api as NA

    d = Path(a.dir)
    teka_p = _teka_pachok(d)
    if teka_p is None or not any(teka_p.glob("batch_*.json")):
        return fail(f"у {d} немає пачок нормалізації — спершу `nysh opys read` (свій опис) чи "
                    f"`nysh opys vziaty` (з обміну)")
    try:
        res = NA.normalizuvaty(teka_p, rezhym=a.rezhym, chekaty_s=a.chekaty_hv * 60)
    except NA.ApiError as exc:
        return fail(str(exc))
    obmin = teka_p == d
    if res["bez_vidpovidi"] == 0:
        nastupne = f"nysh opys viddaty {a.dir}" if obmin else f"nysh opys push {a.dir}"
    elif res["v_roboti"]:
        nastupne = f"задача в роботі — пізніше та сама команда: nysh opys norm {a.dir} --api"
    else:
        nastupne = (f"решту пачок — агентом (batch_NNN.out.txt), тоді "
                    f"{'nysh opys viddaty' if obmin else 'nysh opys push'} {a.dir}")
    env = ok({**res, "dir": str(teka_p), "next": nastupne})
    if res["biudzhet"]:
        env.warn("api_budget", res["biudzhet"])
    for x in res["ne_hodytsia"][:10]:
        env.warn("api_bad", x)
    if res["vycherpano_sproby"]:
        env.warn("api_sproby", f"пачок, на які модель {NA.SPROB} рази дала невідповідь: "
                               f"{len(res['vycherpano_sproby'])} — їх лишено агентові")
    return env
