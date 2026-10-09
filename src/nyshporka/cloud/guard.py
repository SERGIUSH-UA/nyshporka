"""Запобіжник від одночасного локального й хмарного читання справи.

Локальні прогони й наглядач орендованих машин мають різні реєстри. Через це
`nysh read` раніше міг не побачити справу, яка вже стояла у хмарній черзі або
чекала забору з боксу. Тут читається публічний JSON-контракт наглядача — той
самий, який показує `gpurunner htr state`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

TERMINAL_PHASES = frozenset({"done", "failed", "finished", "stopped"})


@dataclass(frozen=True)
class CloudCase:
    """Хмарна справа, яка робить локальний повтор небезпечним."""

    session: str
    phase: str
    status: str
    pages_done: int
    pages_total: int
    detail: str
    active: bool
    updated: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.pages_total and self.pages_done >= self.pages_total)

    def label(self) -> str:
        pages = (f" · {self.pages_done}/{self.pages_total} стор."
                 if self.pages_total else "")
        return f"{self.session} · {self.phase}/{self.status}{pages}"


def state_dir() -> Path:
    """Тека JSON наглядача без залежності від опційного пакета оренди."""
    override = os.environ.get("GPURUNNER_DATA_DIR", "").strip()
    root = Path(override) if override else Path(user_data_dir("gpurunner", appauthor=False))
    return root / "htr"


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _states() -> list[dict[str, Any]]:
    """Усі унікальні стани сесій, новіші першими."""
    folder = state_dir()
    if not folder.is_dir():
        return []
    by_session: dict[str, dict[str, Any]] = {}
    for path in folder.glob("*.json"):
        # Службовий запит на згортання не є станом заходу.
        if path.name.endswith(".wrapup.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
            continue
        session = str(data.get("session") or "")
        if not session:
            continue
        old = by_session.get(session)
        if old is None or _timestamp(str(data.get("updated") or "")) >= _timestamp(
                str(old.get("updated") or "")):
            by_session[session] = data
    return sorted(by_session.values(),
                  key=lambda d: _timestamp(str(d.get("updated") or "")), reverse=True)


def conflict(case_key: str) -> CloudCase | None:
    """Активний або повністю прочитаний хмарний дубль цієї шифри.

    Старий невдалий захід без повного результату не блокує повтор. Жива сесія
    блокує навіть `pending`: справа вже в її черзі й пізніше стартує сама.
    """
    wanted = case_key.strip().casefold()
    if not wanted:
        return None
    completed: CloudCase | None = None
    for data in _states():
        phase = str(data.get("phase") or "unknown")
        verdict = str(data.get("verdict") or "")
        active = not verdict and phase not in TERMINAL_PHASES
        for raw in data.get("cases") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("case_key") or "").strip().casefold() != wanted:
                continue
            pages_done = _integer(raw.get("pages_done"))
            pages_total = _integer(raw.get("n_pages_expected"))
            item = CloudCase(
                session=str(data.get("session") or "?"), phase=phase,
                status=str(raw.get("status") or "unknown"),
                pages_done=pages_done, pages_total=pages_total,
                detail=str(raw.get("detail") or data.get("why") or ""),
                active=active, updated=str(data.get("updated") or ""))
            if active:
                return item
            if item.complete or raw.get("complete") is True or item.status == "done":
                completed = completed or item
    return completed
