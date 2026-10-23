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
    """Той самий `nysh serve` з тими самими прапорцями — і без другої вкладки."""
    import shutil
    import sys
    from pathlib import Path

    head = argv[0] if argv else ""
    if head.lower().endswith(".py"):
        # `python -m nyshporka serve`: argv[0] — `__main__.py`, сам він не стартує.
        exe = [sys.executable, "-m", "nyshporka"]
    elif head and Path(head).is_file():
        exe = [head]
    elif head and Path(head + ".exe").is_file():
        exe = [head + ".exe"]
    elif shutil.which("nysh"):
        exe = [str(shutil.which("nysh"))]
    else:
        exe = [sys.executable, "-m", "nyshporka"]
    rest = list(argv[1:]) or ["serve"]
    if "serve" in rest and "--no-browser" not in rest:
        rest.append("--no-browser")
    return exe + rest


def _launch_chain(pid: int, argv0: str) -> list[int]:
    """Сервер і предки, що належать цій установці: обгортка `nysh.exe`, Python середовища.

    🔴 На Windows `nysh.exe` від uv запускає Python середовища, а той — базовий
    Python, який і слухає порт. Поки живі обгортка й Python середовища, їхні файли
    заблоковані, і `uv tool install --force` їх не замінить. Тож помічник чекає
    весь ланцюг, а не лише процес сервера.
    """
    import contextlib
    import sys
    from pathlib import Path

    out = [pid]
    try:
        import psutil
    except ImportError:
        return out
    roots = [Path(sys.prefix).resolve()]
    if argv0:
        roots.append(Path(argv0).resolve().parent)

    def ours(p: psutil.Process) -> bool:
        with contextlib.suppress(Exception):
            parts = [p.exe(), *p.cmdline()[:2]]
            for x in parts:
                rx = Path(x).resolve()
                if any(rx == r or r in rx.parents for r in roots):
                    return True
        return False

    with contextlib.suppress(Exception):
        cur = psutil.Process(pid).parent()
        while cur is not None and ours(cur) and len(out) < 6:
            out.append(cur.pid)
            cur = cur.parent()
    return out


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
    import contextlib
    import json
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from nyshporka.daemon import app as D
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
    home.mkdir(parents=True, exist_ok=True)
    relaunch = _relaunch_argv(list(D.LAUNCH.get("argv") or []))
    after: list[list[str]] = []
    try:
        from nyshporka.htr.env import venv_python
        from nyshporka.setup.doctor import engine_venv

        if venv_python(engine_venv()).is_file():
            after.append([relaunch[0], "htr", "install"] if relaunch[0].lower().endswith(("nysh", "nysh.exe"))
                         else [sys.executable, "-m", "nyshporka", "htr", "install"])
    except Exception:
        pass
    argv = list(D.LAUNCH.get("argv") or [])
    pid = int(D.LAUNCH.get("pid") or 0)
    task = {"pid": pid, "pids": _launch_chain(pid, argv[0] if argv else ""),
            "cmd": U.command(), "env": U.uv_python_env(),
            "after": after, "relaunch": relaunch, "cwd": D.LAUNCH.get("cwd") or "",
            "from": rel.installed, "to": rel.latest, "wait": 90,
            "log": str(home / "update.log"), "result": str(home / "result.json"),
            "console_log": str(home / "console.log")}
    if a.dry_run:
        return ok({"plan": {k: task[k] for k in ("cmd", "relaunch", "after", "from", "to", "log")}})
    tmp = Path(tempfile.mkdtemp(prefix="nysh-update-"))
    helper = tmp / "updater.py"
    shutil.copyfile(Path(__file__).parent / "setup" / "updater.py", helper)
    task_path = tmp / "task.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    with contextlib.suppress(OSError):
        (home / "result.json").unlink()
    base_py = getattr(sys, "_base_executable", "") or sys.executable
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED | NEW_GROUP
    subprocess.Popen([base_py, str(helper), str(task_path)], cwd=str(tmp), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=sys.platform != "win32")
    D.request_exit(1.5)
    return ok({"restarting": True, "from": rel.installed, "to": rel.latest, "log": task["log"]})
