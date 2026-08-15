from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["direct", "indirect", "circumstantial", "negative", "speculative"]


class Citation(BaseModel):
    """Посилання на конкретне джерело з оцінкою достовірності (genealogy-grade)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    page: str | None = None
    quote: str | None = None
    confidence: Confidence
    accessed: date
    note: str | None = Field(default=None, description="Коментар на полях.")
