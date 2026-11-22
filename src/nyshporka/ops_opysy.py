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


@op("opysy.policy", summary="Чи приймає Супряга описи цього фонду (без мережі)",
    args=PolicyArgs, section=SECTION, tier="rare",
    when="до прогону опису — щоб не читати фонд, закритий для заливки")
def opysy_policy(a: PolicyArgs) -> Envelope:
    from nyshporka.opysy import gates as G

    why = G.excluded(a.repo, a.fond)
    return ok({"repo": G.repo_code(a.repo), "fond": a.fond.strip(), "open": not why,
               "why": why})


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
