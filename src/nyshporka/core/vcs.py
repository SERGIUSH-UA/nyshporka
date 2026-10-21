"""🗂 Історія простору: локальний git, який Нишпорка заводить і веде сама.

Канон правлять агенти файлами. Без історії зіпсовану картку нема чим
повернути, а хук перед комітом, що не пропускає зламаний канон, без комітів не
спрацьовує ніколи. На порталі людей просять поставити git, але до GitHub його
підключає мало хто — тож репозиторій тут **локальний**, без remote.

Межі:

- **Наявний репозиторій не чіпаємо.** Простір, який людина вже веде в git
  (свої коміти, свій `.gitignore`), лишається її: ні `.gitignore`, ні
  автозбереження. Лише хук канону — його й так ставлять руками.
- **Автозбереження** (`[history] auto = true` у маркері) — тільки в
  репозиторії, який завела Нишпорка. Зберігається проєктний шар і облік
  сторінок точним pathspec: чуже застейджене не захоплюється, а зламаний
  канон не проходить хук — збереження відмовляє, а не комітить мовчки.
- **Збереження ніколи не валить команду**, що його викликала: це страховка,
  а не умова (`autosave` повертає причину відмови для попередження).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from nyshporka.core import workspace as W

#: Таблиця маркера Майстерні з налаштуваннями історії.
TABLE = "history"
AUTHOR = ("Нишпорка", "nyshporka@localhost")


class VcsError(RuntimeError):
    """Git не зробив, що просили, — з його поясненням."""


def git_available() -> bool:
    return shutil.which("git") is not None


def _git(root: Path, *args: str, check: bool = True, stdin: bytes | None = None) -> str:
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root,
                             capture_output=True, timeout=120, input=stdin)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VcsError(f"git недоступний: {exc}") from exc
    if check and out.returncode != 0:
        err = out.stderr.decode("utf-8", errors="replace").strip()
        raise VcsError(f"git {args[0] if args else ''} (код {out.returncode}): "
                       f"{err[:600] or 'без пояснення'}")
    return out.stdout.decode("utf-8", errors="replace")


def repo_top(path: Path) -> Path | None:
    """Корінь git-репозиторію, у якому лежить `path`, або `None`."""
    if not git_available() or not path.exists():
        return None
    try:
        top = _git(path, "rev-parse", "--show-toplevel").strip()
    except VcsError:
        return None
    return Path(top).resolve() if top else None


def is_repo(hub: Path) -> bool:
    """Чи сам корінь — git-репозиторій (а не тека всередині чужого)."""
    top = repo_top(hub)
    return top is not None and top == hub.resolve()


def auto_enabled(hub: Path) -> bool:
    cfg = W._read_toml(hub / W.MARKER).get(TABLE) or {}
    return bool(cfg.get("auto")) if isinstance(cfg, dict) else False


def _set_auto(hub: Path) -> None:
    marker = hub / W.MARKER
    text = marker.read_text(encoding="utf-8")
    if f"[{TABLE}]" not in text:
        text = (text.rstrip("\n") + "\n\n# Історія простору (`nysh history`): локальний git,\n"
                "# який завела Нишпорка; зберігає канон і облік сторінок сама.\n"
                f"[{TABLE}]\n")
    text = W._marker_set(text, "auto", "auto = true", TABLE)
    W._write_marker(marker, text)


def gitignore_template() -> str:
    from nyshporka.project import _tmpl

    return _tmpl("gitignore.tmpl")


#: Змінна середовища, що вимикає заведення історії (тести, власний git людини).
NO_HISTORY_ENV = "NYSHPORKA_NO_HISTORY"


def set_auto(hub: Path, on: bool) -> None:
    """Перемкнути автозбереження: людина, що веде git сама, вимикає його тут."""
    if on:
        _set_auto(hub)
        return
    marker = hub / W.MARKER
    text = marker.read_text(encoding="utf-8")
    if f"[{TABLE}]" in text:
        W._write_marker(marker, W._marker_set(text, "auto", "auto = false", TABLE))


@dataclass
class Report:
    root: str
    git: bool = True
    created: bool = False
    inside: str = ""                    # простір лежить усередині чужого репозиторію
    gitignore: bool = False
    hook: str = ""
    commit: str = ""
    auto: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


NO_GIT = ("git не встановлено — історії канону не буде (зіпсовану картку нічим "
          "повернути). Поставте git (git-scm.com, як радить інструкція порталу) і "
          "виконайте `nysh history setup`")


def ensure_repo(hub: Path) -> Report:
    """Завести історію простору — ідемпотентно й не чіпаючи чужого."""
    from nyshporka.canon import hook as H

    rep = Report(root=str(hub))
    if not git_available():
        rep.git = False
        rep.notes.append(NO_GIT)
        return rep
    top = repo_top(hub)
    if top is not None and top != hub.resolve():
        rep.inside = str(top)
        rep.notes.append(f"простір лежить усередині репозиторію {top} — історію веде він; "
                         "окремого не заводжу")
        return rep
    if top is None:
        _git(hub, "init", "-q")
        rep.created = True
    for key, val in (("user.name", AUTHOR[0]), ("user.email", AUTHOR[1]),
                     ("core.quotepath", "false"), ("core.longpaths", "true")):
        if not _git(hub, "config", "--local", "--get", key, check=False).strip():
            _git(hub, "config", "--local", key, val)
    gi = hub / ".gitignore"
    if rep.created and not gi.exists():
        gi.write_text(gitignore_template(), encoding="utf-8", newline="\n")
        rep.gitignore = True
    if rep.created:
        # Перший коміт знімає стан як є — ДО хука: хук стереже наступні зміни,
        # а давня помилка в каноні не має зривати саме заведення історії.
        _set_auto(hub)
        _git(hub, "add", "-A")
        _git(hub, "commit", "-q", "-m", "Простір заведено (nysh history setup)",
             "--allow-empty")
        rep.commit = _git(hub, "rev-parse", "--short", "HEAD").strip()
    try:
        rep.hook = str(H.install(hub))
    except H.HookError as exc:
        rep.notes.append(f"хук канону не поставлено: {exc}")
    rep.auto = auto_enabled(hub)
    return rep


def _layer(ws: W.Workspace) -> list[Path]:
    """Що зберігає автозбереження: проєктний шар і облік сторінок."""
    out = [ws.marker, ws.pages, ws.cases, ws.citations]
    if not (ws.hub_only and ws.project is None):
        out += [ws.canonical, ws.config, ws.views, ws.clan_hunt, ws.candidates]
        rep = ws.reports
        if rep.is_dir():
            out += [c for c in rep.iterdir() if c.name != "htr"]
    return out


def save(ws: W.Workspace, message: str, paths: list[Path] | None = None) -> str | None:
    """Коміт проєктного шару (або `paths`). Нічого не змінилось — `None`."""
    hub = ws.hub
    top = repo_top(hub)
    if top is None:
        raise VcsError("простір не в git — `nysh history setup`")
    rels = []
    for p in paths if paths is not None else _layer(ws):
        if p.exists():
            try:
                rels.append(p.resolve().relative_to(top).as_posix())
            except ValueError:
                continue
    if not rels:
        return None
    _git(top, "add", "-A", "--", *rels)
    # Комітимо рівно застейджене в цих шляхах, переліком файлів: тека без
    # жодного відстеженого файла (`data/pages` свіжого простору) у pathspec
    # коміту — помилка git, а чуже застейджене поза шляхами лишається людині.
    staged = _git(top, "diff", "--cached", "--name-only", "-z", "--", *rels)
    if not staged.strip("\0"):
        return None
    _git(top, "--literal-pathspecs", "commit", "-q", "-m", message,
         "--pathspec-from-file=-", "--pathspec-file-nul", stdin=staged.encode("utf-8"))
    return _git(top, "rev-parse", "--short", "HEAD").strip()


def autosave(message: str) -> str | None:
    """Зберегти, якщо в просторі ввімкнено автозбереження. Повертає причину відмови.

    Тиха страховка для операцій, що пишуть канон чи облік: збій тут не валить
    саму операцію — виклик лише показує попередження.
    """
    try:
        ws = W.workspace()
    except W.WorkspaceError:
        return None
    if ws.readonly or not auto_enabled(ws.hub) or not git_available():
        return None
    try:
        save(ws, message)
    except VcsError as exc:
        return f"історію не збережено: {exc}"
    return None


def log(ws: W.Workspace, path: Path, limit: int = 20) -> list[dict[str, str]]:
    top = repo_top(ws.hub)
    if top is None:
        raise VcsError("простір не в git — `nysh history setup`")
    rel = path.resolve().relative_to(top).as_posix()
    raw = _git(top, "log", f"-n{limit}", "--follow", "--date=short",
               "--format=%h%x09%ad%x09%s", "--", rel)
    out = []
    for line in raw.splitlines():
        rev, day, subj = [*line.split("\t", 2), "", ""][:3]
        out.append({"rev": rev, "date": day, "subject": subj})
    return out


def restore(ws: W.Workspace, path: Path, rev: str) -> str | None:
    """Повернути файл чи теку до стану `rev` — і зберегти це як новий коміт."""
    top = repo_top(ws.hub)
    if top is None:
        raise VcsError("простір не в git — `nysh history setup`")
    rel = path.resolve().relative_to(top).as_posix()
    _git(top, "checkout", rev, "--", rel)
    return save(ws, f"Повернуто {rel} до {rev}", paths=[path])


def autosave_env(env: object, message: str) -> None:
    """`autosave` для операції: причину відмови — попередженням у відповідь."""
    reason = autosave(message)
    if reason and hasattr(env, "warn"):
        env.warn("history", reason)
