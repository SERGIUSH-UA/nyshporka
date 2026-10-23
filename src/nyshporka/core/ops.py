"""⚙️ Реєстр операцій — джерело правди для обох облич.

Браузерна консоль і командний рядок (а через нього й агент) роблять ті самі речі. Найпростіший
спосіб їх розсварити — описати кожну дію двічі: у роутері й у команді.
Спершу це виглядає як дрібне дублювання, далі одна з копій відстає, і розбіжність виявляють користувачі.

Ціна такого розходження вже виміряна на попередньому конвеєрі: 157 роутів у
браузері проти 13 скриптів, підключених до нього, — тобто більшість роботи була
доступна лише з командного рядка, і жоден тест цього не бачив.

Тому дія оголошується один раз:

    @op("workspace.info", summary="Стан робочого простору", args=NoArgs)
    def workspace_info(_: NoArgs) -> Envelope: ...

а CLI і HTTP будуються з реєстру. Розбіжність між ними стає неможливою не
за домовленістю, а за побудовою — і те, що лишилось поза цим (напр. вибір теки
нативним діалогом), перевіряє `test_triptych_parity`.

🔴 `tier=` — рівень для агента. `core` — ядро: карта «ситуація → команда» в
хуку старту (`core.routemap`) і стартовий перелік `nysh ops --agent`.
`situational` — те, що агент знаходить запитом `nysh ops find`, тому `when=`
(коли брати, мовою ситуації) для нього обов'язкове. `rare` — службове, людське,
лабораторне. Рівень нічого не забороняє: `nysh op <ім'я>` дістає будь-яку.
Причина саме такого поділу: повний реєстр — під дві сотні дій, і агент, якому
дали все, не відрізняє важливого (хвиля К багатопроєктності).

🔴 `section=` — до якої частини застосунку належить дія (`core.sections`).
Вимкнена в профілі секція відмовляє тут, у `call()`, а не в HTTP-шарі: це
єдиний вхід для CLI і HTTP, тож інакше обличчя розійшлися б у тому,
що ввімкнено, — рівно та розбіжність, заради усунення якої реєстр і зроблено.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from nyshporka.core.envelope import Envelope

Tier = Literal["core", "situational", "rare"]
Scope = Literal["hub", "project", "mixed"]
TIERS: tuple[str, ...] = ("core", "situational", "rare")
SCOPES: tuple[str, ...] = ("hub", "project", "mixed")


class NoArgs(BaseModel):
    """Операція без аргументів. Окремий тип, щоб схема була, а не `None`."""


@dataclass(frozen=True)
class Op:
    name: str
    fn: Callable[[Any], Envelope]
    summary: str
    args: type[BaseModel] = NoArgs
    #: Чи показувати в браузері взагалі (незалежно від секцій).
    gui: bool = True
    #: Частина застосунку, яку вимикають профілем. Дефолт `core` — незнімна.
    section: str = "core"
    #: Чи міняє стан. Мутації потребують токена, ключа ідемпотентності й
    #: підтвердження в агентній поверхні — тож це не косметична позначка.
    mutates: bool = False
    #: Чи повертає посилання на завдання замість результату (довга робота).
    long: bool = False
    #: Читання, але не публічне: відповідь містить те, чого не має бачити чужа
    #: вкладка, — розкладку диска людини, вміст її тек.
    #:
    #: 🔴 Окреме поле, а не `mutates=True`. Мутація тягне за собою пульс «дані
    #: змінились», напис агентові «змінює стан» і позначку ✎ в командному
    #: рядку — тобто позначити нею читання означало б збрехати в трьох місцях
    #: одразу заради одного побічного ефекту (вимоги токена).
    private: bool = False
    #: Підказки, що робити далі. Пари дій конвеєра легко забути наполовину.
    next_hints: tuple[tuple[str, str], ...] = ()
    #: Рівень для агента: `core` — карта в хуку старту, `situational` —
    #: знаходиться `nysh ops find`, `rare` — службове, людське, лабораторне.
    tier: Tier = "situational"
    #: Коли брати — мовою ситуації, не назвою дії. По ньому шукає `ops find`.
    when: str = ""
    #: Скіл, що веде цю дію (ім'я теки скіла пакета), або порожньо.
    skill: str = ""
    #: Чий шар: Майстерня, проєкт чи обидва (дизайн багатопроєктності, розд. 7).
    scope: Scope = "hub"

    @property
    def agent(self) -> bool:
        """Стартовий перелік (`nysh ops --agent`) — це ядро."""
        return self.tier == "core"

    @property
    def cli_path(self) -> tuple[str, ...]:
        """`workspace.info` → `("workspace", "info")`."""
        return tuple(self.name.split("."))

    def schema(self) -> dict[str, Any]:
        return self.args.model_json_schema()


def _section_refusal(op: Op) -> str | None:
    """Текст відмови, якщо секція операції вимкнена. `None` — можна виконувати.

    🔴 Простір, який не резолвиться, не блокує нічого. Інакше найперша команда
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


def readonly_refusal(name: str, mutates: bool) -> str | None:
    """Відмова змінювати чужий проєкт, відкритий лише для читання (`--project`).

    Спільна для оп реєстру і для команд поза ним (`core.routes`): інакше
    друкована команда, що пише напряму, обходила б межу, яку тримає `call()`.
    """
    if not mutates:
        return None
    try:
        from nyshporka.core.workspace import workspace

        ws = workspace()
    except Exception:
        return None
    if not ws.readonly:
        return None
    return (f"«{name}» змінює дані, а проєкт «{ws.project or ws.name}» відкрито з "
            "іншого проєкту лише для читання. Записувати в нього — з його теки або "
            "з кореня Майстерні")


