"""🏛 Пак архівів — знання про фонди як дані.

Правила, які залежать від конкретного архіву чи фонду, довго жили словниками в
коді: скорочення архіву, опис за замовчуванням для сканованих тек, фонди де
опис ОБОВ'ЯЗКОВО входить у ключ справи, губернія за визначенням фонду, теки що
справами не є. Наслідок — новий архів можна було додати лише правкою коду, і
чужий дослідник із власним фондом упирався в це першим.

Тепер джерело одне — `data/archives.yaml`, а код лише читає.

🔴 Що НЕ переїхало в дані й чому. Розбір конкретних каталогів (TSV краулу
ARCHIUM, курованих `CATALOG.md`, покажчика опису ф.315) лишається кодом: це
формат, а не знання. У пак іде декларація «такий каталог існує й лежить отут»,
а як його читати — вирішує парсер. Спроба описати ще й формат перетворила б
YAML на мову програмування.

Пак розширюваний: користувач може підкласти свій файл поверх вбудованого
(`NYSHPORKA_ARCHIVES_PACK` або `<простір>/config/archives.yaml`), і його записи
переб'ють вбудовані по ключу. Саме так додається архів, якого ми не знаємо.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: Вбудований пак — їде разом із кодом.
BUILTIN = Path(__file__).resolve().parent / "data" / "archives.yaml"
#: Ескейп-хетч: шлях до власного паку.
ENV_PACK = "NYSHPORKA_ARCHIVES_PACK"
#: Ім'я файлу, який шукається в конфігу робочого простору.
WORKSPACE_PACK = "archives.yaml"


@dataclass(frozen=True)
class Repository:
    code: str
    label: str
    name: str = ""
    country: str = ""
    note: str = ""


@dataclass(frozen=True)
class Fond:
    repo: str
    fond: str
    name: str = ""
    guberniya: str = ""
    default_opys: str | None = None
    opys_in_key: bool = False
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.repo, self.fond)


@dataclass(frozen=True)
class ArchivesPack:
    repositories: dict[str, Repository] = field(default_factory=dict)
    fonds: dict[tuple[str, str], Fond] = field(default_factory=dict)
    skip_slugs: frozenset[str] = frozenset()
    record_type_labels: dict[str, str] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()

    # ── те, чим користується решта коду ──────────────────────────────────────
    def repo_label(self, repo: str | None) -> str:
        """Скорочення архіву; невідомий код повертається як є.

        Повертати код замість порожнього рядка тут принципово: у шифрі справи
        краще побачити «XYZ 315-1-8433», ніж « 315-1-8433» і гадати, чий він.
        """
        code = str(repo or "")
        r = self.repositories.get(code.upper())
        return r.label if r else code

    def default_opys(self, repo: str | None, fond: str | None) -> str | None:
        """Опис, який мають скановані теки фонду, коли їхнє ім'я його не несе."""
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return f.default_opys if f else None

    def opys_in_key(self, repo: str | None, fond: str | None) -> bool:
        """Чи опис ОБОВ'ЯЗКОВО входить у ключ справи цього фонду."""
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return bool(f and f.opys_in_key)

    def guberniya(self, repo: str | None, fond: str | None) -> str:
        """Губернія, задана самим фондом. Порожньо, якщо фонд не з відомих.

        Запасний варіант: розбір тексту опису сильніший і йде першим. Потрібно
        там, де поле місця порожнє за побудовою — напр. сповідки консисторії
        описані переліком сіл, і зріз «по губернії» без цього недораховує.
        """
        f = self.fonds.get((str(repo or "").upper(), str(fond or "")))
        return f.guberniya if f else ""

    def rtype_label(self, rtype: str | None) -> str:
        return self.record_type_labels.get(str(rtype or ""), str(rtype or ""))

    def is_skipped_slug(self, slug: str) -> bool:
        return slug in self.skip_slugs


# ── читання ──────────────────────────────────────────────────────────────────
def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Верхній пак перебиває нижній ПО КЛЮЧУ, а не заміщає секцію цілком.

    Інакше користувач, який додав один свій архів, мовчки втратив би всі
    вбудовані — і це виглядало б як «програма забула половину фондів».
    """
    out = dict(base)
    out["repositories"] = {**(base.get("repositories") or {}),
                           **(over.get("repositories") or {})}
    out["record_type_labels"] = {**(base.get("record_type_labels") or {}),
                                 **(over.get("record_type_labels") or {})}
    by_key = {(str(f.get("repo", "")).upper(), str(f.get("fond", ""))): f
              for f in (base.get("fonds") or [])}
    for f in over.get("fonds") or []:
        by_key[(str(f.get("repo", "")).upper(), str(f.get("fond", "")))] = f
    out["fonds"] = list(by_key.values())
    out["skip_slugs"] = sorted({*(base.get("skip_slugs") or []),
                                *(over.get("skip_slugs") or [])})
    return out


def _read(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _overlay_paths() -> list[Path]:
    """Де шукати пак користувача, від найявнішого."""
    out: list[Path] = []
    env = os.environ.get(ENV_PACK)
    if env:
        out.append(Path(env))
    try:
        from nyshporka.core.workspace import workspace
        out.append(workspace().config / WORKSPACE_PACK)
    except Exception:  # простір ще не визначено — це не привід падати
        pass
    return [p for p in out if p.is_file()]


def _build(raw: dict[str, Any], sources: tuple[Path, ...]) -> ArchivesPack:
    repos = {}
    for code, body in (raw.get("repositories") or {}).items():
        b = body or {}
        repos[str(code).upper()] = Repository(
            code=str(code).upper(), label=str(b.get("label") or code),
            name=str(b.get("name") or ""), country=str(b.get("country") or ""),
            note=str(b.get("note") or ""))
    fonds = {}
    for body in raw.get("fonds") or []:
        b = body or {}
        f = Fond(
            repo=str(b.get("repo") or "").upper(), fond=str(b.get("fond") or ""),
            name=str(b.get("name") or ""), guberniya=str(b.get("guberniya") or ""),
            default_opys=(str(b["default_opys"]) if b.get("default_opys") is not None
                          else None),
            opys_in_key=bool(b.get("opys_in_key")), note=str(b.get("note") or ""))
        fonds[f.key] = f
    return ArchivesPack(
        repositories=repos, fonds=fonds,
        skip_slugs=frozenset(str(s) for s in (raw.get("skip_slugs") or [])),
        record_type_labels={str(k): str(v) for k, v in
                            (raw.get("record_type_labels") or {}).items()},
        sources=sources,
    )


def load(extra: Path | None = None) -> ArchivesPack:
    """Вбудований пак + накладки користувача (без кешу — для тестів)."""
    raw = _read(BUILTIN)
    used = [BUILTIN]
    for p in [*_overlay_paths(), *( [extra] if extra else [] )]:
        raw = _merge(raw, _read(p))
        used.append(p)
    return _build(raw, tuple(used))


@lru_cache(maxsize=1)
def active() -> ArchivesPack:
    return load()


def reset() -> None:
    active.cache_clear()
