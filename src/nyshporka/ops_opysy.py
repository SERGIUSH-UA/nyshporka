"""📑 Операції описів фондів: перевірити робочу теку, спакувати `.nyshopys`.

🔴 Цей модуль реєструє операції лише тоді, коли його імпортують, а імпортує
його `nyshporka.ops` тільки з увімкненим флагом `NYSH_OPYSY`
(`nyshporka.features`). Без флагу операцій описів немає ні в `nysh ops`, ні
в MCP, ні в браузері.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

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
    file: str = Field(description="пакет .nyshopys (`nysh opys pack`)")
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


@op("opysy.check", summary="Перевірити робочу теку опису воротами Супряги, нічого не пакуючи",
    args=CheckArgs, section=SECTION, tier="rare",
    when="перед пакуванням опису — що не пройде і що лише позначиться")
def opysy_check(a: CheckArgs) -> Envelope:
    from nyshporka.opysy import bundle as B
    from nyshporka.opysy import gates as G

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
    when="віддати прочитаний опис фонду в Супрягу (поки — лише пакет)")
def opysy_pack(a: PackArgs) -> Envelope:
    from nyshporka import __version__
    from nyshporka.opysy import bundle as B

    work = Path(a.dir)
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
    from nyshporka.opysy import remote as R
    from nyshporka.share.upload import UploadError

    try:
        got = R.push(Path(a.file), base=a.base)
    except (UploadError, OSError) as exc:
        env = fail(str(exc))
        for d in getattr(exc, "details", None) or []:
            env.warn(str(d.get("rule") or "refusal"), str(d.get("text") or ""), level=ALERT)
        return env
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
    res = RU.build(W.run_dir(d), W.table_path(d), title_starts=a.title_starts)
    return ok({**res, "file": str(W.table_path(d)), "next": f"nysh opys norm {a.dir}"})


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
