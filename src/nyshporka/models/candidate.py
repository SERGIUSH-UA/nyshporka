"""Кандидат із зовнішнього джерела, що чекає на людський gate (nysh review)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CandidateStatus = Literal[
    "new",
    "reviewing",
    "accepted",
    "rejected",
    "merged",
    "needs_more",
]


class Candidate(BaseModel):
    """Запис із fetcher'а, зіставлений із канонічною особою (або без).

    Зберігається як JSON у `data/candidates/{source_id}__{id}.json`. Не
    модифікує canonical напряму — лише через `nysh review`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    raw_path: str = Field(description="Шлях до raw-артефакту (data/raw/...).")
    parsed_path: str | None = None
    extracted: dict[str, Any] = Field(description="Розпарсений запис із джерела.")
    proposed_person_id: str | None = None
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    status: CandidateStatus = "new"
    reviewed_at: datetime | None = None
    notes: str = ""
