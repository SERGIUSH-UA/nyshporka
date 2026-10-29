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
from nyshporka.core.ops import NoArgs, op


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
    file: str = Field(default="", description="пакет .zvid; порожньо — наступний із черги порталу")
    id: str = Field(default="", description="з порталу: саме цей пакет (свій узятий — продовжити)")
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
    from nyshporka.zvid import helper, portal

    try:
        applied: list[int] = []
        if a.file:
            rep = helper.take(Path(a.file), fresh=a.fresh)
        else:
            from nyshporka.zvid import patch as PT

            pack_file, patch_files = portal.take(pack_id=a.id)
            rep = helper.take(pack_file, fresh=a.fresh)
            portal.mark_portal(rep.root)
            # Доповнення — і на свіжому пакеті, і на продовженні: нові голоси
            # стають рядками завдань, зведене лишається.
            for pf in patch_files:
                got = PT.apply(pf)
                if not got.skipped:
                    applied.append(got.rev)
                    rep.tasks = got.tasks or rep.tasks
    except (C.ZvidError, T.TaskError, OSError) as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "root": str(rep.root), "procedure": rep.procedure,
              "resumed": rep.resumed, "tasks": [str(f) for f in rep.tasks],
              "rows": rep.rows, "context": str(rep.root / C.CONTEXT) if rep.context else "",
              "commands": rep.commands, "patches": applied})
    if applied:
        env.warn("patched", f"застосовано доповнення пакета: r{', r'.join(map(str, applied))} — "
                            "у завданнях новий голос; зведене не змінено")
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
    no_upload: bool = Field(default=False, description="пакет із порталу, але відповідь "
                                                       "лише файлом (не заливати)")


@op("zvid.give", summary="Віддати зведене: перевірити відповіді й зібрати .answer.zvid",
    args=GiveArgs, mutates=True, section="core", tier="situational",
    skill="zvid", when="зведення пакета Зводу закінчено — віддати власникові")
def zvid_give(a: GiveArgs) -> Envelope:
    """Перевірка тут, а не в власника: агент ще поруч і може виправити."""
    import json

    from nyshporka.zvid import common as C
    from nyshporka.zvid import helper, portal

    try:
        rep = helper.give(a.id, model=a.model, agents=a.agents, note=a.note,
                          out=Path(a.out) if a.out else None, partial=a.partial)
        state = json.loads((helper.root_of(a.id) / C.STATE).read_text(encoding="utf-8"))
        uploaded = bool(state.get("portal")) and not a.no_upload
        if uploaded:
            portal.upload_answer(a.id, rep.file)
    except C.ZvidError as exc:
        return fail(str(exc))
    env = ok({"id": rep.id, "file": str(rep.file), "rows": rep.rows,
              "answered": rep.answered, "missing": rep.missing, "conf": rep.conf,
              "uploaded": uploaded})
    if rep.missing:
        env.warn("partial", f"не зведено {rep.missing} рядків з {rep.rows}"
                 + (" — решту власник викладе в чергу новим пакетом сам, drop не потрібен"
                    if uploaded else ""))
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


# ── портал ───────────────────────────────────────────────────────────────────
class PublishArgs(BaseModel):
    file: str = Field(description="пакет .zvid")
    kind: str = Field(default="", description="клас пакета; порожньо — за голосами "
                                              "(regent, pysar_x18, logofet, інакше public)")
    note: str = Field(default="", description="примітка для помічника")


@op("zvid.publish", summary="Покласти пакет Зводу в чергу порталу",
    args=PublishArgs, mutates=True, long=True, section="lab", tier="rare",
    skill="zvid", when="віддати пакет Зводу помічникам через портал, а не файлом")
def zvid_publish(a: PublishArgs) -> Envelope:
    """Байти — у сховище підписаним посиланням; сервер звіряє sha256 сам."""
    from nyshporka.zvid import common as C
    from nyshporka.zvid import portal

    try:
        got = portal.publish(Path(a.file), kind=a.kind, note=a.note)
    except (C.ZvidError, OSError) as exc:
        return fail(str(exc))
    return ok(got)


class QueueArgs(BaseModel):
    status: str = Field(default="", description="vilnyi | vzhato | povernuto | pryiniato")


@op("zvid.queue", summary="Черга Зводу на порталі: пакети, у кого, помічники",
    args=QueueArgs, section="lab", tier="rare", skill="zvid",
    when="що з пакетами Зводу на порталі: хто взяв, що повернуто")
def zvid_queue(a: QueueArgs) -> Envelope:
    from nyshporka.zvid import common as C
    from nyshporka.zvid import portal

    try:
        return ok(portal.queue(a.status))
    except C.ZvidError as exc:
        return fail(str(exc))


@op("zvid.fetch", summary="Забрати повернуті відповіді Зводу з порталу в набори",
    args=NoArgs, mutates=True, long=True, section="lab", tier="rare", skill="zvid",
    when="помічники повернули пакети Зводу через портал — прийняти всі")
def zvid_fetch(_: NoArgs) -> Envelope:
    """Кожна повернута відповідь → `collect` (ті самі ворота) → «прийнято» на порталі."""
    from nyshporka.train import sets as S
    from nyshporka.train import tasks as T
    from nyshporka.zvid import common as C
    from nyshporka.zvid import portal

    try:
        got = portal.fetch()
    except (C.ZvidError, S.SetError, T.TaskError) as exc:
        return fail(str(exc))
    env = ok({"accepted": got})
    n = sum(g["suspects"] for g in got)
    if n:
        env.warn("suspects", f"{n} рядків на очі людині: nysh train gates --set <набір> "
                             "--suspects")
    return env


