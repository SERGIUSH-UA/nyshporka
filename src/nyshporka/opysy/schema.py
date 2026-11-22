"""📐 Схема опису-внеску: маніфест, сторінка, рядок справи.

🔴 Рядок справи впізнається МІСЦЕМ на сторінці джерела, а не номером справи.
Номер у описі читається з помилками і виправляється; ключ, зібраний із номера
(`<опис>/<№>`, як у реєстрі фонду), роздвоює ту саму справу після кожної
правки й зливає дві різні, коли рушій прочитав однаково.

🔴 Джерело — ОПУБЛІКОВАНИЙ файл, а не наша конвертація. Посилання й номер
сторінки мають вести людину туди, де вона сама відкриє скан: djvu на сайті
архіву, PDF на Commons, кадр FamilySearch. Перероблений нами PDF чи розрізані
половинки розвороту — робоча копія, і на неї посилатись не можна; виробник
пакета переводить свої сторінки в сторінки джерела ДО пакування.

Координати — частки сторінки (0..1), тож не залежать від роздільності, з якою
хтось відрендерив той самий файл: хто має скан, вирізає рядок сам.

Поля строгі (`extra="forbid"`): пакет не може понести поле, якого схема не
знає. Так приватне (примітки, шляхи машини) не просочується новим ключем, а
нове поле з'являється лише разом із новим номером схеми.
"""
from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Номер схеми пакета. Піднімається з кожним новим полем.
SCHEMA = 1

