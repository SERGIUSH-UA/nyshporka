"""Переносні профілі вичитки: тип книги описується налаштуванням, а не кодом.

Числа, зашиті в модулях поруч, підібрані під ОДИН тип книги — православну
метрику РІ другої половини XIX ст. Костел, сповідка чи ревізька казка мають
іншу геометрію аркуша, інші лічильники й іншу мову, і мовчазне перенесення
«як є» дає тихо зіпсований реєстр. Тому нова книга заводиться новим профілем.

🔴 Два шари, і саме тому їх два. Пакетний `data/profiles.yaml` — типи джерел,
однакові для всіх; `<простір>/config/records_profiles.yaml` — свої профілі й
прив'язки конкретних справ. Простір накладається зверху, тож оновлення пакета
не змиває налаштувань дослідника, а дослідник не мусить правити файл усередині
встановленого пакета, щоб завести свою книгу.

Профіль резолвиться так: явний `--profile` → прив'язка справи в секції `cases`
→ `fallback`. Успадкування через `extends` — однорівневе ланцюжком.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: Типи джерел, що їдуть із пакетом.
PACKAGED = Path(__file__).resolve().parent / "data" / "profiles.yaml"

#: Свої профілі й прив'язки справ — у просторі дослідження.
WORKSPACE_CONFIG = "records_profiles.yaml"


@dataclass(frozen=True)
class Profile:
    """Розв'язаний профіль: секції злиті з defaults і предків."""

    name: str
    title: str = ""
    note: str = ""
    tiles: dict[str, Any] = field(default_factory=dict)
    book: dict[str, Any] = field(default_factory=dict)
    reconstitute: dict[str, Any] = field(default_factory=dict)
    consensus: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "note": self.note,
                "tiles": self.tiles, "book": self.book,
                "reconstitute": self.reconstitute, "consensus": self.consensus}


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(
            out.get(k), dict) else v
    return out


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def workspace_config() -> Path | None:
    """Файл профілів простору — або None, коли простору немає."""
    from nyshporka.core.workspace import WorkspaceError, workspace

    try:
        return workspace().config / WORKSPACE_CONFIG
    except WorkspaceError:
        return None


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    """Пакетні типи джерел + профілі простору зверху.

    🔴 Злиття глибоке, а не заміна файлом: інакше дослідник, який завів ОДИН
    свій профіль, втратив би костел, сповідку й ревізьку казку разом із усіма
    defaults — і виявив би це не помилкою, а тихо іншою нарізкою.
    """
    merged = _read(PACKAGED)
    own = workspace_config()
    if own is not None:
        merged = _deep_merge(merged, _read(own))
    merged.setdefault("defaults", {})
    merged.setdefault("profiles", {})
    merged.setdefault("cases", {})
    merged.setdefault("fallback", "")
    return merged


def reload() -> None:
    """Забути прочитане — після правки файла профілів у просторі."""
    _raw.cache_clear()


def available() -> list[dict[str, Any]]:
    """Перелік профілів для `village profiles`."""
    raw = _raw()
    cases_by_profile: dict[str, list[str]] = {}
    for case, prof in (raw.get("cases") or {}).items():
        cases_by_profile.setdefault(prof, []).append(case)
    return [
        {"name": name, "title": (body or {}).get("title", ""),
         "extends": (body or {}).get("extends", ""),
         "cases": cases_by_profile.get(name, [])}
        for name, body in (raw.get("profiles") or {}).items()
    ]


def resolve_name(explicit: str | None = None,
                 case_key: str | None = None) -> str:
    raw = _raw()
    if explicit:
        return explicit
    if case_key:
        bound = (raw.get("cases") or {}).get(case_key)
        if bound:
            return str(bound)
    fallback = raw.get("fallback")
    if fallback:
        return str(fallback)
    return str(next(iter(raw.get("profiles") or {"": {}}), ""))


def load(explicit: str | None = None, case_key: str | None = None) -> Profile:
    """Розв'язати профіль: defaults → ланцюг extends → сам профіль."""
    raw = _raw()
    profiles = raw.get("profiles") or {}
    name = resolve_name(explicit, case_key)
    if name and name not in profiles:
        raise ValueError(
            f"профілю «{name}» немає; є: {', '.join(profiles) or '—'}. "
            f"Свої профілі кладуться у <простір>/config/{WORKSPACE_CONFIG}")

    chain: list[str] = []
    cur: str | None = name
    while cur and cur in profiles:
        if cur in chain:                       # захист від циклу extends
            break
        chain.append(cur)
        cur = (profiles[cur] or {}).get("extends")

    merged = dict(raw.get("defaults") or {})
    for prof_name in reversed(chain):
        body = dict(profiles[prof_name] or {})
        body.pop("extends", None)
        merged = _deep_merge(merged, body)

    return Profile(
        name=name,
        title=merged.pop("title", ""),
        note=merged.pop("note", ""),
        tiles=merged.get("tiles", {}),
        book=merged.get("book", {}),
        reconstitute=merged.get("reconstitute", {}),
        consensus=merged.get("consensus", {}),
    )
