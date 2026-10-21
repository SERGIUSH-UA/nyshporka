"""⚙️🗂 Історія простору як операції: журнал, збереження, повернення, «що змінилось».

Механізм — `core.vcs` (локальний git, який Нишпорка заводить сама). Тут — та
сама логіка для командного рядка (`nysh history …`) і для консолі: екран
«Історія» показує журнал і повертає картку тими самими викликами.

Шлях у аргументах — від кореня проєкту (`data/canonical/persons/<ID>.md`);
командний рядок віддає вже абсолютний, бо людина набирає його від своєї теки.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op


def _path(raw: str) -> Path:
    from nyshporka.core import workspace as W

    p = Path(raw)
    return p if p.is_absolute() else W.workspace().proot / p


class LogArgs(BaseModel):
    path: str = Field(default="", description="файл чи тека від кореня проєкту; "
                                              "порожньо — увесь проєктний шар")
    limit: int = Field(default=20, ge=1, le=500, description="скільки записів")


@op("history.log", summary="Журнал змін: хто й коли міняв картку, файл чи весь проєкт",
    args=LogArgs, scope="project", tier="situational",
    when="хто й коли міняв картку чи файл — перед відкатом")
def history_log(a: LogArgs) -> Envelope:
    from nyshporka.core import vcs as V
    from nyshporka.core import workspace as W

    try:
        rows = V.log(W.workspace(), _path(a.path) if a.path else None, a.limit)
    except (V.VcsError, ValueError) as exc:
        return fail(str(exc))
    return ok({"path": a.path, "rows": rows})


class SaveArgs(BaseModel):
    message: str = Field(default="Збережено вручну", description="пояснення коміту")


@op("history.save", summary="Зберегти стан канону й обліку окремим комітом",
    args=SaveArgs, mutates=True, scope="project", tier="situational",
    when="зберегти стан канону й обліку сторінок окремим комітом зі своїм поясненням")
def history_save(a: SaveArgs) -> Envelope:
    from nyshporka.core import vcs as V
    from nyshporka.core import workspace as W

    try:
        rev = V.save(W.workspace(), a.message or "Збережено вручну")
    except V.VcsError as exc:
        return fail(str(exc))
    return ok({"rev": rev, "saved": rev is not None})


class RestoreArgs(BaseModel):
    path: str = Field(description="файл чи тека від кореня проєкту")
    rev: str = Field(description="мітка коміту з журналу")


@op("history.restore", summary="Повернути файл до стану коміту — новим комітом",
    args=RestoreArgs, mutates=True, scope="project", tier="situational",
    when="агент зіпсував картку чи файл — повернути стан із історії")
def history_restore(a: RestoreArgs) -> Envelope:
    from nyshporka.core import vcs as V
    from nyshporka.core import workspace as W

    try:
        rev = V.restore(W.workspace(), _path(a.path), a.rev)
    except (V.VcsError, ValueError) as exc:
        return fail(str(exc))
    return ok({"path": a.path, "to": a.rev, "rev": rev})


class DiffArgs(BaseModel):
    path: str = Field(description="файл від кореня проєкту")
    rev: str = Field(description="мітка коміту з журналу")


@op("history.diff", summary="Що коміт змінив у файлі: поля картки «було → стало»",
    args=DiffArgs, scope="project", tier="rare",
    when="перед поверненням — що саме цей коміт змінив у картці")
def history_diff(a: DiffArgs) -> Envelope:
    from nyshporka.core import vcs as V
    from nyshporka.core import workspace as W

    try:
        return ok(V.diff(W.workspace(), _path(a.path), a.rev))
    except (V.VcsError, ValueError) as exc:
        return fail(str(exc))


class AutoArgs(BaseModel):
    on: bool | None = Field(default=None, description="ввімкнути чи вимкнути; "
                                                      "порожньо — лише показати стан")


@op("history.auto", summary="Автозбереження канону: стан, ввімкнути, вимкнути",
    args=AutoArgs, mutates=True, tier="rare",
    when="людина веде git сама — вимкнути (чи ввімкнути) автозбереження канону")
def history_auto(a: AutoArgs) -> Envelope:
    from nyshporka.core import vcs as V
    from nyshporka.core import workspace as W

    hub = W.workspace().hub
    if a.on is not None:
        V.set_auto(hub, a.on)
    top = V.repo_top(hub)
    return ok({"git": V.git_available(), "repo": top is not None,
               # Корінь репозиторію вище Майстерні — його веде людина, не ми.
               "own": top is not None and top != hub.resolve(),
               "auto": V.auto_enabled(hub)})
