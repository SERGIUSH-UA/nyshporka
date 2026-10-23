"""🔔 Операції дзвіночка: нова версія, нові моделі, сповіщення Супряги, вимикачі мережі.

Логіка — у `setup/notices.py`; тут лише конверти для консолі й агента.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from nyshporka.core.envelope import Envelope, fail, ok
from nyshporka.core.ops import op

#: Мови консолі, якими портал віддає тексти (решта — основна).
LANGS = ("uk", "en", "pl", "ro", "fr", "de", "ru")


def _lang(v: str) -> str:
    v = (v or "").strip().lower()
    return v if v in LANGS else "uk"


class NetSettingsArgs(BaseModel):
    updates: bool | None = Field(default=None, description="фонова перевірка нової версії "
                                                           "(pypi.org і примітки на порталі)")
    supriaha: bool | None = Field(default=None, description="сповіщення кабінету Супряги "
                                                            "в консолі (з ключем Супряги)")

    def only_shows(self) -> bool:
        return self.updates is None and self.supriaha is None


@op("settings.net", summary="Вимикачі мережі консолі: перевірка оновлень і сповіщення Супряги",
    args=NetSettingsArgs, mutates=True, section="core",
    when="увімкнути чи вимкнути фонову перевірку оновлень і сповіщення Супряги")
def settings_net(a: NetSettingsArgs) -> Envelope:
    """Типово обидва вимкнені: фонової активності в мережі немає (PRIVACY.md)."""
    from nyshporka.setup import notices as N

    # 🔴 Вхід перевіряється тут, у мить, коли людина вмикає сповіщення, а не
    # заздалегідь у `snapshot`: той сховища ключів не питає, поки сповіщення
    # вимкнені, тож консоль не знала про вхід і тримала галочку неактивною —
    # увімкнути сповіщення було неможливо взагалі (дослідник, 23.10.2026).
    if a.supriaha and not N.logged_in():
        return fail("щоб отримувати сповіщення Супряги, спершу увійдіть: nysh share login")
    got = N.set_settings(updates=a.updates, supriaha=a.supriaha)
    return ok({**got, "logged_in": N.logged_in()})


class NoticesStateArgs(BaseModel):
    lang: str = Field(default="uk", description="мова текстів з порталу")


@op("notices.state", summary="Що нового: версія, моделі, сповіщення Супряги (з пам'яті)",
    args=NoticesStateArgs, mutates=False, section="core",
    when="чи вийшла нова версія, нові моделі чи є сповіщення Супряги")
def notices_state(a: NoticesStateArgs) -> Envelope:
    """Без мережі: показує збережене. Якщо людина ввімкнула фонову перевірку і
    настав час — запускає її у фоні й не чекає; наступний виклик покаже свіже."""
    from nyshporka.setup import notices as N

    started = N.refresh_later(_lang(a.lang))
    return ok({**N.snapshot(), "refreshing": started or N.refreshing()})


@op("notices.check", summary="Перевірити зараз: нова версія й сповіщення Супряги",
    args=NoticesStateArgs, mutates=True, section="core",
    when="перевірити оновлення й сповіщення зараз")
def notices_check(a: NoticesStateArgs) -> Envelope:
    """Явна дія людини — іде й з вимкненою фоновою перевіркою."""
    from nyshporka.setup import notices as N

    N.refresh(force=True, lang=_lang(a.lang))
    env = ok(N.snapshot())
    for code, text in (env.data.get("why") or {}).items():
        env.warn(code, f"не все вдалося спитати: {text}")
    return env


class NoticesReadArgs(BaseModel):
    ids: list[int] | None = Field(default=None, description="які сповіщення; порожньо — усі")
    lang: str = Field(default="uk")


@op("notices.read", summary="Позначити сповіщення Супряги прочитаними",
    args=NoticesReadArgs, mutates=True, section="core", private=True,
    when="позначити сповіщення Супряги прочитаними")
def notices_read(a: NoticesReadArgs) -> Envelope:
    from nyshporka.setup import notices as N

    if not N.settings()["supriaha"]:
        return fail("сповіщення Супряги в консолі вимкнені (Налаштування → Мережа)")
    if not N.logged_in():
        return fail("на цій машині не виконано вхід у Супрягу — сповіщень немає")
    try:
        sup = N.mark_read(a.ids, _lang(a.lang))
    except Exception as exc:
        return fail(f"портал не прийняв позначку: {type(exc).__name__}: {exc}")
    return ok({"supriaha": sup})


class ModelsGetArgs(BaseModel):
    ids: list[str] | None = Field(default=None, description="id паків; порожньо — усі, яких бракує")


@op("models.get", summary="Завантажити моделі, яких бракує (sha256 звіряється)",
    args=ModelsGetArgs, mutates=True, long=True, section="core",
    when="завантажити нові моделі читання")
def models_get(a: ModelsGetArgs) -> Envelope:
    """Те саме, що `nysh models get`: ваги з релізу, звірка sha256 завжди."""
    from nyshporka.core import progress
    from nyshporka.setup import packs

    known = [p for p in packs.catalog() if p.kind == "model" and not p.superseded]
    want = [p for p in known if (not a.ids or p.id in a.ids) and not packs.verify(p)]
    if not want:
        return ok({"got": [], "failed": [], "note": "усе на місці"})
    got: list[str] = []
    failed: list[dict[str, str]] = []
    for i, p in enumerate(want):
        progress.report(i, len(want), p.label or p.id)
        try:
            packs.fetch(p)
            got.append(p.id)
        except Exception as exc:
            failed.append({"id": p.id, "why": f"{type(exc).__name__}: {exc}"[:200]})
    progress.report(len(want), len(want), "")
    env = ok({"got": got, "failed": failed})
    for f in failed:
        env.warn("model_failed", f"{f['id']}: {f['why']}")
    return env


class UpdateApplyArgs(BaseModel):
    dry_run: bool = Field(default=False, description="лише показати план: що поставиться і як")

    def only_shows(self) -> bool:
        return self.dry_run


def _relaunch_argv(argv: list[str]) -> list[str]:
    """Перенесено в `daemon/restart.py` (спільне з переносом роду в проєкт)."""
    from nyshporka.daemon.restart import relaunch_argv

    return relaunch_argv(argv)


@op("update.apply", summary="Оновити застосунок одним натиском (консоль перезапуститься)",
    args=UpdateApplyArgs, mutates=True, section="core",
    when="оновити Нишпорку з консолі одним натиском")
def update_apply(a: UpdateApplyArgs) -> Envelope:
    """⬆️ Оновлення з консолі: помічник чекає, доки консоль закриється, оновлює й
    відкриває її знову.

    🔴 Лише для установки інструментом uv (`.exe`-майстер, `uv tool install`):
    там середовище оновлюється однією командою, а базовий інтерпретатор, яким
    іде помічник, оновлення не чіпає. Редагована (розробницька) і pip-установка
    оновлюються своїм способом — для них тут команда, а не кнопка.

    Поза консоллю (агент, термінал) — `nysh update`: та сама перевірка й
    команда, лише при закритій консолі.
    """
    import sys
    import tempfile
    from pathlib import Path

    from nyshporka.daemon import app as D
    from nyshporka.daemon import restart as RS
    from nyshporka.setup import update as U

    if not U.tool_env():
        return fail("оновлення одним натиском — лише для установки майстром або «uv tool "
                    "install»; цю установку оновлюють так: " + U.how_to_update())
    if not D.LAUNCH:
        return fail("оновлення одним натиском — лише з консолі (nysh serve); "
                    "у терміналі — «nysh update»")
    busy = D.running_jobs()
    if busy:
        return fail(f"зараз іде робіт: {busy} — консоль перезапуститься, тож спершу "
                    f"дочекайтесь їх або зупиніть")
    rel = U.latest()
    if not rel.known:
        return fail(f"не вдалося дізнатись, що вийшло: {rel.why}")
    if not rel.newer:
        return ok({"latest": True, "installed": rel.installed, "to": rel.latest})
    from nyshporka.core.workspace import _state_path

    home = (_state_path() or Path(tempfile.gettempdir()) / "state.json").parent / "update"
    relaunch = RS.relaunch_argv(list(D.LAUNCH.get("argv") or []))
    after: list[list[str]] = []
    try:
        from nyshporka.htr.env import venv_python
        from nyshporka.setup.doctor import engine_venv

        if venv_python(engine_venv()).is_file():
            after.append([relaunch[0], "htr", "install"] if relaunch[0].lower().endswith(("nysh", "nysh.exe"))
                         else [sys.executable, "-m", "nyshporka", "htr", "install"])
    except Exception:
        pass
    task = RS.task_for(U.command(), home, env=U.uv_python_env(), after=after,
                       title=f"оновлення {rel.installed} → {rel.latest}",
                       extra={"from": rel.installed, "to": rel.latest})
    if a.dry_run:
        return ok({"plan": {k: task[k] for k in ("cmd", "relaunch", "after", "from", "to", "log")}})
    RS.run_after_exit(task)
    return ok({"restarting": True, "from": rel.installed, "to": rel.latest, "log": task["log"]})
