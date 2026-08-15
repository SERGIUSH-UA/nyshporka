from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nyshporka.models.common import LangCode


class Place(BaseModel):
    """Канонічна модель місця. SoT у data/canonical/places/{id}.md."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(description="Канонічна форма українською.")
    name_variants: dict[LangCode, str] = {}
    osm_id: int | None = None
    coords: tuple[float, float] | None = None
    admin: list[str] = Field(
        default_factory=list,
        description="Адміністративний ланцюг: ['Україна', 'Вінницька обл.', 'Городківка'].",
    )
    period_notes: str = Field(
        default="",
        description="Зміни приналежності в часі (напр. «1939-1944 — рейхскомісаріат»).",
    )
    notes: str = ""
