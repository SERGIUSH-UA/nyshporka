"""🪝 Git pre-commit для канону: аркуш замість вирізки й зламана картка не проходять.

Дві перевірки, обидві лише по тому, що йде в коміт:

* **зображення в `data/source/citations/` понад 2 МБ.** Доказ — вирізка рядка;
  аркуш, що раз потрапив в історію git, прибирається лише її перезаписом, тож
  ловити треба ДО коміту;
* **ERROR `canon check` у картках, які комітяться.** Не в усьому каноні: старий
  борг (биті посилання, яких ніхто не торкався) інакше блокував би кожен коміт,
  і хук вимкнули б на другий день.

Встановлення: `nysh canon hook --install` (лише в git-просторі).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nyshporka.canon.evidence import MAX_BYTES

CITATIONS = "data/source/citations/"
CANONICAL = "data/canonical/"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
MARKERS = ("nyshporka canon precommit", "pre_commit_citations")

HOOK = """#!/bin/sh
# встановлено: nysh canon hook --install
root="$(git rev-parse --show-toplevel)"
py="$root/.venv/Scripts/python.exe"
[ -x "$py" ] || py="$root/.venv/bin/python"
[ -x "$py" ] || py=python
exec "$py" -m nyshporka canon precommit
"""


class HookError(RuntimeError):
    """Хук не встановлено — з поясненням."""


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def staged(root: Path, prefix: str) -> list[str]:
    raw = _git(root, "diff", "--cached", "--name-only", "--diff-filter=AMR", "-z", "--", prefix)
    return [n for n in raw.decode("utf-8").split("\0") if n]


def problems(root: Path) -> list[str]:
    out: list[str] = []
    for name in staged(root, CITATIONS):
        if Path(name).suffix.lower() not in IMAGE_EXT:
            continue
        size = int(_git(root, "cat-file", "-s", f":{name}").decode().strip())
        if size > MAX_BYTES:
            out.append(f"{size / 1048576:5.1f} МБ  {name} — це аркуш, а не вирізка рядка "
                       f"(nysh evidence add кладе сірий JPEG до 2 МБ)")
    cards = {Path(n).stem for n in staged(root, CANONICAL) if n.endswith(".md")}
    if cards:
        from nyshporka.canon.check import check

        rep = check(root)
        for issue in rep.issues:
            owner = Path(issue.where).stem if "/" in issue.where else issue.where
            if issue.severity == "ERROR" and owner in cards:
                out.append(f"{issue.where}: {issue.text}")
    return out


def install(root: Path) -> Path:
    try:
        hooks = Path(_git(root, "rev-parse", "--git-path", "hooks").decode().strip())
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise HookError("простір не є git-репозиторієм — хуку нема куди стати") from exc
    hook = (root / hooks) if not hooks.is_absolute() else hooks
    target = hook / "pre-commit"
    if target.exists():
        text = target.read_text(encoding="utf-8", errors="replace")
        if not any(m in text for m in MARKERS):
            raise HookError(f"{target} уже є й не наш — допишіть у нього рядок "
                            f"`python -m nyshporka canon precommit` руками")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HOOK, encoding="utf-8", newline="\n")
    return target


def main(root: Path) -> int:
    found = problems(root)
    if not found:
        return 0
    print("🔴 pre-commit канону:", file=sys.stderr)
    for p in found:
        print(f"   {p}", file=sys.stderr)
    return 1
