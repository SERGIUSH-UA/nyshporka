"""🛡 Запобіжник агента: скіл Нишпорки вантажиться цілим, а не грепом.

Скіл — це порядок роботи з приймачами. Агент, який економить токени, робить
`wc -l SKILL.md`, далі `rg` по кількох словах і діє за вирваними рядками:
вигадує прапорці, яких немає, пропускає приймач і платить за це орендою
(два зірвані хмарні заходи поспіль, 12 і 15.10.2026). Правило в інструкції
агента цього не втримало, тож потрібна межа, яку агент не може пропустити:
хук Claude Code `PreToolUse`.

Цей файл копіюється в теку хуків агента (`nysh skills hook --install`) і
запускається окремим процесом на кожен виклик Bash, PowerShell, Grep і Read.
Тому він самодостатній: лише stdlib, без імпорту пакета, і швидкий.

Межа дії — лише скіли, які поклав пакет: поруч із ними лежить облік
`.nysh-skills.json`. Власні скіли людини, скіли інших пакетів і репозиторій
самої Нишпорки (там скіли правлять як код) запобіжник не чіпає.

🔴 Будь-яка власна помилка запобіжника — це «пропустити», а не «заборонити»:
зламаний хук, що блокує все, зупинив би роботу агента повністю.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

LEDGER = ".nysh-skills.json"
CARD = "SKILL.md"

#: Команди, якими скіл читають шматком або грепають. З урахуванням регістру:
#: інакше `git … HEAD` поруч зі шляхом до картки читався б як `head`.
READERS = re.compile(
    r"(?<![\w.-])(rg|grep|egrep|fgrep|sed|head|tail|awk|cut|cat|bat|less|more|"
    r"Select-String|Get-Content|select-string|get-content)(?![\w-])")
#: Шлях до картки в тексті команди.
CARD_IN_CMD = re.compile(r"""[^\s"'`|;&<>()=]*SKILL\.md""")
#: Шлях Git Bash `/e/…` → `E:/…` (на Windows Python його не розуміє).
_MSYS = re.compile(r"^/([A-Za-z])/")

REASON = ("Скіл Нишпорки не грепають і не читають шматком: вирваний рядок без "
          "приймача і пасток дає вигадані прапорці. Завантаж скіл ЦІЛИМ "
          "інструментом Skill (ім'я його теки) або прочитай SKILL.md повністю, "
          "без offset/limit. Запобіжник поставлено командою `nysh skills hook`.")


def _path(raw: str, cwd: str) -> Path:
    raw = raw.strip().strip("\"'")
    if os.name == "nt":
        raw = _MSYS.sub(lambda m: f"{m.group(1).upper()}:/", raw)
    p = Path(os.path.expanduser(raw))
    return p if p.is_absolute() else Path(cwd or ".") / p


def _ours(p: Path) -> bool:
    """Чи лежить шлях у теці скілів, яку наповнив пакет.

    Дивимось на сам шлях і два рівні вгору: тека скілів, тека скіла, картка.
    Шаблон `*/SKILL.md` лишає теку скілів на тому ж місці (`parent.parent`),
    тож глоб в імені скіла не заважає.
    """
    for d in (p, p.parent, p.parent.parent):
        try:
            if (d / LEDGER).is_file():
                # Репозиторій пакета: туди теж буває кладуть скіли командою
                # (облік поза git), але там їх правлять як код.
                return not (d.parent.parent / "src" / "nyshporka").is_dir()
        except (OSError, ValueError):
            continue
    return False


def decide(payload: dict[str, Any]) -> str | None:
    """Причина відмови або `None` — пропустити."""
    tool = str(payload.get("tool_name") or "")
    args = payload.get("tool_input") or {}
    cwd = str(payload.get("cwd") or os.getcwd())

    if tool in ("Bash", "PowerShell"):
        cmd = str(args.get("command") or "")
        if CARD not in cmd or not READERS.search(cmd):
            return None
        if any(_ours(_path(tok, cwd)) for tok in CARD_IN_CMD.findall(cmd)):
            return REASON
        return None

    if tool == "Grep":
        raw = str(args.get("path") or "")
        if not raw:
            return None
        p = _path(raw, cwd)
        # тека скілів, тека скіла або сама картка; довідники поруч — можна
        if p.name == CARD or (p / LEDGER).is_file() or (p.parent / LEDGER).is_file():
            return REASON if _ours(p) else None
        return None

    if tool == "Read":
        raw = str(args.get("file_path") or "")
        partial = args.get("offset") is not None or args.get("limit") is not None
        if partial and raw.endswith(CARD) and _ours(_path(raw, cwd)):
            return REASON
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        reason = decide(payload if isinstance(payload, dict) else {})
    except Exception:
        return 0
    if reason:
        # ensure_ascii: кодування stdout на Windows буває cp1252, і кирилиця
        # поклала б сам запобіжник; JSON-екранування агент читає однаково.
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
