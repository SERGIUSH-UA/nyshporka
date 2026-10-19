"""🔒 Приватна справа — позначка `private` у паспорті (`_source.json`).

Приватне означає «нікуди з машини», а не «не видно з інших проєктів»: між
своїми проєктами справа шукається як будь-яка інша. І це фільтр, а не замок —
рішення дослідника 19.10.2026: автоматика (автовіддача, відкритий сайт)
приватну справу пропускає, а ручна дія, що шле вміст у мережу, відмовляє, доки
автор не скаже явно (`--private-ok`).

Хмарне читання позначка не чіпає: кадри на орендованій карті не публікуються,
бокс знищується після прогону.

🔴 Перевірки читають паспорт наживо, а не колонку реєстру: реєстр старіє, і
справа, позначена хвилину тому, проскочила б у Супрягу за вчорашнім зрізом.
"""
from __future__ import annotations

from pathlib import Path

#: Поле паспорта. Справжнє лише значення `true`: інше — не приватна.
FIELD = "private"

#: Прапорець, яким автор віддає приватну справу свідомо.
OVERRIDE = "--private-ok"


def project_default() -> bool:
    """Чи позначає проєкт свої нові справи приватними (`[project] private_default`)."""
    from nyshporka.core import workspace as W

    ws = W.workspace()
    if ws.project is None:
        return False
    tab = W.read_project_table(ws.root) or {}
    return bool(tab.get("private_default"))


def _dirs_of(key: str) -> list[Path]:
    """Усі теки справи: з бібліотеки (і зайві), і теку паспорта без кадрів."""
    from nyshporka.core.workspace import workspace
    from nyshporka.library import load_library
    from nyshporka.share import align

    out: list[Path] = []
    root = workspace().hub
    try:
        rows = load_library()
    except Exception:
        rows = []
    for row in rows:
        if not align._row_matches(row, key):
            continue
        for rel in [row.get("path"), *(row.get("extra_paths") or [])]:
            if rel:
                p = Path(rel)
                out.append(p if p.is_absolute() else root / p)
    home = align.case_home_for(key)
    if home is not None:
        out.append(home)
    return out


def passport_of(case_dir: Path) -> Path | None:
    """Паспорт теки, якщо вона позначена приватною; інакше `None`."""
    from nyshporka.cases.register import SIDECAR, read_sidecar

    d = Path(case_dir)
    if read_sidecar(d).get(FIELD) is not True:
        return None
    return (d.parent if d.name == "pages" else d) / SIDECAR


def is_private(key: str) -> Path | None:
    """Паспорт, що позначає справу приватною, — або `None`.

    Справа буває кількома теками: приватна, якщо позначена хоч одна.
    """
    key = (key or "").strip()
    if not key:
        return None
    for d in _dirs_of(key):
        got = passport_of(d)
        if got is not None:
            return got
    return None


def refusal(key: str, passport: Path, what: str) -> str:
    """Одне повідомлення на всі ручні дії: що зупинено, чим віддати, як зняти."""
    return (f"справа {key} позначена private у паспорті ({passport}) — {what} не "
            f"робиться без явного рішення. Віддати рішенням автора: {OVERRIDE}; "
            f"зняти позначку: nysh case <тека справи> --public")
