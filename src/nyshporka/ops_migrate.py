"""⚙️🧭 Міграція агента між версіями: що змінилось, де застаріле знання, що зробити.

🔴 Перевірки кроків — живі: статус каже не «позначено виконаним», а «зараз
зелене». Позначка `migrate.done` лише гасить нагадування; наступний
`migrate.status` однаково перевірить усе наново.

`agent=False` — стартовий перелік тримається коротким, а нагадування про
міграцію агент і так отримує від `workspace.info` і дашборда.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import NoArgs, op


def _root() -> Path:
    from nyshporka.core.workspace import workspace

    return workspace().root


@op("migrate.status", summary="Які міграції агента ще не пройдено і що з кроками зараз",
    mutates=False, agent=False, gui=False, section="core")
def migrate_status(_a: NoArgs) -> Envelope:
    from nyshporka import __version__
    from nyshporka import migrate as M

    root = _root()
    todo = M.pending(root, __version__)
    out = []
    for m in todo:
        steps = []
        for s in m.steps:
            res = M.run_check(s.check, root) if s.check else M.CheckResult("n/a")
            steps.append({"id": s.id, "do": s.do, "human": s.human, **res.as_dict()})
        out.append({"version": m.version, "title": m.title, "steps": steps})
    env = ok({"package": __version__, "pending": out,
              "done": M.record(root).get("done") or []})
    if todo:
        env.warn("agent_migration", f"простір не мігровано до {todo[-1].version}: "
                                    f"прочитати `nysh migrate --show {todo[-1].version}`, "
                                    f"пройти кроки, `nysh migrate --done`")
    return env


class ScanArgs(BaseModel):
    paths: list[str] = Field(default_factory=list,
                             description="теки чи файли; порожньо — пам'ять агента, CLAUDE.md, правлені скіли")
    version: str = Field(default="", description="лише тези цієї міграції; порожньо — усіх")


@op("migrate.scan", summary="Знайти застарілі тези в пам'яті й нотатках агента",
    args=ScanArgs, mutates=False, agent=False, gui=False, section="core")
def migrate_scan(a: ScanArgs) -> Envelope:
    """Кожен рядок — файл, номер рядка, теза і що правда тепер.

    🔴 Виправляти начисто: правильне на місце хибного, без «було → стало».
    Нотатка з історією змін читається як дві правди, і наступна сесія бере
    першу.
    """
    from nyshporka import migrate as M

    root = _root()
    migs = M.load_all()
    if a.version:
        migs = [m for m in migs if M.version_key(m.version) == M.version_key(a.version)]
        if not migs:
            return fail(f"міграції {a.version} немає")
    paths = [Path(p).expanduser() for p in a.paths] or M.default_scan_paths(root)
    hits = M.scan(paths, migs)
    env = ok({"scanned": [str(p) for p in paths], "hits": [h.as_dict() for h in hits]})
    if not paths:
        env.warn("nothing_scanned", "не знайдено жодної теки пам'яті чи нотаток — "
                                    "назвіть їх явно (--scan <тека>)")
    return env


class DoneArgs(BaseModel):
    version: str = Field(default="", description="версія міграції; порожньо — усі непройдені")


@op("migrate.done", summary="Позначити міграцію агента пройденою в цьому просторі",
    args=DoneArgs, mutates=True, agent=False, gui=False, section="core")
def migrate_done(a: DoneArgs) -> Envelope:
    from nyshporka import __version__
    from nyshporka import migrate as M

    root = _root()
    todo = M.pending(root, __version__)
    if a.version:
        todo = [m for m in todo if M.version_key(m.version) == M.version_key(a.version)]
        if not todo:
            return fail(f"міграції {a.version} серед непройдених немає")
    added = M.mark_done(root, [m.version for m in todo])
    env = ok({"marked": added})
    open_steps = [f"{m.version}/{s.id}" for m in todo for s in m.steps
                  if s.check and M.run_check(s.check, root).state == "todo"]
    if open_steps:
        env.warn("steps_open", f"позначено, але кроки ще не зелені: {', '.join(open_steps)} — "
                               f"якщо пропущено свідомо з людиною, це нормально")
    return env
