"""🚩 Функції, що вже лежать у пакеті, але ще не відкриті людям.

Код іде в реліз раніше, ніж функція готова: так він проходить ту саму збірку,
ті самі тести й ту саму установку, що й решта. Флаг вирішує лише одне — чи
бачить людина точку входу: команду `nysh`, операцію (`nysh ops`, MCP,
браузер), скіл.

🔴 Флаг стоїть на ТОЧКАХ ВХОДУ, а не на бібліотеці. Модулі функції (`nyshporka.opysy.*`)
імпортуються й працюють і з вимкненим флагом: їх тягне сервер Супряги (спільні
ворота) і тести. Вимкнений флаг = функції не видно, а не «модуль падає».

🔴 Флаг клієнта — не замок. Пакет публічний, змінну може виставити будь-хто,
тож справжню межу тримає сервер своїм вимикачем. Флаг клієнта лише не показує
напівготове тим, хто його не шукав.

Читається зі змінної оточення в момент виклику, бо обидві точки входу
(`cli.py` і реєстр операцій) збираються при імпорті — ще до того, як відомо,
у якому просторі працюємо.
"""
from __future__ import annotations

import os

#: Описи фондів як друга сутність Супряги (архітектура 22.11.2026). Запущено в 0.49.0 («Засіки»):
#: увімкнено за замовчуванням, `NYSH_OPYSY=0` ховає.
OPYSY = "NYSH_OPYSY"
_TRUE = frozenset({"1", "true", "yes", "on", "так"})
_FALSE = frozenset({"0", "false", "no", "off", "ні"})
#: Флаги, що діють без змінної: функцію запущено, змінна лише вимикає.
DEFAULT_ON = frozenset({OPYSY})

#: Що саме ховає кожен флаг: групи `nysh` і операції поіменно. Тести «кожна
#: порада веде на команду», «CLI кличе наявну операцію» без флагу пропускають
#: рівно ці імена — відсутні навмисно, а не через описку. Поіменно, а не
#: префіксом, щоб описка в імені операції функції за флагом теж ловилась.
HIDDEN: dict[str, dict[str, tuple[str, ...]]] = {
    OPYSY: {"cli": ("opys",), "ops": ("opysy.api_stan", "opysy.build", "opysy.check",
                                      "opysy.dzherelo", "opysy.init",
                                      "opysy.meta", "opysy.names", "opysy.norm", "opysy.norm_api", "opysy.obmin", "opysy.pack", "opysy.pages", "opysy.policy",
                                      "opysy.push", "opysy.read", "opysy.rule_add", "opysy.rule_undo",
                                      "opysy.rules", "opysy.search", "opysy.table", "opysy.viddaty",
                                      "opysy.vziaty")},
}


def enabled(env_name: str) -> bool:
    """Чи ввімкнено флаг. Порожнє значення — як за замовчуванням (`DEFAULT_ON`); запущений флаг
    вимикає лише явне «0/false/no/off/ні», незапущений вмикає лише явне «1/true/yes/on/так»."""
    v = os.environ.get(env_name, "").strip().lower()
    if env_name in DEFAULT_ON:
        return v not in _FALSE
    return v in _TRUE


def opysy() -> bool:
    """Описи фондів: команди `nysh opys …` і операції `opysy.*`."""
    return enabled(OPYSY)


def hidden_now(kind: str) -> set[str]:
    """Імена (`cli` — групи `nysh`, `ops` — операції), сховані вимкненими флагами."""
    return {name for flag, what in HIDDEN.items() if not enabled(flag)
            for name in what.get(kind, ())}
