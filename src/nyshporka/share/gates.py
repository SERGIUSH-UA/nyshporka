"""🚦 Ворота пакета: що не пускаємо в обмін і чому саме.

Ворота стоять на ОБОХ кінцях і це навмисно. Пакувальник не збирає брак —
так він не доїжджає до пулу взагалі; приймач проганяє ті самі перевірки ще
раз — бо пакет міг зібрати не той пакувальник, і чужому «все гаразд» вірити
підстав немає.

🔴 Що саме вони бережуть: не охайність, а ЗНАМЕННИК. Декод на три сторінки,
розданий як прочитана справа на три тисячі, не просто марний — він виробляє
хибні нулі оптом. Людина грепне його, не знайде прізвища й закриє напрям,
зробивши все правильно й отримавши неправду. Усі інші ворота другорядні щодо
цього одного.

🔴 Причина відмови завжди НАЗВАНА поштучно. Спільне «пакет не пройшов
перевірку» змушує вгадувати, що виправляти, і найчастіше закінчується тим, що
людина здається — а декод у неї насправді добрий.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nyshporka.share.bundle import Manifest

#: Нижче цієї частки прочитаних кадрів пакет вважається уривком, і йому
#: потрібне явне пояснення (`--partial`), інакше знаменник бреше.
MIN_COVERAGE = 0.20

#: Понад стільки порожніх рядків — прогін радше не прочитався, ніж прочитав
#: порожні аркуші. Заміряно на справах, де рушій не взяв письмо взагалі.
MAX_BLANK_FRAC = 0.80

#: Коротший рядок за це — не текст, а сміття сегментації.
MIN_LINE_CHARS = 5


@dataclass
class Verdict:
    """Підсумок воріт: пускати чи ні, і що саме сказати людині."""

    refusals: list[str] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.refusals

    def refuse(self, why: str) -> None:
        self.refusals.append(why)

    def warn(self, code: str, why: str) -> None:
        self.warnings.append((code, why))

    def as_json(self) -> dict[str, Any]:
        return {"passed": self.passed, "refusals": list(self.refusals),
                "warnings": [{"code": c, "text": t} for c, t in self.warnings]}


def check(manifest: Manifest, *, partial_why: str = "") -> Verdict:
    """Проганяє пакет крізь усі ворота. `partial_why` знімає ворота знаменника."""
    v = Verdict()
    _gate_denominator(manifest, v, partial_why=partial_why)
    _gate_model(manifest, v)
    _gate_emptiness(manifest, v)
    _gate_identity(manifest, v)
    _gate_license(manifest, v)
    _gate_payload(manifest, v)
    return v


def _gate_denominator(m: Manifest, v: Verdict, *, partial_why: str) -> None:
    """Скільки кадрів має справа й скільки з них прочитано."""
    if not m.decode:
        v.refuse("у маніфесті немає блоку `decode` — пакет не називає, скільки "
                 "прочитано; без цього чужий нуль нічого не означає")
        return
    pages = m.pages
    if pages <= 0:
        v.refuse("у пакеті нуль прочитаних сторінок — нема чого передавати")
        return
    frames = m.frames_total
    if frames <= 0:
        v.warn("frames_unknown",
               "кадрів справи не названо, тож покриття не порахувати: "
               "отримувач не зможе відрізнити повний декод від уривка")
        return
    frac = pages / frames
    if frac < MIN_COVERAGE and not partial_why:
        v.refuse(
            f"прочитано {pages} сторінок із {frames} кадрів ({frac:.0%}) — це "
            f"уривок, а розданий без застереження він читається як прочитана "
            f"справа. Пояснити й пустити: --partial \"чому саме стільки\"")
    elif frac < 1.0:
        v.warn("partial",
               f"прочитано {pages} з {frames} кадрів ({frac:.0%})"
               + (f"; причина: {partial_why}" if partial_why else ""))


def _gate_model(m: Manifest, v: Verdict) -> None:
    """Чим читали. Без цього декод неможливо ні відтворити, ні оцінити."""
    voices = m.voices
    if not voices:
        v.refuse("у маніфесті немає жодного голосу — невідомо, що саме в пакеті")
        return
    unnamed = [x.get("run") or "?" for x in voices if not str(x.get("model") or "").strip()]
    if unnamed:
        v.refuse(f"прогін без назви моделі: {', '.join(unnamed)}. Модель — це не "
                 f"підпис, а єдиний спосіб зрозуміти, чому текст саме такий")
    if not str(m.case.get("shifra") or "").strip():
        v.refuse("пакет без шифри справи — його нема куди покласти в отримувача")


def _gate_emptiness(m: Manifest, v: Verdict) -> None:
    """Чи є в пакеті власне текст."""
    lines = int(m.decode.get("lines") or 0)
    chars = int(m.decode.get("chars") or 0)
    if lines <= 0:
        v.refuse("у пакеті нуль рядків тексту")
        return
    if chars / lines < MIN_LINE_CHARS:
        v.refuse(f"середній рядок — {chars / lines:.1f} символа: це не текст, а "
                 f"сміття сегментації. Перечитати справу перед тим, як ділитись")
    blank = int(m.decode.get("blank_pages") or 0)
    if m.pages and blank / m.pages > MAX_BLANK_FRAC:
        v.refuse(f"порожніх сторінок {blank} із {m.pages} — рушій радше не взяв "
                 f"письмо, ніж прочитав порожні аркуші")


def _gate_identity(m: Manifest, v: Verdict) -> None:
    """Чи впізнає отримувач цю справу."""
    if not m.refs:
        v.warn("no_refs",
               "пакет не називає джерела сканів. Шифра лишається, але звірити "
               "знахідку з зображенням отримувачу буде нікуди піти — варто "
               "додати: --link \"звідки скани=<адреса>\"")
    if not m.frames.get("total"):
        v.warn("no_frames",
               "переліку кадрів немає, тож прив'язати текст до чужої зйомки "
               "не вийде: сторінки лишаться номерами")


def _gate_license(m: Manifest, v: Verdict) -> None:
    if not str(m.license.get("text") or "").strip():
        v.refuse("не вказано ліцензію тексту. Без неї отримувач не знає, що з "
                 "цим можна робити: --license CC0-1.0")


def _gate_payload(m: Manifest, v: Verdict) -> None:
    """Сліди чужої машини, які не мали пережити пакування."""
    from nyshporka.share.bundle import META_STRIPPED

    leaked = [k for k in META_STRIPPED if k in m.decode or k in m.case]
    if leaked:
        v.refuse(f"у маніфесті лишились поля машини, на якій читали: "
                 f"{', '.join(leaked)}")


def describe(v: Verdict) -> str:
    """Вердикт одним абзацом — для командного рядка."""
    if v.passed and not v.warnings:
        return "ворота пройдено"
    rows = [f"✗ {r}" for r in v.refusals] + [f"⚠ {t}" for _, t in v.warnings]
    return "\n".join(rows)
