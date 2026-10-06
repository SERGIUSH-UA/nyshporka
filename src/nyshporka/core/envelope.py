"""✉️ Спільний конверт відповіді — один формат на браузер, CLI й агента.

Три обличчя дивляться на ті самі дані, і найлегший спосіб їх розсварити — дати
кожному свою форму відповіді. Тоді попередження, яке бачить людина в консолі,
не доходить до агента; агент рапортує «знайдено нуль», не знаючи, що зріз
застарів; і розбіжність виявляється через тиждень.

🔴 Конкретна діра, яку це закриває. У дослідницькому конвеєрі реєстр справ сам
друкує «⚠ реєстр застарів» перед відповіддю — але лише людині: у машинному
режимі попередження не друкується, щоб не псувати вивід. Тобто саме той читач,
який не вміє помітити нічого поза даними, лишався без попередження. Тут воно
стає полем, і не побачити його неможливо.

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


#: Рівні попередження для консолі — див. `Warning_`.
ALERT, NOTE, AGENT = "alert", "note", "agent"


@dataclass(frozen=True)
class Warning_:
    """Попередження конверта.

    `level` каже консолі, як показати його ЛЮДИНІ; агент і термінал отримують
    усі однаково. 🔴 Доти рівня не було, і консоль малювала кожну нотатку
    жовтою плашкою: на головному екрані їх стояло сім, серед них — фраза до
    агента («що ти знаєш про Нишпорку») і хибне «читання не запуститься».

        alert   без дії людини щось зламається або висновок буде хибним
        note    облік, знаменник, порада — згорнутим рядком «Примітки»
        agent   лише агентові й терміналу; консоль не показує
    """

    code: str
    text: str
    level: str = NOTE

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text, "level": self.level}


@dataclass(frozen=True)
class NextStep:
    op: str
    why: str
    #: `agent` — порада лише агентові; консоль кнопки не показує.
    level: str = NOTE

    def as_dict(self) -> dict[str, str]:
        return {"op": self.op, "why": self.why, "level": self.level}


@dataclass(frozen=True)
class CoverageItem:
    """ДЕ саме шукали — і якого віку те, в чому шукали.

    🔴 Друга половина правила «нуль мусить щось означати». Перша — відмова
    джерела, яке шукати не може; ця — про джерела, які змогли: «нічого не
    знайдено» без переліку переглянутого не відрізнити від «ніде не шукали», а в
    генеалогії ціна цієї плутанини максимальна — «немає» закриває напрям
    пошуку.

    `taken` — дата зрізу, а не дата збірки: довідник, знятий із сайту архіву
    пів року тому, не стає свіжішим від того, що пак перезібрали вчора.
    """

    source: str
    taken: str = ""
    rows: int = 0
    scope: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "taken": self.taken,
                "rows": self.rows, "scope": self.scope}

    def human(self) -> str:
        bits = [self.source]
        if self.taken:
            bits.append(f"зріз {self.taken}")
        if self.scope:
            bits.append(self.scope)
        return ", ".join(bits)


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
    coverage: list[CoverageItem] = field(default_factory=list)

    def warn(self, code: str, text: str, level: str = "") -> Envelope:
        """Попередження. Рівень за замовчуванням — примітка (`Warning_`).

        Тривогою (`ALERT`) позначати лише те, без чого людина отримає поламку
        чи хибний висновок: кожна зайва тривога вчить не читати жодної.
        """
        self.warnings.append(Warning_(code, text, level or NOTE))
        return self

    def covered_by(self, items: list[CoverageItem]) -> Envelope:
        """Назвати, ДЕ саме шукали.

        Окремий метод, а не присвоєння поля, з тієї самої причини, що й
        `stale_because`: покриття мусить потрапляти І в структуру, І в текст для
        агента — а це легко зробити наполовину, і тоді саме той читач, який не
        помічає нічого поза даними, лишиться без знаменника.
        """
        self.coverage.extend(items)
        return self

    def suggest(self, op: str, why: str, level: str = "") -> Envelope:
        self.next.append(NextStep(op, why, level or NOTE))
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
        # 🔴 `warnings` є завжди, навіть порожній. Поле, яке то з'являється, то
        # зникає, змушує кожного читача писати захисне `.get(...)` — а той, хто
        # напише пряме звертання, зламається не на попередженні, а на його
        # відсутності, тобто на найспокійнішій відповіді. Ціна — три байти.
        out["warnings"] = [w.as_dict() for w in self.warnings]
        if self.stale is not None:
            out["stale"] = self.stale.as_dict()
        if self.next:
            out["next"] = [n.as_dict() for n in self.next]
        # `coverage` — лише там, де воно є: не кожна операція шукає в довідниках,
        # і порожній список у відповіді «завести справу» означав би «ніде не
        # шукали» там, де питання пошуку взагалі не стояло. Це відрізняє його від
        # `warnings`, які осмислені порожніми завжди.
        if self.coverage:
            out["coverage"] = [c.as_dict() for c in self.coverage]
        return out

    def as_agent_text(self) -> str:
        """Те, що агент мусить прочитати, а не лише отримати структурою.

        Дані їдуть окремим полем, а попередження й підказки — текстом: модель
        читає текст надійніше, ніж службові поля, і саме тут ховається різниця
        між «нуль знайдено» і «нуль знайдено, бо зріз застарів».
        """
        lines: list[str] = []
        # 🔴 Відмова — першим рядком. Доти, доки цей метод дивився лише на
        # попередження, найінформативніший режим був найтихішим: `nysh op X
        # --human` на невдалому виклику друкував `null` (бо `data` порожня) і
        # жодного слова про причину, а MCP клав цей текст першим блоком
        # відповіді — тобто агент бачив порожнечу там, де сервер уже пояснив,
        # що саме не так.
        if not self.ok and self.error:
            lines.append(f"⛔ {self.error}")
        if self.stale and self.stale.is_stale:
            why = "; ".join(self.stale.reasons) or "невідомо чому"
            fix = f" Полагодити: {self.stale.fix}" if self.stale.fix else ""
            lines.append(f"⚠ зріз застарів ({why}) — числу нижче вірити не можна.{fix}")
        lines += [f"⚠ {w.text}" for w in self.warnings]
        if self.coverage:
            # 🔴 Текстом, а не лише полем: саме тут «нуль знайдено» перестає
            # означати «ніде не шукали». Без цього рядка агент рапортує порожній
            # результат як негатив, а негатив закриває напрям пошуку.
            lines.append("🔎 шукали в: "
                         + "; ".join(c.human() for c in self.coverage))
        lines += [f"→ далі: {n.op} — {n.why}" for n in self.next]
        return "\n".join(lines)


def ok(data: Any = None) -> Envelope:
    return Envelope(ok=True, data=data)


def fail(error: str) -> Envelope:
    return Envelope(ok=False, error=error)
