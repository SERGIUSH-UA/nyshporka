"""📜 Операції Зводу — пакет розмітки рядків для іншої машини.

Два боки з різними секціями. `pack` і `collect` — власник наборів, секція
`lab`. `take`, `status`, `give` — помічник, секція `core`: він може не мати
лабораторії у своєму профілі й навіть свого простору (легка установка лише
заради Зводу), і відмова «секція вимкнена» читалась би як поламаний пакет.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


class PackArgs(BaseModel):
    sets: str = Field(description="кома-список наборів для зведення")
    out: str = Field(description="тека, куди покласти .zvid")
    procedure: str = Field(default="arbiter",
                           description="arbiter — обрати між голосами; crop-read — читати "
                                       "кожен рядок по кропу з людським джерелом поруч")
    context: str = Field(default="", description="context.md: справа, рука, правопис, причт")
    control: str = Field(default="", description="кома-список контрольних наборів (уже "
                                                 "звірених) — з них рахується CER помічника")
    pages_per_file: int = Field(default=1, description="сторінок на файл-завдання")
    note: str = Field(default="", description="примітка до пакета")


@op("zvid.pack", summary="Спакувати набори в пакет Зводу для зведення на іншій машині",
    args=PackArgs, mutates=True, long=True, section="lab", tier="rare",
    skill="zvid", when="віддати зведення рядків набору на іншу машину чи іншій людині")
def zvid_pack(a: PackArgs) -> Envelope:
    """Набори → `.zvid`: кропи, сторінки, голоси, людські джерела, контекст.

    🔴 Набір `private` не пакується. Контрольні набори йдуть під такими самими
    безликими іменами, як робочі, і в набір їхня відповідь не імпортується.
    """
    from nyshporka.train import sets as S
    from nyshporka.zvid import common as C
    from nyshporka.zvid import owner

    try:
        rep = owner.build(_csv(a.sets), out=Path(a.out), procedure=a.procedure,
                          context=Path(a.context) if a.context else None,
                          control=_csv(a.control), pages_per_file=a.pages_per_file,
                          note=a.note)
    except (C.ZvidError, S.SetError, OSError) as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "file": str(rep.file), "ledger": str(rep.ledger),
              "sets": rep.sets, "control": rep.control, "pages": rep.pages,
              "crops": rep.crops, "mb": round(rep.bytes / 2**20, 1)})
    for w in rep.warnings:
        env.warn("pack", w)
    env.suggest("zvid.collect", "коли помічник поверне .answer.zvid — прийняти")
    return env


class TakeArgs(BaseModel):
    file: str = Field(description="пакет .zvid")
    fresh: bool = Field(default=False, description="розпакувати наново, ЗАТЕРТИ зведене")


@op("zvid.take", summary="Взяти пакет Зводу: розпакувати в пісочницю й зробити завдання",
    args=TakeArgs, mutates=True, section="core", tier="situational",
    skill="zvid", when="отримав пакет .zvid — розмітити рядки для іншого дослідника")
def zvid_take(a: TakeArgs) -> Envelope:
    """Пакет → окремий простір-пісочниця; завдання будуються тут, локально.

    Повторний виклик — продовження: зведене в `tasks/` не чіпається.
    """
    from nyshporka.train import tasks as T
    from nyshporka.zvid import common as C
    from nyshporka.zvid import helper

    try:
        rep = helper.take(Path(a.file), fresh=a.fresh)
    except (C.ZvidError, T.TaskError, OSError) as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "root": str(rep.root), "procedure": rep.procedure,
              "resumed": rep.resumed, "tasks": [str(f) for f in rep.tasks],
              "rows": rep.rows, "context": str(rep.root / C.CONTEXT) if rep.context else "",
              "commands": rep.commands})
    for w in rep.warnings:
        env.warn("take", w)
    if not rep.context:
        env.warn("no_context", "у пакеті немає context.md — спитай власника про справу")
    env.suggest("zvid.status", "скільки рядків уже зведено")
    return env


class StatusArgs(BaseModel):
    id: str = Field(default="", description="id пакета; порожньо — усі взяті")


@op("zvid.status", summary="Стан взятих пакетів Зводу: рядків у завданнях, зведено",
    args=StatusArgs, section="core", tier="situational",
    skill="zvid", when="що вже зведено в пакеті Зводу, продовжити після обриву")
def zvid_status(a: StatusArgs) -> Envelope:
    from nyshporka.zvid import common as C
    from nyshporka.zvid import helper

    try:
        packs = helper.status(a.id)
    except C.ZvidError as exc:
        return fail(str(exc))
    return ok({"packs": packs, "base": str(C.base_dir())})


class GiveArgs(BaseModel):
    id: str = Field(description="id пакета")
    model: str = Field(description="модель, що зводила (напр. claude-opus-5-5)")
    agents: int = Field(default=0, description="скільки агентів працювало паралельно")
    note: str = Field(default="", description="примітка власникові")
    out: str = Field(default="", description="тека для .answer.zvid; порожньо — пісочниця")
    partial: bool = Field(default=False, description="віддати, хоч зведено не все")


@op("zvid.give", summary="Віддати зведене: перевірити відповіді й зібрати .answer.zvid",
    args=GiveArgs, mutates=True, section="core", tier="situational",
    skill="zvid", when="зведення пакета Зводу закінчено — віддати власникові")
def zvid_give(a: GiveArgs) -> Envelope:
    """Перевірка тут, а не в власника: агент ще поруч і може виправити."""
    from nyshporka.zvid import common as C
    from nyshporka.zvid import helper

    try:
        rep = helper.give(a.id, model=a.model, agents=a.agents, note=a.note,
                          out=Path(a.out) if a.out else None, partial=a.partial)
    except C.ZvidError as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "file": str(rep.file), "rows": rep.rows,
              "answered": rep.answered, "missing": rep.missing, "conf": rep.conf})
    if rep.missing:
        env.warn("partial", f"не зведено {rep.missing} рядків з {rep.rows}")
    return env


class CollectArgs(BaseModel):
    file: str = Field(description="відповідь .answer.zvid")


@op("zvid.collect", summary="Прийняти відповідь Зводу: у злиття наборів через ворота",
    args=CollectArgs, mutates=True, section="lab", tier="rare",
    skill="zvid", when="помічник повернув .answer.zvid — прийняти зведене")
def zvid_collect(a: CollectArgs) -> Envelope:
    """Робочі набори — у `drafts/merge` воротами; контрольні — лише замір CER."""
    from nyshporka.train import sets as S
    from nyshporka.train import tasks as T
    from nyshporka.zvid import common as C
    from nyshporka.zvid import owner

    try:
        rep = owner.collect(Path(a.file))
    except (C.ZvidError, S.SetError, T.TaskError) as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "model": rep.model, "imported": rep.imported,
              "control": rep.control, "refused": rep.refused})
    for w in rep.warnings:
        env.warn("gate", w)
    for r in rep.refused:
        env.warn("refused", r)
    n_susp = sum(v["suspects"] for v in rep.imported.values())
    if n_susp:
        env.warn("suspects", f"{n_susp} рядків на очі людині: nysh train gates --set <набір> "
                             "--suspects")
    return env
