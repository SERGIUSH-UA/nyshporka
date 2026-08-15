from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from nyshporka.models.fact import Fact


class Family(BaseModel):
    """Канонічна модель родини (шлюб). SoT у data/canonical/families/{id}.md."""

    model_config = ConfigDict(extra="forbid")

    id: str
    husband: str | None = None
    wife: str | None = None
    children: list[str] = []
    # Гіпотетичні (не верифіковані) члени родини. Дзеркало Person.hypothetical_*.
    # Двосторонність: Person.hypothetical_parent_family=F → F.hypothetical_children містить P.
    hypothetical_husband: str | None = None
    hypothetical_wife: str | None = None
    hypothetical_children: list[str] = []
    facts: list[Fact] = []
    aliases: list[str] = []
    notes: str = ""
