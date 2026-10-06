"""📏 Чи вміщаються описи скілів у перелік, який Claude Code показує агентові.

Claude Code кожен хід кладе в контекст перелік скілів: ім'я й опис кожного.
Перелік має бюджет — 1% контекстного вікна моделі (`skillListingBudgetFraction`,
без відомого вікна — 8 000 символів), а кожен опис обрізається до 1 536
символів (`skillListingMaxDescChars`). Коли перелік більший за бюджет, Claude
Code лишає всім ім'я, але **відкидає описи найрідше вживаних скілів**
(code.claude.com/docs/en/skills, «Skill descriptions are cut short»).

🔴 Чому це наша справа. Скіл без опису агент сам не обирає: тригерів, за якими
задача збігається зі скілом, немає. А найрідше вживані — саме щойно оновлені
скіли Нишпорки, бо нова версія приходить із новими картками. На машині, де
поруч стоять десятки сторонніх скілів (знайдено 07.10.2026: 16 скілів
Cloudflare/Meshy/Sandbox поруч із 17 нашими, ~30 тис. символів описів), нова
фіча випускалась, а агент про неї не дізнавався.

⚠ Бюджет у символах — оцінка: вікно залежить від моделі, а вбудовані скіли
Claude Code теж займають місце. Точне число — рядок Skills у `/context` або
`/doctor` самого Claude Code. Тому висновок перевірки — попередження, а не
поломка, і налаштувань людини вона не править: лише каже, що змінити.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Типова стеля опису одного скіла в переліку (`skillListingMaxDescChars`).
MAX_DESC = 1536
#: Типова частка вікна під перелік (`skillListingBudgetFraction`).
FRACTION = 0.01
#: Символів на токен — з документації: бюджет без відомого вікна 8 000
#: символів, тобто 1% від 200K токенів при ~4 символах на токен.
CHARS_PER_TOKEN = 4
#: Вікна, для яких рахуємо оцінку: типове й велике.
WINDOWS = (200_000, 1_000_000)
#: Окремий запас на ім'я й розмітку рядка переліку.
ENTRY_OVERHEAD = 8


@dataclass(frozen=True)
class Entry:
    """Скіл у переліку: звідки, ім'я, скільки символів займає."""

    name: str
    where: str          # user · project · synced · plugin:<ім'я>
    chars: int
    ours: bool
    mode: str = "on"    # on · name-only (off/user-invocable-only сюди не потрапляють)


@dataclass
class Listing:
    entries: list[Entry] = field(default_factory=list)
    fraction: float = FRACTION
    max_desc: int = MAX_DESC
    fixed_budget: int | None = None      # SLASH_COMMAND_TOOL_CHAR_BUDGET
    hidden: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(e.chars for e in self.entries)

    @property
    def ours(self) -> int:
        return sum(e.chars for e in self.entries if e.ours)

    def budgets(self) -> dict[int, int]:
        """Бюджет у символах для кожного вікна з `WINDOWS` (або фіксований)."""
        if self.fixed_budget:
            return {0: self.fixed_budget}
        return {w: int(w * self.fraction * CHARS_PER_TOKEN) for w in WINDOWS}

    def foreign_top(self, n: int = 6) -> list[Entry]:
        """Найбільші сторонні скіли користувача й плагінів з повним описом.

        Скіли проєкту сюди не йдуть: їх поклав той, хто веде проєкт, і
        вимикати їх заради нашого місця — не порада, а шкода.
        """
        return sorted((e for e in self.entries
                       if not e.ours and e.mode == "on" and e.where != "project"),
                      key=lambda e: -e.chars)[:n]


