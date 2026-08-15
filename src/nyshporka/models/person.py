from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nyshporka.models.common import MediaRef, NameVariant
from nyshporka.models.fact import Fact

Sex = Literal["M", "F", "U"]


class Floruit(BaseModel):
    """Період активного життя для осіб без точних birth/death.
    Ручний override обчислення у reindex._compute_lived."""

    model_config = ConfigDict(extra="forbid")

    from_year: int
    to_year: int
    note: str = ""


class Person(BaseModel):
    """Канонічна модель особи. SoT у data/canonical/persons/{id}.md."""

    model_config = ConfigDict(extra="forbid")

    id: str
    names: list[NameVariant]
    sex: Sex = "U"
    private: bool = False
    facts: list[Fact] = []
    parent_family: str | None = None
    spouse_families: list[str] = []
    # Гіпотетичні (не верифіковані джерелом) родинні зв'язки. Семантика:
    # parent_family + spouse_families = підтверджені метричним записом/документом.
    # hypothetical_* = виведено з логіки, прізвища, хронології — без first-source.
    # Render/reindex показують їх окремо, щоб не змішувати рівні впевненості.
    hypothetical_parent_family: str | None = None
    hypothetical_spouse_families: list[str] = []
    media: list[MediaRef] = []
    aliases: list[str] = []
    floruit: Floruit | None = None
    notes: str = ""

    @property
    def primary_name(self) -> str:
        for n in self.names:
            if n.primary:
                return n.form
        return self.names[0].form if self.names else self.id
