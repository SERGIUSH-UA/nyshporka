"""✉️ Спільний конверт відповіді — один формат на браузер, CLI й агента.

Три обличчя дивляться на ті самі дані, і найлегший спосіб їх розсварити — дати
кожному свою форму відповіді. Тоді попередження, яке бачить людина в консолі,
не доходить до агента; агент рапортує «знайдено нуль», не знаючи, що зріз
застарів; і розбіжність виявляється через тиждень.

🔴 Конкретна діра, яку це закриває. У дослідницькому конвеєрі реєстр справ сам
друкує «⚠ реєстр застарів» перед відповіддю — але ЛИШЕ людині: у машинному
режимі попередження не друкується, щоб не псувати вивід. Тобто саме той читач,
який не вміє помітити нічого поза даними, лишався без попередження. Тут воно
стає ПОЛЕМ, і не побачити його неможливо.

    {"ok": true, "v": 1,
     "data": {...},
     "warnings": [{"code": "stale_index", "text": "…"}],
     "stale": {"is": true, "reasons": [...], "fix": "nysh cases build"},
     "next": [{"op": "pages.note", "why": "переглянуто 3 скани, не занесено"}]}

`next` — не прикраса: конвеєр має обов'язкові пари дій («подивився → занеси»),
і забути другу половину легко. Підказка їде разом із відповіддю, а не в
інструкції, яку читають один раз.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA = 1


@dataclass(frozen=True)
class Warning_:
    code: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text}


@dataclass(frozen=True)
class NextStep:
    op: str
    why: str

    def as_dict(self) -> dict[str, str]:
        return {"op": self.op, "why": self.why}


@dataclass(frozen=True)
class Staleness:
    """Чи відповідь спирається на застарілий зріз — і що з цим зробити."""

    is_stale: bool = False
    reasons: tuple[str, ...] = ()
    fix: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"is": self.is_stale, "reasons": list(self.reasons), "fix": self.fix}


@dataclass
class Envelope:
    ok: bool = True
    data: Any = None
    error: str = ""
    warnings: list[Warning_] = field(default_factory=list)
    stale: Staleness | None = None
    next: list[NextStep] = field(default_factory=list)

    def warn(self, code: str, text: str) -> Envelope:
        self.warnings.append(Warning_(code, text))
        return self

    def suggest(self, op: str, why: str) -> Envelope:
        self.next.append(NextStep(op, why))
        return self

    def stale_because(self, reasons: list[str], fix: str = "") -> Envelope:
        """Позначити відповідь як зняту зі старого зрізу.

        Окремий метод, а не присвоєння поля: застарілість мусить потрапляти І в
        структуру, І в текст для агента — а це легко зробити наполовину.
        """
        self.stale = Staleness(is_stale=True, reasons=tuple(reasons), fix=fix)
        return self

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "v": SCHEMA}
        if self.ok:
            out["data"] = self.data
        else:
            out["error"] = self.error
        # 🔴 `warnings` є ЗАВЖДИ, навіть порожній. Поле, яке то з'являється, то
        # зникає, змушує кожного читача писати захисне `.get(...)` — а той, хто
        # напише пряме звертання, зламається не на попередженні, а на його
        # ВІДСУТНОСТІ, тобто на найспокійнішій відповіді. Ціна — три байти.
        out["warnings"] = [w.as_dict() for w in self.warnings]
        if self.stale is not None:
            out["stale"] = self.stale.as_dict()
        if self.next:
            out["next"] = [n.as_dict() for n in self.next]
        return out

    def as_agent_text(self) -> str:
        """Те, що агент мусить ПРОЧИТАТИ, а не лише отримати структурою.

        Дані їдуть окремим полем, а попередження й підказки — текстом: модель
        читає текст надійніше, ніж службові поля, і саме тут ховається різниця
        між «нуль знайдено» і «нуль знайдено, бо зріз застарів».
        """
        lines: list[str] = []
        if self.stale and self.stale.is_stale:
            why = "; ".join(self.stale.reasons) or "невідомо чому"
            fix = f" Полагодити: {self.stale.fix}" if self.stale.fix else ""
            lines.append(f"⚠ ЗРІЗ ЗАСТАРІВ ({why}) — числу нижче вірити не можна.{fix}")
        lines += [f"⚠ {w.text}" for w in self.warnings]
        lines += [f"→ далі: {n.op} — {n.why}" for n in self.next]
        return "\n".join(lines)


def ok(data: Any = None) -> Envelope:
    return Envelope(ok=True, data=data)


def fail(error: str) -> Envelope:
    return Envelope(ok=False, error=error)
