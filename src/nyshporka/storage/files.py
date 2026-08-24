"""Читання/запис canonical-сутностей як MD з YAML frontmatter.

Перевага MD-з-frontmatter перед чистим JSON/YAML:
- git diff показує осмислені зміни;
- людина може правити .md руками без ризику зламати схему — pydantic при
  читанні валідує і кричить;
- наратив (поле `notes`) — це тіло markdown'а, природний формат.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypeVar

import frontmatter
import yaml
from pydantic import BaseModel

from nyshporka.models import Family, Person, Place, Source
from nyshporka.utils.atomic import atomic_write_text

T = TypeVar("T", bound=BaseModel)


def _yaml_dump(data: dict[str, Any]) -> str:
    """YAML з юнікодом і стабільним порядком ключів."""
    return str(yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ))


def read_entity(path: Path, model: type[T]) -> T:
    """Прочитати .md → pydantic-модель. `notes` береться з тіла."""
    post = frontmatter.load(str(path))
    data = dict(post.metadata)
    data["notes"] = post.content.strip()
    return model.model_validate(data)


def write_entity(path: Path, entity: BaseModel) -> None:
    """Серіалізувати pydantic → .md атомарно. `notes` йде у тіло MD."""
    full = entity.model_dump(mode="json")
    notes = str(full.pop("notes", "") or "")
    post = frontmatter.Post(content=notes, **full)

    # `YAMLHandler` у python-frontmatter не оголошений у `__all__`, хоч і є
    # публічним у документації — звідси позначка, а не обхідний імпорт.
    text = frontmatter.dumps(post, handler=frontmatter.YAMLHandler())  # type: ignore[attr-defined]
    # frontmatter не дає опції allow_unicode напряму — переписуємо YAML-блок самі.
    text = _rewrite_unicode_frontmatter(text, full)
    # tmp тепер із pid і з перечікуванням зайнятого файлу (Windows) — спільна
    # утиліта замість власного `.tmp`, який два процеси перетирали один одному.
    atomic_write_text(path, text)


#: Огорожа frontmatter — САМОСТІЙНИЙ рядок із трьох дефісів, а не будь-яке `---`.
_FM_FENCE = re.compile(r"^---[ \t]*$", re.MULTILINE)


def _rewrite_unicode_frontmatter(text: str, metadata: dict[str, Any]) -> str:
    """Замінити ascii-escaped YAML на юнікодний, зберігши тіло MD.

    🔴 Розріз по РЯДКОВИХ межах, а не `text.split("---", 2)`. Той різав по
    першому входженню трьох дефісів будь-де — включно з серединою YAML-значення
    (заголовок справи, цитата, назва місця цілком законно містять `---`). Тоді
    хвіст YAML-блоку опинявся в тілі, тобто в `notes`, а що `notes` — вільний
    текст, pydantic це приймав: сміття осідало тихо й накопичувалось із кожним
    наступним записом.
    """
    fences = list(_FM_FENCE.finditer(text))
    if len(fences) < 2 or fences[0].start() != 0:
        return text
    body = text[fences[1].end():].lstrip("\n")
    yaml_block = _yaml_dump(metadata)
    return f"---\n{yaml_block}---\n\n{body}".rstrip() + "\n"


# Зручні шорткати по типах ----------------------------------------------------


def read_person(path: Path) -> Person:
    return read_entity(path, Person)


def write_person(path: Path, person: Person) -> None:
    write_entity(path, person)


def read_family(path: Path) -> Family:
    return read_entity(path, Family)


def write_family(path: Path, family: Family) -> None:
    write_entity(path, family)


def read_place(path: Path) -> Place:
    return read_entity(path, Place)


def write_place(path: Path, place: Place) -> None:
    write_entity(path, place)


def read_source(path: Path) -> Source:
    return read_entity(path, Source)


def write_source(path: Path, source: Source) -> None:
    write_entity(path, source)
