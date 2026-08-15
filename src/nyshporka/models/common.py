from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LangCode = Literal["uk", "ru", "pl", "ro", "en", "de", "yi", "he", "other"]
DatePrecision = Literal["day", "month", "year", "decade", "century"]
DateQualifier = Literal["exact", "about", "before", "after", "between", "estimated", "calculated"]


class GedDate(BaseModel):
    """Дата у генеалогічному форматі. ISO для машинного парсингу, qualifier для семантики."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="ISO-формат: '1968-04-01', '1968-04' або '1968'")
    precision: DatePrecision = "day"
    qualifier: DateQualifier = "exact"
    range_end: str | None = Field(default=None, description="Кінець діапазону для BET..AND")


class NameVariant(BaseModel):
    """Форма імені у конкретній мові/традиції."""

    model_config = ConfigDict(extra="forbid")

    form: str
    lang: LangCode = "uk"
    primary: bool = False
    given: str | None = None
    surname: str | None = None


class MediaRef(BaseModel):
    """Посилання на медіа (фото/документ). sha256 — ключ у MANIFEST.json."""

    model_config = ConfigDict(extra="forbid")

    sha256: str | None = None
    path: str | None = Field(default=None, description="Шлях відносно кореня проєкту.")
    url: str | None = Field(default=None, description="Оригінальний URL (може протухнути).")
    caption: str | None = None
    type: Literal["photo", "document", "other"] = "photo"