def _front(card: Path) -> dict[str, Any]:
    """YAML-шапка `SKILL.md`; бита чи відсутня — порожньо."""
    try:
        text = card.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    try:
        import yaml

        data = yaml.safe_load(m.group(1))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _settings(home: Path, project: Path) -> dict[str, Any]:
    """Злиті налаштування Claude Code: користувача, проєкту, локальні проєкту.

    Пізніший файл перекриває раніший — для `skillOverrides` по ключу.
    """
    merged: dict[str, Any] = {"skillOverrides": {}, "env": {}}
    for path in (home / ".claude" / "settings.json",
                 project / ".claude" / "settings.json",
                 project / ".claude" / "settings.local.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("skillOverrides", "env"):
            if isinstance(data.get(key), dict):
                merged[key].update(data[key])
        for key in ("skillListingBudgetFraction", "skillListingMaxDescChars",
                    "enabledPlugins", "syncClaudeAiSkills"):
            if key in data:
                if key == "enabledPlugins" and isinstance(data[key], dict):
                    merged.setdefault(key, {}).update(data[key])
                else:
                    merged[key] = data[key]
    return merged


def _skill_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if (d / "SKILL.md").is_file())


def _plugin_skill_dirs(home: Path, enabled: dict[str, Any]) -> list[tuple[str, Path]]:
    """Скіли ввімкнених плагінів: `plugins/cache/<маркет>/<плагін>/<версія>/skills/*`."""
    out: list[tuple[str, Path]] = []
    cache = home / ".claude" / "plugins" / "cache"
    for key, on in (enabled or {}).items():
        if on is not True or "@" not in str(key):
            continue
        name, market = str(key).split("@", 1)
        base = cache / market / name
        if not base.is_dir():
            continue
        versions = sorted((d for d in base.iterdir() if d.is_dir()),
                          key=lambda d: d.stat().st_mtime)
        if versions:
            out += [(name, d) for d in _skill_dirs(versions[-1] / "skills")]
    return out


def measure(home: Path | None = None, project: Path | None = None) -> Listing:
    """Перелік скілів, які бачитиме агент у цьому проєкті, і скільки він важить."""
    from nyshporka import skills as S

    home = home or Path.home()
    project = project or Path.cwd()
    st = _settings(home, project)
    overrides = {str(k): str(v) for k, v in st["skillOverrides"].items()}
    ours = {s.name for s in S.available()}
    lst = Listing()
    with contextlib.suppress(TypeError, ValueError):
        lst.fraction = float(st.get("skillListingBudgetFraction") or FRACTION)
    with contextlib.suppress(TypeError, ValueError):
        lst.max_desc = int(st.get("skillListingMaxDescChars") or MAX_DESC)
    raw = os.environ.get("SLASH_COMMAND_TOOL_CHAR_BUDGET") or str(
        st["env"].get("SLASH_COMMAND_TOOL_CHAR_BUDGET") or "")
    if raw.strip().isdigit():
        lst.fixed_budget = int(raw)

    seen: set[str] = set()
    found: list[tuple[str, Path, bool]] = []          # (де, тека, чи діють overrides)
    for where, root in (("project", project / ".claude" / "skills"),
                        ("user", home / ".claude" / "skills")):
        found += [(where, d, True) for d in _skill_dirs(root)]
    # Скіли, синхронізовані з claude.ai, лежать на рівень глибше:
    # `synced/<обліковий запис>/<скіл>/SKILL.md`. Вимкнені — `syncClaudeAiSkills: false`.
    synced = home / ".claude" / "skills" / "synced"
    if st.get("syncClaudeAiSkills") is not False and synced.is_dir():
        for acc in sorted(d for d in synced.iterdir() if d.is_dir()):
            found += [("synced", d, True) for d in _skill_dirs(acc)]
    found += [(f"plugin:{p}", d, False)
              for p, d in _plugin_skill_dirs(home, st.get("enabledPlugins") or {})]
    for where, d, overridable in found:
        meta = _front(d / "SKILL.md")
        name = str(meta.get("name") or d.name)
        if name in seen:
            continue                     # проєктний скіл перекриває однойменний
        seen.add(name)
        mode = "on"
        if overridable:
            mode = overrides.get(name) or overrides.get(d.name) or "on"
        if mode in ("off", "user-invocable-only"):
            lst.hidden.append(name)
            continue
        text = " ".join(str(meta.get(k) or "") for k in ("description", "when_to_use"))
        desc = 0 if mode == "name-only" else min(len(text.strip()), lst.max_desc)
        lst.entries.append(Entry(name=name, where=where,
                                 chars=len(name) + ENTRY_OVERHEAD + desc,
                                 ours=d.name in ours or name in ours, mode=mode))
    return lst
