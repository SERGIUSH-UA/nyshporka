"""📰 Друковане видання як книга пулу: ключ `VYD/<код>/<рік>`.

Єпархіальні відомості, месяцеслови, адрес-календарі не мають архівної шифри,
але в пулі живуть поруч зі справами: той самий пакет, той самий `pull`, той
самий `nysh text grep --case`. Одиниця — видання × рік: один номер окремою
книгою дав би тисячі карток, усе видання однією — пакет, якого не взяти по
роках.

🔴 Модуль без залежностей від `share` і `pagestore`: його кличе
`pagestore.resolve_case`, і будь-який імпорт звідти замкнув би коло.

Ключ розбирається в четвірку `repo=VYD, fond=<код>, opys="", spr=<рік>`, тож
сервер пулу, прийом пакета й текстовий стор бачать звичайну книгу й окремої
гілки для видань не потребують.
"""
from __future__ import annotations

import re

#: Код «архіву» для всіх друкованих видань.
REPO = "VYD"

#: Як цей «архів» підписаний на картці.
REPO_NAME = "Друковані видання"

#: Код видання: латинка й цифри, як у шифрі архіву. Рік — чотири цифри.
_KEY_RE = re.compile(r"^VYD\s*[/ ]\s*([A-Za-z][A-Za-z0-9_]{1,23})\s*[/ -]\s*(\d{4})$",
                     re.IGNORECASE)
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,23}$")


def is_code(code: str) -> bool:
    """Чи придатний рядок бути кодом видання (`PEV`, `KHEV`, `ADRKAL`)."""
    return bool(_CODE_RE.match(code or ""))


def key(code: str, year: int | str) -> str:
    """`VYD/PEV/1880`. Код завжди великими: ключ живе в адресах і маніфестах."""
    code = str(code or "").strip()
    y = str(year).strip()
    if not is_code(code):
        raise ValueError(f"код видання «{code}» — лише латинка й цифри, від двох знаків")
    if not (y.isdigit() and len(y) == 4):
        raise ValueError(f"рік видання «{y}» — чотири цифри")
    return f"{REPO}/{code.upper()}/{y}"


def parse(value: str) -> tuple[str, int] | None:
    """`VYD/PEV/1880`, `VYD PEV-1880` → `("PEV", 1880)`; інше — `None`."""
    m = _KEY_RE.match((value or "").strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))