class RestArgs(BaseModel):
    id: str = Field(description="id пакета, на який прийшла часткова відповідь")
    context: str = Field(default="", description="context.md, якщо його немає в книзі пакетів "
                                                 "(пакети до 0.38.6)")
    out: str = Field(default="", description="тека для .zvid решти; з --publish можна не давати")
    publish: bool = Field(default=False, description="одразу покласти решту в чергу порталу")


@op("zvid.rest", summary="Решта пакета Зводу після часткової відповіді — новим пакетом",
    args=RestArgs, mutates=True, long=True, section="lab", tier="rare", skill="zvid",
    when="помічник віддав пакет Зводу частково — незведене віддати іншому")
def zvid_rest(a: RestArgs) -> Envelope:
    """Набори з недозведеними рядками → новий пакет тієї самої серії й контрольної.

    `fetch` робить це сам після кожної часткової відповіді; руками — коли в
    книзі пакетів немає контексту або `fetch` не зміг викласти.
    """
    import tempfile

    from nyshporka.train import sets as S
    from nyshporka.zvid import common as C
    from nyshporka.zvid import owner, portal

    if not a.out and not a.publish:
        return fail("дай --out <тека> або --publish")
    try:
        with tempfile.TemporaryDirectory(prefix="zvid-rest-") as tmp:
            rep = owner.rest(a.id, out=Path(a.out or tmp),
                             context=Path(a.context) if a.context else None)
            if rep is None:
                return ok({"id": a.id, "rest": None})
            published = None
            if a.publish:
                try:
                    published = portal.publish(rep.file)
                except C.ZvidError:
                    owner.forget_rest(a.id, rep.id)
                    raise
            data = {"id": a.id, "rest": rep.id, "sets": len(rep.sets) - len(rep.control),
                    "pages": rep.pages, "file": str(rep.file) if a.out else "",
                    "published": published}
    except (C.ZvidError, S.SetError, OSError) as exc:
        return fail(str(exc))
    env = ok(data)
    if not a.publish:
        env.suggest("zvid.publish", "покласти решту в чергу порталу")
    return env


class DropArgs(BaseModel):
    id: str = Field(description="id пакета")


@op("zvid.drop", summary="Повернути взятий пакет Зводу в чергу порталу, не зводячи",
    args=DropArgs, mutates=True, section="core", tier="situational", skill="zvid",
    when="пакет Зводу не вийде довести — віддати його іншому")
def zvid_drop(a: DropArgs) -> Envelope:
    from nyshporka.zvid import common as C
    from nyshporka.zvid import portal

    try:
        return ok(portal.drop(a.id))
    except C.ZvidError as exc:
        return fail(str(exc))


# ── доповнення ───────────────────────────────────────────────────────────────
class PatchArgs(BaseModel):
    pack: str = Field(description="id пакета з книги пакетів")
    voices: str = Field(default="", description="кома-список голосів наборів, що додаються")
    hints: str = Field(default="", description="кома-список людських джерел, що додаються")
    out: str = Field(description="тека для .zvidpatch")
    note: str = Field(default="", description="примітка")
    skip_control: bool = Field(default=False, description="голоси не на контрольні набори: модель на них училась")


@op("zvid.patch", summary="Доповнення пакета Зводу: новий голос чи підказка без перепакування",
    args=PatchArgs, mutates=True, section="lab", tier="rare", skill="zvid",
    when="натренували нову модель — додати її голос до вже нарізаних пакетів")
def zvid_patch(a: PatchArgs) -> Envelope:
    """Голос — спершу в набори (`nysh train voices` / інфер по кропах), тоді сюди."""
    from nyshporka.train import sets as S
    from nyshporka.zvid import common as C
    from nyshporka.zvid import patch as PT

    try:
        rep = PT.build(a.pack, voices=_csv(a.voices), hints=_csv(a.hints), out=Path(a.out),
                       note=a.note, skip_control=a.skip_control)
    except (C.ZvidError, S.SetError, OSError) as exc:
        return fail(str(exc))
    env = ok({"pack": rep.pack, "rev": rep.rev, "file": str(rep.file), "voices": rep.voices,
              "hints": rep.hints, "sets": rep.sets, "kb": round(rep.bytes / 1024, 1)})
    env.suggest("zvid.publish", "покласти доповнення до пакета в черзі порталу")
    return env


class ApplyArgs(BaseModel):
    file: str = Field(description="доповнення .zvidpatch")


@op("zvid.apply", summary="Застосувати доповнення до взятого пакета Зводу",
    args=ApplyArgs, mutates=True, section="core", tier="situational", skill="zvid",
    when="отримав доповнення .zvidpatch до пакета Зводу файлом")
def zvid_apply(a: ApplyArgs) -> Envelope:
    from nyshporka.train import tasks as T
    from nyshporka.zvid import common as C
    from nyshporka.zvid import patch as PT

    try:
        rep = PT.apply(Path(a.file))
    except (C.ZvidError, T.TaskError, OSError) as exc:
        return fail(str(exc))
    return ok({"pack": rep.pack, "rev": rep.rev, "skipped": rep.skipped, "voices": rep.voices,
               "tasks": [str(f) for f in rep.tasks]})
