"""🐾 Айдентика — розбір `brand.yaml`.

Тут лише читання й питання до маніфесту: ні кольорів у коді, ні генерації
файлів. CSS збирає `brand.gen`, тему командного рядка — `brand.console`, і
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

#: Теми, у яких існує кожен колір.
#:
#: ⚠ Порядок тут — просто перелік; яка з них БАЗОВА, каже `Brand.theme_default`.
#: Довго базовою була світла, і темна лише перевизначала токени; тепер навпаки.
#: Код, який виводив би це з порядку кортежу, зламався б тихо — саме тому
#: відповідь лежить окремим полем, а не в цій сталій.
THEMES = ("light", "dark")


@dataclass(frozen=True)
class Color:
    """Токен у обох темах.

    `css` — ім'я змінної у фронті (`--bg`, `--s-3`). Воно коротке, бо його
    набирають у верстці руками; що воно означає, каже `why`.

    🔴 `same` — не «забули другу тему», а рішення. Такий токен однаковий в
    обох темах, і кожен випадок пояснений у `brand.yaml`: чорнило на кольоровій
    заливці не світлішає разом зі сторінкою, а рамка знайденого лежить НА
    фотографії, куди тема не сягає взагалі.
    """

    css: str
    why: str
    dark: str
    light: str
    same: bool = False

    def value(self, theme: str = "light") -> str:
        return self.dark if theme == "dark" else self.light


@dataclass(frozen=True)
class Group:
    """Смислова група токенів — вона ж секція згенерованого CSS.

    🔴 `title` і `why` — ДАНІ, а не коментарі YAML. Коментар `safe_load`
    викидає, тож пояснення не доїхало б у згенерований CSS, і той вийшов би
    голим списком чисел — гіршим за файл, з якого його зібрано. А читає його
    той, хто верстає: саме там доречно знати, що яруси в темах ідуть у
    протилежні боки.
    """

    id: str
    title: str
    why: str
    colors: tuple[Color, ...]


@dataclass(frozen=True)
class Alias:
    """Друге ім'я того самого токена.

    🔴 Не другий колір. `--card` каже, ЩО це («підкладка картки»), `--s-3` —
    ЯКИЙ це щабель ярусу поверхонь. Завести їм окремі значення означало б те
    саме тихе розходження, від якого заведено весь цей файл, тож у CSS аліас
    виходить посиланням (`--card: var(--s-3)`), а не копією.
    """

    css: str
    of: str
    why: str


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
    #: Яку тему видно без вибору користувача.
    theme_default: str
    groups: tuple[Group, ...]
    aliases: tuple[Alias, ...]
    #: Токени, значення яких кольором не є (стрілка `<select>` як data-URI).
    controls: tuple[Color, ...]
    radii: tuple[Color, ...]
    shadows: tuple[Color, ...]
    motion: tuple[Color, ...]
    type_text: str
    type_mono: str
    type_size: str
    type_leading: str
    marks: tuple[Mark, ...]
    engines: tuple[EngineStyle, ...]
    section_glyphs: dict[str, str]
    screen_glyphs: dict[str, str]
    section_icons: dict[str, str]
    screen_icons: dict[str, str]

    # ── питання до маніфесту ─────────────────────────────────────────────────
    def name(self, lang: str = "uk") -> str:
        return self.name_en if lang == "en" else self.name_uk

    def line(self, lang: str = "uk") -> str:
        return self.line_en if lang == "en" else self.line_uk

    @property
    def palette(self) -> tuple[Color, ...]:
        """Усі кольорові токени підряд, поза групами."""
        return tuple(c for g in self.groups for c in g.colors)

    def color(self, css: str) -> Color:
        for c in self.palette:
            if c.css == css:
                return c
        raise KeyError(f"немає токена «{css}» — перелік у brand.yaml")

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

    def section_icon(self, sid: str) -> str:
        return self.section_icons.get(sid, "")

    def screen_icon(self, screen: str) -> str:
        return self.screen_icons.get(screen, "")

    def css_vars(self, theme: str = "light") -> dict[str, str]:
        """Усі кольорові токени однієї теми: ім'я змінної → ЗНАЧЕННЯ.

        ⚠ Аліаси тут РЕЗОЛВЛЯТЬСЯ у значення, хоч у CSS вони виходять
        посиланням. Споживачі цього словника — тема командного рядка й
        вимірювач контрасту, а вони працюють із числами: `var(--s-3)` для rich
        не колір, а рядок, який він мовчки покаже як текст.
        """
        out = {c.css: c.value(theme) for c in self.palette}
        out.update({f"engine-{e.id}": e.value(theme) for e in self.engines_ordered()})
        for a in self.aliases:
            out[a.css] = out[a.of]
        return out

    def non_colour(self) -> tuple[Color, ...]:
        """Токени, значення яких кольором не є — у порядку виводу в CSS."""
        return self.controls + self.radii + self.shadows + self.motion


def _colour(raw: dict[str, Any]) -> Color:
    """Один токен.

    Одне значення на обидві теми приходить двома способами, і обидва законні:
    явним `same: true` (колір, який навмисно не перевертається) і просто
    відсутністю тем (радіус, тривалість, крива — вони від світла не залежать).
    """
    css, why = str(raw.get("css") or ""), str(raw.get("why") or "")
    if raw.get("same") or ("value" in raw and "dark" not in raw):
        v = str(raw.get("value") or "")
        return Color(css=css, why=why, dark=v, light=v, same=True)
    return Color(css=css, why=why,
                 dark=str(raw.get("dark") or ""), light=str(raw.get("light") or ""))


def _colours(rows: Any) -> tuple[Color, ...]:
    return tuple(_colour(r) for r in (rows or []))


def _build(raw: dict[str, Any]) -> Brand:
    ident = raw.get("identity") or {}
    typ = raw.get("type") or {}
    glyphs = lambda key: {str(k): str(v) for k, v in (raw.get(key) or {}).items()}
    return Brand(
        name_uk=str(ident.get("name_uk") or ""),
        name_en=str(ident.get("name_en") or ""),
        line_uk=str(ident.get("line_uk") or ""),
        line_en=str(ident.get("line_en") or ""),
        mascot=str(ident.get("mascot") or ""),
        mark_shape=str(ident.get("mark") or ""),
        theme_default=str(raw.get("theme_default") or "dark"),
        groups=tuple(Group(id=str(g.get("group") or ""),
                           title=str(g.get("title") or ""),
                           why=str(g.get("why") or "").rstrip(),
                           colors=_colours(g.get("colors")))
                     for g in (raw.get("palette") or [])),
        aliases=tuple(Alias(css=str(a.get("css") or ""), of=str(a.get("of") or ""),
                            why=str(a.get("why") or ""))
                      for a in (raw.get("aliases") or [])),
        controls=_colours(raw.get("controls")),
        radii=_colours(raw.get("radii")),
        shadows=_colours(raw.get("shadows")),
        motion=_colours(raw.get("motion")),
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
        section_glyphs=glyphs("section_glyphs"),
        screen_glyphs=glyphs("screen_glyphs"),
        section_icons=glyphs("section_icons"),
        screen_icons=glyphs("screen_icons"),
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
