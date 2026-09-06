"""Гості лабораторії не імпортують пакет — і це перевіряється AST.

Та сама межа, що в `test_htr_runner_isolated`: гість їде під інтерпретатором
середовища рушіїв, де `nyshporka` не встановлено, а лінивий імпорт усередині
функції впав би мовчки в `except Exception` — гілка просто не виконалась би.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

GUEST = Path(__file__).resolve().parent.parent / "src" / "nyshporka" / "train" / "guest"

#: Що є в середовищі рушіїв (дзеркало `test_htr_runner_isolated.ENGINE_ENV`
#: плюс `huggingface_hub` — він потрібен тренеру для бази з хабу).
ENGINE_ENV = {
    "numpy", "PIL", "torch", "torchvision", "kraken", "strhub", "timm",
    "nltk", "lightning", "pytorch_lightning", "rapidfuzz",
    "scipy", "skimage", "shapely", "lxml", "regex", "yaml", "click",
    "coremltools", "threadpoolctl", "huggingface_hub",
}

#: Явний перелік, не `rglob`: новий гість — рішення, яке ухвалюють свідомо.
GUEST_FILES = ["cut_runner.py", "parseq_train_runner.py", "eval_runner.py"]


def test_guest_list_matches_disk() -> None:
    on_disk = {p.name for p in GUEST.glob("*.py") if p.name != "__init__.py"}
    assert on_disk == set(GUEST_FILES), (
        f"у теці гостей є файли поза переліком або бракує оголошених: "
        f"{sorted(on_disk ^ set(GUEST_FILES))}")


@pytest.mark.parametrize("name", GUEST_FILES)
def test_no_package_imports(name: str) -> None:
    src = (GUEST / name).read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = set(sys.stdlib_module_names) | ENGINE_ENV
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in allowed:
                    forbidden.append(a.name)
        elif (isinstance(node, ast.ImportFrom) and node.module
              and node.module.split(".")[0] not in allowed):
            forbidden.append(node.module)
    assert not forbidden, f"{name}: імпортує те, чого в середовищі рушіїв немає: {forbidden}"


def test_vendored_train_runner_carries_the_local_edits() -> None:
    """Правки вендорингу на місці — і всі вони живуть у tools/sync_train_runner.py."""
    src = (GUEST / "parseq_train_runner.py").read_text(encoding="utf-8")
    assert "ВЕНДОРЕНА копія з gpurunner" in src.splitlines()[0]
    for needle in ('params.get("input_root")', 'params.get("no_pip")',
                   'params.get("progress_json")', "@@PROGRESS@@", 'os.name == "nt"',
                   '_p.add_argument("--params"', "def _utc_iso"):
        assert needle in src, f"вендорений раннер без правки: {needle}"
    assert 'EXTRACT = KAGGLE_WORKING / "_input"' in src


def test_cut_runner_has_main_and_takes_runner_by_path() -> None:
    src = (GUEST / "cut_runner.py").read_text(encoding="utf-8")
    assert "def main(" in src and 'if __name__ == "__main__"' in src
    assert "--runner" in src and "--lines-json" in src, (
        "гість мусить вантажити раннер за шляхом і звірятись із .lines.json прогону")
