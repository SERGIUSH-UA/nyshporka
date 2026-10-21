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

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

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


#: Мітка коміту: лише шістнадцяткова. Рядок на кшталт `--output=…` git прочитав
#: би як ключ — а мітка приходить і з браузера.
_REV = re.compile(r"[0-9a-fA-F]{4,40}")
#: Скільки рядків сирого diff віддавати (не картка канону).
DIFF_LINES = 400
#: Скільки змінених файлів показувати при коміті журналу всього шару.
LOG_FILES = 12


def _top(ws: W.Workspace) -> Path:
    top = repo_top(ws.hub)
    if top is None:
        raise VcsError("простір не в git — `nysh history setup`")
    return top


def check_rev(rev: str) -> str:
    if not _REV.fullmatch(rev or ""):
        raise ValueError(f"мітка коміту «{rev}» — лише шістнадцяткова, з `history log`")
    return rev


def log(ws: W.Workspace, path: Path | None = None,
        limit: int = 20) -> list[dict[str, Any]]:
    """Журнал файла чи теки; без шляху — усього проєктного шару зі зміненими файлами."""
    top = _top(ws)
    if path is not None:
        rel = path.resolve().relative_to(top).as_posix()
        raw = _git(top, "log", f"-n{limit}", "--follow", "--date=short",
                   "--format=%h%x09%ad%x09%s", "--", rel)
        out: list[dict[str, Any]] = []
        for line in raw.splitlines():
            rev, day, subj = [*line.split("\t", 2), "", ""][:3]
            out.append({"rev": rev, "date": day, "subject": subj})
        return out
    rels = []
    for p in _layer(ws):
        try:
            rels.append(p.resolve().relative_to(top).as_posix())
        except ValueError:
            continue
    if not rels:
        return []
    raw = _git(top, "log", f"-n{limit}", "--date=short", "--name-only",
               "--format=%x1e%h%x09%ad%x09%s", "--", *rels)
    out = []
    for chunk in raw.split("\x1e")[1:]:
        head, _, body = chunk.partition("\n")
        rev, day, subj = [*head.split("\t", 2), "", ""][:3]
        files = [f for f in body.splitlines() if f.strip()]
        out.append({"rev": rev, "date": day, "subject": subj,
                    "files": files[:LOG_FILES], "more": max(0, len(files) - LOG_FILES)})
    return out


def restore(ws: W.Workspace, path: Path, rev: str) -> str | None:
    """Повернути файл чи теку до стану `rev` — і зберегти це як новий коміт."""
    top = _top(ws)
    rel = path.resolve().relative_to(top).as_posix()
    _git(top, "checkout", check_rev(rev), "--", rel)
    return save(ws, f"Повернуто {rel} до {rev}", paths=[path])


def _show(top: Path, spec: str) -> str | None:
    """Вміст файла в коміті; `None` — у цьому коміті файла не було."""
    try:
        return _git(top, "show", spec)
    except VcsError:
        return None


def _plain(v: Any) -> Any:
    """Значення frontmatter у JSON: дати — рядком, решта як є."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    if isinstance(v, date):
        return v.isoformat()
    return v


def diff(ws: W.Workspace, path: Path, rev: str) -> dict[str, Any]:
    """Що коміт `rev` змінив у файлі.

    Картка канону (`.md` з frontmatter) — по полях «було → стало» і чи мінявся
    текст під ним: людині, що вирішує, чи повертати, сирий diff YAML нічого не
    каже. Решта файлів — звичайним diff, обрізаним до `DIFF_LINES` рядків.
    """
    import difflib

    top = _top(ws)
    rel = path.resolve().relative_to(top).as_posix()
    check_rev(rev)
    after = _show(top, f"{rev}:{rel}")
    before = _show(top, f"{rev}^:{rel}")
    out: dict[str, Any] = {"path": rel, "rev": rev, "added": before is None,
                           "removed": after is None}
    if rel.endswith(".md"):
        import frontmatter

        a = frontmatter.loads(before or "")
        b = frontmatter.loads(after or "")
        if a.metadata or b.metadata:
            fields = []
            for k in sorted({*a.metadata, *b.metadata}):
                was, now = _plain(a.metadata.get(k)), _plain(b.metadata.get(k))
                if was != now:
                    fields.append({"field": k, "before": was, "after": now})
            out.update(kind="fields", fields=fields,
                       notes_changed=a.content.strip() != b.content.strip())
            return out
    lines = list(difflib.unified_diff((before or "").splitlines(),
                                      (after or "").splitlines(),
                                      f"{rev}^", rev, lineterm="", n=2))
    out.update(kind="text", lines=lines[:DIFF_LINES], cut=len(lines) > DIFF_LINES)
    return out


def autosave_env(env: object, message: str) -> None:
    """`autosave` для операції: причину відмови — попередженням у відповідь."""
    reason = autosave(message)
    if reason and hasattr(env, "warn"):
        env.warn("history", reason)
