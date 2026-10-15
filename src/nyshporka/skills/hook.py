"""🛡 Поставити запобіжник скілів у конфіг агента — або записати, що людина відмовилась.

Пакет у конфіг агента мовчки не пише (див. `skills.install`). Тому хук ставить
лише явна команда `nysh skills hook --install`, і лише з дозволу людини. Що
людина вирішила, записується в **контрольний файл** машини
(`agent-hook.json` поруч зі станом користувача). Крок міграції `skill_guard`
читає саме його: «поставлено» звіряється з живим конфігом, «відмовились»
приймається як рішення. Якщо запису немає, крок лишається червоним, і агент
мусить спитати.

Хук — Claude Code (`.claude/settings.json`, `PreToolUse`). Для Codex його не
ставимо: там лишаються короткі скіли й правило в інструкції агента.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Ім'я копії запобіжника в теці хуків і мітка нашого запису в конфігу.
SCRIPT = "nysh-skill-guard.py"
#: Які виклики бачить запобіжник.
MATCHER = "Bash|PowerShell|Grep|Read"
#: Контрольний файл: рішення людини по кожному конфігу агента.
CONTROL = "agent-hook.json"


def settings_path(*, user: bool) -> Path:
    """Куди пишемо: `~/.claude/settings.json` або `settings.local.json` проєкту.

    🔴 У проєкті — `settings.local.json`, а не `settings.json`: другий кладуть у
    git, а наш запис несе абсолютні шляхи ЦІЄЇ машини (інтерпретатор, копія
    запобіжника). У спільному файлі він ламав би хук кожному, хто клонував.
    """
    if user:
        return Path.home() / ".claude" / "settings.json"
    return Path.cwd() / ".claude" / "settings.local.json"


#: Куди ставила 0.30.2 у проєкті — `remove` прибирає й звідти.
LEGACY_PROJECT = Path(".claude") / "settings.json"


def control_path() -> Path:
    from platformdirs import user_state_dir

    return Path(user_state_dir("Nyshporka", appauthor=False)) / CONTROL


def _command(script: Path) -> str:
    # Інтерпретатор самого пакета: на машині людини іншого Python може не бути.
    return f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'


def _load(settings: Path) -> dict[str, Any]:
    if not settings.is_file():
        return {}
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except ValueError as exc:
        # Чужий конфіг, який ми не розібрали, не переписуємо — людина
        # втратила б усе, що там було.
        raise ValueError(f"{settings} не розбирається як JSON ({exc}); "
                         f"не чіпаю — виправте файл або поставте хук руками") from None
    if not isinstance(data, dict):
        raise ValueError(f"{settings}: верхній рівень не об'єкт; не чіпаю")
    return data


def _ours(entry: Any) -> bool:
    return SCRIPT in json.dumps(entry, ensure_ascii=False)


def _write(settings: Path, data: dict[str, Any]) -> None:
    from nyshporka.utils.atomic import atomic_write_text

    settings.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(settings, json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      newline="\n")


def present(settings: Path) -> str:
    """Порожньо — хук стоїть і працюватиме; інакше — що з ним не так."""
    try:
        data = _load(settings)
    except ValueError as exc:
        return str(exc)
    entries = [e for e in ((data.get("hooks") or {}).get("PreToolUse") or [])
               if _ours(e)]
    if not entries:
        return f"у {settings} запобіжника немає"
    script = settings.parent / "hooks" / SCRIPT
    if not script.is_file():
        return f"запис є, а файла {script} немає"
    cmds = [str(h.get("command") or "") for e in entries for h in (e.get("hooks") or [])
            if isinstance(h, dict)]
    exe = next((c.split('"')[1] for c in cmds if c.startswith('"') and c.count('"') >= 2), "")
    if exe and not Path(exe).is_file():
        return f"інтерпретатора {exe} уже немає — `nysh skills hook --install` ще раз"
    return ""


GUARD = Path(__file__).with_name("guard.py")
#: Змінна, яку ставить наш Docker-образ (`daemon.app.in_container`).
ENV_DOCKER = "NYSH_DOCKER_IMAGE"


def _put(settings: Path) -> None:
    """Покласти свіжу копію запобіжника й один наш запис у цей конфіг."""
    data = _load(settings)
    script = settings.parent / "hooks" / SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GUARD, script)

    hooks = data.setdefault("hooks", {})
    pre = [e for e in (hooks.get("PreToolUse") or []) if not _ours(e)]
    pre.append({"matcher": MATCHER,
                "hooks": [{"type": "command", "command": _command(script)}]})
    hooks["PreToolUse"] = pre
    _write(settings, data)


def install(*, user: bool) -> Path:
    """Скопіювати запобіжник і дописати його в конфіг, не чіпаючи чужого.

    🔴 У контейнері — відмова. `nysh` там лише через обгортку, а агент живе на
    основній системі: шляхи інтерпретатора й копії з контейнера в конфігу
    основної системи не існують, і хук падав би на кожному виклику агента.
    """
    import os

    if os.environ.get(ENV_DOCKER):
        raise ValueError("Нишпорка в контейнері, а помічник — на основній системі: "
                         "звідси хук поставити не можна. Відмову з поясненням "
                         "запишіть `nysh skills hook --decline --why \"Docker\"`")
    settings = settings_path(user=user)
    _put(settings)
    record(settings, "installed")
    return settings


def _strip(settings: Path) -> None:
    if not settings.is_file():
        return
    data = _load(settings)
    hooks = data.get("hooks") or {}
    if not any(_ours(e) for e in (hooks.get("PreToolUse") or [])):
        return
    pre = [e for e in hooks["PreToolUse"] if not _ours(e)]
    if pre:
        hooks["PreToolUse"] = pre
    else:
        del hooks["PreToolUse"]
    if not hooks:
        data.pop("hooks", None)
    _write(settings, data)


def remove(*, user: bool) -> Path:
    """Зняти наш запис і копію; чужі хуки лишаються."""
    settings = settings_path(user=user)
    _strip(settings)
    if not user:
        _strip(Path.cwd() / LEGACY_PROJECT)
    (settings.parent / "hooks" / SCRIPT).unlink(missing_ok=True)
    return settings


def refresh() -> list[Path]:
    """Після оновлення пакета — свіжа копія запобіжника там, де його поставили.

    Копія лежить у теці агента, і без цього кроку виправлення запобіжника до
    людини не доходили б ніколи. Переписує й шлях інтерпретатора, якщо пакет
    перевстановлено деінде. Чіпає лише конфіги з записом «installed», де наш
    запис досі стоїть: знятий руками хук не повертаємо.
    """
    import os

    from nyshporka.skills import ENV_NO_SYNC

    done: list[Path] = []
    if os.environ.get(ENV_NO_SYNC):
        return done
    for d in decisions():
        if d.decision != "installed":
            continue
        settings = Path(d.settings)
        script = settings.parent / "hooks" / SCRIPT
        try:
            if not script.is_file() or not settings.is_file():
                continue
            ours = [e for e in ((_load(settings).get("hooks") or {}).get("PreToolUse") or [])
                    if _ours(e)]
            if not ours:
                continue
            cmds = {str(h.get("command") or "") for e in ours for h in (e.get("hooks") or [])
                    if isinstance(h, dict)}
            stale = script.read_bytes() != GUARD.read_bytes()
            moved = _command(script) not in cmds
            if stale or moved:
                _put(settings)
                done.append(settings)
        except (OSError, ValueError):
            continue
    return done


# ── контрольний файл ─────────────────────────────────────────────────────────
@dataclass
class Decision:
    settings: str
    decision: str          # installed · declined
    why: str
    at: str


def decisions() -> list[Decision]:
    try:
        data = json.loads(control_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return []
    rows = data.get("decisions") if isinstance(data, dict) else None
    out = []
    for key, d in (rows or {}).items():
        if isinstance(d, dict) and d.get("decision") in ("installed", "declined"):
            out.append(Decision(settings=key, decision=d["decision"],
                                why=str(d.get("why") or ""), at=str(d.get("at") or "")))
    return out


def record(settings: Path, decision: str, why: str = "") -> Path:
    """Записати рішення людини про цей конфіг агента."""
    from nyshporka.utils.atomic import atomic_write_text

    path = control_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    rows = data.setdefault("decisions", {})
    rows[str(settings.resolve())] = {
        "decision": decision, "why": why,
        "at": datetime.now(UTC).isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                      newline="\n")
    return path


def verdict() -> tuple[str, str]:
    """Стан для міграції: (`ok` | `todo`, пояснення)."""
    rows = decisions()
    if not rows:
        return ("todo", "рішення людини не записано: спитати й виконати "
                        "`nysh skills hook --install` або "
                        "`nysh skills hook --decline --why \"…\"`")
    broken: list[str] = []
    fine: list[str] = []
    for d in rows:
        if d.decision == "declined":
            fine.append(f"відмовились ({d.why or 'без пояснення'})")
            continue
        problem = present(Path(d.settings))
        (broken if problem else fine).append(problem or f"стоїть: {d.settings}")
    if broken:
        return ("todo", "; ".join(broken))
    return ("ok", "; ".join(fine))
