"""🧭 Перший запуск: створити простір, не питаючи нічого зайвого.

🔴 Простір НІКОЛИ не створюється мовчки. Тека, що з'явилась сама собі, — це
дослідження, яке потім не можуть знайти: людина шукає свої скани там, де
поклала, а застосунок пише в інше місце. Тому майстер називає шлях і питає
підтвердження, а `--yes` існує лише для інсталятора.

🔴 Дефолт свідомо НЕ в теці синхронізації. `Documents` в багатьох машинах
перенаправлено в OneDrive, а «файли на вимогу» перетворюють обхід справи на
мережеві виклики: 2000 сторінок «зависають» без жодної помилки. Тому дефолт
перевіряється й, якщо він синхронізується, майстер пропонує сусідній шлях.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Ім'я теки простору за замовчуванням. Кирилицею: її бачить людина, а не код.
DEFAULT_DIRNAME = "Нишпорка"

_CLOUD_MARKS = ("onedrive", "dropbox", "google drive", "яндекс", "icloud")


@dataclass(frozen=True)
class Plan:
    """Що майстер збирається зробити. Показується ДО того, як робиться."""

    root: Path
    creating: bool
    warning: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"root": str(self.root), "creating": self.creating,
                "warning": self.warning}


def _is_synced(path: Path) -> bool:
    return any(m in str(path).lower() for m in _CLOUD_MARKS)


def default_root() -> Path:
    """Куди покласти простір, якщо людина не сказала інакше."""
    home = Path.home()
    for candidate in (home / "Documents" / DEFAULT_DIRNAME,
                      home / "Документи" / DEFAULT_DIRNAME,
                      home / DEFAULT_DIRNAME):
        if candidate.parent.is_dir() and not _is_synced(candidate):
            return candidate
    # Усі звичні місця синхронізуються — тоді краще поруч із домівкою, ніж у
    # хмарі: повільний обхід виглядає як зависання, і причину не видно.
    return home / DEFAULT_DIRNAME


def plan(root: str | Path | None = None) -> Plan:
    """Порахувати, що станеться. Нічого не створює."""
    from nyshporka.core.workspace import MARKER, validate_root

    target = Path(root).expanduser() if root else default_root()
    validate_root(target)          # кине WorkspaceError на корені диска чи домівці
    exists = (target / MARKER).is_file()
    warning = ""
    if _is_synced(target):
        warning = ("тека синхронізується з хмарою — обхід справ стане мережевим "
                   "і виглядатиме як зависання")
    elif target.exists() and any(target.iterdir()) and not exists:
        warning = "тека не порожня — простір ляже поруч із наявними файлами"
    return Plan(root=target, creating=not exists, warning=warning)


def create(root: str | Path | None = None, *, name: str = "") -> Path:
    """Створити простір: тека, маркер, кістяк. Ідемпотентно."""
    import tomllib  # noqa: F401  (перевірка, що stdlib має читач TOML)

    from nyshporka.core.workspace import MARKER, use

    target = plan(root).root
    target.mkdir(parents=True, exist_ok=True)
    for sub in ("data/raw", "data/derived", "data/pages", "reports", "config"):
        (target / sub).mkdir(parents=True, exist_ok=True)
    marker = target / MARKER
    if not marker.is_file():
        marker.write_text(
            "# Маркер робочого простору Нишпорки.\n"
            "# Він тут не для краси: саме за цим файлом застосунок і всі\n"
            "# команди знаходять ваше дослідження, підіймаючись від поточної\n"
            "# теки вгору. Переносити простір можна разом із ним.\n"
            "[workspace]\n"
            "schema = 1\n"
            f'name = "{name or target.name}"\n'
            "\n"
            "# Скани, що лежать ПОЗА простором (зовнішній диск, мережева теку):\n"
            "# case_roots = [\"D:/архів\"]\n",
            encoding="utf-8")
    use(target)
    return target
