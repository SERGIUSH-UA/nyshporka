"""🔴 Усе, з чого складається пакет, мусить бути В GIT.

Це не гігієна репозиторію, а перевірка того, що опублікований пакет узагалі
працює. Локально не видно НІЧОГО: колесо збирається з робочого дерева, тести
теж біжать по робочому дереву, лінт і типи — так само. Клон бачить інше.

Двічі поспіль той самий шаблон:

* `data/` (задумане для сканів дослідника) з'їло `archives/data/archives.yaml` —
  знання про фонди, без якого джерела не знають ані назв, ані ключів;
* `models/` (задумане для ваг, 97 МБ на версію) з'їло `src/nyshporka/models/` —
  ОДИНАДЦЯТЬ файлів моделей даних, тобто ядро пакета. Виявилось аж після
  першого push, на CI: «Cannot find implementation for nyshporka.models».

Тому перевірка загальна: не «ось цей файл на місці», а «жодна тека пакета не
загубилась». Перелічувати відомі випадки тут марно — обидва рази ламалось саме
те, чого в переліку не було.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "nyshporka"


def _tracked() -> set[str]:
    res = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8")
    if res.returncode != 0:
        pytest.skip("не git-репозиторій")
    return {line.strip().replace("\\", "/") for line in res.stdout.splitlines()}


def test_every_python_file_of_the_package_is_tracked() -> None:
    tracked = _tracked()
    missing = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in PKG.rglob("*.py")
        if "__pycache__" not in p.parts
        and str(p.relative_to(ROOT)).replace("\\", "/") not in tracked)
    assert not missing, (
        f"у git немає {len(missing)} файлів пакета: {missing[:8]}\n"
        f"Найімовірніше — шаблон у `.gitignore` без прив'язки до кореня "
        f"(`models/` замість `/models/`). Локально це невидно: і колесо, і "
        f"тести йдуть по робочому дереву, а ламається лише клон.")


def test_every_package_data_file_is_tracked() -> None:
    """Дані пакета — теж код: без них джерела не знають ні фондів, ні паків."""
    tracked = _tracked()
    missing = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in PKG.rglob("*")
        if p.is_file() and p.suffix in {".yaml", ".yml", ".json", ".tsv",
                                        ".html", ".css", ".js", ".svg"}
        and "__pycache__" not in p.parts
        and str(p.relative_to(ROOT)).replace("\\", "/") not in tracked)
    assert not missing, f"дані пакета поза git: {missing[:8]}"


def test_the_wheel_would_carry_the_whole_package() -> None:
    """Кожна тека пакета з кодом має `__init__.py`.

    Без нього тека не є пакетом: `hatchling` покладе її у колесо, а імпорт
    усе одно не знайде — і це знову буде видно лише в клона.
    """
    orphans = sorted(
        str(d.relative_to(ROOT)).replace("\\", "/")
        for d in PKG.rglob("*")
        if d.is_dir() and "__pycache__" not in d.parts
        and any(f.suffix == ".py" for f in d.iterdir() if f.is_file())
        and not (d / "__init__.py").is_file())
    # `htr/patches` — навмисний виняток: ці файли вантажаться ЗА ШЛЯХОМ у
    # чужому інтерпретаторі, а не імпортуються як пакет.
    orphans = [o for o in orphans if not o.endswith("htr/patches")]
    assert not orphans, f"тека з кодом без __init__.py: {orphans}"
