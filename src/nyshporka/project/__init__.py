"""📁 Тека проєкту з шаблону: маркер, профіль, інструкції й налаштування агентів.

Проєкт — підтека Майстерні `projects/<ім'я>/` (`core.projects`). Тут —
те, що `nysh project new` кладе в нову теку, і те, як ці файли оновлюються
разом із пакетом.

🔴 Агентні файли проєкту мусять бути ВЛАСНІ. Дослід 19.10.2026: Claude Code
у сесії підтеки читає `CLAUDE.md` батька, але налаштування (`.claude/settings.json`
з хуками) — лише з теки старту. Тому хук старту сесії й окрема тека пам'яті
лежать у кожному проєкті, а не в хабі. Codex так само: `.codex/` проєкту
читається (довіра кореня хаба покриває підтеку), хук потребує одноразового
схвалення людиною (`/hooks`).

Оновлення — за зразком скілів (`skills.sync`): облік sha256 того, що
поклали; файл, який людина змінила, лишається як є (`kept`).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from nyshporka.core import projects as P
from nyshporka.core import workspace as W

#: Облік покладених файлів і версії пакета, що їх поклала.
LEDGER = ".nysh-project.json"

KIND_LABEL = {"family": "дослідження роду", "order": "замовлення клієнта"}

#: Команда, яку хук старту сесії виконує в теці проєкту.
STATUS_CMD = "project status --agent"


def _tmpl(name: str) -> str:
    return resources.files("nyshporka.project").joinpath("data", name).read_text(encoding="utf-8")


def nysh_command() -> str:
    """Як викликати `nysh` з хука: повний шлях, якщо він є в PATH.

    Хук запускає оболонка агента, у якої PATH може бути іншим, ніж у
    терміналі людини; повний шлях прибирає цю різницю. Шлях змінився
    (перевстановлення) — `sync` перепише хук разом з іншими файлами.
    """
    found = shutil.which("nysh")
    return f'"{Path(found).as_posix()}"' if found else "nysh"


def claude_slug(path: Path) -> str:
    """Ім'я теки проєкту в `~/.claude/projects/` — так, як його складає Claude Code."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def memory_dir(path: Path) -> Path:
    """Тека автопам'яті Claude Code для теки `path` (проєкту чи хаба)."""
    return Path.home() / ".claude" / "projects" / claude_slug(path) / "memory"


