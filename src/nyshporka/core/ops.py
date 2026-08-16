"""⚙️ Реєстр операцій — джерело правди для трьох облич.

Браузерна консоль, командний рядок і агент роблять ті самі речі. Найпростіший
спосіб їх розсварити — описати кожну дію тричі: у роутері, у команді й у
tool'і. Спершу це виглядає як дрібне дублювання, далі одна з трьох копій
відстає, і розбіжність виявляють користувачі.

Ціна такого розходження вже виміряна на попередньому конвеєрі: 157 роутів у
браузері проти 13 скриптів, підключених до нього, — тобто більшість роботи була
доступна лише з командного рядка, і жоден тест цього не бачив.

Тому дія оголошується ОДИН раз:

    @op("workspace.info", summary="Стан робочого простору", args=NoArgs)
    def workspace_info(_: NoArgs) -> Envelope: ...

а CLI, HTTP і MCP будуються з реєстру. Розбіжність між ними стає неможливою не
за домовленістю, а за побудовою — і те, що лишилось поза цим (напр. вибір теки
нативним діалогом), перевіряє `test_triptych_parity`.

🔴 `agent=False` — не «поки не зробили», а рішення. Лабораторні дії (банк
розмітки, синтетика, трен) в агентну поверхню не йдуть НІКОЛИ: інакше перелік
tool'ів росте з кожною фічею, поки модель не перестане його читати. Для такого
в агента є командний рядок.

🔴 `section=` — до якої частини застосунку належить дія (`core.sections`).
Вимкнена в профілі секція відмовляє ТУТ, у `call()`, а не в HTTP-шарі: це
єдиний вхід для CLI, HTTP і MCP, тож інакше три обличчя розійшлися б у тому,
що ввімкнено, — рівно та розбіжність, заради усунення якої реєстр і зроблено.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from nyshporka.core.envelope import Envelope


class NoArgs(BaseModel):
    """Операція без аргументів. Окремий тип, щоб схема була, а не `None`."""


@dataclass(frozen=True)
class Op:
    name: str
    fn: Callable[[Any], Envelope]
    summary: str
    args: type[BaseModel] = NoArgs
    #: Чи доступна агентові. Дивись коментар про `agent=False` у докстрінгу.
    agent: bool = True
    #: Чи показувати в браузері взагалі (незалежно від секцій).
    gui: bool = True
    #: Частина застосунку, яку вимикають профілем. Дефолт `core` — незнімна.
    section: str = "core"
    #: Чи МІНЯЄ стан. Мутації потребують токена, ключа ідемпотентності й
    #: підтвердження в агентній поверхні — тож це не косметична позначка.
    mutates: bool = False
    #: Чи повертає посилання на завдання замість результату (довга робота).
    long: bool = False
    #: Підказки, що робити далі. Пари дій конвеєра легко забути наполовину.
    next_hints: tuple[tuple[str, str], ...] = ()

    @property
    def tool_name(self) -> str:
        """Ім'я для MCP: крапки в іменах tool'ів не всі клієнти люблять."""
        return "nysh_" + self.name.replace(".", "_")

    @property
    def cli_path(self) -> tuple[str, ...]:
        """`workspace.info` → `("workspace", "info")`."""
        return tuple(self.name.split("."))

    def schema(self) -> dict[str, Any]:
        return self.args.model_json_schema()


def _section_refusal(op: Op) -> str | None:
    """Текст відмови, якщо секція операції вимкнена. `None` — можна виконувати.

    🔴 Простір, який не резолвиться, НЕ блокує нічого. Інакше найперша команда
    на щойно розпакованій машині («де я взагалі?») відмовляла б через профіль,
    якого ще немає, — і людина читала б це як поламаний застосунок.
    """
    from nyshporka.core import sections as S

    if op.section in S.required_ids():
        return None
    try:
        from nyshporka.core.workspace import workspace

        active = workspace().sections
    except Exception:
        return None
    if op.section in active:
        return None
    sec = S.get(op.section)
    label = sec.label() if sec else op.section
    return (f"секція «{label}» вимкнена у профілі простору, тож «{op.name}» "
            f"недоступна. Увімкнути: nysh sections enable {op.section}")


@dataclass
class Registry:
    ops: dict[str, Op] = field(default_factory=dict)

    def add(self, op: Op) -> Op:
        if op.name in self.ops:
            raise ValueError(f"операція «{op.name}» вже оголошена")
        self.ops[op.name] = op
        return op

    def get(self, name: str) -> Op | None:
        return self.ops.get(name)

    def all(self) -> list[Op]:
        return [self.ops[k] for k in sorted(self.ops)]

    def for_agent(self) -> list[Op]:
        return [o for o in self.all() if o.agent]

    def for_sections(self, active: Iterable[str]) -> list[Op]:
        """Операції ввімкнених секцій — те, що показує браузер."""
        on = frozenset(active)
        return [o for o in self.all() if o.gui and o.section in on]

    def sections_in_use(self) -> frozenset[str]:
        """Секції, у яких є бодай одна операція.

        Порожня секція не має потрапляти в навігацію: вкладка без вмісту — це
        обіцянка без входу. Рахуємо за реєстром, а не за оголошенням, щоб
        відповідь не розходилась із тим, що справді можна зробити.
        """
        return frozenset(o.section for o in self.ops.values())

    def call(self, name: str, payload: dict[str, Any] | None = None) -> Envelope:
        """Виконати операцію. Валідація аргументів — за схемою, один раз тут.

        Один вхід для всіх трьох облич: інакше CLI, HTTP і MCP перевіряли б
        аргументи по-своєму, і «те саме» приймало б різне.
        """
        op = self.ops.get(name)
        if op is None:
            from nyshporka.core.envelope import fail
            known = ", ".join(sorted(self.ops)) or "(жодної)"
            return fail(f"невідома операція «{name}». Є: {known}")
        from pydantic import ValidationError

        from nyshporka.core.envelope import fail

        off = _section_refusal(op)
        if off is not None:
            return fail(off)
        try:
            args = op.args.model_validate(payload or {})
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ())) or "аргументи"
            return fail(f"{where}: {first.get('msg', 'некоректне значення')}")
        # 🔴 Сітка безпеки, а не косметика. Контракт «операція ЗАВЖДИ повертає
        # конверт» мусить триматись механізмом, бо інакше він тримається
        # пам'яттю автора кожної операції. Реальний випадок: операція чесно
        # ловила свою помилку, але з-під неї пролітала помилка робочого
        # простору — і виклик падав винятком замість «ok: false».
        #
        # Тип винятку лишається у відповіді: проковтнути причину означало б
        # сховати ваду замість того, щоб її показати.
        try:
            env = op.fn(args)
        except Exception as exc:
            return fail(f"{name}: {type(exc).__name__}: {exc}")
        # 💓 Пульс — тут і БІЛЬШЕ НІДЕ. Це єдиний вхід для CLI, HTTP і MCP, тож
        # позначка «дані змінились» не може загубитись через те, що автор нової
        # операції про неї не знав. Умисно ПІСЛЯ виклику й лише на успіху:
        # операція, що впала, нічого не змінила, і бити за неї означало б
        # оголошувати реєстр застарілим без причини.
        if op.mutates and getattr(env, "ok", True):
            try:
                from nyshporka.core import pulse

                pulse.beat(name)
            except Exception:
                pass  # прискорювач; без нього лишається повна перевірка
        for hint_op, why in op.next_hints:
            env.suggest(hint_op, why)
        return env


#: Глобальний реєстр. Один на процес — саме тому, що правда одна.
REGISTRY = Registry()


_OpFn = Callable[[Any], Envelope]


def op(name: str, *, summary: str, args: type[BaseModel] = NoArgs,
       agent: bool = True, gui: bool = True, section: str = "core",
       mutates: bool = False, long: bool = False,
       next_hints: tuple[tuple[str, str], ...] = ()) -> Callable[[_OpFn], _OpFn]:
    """Оголосити операцію.

    🔴 `section` перевіряється ПРИ ОГОЛОШЕННІ, а не при виклику. Помилка друку
    інакше дала б операцію, до якої не дійти жодним обличчям, і побачили б це
    не в тесті, а на чужій машині.
    """
    from nyshporka.core import sections as S

    if section not in S.ids():
        raise ValueError(
            f"операція «{name}»: невідома секція «{section}». "
            f"Є: {', '.join(sorted(S.ids()))}")

    def deco(fn: Callable[[Any], Envelope]) -> Callable[[Any], Envelope]:
        REGISTRY.add(Op(name=name, fn=fn, summary=summary, args=args, agent=agent,
                        gui=gui, section=section, mutates=mutates, long=long,
                        next_hints=next_hints))
        return fn

    return deco
