"""🗣 Як команда віддає відповідь — одним контрактом на всі гілки CLI.

🔴 Модуль існує тому, що друк конверта був скопійований, а не спільний. У
`cli.py` жило п'ять місць, які віддавали машині `env.data` замість
`env.as_dict()`, чотирнадцять дослівних копій «надрукувати помилку й вийти» і
дванадцять циклів друку попереджень у трьох різних форматуваннях. Розійтись
таким копіям нічого не заважало — і вони розійшлись: `warnings` дружні команди
друкували людині й не друкували машині, `stale` читалось в одному місці з
сорока дев'яти, `coverage` не друкувалось ніде, а `next` — узагалі ніде, крім
`nysh op --human`.

⚠ Окремий модуль, а не функція в `cli.py`, бо той самий контракт потрібен
підкомандам (`nysh registry` та іншим), а вони приєднуються до `cli.py` через
`add_typer` — імпорт назад дав би цикл.
"""
from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape

from nyshporka import brand

console = brand.console()


def _plain(text: Any) -> str:
    """Текст із конверта — це ДАНІ, а не розмітка.

    🔴 rich читає квадратні дужки як теги й мовчки викидає те, чого не знає.
    Саме в квадратних дужках у цьому застосунку живе найцінніше: «[нрзб]» у
    прочитанні, «Долищ[…]» в обрізаному прізвищі, «nyshporka[xlsx]» у пораді
    доставити пакет. Спіймано на пораді, з якої зникло рівно те слово, заради
    якого її писали, — і людина побачила команду, що ставить не той пакет.
    """
    return escape(str(text))


def answer(env: Any, as_json: bool = False) -> bool:
    """Єдиний вихід команди. `True` — відповідь уже віддано, тіло не потрібне.

    🔴 Конверт віддається цілим. Доти, доки дружні команди друкували
    `env.data`, машинний читач не бачив ні `warnings`, ні `stale`, ні
    `coverage`, ні `next` — тобто рівно того, заради чого конверт існує. У
    пошуку так гинуло `partial_index` («N прогонів поза пошуком: їхній текст ще
    не проіндексовано») — головний генератор хибного нуля, і саме `--json`
    радять агентові скіли.

    🔴 Помилка теж є відповіддю. Раніше кожна команда друкувала її
    rich-розміткою навіть у машинному режимі: агент діставав розмальований
    текст замість `{"ok": false, "error": ...}` і не мав із чого зрозуміти, що
    сталось, — а код повернення при цьому був той самий, що в решти відмов.
    """
    if as_json:
        console.print_json(data=env.as_dict())
        if not env.ok:
            raise typer.Exit(code=1)
        return True
    if not env.ok:
        console.print(f"[err]{_plain(env.error)}[/err]")
        # Попередження при відмові несуть причину частіше, ніж сам текст
        # помилки: «зріз застарів», «індексу немає», «секцію вимкнено».
        notes(env)
        raise typer.Exit(code=1)
    return False


def notes(env: Any, indent: str = "") -> None:
    """Хвіст відповіді людині: застарілість, попередження, покриття, «що далі».

    🔴 Порядок той самий, що в `Envelope.as_agent_text()`, і це не косметика:
    застарілість мусить стояти перед числами, яких вона стосується, інакше її
    читають уже після того, як повірили числу.
    """
    if env.stale is not None and env.stale.is_stale:
        why = "; ".join(env.stale.reasons)
        console.print(f"{indent}[warn]⚠ зріз застарів[/warn] [muted]({_plain(why)})[/muted]")
        if env.stale.fix:
            console.print(f"{indent}  [muted]полагодити: {_plain(env.stale.fix)}[/muted]")
    for w in env.warnings:
        console.print(f"{indent}[warn]⚠[/warn] [muted]{_plain(w.text)}[/muted]")
    if env.coverage:
        seen = "; ".join(c.human() for c in env.coverage)
        console.print(f"{indent}[muted]🔎 шукали в: {_plain(seen)}[/muted]")
    for n in env.next:
        console.print(f"{indent}[accent]→ далі:[/accent] [muted]{n.op} — {_plain(n.why)}[/muted]")
