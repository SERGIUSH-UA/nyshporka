"""🔗 Посилання канону на файли: що резолвиться від Майстерні, а що від проєкту.

Картка пише шлях від кореня простору (`data/source/citations/dahmo/x.jpg`,
`data/raw/…`). Поки Майстерня й проєкт були однією текою, корінь був один. Тепер
канон лежить у `projects/<ім'я>/`, а файл доказу один на Майстерню: те саме
посилання з картки проєкту мусить вести в хаб, інакше кожна цитата нового
проєкту «провисне», хоча файл на місці.

🔴 Записані посилання не переписуються. Канон старого простору лишається
байт у байт, а переїзд канону в проєкт (хвиля 5) не мусить чіпати жодної
картки.

Функції беруть корінь проєкту параметром, а не з `workspace()`: канон
перевіряють і будують сайт з явно переданого кореня (тести, хук коміту).
"""
from __future__ import annotations

from pathlib import Path

from nyshporka.core import workspace as W

#: Шари Майстерні, на які посилається канон. `data/source` — лише докази:
#: кореспонденція й нотатки поруч із ними належать проєкту.
HUB_PREFIXES = ("data/source/citations/", "data/raw/")


def project_id(root: Path) -> str | None:
    """Ім'я проєкту теки або `None` — корінь простору (хаб старого типу)."""
    return root.name if W.read_project_table(root) is not None else None


def hub_of(root: Path) -> Path:
    return W._hub_above(root) if project_id(root) is not None else root


def resolve(root: Path, ref: str) -> Path:
    """Файл, на який вказує посилання картки проєкту `root`."""
    norm = ref.replace("\\", "/")
    return (hub_of(root) if norm.startswith(HUB_PREFIXES) else root) / norm


def citations_dir(root: Path) -> Path:
    return W.Workspace(root=hub_of(root)).citations


def owner(root: Path, card_name: str) -> str:
    """Запис `cited_by` маніфесту для картки цього проєкту.

    🔴 Маніфест один на Майстерню, а ID карток у різних проєктах збігаються
    (той самий номер особи є в кожному роді). Тому картка проєкту пишеться з префіксом
    `<проєкт>:`. Корінь старого типу — без префікса, як завжди.
    """
    pid = project_id(root)
    return f"{pid}:{card_name}" if pid else card_name


def owns(root: Path, entry: str) -> bool:
    pid = project_id(root)
    return entry.startswith(f"{pid}:") if pid else ":" not in entry


def own_cited(root: Path, cited_by: list[object]) -> list[str]:
    """Записи `cited_by`, що належать цьому проєкту, без префікса."""
    pid = project_id(root)
    out: list[str] = []
    for x in cited_by:
        if isinstance(x, str) and owns(root, x):
            out.append(x[len(pid) + 1:] if pid else x)
    return out
