"""🧮 Дзеркало підрахунку ядер: раннер і застосунок мусять рахувати однаково.

🔴 Копій дві, бо раннер їде під інтерпретатором рушіїв без пакета. Застосунок
брав їх у раннера — і з ними numpy, якого в установці «Основа» немає: пошук по
стору тексту падав `No module named 'numpy'` (прохід новачка 23.10.2026).
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from nyshporka.core import cpu as C

RUNNER = (Path(__file__).resolve().parent.parent
          / "src" / "nyshporka" / "htr" / "runner.py")


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("_runner_cpu", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def _body(src: str, name: str) -> str:
    """Тіло функції без докстрінга — те, що рахує."""
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == name)
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    return "\n".join(ast.unparse(s) for s in body)


@pytest.mark.parametrize("name", ["cgroup_quota_cores", "usable_cores"])
def test_both_copies_count_the_same_way(name: str) -> None:
    mine = Path(C.__file__).read_text(encoding="utf-8")
    theirs = RUNNER.read_text(encoding="utf-8")
    assert _body(mine, name) == _body(theirs, name), f"{name} розійшовся з раннером"


def test_quota_is_read_the_same(runner, tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("150000 100000", encoding="utf-8")
    assert C.cgroup_quota_cores(tmp_path) == runner.cgroup_quota_cores(tmp_path) == 1.5
    assert C.usable_cores() == runner.usable_cores()


def test_search_store_does_not_need_numpy() -> None:
    """Пошук по стору не імпортує раннер (а з ним numpy) — навіть щоб порахувати ядра."""
    code = ("import sys; sys.modules['numpy'] = None\n"
            "from nyshporka.search import store as ST\n"
            "assert ST._hardware_workers(1.0) >= 1\n"
            "assert 'nyshporka.htr.runner' not in sys.modules\n")
    got = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=120)
    assert got.returncode == 0, got.stderr
