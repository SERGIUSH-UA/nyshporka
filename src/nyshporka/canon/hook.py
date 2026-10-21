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

import re
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
py="{interpreter}"
[ -x "$py" ] || py="$root/.venv/Scripts/python.exe"
[ -x "$py" ] || py="$root/.venv/bin/python"
[ -x "$py" ] || py=python
# Нагадування про міграцію агента в коміті — шум, а не допомога.
NYSHPORKA_NO_MIGRATION_NAG=1 exec "$py" -m nyshporka canon precommit
"""


def hook_script() -> str:
    """Скрипт хука з інтерпретатором, що його ставить.

    🔴 За звичайної установки (`uv tool install`, інсталятор) у просторі немає
    `.venv`, і хук падав на системний `python`, який Нишпорки не імпортує:
    коміт або відмовляв без пояснення, або перевірка канону не робилась
    зовсім. Тека хуків своя на кожній машині (`.git/hooks` не версіонується),
    тож повний шлях тут безпечний.
    """
    return HOOK.replace("{interpreter}", Path(sys.executable).as_posix())


class HookError(RuntimeError):
    """Хук не встановлено — з поясненням."""


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def staged(root: Path, prefix: str, kinds: str = "AMR") -> list[str]:
    raw = _git(root, "diff", "--cached", "--name-only", f"--diff-filter={kinds}", "-z", "--",
               prefix)
    return [n for n in raw.decode("utf-8").split("\0") if n]


def hooks_dir(root: Path) -> Path:
    """Куди git ставить хуки (враховує `core.hooksPath` і worktree)."""
    hooks = Path(_git(root, "rev-parse", "--git-path", "hooks").decode().strip())
    return hooks if hooks.is_absolute() else root / hooks


def canon_roots(root: Path) -> list[tuple[Path, str]]:
    """Проєкти репозиторію і префікс їхнього канону відносно кореня git.

    🔴 Канон живе в кожному проєкті (`projects/<ім'я>/data/canonical/`), а не
    лише в корені. Хук, що дивився тільки на `data/canonical/` кореня, після
    переїзду роду в підтеку мовчки перестав би перевіряти картки — коміт
    проходив би, і зламане посилання ніхто б не побачив.
    """
    from nyshporka.core import projects as P

    out: list[tuple[Path, str]] = []
    for pr in P.list_projects(root, archived=True):
        try:
            rel = pr.root.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        prefix = CANONICAL if rel in ("", ".") else f"{rel}/{CANONICAL}"
        out.append((pr.root, prefix))
    return out


def _check_project(proj: Path, prefix: str, root: Path) -> list[str]:
    cards = {Path(n).stem for n in staged(root, prefix) if n.endswith(".md")}
    # Видалена картка сама помилки не дає — її дають ті, хто на неї посилається.
    gone = {Path(n).stem for n in staged(root, prefix, "D") if n.endswith(".md")}
    if not (cards or gone):
        return []
    from nyshporka.canon.check import check
    from nyshporka.core import workspace as W

    lead = prefix[: -len(CANONICAL)]
    out: list[str] = []
    # Простором самого проєкту: докази він бере з Майстерні, картки — свої.
    with W.using(W._build(proj, "explicit")):
        rep = check(proj)
    for issue in rep.issues:
        if issue.severity != "ERROR":
            continue
        owner = Path(issue.where).stem if "/" in issue.where else issue.where
        if owner in cards or any(re.search(rf"(?<!\w){re.escape(g)}(?!\w)", issue.text)
                                 for g in gone):
            where = f"{lead.rstrip('/')} · {issue.where}" if lead else issue.where
            out.append(f"{where}: {issue.text}")
    return out


def problems(root: Path) -> list[str]:
    out: list[str] = []
    for name in staged(root, CITATIONS):
        if Path(name).suffix.lower() not in IMAGE_EXT:
            continue
        size = int(_git(root, "cat-file", "-s", f":{name}").decode().strip())
        if size > MAX_BYTES:
            out.append(f"{size / 1048576:5.1f} МБ  {name} — це аркуш, а не вирізка рядка "
                       f"(nysh evidence add кладе сірий JPEG до 2 МБ)")
    for proj, prefix in canon_roots(root):
        out += _check_project(proj, prefix, root)
    return out


def install(root: Path) -> Path:
    try:
        target = hooks_dir(root) / "pre-commit"
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise HookError("простір не є git-репозиторієм — хуку нема куди стати") from exc
    if target.exists():
        text = target.read_text(encoding="utf-8", errors="replace")
        if not any(m in text for m in MARKERS):
            raise HookError(f"{target} уже є й не наш — допишіть у нього рядок "
                            f"`python -m nyshporka canon precommit` руками")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(hook_script(), encoding="utf-8", newline="\n")
    return target


def main(root: Path) -> int:
    found = problems(root)
    if not found:
        return 0
    print("🔴 pre-commit канону:", file=sys.stderr)
    for p in found:
        print(f"   {p}", file=sys.stderr)
    return 1
