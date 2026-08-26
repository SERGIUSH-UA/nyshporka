from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceType = Literal[
    "gedcom",
    "website",
    "archive",
    "book",
    "periodical",
    "oral",
    "interview",
    "photo",
    "pdf",
    "record",
]

CoverageStatus = Literal[
    "known",       # виявлено у довіднику/каталозі/описі
    "ordered",     # замовлено в архіві
    "downloaded",  # скани отримано
    "decoded",     # прочитано/проіндексовано
    "exhausted",   # повністю відпрацьовано
    "negative",    # перевірено — наших немає
]

CoverageRecordType = Literal[
    "birth",        # метрики: народження
    "marriage",     # метрики: шлюби
    "death",        # метрики: смерті
    "confession",   # сповідні відомості
    "revision",     # ревізькі казки / посімейні списки
    "gazette",      # єпархіальні відомості
    "clergy_list",  # клірові відомості
    "finding_aid",  # каталог / опис фонду
    "other",
]


class CoverageSpan(BaseModel):
    """Покриття джерелом одного регіону за діапазон років.

    `region` — код з data/canonical/regions.yml: повіт ("pod.olgopil")
    або ціла губернія ("pod"). Валідність коду перевіряє reindex.
    """

    model_config = ConfigDict(extra="forbid")

    region: str
    parish: str | None = None
    place_ids: list[str] = Field(default_factory=list)
    settlements: list[str] = Field(default_factory=list)
    year_from: int
    year_to: int | None = None  # None = один рік year_from
    record_types: list[CoverageRecordType] = Field(default_factory=list)
    status: CoverageStatus = "known"
    note: str | None = None

    @model_validator(mode="after")
    def _check_years(self) -> CoverageSpan:
        if self.year_to is not None and self.year_to < self.year_from:
            raise ValueError(
                f"year_to ({self.year_to}) < year_from ({self.year_from})"
            )
        return self


class Source(BaseModel):
    """Канонічна модель джерела. SoT у data/canonical/sources/{id}.md."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: SourceType
    title: str
    authority: str | None = None
    url: str | None = None
    repository_ref: str | None = None
    fetched: datetime | None = None
    raw_path: str | None = None
    coverage: list[CoverageSpan] = Field(default_factory=list)
    notes: str = ""