SourceKind = Literal["commons", "archive_site", "fs", "private", "public_other"]
NoStatus = Literal["chain", "neighbors", "between", "unconfirmed", "eye"]
QualityClass = Literal["high", "mid", "low"]
#: Форма опису: машинопис; рукопис на друкованому бланку; рукопис на розграфленому
#: рукою аркуші; мішаний; інше (титул, передмова, покажчик).
Form = Literal["typed", "hand_form", "hand_ruled", "mixed", "other"]
#: Мова назв справ в описі. Від неї залежить, чи є словник загальних слів для
#: воріт «нормалізація вигадує» (`names.LEXICONS`).
Language = Literal["ru", "uk", "pl", "ro", "la", "de", "other"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LINK_KEYS = ("{page}", "{i}", "{frame}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Source(_Strict):
    """Опублікований скан опису: файл (PDF, djvu) або набір кадрів (FS, фото)."""

    kind: SourceKind
    #: Адреса файлу чи плівки. Порожня лише в `private` (фото з читальної зали,
    #: куплена зйомка): там посилатись нема куди, і опис іде з позначкою.
    url: str = ""
    #: Шаблон посилання на сторінку, якщо джерело таке вміє. Підстановки:
    #: `{page}` — номер сторінки з 1 (Commons: `…?page={page}`), `{i}` — з 0
    #: (FamilySearch: `…/search/film/<DGS>?i={i}`), `{frame}` — id кадру.
    #: Порожньо — людина відкриває файл і гортає.
    page_link: str = ""
    #: sha256 опублікованого файлу. Для набору кадрів — порожньо, там `frames`.
    sha256: str = ""
    #: Ідентифікатори кадрів по порядку: FS image id або sha256 кожного фото.
    frames: list[str] = Field(default_factory=list)
    #: Сторінок у джерелі (для набору кадрів — кадрів).
    pages: int
    #: Кожна сторінка джерела — розворот із двох книжкових; рядок тоді має `half`.
    spread: bool = False
    #: Ім'я файлу чи том — те, що людина побачить у посиланні.
    label: str = ""

    @field_validator("sha256")
    @classmethod
    def _sha(cls, v: str) -> str:
        v = v.strip().lower()
        if v and not _HEX64.match(v):
            raise ValueError("sha256 — 64 шістнадцяткові знаки")
        return v

    @model_validator(mode="after")
    def _identity(self) -> Source:
        if self.pages < 1:
            raise ValueError("джерело без сторінок")
        if self.frames:
            if len(self.frames) != self.pages:
                raise ValueError(f"кадрів {len(self.frames)}, а сторінок {self.pages}")
            if len(set(self.frames)) != len(self.frames):
                raise ValueError("той самий кадр двічі")
        elif not self.sha256:
            raise ValueError("файлове джерело без sha256 (а набір кадрів — без frames)")
        if self.kind != "private" and not self.url:
            raise ValueError(f"джерело «{self.kind}» без адреси; немає адреси — це private")
        for what, val in (("url", self.url), ("page_link", self.page_link)):
            if val and not val.startswith(("https://", "http://")):
                raise ValueError(f"{what} — не веб-адреса: людина не відкриє «{val[:60]}»")
        if self.page_link and not any(k in self.page_link for k in _LINK_KEYS):
            raise ValueError("page_link без {page}, {i} чи {frame}")
        if "{frame}" in self.page_link and not self.frames:
            raise ValueError("page_link з {frame}, а кадрів немає")
        return self

    def ident(self, page: int) -> str:
        """Що саме однозначно називає сторінку: файл+сторінка або сам кадр."""
        if self.frames:
            return "f:" + self.frames[page - 1]
        return f"s:{self.sha256}:{page}"

    def link(self, page: int) -> str:
        """Посилання на сторінку, якщо джерело його дає; інакше — на файл."""
        if not self.page_link:
            return self.url
        out = self.page_link.replace("{page}", str(page)).replace("{i}", str(page - 1))
        if self.frames:
            out = out.replace("{frame}", self.frames[page - 1])
        return out


class Region(_Strict):
    """Шматок сторінки джерела, на якому стоїть рядок (рядок буває на двох).

    `half` — лише там, де виробник читав розворот навпіл. Таблиця, складена
    по цілому розвороту (машинопис PaddleOCR-VL), чи ціла сторінка — без `half`.
    """

    src: int = 0
    page: int
    #: Половина розвороту: 0 — ліва, 1 — права; None — сторінка не розворот.
    half: int | None = None
    y0: float
    y1: float
    x0: float = 0.0
    x1: float = 1.0

    @model_validator(mode="after")
    def _box(self) -> Region:
        if self.page < 1:
            raise ValueError("сторінка рахується з 1")
        if self.half not in (None, 0, 1):
            raise ValueError("half — 0, 1 або порожньо")
        for a, b, what in ((self.y0, self.y1, "y"), (self.x0, self.x1, "x")):
            if not (0.0 <= a < b <= 1.0):
                raise ValueError(f"{what}: потрібно 0 ≤ {what}0 < {what}1 ≤ 1, маємо {a}..{b}")
        return self


class Page(_Strict):
    """Прочитаний текст сторінки (половини розвороту) — усіма голосами.

    Сторінка є і без розібраних рядків: титул, передмова, сторінка, де
    таблиця не склалась. Пошук іде по тексті кожної сторінки, тож покриття
    текстом — перше число опису, а таблиця справ — друге.
    """

    src: int = 0
    page: int
    half: int | None = None
    #: Голос (рушій/модель) → текст сторінки.
    voices: dict[str, str] = Field(default_factory=dict)
    #: Рушій пройшов сторінку й не знайшов письма (порожній аркуш, обкладинка).
    blank: bool = False


class Row(_Strict):
    """Справа з опису: номер, назва, роки — і де саме вона стоїть.

    `rk` — позиційний ключ (`row_key`). 🔴 З пакета його не беруть на віру:
    обидва кінці рахують заново й звіряють.
    """

    rk: str = ""
    regions: list[Region] = Field(default_factory=list)
    #: Номер, як його прочитав рушій (сирий), і розібраний.
    no_raw: str = ""
    no: int | None = None
    letter: str = ""
    #: Чим підтверджено номер: ланцюгом, сусідами, між якорями, оком; або ніяк.
    no_status: NoStatus = "unconfirmed"
    title_raw: str
    #: Назва після нормалізації (шаблон `norm_prompt.md`); сира лишається завжди.
    title_norm: str = ""
    years: str = ""
    year_from: int | None = None
    year_to: int | None = None
    folios: str = ""
    #: Колонка «кінчилось»/«кінцева дата», якщо опис її має.
    end: str = ""


class Quality(_Strict):
    """Клас якості читання — з того, що відомо без людського еталону (його в таких описів нема)."""

    klass: QualityClass
    #: Обов'язкова: від неї залежить, чи може клас бути `high` (рукопис — ні).
    form: Form
    ocr_conf_median: float | None = None
    note: str = ""


class Normalization(_Strict):
    prompt: str
    version: str
    model: str


class Partial(_Strict):
    """Явно неповний опис: чому і яких сторінок немає (`src:page[:half]`)."""

    why: str
    missing: list[str] = Field(default_factory=list)


class Manifest(_Strict):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    kind: Literal["opys"] = "opys"
    repo: str
    fond: str
    opys: str
    #: Том чи частина опису («т. 2», «ч. 1»), якщо опис багатотомний.
    volume: str = ""
    #: Назва з титулу опису (фонд, установа), як написано.
    title: str = ""
    #: Мова назв справ (обов'язкова: від неї залежить суворість воріт назв).
    language: Language
    years: str = ""
    sources: list[Source] = Field(min_length=1)
    #: Рушії й моделі, що читали (без них текст не оцінити).
    engines: list[str] = Field(default_factory=list)
    quality: Quality
    normalization: Normalization | None = None
    license: str = ""
    partial: Partial | None = None
    #: Хто зібрав пакет: інструмент і версія.
    tool: str = ""

    @field_validator("repo", "fond", "opys")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("порожньо")
        return v


def row_key(sources: list[Source], row: Row) -> str:
    """Позиційний ключ рядка за ПЕРШИМ шматком: джерело, сторінка, половина, висота.

    Порожній рядок без шматків ключа не має (воротам — відмова за прив'язкою).
    """
    if not row.regions:
        return ""
    r = row.regions[0]
    if not (0 <= r.src < len(sources)) or not (1 <= r.page <= sources[r.src].pages):
        return ""
    ident = sources[r.src].ident(r.page)
    half = "" if r.half is None else str(r.half)
    raw = f"{ident}|{half}|{r.y0:.3f}|{r.y1:.3f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def page_ref(src: int, page: int, half: int | None = None) -> str:
    """Запис сторінки для переліків (`partial.missing`, звіти): `src:page[:half]`."""
    return f"{src}:{page}" + ("" if half is None else f":{half}")
