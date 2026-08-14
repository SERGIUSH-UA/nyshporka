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
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from nyshporka.core.envelope import Envelope

#: Хто бачить операцію в браузері: усі, лише в режимі експерта, ніхто.
GuiVisibility = Literal[True, False, "expert"]


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
    gui: GuiVisibility = True
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

    def for_gui(self, *, expert: bool = False) -> list[Op]:
        return [o for o in self.all()
                if o.gui is True or (expert and o.gui == "expert")]

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
        for hint_op, why in op.next_hints:
            env.suggest(hint_op, why)
        return env


#: Глобальний реєстр. Один на процес — саме тому, що правда одна.
REGISTRY = Registry()


_OpFn = Callable[[Any], Envelope]


def op(name: str, *, summary: str, args: type[BaseModel] = NoArgs,
       agent: bool = True, gui: GuiVisibility = True, mutates: bool = False,
       long: bool = False,
       next_hints: tuple[tuple[str, str], ...] = ()) -> Callable[[_OpFn], _OpFn]:
    """Оголосити операцію."""

    def deco(fn: Callable[[Any], Envelope]) -> Callable[[Any], Envelope]:
        REGISTRY.add(Op(name=name, fn=fn, summary=summary, args=args, agent=agent,
                        gui=gui, mutates=mutates, long=long, next_hints=next_hints))
        return fn

    return deco
