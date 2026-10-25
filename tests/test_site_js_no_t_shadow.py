"""Сайт: локальна змінна `t` не затіняє перекладач `t` з strings.js.

У дереві `const t = svg.transition()` затінило імпорт, і виклик `t('tree.ref')`
посеред `draw()` кидав TypeError: усі картки лишались прозорими, видно було лише
зв'язки. Тест шукає оголошення `t` (const/let/var, параметр функції чи стрілки)
у модулях, що імпортують `t` зі strings.js.
"""
from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "nyshporka" / "site" / "data" / "assets" / "js"

IMPORTS_T = re.compile(r"import\s*\{[^}]*\bt\b[^}]*\}\s*from\s*['\"][^'\"]*strings\.js['\"]")
DECL = re.compile(
    r"\b(?:const|let|var)\s+t\s*[=;,]"
    r"|\b(?:const|let|var)\s*\{[^}]*\bt\b[^}]*\}\s*="
    r"|\bfunction\s*\w*\s*\([^)]*\bt\s*[,)=]"
    r"|\(\s*(?:[^()]*,\s*)?t\s*(?:,[^()]*)?\)\s*=>"
    r"|(?<![\w.])t\s*=>"
)


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|(?<=\s)//\s.*$", "", src)


def test_modules_importing_t_do_not_shadow_it() -> None:
    checked, bad = 0, []
    for p in sorted(JS.rglob("*.js")):
        src = _strip(p.read_text(encoding="utf-8"))
        if not IMPORTS_T.search(src):
            continue
        checked += 1
        for m in DECL.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            bad.append(f"{p.relative_to(JS)}:{line}: {m.group(0).strip()}")
    assert checked >= 4, "модулів з імпортом t не знайдено — зламано сам тест"
    assert not bad, "локальне `t` затіняє перекладач:\n" + "\n".join(bad)


def test_guard_catches_the_original_bug() -> None:
    assert DECL.search("const t = svg.transition().duration(0);")
    assert DECL.search("items.map((t) => t.id)")
    assert not DECL.search("const tr = svg.transition(); const tf = 1;")
