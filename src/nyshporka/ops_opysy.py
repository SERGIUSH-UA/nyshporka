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
    res = RU.build(W.run_dir(d), W.table_path(d), title_starts=a.title_starts, dobudova=a.dobudova)
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
                                                             "аркушах чи машинопис")


def _chytaty(pages: Path, run: Path, script: str) -> int:
    """`nysh read <тека>/pages --out <тека>/run` тим самим інтерпретатором: прогрес — на екран,
    як у звичайному прогоні; продовжує з місця, де читання обірвалось."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "nyshporka", "read", str(pages), "--out", str(run)]
    if script:
        cmd += ["--script", script]
    return subprocess.run(cmd, check=False).returncode


def _prochytano(d: Path) -> tuple[int, int]:
    """(сторінок, прочитано). Прочитана — є текст АБО рушій записав її в мету прогону: порожня
    чи титульна сторінка тексту може не мати, і без мети «прочитано 3 з 4» не минало б ніколи."""
    import contextlib
    import json

    from nyshporka.opysy import workdir as W

    run = W.run_dir(d)
    vsi = {p.stem for p in W.pages_dir(d).glob("*.jpg")} if W.pages_dir(d).exists() else set()
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

    if a.form != "hand_ruled":
        return fail("машинописні описи учасник поки не читає: розбір таблиці рушія друку ще "
                    "звіряється на других описах. Зараз — лише рукопис на розграфлених аркушах")
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
    if gotovi < vsi:
        rc = _chytaty(W.pages_dir(d), W.run_dir(d), a.script)
        vsi, gotovi = _prochytano(d)
        if gotovi < vsi:
            return fail(f"прочитано {gotovi} з {vsi} сторінок (код {rc}) — та сама команда "
                        f"продовжить з місця")
        kroky.append("читання")
    env = opysy_table(TableArgs(dir=a.dir))
    if not env.ok:
        return env
    tablytsia = env.data
    kroky.append("таблиця")
    env = opysy_norm(NormArgs(dir=a.dir, language=a.language))
    if not env.ok:
        return env
    from nyshporka.opysy import norm_batches as NB

    # чекають відповіді — і нарізані щойно, і ті, що лишились з попереднього запуску
    pachky = NB.bez_vidpovidi(W.norm_dir(d))
    nastupne = (f"агент нормалізує пачки в {env.data.get('dir')}, тоді "
                f"`nysh opys push {a.dir} --norm-model <модель>`; немає агента чи ресурсів — "
                f"`nysh opys push {a.dir} --na-obmin` (нормалізує обмін у Супрязі)") if pachky \
        else f"nysh opys push {a.dir}"
    return ok({"dir": str(d.resolve()), "zrobleno": kroky, "storinok": vsi,
               "sprav": tablytsia.get("cases"), "pidtverdzheno_nomeriv": tablytsia.get("confirmed"),
               "pachok_normalizatsii": len(pachky),
               "novykh_pachok": len(env.data.get("batches") or []),
               "norm_dir": env.data.get("dir"), "how": env.data.get("how"), "next": nastupne})


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
    model: str = Field(description="модель, що нормалізувала (назва моделі агента)")
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
    vidp, gotovi, bad = OB.vidpovidi(d)
    if not vidp:
        env = fail("немає нових відповідей — агент кладе batch_NNN.out.txt поруч із пачкою")
        for b in bad:
            env.warn("norm_bad", b, level=ALERT)
        return env
    pidsumok: dict[str, Any] = {"pryiniato": 0, "porozhni": 0, "avtora": 0, "poznachky": []}
    for i in range(0, len(vidp), 500):
        env = _remote(R.obmin_viddaty, int(z["obmin"]), model=a.model,
                      vidpovidi=vidp[i:i + 500], base=a.base)
        if not env.ok:
            return env
        for k in ("pryiniato", "porozhni", "avtora"):
            pidsumok[k] += int(env.data.get(k) or 0)
        pidsumok["poznachky"] += env.data.get("poznachky") or []
        pidsumok.update({k: env.data.get(k) for k in ("stan", "normalizovano", "spravy")})
    OB.poznachyty(d, gotovi)
    env = ok({**pidsumok, "shyfra": z.get("shyfra"), "pachok_bez_vidpovidi": OB.bez_vidpovidi(d)})
    for b in bad:
        env.warn("norm_bad", b, level=ALERT)
    return env
