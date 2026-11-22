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