def _only_shows(args: Any) -> bool:
    """Змінна оп, покликана в режимі «лише показати», — даних не міняє."""
    # `run=False` у `cloud.go` — кошторис без оренди: після нього реєстр
    # «відставав», хоча в просторі нічого не мінялось (22.10.2026).
    return (getattr(args, "show", False) is True
            or getattr(args, "dry_run", False) is True
            or getattr(args, "run", None) is False)


def _readonly_refusal(op: Op) -> str | None:
    return readonly_refusal(op.name, op.mutates)


def _scope_refusal(op: Op) -> str | None:
    """Проєктна оп у чистій Майстерні без проєкту — зрозуміла відмова до тіла.

    Без цього тіло падало `NoProjectError` десь у глибині, і людина в консолі
    бачила виняток про шлях замість «оберіть проєкт».
    """
    if op.scope != "project":
        return None
    try:
        from nyshporka.core.workspace import workspace

        ws = workspace()
    except Exception:
        return None
    if not ws.hub_only or ws.project is not None:
        return None
    return (f"«{op.name}» працює з даними проєкту, а відкрито саму Майстерню. "
            "Оберіть проєкт: у консолі — перемикачем угорі, у терміналі — "
            "`--project <ім'я>` або з теки проєкту")


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

        Один вхід для обох облич: інакше CLI і HTTP перевіряли б
        аргументи по-своєму, і «те саме» приймало б різне.
        """
        op = self.ops.get(name)
        if op is None:
            from nyshporka.core.envelope import fail
            known = ", ".join(sorted(self.ops)) or "(жодної)"
            return fail(f"невідома операція «{name}». Є: {known}")
        from pydantic import ValidationError

        from nyshporka.core.envelope import fail

        off = _section_refusal(op) or _scope_refusal(op) or _readonly_refusal(op)
        if off is not None:
            return fail(off)
        try:
            args = op.args.model_validate(payload or {})
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ())) or "аргументи"
            return fail(f"{where}: {first.get('msg', 'некоректне значення')}")
        # 🔴 Сітка безпеки, а не косметика. Контракт «операція завжди повертає
        # конверт» мусить триматись механізмом, бо інакше він тримається
        # пам'яттю автора кожної операції. Реальний випадок: операція чесно
        # ловила свою помилку, але з-під неї пролітала помилка робочого
        # простору — і виклик падав винятком замість «ok: false».
        #
        # Тип винятку лишається у відповіді: проковтнути причину означало б
        # сховати ваду замість того, щоб її показати.
        try:
            if op.mutates:
                env = op.fn(args)
            else:
                from nyshporka.core.scope import read_scope
                with read_scope():
                    env = op.fn(args)
        except Exception as exc:
            return fail(f"{name}: {type(exc).__name__}: {exc}")
        # 💓 Пульс — тут і більше ніде. Це єдиний вхід для CLI і HTTP, тож
        # позначка «дані змінились» не може загубитись через те, що автор нової
        # операції про неї не знав. Умисно після виклику й лише на успіху:
        # операція, що впала, нічого не змінила, і бити за неї означало б
        # оголошувати реєстр застарілим без причини.
        #
        # Режим «лише показати» (`show`, `dry_run`) нічого не пише, тож і не б'є:
        # шапка консолі читає `share.setup --show` на кожному відкритті сторінки,
        # і реєстр звідси «відставав» одразу після «Оновити» (22.10.2026).
        if op.mutates and getattr(env, "ok", True) and not _only_shows(args):
            try:
                from nyshporka.core import pulse

                pulse.beat(name)
            except Exception:
                pass  # прискорювач; без нього лишається повна перевірка
        # 🔴 Лише на успіху. Статична підказка описує шлях після вдалої дії:
        # на збої `share.publish` радила «перевірити, що пакет знайшовся», і
        # агент ішов шукати пакет, якого немає, замість того, щоб повторити
        # заливку. Що радити після відмови, вирішує сама операція.
        if getattr(env, "ok", True):
            for hint_op, why in op.next_hints:
                env.suggest(hint_op, why)
        return env


#: Глобальний реєстр. Один на процес — саме тому, що правда одна.
REGISTRY = Registry()


_OpFn = Callable[[Any], Envelope]


def op(name: str, *, summary: str, args: type[BaseModel] = NoArgs,
       gui: bool = True, section: str = "core",
       mutates: bool = False, long: bool = False, private: bool = False,
       next_hints: tuple[tuple[str, str], ...] = (),
       tier: Tier = "situational", when: str = "", skill: str = "",
       scope: Scope = "hub") -> Callable[[_OpFn], _OpFn]:
    """Оголосити операцію.

    🔴 `section` перевіряється при оголошенні, а не при виклику. Помилка друку
    інакше дала б операцію, до якої не дійти жодним обличчям, і побачили б це
    не в тесті, а на чужій машині.
    """
    from nyshporka.core import sections as S

    if section not in S.ids():
        raise ValueError(
            f"операція «{name}»: невідома секція «{section}». "
            f"Є: {', '.join(sorted(S.ids()))}")
    if tier not in TIERS:
        raise ValueError(f"операція «{name}»: рівень «{tier}», є {', '.join(TIERS)}")
    if scope not in SCOPES:
        raise ValueError(f"операція «{name}»: шар «{scope}», є {', '.join(SCOPES)}")

    def deco(fn: Callable[[Any], Envelope]) -> Callable[[Any], Envelope]:
        REGISTRY.add(Op(name=name, fn=fn, summary=summary, args=args, gui=gui,
                        section=section, mutates=mutates, long=long,
                        private=private, next_hints=next_hints, tier=tier,
                        when=when, skill=skill, scope=scope))
        return fn

    return deco
