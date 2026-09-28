"""⚙️ Налаштування сайту роду: `data/site/site.yml` у просторі.

Усе необов'язкове. Без файла сайт збирається з назвою «Родовід», без груп
місць і з порогами приватності за замовчуванням.

```yaml
title: Родовід Ковалів
description: Що ми знаємо про рід і на чому це стоїть.
born_after: 1920          # без смерті й народжені від цього року — у відкритій версії приховані
died_after: 2000          # померлі від цього року — теж (найближчі живі)
extra_hide: []            # ID поіменно
extra_show: []            # ID історичних осіб без дат, яких показувати
drop_source_types: [oral, interview, photo]
place_groups:             # групи місць: перелік, мапа, легенда
  - {id: podillia, label: Поділля, color: "#1f77b4", match: [вінницьк, поділ]}
display_order: [podillia] # порядок груп на сторінці; без нього — як у place_groups
eras:                     # фільтр мапи за роками подій
  - {label: "до 1860", to: 1860}
  - {label: "1860–1917", from: 1860, to: 1917}
nav_after:                # власні сторінки з data/site/overlay/
  - {title: Історії, path: stories/index.md}
```
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path("data") / "site" / "site.yml"
OVERLAY = Path("data") / "site" / "overlay"

#: Порядок і назви типів джерел на сторінці «Джерела».
SOURCE_TYPES: list[tuple[str, str]] = [
    ("archive", "Архів"),
    ("periodical", "Періодика"),
    ("book", "Книга"),
    ("record", "Документ"),
    ("pdf", "PDF"),
    ("website", "Веб-ресурс"),
    ("oral", "Усне свідчення"),
    ("interview", "Інтерв'ю"),
    ("photo", "Фото"),
    ("gedcom", "GEDCOM"),
]

#: Покоління за роком народження для покажчиків осіб і родин.
GENERATIONS: list[tuple[str, int | None, int | None]] = [
    ("Покоління I — до 1830", None, 1829),
    ("Покоління II — 1830–1869", 1830, 1869),
    ("Покоління III — 1870–1899", 1870, 1899),
    ("Покоління IV — 1900–1929", 1900, 1929),
    ("Покоління V — 1930–1959", 1930, 1959),
    ("Покоління VI — 1960+", 1960, None),
]


@dataclass
class PlaceGroup:
    id: str
    label: str
    match: list[str] = field(default_factory=list)
    color: str = "#7f7f7f"

    def hits(self, admin: list[str] | None) -> bool:
        text = " ".join(admin or []).lower()
        return any(m.lower() in text for m in self.match if m)


OTHER_GROUP = PlaceGroup(id="other", label="Інше")


@dataclass
class SiteConfig:
    title: str = "Родовід"
    description: str = ""
    language: str = "uk"
    search_langs: list[str] = field(default_factory=lambda: ["uk", "ru", "en"])
    born_after: int = 1920
    died_after: int = 2000
    extra_hide: list[str] = field(default_factory=list)
    extra_show: list[str] = field(default_factory=list)
    drop_source_types: list[str] = field(default_factory=lambda: ["oral", "interview", "photo"])
    place_groups: list[PlaceGroup] = field(default_factory=list)
    display_order: list[str] = field(default_factory=list)
    eras: list[dict[str, Any]] = field(default_factory=list)
    extra_css: list[str] = field(default_factory=list)
    nav_before: list[dict[str, str]] = field(default_factory=list)
    nav_after: list[dict[str, str]] = field(default_factory=list)
    #: Тека власних шаблонів (відносно простору), що перекривають пакетні за
    #: іменем файлу. Порожньо — лише шаблони пакета.
    templates: str = ""

    def place_group(self, admin: list[str] | None) -> PlaceGroup:
        """Перша група, чий підрядок є в адмінподілі; інакше «Інше»."""
        return next((g for g in self.place_groups if g.hits(admin)), OTHER_GROUP)

    def ordered_groups(self) -> list[PlaceGroup]:
        by_id = {g.id: g for g in self.place_groups}
        order = [by_id[i] for i in self.display_order if i in by_id]
        order += [g for g in self.place_groups if g not in order]
        return [*order, OTHER_GROUP]


class ConfigError(ValueError):
    """Файл налаштувань не читається — з назвою поля."""


def load(root: Path) -> SiteConfig:
    path = root / CONFIG
    if not path.is_file():
        return SiteConfig()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{CONFIG.as_posix()}: не YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG.as_posix()}: очікувався словник полів")
    groups = [PlaceGroup(**g) for g in data.pop("place_groups", None) or []]
    known = set(SiteConfig.__dataclass_fields__)
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"{CONFIG.as_posix()}: невідомі поля {unknown}; є {sorted(known)}")
    return SiteConfig(place_groups=groups, **data)
