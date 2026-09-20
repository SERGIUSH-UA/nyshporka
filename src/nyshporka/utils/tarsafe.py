"""🔒 Гард розпакування архіву з чужої машини.

Архів приходить із боксу, який орендували на годину, або з рук іншого
дослідника — підстав довіряти іменам усередині немає в обох випадках. Ім'я
члена tar може вивести запис за межі теки призначення, і тоді «розпакував
декод» означає «дозволив чужому файлу лягти куди завгодно».

🔴 Перевірка ПОКОМПОНЕНТНА, а не `".." in name`. На Windows `Path.joinpath`
розбирає `\\` і `C:` УСЕРЕДИНІ одного POSIX-компонента, тож `out/..\\..\\evil`
проходив фільтр на підрядок і лягав на два рівні вище. Другий рубіж — звірка
вже побудованого шляху з базою: що б не пройшло перший, ціль мусить лишитись
під своєю текою.

🔴 Модуль спільний навмисно. Це виправлення з історією, і друга його копія в
репозиторії означала б, що наступне уточнення полагодить лише один із двох
розпакувальників — причому тихо.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Символи, яких у компоненті імені з чужого архіву бути не може.
BAD_MEMBER_CHARS = frozenset("\\:\x00")


def safe_member_part(part: str) -> bool:
    """Компонент імені з чужого tar, який можна класти на диск як є."""
    if not part or part in (".", "..") or part.strip() != part:
        return False
    return not any(ch in BAD_MEMBER_CHARS for ch in part)


def safe_member_parts(parts: tuple[str, ...] | list[str]) -> bool:
    """Усі компоненти придатні. Порожній перелік — ні: це не шлях."""
    return bool(parts) and all(safe_member_part(p) for p in parts)


def under(dest: Path, base: Path) -> bool:
    """Чи лишається `dest` під `base` після побудови шляху."""
    try:
        return Path(os.path.abspath(dest)).is_relative_to(Path(os.path.abspath(base)))
    except (OSError, ValueError):
        return False
