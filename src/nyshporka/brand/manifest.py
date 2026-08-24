"""🐾 Айдентика — розбір `brand.yaml`.

Тут лише читання й питання до маніфесту: ні кольорів у коді, ні генерації
файлів. CSS збирає `brand.css`, тему командного рядка — `brand.console`, і
обидва беруть дані звідси, тож розійтися їм ніде.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).resolve().parent / "data"
BUILTIN = DATA / "brand.yaml"
ASSETS = DATA / "assets"

#: Теми, у яких існує кожен колір. Порядок значущий: світла — базова, темна
#: приходить із системної налаштованості й лише ПЕРЕвизначає токени.
THEMES = ("light", "dark")


@dataclass(frozen=True)
class Color:
    """Колір палітри в обох темах.

    `css` — ім'я змінної у фронті (`--bg`). Воно коротке, бо його набирають у
    верстці руками; семантичне ім'я (`paper`) лишається в `id`.
    """

    id: str
    css: str
    why: str
    light: str
    dark: str

    def value(self, theme: str = "light") -> str:
        return self.dark if theme == "dark" else self.light


@dataclass(frozen=True)
class Mark:
    """Позначка з єдиного словника — та сама, що в шапці `AGENTS.md`."""

    id: str
    glyph: str
    uk: str
    en: str

    def text(self, lang: str = "uk") -> str:
        return self.en if lang == "en" else self.uk


@dataclass(frozen=True)
class EngineStyle:
    """Візуальна ознака рушія читання.

    🔴 Ознак ТРИ — колір, форма, літера, — і кожна працює сама. Вивід читають
    у чорно-білому терміналі, у логах і з дальтонізмом; якби носієм був самий
    колір, у половині випадків рушій став би невідрізнимим від сусіднього.
    """

    id: str
    order: int
    letter_uk: str
    letter_en: str
    shape: str          # circle | diamond | notched
    hue_uk: str
    light: str
    dark: str
    role_uk: str
    role_en: str

    def value(self, theme: str = "light") -> str:
        return self.dark if theme == "dark" else self.light

    def letter(self, lang: str = "uk") -> str:
        return self.letter_en if lang == "en" else self.letter_uk

    def role(self, lang: str = "uk") -> str:
        return self.role_en if lang == "en" else self.role_uk


@dataclass(frozen=True)
class Brand:
    name_uk: str
    name_en: str
    line_uk: str
    line_en: str
    mascot: str
    mark_shape: str
    palette: tuple[Color, ...]
    type_text: str
    type_mono: str
    type_size: str
    type_leading: str
    marks: tuple[Mark, ...]
    engines: tuple[EngineStyle, ...]
    section_glyphs: dict[str, str]
    screen_glyphs: dict[str, str]

    # ── питання до маніфесту ─────────────────────────────────────────────────
    def name(self, lang: str = "uk") -> str:
        return self.name_en if lang == "en" else self.name_uk

    def line(self, lang: str = "uk") -> str:
        return self.line_en if lang == "en" else self.line_uk

    def color(self, cid: str) -> Color:
        for c in self.palette:
            if c.id == cid:
                return c
        raise KeyError(f"немає кольору «{cid}» — перелік у brand.yaml")

    def mark(self, mid: str) -> Mark:
        for m in self.marks:
            if m.id == mid:
                return m
        raise KeyError(f"немає позначки «{mid}» — перелік у brand.yaml")

    def engine(self, eid: str) -> EngineStyle | None:
        """Стиль рушія або порожньо.

        🔴 Порожньо, а не виняток: перелік рушіїв росте в `engines.yaml`, і
        новий рушій не має валити застосунок через відсутню картинку. Що
        обидві множини збігаються, стежить тест — там ціна помилки лише в
        неоформленому бейджі, а не в тому, що не відкрився екран.
        """
        for e in self.engines:
            if e.id == eid:
                return e
        return None

    def engines_ordered(self) -> tuple[EngineStyle, ...]:
        return tuple(sorted(self.engines, key=lambda e: e.order))

    def section_glyph(self, sid: str) -> str:
        return self.section_glyphs.get(sid, "")

    def screen_glyph(self, screen: str) -> str:
        return self.screen_glyphs.get(screen, "")

    def css_vars(self, theme: str = "light") -> dict[str, str]:
        """Токени однієї теми: ім'я змінної → значення, разом із рушіями."""
        out = {c.css: c.value(theme) for c in self.palette}
        out.update({f"engine-{e.id}": e.value(theme) for e in self.engines_ordered()})
        return out


def _build(raw: dict[str, Any]) -> Brand:
    ident = raw.get("identity") or {}
    typ = raw.get("type") or {}
    return Brand(
        name_uk=str(ident.get("name_uk") or ""),
        name_en=str(ident.get("name_en") or ""),
        line_uk=str(ident.get("line_uk") or ""),
        line_en=str(ident.get("line_en") or ""),
        mascot=str(ident.get("mascot") or ""),
        mark_shape=str(ident.get("mark") or ""),
        palette=tuple(Color(
            id=str(c.get("id") or ""), css=str(c.get("css") or ""),
            why=str(c.get("why") or ""), light=str(c.get("light") or ""),
            dark=str(c.get("dark") or ""))
            for c in (raw.get("palette") or [])),
        type_text=str(typ.get("text") or ""),
        type_mono=str(typ.get("mono") or ""),
        type_size=str(typ.get("base_size") or ""),
        type_leading=str(typ.get("line_height") or ""),
        marks=tuple(Mark(
            id=str(m.get("id") or ""), glyph=str(m.get("glyph") or ""),
            uk=str(m.get("uk") or ""), en=str(m.get("en") or ""))
            for m in (raw.get("marks") or [])),
        engines=tuple(EngineStyle(
            id=str(e.get("id") or ""), order=int(e.get("order") or 0),
            letter_uk=str(e.get("letter_uk") or ""),
            letter_en=str(e.get("letter_en") or ""),
            shape=str(e.get("shape") or ""), hue_uk=str(e.get("hue_uk") or ""),
            light=str(e.get("light") or ""), dark=str(e.get("dark") or ""),
            role_uk=str(e.get("role_uk") or ""), role_en=str(e.get("role_en") or ""))
            for e in (raw.get("engines") or [])),
        section_glyphs={str(k): str(v)
                        for k, v in (raw.get("section_glyphs") or {}).items()},
        screen_glyphs={str(k): str(v)
                       for k, v in (raw.get("screen_glyphs") or {}).items()},
    )


def load(path: Path | None = None) -> Brand:
    src = path or BUILTIN
    return _build(yaml.safe_load(src.read_text(encoding="utf-8")) or {})


@lru_cache(maxsize=1)
def active() -> Brand:
    return load()


def asset(name: str) -> Path:
    """Шлях до асета за іменем файлу.

    ⚠ Існування НЕ перевіряється тут — це зробив би кожен виклик дорожчим і
    все одно не сказав би, чи асет потрапив у колесо. Перелік згаданих і
    наявних асетів звіряє тест.
    """
    return ASSETS / name