def _hub_skill_overrides(hub: Path) -> dict[str, Any]:
    """`skillOverrides` хаба: їх треба повторити в проєкті.

    Налаштування хаба в сесії проєкту не діють, а вимкнений у хабі скіл
    (двійник приватного) у проєкті знову змагався б за ту саму фразу.
    """
    try:
        got = json.loads((hub / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    val = got.get("skillOverrides") if isinstance(got, dict) else None
    return val if isinstance(val, dict) else {}


def _hub_hooks(hub: Path) -> dict[str, Any]:
    try:
        got = json.loads((hub / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    hooks = got.get("hooks") if isinstance(got, dict) else None
    return hooks if isinstance(hooks, dict) else {}


def _rebase(node: Any, up: str) -> Any:
    """`$CLAUDE_PROJECT_DIR` хаба → той самий шлях із теки проєкту."""
    if isinstance(node, str):
        return node.replace("$CLAUDE_PROJECT_DIR", f"$CLAUDE_PROJECT_DIR/{up}")
    if isinstance(node, list):
        return [_rebase(x, up) for x in node]
    if isinstance(node, dict):
        return {k: _rebase(v, up) for k, v in node.items()}
    return node


def hub_hooks_for(hub: Path, root: Path) -> dict[str, Any]:
    """Хуки Майстерні для сесії проєкту — крім старту, який у проєкту свій.

    Claude Code читає налаштування лише з теки старту, тож хук хаба (сторож
    команд, заборона грепу скілів) у проєкті без цього просто не діяв би.
    Шлях `$CLAUDE_PROJECT_DIR/…` переписується на хабовий: скрипти хуків
    лежать у Майстерні.
    """
    import os

    up = Path(os.path.relpath(hub, root)).as_posix()
    return {ev: _rebase(v, up) for ev, v in _hub_hooks(hub).items() if ev != "SessionStart"}


def render(hub: Path, root: Path, pid: str, *, kind: str, title: str) -> dict[str, str]:
    """Керовані файли проєкту: шлях від теки проєкту → вміст."""
    subst = {"pid": pid, "title": title, "kind_label": KIND_LABEL.get(kind, kind),
             "order_rules": Template(_tmpl("order_rules.md.tmpl")).safe_substitute()
             if kind == "order" else ""}
    hook = {"type": "command", "command": f"{nysh_command()} {STATUS_CMD}"}
    claude: dict[str, Any] = {
        "autoMemoryDirectory": memory_dir(root).as_posix(),
        "hooks": {"SessionStart": [{"hooks": [hook]}], **hub_hooks_for(hub, root)},
    }
    overrides = _hub_skill_overrides(hub)
    if overrides:
        claude["skillOverrides"] = overrides
    codex_hooks = {"hooks": {"SessionStart": [{"hooks": [hook]}]}}
    return {
        "CLAUDE.md": Template(_tmpl("claude.md.tmpl")).safe_substitute(subst),
        "AGENTS.md": Template(_tmpl("agents.md.tmpl")).safe_substitute(subst),
        ".claude/settings.json": json.dumps(claude, ensure_ascii=False, indent=2) + "\n",
        ".codex/hooks.json": json.dumps(codex_hooks, ensure_ascii=False, indent=2) + "\n",
        ".codex/config.toml": "# Хуки Codex (старт сесії → стан проєкту). Нові чи змінені\n"
                              "# хуки людина один раз схвалює командою /hooks.\n"
                              "[features]\nhooks = true\n",
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ledger(root: Path) -> dict[str, Any]:
    try:
        got = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _write(path: Path, text: str) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)


@dataclass(frozen=True)
class Created:
    root: Path
    files: list[str]
    warnings: list[str]


def create(hub: Path, pid: str, *, kind: str = "family", title: str = "",
           version: str = "") -> Created:
    """Завести теку проєкту. Наявну не чіпає — відмовляє."""
    from nyshporka import __version__

    P.check_name(pid)
    if kind not in P.KINDS:
        raise P.ProjectError(f"вид проєкту «{kind}»: є {', '.join(P.KINDS)}")
    if not (hub / W.MARKER).is_file() or W.read_project_table(hub) is not None:
        raise P.ProjectError(f"{hub} — не корінь Майстерні (немає {W.MARKER} з [workspace])")
    root = P.projects_dir(hub) / pid
    if root.exists():
        raise P.ProjectError(f"тека {root} уже є — проєкт не перезаписується")
    title = title or pid
    # json.dumps дає коректний рядок TOML і з лапками в назві.
    # 🔒 Замовлення — чужий рід: нові справи в ньому приватні, доки автор не
    # вирішить інакше (`nysh case <тека> --public`).
    private = ("private_default = true   # нові справи — private (нікуди з машини)\n"
               if kind == "order" else "")
    marker = (f'[project]\nname = {json.dumps(title, ensure_ascii=False)}\nkind = "{kind}"\n'
              f"{private}"
              "# archived = true   — сховати з переліку (`nysh project archive`)\n"
              '# preset = "researcher"  — свій профіль секцій; без нього — як у Майстерні\n')
    _write(root / W.MARKER, marker)
    for sub in ("config", "data/canonical", "reports"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    _write(root / "notes" / "agent-memory.md",
           Template(_tmpl("agent-memory.md.tmpl")).safe_substitute(title=title))
    files = render(hub, root, pid, kind=kind, title=title)
    for rel, text in files.items():
        _write(root / rel, text)
    _write(root / LEDGER, json.dumps(
        {"version": version or __version__, "files": {k: _sha(v) for k, v in files.items()}},
        ensure_ascii=False, indent=1))
    warnings: list[str] = []
    carried = sorted(hub_hooks_for(hub, root))
    if carried:
        warnings.append(
            "хуки Майстерні (" + ", ".join(carried) + ") перенесено в "
            ".claude/settings.json проєкту: Claude Code читає налаштування лише з теки "
            "старту, а скрипти хуків лишаються в Майстерні")
    written = [W.MARKER, "notes/agent-memory.md", *files]
    hub_cfg = W._read_marker(hub / W.MARKER)
    if hub_cfg.get("hub_only"):
        for name in ("CLAUDE.md", "AGENTS.md"):
            if not (hub / name).exists():
                _write(hub / name, _tmpl("hub.md.tmpl"))
                written.append(f"../../{name}")
    return Created(root=root, files=written, warnings=warnings)


def sync(root: Path, version: str) -> dict[str, str]:
    """Оновити керовані файли проєкту під нову версію пакета.

    Файл, який людина змінила від останнього запису, лишається (`kept`) —
    як у скілів. Повертає {файл: updated | kept | same}.
    """
    led = _ledger(root)
    if not led or led.get("version") == version:
        return {}
    pid = root.name
    tab = W.read_project_table(root) or {}
    files = render(W._hub_above(root), root, pid, kind=str(tab.get("kind") or "family"),
                   title=str(tab.get("name") or pid))
    known: dict[str, str] = dict(led.get("files") or {})
    out: dict[str, str] = {}
    for rel, text in files.items():
        path = root / rel
        try:
            have = path.read_text(encoding="utf-8")
        except OSError:
            have = None
        if have == text:
            out[rel] = "same"
        elif have is not None and _sha(have) != known.get(rel):
            out[rel] = "kept"
            continue
        else:
            _write(path, text)
            out[rel] = "updated"
        known[rel] = _sha(text)
    _write(root / LEDGER, json.dumps({"version": version, "files": known},
                                     ensure_ascii=False, indent=1))
    return out


def set_style(root: Path, *, color: str | None = None, glyph: str | None = None,
              title: str | None = None, icon: str | None = None,
              scene: str | None = None) -> None:
    """Назва, колір, знак, значок і картина Огляду проєкту в маркері; порожній
    рядок знімає колір, знак, значок чи картину, `None` — не чіпає. Назву не
    знімають: без неї лишився б id."""
    import json

    text = (root / W.MARKER).read_text(encoding="utf-8")
    pairs = [("color", color), ("glyph", glyph), ("icon", icon), ("scene", scene)]
    if title and title.strip():
        pairs.append(("name", title.strip()))
    for key, val in pairs:
        if val is not None:
            text = W._marker_set(text, key, f"{key} = {json.dumps(val, ensure_ascii=False)}"
                                 if val else None, "project")
    W._write_marker(root / W.MARKER, text)


def set_archived(root: Path, archived: bool) -> None:
    text = (root / W.MARKER).read_text(encoding="utf-8")
    line = "archived = true" if archived else None
    W._write_marker(root / W.MARKER, W._marker_set(text, "archived", line, "project"))
