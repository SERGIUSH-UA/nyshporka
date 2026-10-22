"""🗺 Шляхи простору — функції від активного простору, а не константи модуля.

Клас поломок, який цей тест ловить, не падає — він тихо дивиться не туди.
Константа `ROOT = workspace().root` застигає на просторі, активному в мить
імпорту. Відколи в одному процесі живуть кілька проєктів на спільній
Майстерні, застиглий шлях означає, що демон, перемкнутий на
проєкт B, і далі пише вердикти проєкту A — і нічим цього не видає.

Друга перевірка — склейки `root / "data" / …` поза `core/workspace.py`. Кожна з
них мовчки вирішує, чий це шлях: Майстерні чи проєкту. Вирішувати має одне
місце — властивість `Workspace`. `DEBT` фіксує склейки, що лишились (функції,
які отримують корінь проєкту параметром: канон, сайт, перенос ключів), і має
рухатись ЛИШЕ вниз:

    новий файл    — склейка там, де її не було; це регрес;
    число зросло  — у файл повернулась склейка; це теж регрес;
    число впало   — файл переписали, а рядок у DEBT лишили; онови baseline.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "nyshporka"

#: Де склейка легітимна за призначенням: `core/workspace.py` визначає
#: властивості шляхів; `setup/relocate.py` переносить простір цілком, тобто
#: працює з його розкладкою як такою; `htr/bokovi.py` і `htr/seg.py` клеять
#: `data` до теки прогону, а не простору; `ui` — до теки пакета.
ALLOWED = {"core/workspace.py", "setup/relocate.py", "htr/bokovi.py", "htr/seg.py",
           "ui/__init__.py"}

#: Склейки, що лишились. Кожна — у функції, яка отримує корінь параметром і
#: клеїть до нього шлях свого ж шару: проєктні (канон, сайт, база роду) — від
#: кореня проєкту, хабові (`overrides` і черга в `cases/rekey.py`, кеш
#: сегментації в `htr/runner.py`) — від кореня Майстерні, який туди й
#: передається. Докази резолвляться через `canon/refs.py`.
DEBT: dict[str, int] = {
    "canon/check.py": 2,
    "canon/gedcom.py": 2,
    "cases/rekey.py": 10,
    "htr/runner.py": 1,
    "matching/candidate.py": 2,
    "matching/review.py": 2,
    "migrate/__init__.py": 2,
    "models/region.py": 1,
    "ops_canon.py": 4,
    "ops_site.py": 1,
    "site/build.py": 1,
    "site/public.py": 1,
    "site/render.py": 6,
    "storage/reindex.py": 3,
}

_JOINED = {"data", "reports", "config"}


def _rel(p: Path) -> str:
    return p.relative_to(SRC).as_posix()


def _calls_workspace(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if (isinstance(f, ast.Name) and f.id == "workspace") or (
                    isinstance(f, ast.Attribute) and f.attr == "workspace"):
                return True
    return False


def _import_time(tree: ast.Module) -> list[ast.stmt]:
    """Інструкції, що виконуються при імпорті: тіло модуля й тіла класів,
    з гілками `if`/`try`, але без тіл функцій."""
    out: list[ast.stmt] = []
    todo: list[ast.stmt] = list(tree.body)
    while todo:
        st = todo.pop()
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if st.decorator_list:      # декоратор виконується при імпорті
                out.append(st)
            continue
        if isinstance(st, ast.ClassDef):
            todo += st.body
            continue
        if isinstance(st, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                for child in getattr(st, field, []) or []:
                    todo += child.body if isinstance(child, ast.ExceptHandler) else [child]
            if isinstance(st, ast.If):
                out.append(ast.Expr(st.test))
            continue
        out.append(st)
    return out


@pytest.fixture(scope="module")
def trees() -> dict[str, ast.Module]:
    return {_rel(p): ast.parse(p.read_text(encoding="utf-8"))
            for p in sorted(SRC.rglob("*.py"))}


def test_no_workspace_call_at_import_time(trees):
    """Жоден модуль не питає простір у мить імпорту."""
    bad = []
    for rel, tree in trees.items():
        if rel == "core/workspace.py":
            continue
        for st in _import_time(tree):
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(_calls_workspace(d) for d in st.decorator_list):
                    bad.append(f"{rel}:{st.lineno}")
            elif _calls_workspace(st):
                bad.append(f"{rel}:{st.lineno}")
    assert not bad, (
        "шлях простору застигає при імпорті:\n  " + "\n  ".join(bad)
        + "\n\nЗроби з константи функцію: `def library_path() -> Path: "
          "return workspace().derived / ...`")


@pytest.fixture(scope="module")
def joins(trees) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for rel, tree in trees.items():
        if rel in ALLOWED:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                    and isinstance(node.right, ast.Constant)
                    and node.right.value in _JOINED
                    # дані пакета (`Path(__file__).parent / "data"`) — не простір
                    and "__file__" not in ast.unparse(node.left)):
                out.setdefault(rel, []).append(node.lineno)
    return out


def test_no_new_files_join_workspace_dirs(joins):
    new = {f: v for f, v in joins.items() if f not in DEBT}
    assert not new, (
        "склейка `… / \"data\"` поза `Workspace`:\n"
        + "\n".join(f"  {f}: рядки {v}" for f, v in new.items())
        + "\n\nБери шлях із властивості: `ws.raw`, `ws.derived` (Майстерня) чи "
          "`ws.canonical`, `ws.project_derived` (проєкт).")


def test_join_debt_does_not_grow(joins):
    grown = {f: (len(joins.get(f, [])), n) for f, n in DEBT.items()
             if len(joins.get(f, [])) > n}
    assert not grown, "борг склейок зріс:\n" + "\n".join(
        f"  {f}: було {was}, стало {now}" for f, (now, was) in grown.items())


def test_join_debt_baseline_is_current(joins):
    stale = {f: (len(joins.get(f, [])), n) for f, n in DEBT.items()
             if len(joins.get(f, [])) < n}
    assert not stale, "борг склейок зменшився — онови DEBT:\n" + "\n".join(
        f"  {f}: {'прибери рядок' if now == 0 else f'постав {now}'} (у DEBT {was})"
        for f, (now, was) in stale.items())
