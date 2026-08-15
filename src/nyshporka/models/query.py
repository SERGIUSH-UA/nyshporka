"""Універсальна Query-модель для fetcher'ів + stable_hash для ідемпотентності."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["B", "M", "D"]


class Query(BaseModel):
    """Параметри пошуку у зовнішньому джерелі.

    Не всі fetcher'и використовують усі поля — нерелевантні залишаються None
    і не входять у `stable_hash` (через `exclude_none`).
    """

    model_config = ConfigDict(extra="forbid")

    surname: str | None = None
    given: str | None = None
    patronymic: str | None = None
    region: str | None = Field(default=None, description="Регіон-залежний код (e.g. '10pl' для Geneteka).")
    year_from: int | None = None
    year_to: int | None = None
    event_type: EventType | None = None
    page: int = 1
    extra: dict[str, str] = Field(
        default_factory=dict,
        description="Джерело-специфічні параметри, що не входять у канонічний набір.",
    )

    def stable_hash(self) -> str:
        """Детерміністичний 16-символьний hex hash (blake2b 8 bytes).

        Однакові query повертають однаковий hash незалежно від порядку ключів.
        """
        data = self.model_dump(mode="json", exclude_none=True)
        # extra — нормалізуємо ключі
        if data.get("extra") == {}:
            data.pop("extra", None)
        canon = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.blake2b(canon.encode("utf-8"), digest_size=8).hexdigest()
