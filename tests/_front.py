"""Фронт як ОДНЕ ціле — для приймачів, які читають його текстом.

🔴 Браузерне обличчя живе не в одному файлі: вхід у `app.js`, спільне ядро в
`core/`, по модулю на екран у `screens/`. Приймач, який читає рівно `app.js`,
після переїзду кнопки в сусідній модуль перестає її бачити — і мовчки
перестає перевіряти. Помітно це стане тоді, коли розірветься саме та ланка,
заради якої приймач писався.

Тому всі текстові перевірки фронту беруть склейку ВСІХ модулів звідси.
"""
from __future__ import annotations

from pathlib import Path

FRONT_DIR = (Path(__file__).resolve().parents[1]
             / "src" / "nyshporka" / "daemon" / "static")


def front_files() -> list[Path]:
    """Усі модулі фронту в стабільному порядку."""
    return sorted(FRONT_DIR.rglob("*.js"))


def front_js() -> str:
    """Склейка всіх модулів фронту одним текстом."""
    return "\n".join(p.read_text(encoding="utf-8") for p in front_files())
