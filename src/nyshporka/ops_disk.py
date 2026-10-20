"""💽 Операції місця на диску: звіт, чистка відтворюваного, зняття кадрів справи.

Агент на питання «що видалити» мусить кликати це, а не перелічувати теки з
розмірами: незамінне від відтворюваного за назвою теки не відрізнити.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


class DiskReportArgs(BaseModel):
    full: bool = Field(default=False, description="рахувати й розмір прочитаного "
                                                  "(reports/htr) — обхід мільйонів файлів, "
                                                  "десятки хвилин")


@op("disk.report", summary="Місце простору: що лишити, що відтворюване, з яких справ "
                           "можна зняти кадри",
    args=DiskReportArgs,
    next_hints=(("disk.clean", "прибрати відтворюване"),
                ("disk.offload", "зняти кадри прочитаної й відданої справи")),
    when="місце на диску: скільки зайнято, що відтворюване, що можна зняти")
def disk_report(a: DiskReportArgs) -> Envelope:
    from nyshporka import disk as D

    env = ok(D.report(full=a.full))
    if env.data["live_runs"] is None:
        env.warn("live_runs", "стан хмарних заходів не прочитався — хмарні теки чистка "
                 "не чіпатиме")
    elif env.data["live_runs"]:
        env.warn("live_runs", "живі хмарні заходи: " + ", ".join(env.data["live_runs"][:5])
                 + " — хмарні теки чистка не чіпатиме, доки їх не заберуть")
    return env


class DiskCleanArgs(BaseModel):
    apply: bool = Field(default=False, description="справді видалити; без цього — лише "
                                                   "перелік того, що піде")


@op("disk.clean", summary="Прибрати відтворюване: стиснуті кадри й асети хмари, "
                          "тимчасове, власні пакети outbox",
    args=DiskCleanArgs, mutates=True,
    when="бракує місця — прибрати відтворюване: стиснуті кадри, тимчасове")
def disk_clean(a: DiskCleanArgs) -> Envelope:
    from nyshporka import disk as D

    env = ok(D.clean(apply=a.apply))
    for k in env.data["kept"]:
        env.warn("kept", f"{k['path']}: {k['why']}")
    for e in env.data["errors"]:
        env.warn("not_removed", f"{e['path']}: {e['error']}")
    if not a.apply and env.data["remove"]:
        env.suggest("disk.clean", "те саме з apply — справді видалити")
    return env


class DiskOffloadArgs(BaseModel):
    case: str = Field(description="тека справи (або шифра, якщо тека в неї одна)")
    restore: str = Field(description="де лежить копія кадрів: «зовнішній диск X, тека …», "
                                     "посилання на FamilySearch тощо")
    apply: bool = Field(default=False, description="справді зняти; без цього — лише "
                                                   "що й скільки")


@op("disk.offload", summary="Зняти з диска прочитані кадри справи: паспорт і адреса "
                            "копії лишаються",
    args=DiskOffloadArgs, mutates=True,
    when="зняти з диска кадри прочитаної справи; паспорт і адреса копії лишаються")
def disk_offload(a: DiskOffloadArgs) -> Envelope:
    from nyshporka import disk as D

    try:
        got = D.offload(a.case, restore=a.restore, apply=a.apply)
    except D.DiskError as exc:
        return fail(str(exc))
    env = ok(got)
    if got["unread_kept_n"]:
        env.warn("unread_kept", f"{got['unread_kept_n']} кадрів не прочитано власним прогоном "
                 f"цієї теки — вони лишаються: {', '.join(got['unread_kept'][:5])}")
    if got["changed_after_read"]:
        env.warn("changed_after_read", "кадри змінено після прочитання — лишаються, їх варто "
                 "перечитати: " + ", ".join(got["changed_after_read"][:5]))
    for e in got["errors"]:
        env.warn("not_removed", f"{e['path']}: {e['error']}")
    if not a.apply:
        env.suggest("disk.offload", "те саме з apply — справді зняти")
    return env
