"""🌳 Розкладка дерева сайту (`assets/js/tree/layout.js`) — інваріанти під Node.

Сам тест — `tests/js/tree_layout.test.mjs` (`node --test`). Тут він лише
вбудований у pytest, щоб ішов у CI разом із рештою, а не руками: розкладку
дерева переписано наново, і накладання карток чи подружжя в різних рядах
інакше ловилися б лише оком на готовому сайті.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_tree_layout_invariants_hold_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node не встановлено")
    run = subprocess.run([node, "--test", str(ROOT / "tests" / "js" / "tree_layout.test.mjs")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=120)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
