from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nyshporka.models.citation import Citation
from nyshporka.models.common import GedDate

FactType = Literal[
    "birth",
    "death",
    "marriage",
    "divorce",
    "residence",
    "occupation",
    "education",
    "baptism",
    "burial",
    "emigration",
    "military",
    "religion",
    "nationality",
    "other",
]

FactStatus = Literal["confirmed", "hypothesis", "disputed"]


class Fact(BaseModel):
    """Одиниця факту: подія/атрибут із датою, місцем і списком цитат."""

    model_config = ConfigDict(extra="forbid")

    type: FactType
    date: GedDate | None = None
    place_id: str | None = None
    value: str | None = None
    citations: list[Citation] = []
    status: FactStatus = "hypothesis"
