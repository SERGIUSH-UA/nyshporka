"""Реєстр історичних адмінодиниць (губернії/повіти) для карти покриття.

SoT — data/canonical/regions.yml (git-versioned, редагується руками).
Коди регіонів: "pod" (губернія цілком) або "pod.olgopil" (повіт).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class GridPos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int
    col: int


class Uezd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    grid: GridPos


class Governorate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    eparchy: str | None = None
    block: GridPos
    uezds: list[Uezd] = []


class RegionRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    year_min: int
    year_max: int
    governorates: list[Governorate]

    def codes(self) -> set[str]:
        """Усі валідні коди: губернії + повіти."""
        out: set[str] = set()
        for gov in self.governorates:
            out.add(gov.code)
            out.update(u.code for u in gov.uezds)
        return out

    def names(self) -> dict[str, str]:
        """Код → людська назва («Ольгопільський повіт, Подільська губернія»)."""
        out: dict[str, str] = {}
        for gov in self.governorates:
            out[gov.code] = gov.name
            for u in gov.uezds:
                out[u.code] = f"{u.name} повіт, {gov.name}"
        return out


def load_regions(project_root: Path) -> RegionRegistry:
    path = project_root / "data" / "canonical" / "regions.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RegionRegistry.model_validate(data)
