"""🧭 Гіпотеза роду: що не доведено, на чому тримається і що її розв'яже.

Картка `data/canonical/hypotheses/H0001.md`. Факт канону зі статусом
`disputed` посилається на неї полем `hypothesis`, тож у кожного спірного
факту видно, який документ його вирішить.

🔴 Шапка тримає ЧИННИЙ стан, а не історію. Хід міркувань пишеться в тіло
картки або у звіт дослідження. Розв'язаний хіт із `hits` вирізається, бо
список хітів показується людині (`nysh canon next`), і кожен зайвий рядок у ньому
забирає її увагу.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nyshporka.models.citation import Citation

HypothesisStatus = Literal["open", "awaiting", "closed"]
HitStrength = Literal["strong", "weak"]

#: Більше хітів на одну гіпотезу людина не розбирає. Решта лишається у звіті
#: заходу й у журналі пошуку, а сюди йдуть лише ті, від яких щось залежить.
MAX_HITS = 5


class Hit(BaseModel):
    """Кандидат із прочитаного, від вердикту на якого залежить гіпотеза."""

    model_config = ConfigDict(extra="forbid")

    case: str = Field(description="ключ справи, як у сховищі сторінок: REPO/фонд/опис/справа")
    scan: str = Field(description="кадр або скан, як у прогоні: «0082»")
    line: int | None = Field(default=None, description="рядок на скані, якщо відомий")
    reading: str = Field(description="як прочитано — дослівно, з непевними літерами в [ ]")
    strength: HitStrength
    eye: bool = Field(default=False, description="кроп уже дивилися оком")


class Hypothesis(BaseModel):
    """Канонічна модель гіпотези. SoT у data/canonical/hypotheses/{id}.md."""

    model_config = ConfigDict(extra="forbid")

    id: str
    claim: str = Field(description="твердження одним реченням")
    status: HypothesisStatus = Field(
        description="open — шукаємо; awaiting — є хіти, чекає вердикту людини; "
                    "closed — вирішено людиною")
    about: list[str] = Field(default_factory=list, description="I…/F…/PL… — про кого")
    basis: str = Field(default="", description="на чому тримається: скільки незалежних "
                                               "документів, оком чи лише декодом")
    citations: list[Citation] = []
    decides: str = Field(default="", description="який документ, справа чи рядок її розв'яже")
    versus: list[str] = Field(default_factory=list, description="конкурентні гіпотези H…")
    hits: list[Hit] = []
    verdict: str = Field(default="", description="закрита: що вирішено, ким і коли")
    reopen_if: str = Field(default="", description="закрита: який НОВИЙ тип доказу її "
                                                   "відкриває (не повторний замір того самого)")
    updated: date
    notes: str = ""
