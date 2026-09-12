"""🧰 Скіли агента: знання про порядок роботи, яке вантажиться за потреби.

Пакет дає агентові інструменти (`nysh …`, MCP), але не дає найдорожчого — у
якому порядку ними користуватись і чим приймати результат. Це знання живе в
`docs/agents/**` і в скілах: скіл вантажиться тоді, коли задача збіглася з його
описом, а не в кожній сесії.

🔴 Джерело правди — `.claude/skills/` у корені репозиторію, тобто рівно та
тека, з якої Claude Code читає скіли, коли працюють над самим пакетом.
Розробник редагує те саме, що отримає користувач; розійтись їм ніде. У колесо
каталог їде під `nyshporka/skills/` (`force-include` у `pyproject.toml`).

⚠ Через це шукати скіли доводиться у двох місцях, і це не фолбек «про всяк
випадок»: у встановленому пакеті вони лежать поруч із цим модулем, у репо —
на два рівні вище, у `.claude/`. Обидва шляхи реальні одночасно (editable
install), і мовчазний вибір «одного правильного» дав би порожній перелік саме
там, де скіли є.
"""
from __future__ import annotations

import hashlib
import json
import os
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


def _ledger_version(dest: Path) -> str:
    """З якої версії пакета клали скіли в цю теку. Не клали — порожньо."""
    try:
        data = json.loads((dest / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("version") or "")


def installed() -> list[tuple[Path, str]]:
    """Куди скіли вже клали і з якої версії — щоб `doctor` міг це показати.

    🔴 Оновлення пакета скіли НЕ ЧІПАЄ: вони копіюються разово й лежать у теці
    агента, а не в пакеті. Доти про це не було сказано ніде, і людина з новим
    пакетом працювала за старою карткою — мовчки, бо застарілий скіл виглядає
    точно так само, як свіжий (звіт 05.09.2026).

    ⚠ Дивимось обидва місця, куди кладе `nysh skills install`: теку проєкту й
    теку користувача. Порядок той самий, у якому їх читає агент.
    """
    out: list[tuple[Path, str]] = []
    for dest in (Path.cwd() / ".claude" / "skills",
                 Path.home() / ".claude" / "skills"):
        got = _ledger_version(dest)
        if got:
            out.append((dest, got))
    return out


#: Вимикач синхронізації. Потрібен і людині, і тестам: без нього прогін на
#: машині розробника переписував би його ж власні скіли в `~/.claude/skills`.
ENV_NO_SYNC = "NYSHPORKA_NO_SKILL_SYNC"


def sync(version: str) -> list[tuple[Path, dict[str, int]]]:
    """Перекласти скіли туди, куди їх УЖЕ клали, коли облік старший за пакет.

    🔴 Чому це не робить `nysh update`. Та команда виконує
    `uv tool install --force`, тобто **старий процес замінює сам себе**, а скіли
    він читає з власної теки пакета — у ту мить вона або вже перезаписана, або
    ще ні. Копіювати звідти означало б розкладати невідомо чию версію. Тому
    перекладає НАСТУПНИЙ запуск, уже нової збірки.

    🔴 Три межі, які лишаються від рішення «пакет не пише в конфіг агента
    мовчки»:

    * **тільки наявні теки.** Нових не заводимо: тека, куди людина скіли не
      клала, — не наша;
    * **правлене руками не чіпається.** Облік тримає sha256 того, що поклали
      МИ, тож `install()` віддає такому файлу вердикт `kept` — і ми не
      передаємо `force`;
    * **мовчки не буває.** Викликач друкує підсумок; порожній результат означає,
      що робити не було чого.

    🔴 І лише ВГОРУ. Доти умовою було «облік не дорівнює пакету», тож будь-який
    запуск старшої збірки перекладав скіли назад: `.exe` поруч із `pip`-venv,
    стара копія в іншому середовищі, пробний прогін попередньої версії — і
    агент мовчки працював за карткою, старшою за ту, що вже стояла. Спіймано
    живим прогоном 12.09.2026: `nysh version` з 0.12.2 переписав скіли 0.12.3
    у `~/.claude/skills`, не спитавши й не лишивши сліду, крім рядка в stderr.
    """
    from nyshporka.setup.update import _cmp_key

    out: list[tuple[Path, dict[str, int]]] = []
    if os.environ.get(ENV_NO_SYNC):
        return out
    for dest, was in installed():
        mine, theirs = _cmp_key(version, was)
        if mine <= theirs:
            continue
        try:
            got = install(dest, version=version)
        except OSError:
            continue          # тека зникла або читається лише — не привід падати
        tally: dict[str, int] = {}
        for o in got:
            tally[o.verdict] = tally.get(o.verdict, 0) + 1
        out.append((dest, tally))
    return out


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

    ⚠ Встановлення не робиться під час `pip install`: пакет, який мовчки пише в
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
    # 🔴 Облік ЗЛИВАЄТЬСЯ з попереднім, а не переписується з нуля: при
    # `--only X` у `fresh` лише X, і решта скілів випадала з обліку — далі
    # `sync` бачив їх як «ніколи не клали» й не оновлював уже ніколи.
    files = {k: v for k, v in known.items() if k not in kept}
    files.update({k: v for k, v in fresh.items() if k not in kept})
    from nyshporka.utils.atomic import atomic_write_text

    atomic_write_text(dest / LEDGER,
                      json.dumps({"version": version, "files": files},
                                 ensure_ascii=False, indent=1) + "\n",
                      newline="\n")
    return out
