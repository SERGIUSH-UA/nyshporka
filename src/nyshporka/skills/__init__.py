"""🧰 Скіли агента: знання про порядок роботи, яке вантажиться за потреби.

Пакет дає агентові інструменти (`nysh …`, MCP), але не дає найдорожчого — у
якому ПОРЯДКУ ними користуватись і чим приймати результат. Це знання живе в
`docs/agents/**` і в скілах: скіл вантажиться тоді, коли задача збіглася з його
описом, а не в кожній сесії.

🔴 Джерело правди — `.claude/skills/` у корені репозиторію, тобто рівно та
тека, з якої Claude Code читає скіли, коли працюють НАД САМИМ пакетом.
Розробник редагує те саме, що отримає користувач; розійтись їм ніде. У колесо
каталог їде під `nyshporka/skills/` (`force-include` у `pyproject.toml`).

⚠ Через це шукати скіли доводиться у ДВОХ місцях, і це не фолбек «про всяк
випадок»: у встановленому пакеті вони лежать поруч із цим модулем, у репо —
на два рівні вище, у `.claude/`. Обидва шляхи реальні одночасно (editable
install), і мовчазний вибір «одного правильного» дав би порожній перелік саме
там, де скіли є.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Облік того, що ми поклали й з якої версії. Лежить поруч зі скілами.
LEDGER = ".nysh-skills.json"


@dataclass(frozen=True)
class Skill:
    """Скіл у пакеті: тека з `SKILL.md` і, можливо, `references/`."""

    name: str
    root: Path

    @property
    def card(self) -> Path:
        return self.root / "SKILL.md"

    @property
    def title(self) -> str:
        """Перший рядок опису з frontmatter — щоб перелік щось означав."""
        try:
            text = self.card.read_text(encoding="utf-8")
        except OSError:
            return ""
        for line in text.splitlines():
            if line.startswith("description:"):
                d = line.split(":", 1)[1].strip()
                return d[:100] + ("…" if len(d) > 100 else "")
        return ""

    def files(self) -> list[Path]:
        """Усе, що належить скілу, — картка плюс довідники поруч."""
        return sorted(p for p in self.root.rglob("*") if p.is_file())


def _roots() -> list[Path]:
    """Де шукати скіли — обидва місця, у порядку від встановленого до репо."""
    here = Path(__file__).resolve().parent
    return [here, here.parents[2] / ".claude" / "skills"]


def available() -> list[Skill]:
    """Скіли, які несе цей пакет.

    ⚠ Однойменні не дублюються: перший знайдений виграє, і порядок у `_roots`
    саме тому не випадковий — встановлений пакет важить більше за репозиторій
    поруч.
    """
    out: dict[str, Skill] = {}
    for root in _roots():
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "SKILL.md").is_file() and d.name not in out:
                out[d.name] = Skill(name=d.name, root=d)
    return list(out.values())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger(dest: Path) -> dict[str, str]:
    try:
        data = json.loads((dest / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


@dataclass
class Outcome:
    """Що сталося з одним файлом. Розрізняти обов'язково — див. нижче."""

    #: Куди лягло (відносно `dest`).
    rel: str
    #: `new` · `updated` · `same` · `kept` (правлено руками, не чіпаємо)
    verdict: str


def install(dest: Path, *, version: str, force: bool = False,
            names: tuple[str, ...] = ()) -> list[Outcome]:
    """Покласти скіли в теку, яку читає агент.

    🔴 Правлений руками файл не перезаписується без `force`. Скіл — це текст,
    який дослідник дописує під свій матеріал (свої заміри, свої пастки), і
    мовчазне затирання коштувало б рівно тієї роботи, заради якої скіли й
    заводили. Облік `.nysh-skills.json` тримає sha256 того, що поклали МИ, —
    тож «користувач правив» відрізняється від «копія протухла».

    ⚠ Встановлення НЕ робиться під час `pip install`: пакет, який мовчки пише в
    конфіг агента, — це те, за що пакети викидають. Команда явна.
    """
    dest.mkdir(parents=True, exist_ok=True)
    known = _ledger(dest)
    fresh: dict[str, str] = {}
    out: list[Outcome] = []

    for skill in available():
        if names and skill.name not in names:
            continue
        for src in skill.files():
            rel = f"{skill.name}/{src.relative_to(skill.root).as_posix()}"
            dst = dest / rel
            digest = sha256(src)
            fresh[rel] = digest

            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                out.append(Outcome(rel, "new"))
                continue

            have = sha256(dst)
            if have == digest:
                out.append(Outcome(rel, "same"))
            elif not force and known.get(rel) not in (None, have):
                # Файл відрізняється і від нашого, і від того, що ми клали, —
                # отже його правила людина.
                out.append(Outcome(rel, "kept"))
            elif not force and rel not in known:
                # Ми його ніколи не клали — теж чуже.
                out.append(Outcome(rel, "kept"))
            else:
                shutil.copy2(src, dst)
                out.append(Outcome(rel, "updated"))

    kept = {o.rel for o in out if o.verdict == "kept"}
    (dest / LEDGER).write_text(
        json.dumps({"version": version,
                    "files": {k: v for k, v in fresh.items() if k not in kept}},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    return out
